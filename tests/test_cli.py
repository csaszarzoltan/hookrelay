"""Pre-development tests for hookrelay CLI module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest
import typer

from hookrelay import cli

# ============================================================
# Interface tests — imports, signatures, types
# ============================================================

class TestCLIImports:
    """Verify all public CLI symbols exist and are callable."""

    def test_get_app_exists(self):
        assert hasattr(cli, "get_app")
        assert callable(cli.get_app)

    def test_forward_exists(self):
        assert hasattr(cli, "forward")
        assert callable(cli.forward)

    def test_history_exists(self):
        assert hasattr(cli, "history")
        assert callable(cli.history)

    def test_replay_exists(self):
        assert hasattr(cli, "replay")
        assert callable(cli.replay)

    def test_status_exists(self):
        assert hasattr(cli, "status")
        assert callable(cli.status)

    def test_listen_exists(self):
        assert hasattr(cli, "listen")
        assert callable(cli.listen)


class TestCLISignatures:
    """Verify function parameter signatures match spec."""

    def test_forward_signature(self):
        sig = inspect.signature(cli.forward)
        params = sig.parameters
        assert "channel" in params
        assert "target" in params
        assert "server" in params
        assert params["server"].default == "http://localhost:8000"

    def test_history_signature(self):
        sig = inspect.signature(cli.history)
        params = sig.parameters
        assert "channel" in params
        assert params["channel"].default is None
        assert "limit" in params
        assert params["limit"].default == 20
        assert "method" in params
        assert params["method"].default is None
        assert "path" in params
        assert params["path"].default is None
        assert "request_id" in params

    def test_replay_signature(self):
        sig = inspect.signature(cli.replay)
        params = sig.parameters
        assert "request_id" in params
        assert "target" in params
        assert params["target"].default is None
        assert "server" in params
        assert params["server"].default == "http://localhost:8000"

    def test_status_signature(self):
        sig = inspect.signature(cli.status)
        params = sig.parameters
        assert "server" in params

    def test_listen_signature(self):
        sig = inspect.signature(cli.listen)
        params = sig.parameters
        assert "channel" in params
        assert "server" in params


# ============================================================
# Behavioral tests — functions can be called and return / raise expected errors
# ============================================================

class TestCLIBehavioral:
    """Calling CLI functions returns or raises as expected."""

    def test_behavior_get_app_returns_typer_app(self):
        app = cli.get_app()
        assert app is not None
        # Typer app has a registered commands attribute
        assert hasattr(app, "registered_commands")

    def test_behavior_forward_called_with_invalid_server(self):
        """forward with an unreachable server should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.forward(channel="test", target="http://localhost:3000/hook", server="http://nonexistent.invalid:9999")

    def test_behavior_history_no_args_returns_none(self):
        """history() with no args should not raise."""
        result = cli.history()
        assert result is None

    def test_behavior_history_with_channel_returns_none(self):
        result = cli.history(channel="mychan")
        assert result is None

    def test_behavior_history_with_id_returns_none_for_missing(self):
        """history with a non-existent request_id should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.history(request_id="req-123")

    def test_behavior_replay_with_nonexistent_id(self):
        """replay with a missing ID should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.replay(request_id="req-456")

    def test_behavior_status_with_invalid_server(self):
        """status with unreachable server should raise SystemExit from urllib/typer."""
        with pytest.raises(typer.Exit):
            cli.status(server="http://nonexistent.invalid:9999")

    def test_behavior_status_rejects_non_http_scheme(self):
        """status with a file:// URL is rejected by the SSRF guard before I/O."""
        with pytest.raises(typer.Exit):
            cli.status(server="file:///etc/passwd")

    def test_behavior_status_allows_default_localhost(self, monkeypatch):
        """Default localhost server still works: SSRF guard allows private for the local CLI."""
        import types

        fake_resp = types.SimpleNamespace(
            read=lambda: b'{"status": "ok", "version": "1.2.3"}'
        )
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **k: fake_resp
        )
        # Must not raise: scheme valid and localhost allowed (allow_private).
        cli.status()

    def test_behavior_listen_with_invalid_server(self):
        """listen with unreachable server should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.listen(channel="test", server="http://nonexistent.invalid:9999")
