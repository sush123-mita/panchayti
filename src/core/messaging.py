"""
messaging.py — Message model, broker, and channel history.

Message types
-------------
  text      — a user-sent chat message
  system    — local informational message (not sent over the wire)
  presence  — status update (online / away / busy)
  handshake — key-exchange packet (handled in network.py)
  ack       — future: delivery acknowledgement

Wire format for a text message
-------------------------------
Encrypted payload (JSON inside AES-GCM):
    {"content": "Hello!", "channel": "general"}

Outer envelope (sent over TCP):
    {
      "type":        "text",
      "id":          "<uuid>",
      "sender_id":   "<uuid>",
      "sender_name": "Alice",
      "channel":     "general",          # repeated outside for routing
      "timestamp":   "2024-01-01T12:00:00.000",
      "ciphertext":  "<base64>",
      "nonce":       "<base64>"
    }
"""

import datetime
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional


# ------------------------------------------------------------------ #
#  Message                                                             #
# ------------------------------------------------------------------ #

@dataclass
class Message:
    id:          str
    type:        str           # "text" | "system" | "presence" | ...
    sender_id:   str
    sender_name: str
    channel:     str
    timestamp:   str
    content:     str = ""

    # Populated only in the encrypted wire form
    ciphertext: Optional[str] = None
    nonce:      Optional[str] = None

    # ---- Factory helpers ------------------------------------------ #

    @staticmethod
    def text(sender_id: str, sender_name: str, channel: str, content: str) -> "Message":
        return Message(
            id          = str(uuid.uuid4()),
            type        = "text",
            sender_id   = sender_id,
            sender_name = sender_name,
            channel     = channel,
            timestamp   = _now(),
            content     = content,
        )

    @staticmethod
    def system(content: str) -> "Message":
        return Message(
            id          = str(uuid.uuid4()),
            type        = "system",
            sender_id   = "system",
            sender_name = "System",
            channel     = "*",
            timestamp   = _now(),
            content     = content,
        )

    # ---- Serialisation -------------------------------------------- #

    def to_wire(self) -> dict:
        """Return a dict suitable for JSON-over-the-wire."""
        d: dict = {
            "id":          self.id,
            "type":        self.type,
            "sender_id":   self.sender_id,
            "sender_name": self.sender_name,
            "channel":     self.channel,
            "timestamp":   self.timestamp,
        }
        if self.ciphertext:
            d["ciphertext"] = self.ciphertext
            d["nonce"]      = self.nonce
        else:
            d["content"] = self.content
        return d

    @staticmethod
    def from_wire(d: dict) -> "Message":
        return Message(
            id          = d.get("id",          str(uuid.uuid4())),
            type        = d.get("type",        "text"),
            sender_id   = d.get("sender_id",   "unknown"),
            sender_name = d.get("sender_name", "Unknown"),
            channel     = d.get("channel",     "general"),
            timestamp   = d.get("timestamp",   _now()),
            content     = d.get("content",     ""),
            ciphertext  = d.get("ciphertext"),
            nonce       = d.get("nonce"),
        )


# ------------------------------------------------------------------ #
#  MessageBroker                                                       #
# ------------------------------------------------------------------ #

class MessageBroker:
    """
    Central hub for messages:
      - Prepares outgoing messages (encrypts for a target peer).
      - Processes incoming messages (decrypts, validates).
      - Stores per-channel history.
      - Notifies registered listeners on every new message.

    Extension point: add persistent storage (SQLite) by replacing
    store_message() with a DB write.
    """

    def __init__(self, encryption, peer_registry):
        self._enc   = encryption
        self._peers = peer_registry

        # channel  →  [Message, ...]
        self._history: dict[str, List[Message]] = {}
        self._hist_lock = threading.Lock()

        # Registered UI callbacks: fn(message: Message)
        self._listeners: List[Callable[[Message], None]] = []

    # ---- Listener registration ------------------------------------ #

    def on_message(self, callback: Callable[["Message"], None]):
        """Register a function to be called whenever a new message arrives."""
        self._listeners.append(callback)

    # ---- History -------------------------------------------------- #

    def store_message(self, message: Message):
        """Persist message in memory and notify listeners."""
        with self._hist_lock:
            self._history.setdefault(message.channel, []).append(message)
        for cb in self._listeners:
            try:
                cb(message)
            except Exception:
                pass

    def get_history(self, channel: str, limit: int = 200) -> List[Message]:
        with self._hist_lock:
            return list(self._history.get(channel, []))[-limit:]

    # ---- Outgoing ------------------------------------------------- #

    def prepare_outgoing(self, peer_id: str, message: Message) -> dict:
        """
        Build the wire-format dict for a message going to peer_id.
        Encrypts the content if an ECDH session exists.
        """
        if self._enc.has_session(peer_id):
            # Encrypt only the sensitive payload
            inner = json.dumps({"content": message.content, "channel": message.channel})
            enc   = self._enc.encrypt(peer_id, inner)

            wire            = message.to_wire()
            wire.pop("content", None)       # remove plaintext
            wire["ciphertext"] = enc["ciphertext"]
            wire["nonce"]      = enc["nonce"]
            return wire
        else:
            # Fallback: send in the clear (should not happen after handshake)
            return message.to_wire()

    # ---- Incoming ------------------------------------------------- #

    def process_incoming(self, peer_id: str, data: dict) -> Optional[Message]:
        """
        Decrypt and parse an incoming wire-format dict.
        Returns None if processing fails.
        """
        try:
            msg = Message.from_wire(data)

            if data.get("ciphertext") and self._enc.has_session(peer_id):
                raw   = self._enc.decrypt(peer_id, data["ciphertext"], data["nonce"])
                inner = json.loads(raw)
                msg.content = inner.get("content", "")
                msg.channel = inner.get("channel", msg.channel)

            return msg

        except Exception as e:
            from src.utils.logger import get_logger
            get_logger("messaging").error(f"Failed to process message from {peer_id}: {e}")
            return None


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="milliseconds")
