"""
test_encryption.py — Unit tests for EncryptionManager.

Run with:
    pytest tests/test_encryption.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.core.encryption import EncryptionManager


# ------------------------------------------------------------------ #

class TestKeyGeneration:
    def test_public_key_length(self):
        """X25519 public keys are exactly 32 bytes."""
        enc = EncryptionManager()
        assert len(enc.public_key_bytes) == 32

    def test_unique_keys_per_instance(self):
        """Each instance gets a fresh key pair."""
        a = EncryptionManager()
        b = EncryptionManager()
        assert a.public_key_bytes != b.public_key_bytes

    def test_b64_roundtrip(self):
        """Base64 representation decodes back to the same raw bytes."""
        import base64
        enc = EncryptionManager()
        assert base64.b64decode(enc.public_key_b64) == enc.public_key_bytes


# ------------------------------------------------------------------ #

class TestSessionEstablishment:
    def test_both_derive_same_key(self):
        """ECDH: Alice and Bob must arrive at the same AES key."""
        alice = EncryptionManager()
        bob   = EncryptionManager()

        alice.establish_session("bob",   bob.public_key_b64)
        bob.establish_session(  "alice", alice.public_key_b64)

        # Encrypt with Alice's key for Bob, decrypt with Bob's key
        enc = alice.encrypt("bob", "shared secret test")
        dec = bob.decrypt("alice", enc["ciphertext"], enc["nonce"])
        assert dec == "shared secret test"

    def test_has_session_after_establish(self):
        alice = EncryptionManager()
        bob   = EncryptionManager()
        assert not alice.has_session("bob")
        alice.establish_session("bob", bob.public_key_b64)
        assert alice.has_session("bob")

    def test_remove_session(self):
        alice = EncryptionManager()
        bob   = EncryptionManager()
        alice.establish_session("bob", bob.public_key_b64)
        alice.remove_session("bob")
        assert not alice.has_session("bob")


# ------------------------------------------------------------------ #

class TestEncryptDecrypt:
    def setup_method(self):
        self.alice = EncryptionManager()
        self.bob   = EncryptionManager()
        self.alice.establish_session("bob",   self.bob.public_key_b64)
        self.bob.establish_session(  "alice", self.alice.public_key_b64)

    def test_basic_roundtrip(self):
        msg = "Hello, Bob! 🔐"
        enc = self.alice.encrypt("bob", msg)
        assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == msg

    def test_empty_string(self):
        enc = self.alice.encrypt("bob", "")
        assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == ""

    def test_unicode_message(self):
        msg = "こんにちは世界 — Привет мир — مرحبا"
        enc = self.alice.encrypt("bob", msg)
        assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == msg

    def test_long_message(self):
        msg = "A" * 100_000
        enc = self.alice.encrypt("bob", msg)
        assert self.bob.decrypt("alice", enc["ciphertext"], enc["nonce"]) == msg

    def test_ciphertext_not_plaintext(self):
        msg = "secret"
        enc = self.alice.encrypt("bob", msg)
        assert msg not in enc["ciphertext"]

    def test_nonce_is_random(self):
        """Each call produces a different nonce."""
        enc1 = self.alice.encrypt("bob", "hello")
        enc2 = self.alice.encrypt("bob", "hello")
        assert enc1["nonce"] != enc2["nonce"]

    def test_tampered_ciphertext_raises(self):
        """AES-GCM authentication tag must reject tampered data."""
        from cryptography.exceptions import InvalidTag
        enc = self.alice.encrypt("bob", "important")
        bad = enc["ciphertext"][:-4] + "AAAA"   # corrupt last bytes
        with pytest.raises((InvalidTag, Exception)):
            self.bob.decrypt("alice", bad, enc["nonce"])

    def test_wrong_peer_raises(self):
        """Cannot decrypt a message using the wrong session key."""
        charlie = EncryptionManager()
        charlie.establish_session("alice", self.alice.public_key_b64)
        enc = self.alice.encrypt("bob", "for bob")
        # Charlie's session key for alice differs → decryption must fail
        with pytest.raises(Exception):
            charlie.decrypt("alice", enc["ciphertext"], enc["nonce"])

    def test_no_session_raises(self):
        enc_mgr = EncryptionManager()
        with pytest.raises(ValueError):
            enc_mgr.encrypt("nobody", "hello")
