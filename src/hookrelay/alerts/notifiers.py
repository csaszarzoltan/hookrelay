"""Alert notifiers — Slack incoming webhook, SMTP email, generic webhook.

Every outbound target (Slack webhook URL, outbound webhook URL) is guarded
with the repo's SSRF protection (:func:`hookrelay.ssrf.validate_target_url`)
both when the notifier is validated (save time) and when it fires.
Notifier definitions persist as JSON under ``app_settings["alert_notifiers"]``
keyed by notifier id; the registry is rebuilt from settings on startup.
"""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import requests

from hookrelay.ssrf import validate_target_url

_NOTIFIER_TYPES = ("slack", "smtp", "webhook")

# Fields that must never be echoed back by list_notifiers / the API.
_SECRET_FIELDS = ("password",)

# Slack webhook URLs embed the secret token in the path
# (``/services/T000/B000/XXXX``) — listings must never expose it.
_SLACK_URL_MASKED_PATH = "/services/***"

_SLACK_PREFIX = "<hookrelay> "


def _check_ssrf(url: str, *, allow_private: bool = False) -> None:
    """Raise ``ValueError`` when ``url`` fails the repo's SSRF guard."""
    ok, reason = validate_target_url(url, allow_private=allow_private)
    if not ok:
        raise ValueError(f"URL blocked by SSRF protection: {reason}")


def _mask_slack_webhook_url(webhook_url: str) -> str:
    """Mask a Slack webhook URL so its secret path token never leaks.

    Keeps ``scheme://host`` and replaces the path with a fixed masked
    placeholder (``https://hooks.slack.com/services/***``). Falls back
    to ``"<redacted>"`` when the URL cannot be parsed.
    """
    try:
        parsed = urlparse(webhook_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{_SLACK_URL_MASKED_PATH}"
    except ValueError:
        pass
    return "<redacted>"


class Notifier(ABC):
    """Abstract notifier contract.

    Subclasses implement a single ``send`` channel; ``validate`` raises
    ``ValueError`` for misconfiguration; ``health`` must never raise.
    """

    type: str = ""

    @abstractmethod
    def send(self, alert: dict) -> bool:
        """Deliver one alert payload; return True on success."""

    @abstractmethod
    def validate(self) -> None:
        """Validate configuration, raising ``ValueError`` when invalid."""

    @abstractmethod
    def health(self) -> bool:
        """Return True when the notifier is reachable; never raises."""


class SlackNotifier(Notifier):
    """Send alerts to a Slack incoming-webhook URL."""

    type: str = "slack"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, alert: dict) -> bool:
        """POST ``{"text": "<hookrelay> <message>}`` to the webhook.

        The webhook URL is re-validated through the SSRF guard at fire
        time (the guard re-resolves DNS on every call, so a URL that was
        safe at save time is re-checked right before the POST); an unsafe
        URL makes ``send`` fail closed and return False.
        """
        try:
            self.validate()
        except ValueError:
            return False
        message = str(alert.get("message") or "Hookrelay alert")
        try:
            response = requests.post(
                self.webhook_url,
                json={"text": f"{_SLACK_PREFIX}{message}"},
                timeout=10,
            )
            return response.ok
        except requests.RequestException:
            return False

    def validate(self) -> None:
        """Reject non-http(s) or SSRF-unsafe webhook URLs."""
        _check_ssrf(self.webhook_url)

    def health(self) -> bool:
        """Slack health is checked at fire time; nothing to probe here."""
        try:
            self.validate()
        except ValueError:
            return False
        return True


class SmtpNotifier(Notifier):
    """Send alerts by email over SMTP (stdlib ``smtplib``)."""

    type: str = "smtp"

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_addr: str = "",
        to_addrs: list[str] | None = None,
        use_tls: bool = False,
        starttls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs or []
        self.use_tls = use_tls
        self.starttls = starttls

    def _open_smtp(self) -> smtplib.SMTP:
        client = smtplib.SMTP(self.host, self.port, timeout=10)
        if self.use_tls:
            client.starttls()
            client.ehlo()
        elif self.starttls:
            client.ehlo()
            try:
                client.starttls()
                client.ehlo()
            except smtplib.SMTPException:
                # Server did not offer STARTTLS; continue unencrypted.
                pass
        if self.username:
            client.login(self.username, self.password or "")
        return client

    def send(self, alert: dict) -> bool:
        """Compose a plain-text message and deliver it to every recipient."""
        if not self.from_addr or not self.to_addrs:
            return False
        message = EmailMessage()
        message["From"] = self.from_addr
        message["To"] = ", ".join(self.to_addrs)
        message["Subject"] = f"Hookrelay alert: {alert.get('rule_name') or alert.get('rule_id') or 'notification'}"
        message.set_content(str(alert.get("message") or "Hookrelay alert"))
        try:
            client = self._open_smtp()
            try:
                client.sendmail(self.from_addr, self.to_addrs, message.as_string())
            finally:
                try:
                    client.quit()
                except smtplib.SMTPException:
                    client.close()
            return True
        except (smtplib.SMTPException, OSError, ValueError):
            return False

    def validate(self) -> None:
        """Reject empty host / bad port / missing from or to addresses."""
        if not self.host or not self.host.strip():
            raise ValueError("host must not be empty")
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ValueError("port must be an integer in [1, 65535]")
        if not self.from_addr or "@" not in self.from_addr:
            raise ValueError("from_addr must be a valid email address")
        if not self.to_addrs:
            raise ValueError("to_addrs must not be empty")
        for address in self.to_addrs:
            if not address or "@" not in address:
                raise ValueError(f"invalid recipient address: {address}")

    def health(self) -> bool:
        """Probe the server with SMTP NOOP; never raises."""
        try:
            client = self._open_smtp()
            try:
                client.noop()
            finally:
                try:
                    client.quit()
                except smtplib.SMTPException:
                    client.close()
            return True
        except Exception:
            return False


class WebhookNotifier(Notifier):
    """Send alerts to a generic outbound webhook as JSON.

    ``allow_private`` is a test-only override: it bypasses the SSRF
    guard so tests can point a notifier at a local HTTP server. It is
    NOT accepted from the public API (``validate_notifier_payload``
    never reads it from a payload) and is never persisted to settings —
    every notifier rebuilt from settings therefore has
    ``allow_private=False`` and stays SSRF-guarded at save and fire.
    """

    type: str = "webhook"

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        allow_private: bool = False,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.allow_private = allow_private

    def send(self, alert: dict) -> bool:
        """POST the alert envelope with redirects disabled (SSRF-safe).

        The target URL is re-validated through the SSRF guard at fire
        time (re-resolving DNS right before the POST, so a URL that was
        safe at save time is checked again); an unsafe target makes
        ``send`` fail closed and return False.
        """
        try:
            self.validate()
        except ValueError:
            return False
        try:
            response = requests.post(
                self.url,
                json={
                    "alert": alert,
                    "type": "hookrelay.alert",
                    "version": 1,
                },
                headers=self.headers or None,
                timeout=10,
                allow_redirects=False,
            )
            return response.ok
        except requests.RequestException:
            return False

    def validate(self) -> None:
        """Reject SSRF-unsafe targets unless the test-only override is set."""
        _check_ssrf(self.url, allow_private=self.allow_private)

    def health(self) -> bool:
        """Outbound webhook health is checked at fire time."""
        try:
            self.validate()
        except ValueError:
            return False
        return True


class NotifierRegistry:
    """Registry of named notifiers with per-id fan-out.

    ``send_to`` never lets one failing notifier block the others; it
    returns a ``{notifier_id: bool}`` success map.
    """

    def __init__(self) -> None:
        self._notifiers: dict[str, Notifier] = {}

    def register(self, notifier: Notifier, notifier_id: str | None = None) -> str:
        """Register a notifier under an id (auto-generated when omitted)."""
        if notifier_id is None:
            notifier_id = f"{notifier.type}-{len(self._notifiers) + 1}"
        self._notifiers[notifier_id] = notifier
        return notifier_id

    def get(self, notifier_id: str) -> Notifier:
        """Return the notifier with ``notifier_id``.

        Raises:
            KeyError: unknown notifier id.
        """
        if notifier_id not in self._notifiers:
            raise KeyError(f"Notifier {notifier_id} not found")
        return self._notifiers[notifier_id]

    def send_to(self, notifier_ids: list[str], alert: dict) -> dict[str, bool]:
        """Send ``alert`` to every notifier; return a per-id success map."""
        results: dict[str, bool] = {}
        for notifier_id in notifier_ids:
            try:
                results[notifier_id] = self._notifiers[notifier_id].send(alert)
            except (KeyError, Exception):
                results[notifier_id] = False
        return results

    def list_notifiers(self) -> list[dict]:
        """Return redacted notifier summaries (secrets never included).

        Slack webhook URLs are masked to ``scheme://host`` + a masked
        path so the embedded secret token is never exposed; SMTP
        passwords are dropped entirely. The full values remain only in
        :meth:`to_payload` (persistence) and in the live notifier object.
        """
        result: list[dict] = []
        for notifier_id, notifier in self._notifiers.items():
            item: dict[str, Any] = {"id": notifier_id, "type": notifier.type}
            if isinstance(notifier, SlackNotifier):
                item["webhook_url"] = _mask_slack_webhook_url(notifier.webhook_url)
            elif isinstance(notifier, WebhookNotifier):
                item["url"] = notifier.url
                item["headers"] = notifier.headers
            elif isinstance(notifier, SmtpNotifier):
                item["host"] = notifier.host
                item["port"] = notifier.port
                item["from_addr"] = notifier.from_addr
                item["to_addrs"] = list(notifier.to_addrs)
            for secret in _SECRET_FIELDS:
                item.pop(secret, None)
            result.append(item)
        return result

    def to_payload(self) -> dict[str, dict]:
        """Serialize the registry to a settings-JSON-safe dict (id -> def)."""
        payload: dict[str, dict] = {}
        for notifier_id, notifier in self._notifiers.items():
            item: dict[str, Any] = {"type": notifier.type}
            if isinstance(notifier, SlackNotifier):
                item["webhook_url"] = notifier.webhook_url
            elif isinstance(notifier, WebhookNotifier):
                item["url"] = notifier.url
                item["headers"] = notifier.headers
            elif isinstance(notifier, SmtpNotifier):
                item["host"] = notifier.host
                item["port"] = notifier.port
                item["username"] = notifier.username
                item["password"] = notifier.password
                item["from_addr"] = notifier.from_addr
                item["to_addrs"] = list(notifier.to_addrs)
                item["use_tls"] = notifier.use_tls
                item["starttls"] = notifier.starttls
            payload[notifier_id] = item
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, dict]) -> NotifierRegistry:
        """Rebuild a registry from a persisted settings payload."""
        registry = cls()
        for notifier_id, definition in payload.items():
            registry.register(
                validate_notifier_payload(definition), notifier_id=notifier_id
            )
        return registry


def validate_notifier_payload(payload: dict) -> Notifier:
    """Build + validate a notifier from a JSON payload.

    Raises:
        ValueError: unknown type, missing required fields, or an
            SSRF-invalid URL.
    """
    notifier_type = payload.get("type")
    if notifier_type not in _NOTIFIER_TYPES:
        raise ValueError(
            f"type must be one of {', '.join(_NOTIFIER_TYPES)}"
        )
    if notifier_type == "slack":
        webhook_url = payload.get("webhook_url")
        if not webhook_url:
            raise ValueError("webhook_url is required for slack notifiers")
        notifier: Notifier = SlackNotifier(str(webhook_url))
    elif notifier_type == "smtp":
        host = payload.get("host")
        if not host:
            raise ValueError("host is required for smtp notifiers")
        notifier = SmtpNotifier(
            host=str(host),
            port=int(payload.get("port", 587)),
            username=payload.get("username"),
            password=payload.get("password"),
            from_addr=str(payload.get("from_addr") or ""),
            to_addrs=list(payload.get("to_addrs") or []),
            use_tls=bool(payload.get("use_tls", False)),
            starttls=bool(payload.get("starttls", True)),
        )
    else:  # webhook
        if "allow_private" in payload:
            raise ValueError(
                "allow_private is a test-only override and is not accepted "
                "via the API; use a public target URL"
            )
        url = payload.get("url")
        if not url:
            raise ValueError("url is required for webhook notifiers")
        notifier = WebhookNotifier(
            str(url),
            headers=dict(payload.get("headers") or {}),
        )
    notifier.validate()
    return notifier


def load_notifiers_from_settings(store: Any) -> NotifierRegistry:
    """Rebuild the registry from ``app_settings['alert_notifiers']``.

    Invalid persisted definitions are skipped (best-effort; a corrupt
    settings blob must not crash the evaluator).
    """
    raw = store.get_setting("alert_notifiers", {})
    registry = NotifierRegistry()
    if not isinstance(raw, dict):
        return registry
    for notifier_id, definition in raw.items():
        if not isinstance(definition, dict):
            continue
        try:
            registry.register(
                validate_notifier_payload(definition), notifier_id=str(notifier_id)
            )
        except ValueError:
            continue
    return registry


def save_notifiers_to_settings(store: Any, registry: NotifierRegistry) -> None:
    """Persist the registry to ``app_settings['alert_notifiers']``."""
    store.set_setting("alert_notifiers", registry.to_payload())
