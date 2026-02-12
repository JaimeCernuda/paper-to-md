"""Tests for Ed25519 authentication."""

import base64

import pytest
from nacl.signing import SigningKey

from service.auth import build_signing_payload, verify_signature


class TestBuildSigningPayload:
    """Tests for canonical payload construction."""

    def test_basic_payload(self) -> None:
        payload = build_signing_payload("POST", "/submit_paper", "1700000000")
        expected = b"POST\n/submit_paper\n1700000000"
        assert payload == expected

    def test_get_request(self) -> None:
        payload = build_signing_payload("GET", "/status/abc", "1700000000")
        expected = b"GET\n/status/abc\n1700000000"
        assert payload == expected


class TestVerifySignature:
    """Tests for signature verification."""

    def test_valid_signature(self) -> None:
        sk = SigningKey.generate()
        pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
        payload = b"test payload"
        sig = sk.sign(payload).signature
        sig_b64 = base64.b64encode(sig).decode()

        # Should not raise
        verify_signature(pub_b64, sig_b64, payload)

    def test_invalid_signature_raises(self) -> None:
        sk = SigningKey.generate()
        pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
        payload = b"test payload"

        # Sign different data
        sig = sk.sign(b"wrong payload").signature
        sig_b64 = base64.b64encode(sig).decode()

        with pytest.raises(Exception):
            verify_signature(pub_b64, sig_b64, payload)

    def test_wrong_key_raises(self) -> None:
        sk1 = SigningKey.generate()
        sk2 = SigningKey.generate()
        pub_b64 = base64.b64encode(bytes(sk1.verify_key)).decode()
        payload = b"test payload"

        # Sign with different key
        sig = sk2.sign(payload).signature
        sig_b64 = base64.b64encode(sig).decode()

        with pytest.raises(Exception):
            verify_signature(pub_b64, sig_b64, payload)
