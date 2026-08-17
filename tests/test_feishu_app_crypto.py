"""Tests for feishu_app.crypto — the security-critical verification path.

No live Feishu-provided example vector was available while writing this
(#62's PR1), so correctness is anchored two ways instead: a round-trip
against Feishu's own documented encrypt scheme (SHA-256(encrypt_key) as
the AES-256-CBC key, IV prepended to the ciphertext, base64-wrapped) built
independently of the code under test, and explicit negative cases for
every rejection path a forged request could try.
"""
import base64
import json

import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from agentcore_notifier.adapters.django.services.feishu_app.crypto import (
    VerificationError,
    decrypt_event,
    is_url_verification,
    verify_and_parse,
)

ENCRYPT_KEY = "test-encrypt-key-value"
VERIFICATION_TOKEN = "test-verification-token"


def _feishu_encrypt(plaintext_obj, encrypt_key=ENCRYPT_KEY, iv=None):
    """Independent re-implementation of Feishu's documented encrypt
    scheme, used only to build test fixtures — must not import from the
    module under test."""
    import hashlib

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = iv or b"\x00" * AES.block_size
    plaintext = json.dumps(plaintext_obj).encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
    return base64.b64encode(iv + ciphertext).decode("utf-8")


class TestDecryptEvent:
    def test_round_trip(self):
        event = {"header": {"token": VERIFICATION_TOKEN}, "event": {"x": 1}}
        encrypted = _feishu_encrypt(event)
        assert decrypt_event(encrypted, ENCRYPT_KEY) == event

    def test_wrong_key_raises(self):
        encrypted = _feishu_encrypt({"a": 1})
        with pytest.raises(VerificationError):
            decrypt_event(encrypted, "wrong-key")

    def test_garbage_input_raises(self):
        with pytest.raises(VerificationError):
            decrypt_event("not-valid-base64!!!", ENCRYPT_KEY)

    def test_too_short_raises(self):
        with pytest.raises(VerificationError):
            decrypt_event(base64.b64encode(b"short").decode(), ENCRYPT_KEY)


class TestVerifyAndParse:
    def test_plaintext_body_with_matching_token(self):
        body = json.dumps(
            {"header": {"token": VERIFICATION_TOKEN}, "event": {}}
        ).encode()
        event = verify_and_parse(
            body, encrypt_key="", verification_token=VERIFICATION_TOKEN
        )
        assert event["header"]["token"] == VERIFICATION_TOKEN

    def test_plaintext_body_with_wrong_token_rejected(self):
        body = json.dumps({"header": {"token": "wrong"}}).encode()
        with pytest.raises(VerificationError):
            verify_and_parse(
                body, encrypt_key="", verification_token=VERIFICATION_TOKEN
            )

    def test_plaintext_body_with_no_token_rejected(self):
        body = json.dumps({"event": {}}).encode()
        with pytest.raises(VerificationError):
            verify_and_parse(
                body, encrypt_key="", verification_token=VERIFICATION_TOKEN
            )

    def test_encrypted_body_with_matching_token(self):
        inner = {"header": {"token": VERIFICATION_TOKEN}, "event": {"y": 2}}
        body = json.dumps(
            {"encrypt": _feishu_encrypt(inner)}
        ).encode()
        event = verify_and_parse(
            body,
            encrypt_key=ENCRYPT_KEY,
            verification_token=VERIFICATION_TOKEN,
        )
        assert event["event"]["y"] == 2

    def test_encrypted_body_with_wrong_token_rejected(self):
        inner = {"header": {"token": "wrong"}}
        body = json.dumps({"encrypt": _feishu_encrypt(inner)}).encode()
        with pytest.raises(VerificationError):
            verify_and_parse(
                body,
                encrypt_key=ENCRYPT_KEY,
                verification_token=VERIFICATION_TOKEN,
            )

    def test_encrypted_body_without_configured_key_rejected(self):
        """A forged request can't bypass verification just by wrapping
        itself in {"encrypt": ...} if the tenant never configured
        encryption — must fail closed, not silently try to parse as
        plaintext."""
        body = json.dumps({"encrypt": "anything"}).encode()
        with pytest.raises(VerificationError):
            verify_and_parse(
                body, encrypt_key="", verification_token=VERIFICATION_TOKEN
            )

    def test_non_json_body_rejected(self):
        with pytest.raises(VerificationError):
            verify_and_parse(
                b"not json",
                encrypt_key="",
                verification_token=VERIFICATION_TOKEN,
            )

    def test_non_object_json_body_rejected(self):
        with pytest.raises(VerificationError):
            verify_and_parse(
                b"[1, 2, 3]",
                encrypt_key="",
                verification_token=VERIFICATION_TOKEN,
            )

    def test_forged_replay_with_stale_token_rejected(self):
        """Simulates the exact attack #62 called out: a POST with no
        real credential, hoping the endpoint doesn't actually check."""
        body = json.dumps(
            {"header": {"token": ""}, "event": {"draft_id": 1}}
        ).encode()
        with pytest.raises(VerificationError):
            verify_and_parse(
                body, encrypt_key="", verification_token=VERIFICATION_TOKEN
            )


class TestIsUrlVerification:
    def test_recognizes_challenge(self):
        ok, challenge = is_url_verification(
            {"type": "url_verification", "challenge": "abc123"}
        )
        assert ok is True
        assert challenge == "abc123"

    def test_ordinary_event_is_not_a_challenge(self):
        ok, challenge = is_url_verification(
            {"header": {"event_type": "card.action.trigger"}}
        )
        assert ok is False
        assert challenge is None
