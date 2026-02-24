# External Integrations

**Analysis Date:** 2026-02-24

## APIs & External Services

**None detected.**

This is a purely peer-to-peer LAN application with no external API dependencies or cloud service integrations. All communication occurs directly between peers on the local network.

## Data Storage

**Databases:**
- Not used - application does not require a database
- Message history is in-memory only (not persisted by default)

**File Storage:**
- Local filesystem only
- Configuration stored at `~/.localdiscord/config.json` (user home directory)
- User can manually edit this file to change ports, add channels, or set default username

**Caching:**
- In-memory message broker maintains per-channel message history during runtime
- Peer registry holds connected peer information in memory
- All data is volatile and cleared on application shutdown

## Authentication & Identity

**Auth Provider:**
- Custom local implementation (no external auth service)
- Identity mechanism: persistent UUID stored in `~/.localdiscord/config.json`
- Username: user-configurable string (not authenticated; any peer can claim any name on the LAN)

**Implementation:**
- `src/utils/config.py` - Config manager that generates and stores persistent peer_id (UUID)
- `src/core/peer.py` - Peer dataclass tracking peer_id, username, IP, port, and status
- No password/credentials system; operates on LAN trust model

## Monitoring & Observability

**Error Tracking:**
- Not used - no external error reporting

**Logs:**
- `src/utils/logger.py` - Standard Python logging to console/stderr
- Logging tags: "discovery", "network", "encryption", "messaging", "main"
- No external log aggregation or monitoring services

## CI/CD & Deployment

**Hosting:**
- Peer-to-peer LAN application (no central hosting required)
- Each instance runs as a standalone desktop application
- Optional relay server support for bridging unreachable subnets (configurable but not provided in this package)

**CI Pipeline:**
- Not detected - no automated CI/CD configuration files (.github/workflows, .gitlab-ci.yml, etc.)
- Local testing via `pytest tests/`

## Environment Configuration

**Required env vars:**
- None required for operation
- Respects OS environment variables for username fallback:
  - `USERNAME` (Windows)
  - `USER` (Unix/Linux/macOS)

**Secrets location:**
- No API keys, tokens, or credentials required
- Per-peer encryption keys (X25519) are ephemeral (generated fresh on each application start)
- Session keys derived from ECDH are not persisted
- `.env` files not used

## Webhooks & Callbacks

**Incoming:**
- Not applicable (peer-to-peer, no external webhooks)

**Outgoing:**
- Not applicable (no external services to call)

## Relay Server (Optional)

**Purpose:**
- Bridge peers across multiple subnets where multicast is blocked or unavailable
- Configured via `network.relay_host` in config.json

**Protocol:**
- UDP-based relay query/response mechanism
- Peers announce themselves to relay: standard announce JSON
- Peers query relay: `{"magic": "localdiscord_relay_query_v1"}`
- Relay responds with aggregated peer list: `{"magic": "localdiscord_relay_response_v1", "peers": [...]}`

**Status:**
- Optional feature
- Not included in this distribution (must be provided separately)
- Code location for relay client: `src/core/discovery.py` (_relay_loop method)
- Can be disabled by leaving `network.relay_host` empty (default)

## Network Architecture

**Peer Discovery Layers (parallel, all optional):**

1. **Layer 1 — UDP Broadcast** (always available)
   - Protocol: Custom JSON broadcast on port 55000
   - Scope: Same subnet only (/24 by default, or detected subnet mask if psutil installed)
   - Interval: Every 5 seconds (configurable)

2. **Layer 2 — UDP Multicast** (if supported by network)
   - Protocol: IPv4 multicast to 239.192.55.1:55000
   - TTL: 4 (RFC 2365 organization-local)
   - Scope: Local site (crosses subnets with IGMP support)

3. **Layer 3 — Optional Relay Server** (if configured)
   - Protocol: UDP-based relay on port 55002 (configurable)
   - Scope: Any subnet reachable by relay host

4. **Layer 4 — mDNS/Zeroconf** (if zeroconf library installed)
   - Service: _localdiscord._tcp.local.
   - Scope: Network broadcast domain (usually same subnet; some routers forward mDNS)

5. **Layer 5 — Manual Peer Addition** (UI fallback)
   - User directly enters IP address in UI
   - Implementation: `src/ui/app.py` manual add peer dialog

**Connection Protocol:**
- TCP on port 55001 (configurable)
- Handshake: HELLO exchange with public keys (X25519)
- Encryption: AES-256-GCM with per-peer session keys derived from ECDH
- Framing: 4-byte big-endian length prefix + JSON payload

---

*Integration audit: 2026-02-24*
