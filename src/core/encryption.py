"""
encryption.py — End-to-end encryption layer.

Protocol
--------
1. On startup each peer generates a fresh X25519 key pair.
2. During the TCP handshake peers exchange public keys (base64-encoded).
3. Both sides independently derive the **same** 256-bit AES key via
   X25519 ECDH  →  HKDF-SHA256.
4. Every subsequent message is encrypted with AES-256-GCM
   (random 96-bit nonce, authenticated).

Libraries used: `cryptography` (PyCA)
"""

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


class EncryptionManager:
    """
    Manages key generation, ECDH session establishment, and
    AES-256-GCM message encryption / decryption.

    One instance per application; one session key per connected peer.
    """

    _HKDF_INFO = b"localdiscord-v1-session"

    def __init__(self):
        # Generate a fresh X25519 key pair for this session.
        self._private_key: X25519PrivateKey = X25519PrivateKey.generate()
        self._public_key  = self._private_key.public_key()

        # peer_id  →  AES-256 key bytes (32 bytes)
        self._session_keys: dict[str, bytes] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    #  Identity                                                            #
    # ------------------------------------------------------------------ #

    @property
    def public_key_bytes(self) -> bytes:
        """Raw 32-byte X25519 public key."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def public_key_b64(self) -> str:
        """Base64-encoded public key — safe to transmit as a JSON string."""
        return base64.b64encode(self.public_key_bytes).decode()

    # ------------------------------------------------------------------ #
    #  Session establishment                                               #
    # ------------------------------------------------------------------ #

    def establish_session(self, peer_id: str, peer_public_key_b64: str):
        """
        Perform ECDH with the peer's public key and store the derived
        AES session key.  Both sides call this independently and arrive
        at the same key.
        """
        peer_key_bytes = base64.b64decode(peer_public_key_b64)
        peer_pub_key   = X25519PublicKey.from_public_bytes(peer_key_bytes)

        # Diffie-Hellman shared secret (32 bytes)
        shared_secret = self._private_key.exchange(peer_pub_key)

        # Stretch into a proper 256-bit AES key
        aes_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=self._HKDF_INFO,
        ).derive(shared_secret)

        with self._lock:
            self._session_keys[peer_id] = aes_key

    def remove_session(self, peer_id: str):
        """Forget the session key when a peer disconnects."""
        with self._lock:
            self._session_keys.pop(peer_id, None)

    def has_session(self, peer_id: str) -> bool:
        with self._lock:
            return peer_id in self._session_keys

    # ------------------------------------------------------------------ #
    #  Encrypt / Decrypt                                                   #
    # ------------------------------------------------------------------ #

    def encrypt(self, peer_id: str, plaintext: str) -> dict:
        """
        Encrypt *plaintext* for *peer_id*.

        Returns:
            {"ciphertext": "<base64>", "nonce": "<base64>"}

        Raises:
            ValueError if no session has been established for this peer.
        """
        with self._lock:
            key = self._session_keys.get(peer_id)
        if not key:
            raise ValueError(f"No encryption session for peer '{peer_id}'")

        nonce      = os.urandom(12)          # 96-bit random nonce (AES-GCM requirement)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)

        return {
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "nonce":      base64.b64encode(nonce).decode(),
        }

    def decrypt(self, peer_id: str, ciphertext_b64: str, nonce_b64: str) -> str:
        """
        Decrypt a message from *peer_id*.

        Raises:
            ValueError if no session key exists.
            cryptography.exceptions.InvalidTag if the message is tampered.
        """
        with self._lock:
            key = self._session_keys.get(peer_id)
        if not key:
            raise ValueError(f"No encryption session for peer '{peer_id}'")

        plaintext = AESGCM(key).decrypt(
            base64.b64decode(nonce_b64),
            base64.b64decode(ciphertext_b64),
            None,
        )
        return plaintext.decode("utf-8")
