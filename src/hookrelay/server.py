"""FastAPI server for hookrelay dashboard and API."""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hookrelay import __version__, _storage
from hookrelay.audit import create_audit_checkpoint, verify_audit_checkpoint
from hookrelay.auth import (
    SESSION_COOKIE,
    configured_token,
    request_actor,
    session_matches,
    session_value,
    token_matches,
)
from hookrelay.backup import create_backup, inspect_backup, list_backups
from hookrelay.dashboard import create_dashboard_router, get_live_manager
from hookrelay.events import create_event_envelope
from hookrelay.migrations import CURRENT_SCHEMA_VERSION
from hookrelay.query import RequestQuery
from hookrelay.relay import get_shared_relay_manager
from hookrelay.storage import Storage

# Module-level shared instance (for CLI access)
_relay_manager = get_shared_relay_manager()


def _get_or_create_storage(db_path: str | None = None) -> Storage:
    """Get existing storage or create a new one with optional path."""
    store = _storage.get()
    if store is None:
        import os
        import tempfile

        if db_path is None:
            db_dir = os.path.join(tempfile.gettempdir(), "hookrelay")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "webhooks.db")
        store = Storage(db_path)
        _storage.set(store)
    return store


def _register_relay_ws(app: FastAPI) -> None:
    """Mount the existing RelayManager WebSocket endpoint."""

    @app.websocket("/ws/{channel}")
    async def websocket_endpoint(ws: WebSocket, channel: str):
        auth_token = configured_token()
        bearer = ws.headers.get("authorization", "")
        bearer_token = bearer[7:] if bearer.lower().startswith("bearer ") else None
        if auth_token and not (
            token_matches(ws.query_params.get("token"), auth_token)
            or token_matches(bearer_token, auth_token)
            or session_matches(ws.cookies.get(SESSION_COOKIE), auth_token)
        ):
            await ws.close(code=1008, reason="Authentication required")
            return
        await ws.accept()
        session_id = _relay_manager.register_client(
            channel,
            ws,
            target_url=ws.query_params.get("target"),
            client_version=ws.query_params.get("client_version"),
            capabilities=[
                item for item in ws.query_params.get("capabilities", "").split(",") if item
            ],
            session_id=ws.query_params.get("session_id"),
        )
        import json
        await ws.send_text(json.dumps({
            "type": "heartbeat", "channel": channel, "session_id": session_id,
            "schema_version": 1,
        }))
        try:
            while True:
                raw = await ws.receive_text()
                if raw == "ping":
                    _relay_manager.heartbeat(session_id)
                    await ws.send_text(json.dumps({"type": "pong", "session_id": session_id}))
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if message.get("type") == "delivery_result":
                    data = message.get("data", {})
                    request_id = data.get("request_id")
                    if request_id:
                        store = _get_or_create_storage()
                        store.store_delivery_attempt(
                            request_id=request_id,
                            channel=channel,
                            target_url=data.get("target_url"),
                            status=data.get("status", "transport_error"),
                            response_status=data.get("response_status"),
                            duration_ms=data.get("duration_ms"),
                            error=data.get("error"),
                            response_headers=data.get("response_headers"),
                            response_body=data.get("response_body"),
                        )
        except Exception:
            pass
        finally:
            _relay_manager.unregister_client(channel, ws)


class _CreateSchemaRequest(BaseModel):
    name: str
    channel: str
    schema_definition: dict
    draft_version: str = "2020-12"
    enabled: bool = True
    severity_level: str = "error"
    version: str = "1.0.0"
    metadata: dict | None = None


class _UpdateSchemaRequest(BaseModel):
    name: str | None = None
    channel: str | None = None
    schema_definition: dict | None = None
    draft_version: str | None = None
    enabled: bool | None = None
    severity_level: str | None = None
    version: str | None = None
    metadata: dict | None = None


class _ValidateRequest(BaseModel):
    schema: dict | None = None
    schema_id: str | None = None
    payload: dict
    draft: str = "2020-12"


class _EnqueueDeliveryRequest(BaseModel):
    request_id: str
    endpoint_id: str
    target_url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    body: str | None = None
    idempotency_key: str | None = None
    policy: dict | None = None
    delivery_id: str | None = None


class _RecordAttemptRequest(BaseModel):
    success: bool
    response_status: int | None = None
    duration_ms: float | None = None
    error: str | None = None


def _register_schema_api_routes(app: FastAPI) -> None:
    """Register /api/v1/schemas and /api/v1/validate endpoints."""
    from fastapi import HTTPException

    from hookrelay.schemas import SchemaStore
    from hookrelay.validation import validate_payload as run_validation

    def _get_schema_store() -> SchemaStore:
        store = _get_or_create_storage()
        return SchemaStore(store)

    @app.post("/api/v1/schemas", status_code=201)
    async def api_create_schema(req: _CreateSchemaRequest):
        schema_store = _get_schema_store()
        try:
            return schema_store.create_schema(
                name=req.name,
                channel=req.channel,
                schema_definition=req.schema_definition,
                draft_version=req.draft_version,
                enabled=req.enabled,
                severity_level=req.severity_level,
                version=req.version,
                metadata=req.metadata,
            )
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.get("/api/v1/schemas")
    async def api_list_schemas(channel: str | None = None):
        schema_store = _get_schema_store()
        return schema_store.list_schemas(channel=channel, enabled_only=False)

    @app.get("/api/v1/schemas/{schema_id}")
    async def api_get_schema(schema_id: str):
        schema_store = _get_schema_store()
        result = schema_store.get_schema(schema_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Schema not found")
        return result

    @app.put("/api/v1/schemas/{schema_id}")
    async def api_update_schema(schema_id: str, req: _UpdateSchemaRequest):
        schema_store = _get_schema_store()
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        result = schema_store.update_schema(schema_id, **updates)
        if result is None:
            raise HTTPException(status_code=404, detail="Schema not found")
        return result

    @app.delete("/api/v1/schemas/{schema_id}", status_code=204)
    async def api_delete_schema(schema_id: str):
        schema_store = _get_schema_store()
        if not schema_store.delete_schema(schema_id):
            raise HTTPException(status_code=404, detail="Schema not found")

    @app.post("/api/v1/validate")
    async def api_validate(req: _ValidateRequest):
        schema_store = _get_schema_store()

        if req.schema_id:
            schema_record = schema_store.get_schema(req.schema_id)
            if schema_record is None:
                raise HTTPException(status_code=404, detail="Schema not found")
            schema_def = schema_record["schema_definition"]
            draft = req.draft or schema_record["draft_version"]
        elif req.schema:
            schema_def = req.schema
            draft = req.draft
        else:
            raise HTTPException(status_code=422, detail="Either 'schema' or 'schema_id' is required")

        try:
            result = run_validation(req.payload, schema_def, draft=draft)
            return result.to_dict()
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))


def _register_delivery_api_routes(app: FastAPI) -> None:
    """Register /api/deliveries, /api/dlq, and /api/dashboard/metrics.

    Exposes the v1.5 delivery infrastructure (RetryQueue / DeadLetterQueue /
    DeliveryTracker / DashboardService) as a REST surface. Enqueue keeps the
    SSRF guard and idempotency checks that RetryQueue.enqueue already enforces.
    """

    from fastapi import HTTPException

    from hookrelay.config.retry_policy import RetryPolicy
    from hookrelay.dashboard.service import DashboardService
    from hookrelay.delivery import DeadLetterQueue, DeliveryStatus, RetryQueue
    from hookrelay.delivery.tracker import DeliveryTracker

    def _delivery_or_404(store, delivery_id: str) -> dict:
        item = RetryQueue(store).get(delivery_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Delivery {delivery_id} not found")
        return item

    def _normalize_delivery(row: dict) -> dict:
        """Parse JSON-text columns (headers/policy) back into dicts."""
        item = dict(row)
        for column in ("headers", "policy"):
            raw = item.get(column)
            if isinstance(raw, str):
                try:
                    item[column] = json.loads(raw)
                except ValueError:
                    pass
        return item

    @app.get("/api/deliveries")
    async def api_list_deliveries(
        status: str | None = None,
        endpoint_id: str | None = None,
        limit: int = 100,
    ):
        store = _get_or_create_storage()
        if status is not None and status not in DeliveryStatus.ALL:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {', '.join(DeliveryStatus.ALL)}",
            )
        limit = max(1, min(limit, 1000))
        rows = DeliveryTracker(store).list(
            status=status, endpoint_id=endpoint_id, limit=limit
        )
        # Tracker rows carry headers/policy as JSON text; normalize to dicts
        # the same way RetryQueue.get() does.
        return [_normalize_delivery(row) for row in rows]

    @app.post("/api/deliveries", status_code=201)
    async def api_enqueue_delivery(req: _EnqueueDeliveryRequest, request: Request):
        store = _get_or_create_storage()
        from uuid import uuid4

        policy = RetryPolicy.from_dict(req.policy) if req.policy else None
        body_bytes = req.body.encode("utf-8") if req.body is not None else None
        delivery_id = req.delivery_id or uuid4().hex
        try:
            delivery_id = RetryQueue(store).enqueue(
                delivery_id=delivery_id,
                request_id=req.request_id,
                endpoint_id=req.endpoint_id,
                target_url=req.target_url,
                method=req.method,
                headers=req.headers,
                body=body_bytes,
                idempotency_key=req.idempotency_key,
                policy=policy,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        store.record_audit_event(
            "delivery.enqueue", request_actor(request), "delivery", delivery_id,
            "success", details={"endpoint_id": req.endpoint_id, "request_id": req.request_id},
        )
        return _delivery_or_404(store, delivery_id)

    @app.post("/api/deliveries/{delivery_id}/attempts")
    async def api_record_attempt(delivery_id: str, req: _RecordAttemptRequest, request: Request):
        store = _get_or_create_storage()
        _delivery_or_404(store, delivery_id)
        new_status = RetryQueue(store).record_attempt(
            delivery_id,
            success=req.success,
            response_status=req.response_status,
            duration_ms=req.duration_ms,
            error=req.error,
        )
        store.record_audit_event(
            "delivery.attempt", request_actor(request), "delivery", delivery_id,
            "success" if req.success else "failure",
            details={"status": new_status},
        )
        return _delivery_or_404(store, delivery_id)

    @app.get("/api/dlq")
    async def api_list_dlq(endpoint_id: str | None = None, limit: int = 100):
        store = _get_or_create_storage()
        limit = max(1, min(limit, 1000))
        return DeadLetterQueue(store).list_entries(limit=limit, endpoint_id=endpoint_id)

    @app.post("/api/dlq/{entry_id}/requeue")
    async def api_requeue_dlq(entry_id: str, request: Request):
        store = _get_or_create_storage()
        try:
            delivery_id = DeadLetterQueue(store).requeue(entry_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        store.record_audit_event(
            "dlq.requeue", request_actor(request), "delivery", delivery_id,
            "success", details={"dlq_entry": entry_id},
        )
        return {"delivery_id": delivery_id, "status": "pending"}

    @app.get("/api/dashboard/metrics")
    async def api_dashboard_metrics(
        window_minutes: int = 60,
        bucket_minutes: int = 5,
    ):
        if window_minutes < 1 or window_minutes > 1440:
            raise HTTPException(status_code=422, detail="window_minutes must be in [1, 1440]")
        if bucket_minutes < 1 or bucket_minutes > window_minutes:
            raise HTTPException(status_code=422, detail="bucket_minutes must be in [1, window_minutes]")
        store = _get_or_create_storage()
        service = DashboardService(store)
        return {
            "summary": service.summary(window_minutes=window_minutes),
            "time_series": service.time_series(
                window_minutes=window_minutes, bucket_minutes=bucket_minutes
            ),
            "endpoint_breakdown": service.endpoint_breakdown(
                window_minutes=window_minutes
            ),
        }


def _register_webhook_route(app: FastAPI) -> None:
    """Register the webhook ingestion endpoint."""

    @app.api_route("/webhook/{channel}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def webhook_ingest(channel: str, req: Request):
        """Ingest an incoming webhook."""
        return await _handle_webhook(channel, req)


async def _handle_webhook(channel: str, request: Request):
    """Common webhook handling logic for all HTTP methods."""
    from hookrelay.ingester import auto_validate, receive_webhook

    method = request.method
    headers = dict(request.headers)
    body = await request.body()
    query_params = dict(request.query_params)
    source_ip = headers.get("x-real-ip", headers.get("x-forwarded-for", request.client.host if request.client else "unknown"))

    # Receive & store the webhook
    result = receive_webhook(
        channel=channel,
        method=method,
        headers=headers,
        body=body,
        query_params=query_params,
        source_ip=source_ip,
    )

    # Store in database
    store = _get_or_create_storage()
    request_id = store.store_request(result)

    # Auto-validate if applicable (never blocks)
    try:
        validation_info = auto_validate(
            channel=channel,
            body=body,
            headers=headers,
        )
        result["validation"] = validation_info
        # Store validation results
        for vr in validation_info.get("results", []):
            try:
                store.store_validation_result(
                    request_id=request_id,
                    schema_id=vr.get("schema_id", "unknown"),
                    result=vr,
                )
            except Exception:
                pass
    except Exception:
        pass

    # Forward the full request to connected relay clients.
    await _relay_manager.broadcast_async(channel, {
        "type": "webhook",
        "data": {
            "request_id": request_id,
            "channel": channel,
            "method": method,
            "path": result.get("path", "/"),
            "headers": headers,
            "body": body.decode("utf-8", errors="replace"),
            "query_params": query_params,
            "source_ip": source_ip,
            "received_at": result.get("received_at", ""),
        },
    })

    # Persist and broadcast a versioned event for reconnect reconciliation.
    event = create_event_envelope(
        "webhook.received",
        {
            "request_id": request_id,
            "channel": channel,
            "method": method,
            "path": result.get("path", "/"),
            "source_ip": source_ip,
            "received_at": result.get("received_at", ""),
        },
        correlation_id=request_id,
    )
    event["cursor"] = store.append_event(event)
    store.record_audit_event(
        "request.received", "system", "request", request_id, "success",
        correlation_id=request_id, details={"channel": channel, "method": method},
    )
    try:
        await get_live_manager().broadcast({"type": "webhook", **event})
    except Exception:
        pass

    return JSONResponse(
        status_code=201,
        content={
            "request_id": request_id,
            "channel": channel,
            "method": method,
            "path": result.get("path", "/"),
        },
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A configured FastAPI application with all routes mounted.
    """
    # Apply the persisted retention policy on every server startup.
    store = _get_or_create_storage()
    retention_days = store.get_setting("retention_days", 30)
    store.purge_requests_older_than(retention_days)

    app = FastAPI(
        title="Hookrelay",
        version=__version__,
        description="Webhook relay and debugging dashboard",
    )
    auth_token = configured_token()

    @app.middleware("http")
    async def optional_authentication(request: Request, call_next):
        """Protect dashboard and APIs only when a token is configured."""
        if not auth_token:
            return await call_next(request)
        path = request.url.path
        public = path in {"/health", "/", "/dashboard/login"} or path.startswith(
            ("/webhook/", "/dashboard/static/", "/bin/")
        )
        if public:
            return await call_next(request)
        bearer = request.headers.get("authorization", "")
        bearer_token = bearer[7:] if bearer.lower().startswith("bearer ") else None
        authenticated = token_matches(bearer_token, auth_token) or session_matches(
            request.cookies.get(SESSION_COOKIE), auth_token
        )
        if authenticated:
            return await call_next(request)
        if path.startswith("/dashboard/"):
            return RedirectResponse(
                url="/dashboard/login?next=" + path, status_code=303
            )
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required", "code": "unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/dashboard/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str | None = None):
        if not auth_token:
            return RedirectResponse(url="/dashboard/", status_code=303)
        message = '<p class="login-error" role="alert">Invalid access token.</p>' if error else ""
        return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign in — Hookrelay</title><link rel="stylesheet" href="/dashboard/static/style.css"></head>
<body><main class="login-shell"><section class="login-card"><h1>Hookrelay</h1>
<p>Enter the access token configured for this server.</p>{message}
<form method="post" action="/dashboard/login">
<label for="access-token">Access token</label>
<input id="access-token" name="token" type="password" required autofocus autocomplete="current-password">
<input name="next" type="hidden" value="{request.query_params.get('next', '/dashboard/')}">
<button class="btn btn-primary" type="submit">Sign in</button></form></section></main></body></html>""")

    @app.post("/dashboard/login")
    async def login_submit(request: Request):
        from urllib.parse import parse_qs

        values = parse_qs((await request.body()).decode("utf-8", errors="replace"))
        candidate = values.get("token", [""])[0]
        next_path = values.get("next", ["/dashboard/"])[0]
        if not next_path.startswith("/dashboard/") or next_path.startswith("//"):
            next_path = "/dashboard/"
        if not token_matches(candidate, auth_token):
            return HTMLResponse(
                (await login_page(request, error="invalid")).body,
                status_code=401,
            )
        response = RedirectResponse(url=next_path, status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session_value(auth_token),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            max_age=28800,
        )
        return response

    @app.post("/dashboard/logout")
    async def logout():
        response = RedirectResponse(url="/dashboard/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    # Health endpoint
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # Root redirect to dashboard
    @app.get("/")
    async def root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/")

    # Mount webhook ingestion
    _register_webhook_route(app)

    # Mount relay WebSocket
    _register_relay_ws(app)

    # Mount dashboard routes
    dashboard_router = create_dashboard_router()
    for route in dashboard_router.routes:
        app.router.routes.append(route)

    # Mount static files for dashboard
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent / "dashboard" / "static"
    if static_dir.exists():
        app.mount("/dashboard/static", StaticFiles(directory=str(static_dir)), name="dashboard_static")

    # Mount bins API + dashboard (v1.6.0 webhook capture bins).
    # Routes are appended manually (like the dashboard router) so app.routes
    # stays flat — Starlette's include_router wraps routes in _IncludedRouter
    # objects that break tests iterating app.routes for .path.
    from hookrelay.bins.api import create_bins_router
    from hookrelay.bins.dashboard import create_bins_dashboard_router

    bins_router = create_bins_router()
    for route in bins_router.routes:
        app.router.routes.append(route)
    bins_dashboard_router = create_bins_dashboard_router()
    for route in bins_dashboard_router.routes:
        app.router.routes.append(route)

    # Register schema API routes
    _register_schema_api_routes(app)

    # Register delivery / DLQ / dashboard-metrics API routes
    _register_delivery_api_routes(app)


    @app.get("/api/settings/retention")
    async def get_retention():
        store = _get_or_create_storage()
        return {"days": store.get_setting("retention_days", 30)}

    @app.put("/api/settings/retention")
    async def update_retention(request: Request, body: dict):
        days = body.get("days")
        if not isinstance(days, int) or days < 1 or days > 3650:
            return JSONResponse(status_code=422, content={"error": "days must be an integer from 1 to 3650"})
        store = _get_or_create_storage()
        store.set_setting("retention_days", days)
        store.record_audit_event(
            "retention.update", request_actor(request), "setting", "retention_days",
            "success", details={"days": days},
        )
        return {"days": days}

    @app.post("/api/settings/retention/purge")
    async def purge_retention(request: Request):
        store = _get_or_create_storage()
        days = store.get_setting("retention_days", 30)
        deleted = store.purge_requests_older_than(days)
        store.record_audit_event(
            "retention.purge", request_actor(request), "request_collection", None,
            "success", details={"days": days, "deleted": deleted},
        )
        return {"days": days, "deleted": deleted}

    @app.post("/api/data/backups", status_code=201)
    async def create_data_backup(request: Request):
        store = _get_or_create_storage()
        backup_dir = Path(store._db_path).resolve().parent / "backups"
        encryption_key = os.getenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY") or None
        bundle = create_backup(store, backup_dir, encryption_key=encryption_key)
        store.record_audit_event(
            "data.backup", request_actor(request), "database", str(store._db_path),
            "success", details={"sha256": bundle.sha256},
        )
        return {
            "database_path": str(bundle.database_path),
            "manifest_path": str(bundle.manifest_path),
            "sha256": bundle.sha256,
            "schema_version": store.schema_version,
            "encrypted": bool(encryption_key),
        }

    @app.get("/api/data/health")
    async def data_health():
        return _get_or_create_storage().storage_health()

    @app.get("/api/data/backup-policy")
    async def get_backup_policy():
        store = _get_or_create_storage()
        return {
            **store.get_backup_policy(),
            "last_backup_at": store.get_setting("last_backup_at"),
            "due": store.backup_is_due(),
        }

    @app.put("/api/data/backup-policy")
    async def update_backup_policy(request: Request, body: dict):
        store = _get_or_create_storage()
        try:
            store.set_backup_policy(
                enabled=body.get("enabled") is True,
                interval_hours=body.get("interval_hours"),
                keep_last=body.get("keep_last"),
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        policy = store.get_backup_policy()
        store.record_audit_event(
            "backup_policy.update", request_actor(request), "setting", "backup_policy",
            "success", details=policy,
        )
        return policy

    @app.post("/api/data/backups/run", status_code=201)
    async def run_data_backup(request: Request, body: dict | None = None):
        store = _get_or_create_storage()
        backup_dir = Path(store._db_path).resolve().parent / "backups"
        result = store.run_scheduled_backup(
            backup_dir, force=bool((body or {}).get("force", False))
        )
        if result.get("status") == "not_due":
            return JSONResponse(status_code=409, content=result)
        actor = request_actor(request)
        if actor != "local-session":
            store.record_audit_event(
                "data.backup.request", actor, "database", str(store._db_path),
                "success", details={"sha256": result["sha256"]},
            )
        return result

    @app.get("/api/data/backups/summary")
    async def backup_catalog_summary():
        store = _get_or_create_storage()
        backup_dir = Path(store._db_path).resolve().parent / "backups"
        items = list_backups(backup_dir)
        return {
            "total": len(items),
            "valid": sum(1 for item in items if item.get("valid")),
            "invalid": sum(1 for item in items if not item.get("valid")),
            "total_size_bytes": sum(
                int(item.get("database_size_bytes", 0)) for item in items
            ),
        }

    @app.delete("/api/data/backups", status_code=204)
    async def delete_backup_bundle(
        request: Request,
        manifest_path: str,
        confirm: bool = False,
    ):
        if not confirm:
            return JSONResponse(
                status_code=400,
                content={"error": "Set confirm=true to delete this backup bundle."},
            )
        store = _get_or_create_storage()
        backup_dir = (Path(store._db_path).resolve().parent / "backups").resolve()
        candidate = Path(manifest_path).resolve()
        if candidate.parent != backup_dir or candidate.suffix != ".json":
            return JSONResponse(
                status_code=400,
                content={"error": "manifest_path must reference the Hookrelay backup directory"},
            )
        if not candidate.is_file():
            return JSONResponse(status_code=404, content={"error": "Backup manifest not found"})
        try:
            manifest = json.loads(candidate.read_text(encoding="utf-8"))
            database_path = (backup_dir / manifest["database_file"]).resolve()
        except (OSError, KeyError, json.JSONDecodeError):
            return JSONResponse(status_code=422, content={"error": "Backup manifest is invalid"})
        if database_path.parent != backup_dir:
            return JSONResponse(status_code=400, content={"error": "Backup database path is invalid"})
        backup_id = manifest.get("backup_id", candidate.stem)
        candidate.unlink(missing_ok=True)
        database_path.unlink(missing_ok=True)
        store.record_audit_event(
            "data.backup.delete",
            request_actor(request),
            "backup",
            str(backup_id),
            "success",
            details={"manifest": candidate.name},
        )
        return HTMLResponse(status_code=204)

    @app.get("/api/data/backups")
    async def backup_catalog():
        store = _get_or_create_storage()
        backup_dir = Path(store._db_path).resolve().parent / "backups"
        return list_backups(backup_dir)

    @app.get("/api/data/backups/inspect")
    async def backup_inspection(manifest_path: str):
        store = _get_or_create_storage()
        backup_dir = (Path(store._db_path).resolve().parent / "backups").resolve()
        candidate = Path(manifest_path).resolve()
        if candidate.parent != backup_dir or candidate.suffix != ".json":
            return JSONResponse(
                status_code=400,
                content={"error": "manifest_path must reference the Hookrelay backup directory"},
            )
        result = inspect_backup(
            candidate,
            encryption_key=os.getenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY") or None,
        )
        return result if result.get("valid") else JSONResponse(status_code=422, content=result)

    @app.post("/api/audit/checkpoints", status_code=201)
    async def create_checkpoint():
        key = os.getenv("HOOKRELAY_AUDIT_SIGNING_KEY", "")
        if not key:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "HOOKRELAY_AUDIT_SIGNING_KEY is not configured",
                    "code": "signing_key_not_configured",
                },
            )
        return create_audit_checkpoint(_get_or_create_storage(), key)

    @app.post("/api/audit/checkpoints/verify")
    async def verify_checkpoint(body: dict):
        key = os.getenv("HOOKRELAY_AUDIT_SIGNING_KEY", "")
        if not key:
            return JSONResponse(
                status_code=503,
                content={"error": "Signing key is not configured", "code": "signing_key_not_configured"},
            )
        return verify_audit_checkpoint(_get_or_create_storage(), body, key)

    @app.get("/api/audit/verify")
    async def verify_audit():
        return _get_or_create_storage().verify_audit_chain()

    @app.post("/api/audit/purge")
    async def purge_audit(body: dict):
        days = body.get("days")
        if not isinstance(days, int) or days < 1 or days > 3650:
            return JSONResponse(
                status_code=422,
                content={"error": "days must be an integer from 1 to 3650"},
            )
        store = _get_or_create_storage()
        deleted = store.purge_audit_events_older_than(days)
        return {"days": days, "deleted": deleted, "chain": store.verify_audit_chain()}

    @app.get("/api/data/schema")
    async def data_schema():
        store = _get_or_create_storage()
        return {
            "current_version": store.schema_version,
            "supported_version": CURRENT_SCHEMA_VERSION,
            "migrations": store.migration_history(),
            "event_schema_version": 1,
            "request_query_schema_version": 1,
        }

    @app.get("/api/connections")
    async def connections(channel: str | None = None):
        return _relay_manager.list_connections(channel=channel)

    @app.get("/api/events")
    async def events(
        after_cursor: int = 0,
        limit: int = 100,
        event_type: str | None = None,
    ):
        store = _get_or_create_storage()
        try:
            items = store.list_events(after_cursor, limit, event_type)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return {
            "schema_version": 1,
            "items": items,
            "next_cursor": items[-1]["cursor"] if items else after_cursor,
        }

    @app.get("/api/requests/query")
    async def request_query(
        q: str | None = None,
        channel: str | None = None,
        methods: str | None = None,
        path: str | None = None,
        validation_status: str | None = None,
        delivery_status: str | None = None,
        received_from: str | None = None,
        received_to: str | None = None,
        replayed: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ):
        store = _get_or_create_storage()
        try:
            query = RequestQuery(
                q=q, channel=channel,
                methods=[item for item in methods.split(",") if item] if methods else None,
                path=path, validation_status=validation_status,
                delivery_status=delivery_status, received_from=received_from,
                received_to=received_to, replayed=replayed, limit=limit, cursor=cursor,
            )
            return store.query_requests(query)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/audit")
    async def audit_events(
        limit: int = 100,
        action: str | None = None,
        actor: str | None = None,
    ):
        return _get_or_create_storage().list_audit_events(limit, action, actor)

    return app


def start_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    db_path: str | None = None,
) -> None:
    """Start the hookrelay HTTP server.

    Initializes storage and returns. The actual uvicorn server is
    started by the CLI serve command.

    Args:
        host: Host to bind to.
        port: Port to listen on.
        reload: Enable auto-reload on file changes.
        db_path: Optional path to the SQLite database.
    """
    # Initialize storage before starting
    _get_or_create_storage(db_path)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    db_path: str | None = None,
) -> None:
    """Run the hookrelay HTTP server (blocking).

    Calls start_server() for initialization, then starts uvicorn.

    Args:
        host: Host to bind to.
        port: Port to listen on.
        reload: Enable auto-reload on file changes.
        db_path: Optional path to the SQLite database.
    """
    import uvicorn

    start_server(host=host, port=port, reload=reload, db_path=db_path)

    uvicorn.run(
        "hookrelay.server:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
