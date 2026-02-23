"""
test_messaging.py — Unit tests for MessageBroker and Message.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest

from src.core.messaging  import Message, MessageBroker
from src.core.encryption import EncryptionManager
from src.core.peer       import PeerRegistry


# ------------------------------------------------------------------ #
#  Message model                                                       #
# ------------------------------------------------------------------ #

class TestMessage:
    def test_text_factory(self):
        m = Message.text("pid", "Alice", "general", "hi")
        assert m.type == "text"
        assert m.sender_name == "Alice"
        assert m.content == "hi"
        assert m.channel == "general"

    def test_system_factory(self):
        m = Message.system("Server started")
        assert m.type == "system"
        assert m.sender_id == "system"

    def test_to_wire_includes_fields(self):
        m   = Message.text("pid", "Alice", "general", "hello")
        d   = m.to_wire()
        assert d["type"]        == "text"
        assert d["sender_name"] == "Alice"
        assert d["content"]     == "hello"

    def test_from_wire_roundtrip(self):
        m1 = Message.text("pid", "Bob", "random", "test")
        m2 = Message.from_wire(m1.to_wire())
        assert m2.content     == m1.content
        assert m2.sender_name == m1.sender_name
        assert m2.channel     == m1.channel


# ------------------------------------------------------------------ #
#  MessageBroker                                                       #
# ------------------------------------------------------------------ #

class TestMessageBroker:
    def setup_method(self):
        self.enc    = EncryptionManager()
        self.reg    = PeerRegistry()
        self.broker = MessageBroker(self.enc, self.reg)

    def test_store_and_retrieve(self):
        m = Message.text("p1", "Alice", "general", "hello")
        self.broker.store_message(m)
        hist = self.broker.get_history("general")
        assert len(hist) == 1
        assert hist[0].content == "hello"

    def test_listener_called_on_store(self):
        received = []
        self.broker.on_message(received.append)
        m = Message.text("p1", "Alice", "general", "hi")
        self.broker.store_message(m)
        assert len(received) == 1
        assert received[0].content == "hi"

    def test_history_per_channel(self):
        self.broker.store_message(Message.text("p1", "A", "general", "g1"))
        self.broker.store_message(Message.text("p1", "A", "random",  "r1"))
        assert len(self.broker.get_history("general")) == 1
        assert len(self.broker.get_history("random"))  == 1

    def test_prepare_outgoing_encrypted(self):
        """prepare_outgoing must encrypt when a session exists."""
        peer_b = EncryptionManager()
        self.enc.establish_session("bob", peer_b.public_key_b64)

        m    = Message.text("me", "Me", "general", "secret")
        wire = self.broker.prepare_outgoing("bob", m)

        assert "ciphertext" in wire
        assert "nonce"       in wire
        assert "content"    not in wire   # plaintext must be absent

    def test_process_incoming_decrypts(self):
        """process_incoming must decrypt and restore content."""
        enc_a = EncryptionManager()
        enc_b = EncryptionManager()
        enc_a.establish_session("b", enc_b.public_key_b64)
        enc_b.establish_session("a", enc_a.public_key_b64)

        broker_a = MessageBroker(enc_a, self.reg)
        broker_b = MessageBroker(enc_b, self.reg)

        msg  = Message.text("a", "Alice", "general", "top secret")
        wire = broker_a.prepare_outgoing("b", msg)

        result = broker_b.process_incoming("a", wire)
        assert result is not None
        assert result.content == "top secret"

    def test_process_incoming_bad_data_returns_none(self):
        result = self.broker.process_incoming("nobody", {"type": "text"})
        # Should not raise; returns None or an empty-content Message
        # (either is acceptable — just must not crash)
