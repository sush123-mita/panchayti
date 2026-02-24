# Stack Research

**Domain:** P2P LAN chat — adding persistence, sync, file transfer, search
**Researched:** 2026-02-24
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| sqlite3 (stdlib) | Python 3.10+ bundled | Chat history persistence | Zero-dependency, embedded, already bundled with Python. Supports FTS5 for full-text search. Perfect for P2P (no server process). WAL mode enables concurrent reads. |
| Pillow | >=10.0.0 | Image thumbnail generation | De facto Python imaging library. Needed for inline image previews — resize to thumbnails before display. Handles JPEG, PNG, GIF, WebP, BMP. |
| PyQt6 (existing) | >=6.4.0 | UI for DM sidebar, file progress, search panel | Already in use. QProgressBar for file transfers, QListWidget for DM list, QLineEdit for search. No new framework needed. |
| cryptography (existing) | >=41.0.0 | Per-chunk file encryption | Already handles AES-256-GCM for text messages. Same primitives apply to file chunk encryption with per-chunk nonces. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite3 FTS5 | Bundled with Python sqlite3 | Full-text search on message history | Enable at schema creation time. Tokenizer handles natural language queries. Must be set up in Phase 1 so all messages are indexed from the start. |
| hashlib (stdlib) | Python stdlib | File integrity verification | SHA-256 checksums for transferred files. Verify complete file matches sender's hash after all chunks received. |
| pathlib (stdlib) | Python stdlib | Cross-platform file path handling | Use for received file storage paths (~/.localdiscord/received/). Already used in config.py. |
| mimetypes (stdlib) | Python stdlib | File type detection | Determine if a file is an image (for thumbnail generation) vs other file type. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest (existing) | Unit testing for new storage/sync/transfer layers | Already in project. Add fixtures for SQLite in-memory databases. |
| DB Browser for SQLite | Visual schema inspection during development | Optional. Useful for debugging storage layer. |

## Installation

```bash
# Only one new dependency needed
pip install Pillow>=10.0.0

# Everything else is Python stdlib or already in the project
# sqlite3 — stdlib
# hashlib — stdlib
# pathlib — stdlib
# mimetypes — stdlib
# PyQt6 — already installed
# cryptography — already installed
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| sqlite3 (stdlib) | SQLAlchemy | If you need ORM patterns or complex query building. Overkill for this project — direct SQL with parameterized queries is simpler and has zero overhead. |
| sqlite3 (stdlib) | TinyDB / LMDB | TinyDB is JSON-only (no FTS5). LMDB is key-value only. Neither supports full-text search natively. |
| Pillow | PyQt6 QImage | QImage can load/resize images but Pillow has better format support, easier thumbnail generation API (Image.thumbnail()), and better error handling for corrupt images. |
| FTS5 (sqlite3) | Whoosh / Tantivy | External search engines. FTS5 is built into sqlite3, zero-config, and fast enough for local message search. External engines add deployment complexity. |
| hashlib SHA-256 | xxhash / blake3 | Faster hashes, but SHA-256 is stdlib and fast enough for file transfer integrity checks. Avoids adding another dependency. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| peewee / SQLAlchemy ORM | Adds abstraction layer over simple schema. Harder to optimize FTS5 queries. More dependencies. | Direct sqlite3 with parameterized queries |
| aiofiles / asyncio | Existing codebase uses threads, not async. Mixing paradigms causes complexity. | Thread-based I/O with queue.Queue for writes |
| Base64 for file chunks in JSON | 33% size overhead, bloats JSON frames, slows large transfers | Binary frame format (separate from JSON text frames) |
| pickle for serialization | Security risk, not cross-version compatible | JSON for metadata, raw bytes for file chunks |
| FTS3/FTS4 | Older SQLite full-text search. FTS5 is faster, more features, better ranking. | FTS5 |

## Stack Patterns

**For SQLite concurrency:**
- Use WAL (Write-Ahead Logging) mode for concurrent reads during writes
- Single writer thread with queue.Queue (mirrors existing send_thread pattern)
- Read connections can be opened per-thread safely in WAL mode

**For file transfer framing:**
- Use a separate binary frame type (type byte prefix) to distinguish from JSON text frames
- Existing 4-byte length prefix works for both JSON and binary frames
- Add 1-byte type indicator after length: 0x00=JSON, 0x01=binary chunk

**For image thumbnails:**
- Generate on sender side before transfer (saves bandwidth)
- Max thumbnail size: 300x300px, JPEG quality 75
- Store thumbnails alongside messages in SQLite as BLOB or in filesystem with path reference

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| Pillow >=10.0.0 | Python 3.10+ | Full support. Earlier Pillow versions work too but 10.0+ has better WebP and AVIF support. |
| sqlite3 FTS5 | Python 3.10+ (bundled) | FTS5 is included in Python's bundled sqlite3 on all platforms. Verify with `SELECT sqlite_version()`. |
| cryptography >=41.0.0 | Python 3.10+ | Already in project. No version change needed. |

## Sources

- Python sqlite3 documentation — FTS5 support, WAL mode, thread safety
- Pillow documentation — Image.thumbnail() API, format support
- cryptography library docs — AES-GCM nonce requirements for per-chunk encryption
- Existing codebase analysis — threading patterns, frame format, encryption model

---
*Stack research for: P2P LAN chat feature expansion*
*Researched: 2026-02-24*
