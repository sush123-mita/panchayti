# Pitfalls — P2P LAN Chat Feature Expansion

**Research Date:** 2026-02-24
**Scope:** Adding persistence, message sync, DMs, file transfer, and search to Panchayti (LocalDiscord)
**Architecture:** Fully P2P, Python/PyQt6, X25519 ECDH + AES-256-GCM, SQLite target, no central server

---

## Overview

This document catalogs critical mistakes commonly made when adding persistence, sync, direct messaging, file transfer, and search to P2P LAN chat applications — with prevention strategies and phase mapping specific to this codebase. Each pitfall is grounded in the existing architecture (`MessageBroker`, `ConnectionHandler`, `EncryptionManager`, wire-format JSON over TCP) and known concerns already identified in CONCERNS.md.

---

## Persistence Pitfalls

### P1 — Writing to SQLite from Multiple Threads Without Serialization

**What goes wrong:** The existing codebase has one recv_thread and one send_thread per peer (per `ConnectionHandler`). With 5 connected peers, there are 10+ threads that will call `MessageBroker.store_message()` concurrently. If SQLite writes are added directly inside `store_message()` without a write queue, two threads will attempt concurrent writes to the same `.db` file. Python's `sqlite3` module in WAL mode handles some concurrency but will raise `OperationalError: database is locked` under rapid concurrent writes from multiple threads.

**Warning signs:**
- Intermittent `OperationalError: database is locked` in the log file at `~/.localdiscord/localdiscord.log`
- Messages disappearing from history after reconnect (failed writes silently dropped due to bare `except` in listener callbacks — already flagged in CONCERNS.md lines 156-159 of `messaging.py`)
- History out of order despite timestamps being correct

**Prevention strategy:**
- Use a single dedicated SQLite writer thread with a `queue.Queue`. All threads enqueue write operations; the writer thread is the only one calling `cursor.execute()` / `conn.commit()`. This mirrors the existing `send_thread` pattern in `ConnectionHandler`.
- Enable WAL mode (`PRAGMA journal_mode=WAL`) as a secondary safeguard for reads.
- Wrap the `store_message()` path so it enqueues a write task rather than writing inline.
- Fix the bare `except Exception: pass` in listener callbacks (CONCERNS.md) before adding persistence — a failed DB write will otherwise vanish silently.

**Phase:** Address in the persistence phase (Phase 1), before any sync or file transfer work.

---

### P2 — Storing Encrypted Ciphertext in the Database Instead of Plaintext

**What goes wrong:** The existing wire format carries `{"ciphertext": "<base64>", "nonce": "<base64>"}` fields. A naive implementation that persists the `Message.to_wire()` dict directly to SQLite stores the ciphertext. When the app restarts, the AES-256-GCM session key is gone (it is ephemeral, derived fresh per ECDH handshake each connection). The stored ciphertext is permanently unreadable. The user sees empty history on every restart despite persistence being "working."

**Warning signs:**
- Chat history renders blank after app restart even though SQLite rows exist
- No decryption errors logged (the code never attempts to decrypt stored rows — it just fails to find a session key)
- `EncryptionManager._session_keys` is empty on startup (it is always empty — keys are not persisted)

**Prevention strategy:**
- Persist the **decrypted plaintext** to SQLite, not the wire-format dict. The `process_incoming()` path in `messaging.py` already decrypts messages before storing in `_history`. The SQLite write should happen at the same point, after decryption, using the plaintext `Message` object.
- Store: `(message_id, channel, sender_id, sender_name, content_plaintext, timestamp, message_type)`.
- Protect the database file with restrictive filesystem permissions (0600) to keep plaintext content private — consistent with the config file permission gap already noted in CONCERNS.md.

**Phase:** Address in Phase 1 (persistence). Get the schema right before sync adds more message types.

---

### P3 — No Stable Message Identity Across Peers

**What goes wrong:** When implementing sync ("exchange missed messages on reconnect"), each peer needs to identify which messages the other peer already has. Without a stable, globally unique message ID that is consistent across all peers, two common failures occur: (a) messages are duplicated on sync because the receiver cannot tell it already has that message, or (b) messages are skipped because the IDs don't match between sender and receiver.

The existing `Message` dataclass likely generates IDs locally (e.g., `uuid.uuid4()`). Two peers receiving the same group message will generate two different local UUIDs, making deduplication impossible.

**Warning signs:**
- Chat history shows duplicate messages after reconnect
- Message count in SQLite grows every time two peers reconnect
- Messages appear in wrong order or with gaps after sync

**Prevention strategy:**
- The **sender** generates and includes the message ID in the wire format before encryption. The receiver persists the sender-assigned ID. This means all peers store the same stable ID for the same message.
- For group channel messages, the ID is `{sender_peer_id}:{sequence_number}` or a deterministic UUID derived from sender ID + timestamp + content hash. Either approach gives the receiver a stable key to check for duplicates on `INSERT OR IGNORE INTO messages`.
- Add the `msg_id` field to `Message.to_wire()` and `Message.from_wire()` now, before persistence, so that sync can rely on it from day one.

**Phase:** Phase 1 (persistence schema design). Retrofitting IDs after sync is implemented causes a migration nightmare.

---

## Sync Pitfalls

### S1 — Using Wall-Clock Timestamps for Sync Instead of Sequence Numbers

**What goes wrong:** A common approach is to sync by exchanging the "last seen timestamp" and requesting all messages newer than that time. This fails in a P2P LAN setting because: (a) different machines have clock skew (even 1-2 seconds of NTP drift can cause messages to be missed or duplicated), (b) two messages sent at the "same" millisecond are indistinguishable, and (c) a peer that was offline while clocks drifted apart will compute the wrong sync window.

**Warning signs:**
- Messages missing from history after sync even though the sender has them
- Duplicate messages appearing after sync between peers with clock skew
- Sync behaves differently on Windows vs Linux (Windows clock resolution is ~15ms by default)

**Prevention strategy:**
- Use a **per-sender sequence number** stored in SQLite alongside each message. Each peer maintains a `sent_seq` counter that increments monotonically. On sync, peers exchange `{peer_id: last_seq_seen}` maps (a simplified vector clock). The receiver requests messages where `sender_peer_id = X AND seq > N`.
- Keep timestamps as metadata for display only, not for sync logic.
- The `MessageBroker` already has `_history` keyed by channel — add a per-peer-per-channel `last_seq` table to SQLite.

**Phase:** Phase 2 (sync). The sequence number approach must be decided before any sync protocol messages are written.

---

### S2 — Syncing the Full History on Every Reconnect

**What goes wrong:** On reconnect, the naive implementation sends all stored messages to the peer. With "keep history forever" (PROJECT.md requirement), this quickly becomes unacceptable: after 6 months of use, a reconnect triggers megabytes of JSON flowing over a LAN TCP connection, blocking the connection handler thread and making the chat appear frozen while sync completes.

**Warning signs:**
- UI freezes for several seconds on peer reconnect
- High CPU and memory on the receiving end while processing sync
- The `ConnectionHandler` recv_thread blocks on sync payload, starving normal message delivery

**Prevention strategy:**
- Send only the **delta**: messages the remote peer does not have. Use the vector clock exchange (see S1) to compute the minimal set.
- Add a hard cap: sync at most the last N messages (e.g., 500) per channel per reconnect. Include a "sync truncated" notice in the UI so users know older history was not transmitted.
- Run sync as a distinct protocol phase (`MSG_TYPE = "sync_request"` / `"sync_batch"`) that does not block the normal message queue. The existing dispatch-by-type pattern in `NetworkManager._on_frame()` already supports adding new message types cleanly.
- Implement chunked sync batches (e.g., 50 messages per batch) with acknowledgment between batches, similar to the planned file transfer chunking.

**Phase:** Phase 2 (sync protocol design).

---

### S3 — Sync Protocol That Deadlocks on Bidirectional Reconnect

**What goes wrong:** In a fully P2P mesh, when peer A reconnects to peer B, both sides may simultaneously initiate sync ("I'll send you what you missed, you send me what I missed"). Without a coordinator or tiebreaker, both peers send their entire sync_request at the same time. Each is waiting to process the other's request while their own send queue fills, potentially deadlocking the `ConnectionHandler` send_thread if the queue is bounded, or causing memory growth if it is unbounded.

The existing codebase has separate recv_thread and send_thread per connection, which helps — but if the sync payload is large enough to fill the TCP send buffer, the send_thread blocks, which blocks enqueuing more sends, which blocks the sync dispatch.

**Warning signs:**
- Reconnect hangs indefinitely between specific peer pairs
- `ConnectionHandler` send_thread shows high memory in profiling during reconnect
- Sync only works reliably when one peer has significantly more messages than the other

**Prevention strategy:**
- Use a **role negotiation**: the peer with the lower `peer_id` (lexicographic UUID comparison) acts as "sync initiator." Only the initiator sends `sync_request` first. The responder replies with its vector clock, then the initiator sends the delta. Roles then reverse.
- This uses the existing `peer_id` from `PeerRegistry` with no additional state.
- Keep sync batches small (50 messages max) with explicit ACK between batches to avoid filling the TCP window.

**Phase:** Phase 2 (sync protocol design), before any sync code is written.

---

## Direct Messaging Pitfalls

### D1 — Treating DMs as a Channel Named After the Peer Instead of a Dedicated Store

**What goes wrong:** The tempting shortcut is to store DM messages in the existing `MessageBroker._history` dict using a channel key like `"dm:{peer_id}"`. This pollutes the group channel namespace, makes the channel list render DMs alongside group channels (unless filtered), and prevents DM-specific features (e.g., "only show DMs with this person"). More critically, existing tests and group message logic that iterate all channels will inadvertently include DM channels.

**Warning signs:**
- DMs appear in the group channel dropdown list
- Group channel message count includes DM messages in statistics
- Search across "all channels" also searches DMs when the user didn't intend it

**Prevention strategy:**
- Model DMs as a first-class entity in SQLite: a separate `direct_messages` table with `(id, from_peer_id, to_peer_id, content, timestamp, seq)` distinct from the `channel_messages` table.
- In the UI, the existing `_bridge` signal pattern should emit a distinct `dm_received` signal (separate from the existing `message_received` signal) so `MainWindow` routes DMs to the DM sidebar, not the channel display.
- The `MessageBroker` should have a separate `store_dm()` path rather than reusing `store_message()` with a mangled channel name.

**Phase:** Phase 3 (DM implementation). Plan the data model before touching the UI.

---

### D2 — Sending DMs Without Verifying a Live Direct Connection Exists

**What goes wrong:** In the existing group channel flow, `NetworkManager.send_to()` is called with a peer_id. If the peer is in `PeerRegistry` but the `ConnectionHandler` for that peer has silently died (socket closed but registry not yet updated), the DM send will silently fail. With group channels, the user can see other peers still active and infer delivery. With DMs, the user has no such signal — the message appears sent but was dropped.

This is amplified by the existing CONCERNS.md finding that there are no message delivery acknowledgments.

**Warning signs:**
- DMs appear sent in the UI but the recipient never receives them
- No error surfaced in the UI; the log shows a broken pipe exception in `ConnectionHandler`
- DM send failure is especially common during the reconnect window

**Prevention strategy:**
- Before sending a DM, verify the `ConnectionHandler` for that peer is alive (not just that the peer is in `PeerRegistry`). Add a `NetworkManager.is_connected(peer_id) -> bool` check that inspects the actual handler state.
- Implement local DM queuing: if the peer is unreachable, store the outgoing DM in a `pending_dms` SQLite table. On peer reconnect (after sync), flush the queue. This resolves the "no offline message queuing" gap already noted in CONCERNS.md.
- Show a distinct UI state for "queued" vs "sent" DMs.

**Phase:** Phase 3 (DM). The queuing mechanism should be designed at the same time as DM send, not retrofitted later.

---

## File Transfer Pitfalls

### F1 — Reusing the Existing JSON/TCP Frame Protocol for File Chunks

**What goes wrong:** The current wire format is length-prefixed JSON over TCP. JSON is text-based; binary file data requires base64 encoding which adds ~33% overhead. A 10 MB file becomes ~13.4 MB of base64 inside a JSON envelope. Worse, the current `_recv_exact()` buffer is already identified as having no MAX_MESSAGE_SIZE cap (CONCERNS.md) — a 10 MB JSON frame will allocate 10 MB in memory atomically before processing begins, defeating the purpose of chunking.

**Warning signs:**
- File transfer is 33% slower than the raw LAN bandwidth allows
- Memory spikes to several times the file size during transfer
- Large file transfers trigger the existing OOM risk identified in CONCERNS.md

**Prevention strategy:**
- Introduce a second frame type: a binary frame alongside the existing JSON frame. For file chunks, use a header-then-payload structure: `[4-byte type][4-byte chunk_id][4-byte chunk_len][N bytes raw binary]`. This avoids JSON parsing overhead and base64 expansion.
- The existing `_send_frame()` / `_recv_exact()` pattern in `network.py` can be extended with a `_send_binary_frame()` / `_recv_binary_frame()` variant that reads fixed-size headers and raw bytes.
- Add MAX_CHUNK_SIZE (e.g., 64 KB) as a constant. Each file transfer splits into chunks of this size.
- This also naturally enforces the MAX_MESSAGE_SIZE fix from CONCERNS.md — binary frames have explicit size in the header, easy to cap.

**Phase:** Phase 4 (file transfer). Do not retrofit the JSON frame for file transfer; design the binary protocol first.

---

### F2 — Encrypting File Chunks With the Same Nonce Pattern as Text Messages

**What goes wrong:** The existing encryption uses AES-256-GCM with a random nonce per message. For file chunks, if each chunk is encrypted with a fresh random nonce, that is correct — but naive implementations re-use the same nonce across chunks (e.g., using a counter nonce starting at 0 for chunk 0, 1 for chunk 1). AES-GCM nonce reuse with the same key is catastrophic: it leaks the XOR of the two plaintexts and the authentication key, breaking confidentiality and integrity for all traffic on that session.

**Warning signs:**
- File chunks using counter-based nonces starting at 0 (a common "optimization" that seems harmless)
- Encryption code that generates one nonce per file transfer and increments it per chunk
- No test that verifies nonce uniqueness across chunks of the same transfer

**Prevention strategy:**
- Use `os.urandom(12)` per chunk (same as the existing text message path in `EncryptionManager`). Random 96-bit nonces have astronomically low collision probability for the volumes involved in LAN file transfer.
- Alternatively, derive chunk nonces via HKDF from the session key + transfer_id + chunk_index, but this is more complex than random nonces for the security gains it provides at LAN scale.
- Authenticate file metadata (filename, total size, chunk count, transfer_id) as AAD (Additional Authenticated Data) in each chunk's GCM tag. This prevents a man-in-the-middle from substituting chunks from a different transfer.
- Add an end-to-end transfer integrity check: SHA-256 of the reassembled plaintext, sent as a final `file_complete` message and verified by the receiver.

**Phase:** Phase 4 (file transfer). Define the encryption approach for chunks before writing any file transfer code.

---

### F3 — No Transfer State Machine — Resumability Breaks on Reconnect

**What goes wrong:** PROJECT.md requires "resumable large file support." A naive implementation tracks transfer progress in memory (e.g., a dict of `{transfer_id: chunks_received}`). On disconnect and reconnect, this in-memory state is lost. The receiver requests the file from scratch; the sender restarts from chunk 0. For a 1 GB file with a flaky LAN connection, this means the transfer never completes.

**Warning signs:**
- File transfer restarts from 0% after any connection hiccup
- Progress bar resets on peer reconnect
- SQLite has no `file_transfers` table (in-memory only)

**Prevention strategy:**
- Persist transfer state in a `file_transfers` SQLite table: `(transfer_id, direction, peer_id, filename, total_chunks, last_ack_chunk, file_path_local, status)`. Update `last_ack_chunk` each time a chunk batch is acknowledged.
- On reconnect (after sync), both peers exchange their `file_transfers` table status. If a transfer is `in_progress`, the sender resumes from `last_ack_chunk + 1`.
- The `transfer_id` must be generated by the sender and included in all chunk frames — consistent with the stable message ID approach from P3.
- Chunk ACKs should be cumulative (like TCP): the receiver ACKs the highest contiguous chunk received, not individual chunks, to avoid ACK storm.

**Phase:** Phase 4 (file transfer). The SQLite schema for transfer state must be in place before resumability is attempted.

---

### F4 — Storing Received Files in a World-Readable Temp Directory

**What goes wrong:** A common shortcut is to write received file chunks to `tempfile.gettempdir()` (e.g., `/tmp` on Linux, `C:\Users\<user>\AppData\Local\Temp` on Windows). On Linux, `/tmp` is world-readable by default. Any other user on the machine can read files received via an "end-to-end encrypted" channel. This directly contradicts the E2E encryption guarantee.

**Warning signs:**
- Received files written to `/tmp/localdiscord_<filename>` or similar
- No `chmod` applied after writing
- File path logged at INFO level, exposing the temp path to other users reading logs

**Prevention strategy:**
- Write received files to `~/.localdiscord/received/` (already the app's config directory, which should have 0700 permissions per the fix recommended in CONCERNS.md).
- Apply `os.chmod(path, 0o600)` immediately after writing the final assembled file.
- For chunk assembly, write to a `.part` file in the same directory, rename to the final filename atomically on completion.
- Log file receipt at DEBUG level (not INFO) to avoid exposing filenames in the console log.

**Phase:** Phase 4 (file transfer). Establish the file storage path policy before writing any chunk assembly code.

---

## Search Pitfalls

### SR1 — Full-Table Scan for Search Without FTS Index

**What goes wrong:** A `SELECT * FROM messages WHERE content LIKE '%query%'` scan on a large history table is O(n) in the number of rows. With "keep all history forever" (PROJECT.md), a user who has been running the app for a year may have hundreds of thousands of rows. A LIKE scan on 500,000 rows takes 2-5 seconds in SQLite on typical hardware. The search call will block the Qt main thread (if called synchronously) or, if called in a worker thread, the result will still arrive late, making search feel broken.

**Warning signs:**
- Search results take more than 500ms for any query
- UI becomes unresponsive during search (if search is synchronous)
- Performance degrades linearly as history grows

**Prevention strategy:**
- Create a SQLite FTS5 virtual table (`CREATE VIRTUAL TABLE messages_fts USING fts5(content, sender_name, content='messages', content_rowid='id')`). FTS5 is part of the Python `sqlite3` module's default SQLite build and needs no additional dependency.
- Populate FTS5 at insert time: for every new message written to `messages`, insert the plaintext content into `messages_fts`.
- Run search in a dedicated background thread (a new `SearchWorker` QThread or a `QRunnable`) that emits results back to the main thread via a Qt signal on `_Bridge`. This mirrors the existing worker-to-main-thread pattern.
- Limit results to the first 200 matches and paginate on demand.

**Phase:** Phase 5 (search). Design FTS5 into the initial SQLite schema in Phase 1 so the index is populated from the start — retrofitting FTS5 onto an existing large database requires a full rebuild of the index, which can take minutes on old data.

---

### SR2 — Searching Across DMs and Channels Without Permission Scoping

**What goes wrong:** PROJECT.md specifies "basic text search across all conversations." Without explicit scoping, a search for a person's name may surface private DM conversations that the user did not intend to expose in search results. This is especially important if the search results widget displays message previews in a list visible to anyone looking over the user's shoulder.

**Warning signs:**
- Search results intermix group channel messages and DMs with no visual distinction
- No filter to restrict search to "current channel," "all channels," or "DMs only"
- Message preview in search results shows full message content

**Prevention strategy:**
- The search query must accept a `scope` parameter: `channel_id`, `dm_peer_id`, or `all`. Default scope to the currently active channel/DM, not global.
- In the UI, provide a scope selector (dropdown or radio buttons) before the search box.
- Truncate message previews in search results to 80 characters to limit inadvertent exposure.
- This also sets the foundation for future read-receipt or notification features that need to distinguish channel vs DM context.

**Phase:** Phase 5 (search). Define scope during search design, not as a post-launch addition.

---

## Cross-Cutting Pitfalls

### X1 — Adding SQLite Migrations Without a Schema Version Table

**What goes wrong:** The schema will evolve across phases: Phase 1 adds `messages` and `peers`; Phase 2 adds `sync_state`; Phase 3 adds `direct_messages` and `pending_dms`; Phase 4 adds `file_transfers`. If there is no schema version table, existing users upgrading to a new release will have an old schema. The app will crash on `OperationalError: no such column` or silently fail on queries that reference new columns. In a P2P app with no update server, users upgrade at their own pace — the schema mismatch can persist across peers indefinitely.

**Warning signs:**
- `OperationalError: no such column` in logs after upgrade
- App crashes on startup for users who ran a previous version
- No `schema_version` table in the SQLite database

**Prevention strategy:**
- On startup, run a `PRAGMA user_version` check. If the stored version is less than the current version, run migration scripts in order. This is standard SQLite practice and requires no third-party library.
- Define migrations as a list of SQL strings indexed by version: `MIGRATIONS = {1: "CREATE TABLE messages ...", 2: "ALTER TABLE messages ADD COLUMN seq INTEGER", ...}`.
- Apply migrations inside a transaction so a failed migration leaves the database unchanged.
- The `Config` class already handles version-aware config merging — apply the same pattern to the database schema.

**Phase:** Phase 1 (persistence). Build the migration system on day one before shipping any schema.

---

### X2 — Breaking the Existing Group Channel Flow During Feature Addition

**What goes wrong:** This is a brownfield project. The existing `MessageBroker.store_message()` → listener callbacks → Qt signal → `MainWindow._on_message()` pipeline works today. Adding persistence, DM routing, and new message types to this pipeline without regression testing will break the group channel display. Common failures: adding an extra `if` branch in `_on_message()` that incorrectly classifies group messages as DMs, or adding a `store_message_persistent()` call that throws an exception swallowed by the bare `except` in the listener (CONCERNS.md) — silently stopping group message display.

**Warning signs:**
- Group channel messages stop appearing in the UI after a persistence commit is merged
- New DM messages appear in the group channel display
- The bare `except Exception: pass` in `messaging.py` masking a real database error

**Prevention strategy:**
- Before adding any new feature, write integration tests that cover the baseline: send a group channel message, verify it appears in the in-memory history and in the UI bridge signal. These tests act as a regression gate.
- Fix the bare `except Exception: pass` in `messaging.py` (CONCERNS.md tech debt) before adding persistence — without this fix, database errors are invisible.
- Use feature flags in the config (`config.get("features.persistence_enabled")`) to ship new code paths as opt-in initially, keeping the existing path unchanged until the new path is proven.
- The `Message` dataclass's `message_type` field should be the single routing key — do not add routing logic based on channel name patterns.

**Phase:** All phases. Establish the regression test baseline before Phase 1 and maintain it through Phase 5.

---

### X3 — Ignoring the Thread-Unsafe MainWindow State During Feature Addition

**What goes wrong:** CONCERNS.md identifies `MainWindow` as fragile: network threads call `_bridge` signals, and if a signal is connected incorrectly, the UI enters an inconsistent state. Adding DM sidebar widgets, file transfer progress bars, and search result panels all extend this fragile area. A common mistake is to directly update a new DM widget from a network callback thread (e.g., `self._dm_widget.append_message(msg)` called from `ConnectionHandler.recv_thread`) instead of routing through `_bridge`. This causes Qt "QObject: Cannot create children for a parent that is in a different thread" warnings, random crashes, or silent UI corruption.

**Warning signs:**
- Qt cross-thread warning in logs: "QObject used from a different thread"
- DM sidebar updates appear out of order or with missing messages
- Progress bars for file transfer flicker or never update
- Crashes that only occur under concurrent peer activity

**Prevention strategy:**
- Every new UI widget that receives data from network threads MUST be updated only through a new signal on `_Bridge`. The `_Bridge` class should be extended for each new event type (`dm_received`, `file_progress`, `search_result`), never bypassed.
- Add an `assert threading.current_thread() is threading.main_thread()` guard at the top of every `MainWindow` slot method (`_on_dm_received`, `_on_file_progress`, etc.) during development. This converts silent corruption into an immediate crash with a useful traceback.
- The `sync()` method for rebuilding UI state from scratch (recommended in CONCERNS.md for peer list divergence) should be extended to also reconcile DM sidebar state.

**Phase:** All phases. Establish the `_Bridge` extension pattern in Phase 3 (DM) when the first new UI widget is added.

---

### X4 — Expanding the Wire Protocol Without Version Negotiation

**What goes wrong:** New message types (`sync_request`, `sync_batch`, `dm`, `file_chunk`, `file_ack`) are added to the wire format. A peer running the old version receives an unknown `msg_type` and panics, closes the connection, or silently drops the message. In a mixed-version LAN (some users upgraded, some not), the new peer drops from the old peer's view every time it tries to sync, making the app appear broken for old-version users.

**Warning signs:**
- Old-version peers immediately disconnect after reconnect when a new-version peer is present
- Unknown `msg_type` entries visible in logs on the old-version side
- Feature works between two new-version peers but breaks with any old-version peer

**Prevention strategy:**
- Add a `protocol_version` field to the existing HELLO handshake message. After handshake, both sides know the other's version and can negotiate the feature set.
- Old-version code (which does not know the `protocol_version` field) will see it as an unknown field and ignore it — this is safe because the existing JSON parsing does not enforce strict field validation.
- New-version code should gracefully degrade: if the peer's `protocol_version` is below the sync-capable minimum, skip sync entirely. If below DM-capable minimum, disable the DM button for that peer.
- Document the protocol version negotiation in the architecture notes so future features follow the same pattern.

**Phase:** Phase 2 (sync). Introduce protocol versioning when the first new message type is added.

---

## Summary Table

| ID  | Area          | Severity | Phase to Address |
|-----|---------------|----------|-----------------|
| P1  | Persistence   | Critical | Phase 1         |
| P2  | Persistence   | Critical | Phase 1         |
| P3  | Persistence   | High     | Phase 1 (schema)|
| S1  | Sync          | High     | Phase 2         |
| S2  | Sync          | Medium   | Phase 2         |
| S3  | Sync          | High     | Phase 2         |
| D1  | DMs           | Medium   | Phase 3         |
| D2  | DMs           | High     | Phase 3         |
| F1  | File Transfer | High     | Phase 4         |
| F2  | File Transfer | Critical | Phase 4         |
| F3  | File Transfer | Medium   | Phase 4         |
| F4  | File Transfer | High     | Phase 4         |
| SR1 | Search        | Medium   | Phase 5 (FTS setup Phase 1) |
| SR2 | Search        | Low      | Phase 5         |
| X1  | Cross-cutting | High     | Phase 1         |
| X2  | Cross-cutting | High     | All phases      |
| X3  | Cross-cutting | High     | Phase 3+        |
| X4  | Cross-cutting | Medium   | Phase 2         |

---

*Generated: 2026-02-24 | Codebase: Panchayti (LocalDiscord) | Target: .planning/research/PITFALLS.md*
