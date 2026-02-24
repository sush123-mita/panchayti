"""
network.py — TCP connection management and message transport.

Architecture
------------
NetworkManager
  ├── TCP server thread  — accepts inbound connections
  ├── Per-connection handler threads (ConnectionHandler)
  │     ├── recv_thread  — reads length-prefixed JSON frames
  │     └── send_thread  — drains an outbound queue
  └── Public API used by UI and Discovery

Wire framing
------------
Every message is prefixed by a 4-byte big-endian unsigned integer
indicating the byte length of the UTF-8 JSON payload that follows.

    [  4 bytes length  ][  N bytes JSON  ]

Handshake
---------
On a new TCP connection the *initiator* sends HELLO first:
    {
      "type":       "handshake",
      "peer_id":    "<uuid>",
      "username":   "Alice",
      "public_key": "<base64 X25519 pubkey>",
      "port":       55001
    }
The *responder* sends the same structure back.
Both sides then call EncryptionManager.establish_session() and
start normal encrypted traffic.
"""

import json
import queue
import socket
import struct
import threading
from typing import Callable, Optional

from src.utils.logger import get_logger

logger = get_logger("network")

_FRAME_HEADER = struct.Struct("!I")   # 4-byte big-endian uint


# ------------------------------------------------------------------ #
#  Low-level framing helpers                                           #
# ------------------------------------------------------------------ #

def _send_frame(sock: socket.socket, data: dict):
    """Encode *data* as JSON and send with a 4-byte length header."""
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(_FRAME_HEADER.pack(len(payload)) + payload)


def _recv_frame(sock: socket.socket) -> Optional[dict]:
    """Block until a complete framed JSON message is received."""
    def recv_exact(n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    raw_len = recv_exact(4)
    if not raw_len:
        return None
    (msg_len,) = _FRAME_HEADER.unpack(raw_len)

    raw_body = recv_exact(msg_len)
    if not raw_body:
        return None

    return json.loads(raw_body.decode("utf-8"))


# ------------------------------------------------------------------ #
#  Per-connection handler                                              #
# ------------------------------------------------------------------ #

class ConnectionHandler:
    """
    Manages a single full-duplex TCP connection to one peer.

    - recv thread feeds incoming frames to on_message callback.
    - send thread drains an outbound queue.
    """

    def __init__(
        self,
        sock:       socket.socket,
        peer_id:    str,
        on_message: Callable[[str, dict], None],
        on_close:   Callable[[str], None],
    ):
        self.sock    = sock
        self.peer_id = peer_id
        self._on_msg   = on_message
        self._on_close = on_close
        self._q:      queue.Queue = queue.Queue()
        self._alive   = True

        self._recv_t = threading.Thread(target=self._recv_loop, daemon=True,
                                        name=f"recv-{peer_id[:8]}")
        self._send_t = threading.Thread(target=self._send_loop, daemon=True,
                                        name=f"send-{peer_id[:8]}")

    def start(self):
        self._recv_t.start()
        self._send_t.start()

    def enqueue(self, data: dict):
        """Queue a message for sending (thread-safe)."""
        if self._alive:
            self._q.put(data)

    def close(self):
        self._alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # ---- Internal threads ----------------------------------------- #

    def _recv_loop(self):
        try:
            while self._alive:
                frame = _recv_frame(self.sock)
                if frame is None:
                    break
                self._on_msg(self.peer_id, frame)
        except OSError:
            pass
        finally:
            self._alive = False
            self._on_close(self.peer_id)

    def _send_loop(self):
        while self._alive:
            try:
                data = self._q.get(timeout=0.2)
                _send_frame(self.sock, data)
            except queue.Empty:
                continue
            except OSError:
                break


# ------------------------------------------------------------------ #
#  NetworkManager                                                      #
# ------------------------------------------------------------------ #

class NetworkManager:
    """
    High-level interface for the rest of the application.

    Usage
    -----
        net = NetworkManager(encryption, peer_registry, broker, config)
        net.on_peer_connected    = lambda peer: ...   # set by UI
        net.on_peer_disconnected = lambda peer_id: ...
        net.on_message_received  = lambda message: ...
        net.start()
        net.connect_to_peer("192.168.1.5", 55001)
        net.broadcast(my_message)
        net.stop()
    """

    def __init__(self, encryption, peer_registry, message_broker, config):
        self._enc    = encryption
        self._peers  = peer_registry
        self._broker = message_broker
        self._cfg    = config

        self._handlers: dict[str, ConnectionHandler] = {}
        self._h_lock   = threading.RLock()
        self._running  = False

        # --- Callbacks set by the UI (called from worker threads) ---
        # These are emitted as Qt signals by MainWindow so they are
        # delivered safely on the main thread via the queued-connection
        # mechanism even though they are called here from worker threads.
        self.on_peer_connected:    Optional[Callable] = None
        self.on_peer_disconnected: Optional[Callable] = None
        self.on_error:             Optional[Callable] = None
        # NOTE: on_message_received is removed.  Incoming messages are
        # notified through MessageBroker.store_message → broker listeners,
        # which already fire the UI signal.  Adding a second path here
        # caused every received message to appear twice in the chat.

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                         #
    # ---------------------------------------------------------------- #

    def start(self):
        """Start the TCP listener in a background daemon thread."""
        self._running = True
        t = threading.Thread(target=self._server_loop, daemon=True, name="tcp-server")
        t.start()
        logger.info(f"NetworkManager started on TCP port {self._cfg.tcp_port}")

    def stop(self):
        self._running = False
        with self._h_lock:
            for h in list(self._handlers.values()):
                h.close()
            self._handlers.clear()

    # ---------------------------------------------------------------- #
    #  Public API                                                        #
    # ---------------------------------------------------------------- #

    def connect_to_peer(self, ip: str, port: int) -> bool:
        """
        Dial a remote peer, perform the handshake, and register them.
        Called from the discovery thread.
        """
        try:
            sock = socket.create_connection((ip, port), timeout=self._cfg.get("network.connection_timeout_sec", 10))
            self._handshake_as_initiator(sock, ip)
            return True
        except Exception as e:
            logger.warning(f"connect_to_peer {ip}:{port} failed: {e}")
            return False

    def send_to(self, peer_id: str, message) -> bool:
        """Send a Message object to one specific peer."""
        with self._h_lock:
            handler = self._handlers.get(peer_id)
        if not handler:
            return False
        wire = self._broker.prepare_outgoing(peer_id, message)
        handler.enqueue(wire)
        return True

    def broadcast(self, message, exclude_id: str = None):
        """Send a Message to all connected peers (optionally skip one)."""
        with self._h_lock:
            targets = list(self._handlers.keys())
        for pid in targets:
            if pid == exclude_id:
                continue
            self.send_to(pid, message)

    def send_presence(self, status: str):
        """Broadcast a presence/status update to all peers."""
        with self._h_lock:
            targets = list(self._handlers.keys())
        payload = {
            "type":    "presence",
            "peer_id": self._cfg.peer_id,
            "status":  status,
        }
        with self._h_lock:
            for h in self._handlers.values():
                h.enqueue(payload)

    def connected_count(self) -> int:
        with self._h_lock:
            return len(self._handlers)

    # ---------------------------------------------------------------- #
    #  TCP server                                                        #
    # ---------------------------------------------------------------- #

    def _server_loop(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", self._cfg.tcp_port))
        except OSError as exc:
            # Port already in use or firewall blocking — report to the UI
            msg = (
                f"Cannot open TCP port {self._cfg.tcp_port}: {exc}. "
                "Another instance may be running, or a firewall is blocking the port."
            )
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            return   # thread exits; no connections will be accepted
        srv.listen(64)
        srv.settimeout(1.0)
        logger.info(f"TCP server listening on 0.0.0.0:{self._cfg.tcp_port}")

        while self._running:
            try:
                conn, addr = srv.accept()
                threading.Thread(
                    target=self._handshake_as_responder,
                    args=(conn, addr[0]),
                    daemon=True,
                    name=f"hs-resp-{addr[0]}",
                ).start()
            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    logger.error(f"Server accept error: {e}")

        srv.close()

    # ---------------------------------------------------------------- #
    #  Handshake                                                         #
    # ---------------------------------------------------------------- #

    def _handshake_as_initiator(self, sock: socket.socket, ip: str):
        """Initiator sends HELLO first, then waits for HELLO back."""
        _send_frame(sock, self._make_hello())
        peer_hello = _recv_frame(sock)
        if peer_hello and peer_hello.get("type") == "handshake":
            # Clear the connect timeout so the I/O recv thread can block
            # indefinitely waiting for messages instead of disconnecting
            # after the timeout expires during periods of inactivity.
            sock.settimeout(None)
            self._finalise(sock, peer_hello, ip)
        else:
            sock.close()

    def _handshake_as_responder(self, sock: socket.socket, ip: str):
        """Responder waits for HELLO, then replies."""
        # Set a handshake timeout so stalled clients don't block a thread
        # forever.  Accepted sockets have no timeout by default.
        sock.settimeout(self._cfg.get("network.connection_timeout_sec", 10))
        peer_hello = _recv_frame(sock)
        if peer_hello and peer_hello.get("type") == "handshake":
            _send_frame(sock, self._make_hello())
            # Clear the handshake timeout before handing off to I/O threads.
            sock.settimeout(None)
            self._finalise(sock, peer_hello, ip)
        else:
            sock.close()

    def _make_hello(self) -> dict:
        return {
            "type":       "handshake",
            "peer_id":    self._cfg.peer_id,
            "username":   self._cfg.username,
            "public_key": self._enc.public_key_b64,
            "port":       self._cfg.tcp_port,
        }

    def _finalise(self, sock: socket.socket, peer_hello: dict, ip: str):
        """Register peer, establish encryption, start I/O threads."""
        peer_id = peer_hello.get("peer_id", "")

        # Reject self-connections
        if peer_id == self._cfg.peer_id:
            sock.close()
            return

        # Atomic check-and-register: hold the lock through the entire
        # registration so that two simultaneous connections between the
        # same pair of peers cannot both pass the duplicate check.
        with self._h_lock:
            if peer_id in self._handlers:
                sock.close()
                return

            # Establish ECDH session
            self._enc.establish_session(peer_id, peer_hello["public_key"])

            # Register peer in the registry
            from src.core.peer import Peer, PeerStatus
            peer = Peer(
                peer_id      = peer_id,
                username     = peer_hello.get("username", "Unknown"),
                ip           = ip,
                port         = peer_hello.get("port", self._cfg.tcp_port),
                status       = PeerStatus.ONLINE,
                is_encrypted = True,
            )
            self._peers.add_or_update(peer)

            # Create I/O handler and register atomically
            handler = ConnectionHandler(
                sock       = sock,
                peer_id    = peer_id,
                on_message = self._on_frame,
                on_close   = self._on_disconnect,
            )
            self._handlers[peer_id] = handler

        # Start I/O threads outside the lock
        handler.start()

        logger.info(f"Connected to {peer.username} @ {ip} (encrypted)")

        if self.on_peer_connected:
            self.on_peer_connected(peer)

    # ---------------------------------------------------------------- #
    #  Frame / disconnect callbacks                                      #
    # ---------------------------------------------------------------- #

    def _on_frame(self, peer_id: str, data: dict):
        """Dispatch an incoming frame by message type."""
        msg_type = data.get("type")

        if msg_type in ("text", "file"):
            message = self._broker.process_incoming(peer_id, data)
            if message:
                self._broker.store_message(message)

        elif msg_type == "delete":
            message = self._broker.process_incoming(peer_id, data)
            if message:
                target_id = message.content  # ID of message to delete
                channel = message.channel
                target_msg = self._broker.find_message(channel, target_id)
                if target_msg and target_msg.sender_id == message.sender_id:
                    self._broker.delete_message(channel, target_id)
                    self._broker._notify_delete(channel, target_id)

        elif msg_type == "presence":
            from src.core.peer import PeerStatus
            try:
                status = PeerStatus(data.get("status", "online"))
            except ValueError:
                status = PeerStatus.ONLINE
            self._peers.update_fields(peer_id, status=status)

    def _on_disconnect(self, peer_id: str):
        """Clean up after a peer disconnects."""
        with self._h_lock:
            self._handlers.pop(peer_id, None)

        self._enc.remove_session(peer_id)
        peer = self._peers.remove(peer_id)

        if peer:
            logger.info(f"Peer disconnected: {peer.username}")

        if self.on_peer_disconnected:
            self.on_peer_disconnected(peer_id)
