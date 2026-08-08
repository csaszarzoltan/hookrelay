"""Pre-development tests for the alerts REST API.

Interface tests (router factory, mounting contract): pass immediately.
Behavioral tests (rules CRUD, notifiers CRUD, status, auth): RED until the
developer implements ``src/hookrelay/alerts/api.py`` and mounts it flat in
``create_app`` (analysis-brief.md P0-4 / P0-5, §6).

Contract:
- ``create_alerts_router() -> APIRouter``; router mounted flat in
  ``create_app`` (``app.router.routes.append``), token-protected.
- ``GET /api/alerts/rules`` -> ``{"rules": [...]}``
- ``POST /api/alerts/rules`` -> 201 ``{rule_id, ...}``; 422 invalid; 404 unknown notifier
- ``PATCH /api/alerts/rules/{rule_id}`` -> ``{...}``; 404; 422
- ``DELETE /api/alerts/rules/{rule_id}`` -> 204; 404
- ``GET /api/alerts/notifiers`` -> ``{"notifiers": [...]}`` (secrets redacted)
- ``POST /api/alerts/notifiers`` -> 201; 422 SSRF/validation
- ``DELETE /api/alerts/notifiers/{notifier_id}`` -> 204; 404
- ``POST /api/alerts/notifiers/{notifier_id}/test`` -> ``{ok, detail}``
- ``GET /api/alerts/history?rule_id=&limit=`` -> ``{"events": [...]}``
- ``GET /api/alerts/status`` -> ``{interval_seconds, evaluator_running, last_run_at}``
- Errors are JSON ``{"detail": ...}``.
"""

from __future__ import annotations

import inspect
import json

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _client(tmp_path, monkeypatch, token: str | None = None):
    store = Storage(str(tmp_path / "alerts_api.db"))
    _storage.set(store)
    if token is None:
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HOOKRELAY_API_TOKEN", token)
    return TestClient(create_app()), store


def _rule_payload(**overrides) -> dict:
    payload = {
        "name": "high failure rate",
        "scope": "all",
        "metric": "success_rate_below",
        "threshold": 0.9,
        "window_minutes": 15,
        "cooldown_minutes": 15,
        "enabled": True,
        "notifier_ids": [],
    }
    payload.update(overrides)
    return payload


def _create_rule(client, **overrides) -> dict:
    response = client.post("/api/alerts/rules", json=_rule_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================
# Interface tests
# ============================================================


class TestAlertsApiInterface:
    def test_module_imports(self):
        from hookrelay.alerts import api as alerts_api  # noqa: F401

    def test_create_alerts_router_exists(self):
        from hookrelay.alerts.api import create_alerts_router

        assert callable(create_alerts_router)

    def test_create_alerts_router_returns_router(self):
        from hookrelay.alerts.api import create_alerts_router

        try:
            router = create_alerts_router()
        except NotImplementedError:
            pytest.skip("RED phase — router stub not implemented yet")
        assert isinstance(router, APIRouter)

    def test_router_registered_in_create_app(self):
        app = create_app()
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/api/alerts/rules" in paths
        assert "/api/alerts/notifiers" in paths
        assert "/api/alerts/status" in paths


# ============================================================
# Behavioral — rules CRUD
# ============================================================


class TestRulesCrud:
    def test_create_rule_returns_201(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/alerts/rules", json=_rule_payload())
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["rule_id"]
        assert data["name"] == "high failure rate"
        assert data["metric"] == "success_rate_below"

    def test_list_rules(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        _create_rule(client, name="rule a")
        _create_rule(client, name="rule b")
        response = client.get("/api/alerts/rules")
        assert response.status_code == 200
        assert response.json()["rules"]
        names = {r["name"] for r in response.json()["rules"]}
        assert {"rule a", "rule b"} <= names

    def test_patch_updates_rule(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = _create_rule(client)
        response = client.patch(
            f"/api/alerts/rules/{created['rule_id']}", json={"threshold": 0.5}
        )
        assert response.status_code == 200, response.text
        assert response.json()["threshold"] == 0.5

    def test_patch_toggles_enabled(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = _create_rule(client)
        response = client.patch(
            f"/api/alerts/rules/{created['rule_id']}", json={"enabled": False}
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    def test_patch_unknown_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.patch("/api/alerts/rules/ghost", json={"threshold": 0.5})
        assert response.status_code == 404

    def test_delete_returns_204(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = _create_rule(client)
        response = client.delete(f"/api/alerts/rules/{created['rule_id']}")
        assert response.status_code == 204

    def test_delete_unknown_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        assert client.delete("/api/alerts/rules/ghost").status_code == 404

    def test_list_after_delete_is_empty(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = _create_rule(client)
        client.delete(f"/api/alerts/rules/{created['rule_id']}")
        assert client.get("/api/alerts/rules").json()["rules"] == []


# ============================================================
# Behavioral — rules validation (422)
# ============================================================


class TestRulesValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            _rule_payload(name=""),
            _rule_payload(metric="bogus"),
            _rule_payload(threshold=1.5),           # success-rate threshold > 1
            _rule_payload(threshold=0.0),
            _rule_payload(scope="endpoint"),        # missing endpoint_id
            _rule_payload(window_minutes=0),
        ],
        ids=["empty-name", "bad-metric", "threshold-too-high",
             "threshold-zero", "endpoint-scope-no-id", "bad-window"],
    )
    def test_invalid_rule_rejected_422(self, tmp_path, monkeypatch, payload):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/alerts/rules", json=payload)
        assert response.status_code == 422, response.text
        assert "detail" in response.json()

    def test_unknown_notifier_id_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/rules",
            json=_rule_payload(notifier_ids=["does-not-exist"]),
        )
        assert response.status_code == 404, response.text
        assert "detail" in response.json()


# ============================================================
# Behavioral — notifiers CRUD
# ============================================================


class TestNotifiersCrud:
    def test_create_slack_notifier(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/notifiers",
            json={"type": "slack", "webhook_url": "https://hooks.slack.com/services/T/B/X"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["id"] or data["notifier_id"]
        assert data["type"] == "slack"

    def test_create_webhook_notifier(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/notifiers",
            json={"type": "webhook", "url": "https://hooks.example.com/alert"},
        )
        assert response.status_code == 201, response.text

    def test_create_smtp_notifier(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/notifiers",
            json={
                "type": "smtp", "host": "smtp.example.com", "port": 587,
                "from_addr": "a@example.com", "to_addrs": ["b@example.com"],
            },
        )
        assert response.status_code == 201, response.text

    def test_ssrf_url_rejected_422(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/notifiers",
            json={"type": "webhook", "url": "http://192.168.1.1:8000/hook"},
        )
        assert response.status_code == 422, response.text
        assert "detail" in response.json()

    def test_bad_type_rejected_422(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/alerts/notifiers",
            json={"type": "pagerduty", "url": "https://x.example.com"},
        )
        assert response.status_code == 422, response.text

    def test_list_notifiers_redacts_secrets(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        client.post(
            "/api/alerts/notifiers",
            json={
                "type": "smtp", "host": "smtp.example.com", "port": 587,
                "username": "bot", "password": "hunter2",
                "from_addr": "a@example.com", "to_addrs": ["b@example.com"],
            },
        )
        response = client.get("/api/alerts/notifiers")
        assert response.status_code == 200
        body = response.json()
        assert "notifiers" in body
        listing = json.dumps(body)
        assert "hunter2" not in listing, "password must be redacted"

    def test_delete_notifier(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = client.post(
            "/api/alerts/notifiers",
            json={"type": "webhook", "url": "https://hooks.example.com/alert"},
        ).json()
        notifier_id = created.get("notifier_id") or created.get("id")
        response = client.delete(f"/api/alerts/notifiers/{notifier_id}")
        assert response.status_code == 204

    def test_delete_unknown_notifier_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        assert client.delete("/api/alerts/notifiers/ghost").status_code == 404


# ============================================================
# Behavioral — notifier test endpoint + status + history
# ============================================================


class TestNotifierTestEndpoint:
    def test_test_endpoint_returns_ok_shape(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        created = client.post(
            "/api/alerts/notifiers",
            json={"type": "webhook", "url": "https://hooks.example.com/alert"},
        ).json()
        notifier_id = created.get("notifier_id") or created.get("id")
        response = client.post(f"/api/alerts/notifiers/{notifier_id}/test")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "ok" in data
        assert "detail" in data

    def test_test_unknown_notifier_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        assert (
            client.post("/api/alerts/notifiers/ghost/test").status_code == 404
        )


class TestAlertsStatus:
    def test_status_shape(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/alerts/status")
        assert response.status_code == 200
        data = response.json()
        assert "interval_seconds" in data
        assert "evaluator_running" in data
        assert "last_run_at" in data
        assert data["interval_seconds"] == 60


class TestAlertsHistory:
    def test_history_shape(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/alerts/history")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "events" in data

    def test_history_accepts_filters(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/alerts/history?rule_id=r1&limit=5")
        assert response.status_code == 200


# ============================================================
# Behavioral — auth
# ============================================================


class TestAlertsApiAuth:
    def test_endpoints_protected_when_token_configured(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        for method, path in (
            ("GET", "/api/alerts/rules"),
            ("POST", "/api/alerts/rules"),
            ("GET", "/api/alerts/notifiers"),
            ("POST", "/api/alerts/notifiers"),
            ("GET", "/api/alerts/status"),
            ("GET", "/api/alerts/history"),
        ):
            assert client.request(method, path).status_code == 401, (method, path)

    def test_bearer_token_allows_access(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        headers = {"Authorization": "Bearer secret-token"}
        assert client.get("/api/alerts/rules", headers=headers).status_code == 200

    def test_open_mode_without_token(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token=None)
        assert client.get("/api/alerts/rules").status_code == 200


# ============================================================
# Behavioral — hookrelay alerts CLI (P0-7)
# ============================================================


class TestAlertsCli:
    def test_alerts_app_registered(self):
        from hookrelay.cli import app as cli_app

        group_names = [g.name for g in cli_app.registered_groups]
        command_names = [c.name for c in cli_app.registered_commands]
        assert "alerts" in group_names or "alerts" in command_names

    def test_backend_functions_exist(self):
        from hookrelay.cli import alerts_create, alerts_delete, alerts_list

        assert callable(alerts_list)
        assert callable(alerts_create)
        assert callable(alerts_delete)

    def test_alerts_create_signature(self):
        from hookrelay.cli import alerts_create

        sig = inspect.signature(alerts_create)
        params = sig.parameters
        for name in ("name", "scope", "metric", "threshold"):
            assert name in params, name

    def test_alerts_list_empty(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hookrelay import _storage as storage_mod
        from hookrelay.cli import app as cli_app

        storage_mod.set(Storage(str(tmp_path / "alerts_cli.db")))
        runner = CliRunner()
        result = runner.invoke(cli_app, ["alerts", "list"])
        assert result.exit_code == 0, result.output

    def test_alerts_create_and_list_round_trip(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hookrelay import _storage as storage_mod
        from hookrelay.cli import app as cli_app

        storage_mod.set(Storage(str(tmp_path / "alerts_cli2.db")))
        runner = CliRunner()
        created = runner.invoke(
            cli_app,
            [
                "alerts", "create", "my-rule",
                "--scope", "all",
                "--metric", "success_rate_below",
                "--threshold", "0.9",
            ],
        )
        assert created.exit_code == 0, created.output
        listed = runner.invoke(cli_app, ["alerts", "list"])
        assert listed.exit_code == 0, listed.output
        assert "my-rule" in listed.output

    def test_alerts_delete_unknown_rule_exits_1(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hookrelay import _storage as storage_mod
        from hookrelay.cli import app as cli_app

        storage_mod.set(Storage(str(tmp_path / "alerts_cli3.db")))
        runner = CliRunner()
        result = runner.invoke(cli_app, ["alerts", "delete", "ghost-rule"])
        assert result.exit_code == 1
        assert "ghost-rule" in result.output
