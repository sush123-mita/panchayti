# Project Research Summary

**Project:** Panchayti (LocalDiscord) — P2P LAN Chat Feature Expansion
**Domain:** Local-area P2P chat application with E2E encryption
**Researched:** 2026-02-24
**Confidence:** HIGH

## Executive Summary

Panchayti is a brownfield P2P LAN chat application built in Python/PyQt6 with X25519 ECDH + AES-256-GCM encryption. The project's next milestone adds five interconnected capabilities: persistent chat history, message sync on reconnect, direct messaging, file transfer with inline image previews, and full-text search. Research confirms that all five features integrate cleanly into the existing layered architecture — the networking, encryption, and threading models require extension, not replacement. The single most important architectural decision is to introduce a `StorageManager` (`src/core/storage.py`) as the central SQLite data access layer at the very start, since every other feature depends on it.

The recommended approach is to build in strict dependency order: SQLite persistence first, then DM routing, then sync protocol, then file transfer, then search. This order is non-negotiable because sync requires sequence numbers stored in the DB, DMs require conversation history in the DB, file transfer requires transfer state in the DB, and search requires an FTS5 index populated from the start. Attempting to build any of these out of order creates retroactive schema migrations and rework. The only new runtime dependency is `Pillow` (image thumbnails); all other new capabilities use Python stdlib and existing project libraries.

The three critical risks to manage from day one are: (1) concurrent SQLite writes from multiple recv/send threads without serialization, which causes data loss; (2) storing encrypted ciphertext in the database instead of decrypted plaintext, which causes permanent history loss on restart; and (3) AES-GCM nonce reuse across file chunks, which breaks the encryption security model. Each of these is a silent failure — the app appears to work but data is corrupted or inaccessible. Preventing them requires explicit architectural gates before Phase 1 and Phase 4 code is written.

---

## Key Findings

### Recommended Stack

The project requires minimal new dependencies. `sqlite3` with FTS5 (Python stdlib) handles persistence and search with zero new packages. `Pillow >= 10.0.0` is the only new runtime dependency, needed for thumbnail generation before file transfer. All other capabilities — chunked file framing, SHA-256 integrity checks, path handling, MIME type detection — are covered by Python stdlib. PyQt6 and the `cryptography` library are already installed and provide UI widgets (QProgressBar, QListWidget) and per-chunk AES-GCM encryption respectively.

The key stack-level patterns that shape the implementation: SQLite must run in WAL mode with a single dedicated writer thread (matching the existing `send_thread` pattern); file chunks must use a binary frame type distinct from JSON frames to avoid 33% base64 overhead and prevent OOM on large transfers; image thumbnails are generated on the sender side at 300x300px JPEG before transfer to save bandwidth.

**Core technologies:**
- `sqlite3` (stdlib): Persistence, FTS5 search, sync state — zero-dependency, WAL mode, FTS5 built-in
- `Pillow >= 10.0.0`: Image thumbnail generation — only new runtime dependency, handles all image formats
- `PyQt6` (existing): UI extensions (DM sidebar, file progress, search panel) — no new framework
- `cryptography` (existing): Per-chunk AES-GCM file encryption — same primitive as text messages, fresh nonce per chunk

### Expected Features

All five features are required by PROJECT.md. The dependency map is clear and non-negotiable: SQLite persistence is the foundation everything else builds on. See `.planning/research/FEATURES.md` for the full feature dependency graph.

**Must have (table stakes):**
- Local chat persistence (SQLite) — blank-slate restarts are unacceptable for any chat tool
- History loads on app start — immediate from DB before network peers connect
- Message deduplication — sync without dedup produces duplicate messages in history
- Direct messaging (DMs) — explicitly named in PROJECT.md as active milestone goal
- File transfer with progress — explicitly named in PROJECT.md; LAN chat users expect file sharing
- Inline image thumbnails — explicitly named in PROJECT.md; images without thumbnails are broken UX
- Basic text search — users accumulate history and need to find old messages

**Should have (competitive differentiators):**
- Message sync on reconnect — rare in LAN tools; makes Panchayti more reliable than alternatives
- Resumable large file transfer — most LAN tools fail silently on large files; resumability is a differentiator
- Persistent DM history — most LAN tools treat DMs as ephemeral; full history is a step up
- Search across all conversations — most LAN tools have no search at all

**Defer (v2+):**
- Read receipts and typing indicators — deferred in PROJECT.md; adds presence protocol complexity
- Message reactions / emoji picker — deferred in PROJECT.md; reaction sync has fan-out issues in P2P
- Voice or video calls — out of scope; requires entirely different protocol stack
- SQLite encryption at rest (SQLCipher) — valid future hardening, not required for this milestone
- Cross-device sync — breaks P2P model; requires a relay server

### Architecture Approach

All new features integrate by extending the existing layered architecture rather than replacing it. A new `StorageManager` sits beneath `MessageBroker` as the single database access point. A `SyncManager` handles reconnect protocol. A `FileTransferManager` handles chunked binary transfer. A `SearchManager` wraps FTS5 queries. The UI gains a DM sidebar panel, file progress widget, and search panel, all wired through the existing `_Bridge` Qt signal mechanism. The critical rule: all new UI updates from network threads must route through `_Bridge` signals, never directly into widget methods. All new message types (DM, sync, file) flow through the same encrypted TCP channel, dispatched by type in `NetworkManager._on_frame()`.

**Major components:**
1. `StorageManager` (`src/core/storage.py`) — SQLite DAO; single writer thread; messages, file_transfers, sync_state, messages_fts tables; stores plaintext after decryption
2. `SyncManager` (`src/core/sync.py`) — reconnect sync protocol using per-sender sequence numbers; bidirectional with role negotiation to prevent deadlock
3. `FileTransferManager` (`src/core/file_transfer.py`) — binary-framed chunked transfer (64KB chunks); per-chunk AES-GCM encryption with fresh random nonces; resume state in SQLite
4. `SearchManager` (`src/core/search.py`) — FTS5 MATCH queries via StorageManager; sub-100ms on typical history; runs in background thread
5. UI extensions (`dm_panel.py`, `file_transfer.py`, `search_panel.py`) — all updates via `_Bridge` signals; new panels follow existing widget patterns

### Critical Pitfalls

1. **Concurrent SQLite writes without serialization (P1 — Critical)** — Use a single dedicated writer thread with `queue.Queue`; enable WAL mode. Fix the bare `except Exception: pass` in `messaging.py` before Phase 1 or database errors will be silently swallowed.
2. **Storing ciphertext instead of plaintext in the DB (P2 — Critical)** — Write SQLite rows from the already-decrypted `Message` object after `EncryptionManager.decrypt()`, never from the wire-format dict. Session keys are ephemeral; ciphertext stored in the DB is permanently unreadable after restart.
3. **AES-GCM nonce reuse across file chunks (F2 — Critical)** — Use `os.urandom(12)` per chunk (same as existing text message path). Counter-based nonces starting at 0 break AES-GCM confidentiality and integrity for the entire session.
4. **Sync deadlock on bidirectional reconnect (S3 — High)** — Use the existing `peer_id` UUID for role negotiation: lower peer_id is sync initiator. Without this, both peers simultaneously fill each other's TCP send buffers and block.
5. **No schema versioning from day one (X1 — High)** — Implement `PRAGMA user_version` migration system in Phase 1 before any schema ships. Schema will change across all 5 phases; without migration tracking, upgrades crash existing users.

---

## Implications for Roadmap

Research establishes a clear, non-negotiable phase order driven by a hard dependency chain. Every feature sits on the SQLite foundation; phases 2-5 can only build safely once Phase 1 is solid.

### Phase 1: Storage Foundation
**Rationale:** Every subsequent phase depends on SQLite persistence. Building this first eliminates the risk of schema rework when DM, sync, file transfer, or search tables need to be added. The FTS5 index must be created now so all messages are indexed from the first message stored — retrofitting FTS5 onto an existing large database requires a full rebuild.
**Delivers:** `StorageManager` with complete schema (messages, file_transfers, sync_state, messages_fts), MessageBroker writing to SQLite on every message, history loaded from DB on startup, WAL mode, writer thread, schema migration system, and the regression test baseline.
**Addresses:** Chat persistence, history on startup, message deduplication (PRIMARY KEY on message_id).
**Avoids:** P1 (concurrent writes), P2 (ciphertext storage), P3 (unstable message IDs), X1 (schema versioning), X2 (regression baseline established here).
**Research flag:** Standard patterns — SQLite WAL + queue writer is well-documented. No additional research needed.

### Phase 2: Direct Messaging
**Rationale:** DM is the highest user-visible feature and is relatively self-contained once persistence is in place. It reuses existing TCP connections and channel display widgets. Building DMs before sync means the sync protocol can cover DM conversations from the start. This is the phase where new UI widget patterns (`_Bridge` extension, DM sidebar) are established — getting this pattern right here prevents X3 (thread-unsafe UI) in Phases 4 and 5.
**Delivers:** DM wire type, DM routing in NetworkManager, DM conversation storage in SQLite, DM sidebar panel, peer-click-to-DM interaction, DM history on startup.
**Addresses:** Direct messaging (table stakes).
**Avoids:** D1 (DM as a first-class DB entity, not a mangled channel name), D2 (connection-alive check + pending DM queue), X3 (Bridge pattern extended here), X4 (protocol version field introduced here).
**Research flag:** Standard patterns — DM is a naming convention change on existing channel infrastructure. No additional research needed.

### Phase 3: Message Sync
**Rationale:** Sync depends on Phase 1 (sequence numbers in DB) and benefits from Phase 2 (DM conversations are sync-able). The sync protocol design — bidirectional role negotiation, delta-only sync, batch pagination — must be done before any sync code is written to avoid the deadlock and storm pitfalls.
**Delivers:** SyncManager with sequence-number-based delta sync, `sync_request`/`sync_response` wire types, bidirectional role negotiation, batch pagination (500 messages/batch), deduplication via message_id, sync triggered on peer-connect callback.
**Addresses:** Message sync on reconnect (differentiator).
**Avoids:** S1 (sequence numbers, not wall-clock timestamps), S2 (delta-only with cap, not full history), S3 (role negotiation to prevent deadlock), X4 (protocol version already in place from Phase 2).
**Research flag:** Medium complexity — sync protocol design has well-known patterns but the bidirectional deadlock prevention is easy to get wrong. Consider light research during phase planning to validate the role-negotiation approach.

### Phase 4: File Transfer
**Rationale:** File transfer is the most complex phase and is independent of sync (can be parallelized by a second developer if available). It must come after Phase 1 (transfer state in SQLite) and requires binary framing design before any code is written to avoid the base64 overhead and OOM pitfalls. Inline image thumbnails are a sub-task of this phase, not a separate phase.
**Delivers:** `FileTransferManager` with binary framing (64KB chunks), per-chunk AES-GCM encryption with fresh nonces, SHA-256 end-to-end integrity, progress reporting via `_Bridge`, resume state in SQLite, inline image thumbnails via Pillow, received files stored at `~/.localdiscord/received/` with 0600 permissions.
**Addresses:** File transfer (table stakes), inline image thumbnails (table stakes), resumable large file transfer (differentiator), file transfer in DMs (differentiator).
**Avoids:** F1 (binary frame protocol, not base64 JSON), F2 (fresh random nonce per chunk), F3 (transfer state in SQLite for resumability), F4 (files stored in user-private directory, not /tmp).
**Research flag:** High complexity — binary framing protocol and resume handshake need careful design. Recommend a research-phase spike during planning to validate the binary frame format and chunk ACK protocol before implementation begins.

### Phase 5: Search
**Rationale:** Search is the simplest phase because FTS5 is automatically populated from Phase 1 onward. It has no new network protocol and no new threading concerns. It is best done last so it searches across all conversation types (channels, DMs from Phase 2, synced messages from Phase 3).
**Delivers:** `SearchManager` wrapping FTS5 queries, search panel UI (Ctrl+F), scope selector (current channel / all channels / DMs only), debounced search input (300ms), results with sender/snippet/timestamp, click-to-jump, background search thread.
**Addresses:** Basic text search (table stakes), search across all conversations (differentiator).
**Avoids:** SR1 (FTS5 instead of LIKE scan), SR2 (scope parameter, default to current context, truncated previews).
**Research flag:** Standard patterns — SQLite FTS5 is well-documented. No additional research needed.

### Phase Ordering Rationale

- **Dependency chain drives order:** SQLite is the root dependency. All other phases are leaves or mid-nodes in the dependency graph. No phase can safely start without Phase 1 complete.
- **DM before sync:** DM establishes the new UI widget pattern (`_Bridge` extension) and the new wire type dispatch pattern in one low-risk phase. Sync then benefits from both patterns being proven.
- **File transfer last among complex phases:** It is the most complex and most risky phase. Doing it after simpler phases are stable means the regression baseline is well-established before the hardest work begins.
- **Search as final phase:** It depends only on the DB (Phase 1) and benefits from all earlier phases populating it. It adds no network complexity and is a clean, independent deliverable.
- **Protocol versioning in Phase 2:** The first new wire type (DM) is the right moment to introduce `protocol_version` in the handshake. Waiting until Phase 3 (sync) means Phase 2 DM messages are already unversioned in the wild.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Sync):** Bidirectional sync deadlock prevention and batch pagination are well-known in distributed systems literature but have codebase-specific edge cases. A light research pass on the role-negotiation approach is worthwhile.
- **Phase 4 (File Transfer):** Binary frame protocol design, chunk ACK strategy, and resume handshake need a design spike before coding begins. The interaction between the existing `ConnectionHandler` recv_thread and large binary payloads needs validation.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Storage):** SQLite WAL mode + queue writer + FTS5 setup is textbook. Official Python sqlite3 docs are sufficient.
- **Phase 2 (DMs):** Routing change on existing infrastructure. No novel patterns.
- **Phase 5 (Search):** FTS5 MATCH query with snippet() is documented. UI pattern follows existing widget model.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations are stdlib or existing dependencies except Pillow. Choices are conservative and well-validated. Only one new runtime dependency. |
| Features | HIGH | Feature set is explicitly named in PROJECT.md. Dependency graph is deterministic. Complexity estimates are grounded in codebase analysis. |
| Architecture | HIGH | Architecture research is grounded in direct codebase analysis of the existing files (messaging.py, network.py, encryption.py). Integration points are exact and named. |
| Pitfalls | HIGH | Pitfalls are derived from both general P2P/SQLite patterns and specific CONCERNS.md findings already identified in this codebase. Not speculative. |

**Overall confidence:** HIGH

### Gaps to Address

- **Base64 vs binary framing decision for file chunks:** ARCHITECTURE.md notes base64 as a valid starting point for simplicity, while STACK.md and PITFALLS.md recommend binary framing for performance and to avoid OOM. The Phase 4 design spike should make this call definitively based on expected file sizes and acceptable complexity. Recommendation: start with binary framing to avoid retrofitting later.
- **DM pending queue scope:** PITFALLS.md recommends a `pending_dms` SQLite table for offline DM queuing, but this adds complexity to Phase 2. The roadmap should explicitly decide whether offline DM queuing is in scope for Phase 2 or deferred. Given that message sync (Phase 3) handles missed messages on reconnect, offline queuing may be redundant — this needs a decision during Phase 2 planning.
- **Sync batch size cap:** PITFALLS.md recommends a hard cap of 500 messages per sync reconnect. This means a user offline for a long period will have gaps in history. The UI "sync truncated" notice mentioned in research needs explicit UX design during Phase 3 planning.
- **SQLCipher (DB encryption at rest):** Plaintext storage in SQLite is the correct and intentional design (mirroring the existing "keep all history forever" requirement and the local-trust model). SQLCipher is explicitly deferred. This gap is known and accepted.

---

## Sources

### Primary (HIGH confidence)
- Python `sqlite3` documentation — WAL mode, FTS5 virtual tables, thread safety, `PRAGMA user_version`
- Pillow documentation — `Image.thumbnail()` API, format support matrix
- `cryptography` library docs — AES-GCM nonce requirements for per-chunk encryption
- Direct codebase analysis of Panchayti source (`messaging.py`, `network.py`, `encryption.py`, `config.py`, CONCERNS.md, PROJECT.md)

### Secondary (MEDIUM confidence)
- General P2P LAN chat tool survey (NetTalk, LAN Chat comparisons) — feature gap analysis for differentiators
- SQLite FTS5 documentation — query syntax, `snippet()` function, content tables
- General distributed systems patterns — vector clocks, sequence numbers, sync protocol design

### Tertiary (LOW confidence)
- Binary frame protocol design rationale — inferred from existing length-prefix framing pattern; validate during Phase 4 spike

---

*Research completed: 2026-02-24*
*Ready for roadmap: yes*
