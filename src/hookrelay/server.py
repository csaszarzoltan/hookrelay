"""FastAPI server for hookrelay dashboard and API."""

from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hookrelay import __version__, _storage
from hookrelay.dashboard import (
    create_dashboard_router,
    get_live_manager,
    get_relay_manager,
)
from hookrelay.storage import Storage

# Module-level shared instance (for CLI access)
_relay_manager = get_relay_manager()


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
        await ws.accept()
        _relay_manager.register_client(channel, ws)
        import json
        await ws.send_text(json.dumps({"type": "heartbeat", "channel": channel}))
        try:
            while True:
                raw = await ws.receive_text()
                if raw == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
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
                        try:
                            store.store_delivery_attempt(
                                request_id=request_id,
                                channel=channel,
                                target_url=data.get("target_url"),
                                status=data.get("status", "transport_error"),
                                response_status=data.get("response_status"),
                                duration_ms=data.get("duration_ms"),
                                error=data.get("error"),
                            )
                            await get_live_manager().broadcast({
                                "type": "delivery_result",
                                "data": {**data, "channel": channel},
                            })
                        except Exception:
                            pass
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

    # Forward the complete request to relay clients on the selected channel.
    relay_payload = {
        "request_id": request_id,
        "channel": channel,
        "method": method,
        "path": result.get("path", "/"),
        "headers": headers,
        "body": body.decode("utf-8", errors="replace"),
        "query_params": query_params,
        "source_ip": source_ip,
        "received_at": result.get("received_at", ""),
    }
    forwarded_clients = await get_relay_manager().broadcast_async(
        channel, {"type": "webhook", "data": relay_payload}
    )

    # Broadcast a complete, JSON-safe summary to connected dashboards.
    try:
        await get_live_manager().broadcast({
            "type": "webhook",
            "data": {
                "request_id": request_id,
                "channel": channel,
                "method": method,
                "path": result.get("path", "/"),
                "source_ip": source_ip,
                "received_at": result.get("received_at", ""),
            },
        })
    except Exception:
        # Dashboard delivery must never block webhook ingestion.
        pass

    return JSONResponse(
        status_code=201,
        content={
            "request_id": request_id,
            "channel": channel,
            "method": method,
            "path": result.get("path", "/"),
            "forwarded_clients": forwarded_clients,
        },
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A configured FastAPI application with all routes mounted.
    """
    app = FastAPI(
        title="Hookrelay",
        version=__version__,
        description="Webhook relay and debugging dashboard",
    )

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

    # Register schema API routes
    _register_schema_api_routes(app)

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
