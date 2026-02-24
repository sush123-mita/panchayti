# Codebase Structure

**Analysis Date:** 2026-02-24

## Directory Layout

```
panchayti/
├── src/                          # Application source code
│   ├── __init__.py
│   ├── main.py                   # Entry point; wires components together
│   ├── core/                      # Core business logic & networking
│   │   ├── __init__.py
│   │   ├── peer.py               # Peer data model and thread-safe registry
│   │   ├── network.py            # TCP connection management and transport
│   │   ├── discovery.py          # Peer discovery (broadcast/multicast/relay/mDNS)
│   │   ├── encryption.py         # X25519 ECDH + AES-256-GCM encryption
│   │   └── messaging.py          # Message model, broker, and history storage
│   ├── ui/                        # Qt6 user interface
│   │   ├── __init__.py
│   │   ├── app.py                # MainWindow; coordinates UI and network
│   │   └── styles.py             # Dark theme stylesheet
│   └── utils/                     # Utilities and helpers
│       ├── __init__.py
│       ├── config.py             # JSON-based config loader and persistent storage
│       └── logger.py             # Centralized logging setup
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── test_encryption.py        # Encryption tests (key exchange, AES-GCM)
│   ├── test_messaging.py         # Message model tests
│   └── test_discovery.py         # Discovery tests
├── config/                        # Configuration files
│   └── default_config.json       # Default app settings (ports, channels, etc.)
├── assets/                        # Static resources
│   └── icons/                     # Application icons
├── debian/                        # Debian package build files
├── dist/                          # Build output directory
├── .planning/                     # GSD planning documents (this dir)
├── .claude/                       # Claude workspace state
├── .venv/                         # Python virtual environment
├── .git/                          # Git repository metadata
└── .pytest_cache/                 # Pytest cache
```

## Directory Purposes

**src/core/ — Network and State Logic:**
- Purpose: Core peer-to-peer networking, encryption, and state management
- Contains: Peer registry, message broker, network I/O, discovery mechanisms
- Key files:
  - `peer.py`: Peer data class and PeerRegistry (thread-safe observer pattern)
  - `network.py`: TCP server/client, ConnectionHandler, message framing
  - `discovery.py`: Multi-layer discovery (broadcast, multicast, relay, mDNS)
  - `encryption.py`: X25519 key generation, ECDH, AES-256-GCM
  - `messaging.py`: Message dataclass, MessageBroker with in-memory history

**src/ui/ — User Interface:**
- Purpose: Qt6 graphical interface and styling
- Contains: MainWindow widget, theme stylesheet
- Key files:
  - `app.py`: MainWindow class; coordinates UI state and network/discovery components
  - `styles.py`: Dark theme CSS-like stylesheet (Discord-inspired)

**src/utils/ — Utilities:**
- Purpose: Cross-cutting concerns and helpers
- Contains: Configuration management, logging
- Key files:
  - `config.py`: JSON config with dot-notation access; persistent peer_id generation
  - `logger.py`: Named logger setup; file + console output

**config/ — Configuration:**
- Purpose: Default application settings
- Key files:
  - `default_config.json`: Network ports, discovery settings, UI dimensions, channel list

**tests/ — Test Suite:**
- Purpose: Unit and integration tests
- Key files:
  - `test_encryption.py`: Encryption key exchange and AES-GCM roundtrips
  - `test_messaging.py`: Message serialization and broker logic
  - `test_discovery.py`: Peer discovery mechanisms

**assets/ — Static Resources:**
- Purpose: Application branding (icons, images)
- Key files:
  - `icons/`: Application icon for window/taskbar

**debian/ — Distribution:**
- Purpose: Debian/Ubuntu package build metadata
- Contains: postinst, prerm scripts; .deb file generation

**dist/ — Build Artifacts:**
- Purpose: Generated installer/package files (not committed to git)
- Contains: .deb, .egg-info files after build

## Key File Locations

**Entry Points:**
- `src/main.py`: Application entry point; imports and wires all components
  - Called when package is executed as __main__
  - Creates Qt application, initializes config, instantiates core components, starts event loop

**Configuration:**
- `config/default_config.json`: Default application settings
  - Network: TCP port (55001), UDP discovery port (55000), multicast group, TTL
  - UI: Window dimensions, font size, theme
  - Channels: List of available chat channels (general, random, announcements)
- `src/utils/config.py`: Runtime config manager
  - Loads default_config.json + ~/.localdiscord/config.json (user overlay)
  - Persists changes to ~/.localdiscord/config.json

**Core Logic:**
- `src/core/peer.py`: Peer registry and peer data
- `src/core/network.py`: TCP transport and connection lifecycle
- `src/core/discovery.py`: Peer discovery (5 mechanisms)
- `src/core/encryption.py`: E2E encryption
- `src/core/messaging.py`: Message model and broker

**User Interface:**
- `src/ui/app.py`: Main window and layout (channels, peers, chat)
- `src/ui/styles.py`: Dark theme stylesheet

**Testing:**
- `tests/test_encryption.py`: ~127 lines; tests key exchange and AES-GCM
- `tests/test_messaging.py`: Message serialization and broker
- `tests/test_discovery.py`: Discovery mechanisms
- Run with: `pytest tests/ -v` or `pytest tests/test_encryption.py -v`

**Logging & Utilities:**
- `src/utils/logger.py`: Logging setup (console + file)
  - Output: ~/.localdiscord/localdiscord.log
- `src/utils/__init__.py`: Empty module marker

## Naming Conventions

**Files:**
- `snake_case.py` for module files (e.g., `peer.py`, `network.py`)
- `UPPERCASE.json` for config files (e.g., `default_config.json`)
- Test files: `test_<module>.py` (e.g., `test_encryption.py`)
- Ignore pattern: `__pycache__/`, `.pytest_cache/`, `*.egg-info/`

**Classes:**
- `PascalCase` for all classes (e.g., `NetworkManager`, `PeerRegistry`, `MainWindow`)
- Internal classes prefixed with `_` (e.g., `_PeerRow`, `_Bridge` for UI-internal widgets)
- Dataclasses for data-only objects (e.g., `Peer`, `Message`)

**Functions/Methods:**
- `snake_case` for all functions and methods (e.g., `connect_to_peer()`, `establish_session()`)
- Private methods prefixed with `_` (e.g., `_on_frame()`, `_recv_loop()`)

**Variables:**
- `snake_case` for local variables (e.g., `peer_id`, `handler`, `msg_type`)
- `_` prefix for internal/temporary (e.g., `_data`, `_lock`)
- UPPERCASE for constants (e.g., `_FRAME_HEADER`, `_BROADCAST_MAGIC`)

**Types/Enums:**
- `PascalCase` for types (e.g., `PeerStatus` enum with values `ONLINE`, `AWAY`, `BUSY`, `OFFLINE`)

## Where to Add New Code

**New Feature — Persistent Message Storage:**
- Primary code: `src/core/messaging.py` - extend `MessageBroker.store_message()` to write to SQLite
- Migration: Create `src/core/storage.py` for database abstraction
- Tests: Add `tests/test_storage.py`
- Config: Add db path to `config/default_config.json`

**New Discovery Mechanism (e.g., DNS-SD):**
- Implementation: Add new method `_mdns_loop()` in `src/core/discovery.py` (or create `src/core/discovery_dns.py`)
- Integration: Call from `DiscoveryManager.start()` in a new thread
- Tests: Add case to `tests/test_discovery.py`
- Config: Add `network.dns_sd_enabled` to `default_config.json`

**New UI Feature (e.g., File Transfer):**
- Layout changes: Modify `MainWindow._make_*()` methods in `src/ui/app.py`
- New widgets: Create `src/ui/file_transfer.py` for file transfer UI
- Styling: Update `src/ui/styles.py`

**New Message Type (e.g., Voice Signal):**
- Message model: Extend `Message` class factory methods in `src/core/messaging.py`
- Wire format: Add new message type handler in `NetworkManager._on_frame()` in `src/core/network.py`
- Encryption: MessageBroker already handles; no changes needed
- Tests: Add case to `tests/test_messaging.py`

**Utilities:**
- Shared helpers: `src/utils/helpers.py` or extend existing `logger.py`
- Format helpers (e.g., time formatting): Consider moving to `src/utils/` as functions

## Special Directories

**~/.localdiscord/ — User Data (Runtime Generated):**
- Purpose: Persistent user configuration and logs
- Generated: Yes (created on first run by `Config.__init__` and `setup_logger`)
- Committed: No (git ignores)
- Contents:
  - `config.json`: User-overridden settings (persisted via `Config.set()`)
  - `localdiscord.log`: Debug/info/error logs (rotated daily if implemented)

**.planning/codebase/ — GSD Documentation:**
- Purpose: Architecture and structure analysis for future phases
- Generated: Yes (by `/gsd:map-codebase` orchestrator command)
- Committed: Yes (part of repo)
- Documents: ARCHITECTURE.md, STRUCTURE.md, STACK.md, INTEGRATIONS.md, CONVENTIONS.md, TESTING.md, CONCERNS.md

**.venv/ — Python Virtual Environment:**
- Purpose: Isolated Python dependencies
- Generated: Yes (by pip)
- Committed: No (git ignores)

**dist/ and .egg-info/ — Build Artifacts:**
- Purpose: Package metadata and distribution files
- Generated: Yes (by setuptools during build)
- Committed: No (git ignores)
- Rebuild: `python -m pip install -e .` (editable install)

---

*Structure analysis: 2026-02-24*
