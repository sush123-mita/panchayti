"""
discovery.py — Local-network peer discovery (multi-subnet capable).

Five complementary discovery mechanisms run in parallel.  Each one
independently calls network_manager.connect_to_peer() when it finds a
new peer.  This layered approach means discovery works even if some
mechanisms are unavailable on a particular network.

Layer 1 — UDP Broadcast  (same-subnet, fast, always available)
    Sends a JSON announcement to every detected interface broadcast
    address plus 255.255.255.255.  Works instantly on the local /24
    but does NOT cross subnet boundaries.

Layer 2 — UDP Multicast  (cross-subnet, automatic)
    Sends the same announcement to an organisation-local multicast
    group (239.192.55.1, RFC 2365).  Multicast packets are forwarded
    by routers that support IGMP — most modern routers do.  The TTL
    (default 4) limits propagation to the local site.

Layer 3 — Optional Relay Server  (cross-subnet, guaranteed)
    If network.relay_host is configured, announcements are also sent
    to a lightweight UDP relay that aggregates and redistributes them.
    Use this when multicast is blocked (e.g. some managed switches).

Layer 4 — mDNS / Zeroconf  (optional, augments the above)
    If the `zeroconf` library is installed the app registers an mDNS
    service ("_localdiscord._tcp.local.") for additional discovery.

Layer 5 — Manual "Add Peer"  (UI fallback, always works)
    The user can manually enter an IP address in the UI to connect
    directly.  Handled in app.py, not here.
"""

import json
import socket
import struct
import threading
import time
from ipaddress import IPv4Network
from typing import TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.network import NetworkManager

logger = get_logger("discovery")

_BROADCAST_MAGIC    = "localdiscord_hello_v1"
_RELAY_QUERY_MAGIC  = "localdiscord_relay_query_v1"
_RELAY_RESPONSE_MAGIC = "localdiscord_relay_response_v1"


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


def _get_broadcast_addresses(local_ip: str) -> list[str]:
    """
    Detect broadcast addresses for all local network interfaces.

    Strategy 1 — psutil (accurate, handles all subnets and NIC masks)
    Strategy 2 — ipaddress /24 heuristic (stdlib, reasonable default)
    Strategy 3 — 255.255.255.255 as a last resort

    Returns a non-empty list of broadcast address strings.
    """
    addrs: list[str] = []

    # --- Strategy 1: psutil (optional dependency) --------------------
    try:
        import psutil
        for _iface, snic_list in psutil.net_if_addrs().items():
            for snic in snic_list:
                if snic.family == socket.AF_INET and snic.broadcast:
                    if snic.broadcast not in addrs:
                        addrs.append(snic.broadcast)
        if addrs:
            return addrs
    except ImportError:
        pass  # psutil not installed — fall through

    # --- Strategy 2: /24 heuristic from detected local IP ------------
    try:
        net = IPv4Network(f"{local_ip}/24", strict=False)
        return [str(net.broadcast_address)]
    except Exception:
        pass

    # --- Strategy 3: global broadcast --------------------------------
    return ["255.255.255.255"]


def _join_multicast_group(sock: socket.socket, group: str, local_ip: str):
    """
    Join a UDP multicast group on *sock*.

    This tells the OS to subscribe the socket to traffic destined for
    *group* on the network interface bound to *local_ip*.  After this
    call, recvfrom() on the socket will also deliver multicast packets.

    Args:
        sock:     A UDP socket already bound to 0.0.0.0:<port>.
        group:    Multicast group address, e.g. "239.192.55.1".
        local_ip: Local interface IP to receive multicast on.
    """
    mreq = struct.pack(
        "4s4s",
        socket.inet_aton(group),
        socket.inet_aton(local_ip),
    )
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)


# ------------------------------------------------------------------ #
#  DiscoveryManager                                                    #
# ------------------------------------------------------------------ #

class DiscoveryManager:
    """
    Discovers peers on the LAN (including across subnets) and hands
    off to NetworkManager for TCP connection.

    Uses broadcast, multicast, optional relay, and optional mDNS in
    parallel — each mechanism is independent and self-contained.
    """

    def __init__(self, peer_registry, network_manager: "NetworkManager", config):
        self._peers   = peer_registry
        self._net     = network_manager
        self._cfg     = config
        self._running = False

        # Track IPs we've already attempted so we don't spam reconnects.
        self._attempted: set[str] = set()
        self._attempt_lock = threading.Lock()

        # Set to True if the listener successfully joins the multicast group.
        self._mcast_ok = False

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                         #
    # ---------------------------------------------------------------- #

    def start(self):
        self._running = True

        # Layer 1: UDP broadcast — same-subnet discovery (enhanced for
        # multi-NIC machines and proper subnet-mask detection).
        threading.Thread(
            target=self._broadcast_loop, daemon=True, name="udp-bcast",
        ).start()

        # Unified listener — receives BOTH broadcast AND multicast
        # packets on the same socket (port 55000).
        threading.Thread(
            target=self._listen_loop, daemon=True, name="udp-listen",
        ).start()

        # Layer 2: UDP multicast — cross-subnet discovery.
        threading.Thread(
            target=self._multicast_send_loop, daemon=True, name="mcast-send",
        ).start()

        # Layer 3: Optional relay server — if configured.
        if self._cfg.relay_host:
            threading.Thread(
                target=self._relay_loop, daemon=True, name="relay-poll",
            ).start()

        # Layer 4: mDNS / Zeroconf — unchanged.
        self._start_zeroconf()

        logger.info(
            "Discovery started  broadcast=on  multicast=on  relay=%s  mdns=auto",
            "on" if self._cfg.relay_host else "off",
        )

    def stop(self):
        self._running = False
        self._stop_zeroconf()

    # ---------------------------------------------------------------- #
    #  Layer 1 — UDP Broadcast sender (enhanced)                         #
    # ---------------------------------------------------------------- #

    def _broadcast_loop(self):
        """
        Send UDP broadcast announcements to every detected subnet
        broadcast address.  Handles multi-NIC machines and non-/24
        networks (when psutil is installed).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)

        while self._running:
            try:
                payload     = self._make_announce()
                local       = _local_ip()
                bcast_addrs = _get_broadcast_addresses(local)

                for bcast in bcast_addrs:
                    try:
                        sock.sendto(payload, (bcast, self._cfg.udp_port))
                    except OSError as e:
                        logger.debug(f"Broadcast to {bcast} failed: {e}")

                # Global broadcast as a last-resort fallback.
                if "255.255.255.255" not in bcast_addrs:
                    try:
                        sock.sendto(
                            payload, ("255.255.255.255", self._cfg.udp_port),
                        )
                    except OSError:
                        pass

            except OSError as e:
                logger.debug(f"Broadcast send error: {e}")

            # Wait, but stay responsive to stop().
            for _ in range(self._cfg.discovery_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        sock.close()

    # ---------------------------------------------------------------- #
    #  Layer 2 — UDP Multicast sender (NEW — cross-subnet)               #
    # ---------------------------------------------------------------- #

    def _multicast_send_loop(self):
        """
        Send UDP multicast announcements to the configured multicast
        group (default 239.192.55.1).

        Multicast packets can cross subnet boundaries on LAN routers
        that support IGMP snooping — most modern routers/switches do.
        The TTL (default 4) limits propagation to the local site so
        packets never escape to the internet.
        """
        group = self._cfg.multicast_group
        ttl   = self._cfg.multicast_ttl
        port  = self._cfg.udp_port

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.settimeout(1.0)

            # Set multicast TTL — controls how many router hops the
            # packet can traverse.  TTL=4 is plenty for any LAN.
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_TTL,
                struct.pack("b", ttl),
            )

            # Bind outgoing multicast to the detected local interface
            # (important on machines with multiple NICs).
            local = _local_ip()
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(local),
            )

            logger.info(f"Multicast sender ready: group={group} ttl={ttl}")

        except OSError as e:
            logger.warning(
                f"Multicast send setup failed: {e}. "
                "Cross-subnet discovery will rely on relay/mDNS."
            )
            return

        while self._running:
            try:
                payload = self._make_announce()
                sock.sendto(payload, (group, port))
            except OSError as e:
                logger.debug(f"Multicast send error: {e}")

            for _ in range(self._cfg.discovery_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        sock.close()

    # ---------------------------------------------------------------- #
    #  Unified UDP listener (broadcast + multicast on one socket)        #
    # ---------------------------------------------------------------- #

    def _listen_loop(self):
        """
        Listen for UDP discovery announcements from all sources.

        This single socket receives:
          - Subnet-directed broadcast packets  (e.g. 192.168.1.255)
          - Global broadcast packets           (255.255.255.255)
          - Multicast packets                  (239.192.55.1)

        All packets go through the same _handle_announce() path.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass  # Windows doesn't have SO_REUSEPORT
        sock.bind(("", self._cfg.udp_port))
        sock.settimeout(1.0)
        logger.info(f"UDP discovery listener on port {self._cfg.udp_port}")

        # Join the multicast group so this socket also receives
        # cross-subnet multicast announcements.
        try:
            local = _local_ip()
            _join_multicast_group(sock, self._cfg.multicast_group, local)
            self._mcast_ok = True
            logger.info(f"Joined multicast group {self._cfg.multicast_group}")
        except OSError as e:
            self._mcast_ok = False
            logger.warning(
                f"Could not join multicast group {self._cfg.multicast_group}: {e}. "
                "Cross-subnet discovery will rely on relay/mDNS."
            )

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

    # ---------------------------------------------------------------- #
    #  Layer 3 — Optional relay client                                   #
    # ---------------------------------------------------------------- #

    def _relay_loop(self):
        """
        Periodically announce to a relay server and query it for peers.

        The relay is a lightweight standalone script (relay_server.py)
        that can run on any machine reachable from all subnets.  It
        aggregates announcements and responds with the full peer list.

        Protocol (all UDP):
          Client → relay:  normal announce JSON   (register self)
          Client → relay:  {"magic": "localdiscord_relay_query_v1"}
          Relay  → client: {"magic": "localdiscord_relay_response_v1",
                            "peers": [{announce1}, ...]}
        """
        relay_host = self._cfg.relay_host
        relay_port = self._cfg.relay_port

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3.0)
            logger.info(f"Relay client active: {relay_host}:{relay_port}")
        except OSError as e:
            logger.warning(f"Relay socket creation failed: {e}")
            return

        while self._running:
            try:
                # 1. Announce ourselves to the relay.
                payload = self._make_announce()
                sock.sendto(payload, (relay_host, relay_port))

                # 2. Query the relay for all known peers.
                query = json.dumps({"magic": _RELAY_QUERY_MAGIC}).encode("utf-8")
                sock.sendto(query, (relay_host, relay_port))

                # 3. Read the relay's response.
                try:
                    raw, _ = sock.recvfrom(65535)
                    resp = json.loads(raw.decode("utf-8"))
                    if resp.get("magic") == _RELAY_RESPONSE_MAGIC:
                        for peer_data in resp.get("peers", []):
                            peer_ip = peer_data.get("ip", "")
                            if peer_ip:
                                self._handle_announce(
                                    json.dumps(peer_data).encode("utf-8"),
                                    peer_ip,
                                )
                except socket.timeout:
                    pass  # relay not responding — not fatal

            except OSError as e:
                logger.debug(f"Relay communication error: {e}")

            for _ in range(self._cfg.discovery_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        sock.close()

    # ---------------------------------------------------------------- #
    #  Announce packet & handler (shared by all layers)                  #
    # ---------------------------------------------------------------- #

    def _handle_announce(self, raw: bytes, sender_ip: str):
        """Process a discovery announcement from any source."""
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

        # Prefer the IP embedded in the announcement.  Relay-forwarded
        # packets have sender_ip = relay's address, but the *real* peer
        # IP is stored in the JSON "ip" field by the relay.
        peer_ip = msg.get("ip", sender_ip) or sender_ip
        key     = f"{peer_ip}:{tcp_port}"

        with self._attempt_lock:
            if key in self._attempted:
                return
            self._attempted.add(key)

        logger.info(f"Discovered {msg.get('username', '?')} @ {peer_ip}:{tcp_port}")
        threading.Thread(
            target=self._try_connect,
            args=(peer_ip, tcp_port, key),
            daemon=True,
            name=f"dial-{peer_ip}",
        ).start()

    def _try_connect(self, ip: str, port: int, key: str):
        """
        Attempt a TCP connection and then remove the key from _attempted
        so future announcements can trigger a retry if needed.
        """
        self._net.connect_to_peer(ip, port)
        with self._attempt_lock:
            self._attempted.discard(key)

    def _make_announce(self) -> bytes:
        """Build the JSON announcement packet sent by all senders."""
        return json.dumps({
            "magic":    _BROADCAST_MAGIC,
            "peer_id":  self._cfg.peer_id,
            "username": self._cfg.username,
            "port":     self._cfg.tcp_port,
            "ip":       _local_ip(),          # needed for relay forwarding
        }).encode("utf-8")

    # ---------------------------------------------------------------- #
    #  Layer 4 — mDNS / Zeroconf (optional, unchanged)                   #
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
            logger.info("zeroconf not installed — using other discovery methods")
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
                target=self._try_connect,
                args=(ip, tcp_port, key),
                daemon=True,
            ).start()
        except Exception as e:
            logger.debug(f"mDNS add_service error: {e}")

    def remove_service(self, zc, svc_type, name):
        pass   # disconnect handled by TCP close

    def update_service(self, zc, svc_type, name):
        pass
