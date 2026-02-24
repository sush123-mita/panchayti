"""
test_discovery.py — Tests for peer discovery helpers.

We avoid opening real sockets here; instead we test the announce
packet format and the handle_announce logic with a monkey-patched
NetworkManager.
"""

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ------------------------------------------------------------------ #
#  Minimal stubs                                                       #
# ------------------------------------------------------------------ #

class _FakeConfig:
    peer_id            = "aaaa-self"
    username           = "Tester"
    tcp_port           = 55001
    udp_port           = 55000
    discovery_interval = 5
    multicast_group    = "239.192.55.1"
    multicast_ttl      = 4
    relay_host         = ""
    relay_port         = 55002

    def get(self, key, default=None):
        return default


class _FakePeerRegistry:
    def __init__(self):
        self._store = {}

    def get(self, peer_id):
        return self._store.get(peer_id)

    def add_or_update(self, peer):
        self._store[peer.peer_id] = peer


class _FakeNetworkManager:
    def __init__(self):
        self.calls = []  # list of (ip, port) dials

    def connect_to_peer(self, ip, port):
        self.calls.append((ip, port))
        # Small delay to simulate a real connection attempt.  Without this
        # the dial thread completes instantly, removing its key from
        # _attempted before the next _handle_announce call — which makes
        # the duplicate-suppression test unreliable.
        import time; time.sleep(0.05)
        return True


# ------------------------------------------------------------------ #
#  Import after stubs so discovery module initialises cleanly          #
# ------------------------------------------------------------------ #

from src.core.discovery import (
    DiscoveryManager, _BROADCAST_MAGIC, _get_broadcast_addresses,
)


# ------------------------------------------------------------------ #

class TestAnnouncePacket:
    def _make_dm(self):
        cfg  = _FakeConfig()
        reg  = _FakePeerRegistry()
        net  = _FakeNetworkManager()
        dm   = DiscoveryManager(reg, net, cfg)
        return dm, cfg, net

    def test_announce_contains_magic(self):
        dm, cfg, _ = self._make_dm()
        raw = dm._make_announce()
        msg = json.loads(raw)
        assert msg["magic"] == _BROADCAST_MAGIC

    def test_announce_contains_peer_id(self):
        dm, cfg, _ = self._make_dm()
        msg = json.loads(dm._make_announce())
        assert msg["peer_id"] == cfg.peer_id

    def test_announce_contains_port(self):
        dm, cfg, _ = self._make_dm()
        msg = json.loads(dm._make_announce())
        assert msg["port"] == cfg.tcp_port

    def test_announce_contains_ip(self):
        """Announce should include the 'ip' field for relay forwarding."""
        dm, cfg, _ = self._make_dm()
        msg = json.loads(dm._make_announce())
        assert "ip" in msg
        # ip should be a non-empty string
        assert isinstance(msg["ip"], str)
        assert len(msg["ip"]) > 0


class TestHandleAnnounce:
    def _make_dm(self):
        cfg = _FakeConfig()
        reg = _FakePeerRegistry()
        net = _FakeNetworkManager()
        dm  = DiscoveryManager(reg, net, cfg)
        return dm, cfg, reg, net

    def _packet(self, peer_id="bbbb-remote", username="Alice", port=55001, ip=None):
        data = {
            "magic":    _BROADCAST_MAGIC,
            "peer_id":  peer_id,
            "username": username,
            "port":     port,
        }
        if ip is not None:
            data["ip"] = ip
        return json.dumps(data).encode()

    def test_unknown_peer_triggers_connect(self):
        dm, cfg, reg, net = self._make_dm()
        dm._handle_announce(self._packet(), "192.168.1.10")
        # Give the spawned thread a moment
        import time; time.sleep(0.1)
        assert ("192.168.1.10", 55001) in net.calls

    def test_self_packet_ignored(self):
        dm, cfg, reg, net = self._make_dm()
        dm._handle_announce(self._packet(peer_id=cfg.peer_id), "192.168.1.10")
        import time; time.sleep(0.1)
        assert net.calls == []

    def test_wrong_magic_ignored(self):
        dm, cfg, reg, net = self._make_dm()
        bad = json.dumps({"magic": "other", "peer_id": "xxxx"}).encode()
        dm._handle_announce(bad, "192.168.1.20")
        import time; time.sleep(0.1)
        assert net.calls == []

    def test_duplicate_suppressed(self):
        dm, cfg, reg, net = self._make_dm()
        pkt = self._packet()
        dm._handle_announce(pkt, "192.168.1.10")
        dm._handle_announce(pkt, "192.168.1.10")   # second time
        import time; time.sleep(0.2)
        # Should only dial once
        assert net.calls.count(("192.168.1.10", 55001)) == 1

    def test_already_connected_peer_ignored(self):
        from src.core.peer import Peer, PeerStatus
        dm, cfg, reg, net = self._make_dm()
        # Pre-populate registry as if already connected
        reg._store["bbbb-remote"] = Peer(
            peer_id="bbbb-remote", username="Alice",
            ip="192.168.1.10", port=55001
        )
        dm._handle_announce(self._packet(), "192.168.1.10")
        import time; time.sleep(0.1)
        assert net.calls == []

    def test_malformed_json_ignored(self):
        dm, cfg, reg, net = self._make_dm()
        dm._handle_announce(b"not json {{{{", "192.168.1.99")
        import time; time.sleep(0.1)
        assert net.calls == []

    def test_relay_forwarded_packet_uses_embedded_ip(self):
        """
        When a packet contains an 'ip' field (relay-forwarded), the
        handler should connect to that IP, not the socket sender_ip.
        """
        dm, cfg, reg, net = self._make_dm()
        # The "ip" field is the real peer IP; sender_ip is the relay.
        pkt = self._packet(
            peer_id="cccc-relay-peer", username="Bob",
            port=55001, ip="192.168.20.5",
        )
        dm._handle_announce(pkt, "10.0.0.1")  # 10.0.0.1 = relay IP
        import time; time.sleep(0.1)
        # Should connect to the embedded IP, NOT the relay
        assert ("192.168.20.5", 55001) in net.calls
        assert ("10.0.0.1", 55001) not in net.calls


class TestBroadcastAddresses:
    def test_returns_at_least_one_address(self):
        addrs = _get_broadcast_addresses("192.168.1.42")
        assert len(addrs) >= 1

    def test_fallback_contains_valid_broadcast(self):
        """Without psutil, should fall back to /24 heuristic."""
        addrs = _get_broadcast_addresses("192.168.1.42")
        # Should contain either the /24 broadcast or the global fallback
        assert any(
            a in ("192.168.1.255", "255.255.255.255")
            for a in addrs
        )

    def test_loopback_fallback(self):
        """Loopback addresses should still return something usable."""
        addrs = _get_broadcast_addresses("127.0.0.1")
        assert len(addrs) >= 1
