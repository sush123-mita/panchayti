# Testing Patterns

**Analysis Date:** 2026-02-24

## Test Framework

**Runner:**
- pytest (version 7.0.0+, defined in `setup.py` extras_require)
- Config: No explicit config file (pytest.ini, pyproject.toml, or setup.cfg)
- Default discovery: Files matching `test_*.py` pattern

**Assertion Library:**
- pytest's built-in assertion mechanism (simple `assert` statements)
- Some tests use `pytest.raises()` for exception testing

**Run Commands:**
```bash
pytest tests/                          # Run all tests in tests/ directory
pytest tests/test_encryption.py -v    # Run specific test file with verbose output
pytest -k test_public_key_length       # Run tests matching pattern
pytest --tb=short                      # Run with short traceback format
```

## Test File Organization

**Location:**
- Separate directory: `tests/` at project root
- Mirrors source structure indirectly: `tests/test_<module>.py` corresponds to `src/<module>/`

**Naming:**
- Test files: `test_<feature>.py` (e.g., `test_encryption.py`, `test_messaging.py`)
- Test classes: `Test<Feature>` (e.g., `TestKeyGeneration`, `TestMessageBroker`)
- Test functions: `test_<behavior>` (e.g., `test_public_key_length`, `test_both_derive_same_key`)

**Structure:**
```
tests/
├── __init__.py
├── test_encryption.py      # EncryptionManager tests
├── test_messaging.py       # Message and MessageBroker tests
├── test_discovery.py       # DiscoveryManager tests
└── test_network.py         # (if exists) NetworkManager tests
```

## Test Structure

**Suite Organization:**
```python
class TestKeyGeneration:
    def test_public_key_length(self):
        """X25519 public keys are exactly 32 bytes."""
        enc = EncryptionManager()
        assert len(enc.public_key_bytes) == 32
```

**Patterns:**

1. **Setup per test class with `setup_method()`:**
   ```python
   class TestEncryptDecrypt:
       def setup_method(self):
           self.alice = EncryptionManager()
           self.bob   = EncryptionManager()
           self.alice.establish_session("bob",   self.bob.public_key_b64)
           self.bob.establish_session(  "alice", self.alice.public_key_b64)
   ```

2. **Flat function-level tests:**
   ```python
   def test_unique_keys_per_instance(self):
       a = EncryptionManager()
       b = EncryptionManager()
       assert a.public_key_bytes != b.public_key_bytes
   ```

3. **Path insertion for imports** (each test file begins with):
   ```python
   import sys, os
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
   ```
   This allows `from src.core.encryption import EncryptionManager` to work.

4. **Grouped test classes** (one class per feature being tested):
   - `TestKeyGeneration` — Key pair generation tests
   - `TestSessionEstablishment` — ECDH handshake tests
   - `TestEncryptDecrypt` — Encryption/decryption roundtrip tests
   - `TestMessage` — Message model serialization tests
   - `TestMessageBroker` — Message broker logic tests

## Mocking

**Framework:** No explicit mocking framework (unittest.mock not used in tests examined)

**Patterns:**
- Manual stub creation for test isolation
- Example from `tests/test_discovery.py`:
  ```python
  class _FakeConfig:
      peer_id            = "aaaa-self"
      username           = "Tester"
      tcp_port           = 55001
      udp_port           = 55000
      discovery_interval = 5
      multicast_group    = "239.192.55.1"
      multicast_ttl      = 4
      relay_host         = ""
      relay_port         = 55002

      def get(self, key, default=None):
          return default
  ```

- Fake peer registry for testing:
  ```python
  class _FakePeerRegistry:
      def __init__(self):
          self._store = {}

      def get(self, peer_id):
          return self._store.get(peer_id)

      def add_or_update(self, peer):
          self._store[peer.peer_id] = peer
  ```

- Fake network manager for testing discovery:
  ```python
  class _FakeNetworkManager:
      def __init__(self):
          self.calls = []  # list of (ip, port) dials

      def connect_to_peer(self, ip, port):
          self.calls.append((ip, port))
          import time; time.sleep(0.05)
          return True
  ```

**What to Mock:**
- Slow operations: Network I/O, file system access
- External dependencies: NetworkManager in discovery tests, other managers when testing one component
- Callbacks: Instead of mocking, use `received = []` and `self.broker.on_message(received.append)`

**What NOT to Mock:**
- Cryptographic operations: Use real EncryptionManager instances, not mocks
- Core business logic being tested: Real Message objects, real PeerRegistry
- In-memory state: Only mock things that block or create side effects

**Assertion Patterns:**
```python
# Simple assertions on function return value
assert len(enc.public_key_bytes) == 32

# Negative assertions
assert a.public_key_bytes != b.public_key_bytes

# String search (ciphertext should not contain plaintext)
assert msg not in enc["ciphertext"]

# Exception testing
with pytest.raises(ValueError):
    enc_mgr.encrypt("nobody", "hello")

# Tuple/list membership
assert ("192.168.1.10", 55001) in net.calls

# Field value comparison
assert m.type == "text"
assert m.sender_name == "Alice"
```

## Fixtures and Factories

**Test Data:**
- Created inline in test methods or in `setup_method()`
- No fixture framework used (no `@pytest.fixture` decorators detected)
- Factory methods on domain objects used for creating test data:
  ```python
  m = Message.text("pid", "Alice", "general", "hi")
  m = Message.system("Server started")
  ```

**Location:**
- Stubs defined in same test file at module level (before test classes)
- Example: `_FakeConfig`, `_FakePeerRegistry`, `_FakeNetworkManager` in `test_discovery.py`
- Real domain objects instantiated within test methods

## Coverage

**Requirements:** No coverage enforced (no `.coveragerc` or coverage config)

**View Coverage:**
```bash
pytest --cov=src tests/
pytest --cov=src --cov-report=html tests/
```

**Gap Analysis:**
- Core modules with tests: `encryption.py`, `messaging.py`, `discovery.py`
- Core modules without tests: `network.py` (no `test_network.py` found)
- UI module untested: `src/ui/app.py` (no test file)
- Utilities partially tested: `logger.py` untested, `config.py` untested

## Test Types

**Unit Tests:**
- **Scope:** Single class or module in isolation
- **Approach:** Direct instantiation and method calls
- **Examples:**
  - `TestKeyGeneration` — Tests EncryptionManager key generation
  - `TestMessage` — Tests Message model serialization
  - `TestMessageBroker` — Tests broker's store/retrieve logic
- **Coverage:** Encryption, messaging, discovery core logic

**Integration Tests:**
- **Scope:** Multiple components working together
- **Approach:** Creating real instances of dependent components
- **Examples:**
  - `TestSessionEstablishment::test_both_derive_same_key` — Alice and Bob EncryptionManager establish session
  - `test_process_incoming_decrypts` — MessageBroker decrypts data from encrypted MessageBroker
- **Pattern:** Setup two or more components, test interaction
  ```python
  def test_both_derive_same_key(self):
      alice = EncryptionManager()
      bob   = EncryptionManager()
      alice.establish_session("bob",   bob.public_key_b64)
      bob.establish_session(  "alice", alice.public_key_b64)
      enc = alice.encrypt("bob", "shared secret test")
      dec = bob.decrypt("alice", enc["ciphertext"], enc["nonce"])
      assert dec == "shared secret test"
  ```

**E2E Tests:**
- **Status:** Not used in this codebase
- **Reason:** GUI testing is complex; network testing handled by integration tests

## Common Patterns

**Async Testing:**
- No async/await in codebase
- Threading used for background tasks in production, but tests are synchronous
- Where threading needed for test behavior (discovery threads), explicit `time.sleep()` used:
  ```python
  dm._handle_announce(pkt, "192.168.1.10")
  import time; time.sleep(0.1)  # Wait for spawned thread
  assert ("192.168.1.10", 55001) in net.calls
  ```

**Error Testing:**
```python
# Specific exception type
with pytest.raises(ValueError):
    enc_mgr.encrypt("nobody", "hello")

# Multiple possible exceptions (GCM auth failures or decryption errors)
with pytest.raises((InvalidTag, Exception)):
    self.bob.decrypt("alice", bad, enc["nonce"])

# Graceful degradation (no raise expected)
def test_process_incoming_bad_data_returns_none(self):
    result = self.broker.process_incoming("nobody", {"type": "text"})
    # Should not raise; returns None or empty Message
```

**Property-Based Testing:**
- Not used (no hypothesis library)

**Boundary Testing:**
```python
# Empty string
def test_empty_string(self):
    enc = self.alice.encrypt("bob", "")
    assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == ""

# Large payload
def test_long_message(self):
    msg = "A" * 100_000
    enc = self.alice.encrypt("bob", msg)
    assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == msg

# Unicode
def test_unicode_message(self):
    msg = "こんにちは世界 — Привет мир — مرحبا"
    enc = self.alice.encrypt("bob", msg)
    assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == msg
```

## Best Practices Observed

1. **Descriptive test names:** `test_both_derive_same_key`, `test_tampered_ciphertext_raises`
2. **One assertion focus:** Each test verifies one behavior
3. **Docstrings on tests:** Most tests have short docstring explaining intent
4. **Setup isolation:** Each test class has independent `setup_method()` setup
5. **Real crypto in tests:** Don't mock cryptography; test real encryption roundtrips
6. **Callback testing without mocks:** Use `received = []` and closure to capture behavior
7. **Deterministic tests:** No reliance on timing (except explicit sleeps for threads)

---

*Testing analysis: 2026-02-24*
