"""CLI commands for webhook capture bins (v1.6.0).

Exposes ``hookrelay bin create|list|inspect <bin_id>|forward <request_id> --to <url>``.
``bin forward`` takes the **captured request id** (same convention as
``hookrelay replay <request_id>``); ``bin inspect`` prints request ids so a
user can copy one into ``bin forward``.
"""

from __future__ import annotations

import os
import tempfile

import typer

from hookrelay import _storage
from hookrelay.bins.forward import forward_captured_request
from hookrelay.bins.service import BinService
from hookrelay.storage import Storage


def _get_storage() -> Storage:
    """Get or create the default storage (mirrors ``hookrelay.cli``)."""
    store = _storage.get()
    if store is None:
        db_dir = os.path.join(tempfile.gettempdir(), "hookrelay")
        os.makedirs(db_dir, exist_ok=True)
        store = Storage(os.path.join(db_dir, "webhooks.db"))
        _storage.set(store)
    return store


def bin_create(description: str | None = None) -> None:
    """Create a new capture bin and print its public URL."""
    created = BinService(_get_storage()).create_bin(description)
    typer.echo(f"Bin created: {created.url}")
    typer.echo(f"Bin ID: {created.bin_id}")


def bin_list() -> None:
    """List all capture bins."""
    bins = BinService(_get_storage()).list_bins()
    if not bins:
        typer.echo("No bins found.")
        return
    for b in bins:
        description = f"  ({b.description})" if b.description else ""
        typer.echo(f"{b.bin_id}  {b.created_at}  {b.url}{description}")


def bin_inspect(bin_id: str) -> None:
    """Show bin details and its captured requests."""
    store = _get_storage()
    service = BinService(store)
    bin_obj = service.get_bin(bin_id)
    listing = service.list_requests(bin_id)
    if bin_obj is None and not listing["items"]:
        typer.echo(f"Error: Bin {bin_id} not found.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Bin: {bin_id}")
    if bin_obj is not None:
        typer.echo(f"URL: {bin_obj.url}")
        if bin_obj.description:
            typer.echo(f"Description: {bin_obj.description}")
    typer.echo(f"Requests: {listing['total']}")
    for item in listing["items"]:
        typer.echo(
            f"  {item.get('received_at', '')}  {item.get('method', ''):7s} "
            f"{item.get('request_id', '')}"
        )


def bin_forward(request_id: str, to: str) -> None:
    """Forward a captured request to a target URL and print the result."""
    store = _get_storage()
    request = store.get_request(request_id)
    if request is None:
        typer.echo(f"Error: Request {request_id} not found.", err=True)
        raise typer.Exit(code=1)
    bin_id = request.get("channel", "")
    try:
        result = forward_captured_request(bin_id, request_id, to, storage=store)
    except ValueError as exc:
        # The SSRF guard and invalid-target errors surface as ValueError
        # (SSRFError exists but is never raised by the forward path).
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Forwarded {result.request_id} -> {result.target_url}")
    typer.echo(f"  Status: {result.status_code}  Latency: {result.latency_ms:.1f} ms")
    if result.error:
        typer.echo(f"  Error: {result.error}")
    if result.response_body:
        typer.echo(f"  Body: {result.response_body[:500]}")


def register_bin_group(app: typer.Typer) -> None:
    """Register the ``bin`` command group on the main hookrelay CLI app."""
    bin_app = typer.Typer(
        name="bin",
        help="Manage webhook capture bins.",
        no_args_is_help=True,
    )

    @bin_app.command("create")
    def _create_cmd(
        description: str | None = typer.Option(
            None, "--description", "-d", help="Optional bin description"
        ),
    ) -> None:
        bin_create(description)

    @bin_app.command("list")
    def _list_cmd() -> None:
        bin_list()

    @bin_app.command("inspect")
    def _inspect_cmd(
        bin_id: str = typer.Argument(..., help="Bin ID to inspect"),
    ) -> None:
        bin_inspect(bin_id)

    @bin_app.command("forward")
    def _forward_cmd(
        request_id: str = typer.Argument(..., help="Captured request ID"),
        to: str = typer.Option(..., "--to", help="Target URL to forward to"),
    ) -> None:
        bin_forward(request_id, to)

    app.add_typer(bin_app, name="bin")
