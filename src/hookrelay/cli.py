"""Typer CLI for hookrelay."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request

import typer

from hookrelay import _storage
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
    except Exception as e:  # noqa: BLE001
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
    try:
        resp = urllib.request.urlopen(health_url, timeout=10)
        data = json.loads(resp.read().decode())
        typer.echo(f"Server: {server}")
        typer.echo(f"Status: {data.get('status', 'unknown')}")
        typer.echo(f"Version: {data.get('version', '?')}")
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
