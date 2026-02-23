# LocalDiscord — P2P LAN Chat

A Discord-like chat application for local networks with **no central server**, **end-to-end encryption**, and a clean dark-theme GUI.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Quick Start](#quick-start)
5. [Installation](#installation)
6. [Debian / Ubuntu .deb Package](#debian--ubuntu-deb-package)
7. [Running the App](#running-the-app)
8. [Building a Standalone Executable](#building-a-standalone-executable)
9. [Security Model](#security-model)
10. [Extending the App](#extending-the-app)
11. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        LOCAL AREA NETWORK                            │
│                                                                      │
│   ┌────────────────────┐          ┌────────────────────┐            │
│   │   Peer A (Alice)   │  TCP/TLS │   Peer B (Bob)     │            │
│   │                    │◄────────►│                    │            │
│   │  ┌──────────────┐  │          │  ┌──────────────┐  │            │
│   │  │  Qt6 UI      │  │          │  │  Qt6 UI      │  │            │
│   │  │  (main thrd) │  │          │  │  (main thrd) │  │            │
│   │  └──────┬───────┘  │          │  └──────┬───────┘  │            │
│   │         │signals   │          │         │signals   │            │
│   │  ┌──────▼───────┐  │          │  ┌──────▼───────┐  │            │
│   │  │ NetworkMgr   │  │ TCP:55001│  │ NetworkMgr   │  │            │
│   │  │ (bg thread)  │◄─┼──────────┼─►│ (bg thread)  │  │            │
│   │  └──────────────┘  │          │  └──────────────┘  │            │
│   │  ┌──────────────┐  │UDP:55000 │  ┌──────────────┐  │            │
│   │  │ Discovery    │◄─┼──────────┼─►│ Discovery    │  │            │
│   │  │ (UDP + mDNS) │  │broadcast │  │ (UDP + mDNS) │  │            │
│   │  └──────────────┘  │          │  └──────────────┘  │            │
│   └────────────────────┘          └────────────────────┘            │
└──────────────────────────────────────────────────────────────────────┘
```

### How It Works

| Step | What Happens |
|------|-------------|
| **1. Discovery** | Each peer UDP-broadcasts a small JSON "hello" packet to the subnet every 5 s. Optionally also registers an mDNS service for discovery across VLANs. |
| **2. Connection** | Any peer that sees an unknown broadcast dials a TCP connection to it on port 55001. |
| **3. Handshake** | Initiator sends `{"type":"handshake", "public_key":"..."}`. Responder replies in kind. |
| **4. Key Exchange** | Both sides independently compute the same 256-bit AES key via X25519 ECDH + HKDF-SHA256. |
| **5. Messaging** | All subsequent TCP frames carry AES-256-GCM encrypted JSON. The plaintext never leaves the process unencrypted. |
| **6. Routing** | There is no router. Every peer holds a direct TCP connection to every other peer (full mesh). Messages are broadcast to all connections or directed to one. |

---

## Technology Stack

| Component | Technology | Why |
|-----------|------------|-----|
| Language  | Python 3.10+ | Cross-platform, rich ecosystem, fast to iterate |
| GUI       | **PyQt6** | Native widgets on all platforms, QSS theming, Qt signals for thread safety |
| Key Exchange | **X25519 ECDH** (PyCA `cryptography`) | Fast, modern, safe elliptic-curve DH |
| Key Derivation | **HKDF-SHA256** | Standard KDF; deterministic from shared secret |
| Message Encryption | **AES-256-GCM** | Authenticated encryption; detects tampering |
| LAN Discovery | **UDP Broadcast** + **Zeroconf/mDNS** | Works on all OS without config; mDNS as fallback |
| Packaging | **PyInstaller** | Single-file .exe / binary on all platforms |

---

## Project Structure

```
localdiscord/
├── run.py                      ← Entry point (run this)
├── setup.py                    ← pip install support
├── localdiscord.spec           ← PyInstaller build spec
├── requirements.txt
│
├── config/
│   └── default_config.json     ← Ports, channels, UI defaults
│
├── assets/
│   └── icons/                  ← Place .ico / .icns here
│
├── src/
│   ├── main.py                 ← Wires all components together
│   │
│   ├── core/
│   │   ├── peer.py             ← Peer dataclass + PeerRegistry
│   │   ├── encryption.py       ← X25519 ECDH + AES-256-GCM
│   │   ├── messaging.py        ← Message model + MessageBroker
│   │   ├── network.py          ← TCP server + ConnectionHandler
│   │   └── discovery.py        ← UDP broadcast + mDNS discovery
│   │
│   ├── ui/
│   │   ├── app.py              ← MainWindow (Discord-like layout)
│   │   └── styles.py           ← Qt Style Sheet dark theme
│   │
│   └── utils/
│       ├── config.py           ← Config loader / dot-path accessor
│       └── logger.py           ← Logging setup
│
└── tests/
    ├── test_encryption.py
    ├── test_discovery.py
    └── test_messaging.py
```

---

## Quick Start

```bash
# 1. Clone / download the project
cd localdiscord

# 2. Create a virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python run.py
```

On first launch you will be asked for a username. After that the app automatically discovers any other running instances on the same LAN.

---

## Installation

### Prerequisites

- Python **3.10** or newer
- pip

### From source (developer)

```bash
pip install -e ".[dev]"
```

### Without virtual environment (quick test)

```bash
pip install PyQt6 cryptography zeroconf
python run.py
```

---

## Debian / Ubuntu .deb Package

The easiest way to install LocalDiscord on Ubuntu (or any Debian-based distro).
The `.deb` handles all dependency installation automatically via a postinst script
that creates an isolated Python virtual environment.

### Debian packaging files layout

```
debian/
├── control            ← Package metadata (name, version, deps, description)
├── changelog          ← Required version history (Debian policy)
├── copyright          ← MIT licence declaration
├── postinst           ← Post-install: creates venv, pip-installs deps
├── prerm              ← Pre-remove: deletes the venv
├── postrm             ← Post-remove: purges remaining files on apt purge
├── launcher.sh        ← Installed as /usr/bin/localdiscord
└── localdiscord.desktop ← Application menu entry
```

### Step 1 — Install build tools (one time, on Ubuntu)

```bash
sudo apt update
sudo apt install dpkg-dev fakeroot dos2unix python3-venv
```

### Step 2 — Build the .deb

Copy the whole project folder to your Ubuntu machine, then:

```bash
cd /path/to/localdiscord
bash build_deb.sh
```

The script will:
1. Assemble a staging directory under `dist/deb/`
2. Copy Python source to `usr/lib/localdiscord/`
3. Install the launcher at `usr/bin/localdiscord`
4. Install the `.desktop` entry and documentation
5. Fill in `Installed-Size` automatically
6. Run `fakeroot dpkg-deb --build` to produce the final `.deb`

Output: `dist/localdiscord_1.0.0_all.deb`

### Step 3 — Install the package

```bash
# Recommended — apt resolves any missing system deps automatically:
sudo apt install ./dist/localdiscord_1.0.0_all.deb

# Alternative (manual dep fix required if needed):
sudo dpkg -i dist/localdiscord_1.0.0_all.deb
sudo apt-get install -f
```

During installation `postinst` runs and:
- Creates `/usr/lib/localdiscord/venv/` (Python virtual environment)
- Installs `PyQt6`, `cryptography`, and `zeroconf` into the venv via pip

### Step 4 — Run

```bash
localdiscord          # from the terminal
# or open "LocalDiscord" from your application menu (GNOME / KDE / XFCE)
```

### Uninstall

```bash
sudo apt remove localdiscord          # removes files, keeps ~/.localdiscord config
sudo apt purge  localdiscord          # also removes /usr/lib/localdiscord
```

User configuration and chat history in `~/.localdiscord/` are **never deleted**
by the package manager — remove that directory manually if you want a clean slate.

### What gets installed where

| Path | Content |
|------|---------|
| `/usr/lib/localdiscord/` | Python source (`src/`, `config/`, `run.py`) |
| `/usr/lib/localdiscord/venv/` | Isolated Python venv with all pip deps |
| `/usr/bin/localdiscord` | Launcher shell script |
| `/usr/share/applications/localdiscord.desktop` | App menu entry |
| `/usr/share/doc/localdiscord/` | Copyright, changelog |
| `~/.localdiscord/` | Per-user config, chat log (not managed by dpkg) |

### Building for a specific version

```bash
bash build_deb.sh --version 1.1.0
```

---

## Running the App

```bash
python run.py
```

**Configuration** is stored in `~/.localdiscord/config.json` after first run.
Edit it to change ports, add channels, or set a default username.

### Firewall Rules (Windows)

Windows Firewall may block UDP/TCP on first launch.  Click **"Allow"** when prompted, or add rules manually:

```
netsh advfirewall firewall add rule name="LocalDiscord TCP" dir=in action=allow protocol=TCP localport=55001
netsh advfirewall firewall add rule name="LocalDiscord UDP" dir=in action=allow protocol=UDP localport=55000
```

### Firewall Rules (Linux / iptables)

```bash
sudo ufw allow 55001/tcp
sudo ufw allow 55000/udp
```

### Firewall Rules (macOS)

System Preferences → Security & Privacy → Firewall → Allow LocalDiscord.

---

## Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller localdiscord.spec
```

Output is in `dist/localdiscord` (or `dist/localdiscord.exe` on Windows).
Distribute just that single file — no Python installation required.

### Cross-platform notes

| Platform | Command | Output |
|----------|---------|--------|
| Windows  | `pyinstaller localdiscord.spec` | `dist\localdiscord.exe` |
| macOS    | `pyinstaller localdiscord.spec` | `dist/localdiscord` (or .app if you enable the BUNDLE block in the spec) |
| Linux    | `pyinstaller localdiscord.spec` | `dist/localdiscord` |

> You must run PyInstaller on each target platform to produce its native binary.

---

## Security Model

| Property | Implementation |
|----------|---------------|
| **Key exchange** | X25519 Elliptic-Curve Diffie-Hellman — forward-secret per session |
| **Key derivation** | HKDF-SHA256, info = `"localdiscord-v1-session"` |
| **Message encryption** | AES-256-GCM with a fresh random 96-bit nonce per message |
| **Integrity** | GCM authentication tag rejects any tampered ciphertext |
| **Identity** | Persistent UUID in `~/.localdiscord/config.json` |

### What is NOT provided (yet)

- **Peer authentication** — anyone on the LAN can impersonate a username. To fix this, add RSA/Ed25519 identity signing.
- **Perfect forward secrecy per message** — the session key lives for the connection lifetime. To improve, implement a Double Ratchet (Signal Protocol).
- **Key pinning / TOFU** — first connection is trusted. Store peer public keys and warn on change.

---

## Extending the App

The codebase is designed to grow. Here are suggested extension points:

### Add voice chat

1. Capture audio with `pyaudio` or `sounddevice`.
2. Encode with Opus (`pyogg` or `opuslib`).
3. Stream encoded frames via UDP (low latency) alongside the existing TCP control channel.
4. Add a `VoiceManager` class in `src/core/` and a voice-channel UI element.

### Add presence / status

Send a `{"type":"presence","status":"away"}` frame — already handled in `NetworkManager._on_frame()`.
Add a status selector to the user bar in `app.py`.

### Add file transfer

1. Add a `FileMessage` type to `messaging.py`.
2. In `network.py`, stream file bytes in chunks over the existing connection.
3. Display progress bars in the UI.

### Persistent message history

Replace `MessageBroker`'s in-memory dict with SQLite writes:

```python
import sqlite3
# In MessageBroker.store_message():
#   INSERT INTO messages (id, channel, sender, content, ts) VALUES (...)
```

### Add channels dynamically

Send a `{"type":"channel_create","name":"new-channel"}` wire message and update all peers' channel lists.

### Relay mode (bridge across networks)

Add an optional `relay_host` in `config.json`. Peers that can't reach each other directly tunnel through the relay. Implement with a simple TCP proxy server.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Peers not discovered | Firewall blocking UDP 55000 | Add firewall rule (see above) |
| Connection refused | Firewall blocking TCP 55001 | Add firewall rule |
| Two instances on same machine don't connect | Loopback UDP broadcast | Run with `--port 55002` (add CLI arg support) |
| `ModuleNotFoundError: PyQt6` | Dependencies not installed | `pip install -r requirements.txt` |
| Decryption error | Version mismatch or packet corruption | Ensure both peers run the same version |
| App crashes on macOS with SSL error | System Python SSL issue | Use a brew-installed Python or pyenv |

---

## Running Tests

```bash
pytest tests/ -v
```

All tests are pure-Python and require no real network sockets.
