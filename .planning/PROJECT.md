# Panchayti (LocalDiscord) — Feature Expansion

## What This Is

A peer-to-peer LAN chat application that lets users on the same local network communicate without any central server. Built with Python/PyQt6 with E2E encryption, multi-mechanism peer discovery, and a dark-themed desktop UI. This milestone adds persistent chat history, direct messaging, file/image transfer, and message search.

## Core Value

Users can communicate privately on their local network with full message history that persists across sessions and syncs between peers on reconnect.

## Requirements

### Validated

- ✓ P2P peer discovery via UDP broadcast, multicast, mDNS, and relay — existing
- ✓ End-to-end encryption (X25519 ECDH + AES-256-GCM) — existing
- ✓ Group channel text chat — existing
- ✓ Cross-platform deployment (Windows exe, Linux .deb, pip install) — existing
- ✓ Dark-themed PyQt6 desktop UI with peer list and channel list — existing
- ✓ Thread-safe networking with per-connection handler threads — existing
- ✓ JSON-based user configuration with persistent peer identity — existing

### Active

- [ ] Chat history persisted locally on each device (SQLite)
- [ ] Message sync between peers on reconnect (exchange missed messages)
- [ ] Person-to-person direct messaging with DM sidebar in UI
- [ ] Click peer name in peer list to open/resume DM conversation
- [ ] File transfer with progress bars and resumable large file support
- [ ] Inline image preview in chat (thumbnail + click to view full size)
- [ ] File/image transfer in both group channels and DMs
- [ ] Basic text search across all conversations
- [ ] Keep all message history forever (no auto-deletion)

### Out of Scope

- Mobile app — desktop-first, P2P model doesn't suit mobile well
- Cloud sync / central server — contradicts P2P architecture
- Voice/video calls — significant complexity, different protocol stack
- OAuth / user authentication — local network trust model is sufficient
- Message reactions / emoji picker — nice-to-have, not core
- Read receipts / typing indicators — defer to future

## Context

- Brownfield project with established P2P networking architecture
- Current message storage is in-memory only (MessageBroker) — no persistence layer
- Existing wire format is length-prefixed JSON over TCP with encryption
- File transfer will need chunked binary transfer protocol (separate from text messages)
- UI already has channel list and peer list panels — DM sidebar extends this pattern
- Message sync requires some form of vector clock or sequence numbering to detect gaps
- All transfers must remain encrypted end-to-end

## Constraints

- **Architecture**: Must remain fully P2P — no central server or coordinator
- **Encryption**: All data (messages, files, metadata) must be E2E encrypted
- **Storage**: SQLite for local persistence — lightweight, no server process
- **Compatibility**: Must not break existing group channel functionality
- **Platform**: Must continue working on Windows, macOS, and Linux

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SQLite for chat persistence | Lightweight, embedded, no server needed — fits P2P model | — Pending |
| Sync on reconnect (not real-time relay) | P2P has no server to buffer offline messages; sync when both online | — Pending |
| DM as sidebar alongside channels | Familiar UX pattern (like Discord/Slack), preserves existing channel model | — Pending |
| Chunked file transfer with progress | Large files need resumability and user feedback | — Pending |
| Inline image preview | Better UX for image sharing, thumbnails keep chat readable | — Pending |
| Keep all history forever | Users want complete archive, let them manage their own storage | — Pending |

---
*Last updated: 2026-02-24 after initialization*
