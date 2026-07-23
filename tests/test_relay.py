"""Pre-development tests for relay tunnel (WebSocket relay manager + client).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest
import requests
import websocket

from hookrelay import client, relay

# ============================================================
# Interface tests — RelayManager (server-side)
# ============================================================

class TestRelayManagerInterface:
    """Verify RelayManager class and methods exist."""

    def test_relay_manager_class_exists(self):
        assert hasattr(relay, "RelayManager")

    def test_relay_manager_is_class(self):
        assert inspect.isclass(relay.RelayManager)

    def test_relay_manager_init_signature(self):
        sig = inspect.signature(relay.RelayManager.__init__)
        # __init__ should accept self only (no required args)
        assert "self" in sig.parameters

    def test_relay_manager_register_client_exists(self):
        assert hasattr(relay.RelayManager, "register_client")
        assert callable(relay.RelayManager.register_client)
        sig = inspect.signature(relay.RelayManager.register_client)
        assert "channel" in sig.parameters
        assert "websocket" in sig.parameters

    def test_relay_manager_unregister_client_exists(self):
        assert hasattr(relay.RelayManager, "unregister_client")
        assert callable(relay.RelayManager.unregister_client)
        sig = inspect.signature(relay.RelayManager.unregister_client)
        assert "channel" in sig.parameters
        assert "websocket" in sig.parameters

    def test_relay_manager_broadcast_exists(self):
        assert hasattr(relay.RelayManager, "broadcast")
        assert callable(relay.RelayManager.broadcast)
        sig = inspect.signature(relay.RelayManager.broadcast)
        assert "channel" in sig.parameters
        assert "message" in sig.parameters

    def test_relay_manager_get_connected_clients_exists(self):
        assert hasattr(relay.RelayManager, "get_connected_clients")
        assert callable(relay.RelayManager.get_connected_clients)
        sig = inspect.signature(relay.RelayManager.get_connected_clients)
        assert "channel" in sig.parameters

    def test_relay_manager_has_connected_clients_exists(self):
        assert hasattr(relay.RelayManager, "has_connected_clients")
        assert callable(relay.RelayManager.has_connected_clients)

    def test_relay_manager_send_heartbeat_exists(self):
        assert hasattr(relay.RelayManager, "send_heartbeat")
        assert callable(relay.RelayManager.send_heartbeat)

    def test_relay_manager_forward_replay_exists(self):
        assert hasattr(relay.RelayManager, "forward_replay")
        assert callable(relay.RelayManager.forward_replay)


# ============================================================
# Interface tests — WebSocketClient
# ============================================================

class TestWebSocketClientInterface:
    """Verify WebSocketClient class and methods exist."""

    def test_websocket_client_class_exists(self):
        assert hasattr(client, "WebSocketClient")
        assert inspect.isclass(client.WebSocketClient)

    def test_ws_client_init_signature(self):
        sig = inspect.signature(client.WebSocketClient.__init__)
        assert "server_url" in sig.parameters
        assert "channel" in sig.parameters
        assert "target_url" in sig.parameters

    def test_ws_client_connect_exists(self):
        assert hasattr(client.WebSocketClient, "connect")
        assert callable(client.WebSocketClient.connect)

    def test_ws_client_disconnect_exists(self):
        assert hasattr(client.WebSocketClient, "disconnect")
        assert callable(client.WebSocketClient.disconnect)

    def test_ws_client_forward_to_local_exists(self):
        assert hasattr(client.WebSocketClient, "forward_to_local")
        assert callable(client.WebSocketClient.forward_to_local)
        sig = inspect.signature(client.WebSocketClient.forward_to_local)
        assert "request_data" in sig.parameters
        assert "timeout" in sig.parameters

    def test_ws_client_is_connected_exists(self):
        assert hasattr(client.WebSocketClient, "is_connected")
        assert callable(client.WebSocketClient.is_connected)

    def test_connect_and_forward_function_exists(self):
        assert hasattr(client, "connect_and_forward")
        assert callable(client.connect_and_forward)
        sig = inspect.signature(client.connect_and_forward)
        assert "server_url" in sig.parameters
        assert "channel" in sig.parameters
        assert "target_url" in sig.parameters


# ============================================================
# Behavioral tests — RelayManager real behavior
# ============================================================

class TestRelayManagerBehavioral:
    """Calling RelayManager methods works correctly."""

    def test_behavior_init_returns_manager(self):
        mgr = relay.RelayManager()
        assert mgr is not None
        assert isinstance(mgr, relay.RelayManager)

    @pytest.fixture
    def manager_instance(self):
        return relay.RelayManager()

    def test_behavior_register_client_adds_client(self, manager_instance):
        manager_instance.register_client(channel="test", websocket="ws1")
        assert manager_instance.get_connected_clients("test") == 1
        assert manager_instance.has_connected_clients("test") is True

    def test_behavior_unregister_client_removes_client(self, manager_instance):
        manager_instance.register_client(channel="test", websocket="ws1")
        manager_instance.unregister_client(channel="test", websocket="ws1")
        assert manager_instance.get_connected_clients("test") == 0

    def test_behavior_broadcast_returns_count(self, manager_instance):
        class FakeWS:
            def send(self, msg):
                pass
        manager_instance.register_client(channel="test", websocket=FakeWS())
        count = manager_instance.broadcast(channel="test", message={"key": "val"})
        assert count == 1

    def test_behavior_get_connected_returns_zero_for_unknown(self, manager_instance):
        assert manager_instance.get_connected_clients("unknown") == 0

    def test_behavior_has_connected_returns_false_for_unknown(self, manager_instance):
        assert manager_instance.has_connected_clients("unknown") is False

    def test_behavior_heartbeat_does_not_raise(self, manager_instance):
        # No clients connected so broadcast returns 0, should not raise
        manager_instance.send_heartbeat(channel="test")

    def test_behavior_forward_replay_returns_false_with_no_clients(self, manager_instance):
        result = manager_instance.forward_replay(
            channel="test", request_data={"id": "abc"}
        )
        assert result is False


# ============================================================
# Behavioral tests — WebSocketClient real behavior
# ============================================================

class TestWebSocketClientBehavioral:
    """Calling WebSocketClient methods with invalid server raises."""

    def test_behavior_init_creates_instance(self):
        client_inst = client.WebSocketClient(
            server_url="ws://localhost:8000/ws/test",
            channel="test",
            target_url="http://localhost:3000/webhook",
        )
        assert client_inst is not None
        assert client_inst.server_url == "ws://localhost:8000/ws/test"

    def test_behavior_connect_to_nonexistent_server_raises(self):
        client_inst = client.WebSocketClient(
            server_url="ws://nonexistent.invalid:9999/ws/test",
            channel="test",
            target_url="http://localhost:3000/webhook",
        )
        with pytest.raises((ConnectionError, OSError, ValueError, websocket.WebSocketException)):
            client_inst.connect()

    def test_behavior_disconnect_does_not_raise_when_not_connected(self):
        client_inst = client.WebSocketClient(
            server_url="ws://localhost:8000/ws/test",
            channel="test",
            target_url="http://localhost:3000/webhook",
        )
        # Disconnecting when not connected should not raise
        client_inst.disconnect()

    def test_behavior_is_connected_returns_false_when_not_connected(self):
        client_inst = client.WebSocketClient(
            server_url="ws://localhost:8000/ws/test",
            channel="test",
            target_url="http://localhost:3000/webhook",
        )
        assert client_inst.is_connected() is False

    def test_behavior_forward_to_local_invalid_url_raises(self):
        client_inst = client.WebSocketClient(
            server_url="ws://localhost:8000/ws/test",
            channel="test",
            target_url="http://nonexistent.invalid:9999/webhook",
        )
        with pytest.raises((ConnectionError, OSError, ValueError, requests.exceptions.ConnectionError)):
            client_inst.forward_to_local(
                request_data={"method": "POST"}, timeout=5.0
            )
