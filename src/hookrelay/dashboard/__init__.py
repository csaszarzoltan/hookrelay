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
    session_matches,
    token_matches,
)
from hookrelay.dashboard.connection_manager import ConnectionManager
from hookrelay.relay import RelayManager
from hookrelay.replay import RequestNotFoundError, replay_request

# Global connection manager for live monitoring
_live_manager = ConnectionManager()
_relay_manager = RelayManager()

# Templates directory relative to this file
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.globals["auth_enabled"] = lambda: configured_token() is not None


def create_dashboard_router() -> APIRouter:
    """Create the dashboard FastAPI router with all UI routes.

    All routes are prefixed with /dashboard.
    Returns:
        An APIRouter with dashboard routes mounted.
    """
    router = APIRouter()

    @router.get("/dashboard/", response_class=HTMLResponse)
    async def dashboard_index(request: Request):
        """Dashboard landing page with live feed overview."""
        store = _storage.get()
        recent_requests = store.list_requests(limit=10) if store else []
        total_count = store.count_requests() if store else 0
        return templates.TemplateResponse(
            request,
            "index.html",
            {"recent_requests": recent_requests, "total_count": total_count},
        )

    @router.get("/dashboard/history", response_class=HTMLResponse)
    async def dashboard_history(
        request: Request,
        channel: str | None = Query(None),
        method: str | None = Query(None),
        limit: int = Query(20),
        offset: int = Query(0),
        validation_status: str | None = Query(None),
    ):
        """History browser page with filters and pagination."""
        store = _storage.get()
        if store:
            requests = store.list_requests(
                channel=channel, limit=limit, offset=offset, method=method
            )
            total = store.count_requests(channel=channel)
            for req in requests:
                try:
                    vr = store.get_validation_results_for_request(
                        req.get("request_id", "")
                    )
                    if vr:
                        req["validation_status"] = (
                            "invalid" if not vr[0].get("valid", True) else "valid"
                        )
                except Exception:
                    pass
        else:
            requests = []
            total = 0

        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "requests": requests,
                "total": total,
                "channel": channel,
                "method": method,
                "limit": limit,
                "offset": offset,
                "validation_status": validation_status,
            },
        )

    @router.get("/dashboard/inspect/{request_id}", response_class=HTMLResponse)
    async def dashboard_inspect(request: Request, request_id: str):
        """Payload inspector page with validation status."""
        store = _storage.get()
        detail = store.get_request(request_id) if store else None
        validation_result = None
        delivery_attempts = store.list_delivery_attempts(request_id) if store and detail else []
        if store and detail:
            try:
                validation_result = store.get_validation_result(request_id)
            except Exception:
                pass

        return templates.TemplateResponse(
            request,
            "inspect.html",
            {
                "detail": detail,
                "validation_result": validation_result,
                "delivery_attempts": delivery_attempts,
                "request_id": request_id,
            },
        )

    @router.get("/dashboard/replay/{request_id}", response_class=HTMLResponse)
    async def dashboard_replay(request: Request, request_id: str):
        """Replay page for a specific webhook."""
        store = _storage.get()
        detail = store.get_request(request_id) if store else None
        return templates.TemplateResponse(
            request,
            "replay.html",
            {"detail": detail, "request_id": request_id},
        )

    @router.post("/api/replay/{request_id}")
    async def api_replay(request_id: str, body: dict[str, Any] | None = None):
        """Replay a webhook request via REST API."""
        store = _storage.get()
        if store is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"Request {request_id} not found"},
            )
        target = None
        if body:
            target = body.get("target")
        try:
            replay_request(
                request_id=request_id,
                channel="default",
                storage=store,
                relay_manager=_relay_manager,
                target_url=target,
            )
            return {"status": "ok", "request_id": request_id}
        except RequestNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": f"Request {request_id} not found"},
            )


    @router.get("/dashboard/settings", response_class=HTMLResponse)
    async def dashboard_settings(request: Request):
        store = _storage.get()
        retention_days = store.get_setting("retention_days", 30) if store else 30
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"retention_days": retention_days},
        )

    @router.websocket("/dashboard/ws/live")
    async def live_websocket(ws: WebSocket):
        """Live monitoring WebSocket for real-time dashboard updates."""
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
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text('{"type": "pong"}')
        except WebSocketDisconnect:
            await _live_manager.disconnect(ws)
        except Exception:
            try:
                await _live_manager.disconnect(ws)
            except ValueError:
                pass

    return router
