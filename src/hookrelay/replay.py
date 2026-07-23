"""Request replay orchestration."""

from __future__ import annotations

from typing import Any


class ReplayError(Exception):
    """Base replay error."""


class RequestNotFoundError(ReplayError):
    """Request ID not found in storage."""


class NoConnectedClientError(ReplayError):
    """No client connected to handle replay."""


def replay_request(
    request_id: str,
    channel: str,
    storage: Any,
    relay_manager: Any,
    target_url: str | None = None,
) -> dict[str, Any]:
    """Replay a stored request by ID.

    Retrieves the request from storage, forwards it via the relay
    manager, and returns the replay result.

    Raises RequestNotFoundError if the request_id doesn't exist.
    Raises NoConnectedClientError if no client is connected.
    """
    request = storage.get_request(request_id)
    if request is None:
        raise RequestNotFoundError(f"Request {request_id} not found")

    if not relay_manager.has_connected_clients(channel):
        raise NoConnectedClientError(
            f"No clients connected on channel '{channel}'"
        )

    # Forward the replay
    forwarded = relay_manager.forward_replay(channel, request)
    if not forwarded:
        raise NoConnectedClientError("Failed to forward replay to any client")

    # Increment replay count
    storage.increment_replay_count(request_id)

    return {
        "request_id": request_id,
        "channel": channel,
        "replayed": True,
        "target_url": target_url,
    }


def get_replay_status(request_id: str, storage: Any) -> int:
    """Get the number of times a request has been replayed."""
    request = storage.get_request(request_id)
    if request is None:
        raise RequestNotFoundError(f"Request {request_id} not found")
    return request.get("replayed", 0)
