"""Pre-development tests for alert notifiers (Slack / SMTP / webhook + SSRF).

Interface tests (imports, ABC shape, signatures, type hints): pass immediately
against ``analysis/analysis-brief.md`` P0-3 / P1-5.

Behavioral tests (payload shapes, SSRF blocks, registry fan-out, settings
persistence, SMTP hardening): RED until ``src/hookrelay/alerts/notifiers.py``
is implemented.

Contract (P0-3):
- ``Notifier`` ABC: ``type``, ``send(alert) -> bool``, ``validate() -> None``
  (ValueError on invalid), ``health() -> bool``.
- ``SlackNotifier(webhook_url)`` POSTs ``{"text": "<hookrelay> <msg>"}``.
- ``SmtpNotifier(host, port=587, username, password, from_addr, to_addrs,
  use_tls, starttls)`` via stdlib smtplib.
- ``WebhookNotifier(url, headers=None, allow_private=False)`` POSTs JSON
  ``{"alert": {...}, "type": "hookrelay.alert", "version": 1}`` with
  ``timeout=10`` and ``allow_redirects=False``; SSRF guard at save + fire.
- ``NotifierRegistry.register/get/send_to/list_notifiers``.
- ``validate_notifier_payload(dict) -> Notifier`` (ValueError on SSRF/type).
- Settings persistence under ``app_settings["alert_notifiers"]``.
"""

from __future__ import annotations

import inspect
from abc import ABC
from typing import ClassVar, get_type_hints

import pytest

from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "notifiers.db"))


def _fake_post_factory(log: list[dict], status_code: int = 200):
    """Return a requests.post stand-in recording kwargs."""

    def fake_post(url, *args, **kwargs):
        log.append({"url": url, "args": args, "kwargs": kwargs})
        return _FakeResponse(status_code)

    return fake_post


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text
        self.ok = status_code < 400

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class _FakeSMTP:
    """Minimal smtplib.SMTP stand-in recording interactions."""

    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[str] = []
        self.starttls_called = False
        self.login_called: tuple[str, str] | None = None
        self.message: str | None = None
        self.from_addr: str | None = None
        self.to_addrs: list[str] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self) -> tuple:
        self.calls.append("ehlo")
        return (250, b"ok")

    def starttls(self) -> tuple:
        self.calls.append("starttls")
        self.starttls_called = True
        return (220, b"ready")

    def login(self, user: str, password: str) -> tuple:
        self.calls.append("login")
        self.login_called = (user, password)
        return (235, b"auth ok")

    def sendmail(self, from_addr: str, to_addrs: list[str], message: str) -> dict:
        self.calls.append("sendmail")
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.message = message
        return {}

    def quit(self) -> tuple:
        self.calls.append("quit")
        return (221, b"bye")

    def close(self) -> None:
        self.calls.append("close")


# ============================================================
# Interface tests — Notifier ABC
# ============================================================


class TestNotifierInterface:
    def test_module_imports(self):
        from hookrelay.alerts import notifiers  # noqa: F401

    def test_notifier_is_abstract(self):
        from hookrelay.alerts.notifiers import Notifier

        assert inspect.isclass(Notifier)
        assert issubclass(Notifier, ABC)

    def test_notifier_abstract_methods(self):
        from hookrelay.alerts.notifiers import Notifier

        for name in ("send", "validate", "health"):
            assert name in Notifier.__abstractmethods__, name

    def test_notifier_send_signature(self):
        from hookrelay.alerts.notifiers import Notifier

        sig = inspect.signature(Notifier.send)
        assert "alert" in sig.parameters
        hints = get_type_hints(Notifier.send)
        assert hints.get("return") is bool

    def test_notifier_validate_returns_none(self):
        from hookrelay.alerts.notifiers import Notifier

        hints = get_type_hints(Notifier.validate)
        assert hints.get("return") is None or "None" in str(hints.get("return"))

    def test_slack_notifier_exists(self):
        from hookrelay.alerts.notifiers import Notifier, SlackNotifier

        assert inspect.isclass(SlackNotifier)
        assert issubclass(SlackNotifier, Notifier)

    def test_slack_notifier_init_signature(self):
        from hookrelay.alerts.notifiers import SlackNotifier

        sig = inspect.signature(SlackNotifier.__init__)
        assert "webhook_url" in sig.parameters

    def test_smtp_notifier_init_signature(self):
        from hookrelay.alerts.notifiers import SmtpNotifier

        sig = inspect.signature(SmtpNotifier.__init__)
        params = sig.parameters
        for name in ("host", "port", "username", "password", "from_addr", "to_addrs"):
            assert name in params, name
        assert params["port"].default == 587

    def test_webhook_notifier_init_signature(self):
        from hookrelay.alerts.notifiers import WebhookNotifier

        sig = inspect.signature(WebhookNotifier.__init__)
        params = sig.parameters
        assert "url" in params
        assert "headers" in params

    def test_registry_class_exists(self):
        from hookrelay.alerts.notifiers import NotifierRegistry

        assert inspect.isclass(NotifierRegistry)

    def test_registry_methods_exist(self):
        from hookrelay.alerts.notifiers import NotifierRegistry

        for name in ("register", "get", "send_to", "list_notifiers"):
            assert callable(getattr(NotifierRegistry, name)), name

    def test_validate_notifier_payload_exists(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        assert callable(validate_notifier_payload)

    def test_notifier_types(self):
        from hookrelay.alerts.notifiers import (
            SlackNotifier,
            SmtpNotifier,
            WebhookNotifier,
        )

        assert SlackNotifier.type == "slack"
        assert SmtpNotifier.type == "smtp"
        assert WebhookNotifier.type == "webhook"


# ============================================================
# Behavioral — SlackNotifier
# ============================================================


class TestSlackNotifierBehavioral:
    def test_send_posts_text_payload(self, monkeypatch):
        from hookrelay.alerts.notifiers import SlackNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log))
        notifier = SlackNotifier("https://hooks.slack.com/services/T000/B000/XXXX")
        try:
            ok = notifier.send({"message": "deliveries failing"})
        except NotImplementedError:
            pytest.skip("RED phase — SlackNotifier.send stub not implemented yet")
        assert ok is True
        assert len(log) == 1
        body = log[0]["kwargs"].get("json")
        assert body is not None
        assert "deliveries failing" in body["text"]
        assert log[0]["kwargs"].get("timeout") is not None

    def test_send_returns_false_on_http_error(self, monkeypatch):
        from hookrelay.alerts.notifiers import SlackNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log, status_code=500))
        notifier = SlackNotifier("https://hooks.slack.com/services/T000/B000/XXXX")
        try:
            ok = notifier.send({"message": "boom"})
        except NotImplementedError:
            pytest.skip("RED phase — SlackNotifier.send stub not implemented yet")
        assert ok is False

    def test_validate_rejects_private_url(self):
        from hookrelay.alerts.notifiers import SlackNotifier

        notifier = SlackNotifier("http://192.168.1.10:9000/hook")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SlackNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_rejects_bad_scheme(self):
        from hookrelay.alerts.notifiers import SlackNotifier

        notifier = SlackNotifier("file:///etc/passwd")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SlackNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_accepts_public_https(self):
        from hookrelay.alerts.notifiers import SlackNotifier

        notifier = SlackNotifier("https://hooks.slack.com/services/T000/B000/XXXX")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SlackNotifier.validate stub not implemented yet")


# ============================================================
# Behavioral — WebhookNotifier (+ SSRF)
# ============================================================


class TestWebhookNotifierBehavioral:
    def test_send_posts_alert_envelope(self, monkeypatch):
        from hookrelay.alerts.notifiers import WebhookNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log))
        notifier = WebhookNotifier("https://example.com/hook", headers={"X-Token": "abc"})
        alert = {"rule_id": "r1", "message": "down"}
        try:
            ok = notifier.send(alert)
        except NotImplementedError:
            pytest.skip("RED phase — WebhookNotifier.send stub not implemented yet")
        assert ok is True
        assert len(log) == 1
        kwargs = log[0]["kwargs"]
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 10
        payload = kwargs["json"]
        assert payload["type"] == "hookrelay.alert"
        assert payload["version"] == 1
        assert payload["alert"]["rule_id"] == "r1"
        assert kwargs.get("headers") == {"X-Token": "abc"}

    def test_send_returns_false_on_http_error(self, monkeypatch):
        from hookrelay.alerts.notifiers import WebhookNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log, status_code=500))
        notifier = WebhookNotifier("https://example.com/hook")
        try:
            ok = notifier.send({"message": "x"})
        except NotImplementedError:
            pytest.skip("RED phase — WebhookNotifier.send stub not implemented yet")
        assert ok is False

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080/hook",
            "http://192.168.1.50:3000/hook",
            "http://10.0.0.5/hook",
            "http://169.254.169.254/latest/meta-data",
            "http://localhost:8080/hook",
            "http://[::1]:8080/hook",
            "http://example.com:80/hook",  # system port < 1024
            "file:///etc/passwd",
            "ftp://example.com/hook",
        ],
    )
    def test_validate_rejects_ssrf_targets(self, url):
        from hookrelay.alerts.notifiers import WebhookNotifier

        notifier = WebhookNotifier(url)
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — WebhookNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_accepts_public_https(self):
        from hookrelay.alerts.notifiers import WebhookNotifier

        notifier = WebhookNotifier("https://hooks.example.com/alert")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — WebhookNotifier.validate stub not implemented yet")

    def test_allow_private_test_hook(self):
        """Test-only override: allow_private=True accepts local targets."""
        from hookrelay.alerts.notifiers import WebhookNotifier

        notifier = WebhookNotifier("http://127.0.0.1:9000/hook", allow_private=True)
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — WebhookNotifier.validate stub not implemented yet")


# ============================================================
# Behavioral — SmtpNotifier
# ============================================================


class TestSmtpNotifierBehavioral:
    def _make(self, **overrides):
        from hookrelay.alerts.notifiers import SmtpNotifier

        base = {
            "host": "smtp.example.com", "port": 587, "username": None,
            "password": None, "from_addr": "alerts@example.com",
            "to_addrs": ["ops@example.com"],
        }
        base.update(overrides)
        return SmtpNotifier(**base)

    def test_send_builds_message_and_sends(self, monkeypatch):
        monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
        notifier = self._make()
        try:
            ok = notifier.send({"message": "deliveries failing", "rule_id": "r1"})
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.send stub not implemented yet")
        assert ok is True
        assert _FakeSMTP.instances
        smtp = _FakeSMTP.instances[-1]
        assert smtp.host == "smtp.example.com"
        assert smtp.port == 587
        assert smtp.from_addr == "alerts@example.com"
        assert smtp.to_addrs == ["ops@example.com"]
        assert "From:" in smtp.message
        assert "To:" in smtp.message
        assert "Subject:" in smtp.message
        assert "deliveries failing" in smtp.message

    def test_starttls_and_login_when_configured(self, monkeypatch):
        monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
        notifier = self._make(username="bot", password="secret")
        try:
            notifier.send({"message": "hi"})
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.send stub not implemented yet")
        smtp = _FakeSMTP.instances[-1]
        assert smtp.starttls_called is True
        assert smtp.login_called == ("bot", "secret")

    def test_validate_rejects_empty_host(self):
        notifier = self._make(host="")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_rejects_bad_port(self):
        notifier = self._make(port=0)
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_rejects_empty_from_addr(self):
        notifier = self._make(from_addr="")
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_rejects_empty_to_addrs(self):
        notifier = self._make(to_addrs=[])
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.validate stub not implemented yet")
        with pytest.raises(ValueError):
            notifier.validate()

    def test_validate_accepts_valid_config(self):
        notifier = self._make()
        try:
            notifier.validate()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.validate stub not implemented yet")

    def test_health_never_raises(self, monkeypatch):
        monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
        notifier = self._make()
        try:
            healthy = notifier.health()
        except NotImplementedError:
            pytest.skip("RED phase — SmtpNotifier.health stub not implemented yet")
        assert isinstance(healthy, bool)


# ============================================================
# Behavioral — NotifierRegistry
# ============================================================


class TestRegistryBehavioral:
    def test_register_returns_id(self):
        from hookrelay.alerts.notifiers import NotifierRegistry, WebhookNotifier

        registry = NotifierRegistry()
        try:
            notifier_id = registry.register(
                WebhookNotifier("https://example.com/hook")
            )
        except NotImplementedError:
            pytest.skip("RED phase — register stub not implemented yet")
        assert isinstance(notifier_id, str) and notifier_id

    def test_get_returns_registered(self):
        from hookrelay.alerts.notifiers import NotifierRegistry, WebhookNotifier

        registry = NotifierRegistry()
        notifier = WebhookNotifier("https://example.com/hook")
        try:
            notifier_id = registry.register(notifier)
            fetched = registry.get(notifier_id)
        except NotImplementedError:
            pytest.skip("RED phase — register/get stubs not implemented yet")
        assert fetched is notifier

    def test_get_unknown_raises_key_error(self):
        from hookrelay.alerts.notifiers import NotifierRegistry

        registry = NotifierRegistry()
        try:
            registry.get("ghost")
        except NotImplementedError:
            pytest.skip("RED phase — get stub not implemented yet")
        with pytest.raises(KeyError):
            registry.get("ghost")

    def test_send_to_returns_per_id_map(self, monkeypatch):
        from hookrelay.alerts.notifiers import NotifierRegistry, WebhookNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log))
        registry = NotifierRegistry()
        try:
            a = registry.register(WebhookNotifier("https://a.example.com/hook"))
            b = registry.register(WebhookNotifier("https://b.example.com/hook"))
            result = registry.send_to([a, b], {"message": "alert!"})
        except NotImplementedError:
            pytest.skip("RED phase — send_to stub not implemented yet")
        assert result == {a: True, b: True}

    def test_one_failing_notifier_does_not_block_others(self, monkeypatch):
        from hookrelay.alerts.notifiers import NotifierRegistry, WebhookNotifier

        log: list[dict] = []
        monkeypatch.setattr("requests.post", _fake_post_factory(log, status_code=500))
        registry = NotifierRegistry()
        try:
            a = registry.register(WebhookNotifier("https://a.example.com/hook"))
            b = registry.register(WebhookNotifier("https://b.example.com/hook"))
            result = registry.send_to([a, b], {"message": "x"})
        except NotImplementedError:
            pytest.skip("RED phase — send_to stub not implemented yet")
        assert result == {a: False, b: False}

    def test_list_notifiers_returns_dicts(self):
        from hookrelay.alerts.notifiers import NotifierRegistry, WebhookNotifier

        registry = NotifierRegistry()
        try:
            registry.register(WebhookNotifier("https://example.com/hook"))
            listing = registry.list_notifiers()
        except NotImplementedError:
            pytest.skip("RED phase — list_notifiers stub not implemented yet")
        assert isinstance(listing, list)
        assert all(isinstance(item, dict) for item in listing)


# ============================================================
# Behavioral — validate_notifier_payload + settings persistence
# ============================================================


class TestNotifierPayload:
    def test_valid_slack_payload(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        try:
            notifier = validate_notifier_payload(
                {"type": "slack", "webhook_url": "https://hooks.slack.com/services/T/B/X"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — validate_notifier_payload stub not implemented yet")
        assert notifier.type == "slack"

    def test_valid_smtp_payload(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        try:
            notifier = validate_notifier_payload(
                {
                    "type": "smtp", "host": "smtp.example.com", "port": 587,
                    "from_addr": "a@example.com", "to_addrs": ["b@example.com"],
                }
            )
        except NotImplementedError:
            pytest.skip("RED phase — validate_notifier_payload stub not implemented yet")
        assert notifier.type == "smtp"

    def test_valid_webhook_payload(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        try:
            notifier = validate_notifier_payload(
                {"type": "webhook", "url": "https://example.com/hook"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — validate_notifier_payload stub not implemented yet")
        assert notifier.type == "webhook"

    def test_unknown_type_rejected(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        try:
            validate_notifier_payload({"type": "pagerduty", "url": "https://x.example.com"})
        except NotImplementedError:
            pytest.skip("RED phase — validate_notifier_payload stub not implemented yet")
        with pytest.raises(ValueError):
            validate_notifier_payload({"type": "pagerduty", "url": "https://x.example.com"})

    def test_ssrf_url_rejected(self):
        from hookrelay.alerts.notifiers import validate_notifier_payload

        try:
            validate_notifier_payload({"type": "webhook", "url": "http://192.168.1.1:8000/h"})
        except NotImplementedError:
            pytest.skip("RED phase — validate_notifier_payload stub not implemented yet")
        with pytest.raises(ValueError):
            validate_notifier_payload({"type": "webhook", "url": "http://192.168.1.1:8000/h"})

    def test_round_trip_via_settings(self, store):
        """Notifiers persist under app_settings['alert_notifiers'] and reload."""
        from hookrelay.alerts.notifiers import (
            NotifierRegistry,
            WebhookNotifier,
            load_notifiers_from_settings,
            save_notifiers_to_settings,
        )

        registry = NotifierRegistry()
        try:
            registry.register(WebhookNotifier("https://example.com/hook"))
            save_notifiers_to_settings(store, registry)
            raw = store.get_setting("alert_notifiers")
            reloaded = load_notifiers_from_settings(store)
        except NotImplementedError:
            pytest.skip("RED phase — settings persistence stubs not implemented yet")
        assert isinstance(raw, dict) and len(raw) == 1
        assert len(reloaded.list_notifiers()) == 1
