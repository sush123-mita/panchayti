# Coding Conventions

**Analysis Date:** 2026-02-24

## Naming Patterns

**Files:**
- All lowercase with underscores separating words (snake_case)
- Examples: `encryption.py`, `peer.py`, `logger.py`, `config.py`
- Test files follow: `test_<module>.py` (e.g., `test_encryption.py`)
- No spaces or dashes in filenames

**Functions:**
- snake_case for all function names
- Examples: `establish_session()`, `prepare_outgoing()`, `get_history()`, `_local_ip()`
- Private/internal functions prefixed with single underscore: `_send_frame()`, `_emit()`, `_now()`
- Factory methods named with module context: `Message.text()`, `Message.system()`

**Variables:**
- snake_case for all variable names
- Single-letter loop variables acceptable in limited scope (e.g., `for cb in self._cbs`)
- Class attributes prefixed with underscore for private (e.g., `self._private_key`, `self._session_keys`)
- Callback variables follow pattern: `on_<event>`, `<event>_cb` (e.g., `on_message`, `on_change`)

**Types:**
- PascalCase for class names (e.g., `EncryptionManager`, `PeerRegistry`, `Message`)
- ALL_CAPS for enum values (e.g., `ONLINE`, `AWAY`, `BUSY`, `OFFLINE`)
- Type hints used throughout: `def get(self, peer_id: str) -> Optional[Peer]`
- Enum class format: `class PeerStatus(Enum):`

## Code Style

**Formatting:**
- No explicit linting config file detected (no `.eslintrc`, `.pylintrc`, `black`, `flake8`)
- Imports use standard Python style with `from typing import` for type hints
- Standard indentation: 4 spaces (Python default)
- Line length: appears to prefer ~100 chars, no explicit enforcement
- Module-level docstrings present in all files

**Linting:**
- No strict linting configured; style is enforced through convention
- Code demonstrates good Python practices:
  - Type annotations throughout
  - Proper exception handling
  - Logging usage in error paths
  - No bare `except Exception` at top level (specific exception types used)

## Import Organization

**Order:**
1. Standard library imports (e.g., `import sys`, `import os`, `import json`)
2. Third-party imports (e.g., `from PyQt6`, `from cryptography`)
3. Local imports (e.g., `from src.core.peer import PeerRegistry`)
4. Within each group, imports are sorted alphabetically

**Examples from codebase:**
```python
# From src/core/encryption.py
import base64
import os
import threading
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
```

**Path Aliases:**
- No path aliases configured (`@` shortcuts or similar)
- Full imports used throughout: `from src.core.encryption import EncryptionManager`

## Error Handling

**Patterns:**
- Specific exception types caught, not bare `except:`
- Examples in `src/core/encryption.py`:
  ```python
  if not key:
      raise ValueError(f"No encryption session for peer '{peer_id}'")
  ```
- Exception re-raising for diagnostics:
  ```python
  except Exception as e:
      get_logger("messaging").error(f"Failed to process message from {peer_id}: {e}")
      return None
  ```
- Silent failure with logging is common for callbacks:
  ```python
  def _emit(self, event: str, peer: Peer):
      for cb in self._cbs:
          try:
              cb(event, peer)
          except Exception:
              pass  # Silently suppress callback errors
  ```
- Thread safety: Using `threading.RLock()` for shared state

**Validation:**
- Defensive checks on None/empty values before operations
- Example from `src/core/peer.py`:
  ```python
  if not peer:
      return
  ```

## Logging

**Framework:** Python's built-in `logging` module

**Setup:**
- Centralized logger initialization in `src/utils/logger.py`
- Module loggers retrieved via `get_logger(__name__)` or `get_logger("module.name")`
- Root logger: `"localdiscord"` namespace

**Patterns:**
- All modules that need logging use: `from src.utils.logger import get_logger`
- Logger instantiation: `logger = get_logger(__name__)` or `get_logger("discovery")`
- Console handler at INFO level, file handler at DEBUG level
- Log format: `"[%(asctime)s] %(levelname)-8s %(name)s — %(message)s"`
- Error logging in exception handlers with context
- No print() statements for normal operation (logging used instead)

**Example from `src/core/messaging.py`:**
```python
except Exception as e:
    from src.utils.logger import get_logger
    get_logger("messaging").error(f"Failed to process message from {peer_id}: {e}")
    return None
```

## Comments

**When to Comment:**
- Module docstrings: Present in all files, explaining high-level purpose
- Class docstrings: Present for public classes, explaining responsibility
- Function docstrings: Present for important public methods
- Inline comments: Used for non-obvious logic (especially in network/crypto code)
- Section markers used for organizing code (e.g., `# ---- Mutators ----`)

**JSDoc/TSDoc:**
- Not applicable (Python codebase)
- Docstring format follows standard Python conventions
- Multiline docstrings with `"""` triple quotes
- Parameter documentation in docstrings

**Example from `src/core/encryption.py`:**
```python
def encrypt(self, peer_id: str, plaintext: str) -> dict:
    """
    Encrypt *plaintext* for *peer_id*.

    Returns:
        {"ciphertext": "<base64>", "nonce": "<base64>"}

    Raises:
        ValueError if no session has been established for this peer.
    """
```

## Function Design

**Size:**
- Functions kept focused and reasonably sized (10-40 lines typical)
- Single responsibility principle observed
- Example: `establish_session()` in `src/core/encryption.py` performs only ECDH + key storage

**Parameters:**
- Type hints required on all parameters
- Keyword-only arguments not enforced but used where logical
- Factory methods use explicit parameters over **kwargs
- Example: `def text(sender_id: str, sender_name: str, channel: str, content: str) -> "Message"`

**Return Values:**
- Type hints on all return statements
- Optional return types used explicitly: `-> Optional[Peer]`
- Functions returning dicts have implicit structure documented in docstring
- Example from `src/core/encryption.py`:
  ```python
  def encrypt(self, peer_id: str, plaintext: str) -> dict:
      return {
          "ciphertext": base64.b64encode(ciphertext).decode(),
          "nonce":      base64.b64encode(nonce).decode(),
      }
  ```

## Module Design

**Exports:**
- Implicit exports; no `__all__` defined
- Public classes and functions are those without leading underscore
- Internal utilities prefixed with underscore: `_send_frame()`, `_now()`, `_deep_merge()`

**Barrel Files:**
- `src/__init__.py` is empty (no re-exports)
- `src/core/__init__.py` is empty (no re-exports)
- `src/ui/__init__.py` is empty (no re-exports)
- `src/utils/__init__.py` is empty (no re-exports)
- Direct imports required: `from src.core.encryption import EncryptionManager`

**Single Responsibility:**
- Each module handles one concern:
  - `encryption.py` — ECDH + AES-GCM crypto
  - `peer.py` — Peer data model and registry
  - `messaging.py` — Message model and broker
  - `network.py` — TCP connection handling
  - `discovery.py` — Peer discovery (UDP broadcast/multicast)
  - `logger.py` — Centralized logging setup
  - `config.py` — Configuration management

---

*Convention analysis: 2026-02-24*
