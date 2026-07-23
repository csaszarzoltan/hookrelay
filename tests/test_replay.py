"""Pre-development tests for request replay module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import replay

# ============================================================
# Interface tests — imports, classes, signatures
# ============================================================

class TestReplayInterface:
    """Verify replay module symbols exist."""

    def test_replay_request_exists(self):
        assert hasattr(replay, "replay_request")
        assert callable(replay.replay_request)

    def test_replay_request_signature(self):
        sig = inspect.signature(replay.replay_request)
        params = sig.parameters
        assert "request_id" in params
        assert "channel" in params
        assert "storage" in params
        assert "relay_manager" in params
        assert "target_url" in params
        assert params["target_url"].default is None

    def test_get_replay_status_exists(self):
        assert hasattr(replay, "get_replay_status")
        assert callable(replay.get_replay_status)

    def test_get_replay_status_signature(self):
        sig = inspect.signature(replay.get_replay_status)
        assert "request_id" in sig.parameters
        assert "storage" in sig.parameters

    def test_replay_error_class_exists(self):
        assert hasattr(replay, "ReplayError")
        assert inspect.isclass(replay.ReplayError)
        assert issubclass(replay.ReplayError, Exception)

    def test_request_not_found_error_class_exists(self):
        assert hasattr(replay, "RequestNotFoundError")
        assert inspect.isclass(replay.RequestNotFoundError)
        assert issubclass(replay.RequestNotFoundError, replay.ReplayError)

    def test_no_connected_client_error_class_exists(self):
        assert hasattr(replay, "NoConnectedClientError")
        assert inspect.isclass(replay.NoConnectedClientError)
        assert issubclass(replay.NoConnectedClientError, replay.ReplayError)


# ============================================================
# Behavioral tests — real exceptions and behavior
# ============================================================

class TestReplayBehavioral:
    """Calling replay functions returns expected results or raises."""

    def test_behavior_replay_request_raises_not_found(self):
        """replay_request with a missing ID should raise RequestNotFoundError."""
        from hookrelay.relay import RelayManager

        class FakeStorage:
            def get_request(self, request_id):
                return None

        with pytest.raises(replay.RequestNotFoundError):
            replay.replay_request(
                request_id="req-123",
                channel="test",
                storage=FakeStorage(),
                relay_manager=RelayManager(),
            )

    def test_behavior_replay_request_with_target_raises_not_found(self):
        from hookrelay.relay import RelayManager

        class FakeStorage:
            def get_request(self, request_id):
                return None

        with pytest.raises(replay.RequestNotFoundError):
            replay.replay_request(
                request_id="req-456",
                channel="demo",
                storage=FakeStorage(),
                relay_manager=RelayManager(),
                target_url="http://localhost:4000/hook",
            )

    def test_behavior_replay_request_no_clients_raises(self):
        """replay_request with no connected clients should raise NoConnectedClientError."""
        from hookrelay.relay import RelayManager

        class FakeStorage:
            def get_request(self, request_id):
                return {"request_id": request_id, "method": "POST", "channel": "demo"}

            def increment_replay_count(self, request_id):
                pass

        with pytest.raises(replay.NoConnectedClientError):
            replay.replay_request(
                request_id="req-789",
                channel="demo",
                storage=FakeStorage(),
                relay_manager=RelayManager(),
            )

    def test_behavior_get_replay_status_raises_not_found(self):
        class FakeStorage:
            def get_request(self, request_id):
                return None

        with pytest.raises(replay.RequestNotFoundError):
            replay.get_replay_status(
                request_id="req-789", storage=FakeStorage()
            )

    def test_behavior_replay_error_can_be_raised(self):
        """ReplayError is a real exception class, not a stub."""
        with pytest.raises(replay.ReplayError):
            raise replay.ReplayError("test error")

    def test_behavior_request_not_found_error_can_be_raised(self):
        """RequestNotFoundError is a real exception class."""
        with pytest.raises(replay.RequestNotFoundError):
            raise replay.RequestNotFoundError("not found")

    def test_behavior_no_connected_client_error_can_be_raised(self):
        """NoConnectedClientError is a real exception class."""
        with pytest.raises(replay.NoConnectedClientError):
            raise replay.NoConnectedClientError("no client")
