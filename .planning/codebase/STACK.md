# Technology Stack

**Analysis Date:** 2026-02-24

## Languages

**Primary:**
- Python 3.10+ - Cross-platform application, GUI, networking, and cryptography

## Runtime

**Environment:**
- Python 3.10 or newer (tested with Python 3.14.0)

**Package Manager:**
- pip
- Virtual environment support via `python -m venv`

## Frameworks

**Core UI:**
- PyQt6 (>=6.4.0) - Native cross-platform GUI with QSS dark theming and Qt signal system for thread-safe communication

**Cryptography:**
- PyCA cryptography (>=41.0.0) - Provides X25519 ECDH key exchange, AES-256-GCM encryption, HKDF-SHA256 key derivation

**Network Discovery:**
- zeroconf (>=0.131.0) - mDNS/Zeroconf service registration and discovery (optional, with fallback to UDP broadcast)
- psutil (>=5.9.0) - Network interface detection for multi-subnet broadcast support (optional, with /24 heuristic fallback)

**Testing:**
- pytest (>=7.0.0) - Dev/testing dependency for test suite

## Key Dependencies

**Critical:**
- PyQt6 6.4.0+ - Primary GUI framework; handles all UI rendering and Qt signal-based thread synchronization
- cryptography 41.0.0+ - Essential for end-to-end encryption; provides X25519, ECDH, HKDF-SHA256, and AES-256-GCM primitives

**Infrastructure:**
- zeroconf 0.131.0+ - Optional but recommended for cross-VLAN/subnet discovery via mDNS (Layer 4 discovery); gracefully degrades if unavailable
- psutil 5.9.0+ - Optional but recommended for accurate multi-subnet broadcast detection; falls back to /24 heuristic

## Configuration

**Environment:**
- Managed through JSON config files: `config/default_config.json` (defaults) + `~/.localdiscord/config.json` (user overrides)
- Supports dot-path nested access: `config.get("network.tcp_port")`
- User configuration location: `~/.localdiscord/config.json`
- Persistent peer identity (UUID) generated on first run

**Build:**
- setup.py - Standard Python package configuration with console_scripts entry point
- localdiscord.spec - PyInstaller specification for building standalone executables
- build_deb.sh - Debian/Ubuntu .deb packaging script

## Platform Requirements

**Development:**
- Python 3.10+
- pip
- Virtual environment support
- Platform-agnostic networking (UDP, TCP, multicast)

**Production:**
- Cross-platform deployment: Windows, macOS, Linux
- Standalone executable via PyInstaller or Debian .deb package
- No central server required (peer-to-peer architecture)
- Firewall rules required for UDP port 55000 (discovery) and TCP port 55001 (messaging)

## Network Configuration

**Discovery:**
- UDP broadcast on port 55000 (subnet-directed and global 255.255.255.255)
- UDP multicast on 239.192.55.1 port 55000 with TTL=4 for cross-subnet discovery
- Optional UDP relay server on port 55002 for bridging unreachable subnets
- mDNS service registration on _localdiscord._tcp.local. (optional via zeroconf)

**Messaging:**
- TCP server on port 55001 (configurable via `network.tcp_port`)
- Per-connection handler threads for full-duplex communication
- 4-byte big-endian length-prefixed JSON framing
- 10-second connection timeout (configurable via `network.connection_timeout_sec`)

## Deployment

**Package Installation:**
- `pip install -e .` - Editable development install
- `pip install .` - Production install
- Console script entry point: `localdiscord`

**Standalone Executable:**
- PyInstaller produces single-file binaries for Windows (.exe), macOS, and Linux
- No Python runtime required for end users

**Debian Packaging:**
- Builds isolated venv at `/usr/lib/localdiscord/venv/` during installation
- Launcher script at `/usr/bin/localdiscord`
- Desktop application menu entry
- User config stored in `~/.localdiscord/` (not managed by dpkg, survives uninstall)

---

*Stack analysis: 2026-02-24*
