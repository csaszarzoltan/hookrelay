"""Typer CLI for hookrelay."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import typer

from hookrelay import _storage
from hookrelay.ssrf import validate_target_url
from hookrelay.storage import Storage

app = typer.Typer(
    name="hookrelay",
    help="Webhook relay tool for local development.",
    no_args_is_help=True,
)


def _ws_url(server: str, channel: str) -> str:
    """Convert an http(s) server URL to a WebSocket URL."""
    base = server.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif not base.startswith("ws://") and not base.startswith("wss://"):
        base = "ws://" + base
    return f"{base}/ws/{channel}"


def _get_storage() -> Storage:
    """Get or create the default storage."""
    store = _storage.get()
    if store is None:
        db_dir = os.path.join(tempfile.gettempdir(), "hookrelay")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "webhooks.db")
        store = Storage(db_path)
        _storage.set(store)
    return store


# ============================================================
# Backend functions (plain Python signatures for testing)
# ============================================================


def forward(
    channel: str,
    target: str,
    server: str = "http://localhost:8000",
    timeout: float = 30.0,
) -> None:
    """Forward webhooks from a channel to a local target URL.

    Usage: hookrelay forward <channel> <target>
    """
    from hookrelay.client import connect_and_forward

    try:
        typer.echo(f"Connecting to {_ws_url(server, channel)}...")
        connect_and_forward(server, channel, target, timeout)
    except KeyboardInterrupt:
        typer.echo("\nDisconnected.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def history(
    channel: str | None = None,
    limit: int = 20,
    method: str | None = None,
    path: str | None = None,
    request_id: str | None = None,
) -> None:
    """Show recent webhook requests.

    Usage: hookrelay history [--channel CHANNEL] [--limit N]
           hookrelay history --id <request_id>
    """
    store = _get_storage()

    if request_id:
        detail = store.get_request(request_id)
        if detail is None:
            typer.echo(f"Request {request_id} not found.", err=True)
            raise typer.Exit(code=1)
        typer.echo(json.dumps(detail, indent=2, default=str))
        return

    results = store.list_requests(
        channel=channel, limit=limit, method=method, path=path
    )
    if not results:
        typer.echo("No webhooks found.")
        return

    for r in results:
        method_str = r.get("method", "POST")
        path_str = r.get("path", "/")
        rid = r.get("request_id", "")[:12]
        ts = r.get("received_at", "")
        src = r.get("source_ip", "")
        typer.echo(f"{ts} {method_str:7s} {path_str:30s} {rid}  {src}")


def replay(
    request_id: str,
    target: str | None = None,
    server: str = "http://localhost:8000",
) -> None:
    """Replay a stored webhook request.

    Usage: hookrelay replay <request_id>
    """
    from hookrelay.relay import RelayManager
    from hookrelay.replay import (
        NoConnectedClientError,
        RequestNotFoundError,
        replay_request,
    )

    store = _get_storage()
    relay_mgr = RelayManager()

    try:
        replay_request(
            request_id=request_id,
            channel="default",
            storage=store,
            relay_manager=relay_mgr,
            target_url=target,
        )
        typer.echo(f"Replayed {request_id}: OK")
        if target:
            typer.echo(f"  Target: {target}")
    except RequestNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    except NoConnectedClientError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def status(server: str = "http://localhost:8000") -> None:
    """Show connection health and server info.

    Usage: hookrelay status [--server URL]
    """
    health_url = f"{server.rstrip('/')}/health"
    # SSRF guard before any network I/O. The CLI is user-invoked against a
    # (usually local) relay, so private targets stay allowed (allow_private)
    # — the chokepoint still rejects non-http(s) schemes, malformed URLs,
    # and system ports, the same way EndpointConfig.validate does.
    parsed = urlparse(health_url)
    if parsed.scheme not in ("http", "https"):
        typer.echo(
            f"Error: unsupported URL scheme '{parsed.scheme}' "
            "(only http/https allowed)",
            err=True,
        )
        raise typer.Exit(code=1)
    is_valid, reason = validate_target_url(health_url, allow_private=True)
    if not is_valid:
        typer.echo(f"Error: invalid server URL: {reason}", err=True)
        raise typer.Exit(code=1)
    try:
        resp = urllib.request.urlopen(health_url, timeout=10)
        data = json.loads(resp.read().decode())
        typer.echo(f"Server: {server}")
        typer.echo(f"Status: {data.get('status', 'unknown')}")
        typer.echo(f"Version: {data.get('version', '?')}")
    except Exception as e:
        typer.echo(f"Server: {server}")
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def listen(
    channel: str,
    server: str = "http://localhost:8000",
) -> None:
    """Listen for webhooks on a channel (print to stdout).

    Usage: hookrelay listen <channel>
    """

    import websocket as ws

    try:
        ws_url = _ws_url(server, channel)
        ws_conn = ws.create_connection(ws_url, timeout=30)
        typer.echo(f"Listening on {ws_url}")
        typer.echo("Press Ctrl+C to stop.")
        while True:
            raw = ws_conn.recv()
            data = json.loads(raw)
            typer.echo(json.dumps(data, indent=2))
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


# ============================================================
# Typer command registration (wraps backend functions)
# ============================================================


@app.command("forward")
def _forward_cmd(
    channel: str = typer.Argument(..., help="Channel name"),
    target: str = typer.Argument(..., help="Local target URL"),
    server: str = typer.Option("http://localhost:8000", "--server", "-s", help="Relay server URL"),
    timeout: float = typer.Option(30.0, "--timeout", "-t", help="Connection timeout"),
):
    forward(channel=channel, target=target, server=server, timeout=timeout)


@app.command("history")
def _history_cmd(
    channel: str | None = typer.Option(None, "--channel", "-c", help="Filter by channel"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    method: str | None = typer.Option(None, "--method", "-m", help="Filter by method"),
    path: str | None = typer.Option(None, "--path", "-p", help="Filter by path"),
    request_id: str | None = typer.Option(None, "--id", help="Specific request ID"),
):
    history(
        channel=channel,
        limit=limit,
        method=method,
        path=path,
        request_id=request_id,
    )


@app.command("replay")
def _replay_cmd(
    request_id: str = typer.Argument(..., help="Request ID to replay"),
    target: str | None = typer.Option(None, "--target", "-t", help="Override target URL"),
    server: str = typer.Option("http://localhost:8000", "--server", "-s", help="Relay server URL"),
):
    replay(request_id=request_id, target=target, server=server)


@app.command("status")
def _status_cmd(
    server: str = typer.Option("http://localhost:8000", "--server", "-s", help="Relay server URL"),
):
    status(server=server)


@app.command("listen")
def _listen_cmd(
    channel: str = typer.Argument(..., help="Channel to listen on"),
    server: str = typer.Option("http://localhost:8000", "--server", "-s", help="Relay server URL"),
):
    listen(channel=channel, server=server)


def get_app() -> object:
    """Return the Typer application object with all commands registered."""
    return app


# ============================================================
# Schema subcommand — will be extended in Phase 7
# ============================================================


schema_app = typer.Typer(
    name="schema",
    help="Manage JSON Schema definitions for webhook validation.",
    no_args_is_help=True,
)
app.add_typer(schema_app, name="schema")


@schema_app.command("create")
def _schema_create_cmd(
    file: str = typer.Argument(..., help="Path to JSON Schema file"),
    channel: str = typer.Option("default", "--channel", "-c", help="Webhook channel"),
    name: str | None = typer.Option(None, "--name", "-n", help="Schema name"),
    version: str = typer.Option("1.0.0", "--version", "-v", help="Schema version"),
    severity: str = typer.Option("error", "--severity", help="Default severity level"),
    draft: str = typer.Option("2020-12", "--draft", "-d", help="JSON Schema draft version"),
):
    """Register a new JSON Schema from a file."""
    result = schema_create(file=file, channel=channel, name=name, version=version, severity=severity, draft=draft)
    typer.echo(json.dumps(result, indent=2, default=str))


@schema_app.command("list")
def _schema_list_cmd(
    channel: str | None = typer.Option(None, "--channel", "-c", help="Filter by channel"),
):
    """List registered schemas."""
    results = schema_list(channel=channel)
    if not results:
        typer.echo("No schemas found.")
        return
    for s in results:
        typer.echo(f"  {s['schema_id']}  {s['name']:20s}  channel={s['channel']}  enabled={s['enabled']}")


@schema_app.command("get")
def _schema_get_cmd(
    schema_id: str = typer.Argument(..., help="Schema ID"),
):
    """Show schema detail."""
    result = schema_get(schema_id=schema_id)
    typer.echo(json.dumps(result, indent=2, default=str))


@schema_app.command("delete")
def _schema_delete_cmd(
    schema_id: str = typer.Argument(..., help="Schema ID"),
):
    """Delete a schema."""
    schema_delete(schema_id=schema_id)
    typer.echo(f"Schema '{schema_id}' deleted.")


@schema_app.command("validate")
def _schema_validate_cmd(
    payload_file: str = typer.Argument(..., help="Path to JSON payload file"),
    schema_id: str | None = typer.Option(None, "--schema", "-s", help="Schema ID to validate against"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Channel to find schemas for"),
):
    """Validate a payload against a schema."""
    result = schema_validate(payload_file=payload_file, schema_id=schema_id, channel=channel)
    typer.echo(json.dumps(result, indent=2, default=str))


def schema_create(
    file: str,
    channel: str,
    name: str | None = None,
    version: str = "1.0.0",
    severity: str = "error",
    draft: str = "2020-12",
) -> dict:
    """Register a new JSON Schema from a file.

    Args:
        file: Path to JSON Schema file.
        channel: Webhook channel this schema applies to.
        name: Optional human-readable name (defaults to filename stem).
        version: Schema version string.
        severity: Default severity level (error, warning, info).
        draft: JSON Schema draft version.

    Returns:
        The created schema record as a dict.
    """
    from hookrelay.schemas import SchemaStore

    if not os.path.exists(file):
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(code=1)

    import json as json_mod
    try:
        with open(file) as f:
            schema_def = json_mod.load(f)
    except json_mod.JSONDecodeError as e:
        typer.echo(f"Error: Invalid JSON in schema file: {e}", err=True)
        raise typer.Exit(code=1)

    store = _get_storage()
    schema_store = SchemaStore(store)
    schema_name = name or os.path.splitext(os.path.basename(file))[0]
    result = schema_store.create_schema(
        name=schema_name,
        channel=channel,
        schema_definition=schema_def,
        version=version,
        severity_level=severity,
        draft_version=draft,
    )
    return result


def schema_list(channel: str | None = None) -> list[dict]:
    """List registered schemas.

    Args:
        channel: Optional channel filter.

    Returns:
        List of schema records.
    """
    from hookrelay.schemas import SchemaStore

    store = _get_storage()
    schema_store = SchemaStore(store)
    return schema_store.list_schemas(channel=channel, enabled_only=False)


def schema_get(schema_id: str) -> dict:
    """Show schema detail.

    Args:
        schema_id: The schema's unique ID.

    Returns:
        The schema record as a dict.
    """
    from hookrelay.schemas import SchemaStore

    store = _get_storage()
    schema_store = SchemaStore(store)
    result = schema_store.get_schema(schema_id)
    if result is None:
        typer.echo(f"Error: Schema '{schema_id}' not found.", err=True)
        raise typer.Exit(code=1)
    return result


def schema_delete(schema_id: str) -> bool:
    """Delete a schema.

    Args:
        schema_id: The schema's unique ID.

    Returns:
        True if deleted.
    """
    from hookrelay.schemas import SchemaStore

    store = _get_storage()
    schema_store = SchemaStore(store)
    if not schema_store.delete_schema(schema_id):
        typer.echo(f"Error: Schema '{schema_id}' not found.", err=True)
        raise typer.Exit(code=1)
    return True


def schema_validate(
    payload_file: str,
    schema_id: str | None = None,
    channel: str | None = None,
) -> dict:
    """Validate a payload against a schema.

    Args:
        payload_file: Path to JSON payload file.
        schema_id: Schema ID to validate against.
        channel: Channel to find schemas for.

    Returns:
        Validation result dict.
    """
    from hookrelay.schemas import SchemaStore
    from hookrelay.validation import validate_payload as validate_fn

    if not os.path.exists(payload_file):
        typer.echo(f"Error: File not found: {payload_file}", err=True)
        raise typer.Exit(code=1)

    import json as json_mod
    try:
        with open(payload_file) as f:
            payload = json_mod.load(f)
    except json_mod.JSONDecodeError as e:
        typer.echo(f"Error: Invalid JSON in payload file: {e}", err=True)
        raise typer.Exit(code=1)

    store = _get_storage()
    schema_store = SchemaStore(store)

    if schema_id:
        schema_record = schema_store.get_schema(schema_id)
        if schema_record is None:
            typer.echo(f"Error: Schema '{schema_id}' not found.", err=True)
            raise typer.Exit(code=1)
        result = validate_fn(payload, schema_record["schema_definition"], draft=schema_record["draft_version"])
        return {"valid": result.valid, "errors": [e.__dict__ for e in result.errors]}

    return {"valid": True, "errors": []}


# ============================================================
# Data resilience commands
# ============================================================


data_app = typer.Typer(help="Backup, restore, and verify Hookrelay data.")
app.add_typer(data_app, name="data")


@data_app.command("backup")
def data_backup(
    db_path: str = typer.Option(..., "--db-path", help="SQLite database to back up"),
    destination: str = typer.Option("./backups", "--destination", "-d", help="Backup directory"),
):
    """Create a consistent database backup and checksum manifest."""
    from hookrelay.backup import create_backup

    store = Storage(db_path)
    try:
        bundle = create_backup(
            store,
            destination,
            encryption_key=os.getenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY") or None,
        )
    finally:
        store.close()
    typer.echo(f"Manifest: {bundle.manifest_path}")
    typer.echo(f"Database: {bundle.database_path}")
    typer.echo(f"SHA-256: {bundle.sha256}")


@data_app.command("restore")
def data_restore(
    manifest: str = typer.Argument(..., help="Backup manifest JSON path"),
    db_path: str = typer.Option(..., "--db-path", help="Destination SQLite database"),
):
    """Verify and restore a backup, preserving any existing database."""
    from hookrelay.backup import BackupIntegrityError, restore_backup

    try:
        restored = restore_backup(
            manifest,
            db_path,
            encryption_key=os.getenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY") or None,
        )
    except (BackupIntegrityError, OSError, ValueError) as exc:
        typer.echo(f"Restore failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Restored: {restored}")
    rollback = Path(db_path).with_suffix(Path(db_path).suffix + ".pre_restore")
    if rollback.exists():
        typer.echo(f"Previous database: {rollback}")


@data_app.command("verify-audit")
def data_verify_audit(
    db_path: str = typer.Option(..., "--db-path", help="SQLite database to verify"),
):
    """Verify the tamper-evident audit hash chain."""
    store = Storage(db_path)
    try:
        result = store.verify_audit_chain()
    finally:
        store.close()
    if not result["valid"]:
        typer.echo(
            f"Audit verification failed at {result['broken_audit_id']}", err=True
        )
        raise typer.Exit(code=2)
    typer.echo(f"Audit chain valid. Checked {result['checked']} records.")


# ============================================================
# Delivery & DLQ commands
# ============================================================


def delivery_list(
    status: str | None = None,
    endpoint_id: str | None = None,
    limit: int = 20,
) -> None:
    """Show outbound deliveries, optionally filtered by status/endpoint.

    Usage: hookrelay delivery list [--status STATUS] [--endpoint-id ID] [--limit N]
    """
    from hookrelay.delivery import DeliveryStatus
    from hookrelay.delivery.tracker import DeliveryTracker

    if status is not None and status not in DeliveryStatus.ALL:
        typer.echo(f"Error: status must be one of {', '.join(DeliveryStatus.ALL)}", err=True)
        raise typer.Exit(code=1)
    store = _get_storage()
    rows = DeliveryTracker(store).list(
        status=status, endpoint_id=endpoint_id, limit=limit
    )
    if not rows:
        typer.echo("No deliveries found.")
        return
    for item in rows:
        ts = (item.get("created_at") or "")[:19]
        status_str = item.get("status", "?")
        typer.echo(
            f"{ts} {status_str:10s} {item.get('endpoint_id',''):20s} "
            f"{item.get('delivery_id','')[:12]}  {item.get('target_url','')}"
        )


def delivery_status(delivery_id: str) -> None:
    """Show one delivery record (including current status).

    Usage: hookrelay delivery status <delivery_id>
    """
    from hookrelay.delivery import RetryQueue

    store = _get_storage()
    item = RetryQueue(store).get(delivery_id)
    if item is None:
        typer.echo(f"Delivery {delivery_id} not found.", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(item, indent=2, default=str))


def dlq_list(endpoint_id: str | None = None, limit: int = 20) -> None:
    """Show dead-letter queue entries.

    Usage: hookrelay dlq list [--endpoint-id ID] [--limit N]
    """
    from hookrelay.delivery import DeadLetterQueue

    store = _get_storage()
    entries = DeadLetterQueue(store).list_entries(limit=limit, endpoint_id=endpoint_id)
    if not entries:
        typer.echo("No dead-letter entries.")
        return
    for entry in entries:
        ts = (entry.get("dead_lettered_at") or "")[:19]
        typer.echo(
            f"{ts} {entry.get('endpoint_id',''):20s} "
            f"{entry.get('delivery_id','')[:12]}  {entry.get('reason','')}"
        )


def dlq_requeue(entry_id: str) -> None:
    """Move a dead-letter entry back to the pending delivery queue.

    Usage: hookrelay dlq requeue <entry_id>
    """
    from hookrelay.delivery import DeadLetterQueue

    store = _get_storage()
    try:
        delivery_id = DeadLetterQueue(store).requeue(entry_id)
    except KeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Requeued {entry_id}: delivery {delivery_id} is pending again.")


delivery_app = typer.Typer(
    name="delivery",
    help="Inspect and manage outbound deliveries.",
    no_args_is_help=True,
)
app.add_typer(delivery_app, name="delivery")


@delivery_app.command("list")
def _delivery_list_cmd(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by delivery status"),
    endpoint_id: str | None = typer.Option(None, "--endpoint-id", "-e", help="Filter by endpoint"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    delivery_list(status=status, endpoint_id=endpoint_id, limit=limit)


@delivery_app.command("status")
def _delivery_status_cmd(
    delivery_id: str = typer.Argument(..., help="Delivery ID"),
):
    delivery_status(delivery_id=delivery_id)


dlq_app = typer.Typer(
    name="dlq",
    help="Inspect and requeue dead-letter entries.",
    no_args_is_help=True,
)
app.add_typer(dlq_app, name="dlq")


@dlq_app.command("list")
def _dlq_list_cmd(
    endpoint_id: str | None = typer.Option(None, "--endpoint-id", "-e", help="Filter by endpoint"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    dlq_list(endpoint_id=endpoint_id, limit=limit)


@dlq_app.command("requeue")
def _dlq_requeue_cmd(
    entry_id: str = typer.Argument(..., help="DLQ entry ID"),
):
    dlq_requeue(entry_id=entry_id)


# ============================================================
# Serve command
# ============================================================


def serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    db_path: str | None = None,
) -> None:
    """Start the Hookrelay HTTP server.

    Args:
        host: Host to bind to (default: 0.0.0.0).
        port: Port to listen on (default: 8000).
        reload: Enable auto-reload on file changes.
        db_path: Optional path to SQLite database.
    """
    from hookrelay import server as _server

    _server.start_server(host=host, port=port, reload=reload, db_path=db_path)


@app.command("serve")
def _serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
    db_path: str | None = typer.Option(None, "--db-path", help="Path to SQLite database"),
):
    serve(host=host, port=port, reload=reload, db_path=db_path)
    import uvicorn
    uvicorn.run(
        "hookrelay.server:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
