# Architecture Research — P2P Chat Feature Expansion

**Research Type:** Project Research — Architecture dimension
**Date:** 2026-02-24
**Question:** How should SQLite persistence, message sync protocols, chunked file transfer, and search integrate into an existing P2P chat architecture with E2E encryption?

---

## Summary

The existing architecture is a clean, layered P2P system with strong separation of concerns: a network transport layer, a peer discovery layer, a state/registry layer (MessageBroker + PeerRegistry), an encryption layer, and a Qt6 UI layer. All new features — SQLite persistence, direct messaging, message sync, chunked file transfer, inline image preview, and full-text search — integrate by extending the existing layers rather than replacing them. The primary addition is a new Storage Layer (`src/core/storage.py`) that sits beneath MessageBroker, plus a new wire protocol extension for file chunks and sync messages. The UI gains a DM sidebar panel and file transfer widgets within the existing MainWindow pattern.

The most critical architectural insight: all new message types (DM, file-chunk, sync-request, sync-response) flow through the same encrypted TCP channel already established per peer, dispatched by a type field in `NetworkManager._on_frame()`. This keeps the encryption model unchanged and avoids introducing new connection types.

---

## Current Architecture (Baseline)

### Layer Map

```
┌─────────────────────────────────────────────────────┐
│  UI Layer          src/ui/app.py  (MainWindow)       │
│  - Channel list, peer list, chat display             │
│  - _Bridge Qt signals for thread-safe updates        │
└──────────────────┬──────────────────────────────────┘
                   │ depends on
┌──────────────────▼──────────────────────────────────┐
│  State / Registry Layer                              │
│  - src/core/messaging.py  MessageBroker              │
│    (in-memory message history, observer callbacks)   │
│  - src/core/peer.py       PeerRegistry               │
│    (thread-safe peer roster, observer callbacks)     │
└──────┬────────────────────┬───────────────────────┬─┘
       │                    │                       │
┌──────▼──────┐  ┌──────────▼───────┐  ┌───────────▼──┐
│ Encryption  │  │  Network         │  │  Discovery    │
│ Layer       │  │  Transport Layer │  │  Layer        │
│ encryption  │  │  network.py      │  │  discovery.py │
│ .py         │  │  TCP + framing   │  │  UDP/mDNS     │
│ X25519+AES  │  │  ConnectionHandler│  │  broadcast   │
└─────────────┘  └──────────────────┘  └──────────────┘
```

### Key Constraints That Shape New Architecture

1. **Wire format is length-prefixed JSON over encrypted TCP** — new message types must fit or extend this format.
2. **MessageBroker is in-memory only** — SQLite persistence must be added beneath it without breaking the observer/callback contract.
3. **All state is thread-safe via RLock** — new shared state (e.g., pending file transfers) must follow the same pattern.
4. **UI receives events via Qt signals through `_Bridge`** — new UI panels (DM sidebar, file progress) must use the same bridge pattern.
5. **E2E encryption is per-peer session** — all new message types encrypted at the same layer, no change to `EncryptionManager`.

---

## New Architecture — Additions Required

### Component Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  UI Layer  src/ui/app.py  (MainWindow)                                   │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │  Channel Panel  │  │  DM Sidebar      │  │  File Transfer Panel   │  │
│  │  (existing)     │  │  (NEW)           │  │  (NEW)                 │  │
│  │                 │  │  DMConversation  │  │  FileTransferWidget    │  │
│  │                 │  │  widget per peer │  │  progress bars         │  │
│  └─────────────────┘  └──────────────────┘  └────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Search Panel (NEW) — text input → SearchManager → results list    │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────┬─────────────────────┬───────────────────────────┬─────────────┘
           │                     │                           │
┌──────────▼──────────┐ ┌────────▼─────────┐ ┌─────────────▼──────────────┐
│  MessageBroker       │ │  FileTransfer    │ │  SearchManager             │
│  (extended)          │ │  Manager (NEW)   │ │  (NEW)                     │
│  - group channels    │ │  src/core/       │ │  src/core/search.py        │
│  - DM conversations  │ │  file_transfer.py│ │  - FTS5 SQLite queries     │
│  - now calls Storage │ │  - chunked xfer  │ │  - searches all convos     │
│    on every message  │ │  - resume state  │ │  - returns Message refs    │
└──────────┬──────────┘ └────────┬─────────┘ └─────────────┬──────────────┘
           │                     │                           │
           └──────────┬──────────┘                          │
                      │ all read/write                       │ read-only queries
           ┌──────────▼──────────────────────────────────────▼─────────────┐
           │  Storage Layer  src/core/storage.py  (NEW)                     │
           │  StorageManager                                                 │
           │  - SQLite database at ~/.localdiscord/history.db               │
           │  - Tables: messages, peers, file_transfers, sync_state         │
           │  - FTS5 virtual table for full-text search                     │
           │  - Provides: store_message(), get_history(), get_dm_history(), │
           │    search(), record_file_transfer(), get_sync_cursor()         │
           └────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│  Network Transport Layer  src/core/network.py  (extended)                 │
│  NetworkManager._on_frame() dispatch table — new message types added:     │
│  "dm"           → MessageBroker.process_incoming_dm()                     │
│  "file_meta"    → FileTransferManager.on_file_meta()                      │
│  "file_chunk"   → FileTransferManager.on_file_chunk()                     │
│  "file_ack"     → FileTransferManager.on_chunk_ack()                      │
│  "sync_request" → SyncManager.handle_sync_request()                       │
│  "sync_response"→ MessageBroker.replay_sync_batch()                       │
└───────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│  Sync Layer  src/core/sync.py  (NEW)  SyncManager                        │
│  - On peer connect: sends sync_request with local cursor                  │
│  - On receiving sync_request: queries Storage, sends sync_response batch  │
│  - Handles deduplication via message_id                                   │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries

### StorageManager (`src/core/storage.py`)

**Responsibility:** All SQLite I/O. Single point of contact for the database.

**Inputs:** Called by MessageBroker (store/retrieve messages), FileTransferManager (transfer records), SyncManager (sync cursors), SearchManager (queries).

**Outputs:** Returns Message objects, file transfer records, sync state dicts.

**Does NOT know about:** Network, encryption, UI. Purely a data access object (DAO).

**Schema (logical):**

```
messages (
  message_id    TEXT PRIMARY KEY,  -- UUID generated at send time
  channel       TEXT,              -- channel name or peer_id for DMs
  type          TEXT,              -- "channel" | "dm"
  sender_id     TEXT,
  sender_name   TEXT,
  content       TEXT,              -- plaintext (decrypted before storage)
  timestamp     REAL,
  synced_from   TEXT               -- NULL if local, peer_id if received via sync
)

file_transfers (
  transfer_id   TEXT PRIMARY KEY,
  peer_id       TEXT,
  direction     TEXT,              -- "send" | "recv"
  filename      TEXT,
  total_size    INTEGER,
  transferred   INTEGER,
  status        TEXT,              -- "pending" | "active" | "complete" | "failed"
  local_path    TEXT,
  timestamp     REAL
)

sync_state (
  peer_id       TEXT PRIMARY KEY,
  last_seq      INTEGER            -- highest message sequence seen from this peer
)

messages_fts (                     -- FTS5 virtual table
  message_id, content, sender_name
)
```

**Boundary rule:** Messages stored after decryption (plaintext stored locally). The network always transmits ciphertext; the local database always stores plaintext. This means the storage layer is completely decoupled from encryption.

---

### MessageBroker Extensions (`src/core/messaging.py`)

**Responsibility:** Extend existing MessageBroker to call StorageManager on every `store_message()`, and add DM conversation tracking alongside channel history.

**New method:** `get_dm_history(peer_id: str) -> list[Message]` — loads from StorageManager on first access, then serves from in-memory cache.

**DM conversations:** Stored in the same `messages` table with `type="dm"` and `channel=peer_id`. MessageBroker tracks a `_dm_history: dict[str, list[Message]]` alongside the existing `_history: dict[str, list[Message]]` for channels.

**Does NOT change:** The observer callback pattern, the thread locking model, or the wire format. This is an additive change.

---

### SyncManager (`src/core/sync.py`)

**Responsibility:** On peer reconnect, negotiate which messages each side is missing and exchange them.

**Protocol:**

```
Peer A connects to Peer B
→ A sends: { "type": "sync_request", "channels": ["general", "random"], "last_seq": 142 }
← B responds: { "type": "sync_response", "messages": [ ...Message objects for seq 143-158... ] }
→ A sends: { "type": "sync_request", ... from A's perspective }
← B responds: ...
```

**Sequence numbering:** Each peer maintains a local monotonic sequence counter per channel. Stored in `sync_state` table. On reconnect, A sends its last known sequence; B sends all messages it has with seq > that value.

**Deduplication:** `message_id` (UUID) prevents double-insertion if a message arrives both live and via sync.

**Integration point:** SyncManager is triggered from `NetworkManager` when the peer-connected signal fires (after handshake completes). It is called from the existing peer_connected callback in `main.py`.

**Does NOT handle:** File transfer resume (that is FileTransferManager's responsibility). Does NOT relay messages between peers that are not directly connected.

---

### FileTransferManager (`src/core/file_transfer.py`)

**Responsibility:** Chunked binary file transfer with progress reporting, resume support, and inline image thumbnail generation.

**Wire protocol extension:** File transfer uses the same encrypted TCP channel but with binary framing for chunks. The `file_meta` message establishes the transfer; subsequent `file_chunk` frames carry raw binary data. Each chunk is independently encrypted as a separate AES-GCM ciphertext.

**Transfer flow:**

```
Sender                                    Receiver
  │── file_meta (filename, size, hash) ──▶│
  │◀── file_ack (accepted, resume_from) ──│
  │── file_chunk (seq=0, data) ──────────▶│
  │── file_chunk (seq=1, data) ──────────▶│
  │   ...                                 │
  │── file_chunk (seq=N, is_last=true) ──▶│
  │◀── file_ack (complete) ───────────────│
```

**Chunk size:** 64KB per chunk (configurable). Large enough for throughput, small enough for progress granularity.

**Resume:** `file_ack` after reconnect includes `resume_from=seq_N` so sender skips already-received chunks. Transfer state persisted in StorageManager.

**Image preview:** After a file chunk transfer completes for an image (png, jpg, gif, webp), FileTransferManager generates a thumbnail using Python's `Pillow` library (new dependency) and stores it alongside the file. MessageBroker is notified to update the chat display.

**Thread model:** Each active transfer runs in a dedicated send-thread (for outbound) or is handled by the existing recv-thread of the peer's ConnectionHandler (for inbound). Progress updates emitted via a Qt signal through `_Bridge`.

---

### SearchManager (`src/core/search.py`)

**Responsibility:** Full-text search across all stored messages using SQLite FTS5.

**Interface:**

```python
def search(query: str, limit: int = 100) -> list[SearchResult]
```

`SearchResult` is a lightweight dataclass: `message_id`, `channel`, `sender_name`, `snippet` (highlighted match context), `timestamp`.

**Implementation:** Uses SQLite FTS5 `MATCH` operator with `snippet()` function for context highlighting. Runs on the SQLite connection managed by StorageManager. Queries are synchronous but fast enough for interactive use (sub-100ms on typical history sizes).

**UI integration:** A search bar in the main window opens a results panel showing snippets. Clicking a result jumps to the message in the relevant channel or DM conversation.

---

### UI Extensions (`src/ui/app.py` + new files)

**DM Sidebar (`src/ui/dm_panel.py`):**
- New panel added to MainWindow layout (right of channel list, same pattern as existing channel list widget)
- Shows list of peers with open DM conversations
- Clicking a peer entry opens their DM chat view (reuses existing chat display widget)
- Clicking a peer name in the peer list panel opens/creates a DM conversation (single signal wire in `_on_peer_row_clicked`)

**FileTransferWidget (`src/ui/file_transfer.py`):**
- Progress bar widget embedded in chat messages that involve files
- Inline thumbnail for image files after transfer completes
- Click-to-expand for full image view (QLabel in a dialog)

**SearchPanel (`src/ui/search_panel.py`):**
- Triggered by Ctrl+F or toolbar button
- Text input → debounced call to SearchManager → results list widget
- Results show sender, snippet, timestamp; click jumps to conversation

---

## Data Flow

### Sending a Text Message (Extended)

```
User types → MainWindow._send()
  → creates Message with UUID message_id
  → MessageBroker.store_message(msg)
      → appends to in-memory _history
      → StorageManager.store_message(msg)   [NEW — writes to SQLite]
      → notifies observers → UI updates
  → NetworkManager.send_to(peer_id, msg.to_wire())
      → EncryptionManager.encrypt(peer_id, payload)
      → ConnectionHandler.send_queue.put(frame)
      → send_thread drains queue → socket write
```

### Receiving a Text Message (Extended)

```
socket read → ConnectionHandler._recv_thread
  → NetworkManager._on_frame(peer_id, raw_data)
  → EncryptionManager.decrypt(peer_id, ciphertext)
  → type = "text" or "dm" → MessageBroker.process_incoming(peer_id, decrypted)
      → creates Message with sender's message_id
      → StorageManager.store_message(msg)   [NEW — writes to SQLite]
      → notifies observers → _Bridge signal → MainWindow._on_message()
```

### Peer Reconnect / Sync Flow (New)

```
DiscoveryManager finds peer → NetworkManager.connect_to_peer()
  → handshake + key exchange (existing)
  → peer_connected callback fires (existing)
  → SyncManager.initiate_sync(peer_id)   [NEW]
      → StorageManager.get_sync_cursor(peer_id) → last_seq=N
      → NetworkManager.send_to(peer_id, sync_request)
  → remote receives sync_request → SyncManager.handle_sync_request()
      → StorageManager.get_messages_after(seq=N)
      → NetworkManager.send_to(requester_id, sync_response with message batch)
  → local receives sync_response → MessageBroker.replay_sync_batch(messages)
      → for each message: StorageManager.store_message() with dedup check
      → observers notified → chat display updated
```

### File Transfer Send Flow (New)

```
User drags file or clicks attach → MainWindow._on_file_attach()
  → FileTransferManager.send_file(peer_id, filepath)
      → StorageManager.record_file_transfer(transfer_id, ...)
      → NetworkManager.send_to(peer_id, file_meta message)
  → Receiver replies with file_ack
      → NetworkManager._on_frame() → type "file_ack" → FileTransferManager.on_chunk_ack()
      → sends file_chunk frames in loop
      → each chunk: EncryptionManager.encrypt(peer_id, chunk_bytes)
      → progress callback → _Bridge signal → FileTransferWidget updates progress bar
  → final chunk → FileTransferManager marks transfer complete
      → StorageManager updates transfer record
      → If image: generate thumbnail → MessageBroker notified → inline preview shown
```

### Search Flow (New)

```
User types in search bar → debounce 300ms → SearchManager.search(query)
  → StorageManager.fts_search(query)
      → SQLite: SELECT ... FROM messages_fts WHERE messages_fts MATCH ?
  → returns list[SearchResult]
  → SearchPanel populates results list widget
  → User clicks result → MainWindow.jump_to_message(channel, message_id)
```

---

## Encryption Integration

All new message types (DM text, file metadata, file chunks, sync batches) are encrypted using the existing per-peer X25519/AES-256-GCM sessions established during handshake. No changes to `EncryptionManager`.

**Key rule for storage:** Messages are stored in SQLite **after decryption**. The database holds plaintext. This is intentional: the encrypted copy is on the wire; the local device is the trusted boundary. SQLite encryption at rest (e.g., SQLCipher) is out of scope for this milestone but could be added later as a wrapper around StorageManager.

**DM encryption:** DMs use the existing per-peer session key established when the peer connected. No new key derivation needed — DMs are just text messages sent directly to a specific peer's connection (not broadcast to all peers in a channel).

**File chunk encryption:** Each chunk is independently encrypted with a fresh AES-GCM nonce (the existing `EncryptionManager.encrypt()` generates a random nonce per call). This means a chunk replay attack cannot occur because the GCM authentication tag covers the nonce.

---

## Build Order (Dependency Chain)

Each phase depends on the previous phase being complete. Components within a phase can be built in parallel.

### Phase 1 — Storage Foundation
**Build first. Everything else depends on this.**

1. `src/core/storage.py` — StorageManager with SQLite schema, `store_message()`, `get_history()`, `get_dm_history()`, FTS5 table setup
2. Extend `src/core/messaging.py` — MessageBroker calls `StorageManager.store_message()` on every message; load history from SQLite on startup
3. `src/utils/config.py` — add `storage.db_path` config key (default `~/.localdiscord/history.db`)
4. Tests: `tests/test_storage.py` — CRUD, FTS query, migration

**Why first:** All subsequent features (DM, sync, search, file transfer records) require a working persistence layer.

### Phase 2 — Direct Messaging
**Depends on Phase 1 (DM history stored in SQLite).**

1. Extend `NetworkManager._on_frame()` — add `"dm"` type dispatch → `MessageBroker.process_incoming_dm()`
2. Extend `MessageBroker` — `process_incoming_dm()`, `get_dm_history()`, `send_dm()` methods
3. Extend `Message` dataclass — add `dm_recipient_id` field; extend `to_wire()`/`from_wire()`
4. `src/ui/dm_panel.py` — DM sidebar widget (peer list + per-peer conversation view)
5. Wire peer-click in MainWindow peer list panel → open DM conversation
6. Tests: `tests/test_dm.py`

**Why second:** DM is the highest-value user feature and relatively self-contained. It reuses existing channel chat display widgets with minimal new UI.

### Phase 3 — Message Sync
**Depends on Phase 1 (StorageManager provides sync cursor and message retrieval).**

1. `src/core/sync.py` — SyncManager: `initiate_sync()`, `handle_sync_request()`, `handle_sync_response()`
2. Extend `NetworkManager._on_frame()` — add `"sync_request"` and `"sync_response"` dispatch
3. Extend `MessageBroker` — `replay_sync_batch()` with deduplication via `message_id`
4. Add message sequence numbers to `Message` dataclass and StorageManager
5. Wire SyncManager call into peer-connected callback in `main.py`
6. Tests: `tests/test_sync.py` — reconnect scenario, dedup, partial gap fill

**Why third:** Sync requires the storage layer (Phase 1) to know what messages exist locally, and benefits from DM conversations (Phase 2) being sync-able too. However sync does not depend on Phase 2 functionally — it can be built in parallel with Phase 2 if needed.

### Phase 4 — File Transfer
**Depends on Phase 1 (transfer records in SQLite). Independent of Phases 2-3.**

1. `src/core/file_transfer.py` — FileTransferManager: `send_file()`, `on_file_meta()`, `on_file_chunk()`, `on_chunk_ack()`, resume logic
2. Extend `NetworkManager._on_frame()` — add `"file_meta"`, `"file_chunk"`, `"file_ack"` dispatch
3. `src/ui/file_transfer.py` — FileTransferWidget (progress bar, status label)
4. Wire file-attach UI into MainWindow (toolbar button or drag-and-drop)
5. Add `Pillow` dependency for image thumbnail generation
6. Inline image preview in chat display (thumbnail embedded in message bubble)
7. Tests: `tests/test_file_transfer.py` — chunk assembly, resume, hash verification

**Why fourth:** File transfer is the most complex new component (new binary framing, resume logic, thumbnail generation). Building it after the storage foundation avoids rework. It is independent of DM and sync, so could theoretically be parallelized with Phases 2-3 by a second developer.

### Phase 5 — Search
**Depends on Phase 1 (FTS5 table populated by then). Independent of Phases 2-4.**

1. `src/core/search.py` — SearchManager: `search()` wrapping StorageManager FTS5 query
2. `src/ui/search_panel.py` — search bar, results list, jump-to-message
3. Wire Ctrl+F shortcut and toolbar button in MainWindow
4. Tests: `tests/test_search.py` — query matching, snippet extraction, empty results

**Why fifth:** Search only needs the FTS5 table to be populated, which happens automatically as Phase 1 stores messages. It can be built last because it adds no new network protocol and has no dependencies on Phases 2-4 (though it will search DMs if Phase 2 is done first).

---

## New Files Summary

| File | Layer | Purpose |
|------|-------|---------|
| `src/core/storage.py` | Storage | SQLite DAO — all database access |
| `src/core/sync.py` | Sync | Reconnect message sync protocol |
| `src/core/file_transfer.py` | File Transfer | Chunked binary file transfer |
| `src/core/search.py` | Search | FTS5 full-text search |
| `src/ui/dm_panel.py` | UI | DM sidebar widget |
| `src/ui/file_transfer.py` | UI | File progress and inline preview widgets |
| `src/ui/search_panel.py` | UI | Search input and results panel |
| `tests/test_storage.py` | Tests | Storage layer unit tests |
| `tests/test_dm.py` | Tests | DM send/receive tests |
| `tests/test_sync.py` | Tests | Sync protocol tests |
| `tests/test_file_transfer.py` | Tests | File transfer unit tests |
| `tests/test_search.py` | Tests | Search query tests |

---

## Files Modified (Existing)

| File | Change |
|------|--------|
| `src/core/messaging.py` | Add StorageManager integration; add DM methods; add `replay_sync_batch()` |
| `src/core/network.py` | Add new `_on_frame()` dispatch cases for `dm`, `file_meta`, `file_chunk`, `file_ack`, `sync_request`, `sync_response` |
| `src/core/messaging.py` | Add `message_id` UUID field and sequence number to `Message` dataclass |
| `src/ui/app.py` | Add DM panel, search panel, file attach; wire peer-click to DM open; add `_Bridge` signals for file progress |
| `src/main.py` | Instantiate StorageManager, SyncManager, FileTransferManager, SearchManager; pass to components |
| `config/default_config.json` | Add `storage.db_path` key |

---

## Risks and Constraints

**Binary chunks in JSON wire format:** The existing wire format is JSON. File chunks are binary. Two options: (a) base64-encode chunks and keep JSON framing (simple, ~33% overhead), or (b) add a second framing mode for raw binary (efficient, more complex). Recommendation: start with base64 for simplicity (LAN bandwidth is not the bottleneck for typical file sizes); revisit if large file transfer performance is unsatisfactory.

**SQLite concurrency:** SQLite in WAL mode handles concurrent reads with a single writer safely. The existing threading model (one recv-thread and one send-thread per peer) means multiple threads may call StorageManager simultaneously. WAL mode + a dedicated `threading.RLock` in StorageManager is sufficient.

**Sync storm on large history:** If two peers reconnect after a long separation, sync_response could carry thousands of messages. Implement batch pagination: send sync_response in chunks of 500 messages, with a sequence number indicating whether more batches follow.

**DM confidentiality:** DM messages are stored in the local SQLite database in plaintext (same as channel messages). Both peers store the full DM history locally. There is no concept of "delete for both sides" — this matches the existing "keep all history forever" requirement.

**Image thumbnails and Pillow dependency:** Adding Pillow as a new dependency is the only new runtime dependency this milestone introduces. It is a mature, well-maintained library. PyInstaller bundles it automatically; the Debian build script's postinst `pip install` step will install it. No architectural concerns.

---

*Research date: 2026-02-24*
