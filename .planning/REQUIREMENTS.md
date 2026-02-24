# Requirements: Panchayti Feature Expansion

**Defined:** 2026-02-24
**Core Value:** Users can communicate privately on their local network with full message history that persists across sessions and syncs between peers on reconnect.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Persistence

- [ ] **PERS-01**: Messages are persisted to local SQLite database on each device
- [ ] **PERS-02**: User sees all prior messages immediately on app startup, before peers connect
- [ ] **PERS-03**: Duplicate messages are prevented via UUID-based deduplication on insert
- [ ] **PERS-04**: Database schema includes migration system (PRAGMA user_version) for future upgrades

### Direct Messaging

- [ ] **DM-01**: User can open a 1-on-1 DM conversation by clicking a peer's name in the peer list
- [ ] **DM-02**: DM conversations appear in a separate sidebar section from group channels
- [ ] **DM-03**: DM messages are stored in local SQLite and persist across sessions
- [ ] **DM-04**: DM messages are not visible in group channels

### File Transfer

- [ ] **FILE-01**: User can send files to a peer with encrypted chunked transfer and progress bar
- [ ] **FILE-02**: User can send images that display as inline thumbnails in chat (click to view full size)
- [ ] **FILE-03**: Interrupted large file transfers can be resumed on reconnect
- [ ] **FILE-04**: File transfer works in both group channels and DM conversations
- [ ] **FILE-05**: Received files are verified via SHA-256 hash integrity check

### Message Sync

- [ ] **SYNC-01**: When two peers reconnect, missed messages are exchanged automatically
- [ ] **SYNC-02**: Synced messages appear in correct chronological order without duplicates

### Search

- [ ] **SRCH-01**: User can search message text across all conversations using a search box
- [ ] **SRCH-02**: Search results show sender, channel/DM, timestamp, and matching text

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### UX Enhancements

- **UX-01**: Read receipts and typing indicators
- **UX-02**: Message reactions and emoji picker
- **UX-03**: Unread message badges on DM conversations
- **UX-04**: Click search result to scroll to message in context

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cloud sync / central server | Contradicts P2P architecture and privacy model |
| Voice or video calls | Completely different protocol stack, not incrementally addable |
| Mobile app | Desktop-first, P2P model doesn't suit mobile well |
| Cross-device sync | No server to coordinate — breaks P2P model |
| Auto-deletion / message expiry | User wants to keep all history forever |
| Cross-peer search | Privacy concerns, latency, complexity — local search sufficient |
| Group file broadcast | Requires re-encrypting per peer (no group key) — keep file transfer unicast |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERS-01 | Phase 1 | Pending |
| PERS-02 | Phase 1 | Pending |
| PERS-03 | Phase 1 | Pending |
| PERS-04 | Phase 1 | Pending |
| DM-01 | Phase 2 | Pending |
| DM-02 | Phase 2 | Pending |
| DM-03 | Phase 2 | Pending |
| DM-04 | Phase 2 | Pending |
| SYNC-01 | Phase 3 | Pending |
| SYNC-02 | Phase 3 | Pending |
| FILE-01 | Phase 4 | Pending |
| FILE-02 | Phase 4 | Pending |
| FILE-03 | Phase 4 | Pending |
| FILE-04 | Phase 4 | Pending |
| FILE-05 | Phase 4 | Pending |
| SRCH-01 | Phase 5 | Pending |
| SRCH-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-02-24*
*Last updated: 2026-02-24 — traceability confirmed after roadmap creation*
