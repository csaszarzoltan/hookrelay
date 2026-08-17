"""Multi-destination delivery dispatcher (v1.8.0).

Wires the routing / transformation / signing engine into the real
delivery path. For every captured webhook the dispatcher:

1. loads the bin's enabled destinations and builds a
   :class:`~hookrelay.routing.destination.MultiDestinationRouter`
2. ``route()`` fans the payload out per the bin's delivery mode
   (broadcast → every enabled destination, round-robin/weighted → one)
3. applies the destination's transformation rule (if any) to the JSON
   body before sending
4. builds outgoing headers: the destination's static ``headers`` plus
   the signing headers from :class:`~hookrelay.security.outgoing.OutgoingSigner`
   (``x-hookrelay-timestamp`` / ``x-hookrelay-signature``) when a
   ``signing_config`` is configured
5. sends the request, records a ``delivery_attempts`` row for the
   dashboard/insights feed, and increments the destination's
   ``delivered_count`` / ``failed_count`` on the outcome.

Destination URLs were SSRF-validated at create/update time (see
:func:`hookrelay.routing.destination_store.validate_destination_url`), so
the delivery path itself performs no re-validation — exactly like the
v1.5 ``RetryQueue`` which guards at enqueue time.

The transport is module-level ``requests`` so tests can swap it with a
mock (``delivery/retry_queue.py`` follows the same seam).
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from hookrelay.routing.destination import (
    DeliveryMode,
    Destination,
    MultiDestinationRouter,
)
from hookrelay.routing.destination_store import DestinationStore
from hookrelay.routing.rules import RouterEngine
from hookrelay.security.outgoing import OutgoingSigner
from hookrelay.storage import Storage
from hookrelay.transforms.engine import TransformationEngine

#: Headers that are never forwarded to a destination (hop-by-hop + framing).
_STRIPPED_FORWARD_HEADERS = frozenset(
    {"host", "content-length", "connection", "transfer-encoding"}
)

_DEFAULT_MODE = DeliveryMode.BROADCAST


def _evaluate_routing(
    storage: Storage, bin_id: str, request_data: dict[str, Any]
) -> list[str] | None:
    """Evaluate conditional routing rules for *bin_id*.

    Returns the list of ``target_destination_ids`` from the first
    matched :class:`~hookrelay.routing.rules.RoutingRule`, or ``None``
    when no rule matches (triggering the fallback broadcast).
    """
    from hookrelay.routing.rules import RoutingRule

    # List routing rules for this bin (channel == bin_id), ordered by priority.
    raw_rules = storage.list_routing_rules(channel=bin_id)
    if not raw_rules:
        return None  # no rules → broadcast

    engine = RouterEngine()
    for raw in raw_rules:
        rule = RoutingRule(
            rule_id=raw["rule_id"],
            name=raw["name"],
            enabled=raw.get("enabled", True),
            priority=raw.get("priority", 100),
            condition=raw.get("condition"),
            target_endpoint=raw.get("target_endpoint"),
            channel=raw.get("channel"),
            max_forward_count=raw.get("max_forward_count"),
            fallback=raw.get("fallback", False),
            target_destination_ids=raw.get("target_destination_ids"),
        )
        engine.add_rule(rule)

    results = engine.evaluate(channel=bin_id, request_data=request_data)
    if not results:
        return None  # no match → fallback broadcast

    # Collect target_destination_ids from matched rules.
    matched = results[0][0]  # first match (first-match-wins)
    if matched.target_destination_ids:
        return matched.target_destination_ids
    return None  # rule matched but no target_destination_ids → broadcast


def _destination_records(store: Storage, bin_id: str) -> list[dict[str, Any]]:
    """Return the destination records for ``bin_id`` (newest first)."""
    return DestinationStore(store).list(bin_id=bin_id)


def _build_destinations(records: list[dict[str, Any]]) -> list[Destination]:
    """Convert stored records into :class:`Destination` models."""
    return [Destination.from_dict(record) for record in records]


def _router_for(records: list[dict[str, Any]]) -> MultiDestinationRouter:
    """Build a router whose mode follows the destinations' delivery_mode.

    The first enabled destination's ``delivery_mode`` acts as the fan-out
    mode for the bin (per docs/destinations.md: the destination's stored
    mode is used when the bin's router has no explicit override).
    """
    enabled = [r for r in records if r.get("enabled", True)]
    if not enabled:
        return MultiDestinationRouter([], mode=_DEFAULT_MODE)
    try:
        mode = DeliveryMode(enabled[0].get("delivery_mode", "broadcast"))
    except ValueError:
        mode = _DEFAULT_MODE
    return MultiDestinationRouter(_build_destinations(enabled), mode=mode)


def _load_transform(store: Storage, transform_id: str | None) -> TransformationEngine | None:
    """Load the transformation rule filters for ``transform_id``."""
    if not transform_id:
        return None
    from hookrelay.transforms.store import TransformationStore

    record = TransformationStore(store).get(transform_id)
    if record is None:
        return None
    return TransformationEngine(record.get("filters") or [])


def _signing_headers(
    signing_config: dict[str, Any] | None, payload: bytes
) -> dict[str, str]:
    """Return signing headers for ``signing_config`` (empty dict when unset)."""
    if not signing_config:
        return {}
    algorithm = signing_config.get("algorithm")
    secret = signing_config.get("secret")
    if not algorithm or not secret:
        return {}
    return OutgoingSigner(algorithm=algorithm, secret=secret).build_headers(payload)


def _prepare_body(
    raw_body: bytes | str, transform: TransformationEngine | None
) -> bytes:
    """Return the body to send: the transformed JSON, else the raw bytes.

    A transformation only applies when the payload is JSON; non-JSON
    payloads are forwarded byte-exact (the transform engine is a JSON
    engine, mirroring the documented preview semantics).
    """
    if transform is None:
        return raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        return raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
    if not isinstance(payload, dict):
        return raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
    transformed = transform.apply(payload)
    return json.dumps(transformed).encode("utf-8")


def _deliver_to_destination(
    store: Storage,
    *,
    request_id: str,
    channel: str,
    destination_id: str,
    url: str,
    transform: TransformationEngine | None,
    headers: dict[str, str],
    signing_config: dict[str, Any] | None,
    method: str,
    body: bytes,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send one payload to one destination; record attempt + counters.

    Returns a result dict with ``destination_id``, ``status``
    (``delivered`` | ``failed``), ``status_code`` and ``error``.
    """
    dest_store = DestinationStore(store)
    outgoing_headers = {
        key: value
        for key, value in headers.items()
        if key.lower() not in _STRIPPED_FORWARD_HEADERS
    }
    outgoing_headers.update(_signing_headers(signing_config, body))

    started = time.perf_counter()
    try:
        response = requests.request(
            method, url, headers=outgoing_headers, data=body, timeout=timeout
        )
    except requests.RequestException as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        store.store_delivery_attempt(
            request_id=request_id,
            channel=channel,
            status="transport_error",
            target_url=url,
            error=str(exc),
            duration_ms=latency_ms,
            endpoint_id=destination_id,
        )
        dest_store.increment_failed(destination_id)
        return {
            "destination_id": destination_id,
            "status": "failed",
            "status_code": 0,
            "error": str(exc),
        }

    latency_ms = (time.perf_counter() - started) * 1000.0
    store.store_delivery_attempt(
        request_id=request_id,
        channel=channel,
        status="delivered",
        target_url=url,
        response_status=response.status_code,
        duration_ms=latency_ms,
        response_body=response.text,
        endpoint_id=destination_id,
    )
    dest_store.increment_delivered(destination_id)
    return {
        "destination_id": destination_id,
        "status": "delivered",
        "status_code": response.status_code,
    }


def deliver_captured_request(
    bin_id: str,
    request_id: str,
    storage: Storage,
    *,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Route and deliver one captured request to its bin's destinations.

    Runs the full pipeline — route → transform → sign → send — for each
    destination selected by the bin's delivery mode and returns one
    result dict per attempted destination.

    Args:
        bin_id: The capture bin the request was received on.
        request_id: The stored request id (the webhooks ``channel`` must
            equal ``bin_id``).
        storage: The shared :class:`~hookrelay.storage.Storage`.
        timeout: Per-destination HTTP timeout in seconds.

    Returns:
        List of ``{"destination_id", "status", "status_code", "error"}``
        dicts; empty when the bin has no enabled destinations.
    """
    captured = storage.get_request(request_id)
    if captured is None or captured.get("channel") != bin_id:
        raise ValueError(f"Request {request_id} not found in bin {bin_id}")

    records = _destination_records(storage, bin_id)

    # --- Conditional routing: evaluate rules before fan-out. ---------
    # Build a request-like dict so the filter parser can inspect
    # body, method, path, and headers via the standard dot-paths.
    raw_body = captured.get("body", b"")
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    _request_data: dict[str, Any] = {
        "body": raw_body.decode("utf-8", errors="replace") if raw_body else "",
        "method": captured.get("method", "POST"),
        "path": captured.get("path", "/"),
        "headers": captured.get("headers", {}),
    }
    _target_ids = _evaluate_routing(storage, bin_id, _request_data)
    if _target_ids is not None:
        records = [r for r in records if r["destination_id"] in _target_ids]

    router = _router_for(records)
    instructions = router.route({})

    # Records keyed by destination id for lookup during the fan-out.
    by_id = {r["destination_id"]: r for r in records}

    method = captured.get("method", "POST")

    results: list[dict[str, Any]] = []
    for instruction in instructions:
        destination_id = instruction["destination_id"]
        record = by_id.get(destination_id)
        if record is None:
            continue
        transform = _load_transform(storage, record.get("transform_id"))
        body = _prepare_body(raw_body, transform)
        results.append(
            _deliver_to_destination(
                store=storage,
                request_id=request_id,
                channel=bin_id,
                destination_id=destination_id,
                url=record["url"],
                transform=transform,
                headers=record.get("headers") or {},
                signing_config=record.get("signing_config") or None,
                method=method,
                body=body,
                timeout=timeout,
            )
        )
    return results
