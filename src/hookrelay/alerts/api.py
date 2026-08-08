"""Alerts REST router — rule CRUD, notifier CRUD, status, history, test.

Mounted flat in ``create_app`` (repo convention) and token-protected by
the existing auth middleware. All error bodies are JSON ``{"detail": ...}``
with ``ValueError`` mapping to 422 and unknown ids to 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from hookrelay import _storage
from hookrelay.alerts.notifiers import (
    NotifierRegistry,
    load_notifiers_from_settings,
    save_notifiers_to_settings,
    validate_notifier_payload,
)
from hookrelay.alerts.rules import AlertRule
from hookrelay.alerts.storage import AlertRuleStore


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _get_store() -> Any:
    """Return the process-wide Storage (created on demand)."""
    store = _storage.get()
    if store is None:
        from hookrelay.server import _get_or_create_storage

        store = _get_or_create_storage()
    return store


def _rule_store() -> AlertRuleStore:
    return AlertRuleStore(_get_store())


def _registry() -> NotifierRegistry:
    return load_notifiers_from_settings(_get_store())


def _evaluator_status() -> dict[str, Any]:
    evaluator = getattr(_get_store(), "_alert_evaluator", None)
    running = bool(evaluator is not None and evaluator.is_running())
    last_run_at = getattr(evaluator, "_last_run_at", None) if evaluator else None
    return {
        "interval_seconds": int(_get_store().get_setting("alert_interval_seconds", 60)),
        "evaluator_running": running,
        "last_run_at": last_run_at,
    }


def _rule_payload(rule: AlertRule) -> dict[str, Any]:
    return rule.to_dict()


def create_alerts_router() -> APIRouter:
    """Build the alerts REST router (rules + notifiers + status + history)."""
    router = APIRouter()

    # -- rules ---------------------------------------------------------

    @router.get("/api/alerts/rules")
    async def list_rules() -> dict[str, Any]:
        """Return every alert rule."""
        return {"rules": [_rule_payload(rule) for rule in _rule_store().list()]}

    @router.post("/api/alerts/rules", status_code=201)
    async def create_rule(body: dict[str, Any]) -> dict[str, Any]:
        """Create a rule; 422 on invalid fields, 404 on unknown notifier."""
        rule_id = body.get("rule_id") or uuid4().hex
        notifier_ids = list(body.get("notifier_ids") or [])
        registry = _registry()
        for notifier_id in notifier_ids:
            try:
                registry.get(notifier_id)
            except KeyError:
                raise HTTPException(
                    status_code=404,
                    detail=f"Notifier {notifier_id} not found",
                )
        now = _now_iso()
        rule = AlertRule(
            rule_id=rule_id,
            name=str(body.get("name") or ""),
            scope=body.get("scope", "all"),  # type: ignore[arg-type]
            endpoint_id=body.get("endpoint_id"),
            metric=body.get("metric", "success_rate_below"),  # type: ignore[arg-type]
            threshold=float(body.get("threshold", 0)),
            window_minutes=int(body.get("window_minutes", 15)),
            cooldown_minutes=int(body.get("cooldown_minutes", 15)),
            enabled=bool(body.get("enabled", True)),
            notifier_ids=notifier_ids,
            created_at=now,
            updated_at=now,
            last_fired_at=None,
        )
        try:
            rule.validate()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _rule_store().create(rule)
        return _rule_payload(rule)

    @router.patch("/api/alerts/rules/{rule_id}")
    async def patch_rule(rule_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Partially update a rule (404 unknown, 422 invalid fields)."""
        try:
            updated = _rule_store().update(rule_id, **body)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return _rule_payload(updated)

    @router.delete("/api/alerts/rules/{rule_id}", status_code=204)
    async def delete_rule(rule_id: str) -> JSONResponse:
        """Delete a rule (404 unknown)."""
        if not _rule_store().delete(rule_id):
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        return JSONResponse(status_code=204, content={})

    # -- notifiers ------------------------------------------------------

    @router.get("/api/alerts/notifiers")
    async def list_notifiers() -> dict[str, Any]:
        """Return redacted notifier summaries."""
        return {"notifiers": _registry().list_notifiers()}

    @router.post("/api/alerts/notifiers", status_code=201)
    async def create_notifier(body: dict[str, Any]) -> dict[str, Any]:
        """Create a notifier; 422 on SSRF/validation failure."""
        try:
            notifier = validate_notifier_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        registry = _registry()
        notifier_id = registry.register(notifier)
        save_notifiers_to_settings(_get_store(), registry)
        return {
            "id": notifier_id,
            "notifier_id": notifier_id,
            "type": notifier.type,
        }

    @router.delete("/api/alerts/notifiers/{notifier_id}", status_code=204)
    async def delete_notifier(notifier_id: str) -> JSONResponse:
        """Delete a notifier (404 unknown)."""
        registry = _registry()
        try:
            registry.get(notifier_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Notifier {notifier_id} not found")
        registry._notifiers.pop(notifier_id, None)
        save_notifiers_to_settings(_get_store(), registry)
        return JSONResponse(status_code=204, content={})

    @router.post("/api/alerts/notifiers/{notifier_id}/test")
    def test_notifier(notifier_id: str) -> dict[str, Any]:
        """Fire a synthetic alert through one notifier (never 500s).

        Declared as a plain ``def`` (not ``async``) so FastAPI runs it in the
        threadpool: notifier ``send`` performs blocking HTTP/SMTP I/O, and
        doing that on the event loop would stall every other endpoint (same
        convention as ``bins/api.py`` forward).
        """
        registry = _registry()
        try:
            notifier = registry.get(notifier_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Notifier {notifier_id} not found")
        try:
            ok = notifier.send(
                {
                    "rule_id": "test",
                    "rule_name": "Test alert",
                    "metric": "test",
                    "observed_value": 0.0,
                    "threshold": 0.0,
                    "message": "Hookrelay test notification",
                }
            )
            return {"ok": ok, "detail": "Notification sent" if ok else "Notification failed"}
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "detail": str(exc)}

    # -- status + history -------------------------------------------------

    @router.get("/api/alerts/status")
    async def alerts_status() -> dict[str, Any]:
        """Return evaluator status (interval, running, last run)."""
        return _evaluator_status()

    @router.get("/api/alerts/history")
    async def alerts_history(
        rule_id: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        """Return fired-alert history, newest first (max 1000)."""
        events = _rule_store().list_history(rule_id=rule_id, limit=limit)
        return {"events": events}

    return router
