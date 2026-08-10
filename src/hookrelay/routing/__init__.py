"""Multi-destination routing and forwarding rules.

Re-exports the original ``RouterEngine`` and ``RoutingRule`` from
:mod:`hookrelay.routing.rules`, and exposes the new ``Destination``,
``DeliveryMode``, and ``MultiDestinationRouter`` from
:mod:`hookrelay.routing.destination`.
"""

from __future__ import annotations

from hookrelay.routing.destination import (
    DeliveryMode,
    Destination,
    MultiDestinationRouter,
)
from hookrelay.routing.destination_store import DestinationStore
from hookrelay.routing.rules import RouterEngine, RoutingRule

__all__ = [
    "DeliveryMode",
    "Destination",
    "DestinationStore",
    "MultiDestinationRouter",
    "RouterEngine",
    "RoutingRule",
]