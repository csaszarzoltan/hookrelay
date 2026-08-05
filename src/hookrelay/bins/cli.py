"""CLI commands for webhook capture bins (v1.6.0).

Pre-development stub: raises ``NotImplementedError`` until implemented.

Contract notes for the developer:

- Wire the ``bin`` group into the main CLI by calling
  ``register_bin_group(hookrelay.cli.app)`` from :func:`hookrelay.cli.get_app`
  (or equivalent). Expected surface:

  * ``hookrelay bin create [--description TEXT]``   → prints public bin URL
  * ``hookrelay bin list``                          → prints all bins
  * ``hookrelay bin inspect <bin_id>``              → bin details + requests
  * ``hookrelay bin forward <request_id> --to <url>`` → forwards one captured
    request to the target URL (SSRF-guarded) and prints status/latency/body

- ``bin_forward`` takes the **captured request id** (same convention as the
  existing ``hookrelay replay <request_id>`` command); ``bin inspect`` prints
  request ids so users can copy one into ``bin forward``.
"""

from __future__ import annotations

import typer


def bin_create(description: str | None = None) -> None:
    """Create a new capture bin and print its public URL."""
    raise NotImplementedError("bin_create is not implemented yet")


def bin_list() -> None:
    """List all capture bins."""
    raise NotImplementedError("bin_list is not implemented yet")


def bin_inspect(bin_id: str) -> None:
    """Show bin details and its captured requests."""
    raise NotImplementedError("bin_inspect is not implemented yet")


def bin_forward(request_id: str, to: str) -> None:
    """Forward a captured request to a target URL and print the result."""
    raise NotImplementedError("bin_forward is not implemented yet")


def register_bin_group(app: typer.Typer) -> None:
    """Register the ``bin`` command group on the main hookrelay CLI app."""
    raise NotImplementedError("register_bin_group is not implemented yet")
