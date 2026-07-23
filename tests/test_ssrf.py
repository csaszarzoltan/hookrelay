"""Pre-development tests for SSRF protection module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import ssrf

# ============================================================
# Interface tests — function existence and signatures
# ============================================================

class TestSSRFInterface:
    """Verify ssrf module functions exist with correct signatures."""

    def test_validate_target_url_exists(self):
        assert hasattr(ssrf, "validate_target_url")
        assert callable(ssrf.validate_target_url)

    def test_validate_target_url_signature(self):
        sig = inspect.signature(ssrf.validate_target_url)
        params = sig.parameters
        assert "url" in params
        assert "allow_private" in params
        assert params["allow_private"].default is False
        assert "allowed_protocols" in params
        assert params["allowed_protocols"].default is None

    def test_is_private_ip_exists(self):
        assert hasattr(ssrf, "is_private_ip")
        assert callable(ssrf.is_private_ip)

    def test_is_private_ip_signature(self):
        sig = inspect.signature(ssrf.is_private_ip)
        assert "ip_address" in sig.parameters

    def test_resolve_and_check_exists(self):
        assert hasattr(ssrf, "resolve_and_check")
        assert callable(ssrf.resolve_and_check)

    def test_resolve_and_check_signature(self):
        sig = inspect.signature(ssrf.resolve_and_check)
        assert "hostname" in sig.parameters

    def test_ssrf_error_class_exists(self):
        assert hasattr(ssrf, "SSRFError")
        assert inspect.isclass(ssrf.SSRFError)
        assert issubclass(ssrf.SSRFError, Exception)

    def test_validate_target_url_returns_tuple(self):
        """Interface test: verify function returns a tuple."""
        result = ssrf.validate_target_url("https://example.com/webhook")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ============================================================
# Behavioral tests — SSRFError is a real exception
# ============================================================

class TestSSRFErrorBehavior:
    """SSRFError is a real exception class (not a stub)."""

    def test_ssrf_error_can_be_raised(self):
        with pytest.raises(ssrf.SSRFError):
            raise ssrf.SSRFError("blocked by SSRF protection")

    def test_ssrf_error_is_exception_subclass(self):
        assert issubclass(ssrf.SSRFError, Exception)


# ============================================================
# Behavioral tests — real SSRF protection behavior
# ============================================================

class TestSSRFBehavioral:
    """Calling ssrf functions returns expected results."""

    def test_behavior_validate_target_url_default_allows_public(self):
        """A public https URL should be valid."""
        valid, reason = ssrf.validate_target_url("https://example.com/webhook")
        assert valid is True
        assert reason is None

    def test_behavior_validate_target_url_reject_private(self):
        """A private IP URL should be rejected by default."""
        valid, reason = ssrf.validate_target_url("http://192.168.1.1:3000/hook")
        assert valid is False
        assert reason is not None

    def test_behavior_validate_target_url_allow_private(self):
        """A private URL should be allowed when allow_private=True."""
        valid, reason = ssrf.validate_target_url(
            "http://localhost:8080/webhook", allow_private=True
        )
        assert valid is True
        assert reason is None

    def test_behavior_validate_target_url_bad_protocol(self):
        """A file:// URL should be rejected."""
        valid, reason = ssrf.validate_target_url(
            "file:///etc/passwd", allowed_protocols=("http", "https")
        )
        assert valid is False
        assert reason is not None
        assert "not allowed" in reason

    def test_behavior_is_private_ip_localhost_is_private(self):
        assert ssrf.is_private_ip("127.0.0.1") is True

    def test_behavior_is_private_ip_loopback_ipv6_is_private(self):
        assert ssrf.is_private_ip("::1") is True

    def test_behavior_is_private_ip_10_range_is_private(self):
        assert ssrf.is_private_ip("10.0.0.5") is True

    def test_behavior_is_private_ip_172_range_is_private(self):
        assert ssrf.is_private_ip("172.16.0.1") is True

    def test_behavior_is_private_ip_192_168_range_is_private(self):
        assert ssrf.is_private_ip("192.168.1.100") is True

    def test_behavior_is_private_ip_public_ip_is_not_private(self):
        assert ssrf.is_private_ip("8.8.8.8") is False

    def test_behavior_resolve_and_check_public_host(self):
        """A public hostname should resolve safely."""
        valid, reason = ssrf.resolve_and_check("example.com")
        assert valid is True
        assert reason is None

    def test_behavior_resolve_and_check_localhost_is_private(self):
        valid, reason = ssrf.resolve_and_check("localhost")
        assert valid is False
        assert reason is not None
        assert "private" in reason.lower()
