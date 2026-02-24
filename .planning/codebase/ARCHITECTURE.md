# Architecture

**Analysis Date:** 2026-02-24

## Pattern Overview

**Overall:** Layered P2P networking architecture with clear separation between network transport, business logic, and UI presentation. The design follows a modular, single-responsibility pattern with decoupled components communicating through well-defined interfaces.

**Key Characteristics:**
- Peer-to-peer (P2P) topology: no central server required; all peers are equal
- Multi-threaded async design: network I/O and discovery run in background worker threads
- Thread-safe state management: core objects (PeerRegistry, MessageBroker) use thread locks
- Qt signal-based UI coupling: worker threads safely post updates to main thread via Qt signals
- Pluggable discovery: multiple discovery mechanisms (UDP broadcast, multicast, relay, mDNS) work independently
- End-to-end encryption: X25519 ECDH + AES-256-GCM per peer

## Layers

**Network Transport Layer:**
- Purpose: TCP connection management, framing, and handshake
- Location: `src/core/network.py` - `NetworkManager` and `ConnectionHandler` classes
- Contains: Low-level socket I/O, frame serialization (4-byte length prefix), connection lifecycle
- Depends on: `EncryptionManager`, `PeerRegistry`, `MessageBroker`, config
- Used by: `DiscoveryManager` (initiates connections), `MainWindow` (emits UI signals)

**Peer Discovery Layer:**
- Purpose: Locate peers on local network through multiple mechanisms
- Location: `src/core/discovery.py` - `DiscoveryManager` class
- Contains: UDP broadcast, UDP multicast, optional relay client, mDNS/Zeroconf registration
- Depends on: `NetworkManager.connect_to_peer()`, `PeerRegistry`
- Used by: Application startup flow in `main.py`

**State & Registry Layer:**
- Purpose: Thread-safe in-memory storage of peer state and message history
- Location: `src/core/peer.py` - `PeerRegistry` and `Peer` dataclass
- Location: `src/core/messaging.py` - `MessageBroker` and `Message` dataclass
- Contains: Peer status tracking, message channel history, observer callbacks
- Depends on: `EncryptionManager` (for message encryption)
- Used by: All layers (network, UI, discovery)

**Encryption Layer:**
- Purpose: End-to-end key agreement and message encryption/decryption
- Location: `src/core/encryption.py` - `EncryptionManager` class
- Contains: X25519 key generation, ECDH session establishment, AES-256-GCM cipher
- Depends on: `cryptography` library (PyCA)
- Used by: `NetworkManager` (during handshake), `MessageBroker` (payload encryption)

**Configuration Layer:**
- Purpose: Load and persist application settings
- Location: `src/utils/config.py` - `Config` class
- Contains: JSON-based config with dot-notation access, persistent peer_id generation
- Depends on: User home directory (~/.localdiscord/config.json)
- Used by: All initialization code; accessed via dot notation (e.g., `config.get("network.tcp_port")`)

**Logging Layer:**
- Purpose: Centralized logging to console and file
- Location: `src/utils/logger.py`
- Contains: Named loggers under "localdiscord" namespace, file rotation
- Used by: All modules for debug/info/error reporting

**UI Presentation Layer:**
- Purpose: Qt6-based graphical interface
- Location: `src/ui/app.py` - `MainWindow` class
- Location: `src/ui/styles.py` - Dark theme stylesheet
- Contains: Channel list, peer list, chat history display, message input
- Depends on: `NetworkManager`, `DiscoveryManager`, `PeerRegistry`, `MessageBroker`
- Threading: Receives updates from worker threads via `_Bridge` Qt signal object

## Data Flow

**Peer Connection Flow:**

1. DiscoveryManager discovers a peer via UDP broadcast/multicast/mDNS
2. Calls NetworkManager.connect_to_peer(ip, port)
3. NetworkManager initiates TCP connection, performs handshake:
   - Sends HELLO with X25519 public key
   - Receives peer's HELLO
4. EncryptionManager.establish_session() derives shared AES key
5. Peer object created and added to PeerRegistry
6. ConnectionHandler started with recv_thread and send_thread
7. NetworkManager emits peer_connected signal → MainWindow._on_peer_joined()

**Message Send Flow:**

1. User types in MainWindow._input and presses Enter
2. _send() creates Message object (text type)
3. MessageBroker.store_message() saves to in-memory history
4. Broker notifies listeners → message appears in chat display
5. NetworkManager.send_to() prepares encrypted wire format
6. ConnectionHandler.send_thread drains queue and writes to socket

**Message Receive Flow:**

1. ConnectionHandler._recv_thread reads length-prefixed JSON frame
2. Calls NetworkManager._on_frame(peer_id, data)
3. NetworkManager dispatches by type:
   - "text" → MessageBroker.process_incoming() decrypts and parses
   - "presence" → updates peer status in PeerRegistry
4. MessageBroker.store_message() saves and notifies listeners
5. Listener callback fires message_received signal
6. MainWindow._on_message() appends to chat display

**State Management:**

- **PeerRegistry:** Thread-safe observer pattern. Stores current peer roster with status. Worker threads call add_or_update/remove; UI listens via on_change callback registered in main.py then wired to Qt signal.
- **MessageBroker:** Thread-safe message history per channel. Stores in-memory only (no persistence layer yet). Listeners notified synchronously when store_message() called.
- **Config:** Loads on startup from default_config.json + ~/.localdiscord/config.json. Persists changes immediately to user config file.

## Key Abstractions

**Peer:**
- Purpose: Represents a remote participant on the network
- Examples: `src/core/peer.py` - `Peer` dataclass with peer_id, username, ip, port, status
- Pattern: Immutable data class with convenience methods (address(), __hash__, __eq__)

**Message:**
- Purpose: Represents a chat message or system notification
- Examples: `src/core/messaging.py` - `Message` dataclass with factory methods (text(), system())
- Pattern: Wire-format serialization (to_wire/from_wire) with optional encryption fields

**ConnectionHandler:**
- Purpose: Manages bidirectional I/O for a single peer connection
- Examples: `src/core/network.py` - Thread-safe socket handler with separate recv/send threads
- Pattern: Internal threads feed via callbacks; external code enqueues messages

**DiscoveryManager:**
- Purpose: Runs multiple independent discovery mechanisms in parallel
- Pattern: Each mechanism (broadcast, multicast, relay, mDNS) runs in its own thread and independently calls network_manager.connect_to_peer()

## Entry Points

**Application Startup:**
- Location: `src/main.py` - `main()` function
- Triggers: Executed when package is run as __main__
- Responsibilities:
  1. Create Qt application
  2. Set dark theme stylesheet
  3. Load config and setup logger
  4. Ask user for username if first-run
  5. Instantiate core components: EncryptionManager, PeerRegistry, MessageBroker, NetworkManager, DiscoveryManager
  6. Create MainWindow and wire callbacks
  7. Start networking (MainWindow.start_network())
  8. Run Qt event loop

**Network Start (MainWindow.start_network):**
- Location: `src/ui/app.py` - Line ~348
- Triggers: Called after MainWindow.show() so Qt signals are connected
- Responsibilities:
  1. Start DiscoveryManager (all 4 layers: broadcast, multicast, optional relay, optional mDNS)
  2. Start NetworkManager (TCP listener thread)
  3. Register peer change callbacks to update UI

**UI Signal Bridge:**
- Location: `src/ui/app.py` - `_Bridge` class
- Triggers: Worker threads emit signals when peer/message events occur
- Pattern: Qt queued-connection delivers signals on main thread, preventing race conditions

## Error Handling

**Strategy:** Defensive error handling at component boundaries; internal errors are logged but do not propagate up to crash the application.

**Patterns:**

- **Network errors:** Caught in socket operations, logged as warnings/errors. TCP port bind failure reported via on_error callback to UI. Connection failures do not crash; peer is removed from registry and UI updates.
- **Message decryption:** Failures return None; sender is logged as error; message is silently dropped (no double display).
- **Config loading:** Missing config file falls back to defaults; user settings overlay base config via deep merge.
- **Encryption key exchange:** No session = fallback to plaintext (should not happen after handshake; logged as error if attempted).

## Cross-Cutting Concerns

**Logging:** All modules use `get_logger(name)` from `src/utils/logger.py`. Messages prefixed with timestamp, level, module name. Console shows INFO+; file shows DEBUG+. Log file: ~/.localdiscord/localdiscord.log

**Validation:** Input validation minimal in core layers; UI layer validates user input before creating Message objects. Wire format assumed valid after JSON parsing (cryptography library handles integrity via GCM tag).

**Authentication:** No user authentication layer. Peer identification relies on X25519 public key + ECDH session. Assumes local network is trusted (not exposed to internet without additional security).

**Concurrency:** Threading is fine-grained per connection (one recv_thread + one send_thread per peer). All shared state (peer registry, message history, encryption sessions) protected by RLock. No async/await; uses thread.Thread with daemon=True for background work.

---

*Architecture analysis: 2026-02-24*
