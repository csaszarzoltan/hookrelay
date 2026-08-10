"""Multi-destination routing models and router.

A *Destination* is a forwarding target attached to a capture bin or relay rule.
A *MultiDestinationRouter* fans a single inbound webhook out to zero or more
destinations according to a delivery mode (broadcast / round-robin / weighted)
and tracks per-destination delivery statistics consumed by the Insights API.
"""

from __future__ import annotations

import random
import threading
from enum import Enum
from typing import Any


class DeliveryMode(str, Enum):
    """How a single inbound webhook is fanned out to multiple destinations."""

    BROADCAST = "broadcast"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"


class Destination:
    """A forwarding target attached to a capture bin or relay rule.

    Parameters
    ----------
    destination_id : str
        Unique identifier.
    bin_id : str
        The capture bin this destination belongs to.
    url : str
        Target URL for forwarded webhooks.
    transform_id : str | None
        Optional transformation rule to apply before forwarding.
    signing_config : dict[str, Any] | None
        Outgoing signing configuration (algorithm, secret, etc.).
    headers : dict[str, str]
        Extra headers to attach to every forwarded request.
    retry_policy : dict[str, Any]
        Per-destination retry configuration.
    enabled : bool
        Whether this destination is active.
    weight : int
        Weight for weighted delivery mode (default 1).
    delivery_mode : str
        Default delivery mode for this destination when part of a multi-dest bin
        (broadcast / round_robin / weighted).  Only used when the bin's router
        has no explicit mode override.
    """

    def __init__(
        self,
        destination_id: str,
        bin_id: str,
        url: str,
        *,
        transform_id: str | None = None,
        signing_config: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_policy: dict[str, Any] | None = None,
        enabled: bool = True,
        weight: int = 1,
        delivery_mode: str = "broadcast",
    ) -> None:
        if not destination_id:
            raise ValueError("destination_id must not be empty")
        if not bin_id:
            raise ValueError("bin_id must not be empty")
        if not url:
            raise ValueError("url must not be empty")
        if weight < 1:
            raise ValueError("weight must be >= 1")
        if delivery_mode not in ("broadcast", "round_robin", "weighted"):
            raise ValueError(f"invalid delivery_mode: {delivery_mode}")

        self.destination_id = destination_id
        self.bin_id = bin_id
        self.url = url
        self.transform_id = transform_id
        self.signing_config = dict(signing_config) if signing_config else None
        self.headers = dict(headers) if headers else {}
        self.retry_policy = dict(retry_policy) if retry_policy else None
        self.enabled = enabled
        self.weight = weight
        self.delivery_mode = delivery_mode
        self._delivered = 0
        self._failed = 0
        self._lock = threading.Lock()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "destination_id": self.destination_id,
            "bin_id": self.bin_id,
            "url": self.url,
            "transform_id": self.transform_id,
            "signing_config": self.signing_config,
            "headers": self.headers,
            "retry_policy": self.retry_policy,
            "enabled": self.enabled,
            "weight": self.weight,
            "delivery_mode": self.delivery_mode,
            "delivered_count": self._delivered,
            "failed_count": self._failed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Destination:
        """Deserialize from a dict produced by :meth:`to_dict`."""
        dest = cls(
            destination_id=data["destination_id"],
            bin_id=data["bin_id"],
            url=data["url"],
            transform_id=data.get("transform_id"),
            signing_config=data.get("signing_config"),
            headers=data.get("headers"),
            retry_policy=data.get("retry_policy"),
            enabled=data.get("enabled", True),
            weight=data.get("weight", 1),
            delivery_mode=data.get("delivery_mode", "broadcast"),
        )
        dest._delivered = int(data.get("delivered_count", 0))
        dest._failed = int(data.get("failed_count", 0))
        return dest

    def record_delivered(self) -> None:
        """Increment the delivered counter (thread-safe)."""
        with self._lock:
            self._delivered += 1

    def record_failed(self) -> None:
        """Increment the failed counter (thread-safe)."""
        with self._lock:
            self._failed += 1


class MultiDestinationRouter:
    """Route a single inbound webhook to multiple destinations.

    Parameters
    ----------
    destinations : list[Destination]
        Forwarding targets.
    mode : DeliveryMode
        Broadcast, round-robin, or weighted.
    """

    def __init__(
        self,
        destinations: list[Destination],
        mode: DeliveryMode = DeliveryMode.BROADCAST,
    ) -> None:
        self._destinations = [d for d in destinations if d.enabled]
        self._mode = mode
        self._rr_index = 0
        self._rr_lock = threading.Lock()

    def route(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a list of per-destination delivery instructions.

        Each item is a dict with at least ``destination_id`` and ``url``.  In
        broadcast mode all enabled destinations are returned; in round-robin
        and weighted modes exactly one destination is returned.

        Args:
            payload: The inbound payload (unused by the router itself, passed
                through for downstream consumers).

        Returns:
            List of delivery instruction dicts.
        """
        if not self._destinations:
            return []

        if self._mode == DeliveryMode.BROADCAST:
            return [
                {"destination_id": d.destination_id, "url": d.url} for d in self._destinations
            ]

        dest = self.next_destination()
        if dest is None:
            return []
        return [{"destination_id": dest.destination_id, "url": dest.url}]

    def next_destination(self) -> Destination | None:
        """Return the next destination for round-robin/weighted mode.

        In weighted mode the choice is a random draw proportional to
        ``Destination.weight``.  The caller is responsible for recording
        success/failure via :meth:`Destination.record_delivered` or
        :meth:`Destination.record_failed`.

        Returns:
            The selected :class:`Destination`, or ``None`` if none enabled.
        """
        if not self._destinations:
            return None

        if self._mode == DeliveryMode.ROUND_ROBIN:
            with self._rr_lock:
                dest = self._destinations[self._rr_index % len(self._destinations)]
                self._rr_index += 1
                return dest

        if self._mode == DeliveryMode.WEIGHTED:
            total = sum(d.weight for d in self._destinations)
            r = random.random() * total
            acc = 0.0
            for d in self._destinations:
                acc += d.weight
                if r <= acc:
                    return d
            return self._destinations[-1]

        return None

    def get_delivery_stats(self) -> dict[str, Any]:
        """Return per-destination delivery counts and success rates.

        Returns:
            Dict mapping ``destination_id`` to ``{"delivered": int, "failed": int}``.
        """
        stats: dict[str, Any] = {}
        for d in self._destinations:
            stats[d.destination_id] = {
                "delivered": d._delivered,
                "failed": d._failed,
            }
        return stats