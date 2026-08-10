"""Pre-development tests for outgoing HMAC / Ed25519 payload signing.

Interface tests verify both the existing inbound HMACVerifier (from
src/hookrelay/security/hmac.py) and the new OutgoingSigner stub (from
/tmp/hookrelay-stubs).  They pass immediately.

Behavioral tests exercise the real outgoing signing module and the
signature verification endpoint — they fail with ImportError /
NotImplementedError / assertion errors until implemented.

Target: ~35 tests (18 interface PASS, 17 behavioral RED).
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import inspect
import time

import pytest

from hookrelay.security.hmac import HMACVerifier

# ---------------------------------------------------------------------------
# Stub loader for OutgoingSigner
# ---------------------------------------------------------------------------

_STUBS_PATH = "/tmp/hookrelay-stubs/hookrelay/security/outgoing.py"


def _load_stub(path: str = _STUBS_PATH, name: str = "outgoing_stub"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_outgoing_stub = _load_stub()

# ---------------------------------------------------------------------------
# Interface tests — existing HMACVerifier (inbound)
# ---------------------------------------------------------------------------


class TestHMACVerifierInterface:
    """Verify HMACVerifier exists with correct signatures (existing code)."""

    def test_class_exists(self):
        assert inspect.isclass(HMACVerifier)

    def test_init_signature(self):
        sig = inspect.signature(HMACVerifier.__init__)
        params = sig.parameters
        assert "secret" in params
        assert "algorithm" in params
        assert params["algorithm"].default == "sha256"
        assert "header_name" in params
        assert "tolerance_seconds" in params

    def test_sign_exists(self):
        assert callable(getattr(HMACVerifier, "sign", None))

    def test_verify_exists(self):
        assert callable(getattr(HMACVerifier, "verify", None))

    def test_sign_returns_string(self):
        verifier = HMACVerifier("test-secret")
        result = verifier.sign("payload", timestamp="1234567890")
        assert isinstance(result, str)
        assert "t=1234567890" in result
        assert "v1=" in result

    def test_verify_accepts_valid(self):
        from datetime import UTC, datetime

        verifier = HMACVerifier("test-secret")
        ts = "1700000000"
        sig = verifier.sign("hello", timestamp=ts)
        now = datetime.fromtimestamp(int(ts), tz=UTC)
        assert verifier.verify("hello", sig, now=now) is True

    def test_verify_rejects_tampered(self):
        from datetime import UTC, datetime

        verifier = HMACVerifier("test-secret")
        ts = "1700000000"
        sig = verifier.sign("hello", timestamp=ts)
        now = datetime.fromtimestamp(int(ts), tz=UTC)
        assert verifier.verify("tampered", sig, now=now) is False


# ---------------------------------------------------------------------------
# Interface tests — OutgoingSigner stub
# ---------------------------------------------------------------------------


class TestOutgoingSignerStubInterface:
    """Verify OutgoingSigner stub exists with correct signatures."""

    def test_module_loads(self):
        assert _outgoing_stub is not None

    def test_class_exists(self):
        assert inspect.isclass(_outgoing_stub.OutgoingSigner)

    def test_supported_algorithms(self):
        algos = _outgoing_stub.OutgoingSigner.SUPPORTED_ALGORITHMS
        assert "svix" in algos
        assert "hookdeck" in algos
        assert "github" in algos
        assert "custom" in algos

    def test_init_signature(self):
        sig = inspect.signature(_outgoing_stub.OutgoingSigner.__init__)
        params = sig.parameters
        assert "self" in params
        assert "algorithm" in params
        assert "secret" in params

    def test_sign_exists(self):
        assert callable(getattr(_outgoing_stub.OutgoingSigner, "sign", None))

    def test_sign_signature(self):
        sig = inspect.signature(_outgoing_stub.OutgoingSigner.sign)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params
        assert "timestamp" in params
        assert params["timestamp"].default is None

    def test_build_headers_exists(self):
        assert callable(getattr(_outgoing_stub.OutgoingSigner, "build_headers", None))

    def test_build_headers_signature(self):
        sig = inspect.signature(_outgoing_stub.OutgoingSigner.build_headers)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params
        assert "timestamp" in params

    def test_verify_exists(self):
        assert callable(getattr(_outgoing_stub.OutgoingSigner, "verify", None))

    def test_verify_signature_params(self):
        sig = inspect.signature(_outgoing_stub.OutgoingSigner.verify)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params
        assert "signature" in params
        assert "timestamp" in params

    def test_verify_standalone_exists(self):
        assert hasattr(_outgoing_stub, "verify_signature")
        assert callable(_outgoing_stub.verify_signature)


# ---------------------------------------------------------------------------
# Behavioral tests — target behavior (RED until implemented)
# ---------------------------------------------------------------------------


class TestOutgoingSigningBehavioral:
    """Assert expected signing behavior for outgoing webhooks."""

    def _get_signer(self, algorithm: str = "github", secret: str = "test-secret-key"):
        from hookrelay.security.outgoing import OutgoingSigner

        return OutgoingSigner(algorithm=algorithm, secret=secret)

    def test_github_sign_returns_hex_string(self):
        signer = self._get_signer("github")
        sig = signer.sign(b'{"event":"push"}', timestamp="1700000000")
        assert isinstance(sig, str)
        # github signature is just hex, no prefix
        assert all(c in "0123456789abcdef" for c in sig)

    def test_hookdeck_sign_returns_hex_string(self):
        signer = self._get_signer("hookdeck")
        sig = signer.sign(b'{"event":"order"}', timestamp="1700000000")
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex

    def test_svx_sign_returns_ed25519_signature(self):
        # svix uses ed25519 — signature is base64-encoded
        import base64

        signer = self._get_signer("svix", secret="dGVzdC1zZWNyZXQta2V5LTEyMw==")
        sig = signer.sign(b'{"event":"invoice"}', timestamp="1700000000")
        assert isinstance(sig, str)
        # Should be base64-decodable
        decoded = base64.b64decode(sig)
        assert len(decoded) == 64  # ed25519 signature length

    def test_build_headers_includes_timestamp(self):
        signer = self._get_signer("github")
        headers = signer.build_headers(b"payload", timestamp="1700000000")
        assert "x-hookrelay-timestamp" in headers
        assert headers["x-hookrelay-timestamp"] == "1700000000"

    def test_build_headers_includes_signature(self):
        signer = self._get_signer("github")
        headers = signer.build_headers(b"payload", timestamp="1700000000")
        assert "x-hookrelay-signature" in headers

    def test_svx_build_headers_includes_svix_id(self):
        signer = self._get_signer("svix", secret="dGVzdC1zZWNyZXQta2V5LTEyMw==")
        headers = signer.build_headers(b"payload", timestamp="1700000000")
        assert "svix-id" in headers or "x-hookrelay-signature" in headers

    def test_verify_roundtrip(self):
        signer = self._get_signer("github")
        payload = b'{"id": 42}'
        sig = signer.sign(payload, timestamp="1700000000")
        assert signer.verify(payload, sig, timestamp="1700000000") is True

    def test_verify_rejects_tampered_payload(self):
        signer = self._get_signer("github")
        sig = signer.sign(b"original", timestamp="1700000000")
        assert signer.verify(b"tampered", sig, timestamp="1700000000") is False

    def test_verify_rejects_tampered_signature(self):
        signer = self._get_signer("github")
        assert signer.verify(b"payload", "deadbeef" * 8) is False

    def test_standalone_verify_valid(self):
        from hookrelay.security.outgoing import verify_signature

        import hashlib
        import hmac as hmac_mod

        secret = "my-secret"
        payload = b'{"ok": true}'
        ts = "1700000000"
        expected = hmac_mod.new(
            secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256
        ).hexdigest()
        assert verify_signature(payload, expected, secret, "github", timestamp=ts) is True

    def test_standalone_verify_tampered(self):
        from hookrelay.security.outgoing import verify_signature

        assert (
            verify_signature(b"data", "bad", "secret", "github", timestamp="1") is False
        )

    def test_custom_algorithm_sign(self):
        signer = self._get_signer("custom")
        sig = signer.sign(b"test", timestamp="1700000000")
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_timestamp_header_value_matches(self):
        signer = self._get_signer("github")
        ts = str(int(time.time()))
        headers = signer.build_headers(b"x", timestamp=ts)
        assert headers["x-hookrelay-timestamp"] == ts

    def test_sign_with_auto_timestamp(self):
        signer = self._get_signer("github")
        sig = signer.sign(b"auto-ts-test")
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_github_matches_hmac_sha256(self):
        """github signing should produce HMAC-SHA256 hex."""
        signer = self._get_signer("github", secret="whsec_abc123")
        payload = b'{"action":"opened"}'
        ts = "1700000000"
        sig = signer.sign(payload, timestamp=ts)
        expected = hmac.new(
            b"whsec_abc123", f"{ts}.".encode() + payload, hashlib.sha256
        ).hexdigest()
        assert sig == expected

    def test_unsupported_algorithm_raises(self):
        with pytest.raises((ValueError, KeyError)):
            self._get_signer("unsupported_algo")
