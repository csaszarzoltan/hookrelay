"""Pre-development tests for server & dashboard foundation (Group A + I).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import server
from hookrelay.dashboard import connection_manager

# ============================================================
# Interface tests — server module
# ============================================================

class TestServerInterface:
    """Verify server module symbols exist with correct signatures."""

    def test_create_app_exists(self):
        assert hasattr(server, "create_app")
        assert callable(server.create_app)

    def test_create_app_signature(self):
        sig = inspect.signature(server.create_app)
        # No required parameters
        params = sig.parameters
        assert len(params) == 0

    def test_start_server_exists(self):
        assert hasattr(server, "start_server")
        assert callable(server.start_server)

    def test_start_server_signature(self):
        sig = inspect.signature(server.start_server)
        params = sig.parameters
        assert "host" in params
        assert params["host"].default == "0.0.0.0"
        assert "port" in params
        assert params["port"].default == 8000
        assert "reload" in params
        assert params["reload"].default is False
        assert "db_path" in params
        assert params["db_path"].default is None


# ============================================================
# Interface tests — ConnectionManager (dashboard WebSocket)
# ============================================================

class TestConnectionManagerInterface:
    """Verify ConnectionManager class and methods exist."""

    def test_connection_manager_class_exists(self):
        assert hasattr(connection_manager, "ConnectionManager")
        assert inspect.isclass(connection_manager.ConnectionManager)

    def test_connection_manager_init_signature(self):
        sig = inspect.signature(connection_manager.ConnectionManager.__init__)
        # No required args beyond self
        assert "self" in sig.parameters

    def test_connect_exists(self):
        assert hasattr(connection_manager.ConnectionManager, "connect")
        assert callable(connection_manager.ConnectionManager.connect)

    async def test_connect_signature(self):
        sig = inspect.signature(connection_manager.ConnectionManager.connect)
        assert "websocket" in sig.parameters

    def test_disconnect_exists(self):
        assert hasattr(connection_manager.ConnectionManager, "disconnect")
        assert callable(connection_manager.ConnectionManager.disconnect)

    def test_broadcast_exists(self):
        assert hasattr(connection_manager.ConnectionManager, "broadcast")
        assert callable(connection_manager.ConnectionManager.broadcast)

    def test_broadcast_signature(self):
        sig = inspect.signature(connection_manager.ConnectionManager.broadcast)
        assert "message" in sig.parameters

    def test_active_connections_property_exists(self):
        assert hasattr(connection_manager.ConnectionManager, "active_connections")
        # It should be a property
        assert isinstance(
            inspect.getattr_static(connection_manager.ConnectionManager, "active_connections"),
            property,
        )


# ============================================================
# Behavioral tests — create_app
# ============================================================

class TestServerCreateAppBehavioral:
    """Call create_app with expected behavior."""

    def test_behavior_create_app_returns_fastapi_app(self):
        """create_app() should return a FastAPI application instance."""
        app = server.create_app()
        # Should have FastAPI attributes like router, routes, etc.
        assert app is not None
        from fastapi import FastAPI
        assert isinstance(app, FastAPI)
        # Should have a health endpoint registered
        routes = [r.path for r in app.routes]
        assert "/health" in routes

    def test_behavior_create_app_has_webhook_endpoint(self):
        """Server should mount /webhook/{channel} endpoint."""
        app = server.create_app()
        routes = [r.path for r in app.routes]
        assert any("webhook" in path for path in routes)

    def test_behavior_create_app_has_dashboard_routes(self):
        """Server should mount dashboard routes."""
        app = server.create_app()
        routes = [r.path for r in app.routes]
        assert any("dashboard" in path for path in routes)

    def test_behavior_create_app_has_websocket_endpoint(self):
        """Server should have /ws/{channel} WebSocket endpoint."""
        app = server.create_app()
        routes = [r.path for r in app.routes]
        assert any("ws" in path for path in routes)


# ============================================================
# Behavioral tests — start_server
# ============================================================

class TestServerStartBehavioral:
    """Call start_server with expected behavior."""

    def test_behavior_start_server_defaults(self):
        """start_server() should boot the server."""
        server.start_server()
        # If it reaches here without raising, the test passes

    def test_behavior_start_server_with_custom_port(self):
        """start_server(port=9000) should boot on specified port."""
        server.start_server(host="127.0.0.1", port=9000)

    def test_behavior_start_server_with_reload(self):
        """start_server(reload=True) should enable auto-reload."""
        server.start_server(host="127.0.0.1", port=9001, reload=True)

    def test_behavior_start_server_with_db_path(self):
        """start_server(db_path='/tmp/test.db') should use custom DB."""
        server.start_server(
            host="127.0.0.1",
            port=9002,
            db_path="/tmp/test_hookrelay.db",
        )


# ============================================================
# Behavioral tests — ConnectionManager
# ============================================================

class TestConnectionManagerBehavioral:
    """Call ConnectionManager methods with expected behavior."""

    def test_behavior_init_creates_instance(self):
        """ConnectionManager() should create an instance."""
        mgr = connection_manager.ConnectionManager()
        assert mgr is not None
        assert isinstance(mgr, connection_manager.ConnectionManager)

    @pytest.mark.asyncio
    async def test_behavior_connect_and_disconnect(self):
        """connect() and disconnect() should manage WebSocket lifecycle."""
        mgr = connection_manager.ConnectionManager()
        # Create a mock WebSocket
        from unittest.mock import AsyncMock
        mock_ws = AsyncMock()

        await mgr.connect(mock_ws)
        assert mgr.active_connections == 1

        await mgr.disconnect(mock_ws)
        assert mgr.active_connections == 0

    @pytest.mark.asyncio
    async def test_behavior_broadcast_sends_to_all(self):
        """broadcast() should send to all connected clients."""
        mgr = connection_manager.ConnectionManager()
        from unittest.mock import AsyncMock
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        await mgr.connect(mock_ws1)
        await mgr.connect(mock_ws2)

        await mgr.broadcast({"type": "test", "data": "hello"})

        mock_ws1.send_text.assert_called_once()
        mock_ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_behavior_broadcast_with_no_clients(self):
        """broadcast() with no clients should not raise."""
        mgr = connection_manager.ConnectionManager()
        await mgr.broadcast({"type": "test", "data": "hello"})
        # Should not raise

    def test_behavior_active_connections_property(self):
        """active_connections should return correct count."""
        mgr = connection_manager.ConnectionManager()
        assert mgr.active_connections == 0


# ============================================================
# Behavioral tests — CLI serve command (Group I)
# ============================================================

class TestCLIServeCommandBehavioral:
    """CLI serve command should wrap server.start_server()."""

    def test_behavior_cli_has_serve_function(self):
        """cli module should have a serve() function."""
        from hookrelay import cli
        assert hasattr(cli, "serve")
        assert callable(cli.serve)

    def test_behavior_cli_serve_signature(self):
        """serve() should accept host, port, reload, db-path params."""
        from hookrelay import cli
        sig = inspect.signature(cli.serve)
        params = sig.parameters
        assert "host" in params
        assert "port" in params
        assert "reload" in params

    def test_behavior_cli_serve_defaults(self):
        """serve() should use default host=0.0.0.0, port=8000."""
        from hookrelay import cli
        sig = inspect.signature(cli.serve)
        assert sig.parameters["host"].default == "0.0.0.0"
        assert sig.parameters["port"].default == 8000
        assert sig.parameters["reload"].default is False

    def test_behavior_cli_serve_calls_start_server(self):
        """serve() should internally call server.start_server()."""
        from unittest.mock import patch

        from hookrelay import cli
        with patch("hookrelay.server.start_server") as mock_start:
            cli.serve(host="127.0.0.1", port=9999, reload=True)
            mock_start.assert_called_once_with(
                host="127.0.0.1", port=9999, reload=True, db_path=None
            )

    def test_behavior_cli_serve_with_db_path(self):
        """serve() should pass db_path to start_server()."""
        from unittest.mock import patch

        from hookrelay import cli
        with patch("hookrelay.server.start_server") as mock_start:
            cli.serve(host="0.0.0.0", port=8000, reload=False, db_path="/tmp/custom.db")
            mock_start.assert_called_once_with(
                host="0.0.0.0", port=8000, reload=False, db_path="/tmp/custom.db"
            )
