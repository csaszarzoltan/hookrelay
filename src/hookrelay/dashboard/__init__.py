"""Dashboard router and templates for hookrelay web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from hookrelay import _storage
from hookrelay.auth import (
    SESSION_COOKIE,
    configured_token,
    request_actor,
    session_matches,
    token_matches,
)
from hookrelay.backup import list_backups
from hookrelay.dashboard.connection_manager import ConnectionManager
from hookrelay.relay import get_shared_relay_manager
from hookrelay.replay import (
    NoConnectedClientError,
    RequestNotFoundError,
    replay_request,
)

_live_manager = ConnectionManager()
_relay_manager = get_shared_relay_manager()
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.globals["auth_enabled"] = lambda: configured_token() is not None

_SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "api-key",
})


def get_live_manager() -> ConnectionManager:
    """Return the process-wide dashboard live connection manager."""
    return _live_manager


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Mask common secret-bearing request headers for display."""
    return {
        name: ("••••••••" if name.lower() in _SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def create_dashboard_router() -> APIRouter:
    """Create the dashboard FastAPI router."""
    router = APIRouter()

    @router.get("/dashboard/", response_class=HTMLResponse)
    async def dashboard_index(request: Request):
        store = _storage.get()
        recent_requests = store.list_requests(limit=10) if store else []
        total_count = store.count_requests() if store else 0
        return templates.TemplateResponse(
            request, "index.html",
            {"recent_requests": recent_requests, "total_count": total_count},
        )

    @router.get("/dashboard/history", response_class=HTMLResponse)
    async def dashboard_history(
        request: Request,
        channel: str | None = Query(None),
        method: str | None = Query(None),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        validation_status: str | None = Query(None),
        path: str | None = Query(None),
        q: str | None = Query(None),
        view: str | None = Query(None),
    ):
        store = _storage.get()
        selected_view = None
        saved_views = store.list_request_views() if store else []
        if store and view:
            selected_view = store.get_request_view(view)
            if selected_view:
                filters = selected_view["filters"]
                q = q or filters.get("q")
                channel = channel or filters.get("channel")
                method = method or filters.get("method")
                path = path or filters.get("path")
                validation_status = validation_status or filters.get("validation_status")
                if limit == 20 and filters.get("limit"):
                    limit = min(100, max(1, int(filters["limit"])))
        if not store:
            requests, total = [], 0
        else:
            if q:
                matched = store.search_requests(query=q, channel=channel, limit=10000)
                if method:
                    matched = [item for item in matched if item.get("method") == method]
                if path:
                    matched = [item for item in matched if path in item.get("path", "")]
            else:
                matched = store.list_requests(
                    channel=channel, limit=10000, offset=0, method=method, path=path
                )
            for item in matched:
                try:
                    results = store.get_validation_results_for_request(item["request_id"])
                    if results:
                        item["validation_status"] = "valid" if results[0].get("valid", True) else "invalid"
                except Exception:
                    pass
            if validation_status in {"valid", "invalid"}:
                matched = [item for item in matched if item.get("validation_status") == validation_status]
            total = len(matched)
            requests = matched[offset:offset + limit]
        return templates.TemplateResponse(
            request, "history.html",
            {
                "requests": requests, "total": total, "channel": channel,
                "method": method, "limit": limit, "offset": offset,
                "validation_status": validation_status, "path": path, "q": q,
                "saved_views": saved_views, "selected_view": selected_view,
                "selected_view_id": view, "has_next": offset + len(requests) < total,
            },
        )

    @router.get("/dashboard/inspect/{request_id}", response_class=HTMLResponse)
    async def dashboard_inspect(request: Request, request_id: str):
        store = _storage.get()
        detail = store.get_request(request_id) if store else None
        if detail:
            detail = dict(detail)
            detail["headers"] = redact_headers(detail.get("headers", {}))
        validation_result = None
        delivery_attempts = store.list_delivery_attempts(request_id) if store and detail else []
        if store and detail:
            try:
                validation_result = store.get_validation_result(request_id)
            except Exception:
                pass
        return templates.TemplateResponse(
            request, "inspect.html",
            {
                "detail": detail, "validation_result": validation_result,
                "delivery_attempts": delivery_attempts, "request_id": request_id,
            },
        )

    @router.get("/dashboard/replay/{request_id}", response_class=HTMLResponse)
    async def dashboard_replay(request: Request, request_id: str):
        store = _storage.get()
        detail = store.get_request(request_id) if store else None
        return templates.TemplateResponse(
            request, "replay.html", {"detail": detail, "request_id": request_id}
        )

    @router.post("/api/replay/{request_id}")
    async def api_replay(
        request: Request, request_id: str, body: dict[str, Any] | None = None
    ):
        store = _storage.get()
        detail = store.get_request(request_id) if store else None
        if detail is None:
            return JSONResponse(status_code=404, content={"error": f"Request {request_id} not found", "code": "not_found"})
        channel = detail.get("channel", "default")
        target = body.get("target") if body else None
        try:
            result = replay_request(
                request_id=request_id, channel=channel, storage=store,
                relay_manager=_relay_manager, target_url=target,
            )
            store.record_audit_event(
                "request.replay", request_actor(request), "request", request_id,
                "success", correlation_id=request_id,
                details={"channel": channel, "target_override": bool(target)},
            )
            return {"status": "ok", "request_id": request_id, "channel": channel, **result}
        except NoConnectedClientError as exc:
            store.record_audit_event(
                "request.replay", request_actor(request), "request", request_id,
                "failure", correlation_id=request_id,
                details={"channel": channel, "error_code": "no_connected_client"},
            )
            return JSONResponse(
                status_code=409,
                content={"error": str(exc), "code": "no_connected_client", "request_id": request_id, "channel": channel},
            )
        except RequestNotFoundError:
            return JSONResponse(status_code=404, content={"error": f"Request {request_id} not found", "code": "not_found"})

    @router.get("/api/dashboard/status")
    async def dashboard_status():
        return {
            "status": "ok",
            "dashboard_connections": _live_manager.active_connections,
            "relay_channels": {
                channel: len(clients) for channel, clients in _relay_manager._channels.items()
            },
        }

    @router.get("/api/requests/{request_id}/delivery-attempts")
    async def delivery_attempts(request_id: str):
        store = _storage.get()
        if store is None or store.get_request(request_id) is None:
            return JSONResponse(status_code=404, content={"error": f"Request {request_id} not found"})
        return store.list_delivery_attempts(request_id)

    @router.delete("/api/requests/{request_id}", status_code=204)
    async def delete_request(
        request: Request, request_id: str, confirm: bool = Query(False)
    ):
        if not confirm:
            return JSONResponse(status_code=400, content={"error": "Set confirm=true to delete this request."})
        store = _storage.get()
        if store is None or store.get_request(request_id) is None:
            return JSONResponse(status_code=404, content={"error": f"Request {request_id} not found"})
        store.record_audit_event(
            "request.delete", request_actor(request), "request", request_id, "success"
        )
        store.delete_request(request_id)
        return HTMLResponse(status_code=204)

    @router.get("/api/request-views")
    async def list_request_views():
        store = _storage.get()
        return store.list_request_views() if store else []

    @router.post("/api/request-views", status_code=201)
    async def create_request_view(body: dict[str, Any]):
        store = _storage.get()
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Storage unavailable"})
        try:
            view_id = store.save_request_view(str(body.get("name", "")), dict(body.get("filters", {})))
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return {"view_id": view_id, "name": body.get("name")}

    @router.delete("/api/request-views/{view_id}", status_code=204)
    async def delete_request_view(view_id: str):
        store = _storage.get()
        if store is None or not store.delete_request_view(view_id):
            return JSONResponse(status_code=404, content={"error": "Saved view not found"})
        return HTMLResponse(status_code=204)

    @router.get("/dashboard/backups", response_class=HTMLResponse)
    async def dashboard_backups(request: Request):
        store = _storage.get()
        if store:
            backup_dir = Path(store._db_path).resolve().parent / "backups"
            backups = list_backups(backup_dir)
        else:
            backups = []
        summary = {
            "total": len(backups),
            "valid": sum(1 for item in backups if item.get("valid")),
            "invalid": sum(1 for item in backups if not item.get("valid")),
            "total_size_bytes": sum(int(item.get("database_size_bytes", 0)) for item in backups),
        }
        return templates.TemplateResponse(
            request, "backups.html", {"backups": backups, "summary": summary}
        )

    @router.get("/dashboard/settings", response_class=HTMLResponse)
    async def dashboard_settings(request: Request):
        store = _storage.get()
        retention_days = store.get_setting("retention_days", 30) if store else 30
        backup_policy = store.get_backup_policy() if store else {
            "enabled": False, "interval_hours": 24, "keep_last": 7
        }
        storage_health = store.storage_health() if store else None
        last_backup_at = store.get_setting("last_backup_at") if store else None
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "retention_days": retention_days,
                "backup_policy": backup_policy,
                "storage_health": storage_health,
                "last_backup_at": last_backup_at,
            },
        )

    @router.websocket("/dashboard/ws/live")
    async def live_websocket(ws: WebSocket):
        auth_token = configured_token()
        if auth_token and not (
            token_matches(ws.query_params.get("token"), auth_token)
            or session_matches(ws.cookies.get(SESSION_COOKIE), auth_token)
        ):
            await ws.close(code=1008, reason="Authentication required")
            return
        await _live_manager.connect(ws)
        try:
            while True:
                if await ws.receive_text() == "ping":
                    await ws.send_text('{"type": "pong"}')
        except WebSocketDisconnect:
            await _live_manager.disconnect(ws)
        except Exception:
            try:
                await _live_manager.disconnect(ws)
            except ValueError:
                pass

    return router
