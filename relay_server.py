#!/usr/bin/env python3
"""
relay_server.py — Optional lightweight discovery relay for LocalDiscord.

Run this on any machine that is reachable from all subnets in your LAN.
Peers will announce themselves to this relay and query it for other peers,
enabling discovery even when UDP broadcast and multicast cannot cross
subnet boundaries.

Usage:
    python relay_server.py                     # listen on 0.0.0.0:55002
    python relay_server.py --port 55002        # custom port
    python relay_server.py --bind 10.0.0.1     # custom bind address

On the client side, set network.relay_host in ~/.localdiscord/config.json:
    { "network": { "relay_host": "192.168.1.1", "relay_port": 55002 } }

Protocol (all UDP, same port):
    1. Peers send their normal JSON announcement to the relay periodically.
    2. Peers send {"magic": "localdiscord_relay_query_v1"} to request the
       full list of known peers.
    3. Relay responds with:
       {"magic": "localdiscord_relay_response_v1",
        "peers": [<announce1>, <announce2>, ...]}

Peers are automatically expired after 30 seconds of silence.
No external dependencies — uses only the Python standard library.
"""

import argparse
import json
import socket
import time
import threading

ANNOUNCE_MAGIC  = "localdiscord_hello_v1"
QUERY_MAGIC     = "localdiscord_relay_query_v1"
RESPONSE_MAGIC  = "localdiscord_relay_response_v1"
EXPIRY_SEC      = 30


def main():
    parser = argparse.ArgumentParser(
        description="LocalDiscord discovery relay server",
    )
    parser.add_argument(
        "--bind", default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=55002,
        help="UDP port to listen on (default: 55002)",
    )
    args = parser.parse_args()

    # peer_id  →  {"data": <announce_dict>, "ip": str, "last_seen": float}
    peers: dict = {}
    lock = threading.Lock()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))
    sock.settimeout(1.0)

    print(f"[relay] Listening on {args.bind}:{args.port}")
    print(f"[relay] Peers expire after {EXPIRY_SEC}s of silence")
    print()

    # -- Background thread: expire stale peers --

    def expire_loop():
        while True:
            now = time.time()
            with lock:
                expired = [
                    pid for pid, info in peers.items()
                    if now - info["last_seen"] > EXPIRY_SEC
                ]
                for pid in expired:
                    name = peers[pid]["data"].get("username", "?")
                    print(f"[relay] Expired: {name} ({pid[:8]})")
                    del peers[pid]
            time.sleep(5)

    threading.Thread(target=expire_loop, daemon=True).start()

    # -- Main loop: receive and respond --

    while True:
        try:
            raw, (sender_ip, sender_port) = sock.recvfrom(65535)
            msg = json.loads(raw.decode("utf-8"))
        except socket.timeout:
            continue
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue

        magic = msg.get("magic", "")

        if magic == ANNOUNCE_MAGIC:
            # Store / update peer announcement.
            peer_id = msg.get("peer_id", "")
            if peer_id:
                # Overwrite the "ip" field with the actual sender IP so
                # that peers on different subnets get the routable address.
                msg["ip"] = sender_ip
                with lock:
                    is_new = peer_id not in peers
                    peers[peer_id] = {
                        "data":      msg,
                        "ip":        sender_ip,
                        "last_seen": time.time(),
                    }
                action = "Registered" if is_new else "Refreshed"
                print(
                    f"[relay] {action}: "
                    f"{msg.get('username', '?')} @ {sender_ip} ({peer_id[:8]})"
                )

        elif magic == QUERY_MAGIC:
            # Respond with all known peers.
            with lock:
                peer_list = [info["data"] for info in peers.values()]
            response = json.dumps({
                "magic": RESPONSE_MAGIC,
                "peers": peer_list,
            }).encode("utf-8")
            sock.sendto(response, (sender_ip, sender_port))
            print(f"[relay] Query from {sender_ip} — sent {len(peer_list)} peer(s)")


if __name__ == "__main__":
    main()
