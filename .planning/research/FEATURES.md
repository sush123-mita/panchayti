# Features Research — P2P LAN Chat Feature Expansion

**Research date:** 2026-02-24
**Scope:** Chat persistence, message sync, direct messaging, file transfer, search
**Project:** Panchayti — P2P LAN chat app (Python/PyQt6, X25519+AES-256-GCM, SQLite target)

---

## How These Features Work in P2P LAN Chat Applications

### Chat Persistence

In centralized chat (Slack, Discord), the server holds the source of truth. In P2P, each node
owns its own copy of history. This is the fundamental difference: persistence is local-first,
sync happens peer-to-peer on reconnect.

**Standard pattern:**
- Each client writes received and sent messages to a local SQLite database.
- Messages are indexed by (channel, timestamp) or (conversation_id, sequence_number).
- On app launch, history is loaded from the local DB and rendered into the chat view.
- The DB is append-only in practice — no edits or deletes of history content.

**Expected behavior:**
- App opens: all prior messages are visible immediately, before any peers connect.
- Restart: no gap in history display; messages stored include ones you sent.
- Peers offline: history is still readable from local DB.

**Complexity:** Low-medium. SQLite write path is straightforward; the schema design and
migration strategy add moderate complexity.

---

### Message Sync (On Reconnect)

Since there is no server buffering offline messages, peers must exchange missed messages when
they reconnect. Two main approaches exist in LAN P2P tools:

**Approach A — Sequence numbers (simplest for small networks):**
Each node keeps a monotonically-increasing sequence number per sender. On connect, peers
exchange their last-known sequence number for each peer. The peer with newer messages sends
the delta. Works well when network is stable and peer identity is consistent.

**Approach B — Vector clocks / Lamport timestamps:**
Each message carries a logical clock value. On reconnect, peers exchange their vector clocks
and determine which messages are missing. More correct under concurrency but more complex.

**Expected behavior for a LAN app:**
- Short disconnects (seconds to minutes): all missed messages delivered on reconnect.
- Long disconnects: messages from the period offline are synced in order when you reconnect.
- Messages do not arrive duplicated.
- Peer identity is stable (the existing `peer_id` UUID serves this role).

**Practical approach for this codebase:** Sequence numbers per sender stored in the local DB.
On reconnect handshake, exchange a "sync request" with the last-seen sequence number per peer.
The responding peer sends a batch of missed messages. This is a new message type on the wire
(`"type": "sync_request"` and `"type": "sync_batch"`).

**Complexity:** Medium. Requires careful handling of ordering, deduplication (by message UUID
which already exists), and the new sync wire protocol exchange.

---

### Direct Messaging (DMs)

In P2P apps, DMs are conceptually identical to group channels: they use the same encrypted TCP
connection that already exists between two peers, but the message is tagged with a DM channel
identifier instead of a group channel name.

**Standard pattern:**
- DM conversations are stored as a channel with a deterministic ID, typically derived from
  both participant peer IDs (e.g., sorted UUIDs joined: `dm:<uuid_a>:<uuid_b>`).
- The wire format already carries a `channel` field — DMs just use a DM channel ID.
- The UI presents a sidebar section for DMs separate from group channels.
- Clicking a peer name opens (or creates) the DM thread.

**Expected behavior:**
- Click peer in peer list → DM panel opens, history loads, input focused.
- DM messages are not visible in group channels.
- If peer is offline, the DM panel is visible but sending fails gracefully.
- DMs persist in local history just like group channel messages.

**Complexity:** Low-medium. The networking layer is already correct; the work is schema,
routing logic, and UI (sidebar, conversation switching, unread badge logic).

---

### File Transfer

P2P file transfer bypasses central storage — files move directly between peers over the
existing TCP connection (or a separate transfer connection). This is more complex than text
messages.

**Standard approach:**
1. Sender sends a `file_offer` frame: filename, size, MIME type, transfer ID.
2. Receiver accepts (auto-accept or prompt), sends `file_accept`.
3. Sender streams file in chunks (typically 32KB–256KB per chunk) with sequential chunk IDs.
4. Receiver acknowledges chunk batches and writes to a temp file.
5. On completion, receiver verifies integrity (SHA-256 hash) and moves to final location.
6. Both sides update the UI: progress bar during transfer, clickable link/thumbnail on finish.

**Resumability:** For large files, if the connection drops mid-transfer, on reconnect the
receiver sends the last received chunk ID and the sender resumes from there.

**For inline images:** The sender detects MIME type is image/* and also sends a thumbnail
(JPEG, max ~800x800, generated locally). The receiver displays the thumbnail inline in chat;
clicking opens the full-size file.

**Encryption:** File chunks must be encrypted — each chunk is an AES-GCM ciphertext using the
established per-peer session key (same as text messages).

**Expected behavior:**
- Small files (<5MB): transfer completes in seconds with progress bar.
- Large files: resumable if connection drops.
- Images appear as thumbnails inline in chat.
- Failed transfers report error; user can retry.
- Files land in a configurable Downloads folder (~/.localdiscord/downloads/).

**Complexity:** High. Binary chunked transfer, chunk acknowledgment, hash verification,
thumbnail generation, resume state tracking, and UI progress feedback are all non-trivial.

---

### Message Search

Search in P2P chat apps operates entirely locally against the local message database. There is
no server-side index.

**Standard approaches:**

**SQLite FTS5 (Full-Text Search):** SQLite ships with a built-in full-text search extension.
An FTS5 virtual table is created alongside the messages table. Searching is fast even for
large corpora (millions of messages) on desktop hardware. The FTS5 index is kept in sync with
message inserts automatically.

**Simple LIKE query:** Fallback for apps not using FTS5. `SELECT * FROM messages WHERE content
LIKE '%term%'`. Works but slower and does not support ranking.

**Expected behavior:**
- User types in a search box, results appear as they type (debounced ~300ms).
- Results show: sender name, channel/DM, timestamp, and the matching message with term
  highlighted.
- Clicking a result scrolls to that message in context.
- Search covers all channels and DMs in local history.
- No cross-peer search — you can only search messages stored on your device.

**Complexity:** Low, if SQLite FTS5 is used from the start. Medium if retrofitting onto an
existing DB schema that was not designed for FTS.

---

## Feature Categorization

### Table Stakes (Must Have — Users Leave Without These)

| Feature | Why Table Stakes | Implementation Notes | Complexity |
|---------|-----------------|----------------------|------------|
| **Local chat persistence (SQLite)** | Without this, every restart is a blank slate. Non-negotiable for any chat tool. | Replace in-memory MessageBroker history with SQLite writes. Schema: messages table with (id, type, sender_id, sender_name, channel, timestamp, content, is_dm). | Low-Medium |
| **History loads on app start** | Corollary of persistence. Immediate from DB before network comes up. | Load last N messages per channel on startup from SQLite. | Low |
| **Message deduplication** | Sync without dedup = duplicate messages appearing in history. | UUID field already exists on Message — deduplicate on insert by PRIMARY KEY id. | Low |
| **Direct messaging (DMs)** | Core requirement. Named in PROJECT.md as active milestone goal. | DM channel ID = `dm:<sorted(peer_id_a, peer_id_b)>`. Route in network layer, separate UI sidebar. | Low-Medium |
| **Click-to-open DM** | Expected interaction pattern. Without it, DM is unusable. | Click handler on peer list item → open or create DM channel in UI. | Low |
| **File transfer (basic)** | Named in PROJECT.md. Users expect to share files on a LAN chat tool. | Chunked binary over existing TCP conn, encrypted per chunk. `file_offer` / `file_accept` / `file_chunk` / `file_ack` wire types. | High |
| **Inline image thumbnails** | Named in PROJECT.md. Images in chat without thumbnails are a broken UX. | Generate thumbnail on sender side (Pillow), send alongside full file transfer. Render in QLabel within chat. | Medium |
| **Basic text search** | Users build up history and need to find old messages. Without search, history is inaccessible. | SQLite FTS5 virtual table. Search box in UI, results panel. | Low-Medium |

---

### Differentiators (Competitive Advantage — Go Here to Win)

| Feature | Why Differentiating | Implementation Notes | Complexity |
|---------|-------------------|----------------------|------------|
| **Message sync on reconnect** | Most simple LAN chat tools (NetTalk, LAN Chat, etc.) do NOT sync missed messages. This makes Panchayti more reliable. | Sequence-number-based sync. New wire types: `sync_request` / `sync_batch`. Exchanged after handshake. | Medium |
| **Resumable large file transfer** | Tools that do file transfer often fail silently on large files. Resumability is rare in LAN P2P tools. | Track last-confirmed chunk in a transfer_state table. On reconnect, send `file_resume` with last chunk ID. | Medium-High |
| **File transfer in DMs AND group channels** | Most simple tools separate these. Supporting both consistently is a differentiator. | Channel field already in wire format. File transfer frames carry `channel` field. | Low (once core transfer works) |
| **Persistent DM history** | Many LAN tools treat DMs as ephemeral. Full persistent history for DMs is a step up. | DM messages stored in same messages table with `is_dm=1` or channel naming convention. | Low (if persistence is in place) |
| **Thumbnail + full-size image** | Inline thumbnails with click-to-expand is Discord-quality UX, rare in LAN tools. | Two-stage: thumbnail frame (small JPEG bytes inline), full file via normal file transfer. | Medium |
| **Search across all conversations** | Most LAN chat tools have no search at all. Cross-channel search in one UI is strong. | Single FTS5 index over all messages regardless of channel. Filter UI by channel/DM optional. | Low (with FTS5) |

---

### Anti-Features (Deliberately NOT Build)

| Anti-Feature | Reason |
|-------------|--------|
| **Cloud sync or central message server** | Directly contradicts the P2P architecture and threat model. Would require server infrastructure and destroy the privacy guarantee. |
| **Auto-deletion / message expiry** | PROJECT.md explicitly states "keep all history forever." Adding expiry adds complexity and is not wanted. |
| **Read receipts / typing indicators** | Explicitly deferred in PROJECT.md. Adds state management complexity, requires presence protocol extensions, and is not core. |
| **Message reactions / emoji picker** | Deferred in PROJECT.md. Adds non-trivial UI complexity (reaction state sync across P2P peers has fan-out issues). |
| **Voice or video calls** | Out of scope in PROJECT.md. Requires a completely different protocol stack (WebRTC or custom RTP), not incrementally addable. |
| **Cross-device sync** | No central server means no cross-device sync without building a relay — which breaks the P2P model. Out of scope. |
| **End-to-end encrypted group file broadcast** | Sending a file to all peers simultaneously would require re-encrypting per peer (no group key). Keep file transfer as unicast (sender-to-one-peer at a time, user selects recipient). |
| **Full-text search across peers** | Network search (query other peers' local DBs) adds complexity, latency, and privacy concerns. Local-only search is sufficient and correct. |
| **File transfer resume across different peers** | Resume state is tied to a transfer session between two specific peers. Do not attempt cross-peer resume. |

---

## Feature Dependency Map

```
SQLite persistence
    └── is required by: History on startup
    └── is required by: Message sync (needs DB sequence numbers)
    └── is required by: DM history
    └── is required by: Search (FTS5 index)

Message deduplication
    └── is required by: Message sync (batched resend needs dedup)

DM channel routing
    └── requires: SQLite persistence (for DM history)
    └── is required by: File transfer in DMs

File transfer (core)
    └── requires: SQLite persistence (transfer state tracking)
    └── is required by: Inline image thumbnails (thumbnail is a file transfer variant)
    └── is required by: File transfer in DMs (channel routing)
    └── is required by: Resumable transfers (builds on core chunking)

Inline image thumbnails
    └── requires: File transfer (core)
    └── requires: Pillow (already likely available or easy to add)

Message sync on reconnect
    └── requires: SQLite persistence (sequence numbers stored in DB)
    └── requires: New wire protocol types (sync_request, sync_batch)

Basic search
    └── requires: SQLite persistence
    └── requires: FTS5 (ships with SQLite — no extra dependency)
```

**Build order implied by dependencies:**
1. SQLite persistence + deduplication (everything else depends on this)
2. History load on startup
3. DM channel routing + UI sidebar
4. Message sync on reconnect
5. File transfer core (chunked, encrypted)
6. Inline image thumbnails (extends file transfer)
7. Resumable file transfer (extends file transfer)
8. Basic text search (FTS5 on top of existing DB)

---

## Complexity Summary

| Feature | Complexity | Primary Risk |
|---------|-----------|-------------|
| SQLite persistence | Low-Medium | DB schema must be right first time; migrations add risk later |
| History on startup | Low | Trivial query, must handle large history performantly |
| Message deduplication | Low | PRIMARY KEY constraint on message UUID handles this |
| DM routing + UI sidebar | Low-Medium | UI layout and conversation switching state |
| Message sync on reconnect | Medium | Ordering, dedup, and new wire protocol types |
| File transfer core | High | Chunking, encryption per chunk, ACK protocol, error handling |
| Inline image thumbnails | Medium | Pillow dependency, image resizing, inline Qt widget rendering |
| Resumable file transfers | Medium-High | Transfer state persistence, resume handshake protocol |
| File transfer in DMs | Low | Channel field already exists; routing handles it |
| Basic text search | Low-Medium | FTS5 setup straightforward; UI for results is more work |

---

## Notes on This Codebase Specifically

- The existing `Message` dataclass already has `id` (UUID), `channel`, `sender_id`, `sender_name`,
  `timestamp` — the SQLite schema maps directly from these fields. No structural changes needed.
- `MessageBroker.store_message()` is the single write path — adding SQLite writes here is a
  clean extension point (the docstring even says "add persistent storage by replacing store_message()").
- The wire format already carries `channel` — DMs are purely a naming convention change on channel IDs.
- `network.py` `_on_frame()` has a comment "Future: handle 'file', 'voice_signal', 'ack', etc." —
  file transfer frames fit directly into this dispatch pattern.
- The handshake in `_finalise()` is the natural injection point for the sync request exchange
  after a connection is established.
- All history is currently in-memory in `MessageBroker._history` — this dict can remain as a
  read cache (loaded from SQLite on startup) with writes going to both DB and the cache.

---

*Research by: Claude Code (claude-sonnet-4-6) — 2026-02-24*
