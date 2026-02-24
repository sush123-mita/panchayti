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

import base64
import datetime
import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


# ------------------------------------------------------------------ #
#  Message                                                             #
# ------------------------------------------------------------------ #

@dataclass
class Message:
    id:          str
    type:        str           # "text" | "system" | "presence" | "file" | ...
    sender_id:   str
    sender_name: str
    channel:     str
    timestamp:   str
    content:     str = ""

    # Populated only in the encrypted wire form
    ciphertext: Optional[str] = None
    nonce:      Optional[str] = None

    # File transfer fields (type == "file")
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None     # MIME type, e.g. "image/png"
    file_path: Optional[str] = None     # local path after saving to disk

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

    @staticmethod
    def file(sender_id: str, sender_name: str, channel: str,
             file_name: str, file_size: int, file_type: str,
             content: str, file_path: Optional[str] = None) -> "Message":
        """Create a file transfer message. *content* is base64-encoded file data."""
        return Message(
            id          = str(uuid.uuid4()),
            type        = "file",
            sender_id   = sender_id,
            sender_name = sender_name,
            channel     = channel,
            timestamp   = _now(),
            content     = content,
            file_name   = file_name,
            file_size   = file_size,
            file_type   = file_type,
            file_path   = file_path,
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
        # File metadata travels in the clear alongside encrypted content
        if self.file_name:
            d["file_name"] = self.file_name
            d["file_size"] = self.file_size
            d["file_type"] = self.file_type
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
            file_name   = d.get("file_name"),
            file_size   = d.get("file_size"),
            file_type   = d.get("file_type"),
        )


# ------------------------------------------------------------------ #
#  MessageBroker                                                       #
# ------------------------------------------------------------------ #

class MessageBroker:
    """
    Central hub for messages:
      - Prepares outgoing messages (encrypts for a target peer).
      - Processes incoming messages (decrypts, validates).
      - Stores per-channel history (in-memory cache + JSON file).
      - Saves received file data to ~/.localdiscord/files/.
      - Notifies registered listeners on every new message.
    """

    FILES_DIR = Path.home() / ".localdiscord" / "files"

    def __init__(self, encryption, peer_registry, storage=None):
        self._enc     = encryption
        self._peers   = peer_registry
        self._storage = storage   # StorageManager (optional for backwards compat)

        # channel  →  [Message, ...]   (in-memory cache, also the read-through layer)
        self._history: dict[str, List[Message]] = {}
        self._hist_lock = threading.Lock()

        # Registered UI callbacks: fn(message: Message)
        self._listeners: List[Callable[[Message], None]] = []

        # Ensure files directory exists
        self.FILES_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Listener registration ------------------------------------ #

    def on_message(self, callback: Callable[["Message"], None]):
        """Register a function to be called whenever a new message arrives."""
        self._listeners.append(callback)

    # ---- History -------------------------------------------------- #

    def store_message(self, message: Message):
        """Persist message in memory + JSON file, then notify listeners."""
        # For received file messages: decode base64 → save to disk
        if message.type == "file" and message.content and not message.file_path:
            message.file_path = self._save_file(message)
            message.content = ""  # free the base64 blob from memory

        with self._hist_lock:
            self._history.setdefault(message.channel, []).append(message)

        # Persist to JSON file (non-blocking — queued to writer thread)
        if self._storage and message.type in ("text", "file"):
            record = {
                "id":          message.id,
                "type":        message.type,
                "sender_id":   message.sender_id,
                "sender_name": message.sender_name,
                "channel":     message.channel,
                "timestamp":   message.timestamp,
                "content":     message.content if message.type == "text" else "",
            }
            if message.type == "file":
                record["file_name"] = message.file_name
                record["file_size"] = message.file_size
                record["file_type"] = message.file_type
                record["file_path"] = message.file_path
            self._storage.write_message(record)

        for cb in self._listeners:
            try:
                cb(message)
            except Exception as e:
                from src.utils.logger import get_logger
                get_logger("messaging").error(f"Listener callback failed: {e}")

    def get_history(self, channel: str, limit: int = 200) -> List[Message]:
        """Return history from in-memory cache (populated from DB on load)."""
        with self._hist_lock:
            return list(self._history.get(channel, []))[-limit:]

    def load_history_from_db(self, channel: str, limit: int = 200):
        """
        Load messages from JSON file into the in-memory cache.
        Called once per channel on startup or first view.
        """
        if not self._storage:
            return
        rows = self._storage.get_history(channel, limit)
        with self._hist_lock:
            if channel in self._history:
                existing_ids = {m.id for m in self._history[channel]}
                for row in rows:
                    if row["id"] not in existing_ids:
                        self._history.setdefault(channel, []).insert(0,
                            _msg_from_row(row))
                self._history[channel].sort(key=lambda m: m.timestamp)
            else:
                self._history[channel] = [_msg_from_row(r) for r in rows]

    def get_dm_channels(self) -> List[str]:
        """Return all DM channel IDs that have stored messages."""
        if not self._storage:
            return []
        return self._storage.get_dm_channels()

    # ---- File I/O ------------------------------------------------- #

    def _save_file(self, message: Message) -> str:
        """Decode base64 content and save to ~/.localdiscord/files/."""
        safe_name = f"{message.id}_{message.file_name}"
        path = self.FILES_DIR / safe_name
        try:
            data = base64.b64decode(message.content)
            path.write_bytes(data)
        except Exception as e:
            from src.utils.logger import get_logger
            get_logger("messaging").error(f"Failed to save file: {e}")
        return str(path)

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


def dm_channel_id(id_a: str, id_b: str) -> str:
    """Deterministic DM channel name for a pair of peers."""
    return "dm:" + ":".join(sorted([id_a, id_b]))


def _msg_from_row(row: dict) -> Message:
    """Build a Message from a JSON storage row."""
    return Message(
        id          = row["id"],
        type        = row["type"],
        sender_id   = row["sender_id"],
        sender_name = row["sender_name"],
        channel     = row["channel"],
        timestamp   = row["timestamp"],
        content     = row.get("content", ""),
        file_name   = row.get("file_name"),
        file_size   = row.get("file_size"),
        file_type   = row.get("file_type"),
        file_path   = row.get("file_path"),
    )
