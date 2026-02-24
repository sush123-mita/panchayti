# Codebase Concerns

**Analysis Date:** 2026-02-24

## Tech Debt

**Bare exception handling in listener callbacks:**
- Issue: The MessageBroker and PeerRegistry emit callbacks to listeners but silently swallow ALL exceptions with bare `except Exception: pass`.
- Files: `src/core/messaging.py` (lines 156-159), `src/core/peer.py` (lines 111-115)
- Impact: If a listener (e.g., the Qt signal emitter in `src/ui/app.py`) crashes, the error is silently lost. The UI may freeze or become unresponsive without any indication of the failure.
- Fix approach: Log the exception before swallowing it. Replace `except Exception: pass` with `except Exception as e: logger.error(f"Listener error: {e}", exc_info=True)`.

**Unvalidated socket recv() buffer in network.py:**
- Issue: The `_recv_exact()` helper in `src/core/network.py` (lines 61-68) reads chunks from the socket without a hard cap. A malicious peer could send a huge length prefix (e.g., 2GB) causing the application to allocate unbounded memory before the message is even received.
- Files: `src/core/network.py` (lines 59-79)
- Impact: Denial of service (OOM crash) from a malicious peer on the network.
- Fix approach: Add a MAX_MESSAGE_SIZE constant (e.g., 10MB), check `msg_len` against it before allocating the buffer, and close the connection if exceeded.

**Silent failure on message decryption:**
- Issue: When `process_incoming()` in `src/core/messaging.py` (line 204) catches an exception during decryption, it returns `None` without alerting the user or logging severity. Malformed or tampered messages are silently dropped.
- Files: `src/core/messaging.py` (lines 188-207)
- Impact: Users won't know if messages are being corrupted or an attacker is tampering with traffic. Security issues are invisible.
- Fix approach: Log decryption failures with peer ID and error type so operators can identify attacks.

**No persistence for message history:**
- Issue: All message history is stored in-memory in `MessageBroker._history` (line 137 of `src/core/messaging.py`). When the application closes, all chat history is lost.
- Files: `src/core/messaging.py` (lines 136-163)
- Impact: Users lose all conversation history on restart. No audit trail or recovery mechanism.
- Fix approach: Add optional SQLite backend (see line 128 comment). Create a `store_message_persistent()` path that writes to a local database while keeping the in-memory cache for performance.

## Known Bugs

**mDNS service browser leaks callback (minor):**
- Symptoms: If zeroconf is available but later fails to initialize, the ServiceBrowser may still be alive and processing callbacks.
- Files: `src/core/discovery.py` (lines 484-524)
- Trigger: Install zeroconf, then kill zeroconf daemon mid-startup.
- Workaround: Restart the application.
- Fix: Add proper cleanup in `_stop_zeroconf()` for the `_browser` object; ensure `self._browser` is set to None after cleanup.

**Socket timeout not cleared on responder path:**
- Symptoms: On incoming connections, the responder sets a handshake timeout (line 333 of `src/core/network.py`) but if `_recv_frame()` or peer_hello parsing fails, the socket may be closed without clearing the timeout, potentially causing resource exhaustion if many inbound connections fail.
- Files: `src/core/network.py` (lines 329-341)
- Trigger: Many failed handshakes from malicious peers.
- Workaround: Restart the application.
- Fix: Wrap the handshake logic in try-finally and always call `sock.close()` even on error.

## Security Considerations

**No rate limiting on discovery announces:**
- Risk: A peer can spam broadcast/multicast/relay announcements to flood the network or trigger excessive connection attempts.
- Files: `src/core/discovery.py` (lines 307-352, 199-239)
- Current mitigation: The `_attempted` set prevents duplicate connection attempts to the same IP:port combination (lines 446-451), but it never expires entries. A peer that announces, connects, disconnects, and re-announces with the same IP will be retried.
- Recommendations: (1) Implement exponential backoff: if a dial fails, wait 30-60 seconds before retrying. (2) Limit total concurrent dial attempts to prevent thread exhaustion.

**Public key exchange during handshake is unauthenticated:**
- Risk: An attacker on the LAN can intercept the initial TCP connection and perform a man-in-the-middle (MITM) attack by substituting their own public key. Subsequent messages would be encrypted to the attacker's key instead of the real peer.
- Files: `src/core/network.py` (lines 316-350)
- Current mitigation: Encryption is present (ECDH + AES-256-GCM), but there is no peer identity verification. The peer_id in the handshake is self-claimed and not verified against any certificate or pinned key.
- Recommendations: (1) Implement peer identity verification (e.g., short authentication string displayed to both users). (2) Add optional certificate pinning for known peers. (3) Document the risk prominently in the README.

**Relay server is completely open:**
- Risk: The relay server (`relay_server.py`) accepts announcements from ANY IP without authentication. An attacker can register fake peers and receive the full peer list.
- Files: `relay_server.py` (lines 100-128)
- Current mitigation: None. The relay trusts all incoming packets.
- Recommendations: (1) Add a pre-shared key (PSK) field to announcements and validate it. (2) Implement IP-based access control. (3) Document that the relay should only be deployed on a trusted network.

**Configuration directory permissions not validated:**
- Risk: The user config file at `~/.localdiscord/config.json` is created with default permissions (world-readable on Unix). A local attacker can read the peer_id and other settings.
- Files: `src/utils/config.py` (lines 55-58)
- Current mitigation: None.
- Recommendations: Create the directory with restrictive permissions (0700) and the config file with 0600 when first created.

## Performance Bottlenecks

**All messages stored in-memory without limit:**
- Problem: The `_history` dict in `MessageBroker` grows unbounded. With continuous chatting, memory usage grows linearly forever.
- Files: `src/core/messaging.py` (lines 136-163)
- Cause: No eviction policy. Entries are only removed when the app exits.
- Improvement path: Implement a bounded in-memory cache (e.g., max 10,000 messages per channel, LRU eviction) combined with optional persistent storage (SQLite). The cache serves hot reads while the database provides history beyond the cache limit.

**Multicast TTL fixed to 4:**
- Problem: On large campus/enterprise networks with many subnets, TTL=4 may not reach all reachable peers.
- Files: `src/core/discovery.py` (line 256)
- Cause: Fixed configuration in `config/default_config.json` (default multicast_ttl=4).
- Improvement path: Make TTL configurable per deployment. Provide guidance in README: use TTL=8-16 for larger sites, TTL=2-4 for small LANs.

**Discovery loops continuously rescan without backoff:**
- Problem: The broadcast, multicast, and relay loops (lines 199-239, 245-301, 358-416 in `src/core/discovery.py`) run every `discovery_interval` seconds (default 5) indefinitely. This wastes CPU and network bandwidth even after all local peers have been discovered.
- Files: `src/core/discovery.py`
- Cause: No adaptive discovery (e.g., slow down after finding peers, speed up if new announcements arrive).
- Improvement path: Implement exponential backoff: after discovering all peers, slow down to 60-second intervals. Resume fast scanning if a new announcement arrives or a peer disconnects.

## Fragile Areas

**Thread-unsafe state in MainWindow:**
- Files: `src/ui/app.py` (full class, especially lines 145-175)
- Why fragile: Multiple network threads call `self._bridge` signals which are then delivered to the main thread. If a signal is connected incorrectly or a callback crashes, the UI enters an inconsistent state (e.g., user list out of sync with peer_registry). The application has no recover mechanism.
- Safe modification: (1) Validate that all network callbacks are wired through the signal bridge (never direct). (2) Add invariant checks in `_on_peer_joined()` and `_on_peer_left()` to detect list/registry divergence. (3) Add a `sync()` method that rebuilds the user list from scratch if divergence is detected.
- Test coverage: No tests for concurrent peer join/leave scenarios or signal delivery under high load.

**DiscoveryManager attempt tracking is complex:**
- Files: `src/core/discovery.py` (lines 146-151, 446-451, 461-468)
- Why fragile: The `_attempted` set is designed to prevent duplicate dials, but it's cleared only after `_try_connect()` completes. If a dial is slow or hangs, new announces for the same peer will be suppressed even though no active connection is in progress. Additionally, the set never expires old entries; a peer that moves to a new IP will be permanently blacklisted if its old IP announced first.
- Safe modification: (1) Use a dict instead of a set, mapping `key -> last_attempt_time`. (2) Expire entries after 30 seconds. (3) Only suppress a new dial if the last attempt was within the last 10 seconds.
- Test coverage: `tests/test_discovery.py` has basic duplicate suppression tests (line 144-151) but no tests for entry expiration or the slow-dial scenario.

**NetworkManager handler registration race condition:**
- Files: `src/core/network.py` (lines 352-399)
- Why fragile: In `_finalise()`, the lock is held during peer registration, encryption setup, and handler creation (lines 364-391), but handler threads are started OUTSIDE the lock (line 394). Between releasing the lock and starting threads, another inbound connection for the same peer could sneak in and bypass the duplicate check.
- Safe modification: Move `handler.start()` INSIDE the lock, after the handler is registered. Alternatively, register the handler with a "starting" flag and set it to "started" after threads are running.
- Test coverage: No tests for simultaneous bidirectional connections between the same peer pair.

## Scaling Limits

**Discovery announce storm with many peers:**
- Current capacity: Tested with ~50 peers locally.
- Limit: With 100+ peers, all simultaneously announcing every 5 seconds, UDP socket buffer on shared switches may overflow, causing announcements to be dropped. Some peers will never be discovered.
- Scaling path: (1) Implement exponential backoff as mentioned in Performance. (2) For very large networks (100+ peers), deploy a relay server. (3) Increase announce interval in config (e.g., to 10-15 seconds).

**Single-threaded Qt event loop can lag:**
- Current capacity: Chat with ~50 connected peers at ~10 messages/second per peer.
- Limit: The main Qt thread must process peer join/leave, message rendering, and UI updates. With 500 messages/second arriving concurrently, the event queue will back up and the UI will become unresponsive.
- Scaling path: (1) Implement message batching: collect N messages before rendering them as a single batch. (2) Move message history scrollback to a background thread. (3) For very large deployments, use a message server instead of peer-to-peer.

## Dependencies at Risk

**cryptography library version unpinned:**
- Risk: `src/core/encryption.py` imports from cryptography but `requirements.txt` likely has no pinned version. A breaking API change in a future release could silently break the handshake.
- Impact: Dependency upgrade breaks the application.
- Migration plan: Pin cryptography to a specific version (e.g., cryptography==42.0.0) in requirements.txt. Add CI tests that run on new versions weekly to catch breaks early.

**zeroconf is optional and untested:**
- Risk: The zeroconf import is guarded (line 489 of `src/core/discovery.py`) but if it IS installed and breaks, the exception handler (lines 513-516) silently logs a warning. No tests validate mDNS discovery.
- Impact: mDNS discovery silently fails on systems where zeroconf was upgraded to an incompatible version.
- Migration plan: Add conditional tests that run only if zeroconf is installed. Add a CI check that tests both with and without zeroconf.

## Missing Critical Features

**No graceful shutdown:**
- Problem: When the app exits (`closeEvent()` in `src/ui/app.py`, lines 594-597), the threads are stopped but not waited for. If a network thread is in the middle of a recv_frame(), it may not exit cleanly, potentially leaving sockets in TIME_WAIT state.
- Blocks: Proper restart behavior; prevents rapid restart in scripts.
- Fix: Call `discovery.stop()` and `network.stop()`, then wait for all threads with a timeout (e.g., `join(timeout=2)`).

**No message delivery acknowledgments:**
- Problem: When a message is broadcast (line 455 of `src/ui/app.py`), there is no feedback if the peer received it. If the connection drops after send but before deliver, the user has no idea.
- Blocks: Reliable messaging; file transfer; critical applications.
- Fix: Implement ACK messages (already sketched in line 426 of `src/core/network.py`). Wait for ACK before marking message as "delivered" in the UI.

**No offline message queuing:**
- Problem: If a peer is offline when you send a message, the message is lost forever.
- Blocks: Asynchronous messaging; reliability.
- Fix: Store outgoing messages in a local queue. When the peer comes online, replay the queue.

**No username collision handling:**
- Problem: Two users with the same username will appear as duplicates in the chat. There's no mechanism to enforce unique usernames across the network.
- Blocks: Clear attribution of messages; administrative control.
- Fix: On discovery, check if a peer with the same username already exists and reject or prompt for rename.

## Test Coverage Gaps

**No network integration tests:**
- What's not tested: Actual TCP connection handshake, encryption key exchange, message send/receive over the network.
- Files: `src/core/network.py`, `src/core/encryption.py`
- Risk: A breaking change to the handshake format could go unnoticed until deployment.
- Priority: High

**No UI thread-safety tests:**
- What's not tested: Concurrent peer join/leave and message delivery; signal delivery under load.
- Files: `src/ui/app.py`
- Risk: Race conditions in the UI that only manifest under high concurrency.
- Priority: High

**No relay server tests:**
- What's not tested: Relay server peer aggregation, expiry, and response correctness.
- Files: `relay_server.py`
- Risk: Silent failures in the relay (e.g., peer list not updated, expired peers not removed).
- Priority: Medium

**No configuration merge tests:**
- What's not tested: The `_deep_merge()` function in `src/utils/config.py` (lines 137-144) with complex nested structures.
- Files: `src/utils/config.py`
- Risk: Config override merging could fail silently on edge cases.
- Priority: Low

**No error recovery tests:**
- What's not tested: What happens when a socket fails, a peer disconnects unexpectedly, or encryption fails.
- Files: `src/core/network.py`, `src/core/messaging.py`
- Risk: Edge case crashes in production.
- Priority: Medium

---

*Concerns audit: 2026-02-24*
