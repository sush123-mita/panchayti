"""
peer.py — Peer data model and thread-safe registry.

A Peer represents another user on the local network.
PeerRegistry is the single source of truth for who is online.
"""

import socket
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class PeerStatus(Enum):
    ONLINE  = "online"
    AWAY    = "away"
    BUSY    = "busy"
    OFFLINE = "offline"


@dataclass
class Peer:
    """Represents a remote peer on the local network."""
    peer_id:      str
    username:     str
    ip:           str
    port:         int                           # TCP port the peer listens on
    status:       PeerStatus = PeerStatus.ONLINE
    is_encrypted: bool = False                  # True after ECDH handshake
    conn:         Optional[socket.socket] = None  # live socket (internal use)

    def address(self) -> str:
        return f"{self.ip}:{self.port}"

    def __hash__(self):
        return hash(self.peer_id)

    def __eq__(self, other):
        return isinstance(other, Peer) and self.peer_id == other.peer_id

    def __repr__(self):
        return f"Peer({self.username!r}, {self.ip}, status={self.status.value})"


# ------------------------------------------------------------------ #


class PeerRegistry:
    """
    Thread-safe in-memory store of known/connected peers.

    Consumers register change callbacks with on_change():
        registry.on_change(lambda event, peer: ...)

    Events: 'added', 'updated', 'removed'
    """

    def __init__(self):
        self._peers: dict[str, Peer] = {}
        self._lock  = threading.RLock()
        self._cbs:  list[Callable[[str, Peer], None]] = []

    # ---- Mutators ---------------------------------------------------- #

    def add_or_update(self, peer: Peer):
        with self._lock:
            is_new = peer.peer_id not in self._peers
            self._peers[peer.peer_id] = peer
        self._emit("added" if is_new else "updated", peer)

    def remove(self, peer_id: str) -> Optional[Peer]:
        with self._lock:
            peer = self._peers.pop(peer_id, None)
        if peer:
            self._emit("removed", peer)
        return peer

    def update_fields(self, peer_id: str, **kwargs):
        """Patch specific fields on an existing peer."""
        with self._lock:
            peer = self._peers.get(peer_id)
            if not peer:
                return
            for k, v in kwargs.items():
                setattr(peer, k, v)
        if peer:
            self._emit("updated", peer)

    # ---- Accessors --------------------------------------------------- #

    def get(self, peer_id: str) -> Optional[Peer]:
        with self._lock:
            return self._peers.get(peer_id)

    def all(self) -> list[Peer]:
        with self._lock:
            return list(self._peers.values())

    def count(self) -> int:
        with self._lock:
            return len(self._peers)

    # ---- Observer ---------------------------------------------------- #

    def on_change(self, callback: Callable[[str, Peer], None]):
        """Register a listener: fn(event: str, peer: Peer)."""
        self._cbs.append(callback)

    def _emit(self, event: str, peer: Peer):
        for cb in self._cbs:
            try:
                cb(event, peer)
            except Exception:
                pass
