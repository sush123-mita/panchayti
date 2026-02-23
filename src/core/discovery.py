"""
discovery.py — Local-network peer discovery.

Two complementary mechanisms are used:

1. UDP Broadcast (primary)
   Each peer sends a small JSON announcement to the subnet broadcast
   address every N seconds on UDP port 55000.  Any peer that sees an
   unfamiliar announcement immediately tries a TCP connection.

2. mDNS / Zeroconf (optional, augments UDP)
   If the `zeroconf` library is available the app also registers an
   mDNS service ("_localdiscord._tcp.local.") so peers can be found
   across VLANs or when directed broadcast is blocked.

The two mechanisms are completely independent; both simply call
network_manager.connect_to_peer() when they find a new address.
"""

import json
import socket
import threading
import time
from typing import TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.network import NetworkManager

logger = get_logger("discovery")

_BROADCAST_MAGIC = "localdiscord_hello_v1"


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _local_ip() -> str:
    """Best-effort detection of the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _broadcast_addr(local_ip: str) -> str:
    """Derive the /24 subnet broadcast from local_ip (simple heuristic)."""
    parts    = local_ip.split(".")
    parts[3] = "255"
    return ".".join(parts)


# ------------------------------------------------------------------ #
#  DiscoveryManager                                                    #
# ------------------------------------------------------------------ #

class DiscoveryManager:
    """
    Discovers peers on the LAN and hands off to NetworkManager.

    Extension point: add voice-channel discovery, channel listings,
    or relay-peer negotiation here without touching the rest of the app.
    """

    def __init__(self, peer_registry, network_manager: "NetworkManager", config):
        self._peers   = peer_registry
        self._net     = network_manager
        self._cfg     = config
        self._running = False

        # Track IPs we've already attempted so we don't spam reconnects.
        self._attempted: set[str] = set()
        self._attempt_lock = threading.Lock()

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                         #
    # ---------------------------------------------------------------- #

    def start(self):
        self._running = True
        threading.Thread(target=self._broadcast_loop, daemon=True, name="udp-bcast").start()
        threading.Thread(target=self._listen_loop,    daemon=True, name="udp-listen").start()
        self._start_zeroconf()
        logger.info("Discovery service started")

    def stop(self):
        self._running = False
        self._stop_zeroconf()

    # ---------------------------------------------------------------- #
    #  UDP broadcast sender                                              #
    # ---------------------------------------------------------------- #

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)

        while self._running:
            try:
                payload = self._make_announce()
                local   = _local_ip()
                bcast   = _broadcast_addr(local)
                sock.sendto(payload, (bcast, self._cfg.udp_port))
                # Also send to global broadcast as a fallback
                if bcast != "255.255.255.255":
                    sock.sendto(payload, ("255.255.255.255", self._cfg.udp_port))
            except OSError as e:
                logger.debug(f"Broadcast send error: {e}")

            # Wait, but stay responsive to stop()
            for _ in range(self._cfg.discovery_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        sock.close()

    # ---------------------------------------------------------------- #
    #  UDP listener                                                      #
    # ---------------------------------------------------------------- #

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # Linux/macOS
        except (AttributeError, OSError):
            pass
        sock.bind(("", self._cfg.udp_port))
        sock.settimeout(1.0)
        logger.info(f"UDP discovery listener on port {self._cfg.udp_port}")

        while self._running:
            try:
                raw, (sender_ip, _) = sock.recvfrom(4096)
                self._handle_announce(raw, sender_ip)
            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    logger.debug(f"UDP listen error: {e}")

        sock.close()

    def _handle_announce(self, raw: bytes, sender_ip: str):
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.get("magic") != _BROADCAST_MAGIC:
            return

        peer_id = msg.get("peer_id", "")
        if not peer_id or peer_id == self._cfg.peer_id:
            return          # ignore self

        # Already connected?
        if self._peers.get(peer_id):
            return

        tcp_port = int(msg.get("port", self._cfg.tcp_port))
        key      = f"{sender_ip}:{tcp_port}"

        with self._attempt_lock:
            if key in self._attempted:
                return
            self._attempted.add(key)

        logger.info(f"Discovered {msg.get('username', '?')} @ {sender_ip}:{tcp_port}")
        threading.Thread(
            target=self._net.connect_to_peer,
            args=(sender_ip, tcp_port),
            daemon=True,
            name=f"dial-{sender_ip}",
        ).start()

    def _make_announce(self) -> bytes:
        return json.dumps({
            "magic":    _BROADCAST_MAGIC,
            "peer_id":  self._cfg.peer_id,
            "username": self._cfg.username,
            "port":     self._cfg.tcp_port,
        }).encode("utf-8")

    # ---------------------------------------------------------------- #
    #  mDNS / Zeroconf (optional)                                        #
    # ---------------------------------------------------------------- #

    def _start_zeroconf(self):
        """Register an mDNS service if zeroconf is available."""
        self._zc   = None
        self._info = None
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
            import socket as _s

            local_ip  = _local_ip()
            self._zc  = Zeroconf()

            # Register our own service
            self._info = ServiceInfo(
                "_localdiscord._tcp.local.",
                f"{self._cfg.peer_id}._localdiscord._tcp.local.",
                addresses=[_s.inet_aton(local_ip)],
                port=self._cfg.tcp_port,
                properties={
                    b"peer_id":  self._cfg.peer_id.encode(),
                    b"username": self._cfg.username.encode(),
                },
            )
            self._zc.register_service(self._info)

            # Browse for others
            self._browser = ServiceBrowser(
                self._zc, "_localdiscord._tcp.local.", self  # listener = self
            )
            logger.info("mDNS service registered and browsing")
        except ImportError:
            logger.info("zeroconf not installed — using UDP broadcast only")
        except Exception as e:
            logger.warning(f"mDNS start failed: {e}")

    def _stop_zeroconf(self):
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
                self._zc.close()
        except Exception:
            pass

    # --- Zeroconf ServiceBrowser listener interface ------------------- #

    def add_service(self, zc, svc_type, name):
        """Called by ServiceBrowser when a new mDNS peer appears."""
        try:
            info = zc.get_service_info(svc_type, name)
            if not info:
                return
            peer_id = info.properties.get(b"peer_id", b"").decode()
            if peer_id == self._cfg.peer_id or not peer_id:
                return
            if self._peers.get(peer_id):
                return

            import socket as _s
            ip       = _s.inet_ntoa(info.addresses[0])
            tcp_port = info.port
            key      = f"{ip}:{tcp_port}"

            with self._attempt_lock:
                if key in self._attempted:
                    return
                self._attempted.add(key)

            logger.info(f"mDNS discovered peer {peer_id[:8]} @ {ip}:{tcp_port}")
            threading.Thread(
                target=self._net.connect_to_peer,
                args=(ip, tcp_port),
                daemon=True,
            ).start()
        except Exception as e:
            logger.debug(f"mDNS add_service error: {e}")

    def remove_service(self, zc, svc_type, name):
        pass   # disconnect handled by TCP close

    def update_service(self, zc, svc_type, name):
        pass
