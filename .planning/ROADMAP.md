# Roadmap: Panchayti Feature Expansion

## Overview

This milestone layers five interconnected capabilities onto the existing P2P LAN chat foundation — persistent chat history, direct messaging, message sync on reconnect, file transfer with inline image previews, and full-text search. The dependency chain is non-negotiable: SQLite persistence is the root every other phase builds on. Phases execute in strict order because each phase's data schema and wire protocol are prerequisites for the next.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Storage Foundation** - Introduce SQLite persistence so all messages survive app restarts
- [ ] **Phase 2: Direct Messaging** - Add 1-on-1 DM conversations with sidebar UI and persistent history
- [ ] **Phase 3: Message Sync** - Exchange missed messages automatically when peers reconnect
- [ ] **Phase 4: File Transfer** - Send files and images over encrypted chunked transfer with progress bars
- [ ] **Phase 5: Search** - Full-text search across all conversations via FTS5

## Phase Details

### Phase 1: Storage Foundation
**Goal**: All messages are written to a local SQLite database and loaded back on startup, so users never lose chat history across app restarts
**Depends on**: Nothing (first phase)
**Requirements**: PERS-01, PERS-02, PERS-03, PERS-04
**Success Criteria** (what must be TRUE):
  1. User closes and reopens the app and sees all prior group channel messages exactly as they were before closing
  2. Messages appear in chat immediately on startup, before any peers have connected
  3. Sending the same message twice (simulated duplicate) results in only one message appearing in the history
  4. Changing the schema (adding a column) via a migration runs without crashing and preserves existing data
**Plans**: TBD

### Phase 2: Direct Messaging
**Goal**: Users can open private 1-on-1 conversations with peers, stored persistently and separate from group channels
**Depends on**: Phase 1
**Requirements**: DM-01, DM-02, DM-03, DM-04
**Success Criteria** (what must be TRUE):
  1. User clicks a peer's name in the peer list and a DM conversation opens in the chat area
  2. DM conversations appear in a separate sidebar section, visually distinct from group channels
  3. User closes and reopens the app and finds DM history intact for all prior conversations
  4. A message sent in a DM does not appear in any group channel view
**Plans**: TBD

### Phase 3: Message Sync
**Goal**: When two peers reconnect after being offline, both automatically receive messages they missed during the disconnection
**Depends on**: Phase 2
**Requirements**: SYNC-01, SYNC-02
**Success Criteria** (what must be TRUE):
  1. Peer A sends messages while Peer B is offline; when Peer B reconnects, B's chat history fills in the missed messages without manual action
  2. Synced messages appear in correct chronological order and no message appears twice even after repeated reconnects
**Plans**: TBD

### Phase 4: File Transfer
**Goal**: Users can send files and images to peers in both group channels and DMs, with visible progress and the ability to resume interrupted transfers
**Depends on**: Phase 3
**Requirements**: FILE-01, FILE-02, FILE-03, FILE-04, FILE-05
**Success Criteria** (what must be TRUE):
  1. User selects a file to send and sees a progress bar that updates as the transfer proceeds; recipient receives the complete file
  2. User sends an image and it appears as an inline thumbnail in the chat; clicking the thumbnail opens the full-size image
  3. A large file transfer interrupted mid-way resumes from where it stopped when the peer reconnects, without re-sending the whole file
  4. File transfer works from both a group channel and a DM conversation
  5. Received file's SHA-256 hash matches the sent file's hash (verifiable via a hash check)
**Plans**: TBD

### Phase 5: Search
**Goal**: Users can search the full text of all message history across channels and DMs from a single search panel
**Depends on**: Phase 4
**Requirements**: SRCH-01, SRCH-02
**Success Criteria** (what must be TRUE):
  1. User opens the search panel (Ctrl+F), types a word, and sees results from across all conversations
  2. Each search result displays the sender name, channel or DM context, timestamp, and a snippet of the matching message text
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Storage Foundation | 0/? | Not started | - |
| 2. Direct Messaging | 0/? | Not started | - |
| 3. Message Sync | 0/? | Not started | - |
| 4. File Transfer | 0/? | Not started | - |
| 5. Search | 0/? | Not started | - |

---
*Roadmap created: 2026-02-24*
*Last updated: 2026-02-24 after initial creation*
