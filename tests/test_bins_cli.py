"""Pre-development CLI tests for Webhook Capture Bins (v1.6.0).

Covers ``hookrelay bin create|list|inspect <id>|forward <id> --to <url>``:

- Interface tests (``hookrelay.bins.cli`` exports + signatures): pass
  immediately against the stubs.
- Behavioral tests (Typer ``CliRunner`` against the real CLI app): RED until
  the developer wires the ``bin`` group into ``hookrelay.cli``, then green.

Contract note: ``bin forward`` takes the **captured request id** (same
convention as the existing ``hookrelay replay <request_id>`` command); the id
is printed by ``bin inspect`` so users can copy it.
"""

from __future__ import annotations

import inspect

import pytest
from typer.testing import CliRunner

from hookrelay import _storage
from hookrelay.bins import cli as bins_cli
from hookrelay.cli import app as cli_app
from hookrelay.storage import Storage

runner = CliRunner()


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path):
    store = Storage(str(tmp_path / "bins_cli.db"))
    _storage.set(store)
    return store


# ============================================================
# Interface tests — bins CLI module
# ============================================================


class TestBinsCliInterface:
    def test_bin_create_exists(self):
        assert callable(bins_cli.bin_create)

    def test_bin_create_signature(self):
        sig = inspect.signature(bins_cli.bin_create)
        assert "description" in sig.parameters
        assert sig.parameters["description"].default is None

    def test_bin_list_exists(self):
        assert callable(bins_cli.bin_list)

    def test_bin_list_signature(self):
        assert inspect.signature(bins_cli.bin_list).parameters == {}

    def test_bin_inspect_exists(self):
        assert callable(bins_cli.bin_inspect)

    def test_bin_inspect_signature(self):
        sig = inspect.signature(bins_cli.bin_inspect)
        assert "bin_id" in sig.parameters

    def test_bin_forward_exists(self):
        assert callable(bins_cli.bin_forward)

    def test_bin_forward_signature(self):
        sig = inspect.signature(bins_cli.bin_forward)
        params = sig.parameters
        assert "request_id" in params
        assert "to" in params

    def test_register_bin_group_exists(self):
        assert callable(bins_cli.register_bin_group)


# ============================================================
# Behavioral — hookrelay bin <subcommand>
# ============================================================


class TestBinsCliBehavioral:
    def test_bin_group_is_registered(self):
        app = cli_app
        group_names = [g.name for g in app.registered_groups]
        command_names = [c.name for c in app.registered_commands]
        assert "bin" in group_names or "bin" in command_names

    def test_bin_create_prints_public_url(self, store):
        result = runner.invoke(cli_app, ["bin", "create"])
        assert result.exit_code == 0, result.output
        assert "/bin/" in result.output

    def test_bin_create_with_description(self, store):
        result = runner.invoke(cli_app, ["bin", "create", "--description", "my bin"])
        assert result.exit_code == 0, result.output
        assert "/bin/" in result.output

    def test_bin_list_prints_created_bins(self, store):
        created = runner.invoke(cli_app, ["bin", "create"])
        assert created.exit_code == 0, created.output
        result = runner.invoke(cli_app, ["bin", "list"])
        assert result.exit_code == 0, result.output
        assert "/bin/" in result.output

    def test_bin_inspect_prints_bin_and_requests(self, store):
        created = runner.invoke(cli_app, ["bin", "create"])
        assert created.exit_code == 0, created.output
        # seed one captured request directly in storage (bin_id = channel)
        store.store_request(
            {
                "request_id": "req-inspect-1",
                "channel": "bin-inspect-1",
                "method": "POST",
                "path": "/",
                "headers": {"Content-Type": "application/json"},
                "body": b'{"k": "v"}',
                "query_params": {},
                "source_ip": "203.0.113.5",
                "received_at": "2026-08-05T00:00:00+00:00",
            }
        )
        result = runner.invoke(cli_app, ["bin", "inspect", "bin-inspect-1"])
        assert result.exit_code == 0, result.output
        assert "bin-inspect-1" in result.output
        assert "req-inspect-1" in result.output

    def test_bin_forward_prints_result(self, store):
        store.store_request(
            {
                "request_id": "req-forward-1",
                "channel": "bin-fwd-1",
                "method": "POST",
                "path": "/",
                "headers": {},
                "body": b"{}",
                "query_params": {},
                "source_ip": "203.0.113.5",
                "received_at": "2026-08-05T00:00:00+00:00",
            }
        )
        result = runner.invoke(
            cli_app, ["bin", "forward", "req-forward-1", "--to", "https://example.com/hook"]
        )
        assert result.exit_code == 0, result.output
        assert "req-forward-1" in result.output

    def test_bin_forward_requires_to(self, store):
        result = runner.invoke(cli_app, ["bin", "forward", "req-forward-1"])
        assert result.exit_code != 0

    def test_bin_forward_ssrf_blocks_private_target(self, store):
        store.store_request(
            {
                "request_id": "req-fwd-ssrf",
                "channel": "bin-fwd-2",
                "method": "POST",
                "path": "/",
                "headers": {},
                "body": b"{}",
                "query_params": {},
                "source_ip": "203.0.113.5",
                "received_at": "2026-08-05T00:00:00+00:00",
            }
        )
        result = runner.invoke(
            cli_app, ["bin", "forward", "req-fwd-ssrf", "--to", "http://127.0.0.1:8080/x"]
        )
        assert result.exit_code != 0
