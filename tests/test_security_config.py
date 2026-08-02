"""Pre-development tests for security & configuration (T2).

Interface tests (imports, signatures, type hints): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError (RED)
until the developer implements the module.

Target: >= 30 tests (~10 interface PASS, ~20 behavioral RED).
"""

from __future__ import annotations

import inspect
import re
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime

import pytest

from hookrelay.config.endpoint import EndpointConfig
from hookrelay.config.headers import HeaderManager
from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.security.hmac import HMACVerifier

# ============================================================
# Interface tests — HMACVerifier
# ============================================================


class TestHMACVerifierInterface:
    """Verify HMACVerifier class, signatures, and constructor state."""

    def test_class_exists(self):
        assert inspect.isclass(HMACVerifier)

    def test_init_signature(self):
        sig = inspect.signature(HMACVerifier.__init__)
        params = sig.parameters
        assert "self" in params
        assert "secret" in params
        assert params["secret"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert params["secret"].annotation in (str, "str")
        assert "algorithm" in params
        assert params["algorithm"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["algorithm"].default == "sha256"
        assert "header_name" in params
        assert params["header_name"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["header_name"].default == "X-Hookrelay-Signature"
        assert "tolerance_seconds" in params
        assert params["tolerance_seconds"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["tolerance_seconds"].default == 300

    def test_sign_signature(self):
        sig = inspect.signature(HMACVerifier.sign)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params
        assert params["payload"].annotation in (bytes, str, "bytes | str", "bytes", "str")
        assert "timestamp" in params
        assert params["timestamp"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["timestamp"].default is None

    def test_verify_signature(self):
        sig = inspect.signature(HMACVerifier.verify)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params
        assert "signature" in params
        assert "now" in params
        assert params["now"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["now"].default is None

    def test_constant_time_equals_is_staticmethod(self):
        assert isinstance(inspect.getattr_static(HMACVerifier, "constant_time_equals"), staticmethod)

    def test_constant_time_equals_signature(self):
        sig = inspect.signature(HMACVerifier.constant_time_equals)
        params = sig.parameters
        assert "a" in params
        assert "b" in params
        assert params["a"].annotation in (str, "str")
        assert params["b"].annotation in (str, "str")

    def test_constructor_stores_attributes(self):
        verifier = HMACVerifier("sekret", tolerance_seconds=60)
        assert verifier.secret == "sekret"
        assert verifier.algorithm == "sha256"
        assert verifier.header_name == "X-Hookrelay-Signature"
        assert verifier.tolerance_seconds == 60

    def test_constructor_custom_values(self):
        verifier = HMACVerifier("s", algorithm="sha512", header_name="X-Sig", tolerance_seconds=None)
        assert verifier.algorithm == "sha512"
        assert verifier.header_name == "X-Sig"
        assert verifier.tolerance_seconds is None


# ============================================================
# Interface tests — RetryPolicy
# ============================================================


class TestRetryPolicyInterface:
    """Verify RetryPolicy dataclass shape, fields, and defaults."""

    def test_is_frozen_dataclass(self):
        assert is_dataclass(RetryPolicy)
        assert RetryPolicy.__dataclass_params__.frozen is True

    def test_fields_exist(self):
        for name in (
            "max_retries",
            "backoff_factor",
            "base_delay_seconds",
            "max_backoff_seconds",
            "jitter",
        ):
            assert name in RetryPolicy.__dataclass_fields__

    def test_default_values(self):
        policy = RetryPolicy()
        assert policy.max_retries == 5
        assert policy.backoff_factor == 2.0
        assert policy.base_delay_seconds == 1.0
        assert policy.max_backoff_seconds == 3600.0
        assert policy.jitter is True

    def test_field_defaults_in_dataclass(self):
        fields = RetryPolicy.__dataclass_fields__
        assert fields["max_retries"].default == 5
        assert fields["backoff_factor"].default == 2.0
        assert fields["base_delay_seconds"].default == 1.0
        assert fields["max_backoff_seconds"].default == 3600.0
        assert fields["jitter"].default is True

    def test_backoff_delay_signature(self):
        sig = inspect.signature(RetryPolicy.backoff_delay)
        params = sig.parameters
        assert "self" in params
        assert "attempt" in params
        assert params["attempt"].annotation in (int, "int")

    def test_to_dict_exists(self):
        assert callable(RetryPolicy.to_dict)

    def test_from_dict_is_classmethod(self):
        assert isinstance(inspect.getattr_static(RetryPolicy, "from_dict"), classmethod)

    def test_custom_values_construct(self):
        policy = RetryPolicy(max_retries=2, backoff_factor=1.5, base_delay_seconds=0.5, jitter=False)
        assert policy.max_retries == 2
        assert policy.backoff_factor == 1.5
        assert policy.base_delay_seconds == 0.5
        assert policy.jitter is False

    def test_frozen_immutable(self):
        policy = RetryPolicy()
        with pytest.raises(FrozenInstanceError):
            policy.max_retries = 99


# ============================================================
# Interface tests — EndpointConfig
# ============================================================


class TestEndpointConfigInterface:
    """Verify EndpointConfig dataclass shape, fields, and defaults."""

    def test_is_frozen_dataclass(self):
        assert is_dataclass(EndpointConfig)
        assert EndpointConfig.__dataclass_params__.frozen is True

    def test_required_fields(self):
        for name in ("endpoint_id", "name", "url"):
            assert name in EndpointConfig.__dataclass_fields__

    def test_default_fields_exist(self):
        for name in (
            "timeout_seconds",
            "retry_policy",
            "headers",
            "secret",
            "enabled",
            "channel",
            "idempotency_ttl_seconds",
        ):
            assert name in EndpointConfig.__dataclass_fields__

    def test_construct_minimal(self):
        cfg = EndpointConfig(endpoint_id="ep-1", name="Acme", url="https://example.com/hook")
        assert cfg.timeout_seconds == 30.0
        assert cfg.retry_policy == RetryPolicy()
        assert cfg.headers == {}
        assert cfg.secret is None
        assert cfg.enabled is True
        assert cfg.channel is None
        assert cfg.idempotency_ttl_seconds == 86400

    def test_headers_uses_default_factory(self):
        fields = EndpointConfig.__dataclass_fields__
        assert fields["headers"].default_factory is dict

    def test_to_dict_exists(self):
        assert callable(EndpointConfig.to_dict)

    def test_from_dict_is_classmethod(self):
        assert isinstance(inspect.getattr_static(EndpointConfig, "from_dict"), classmethod)

    def test_validate_exists(self):
        assert callable(EndpointConfig.validate)

    def test_frozen_immutable(self):
        cfg = EndpointConfig(endpoint_id="ep-1", name="Acme", url="https://example.com/hook")
        with pytest.raises(FrozenInstanceError):
            cfg.url = "https://other.example.com/hook"


# ============================================================
# Interface tests — HeaderManager
# ============================================================


class TestHeaderManagerInterface:
    """Verify HeaderManager class, signatures, and constructor state."""

    def test_class_exists(self):
        assert inspect.isclass(HeaderManager)

    def test_init_signature(self):
        sig = inspect.signature(HeaderManager.__init__)
        params = sig.parameters
        assert "self" in params
        for name in ("base_headers", "injected", "forward_allowlist"):
            assert name in params
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[name].default is None

    def test_prepare_signature(self):
        sig = inspect.signature(HeaderManager.prepare)
        params = sig.parameters
        assert "self" in params
        assert "source_headers" in params
        assert params["source_headers"].default is None

    def test_add_injected_signature(self):
        sig = inspect.signature(HeaderManager.add_injected)
        params = sig.parameters
        assert "self" in params
        assert "name" in params
        assert "value" in params
        assert params["name"].annotation in (str, "str")
        assert params["value"].annotation in (str, "str")

    def test_redact_signature(self):
        sig = inspect.signature(HeaderManager.redact)
        params = sig.parameters
        assert "self" in params
        assert "headers" in params

    def test_constructor_stores_config(self):
        hm = HeaderManager(
            base_headers={"User-Agent": "hookrelay"},
            injected={"X-Signature": "abc"},
            forward_allowlist={"X-Request-Id"},
        )
        assert hm._base_headers == {"User-Agent": "hookrelay"}
        assert hm._injected == {"X-Signature": "abc"}
        assert hm._forward_allowlist == {"X-Request-Id"}

    def test_constructor_defaults(self):
        hm = HeaderManager()
        assert hm._base_headers == {}
        assert hm._injected == {}
        assert hm._forward_allowlist == set()


# ============================================================
# Behavioral tests — HMACVerifier (RED until implemented)
# ============================================================


class TestHMACVerifierBehavioral:
    """Calling HMACVerifier methods works correctly (currently RED)."""

    def test_sign_returns_svix_style_signature(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b'{"event": "charge.succeeded"}')
        assert re.fullmatch(r"t=\d+,v1=[0-9a-f]{64}", sig)

    def test_sign_accepts_str_payload(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign('{"event": "charge.succeeded"}')
        assert re.fullmatch(r"t=\d+,v1=[0-9a-f]{64}", sig)

    def test_sign_with_explicit_timestamp(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b"payload", timestamp="1700000000")
        assert sig.startswith("t=1700000000,")

    def test_sign_empty_secret_raises_value_error(self):
        verifier = HMACVerifier("")
        with pytest.raises(ValueError):
            verifier.sign(b"payload")

    def test_round_trip_verify_true(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b"payload")
        assert verifier.verify(b"payload", sig) is True

    def test_tampered_payload_fails(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b"payload")
        assert verifier.verify(b"tampered", sig) is False

    def test_wrong_secret_fails(self):
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b"payload")
        assert HMACVerifier("wrong-secret").verify(b"payload", sig) is False

    def test_constant_time_equals_same(self):
        assert HMACVerifier.constant_time_equals("abc123", "abc123") is True

    def test_constant_time_equals_different(self):
        assert HMACVerifier.constant_time_equals("abc123", "abc124") is False

    def test_constant_time_equals_diff_length(self):
        assert HMACVerifier.constant_time_equals("abc", "abcd") is False

    def test_verify_uses_constant_time_compare(self, monkeypatch):
        import hmac as hmac_module

        calls: list = []
        real_compare = hmac_module.compare_digest

        def fake_compare(a, b):
            calls.append((a, b))
            return real_compare(a, b)

        monkeypatch.setattr(hmac_module, "compare_digest", fake_compare)
        verifier = HMACVerifier("sekret")
        sig = verifier.sign(b"payload")
        assert verifier.verify(b"payload", sig) is True
        assert calls, "verify() must use hmac.compare_digest"

    def test_fresh_signature_passes_within_tolerance(self):
        verifier = HMACVerifier("sekret", tolerance_seconds=300)
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        ts = int(now.timestamp())
        sig = verifier.sign(b"payload", timestamp=str(ts - 60))  # 60s old
        assert verifier.verify(b"payload", sig, now=now) is True

    def test_stale_signature_fails_beyond_tolerance(self):
        verifier = HMACVerifier("sekret", tolerance_seconds=300)
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        ts = int(now.timestamp())
        sig = verifier.sign(b"payload", timestamp=str(ts - 600))  # 600s old > 300
        assert verifier.verify(b"payload", sig, now=now) is False

    def test_tolerance_none_bypasses_timestamp(self):
        verifier = HMACVerifier("sekret", tolerance_seconds=None)
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        sig = verifier.sign(b"payload", timestamp="1000")  # ancient
        assert verifier.verify(b"payload", sig, now=now) is True

    def test_malformed_signature_returns_false(self):
        verifier = HMACVerifier("sekret")
        assert verifier.verify(b"payload", "garbage-not-a-signature") is False


# ============================================================
# Behavioral tests — RetryPolicy (RED until implemented)
# ============================================================


class TestRetryPolicyBehavioral:
    """Calling RetryPolicy methods works correctly (currently RED)."""

    def test_backoff_delay_attempt_zero(self):
        policy = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, jitter=False)
        assert policy.backoff_delay(0) == 1.0

    def test_backoff_delay_exponential(self):
        policy = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, jitter=False)
        assert policy.backoff_delay(0) == 1.0
        assert policy.backoff_delay(1) == 2.0
        assert policy.backoff_delay(2) == 4.0
        assert policy.backoff_delay(3) == 8.0

    def test_backoff_delay_custom_base_and_factor(self):
        policy = RetryPolicy(base_delay_seconds=0.5, backoff_factor=3.0, jitter=False)
        assert policy.backoff_delay(0) == 0.5
        assert policy.backoff_delay(1) == 1.5
        assert policy.backoff_delay(2) == 4.5

    def test_backoff_delay_capped_at_max_backoff(self):
        policy = RetryPolicy(
            base_delay_seconds=1.0,
            backoff_factor=2.0,
            max_backoff_seconds=30.0,
            jitter=False,
        )
        assert policy.backoff_delay(4) == 16.0
        assert policy.backoff_delay(10) == 30.0  # capped
        assert policy.backoff_delay(100) == 30.0

    def test_backoff_delay_jitter_within_bounds(self):
        policy = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, jitter=True)
        for attempt in range(5):
            delay = policy.backoff_delay(attempt)
            base = min(3600.0, 1.0 * 2.0**attempt)
            assert base <= delay < base * 2, f"attempt {attempt}: {delay}"

    def test_max_retries_customization(self):
        default = RetryPolicy()
        custom = RetryPolicy(max_retries=2)
        assert default.max_retries == 5
        assert custom.max_retries == 2

    def test_to_dict_round_trip(self):
        policy = RetryPolicy(max_retries=3, backoff_factor=1.5, base_delay_seconds=0.25, jitter=False)
        data = policy.to_dict()
        assert data["max_retries"] == 3
        assert data["backoff_factor"] == 1.5
        assert data["base_delay_seconds"] == 0.25
        assert data["max_backoff_seconds"] == 3600.0
        assert data["jitter"] is False
        restored = RetryPolicy.from_dict(data)
        assert restored == policy

    def test_from_dict_defaults(self):
        restored = RetryPolicy.from_dict({})
        assert restored == RetryPolicy()

    def test_from_dict_partial(self):
        restored = RetryPolicy.from_dict({"max_retries": 7, "jitter": False})
        assert restored.max_retries == 7
        assert restored.jitter is False
        assert restored.backoff_factor == 2.0


# ============================================================
# Behavioral tests — EndpointConfig (RED until implemented)
# ============================================================


def _make_endpoint(**overrides) -> EndpointConfig:
    base = {
        "endpoint_id": "ep-1",
        "name": "Acme webhook",
        "url": "https://example.com/hook",
    }
    base.update(overrides)
    return EndpointConfig(**base)


class TestEndpointConfigBehavioral:
    """Calling EndpointConfig methods works correctly (currently RED)."""

    def test_validate_valid_config_passes(self):
        cfg = _make_endpoint()
        assert cfg.validate() is None

    def test_validate_rejects_bad_url(self):
        with pytest.raises(ValueError):
            _make_endpoint(url="not-a-url").validate()

    def test_validate_rejects_empty_url(self):
        with pytest.raises(ValueError):
            _make_endpoint(url="").validate()

    def test_validate_rejects_zero_timeout(self):
        with pytest.raises(ValueError):
            _make_endpoint(timeout_seconds=0.0).validate()

    def test_validate_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            _make_endpoint(timeout_seconds=-5.0).validate()

    def test_validate_rejects_negative_max_retries(self):
        cfg = _make_endpoint(retry_policy=RetryPolicy(max_retries=-1))
        with pytest.raises(ValueError):
            cfg.validate()

    def test_to_dict_round_trip(self):
        cfg = _make_endpoint(
            timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_retries=2, jitter=False),
            headers={"X-Custom": "v1"},
            secret="s3cret",
            enabled=False,
            channel="stripe",
            idempotency_ttl_seconds=3600,
        )
        data = cfg.to_dict()
        restored = EndpointConfig.from_dict(data)
        assert restored == cfg

    def test_to_dict_contains_all_fields(self):
        cfg = _make_endpoint()
        data = cfg.to_dict()
        for name in (
            "endpoint_id",
            "name",
            "url",
            "timeout_seconds",
            "retry_policy",
            "headers",
            "secret",
            "enabled",
            "channel",
            "idempotency_ttl_seconds",
        ):
            assert name in data

    def test_from_dict_parses_retry_policy(self):
        cfg = EndpointConfig.from_dict(
            {
                "endpoint_id": "ep-9",
                "name": "GitHub",
                "url": "https://github.com/hooks",
                "retry_policy": {"max_retries": 1, "jitter": False},
            }
        )
        assert cfg.retry_policy.max_retries == 1
        assert cfg.retry_policy.jitter is False

    def test_headers_dict_is_independent_per_instance(self):
        a = _make_endpoint()
        b = _make_endpoint()
        a.headers["X-A"] = "1"
        assert b.headers == {}


# ============================================================
# Behavioral tests — HeaderManager (RED until implemented)
# ============================================================


class TestHeaderManagerBehavioral:
    """Calling HeaderManager methods works correctly (currently RED)."""

    def test_prepare_merges_base_and_injected(self):
        hm = HeaderManager(
            base_headers={"User-Agent": "hookrelay/1.0"},
            injected={"X-Signature": "sig123"},
        )
        out = hm.prepare()
        assert out["User-Agent"] == "hookrelay/1.0"
        assert out["X-Signature"] == "sig123"

    def test_prepare_injected_overrides_base(self):
        hm = HeaderManager(
            base_headers={"X-Token": "base"},
            injected={"X-Token": "injected"},
        )
        assert hm.prepare()["X-Token"] == "injected"

    def test_prepare_forwards_allowlisted_source_headers(self):
        hm = HeaderManager(forward_allowlist={"X-Request-Id", "X-Trace"})
        out = hm.prepare({"X-Request-Id": "req-1", "X-Secret": "shh", "X-Trace": "trace-1"})
        assert out["X-Request-Id"] == "req-1"
        assert out["X-Trace"] == "trace-1"
        assert "X-Secret" not in out

    def test_prepare_drops_non_allowlisted_source_headers(self):
        hm = HeaderManager(forward_allowlist={"X-Request-Id"})
        out = hm.prepare({"X-Not-Allowed": "nope"})
        assert "X-Not-Allowed" not in out

    def test_prepare_with_none_source_headers(self):
        hm = HeaderManager(base_headers={"User-Agent": "hookrelay"})
        assert hm.prepare(None) == {"User-Agent": "hookrelay"}

    def test_prepare_does_not_mutate_source(self):
        hm = HeaderManager(forward_allowlist={"X-Request-Id"})
        source = {"X-Request-Id": "req-1", "X-Other": "x"}
        hm.prepare(source)
        assert source == {"X-Request-Id": "req-1", "X-Other": "x"}

    def test_add_injected_visible_in_prepare(self):
        hm = HeaderManager(base_headers={"User-Agent": "hookrelay"})
        hm.add_injected("X-Idempotency-Key", "key-123")
        out = hm.prepare()
        assert out["X-Idempotency-Key"] == "key-123"
        assert out["User-Agent"] == "hookrelay"

    def test_redact_masks_authorization(self):
        out = HeaderManager().redact({"Authorization": "Bearer topsecret"})
        assert out["Authorization"] != "Bearer topsecret"

    def test_redact_masks_cookie(self):
        out = HeaderManager().redact({"Cookie": "session=abc123"})
        assert out["Cookie"] != "session=abc123"

    def test_redact_masks_x_api_key(self):
        out = HeaderManager().redact({"X-Api-Key": "sk-live-123"})
        assert out["X-Api-Key"] != "sk-live-123"

    def test_redact_case_insensitive(self):
        out = HeaderManager().redact({"authorization": "Bearer topsecret"})
        assert out["authorization"] != "Bearer topsecret"

    def test_redact_keeps_benign_headers(self):
        headers = {"Content-Type": "application/json", "User-Agent": "hookrelay"}
        out = HeaderManager().redact(headers)
        assert out["Content-Type"] == "application/json"
        assert out["User-Agent"] == "hookrelay"

    def test_redact_does_not_mutate_input(self):
        headers = {"Authorization": "Bearer topsecret", "X-Keep": "v"}
        HeaderManager().redact(headers)
        assert headers == {"Authorization": "Bearer topsecret", "X-Keep": "v"}
