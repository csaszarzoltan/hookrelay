"""Webhook transformations, multi-destination routing and signing (hookrelay v1.8.0).

Walks through the three v1.8.0 building blocks end-to-end:

1. Create a named transformation rule (JQ-style filters) and preview it.
2. Attach destinations to a capture bin, each with its own transformation,
   signing config, headers, retry policy and delivery mode.
3. Route a payload through a MultiDestinationRouter (broadcast, round-robin,
   weighted) and sign the outgoing body with every supported algorithm
   (svix, hookdeck, github, custom), verifying the signature afterwards.

No server is required — the example drives the stores, router and signer
directly against a scratch SQLite database in a temp directory.

Usage:
    python examples/transforms_routing.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hookrelay.routing.destination import (
    DeliveryMode,
    Destination,
    MultiDestinationRouter,
)
from hookrelay.routing.destination_store import DestinationStore
from hookrelay.security.outgoing import OutgoingSigner, verify_signature
from hookrelay.storage import Storage
from hookrelay.transforms.engine import preview_transformation
from hookrelay.transforms.store import TransformationStore


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-transforms-")) / "t.db"
    storage = Storage(str(db))

    # 1. Create a named transformation rule and preview it against a payload.
    #    Filters run in order; each may contain several statements split by `|`.
    transform_store = TransformationStore(storage)
    rule = transform_store.create(
        "scrub-and-normalize",
        [
            ".data.currency |= uppercase",
            ".data.amount :: integer",
            ".sent_at = timestamp",
            "del(.token)",
        ],
    )
    print(f"Created transformation {rule['transform_id'][:8]}... ({rule['name']})")

    raw = {
        "event": "order.created",
        "data": {"currency": "usd", "amount": "4200"},
        "token": "sk_live_1234567890abc",
    }
    preview = preview_transformation(rule["filters"], raw)
    print(f"Preview: {preview}")

    # 2. Attach destinations to a bin. Each destination can transform,
    #    sign, add headers, and carry its own retry policy.
    destination_store = DestinationStore(storage)
    primary = destination_store.create(
        bin_id="bin-checkout",
        url="https://api.acme.com/hook",
        transform_id=rule["transform_id"],
        signing_config={"algorithm": "github", "secret": "whsec_checkout"},
        headers={"X-Source": "hookrelay"},
        retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
    )
    canary = destination_store.create(
        bin_id="bin-checkout",
        url="https://canary.acme.com/hook",
        delivery_mode="round_robin",
        weight=1,
    )
    print(
        f"Destinations: {primary['destination_id'][:8]}... (github-signed), "
        f"{canary['destination_id'][:8]}... (round_robin)"
    )
    print(f"Bin listing: {[d['destination_id'][:8] for d in destination_store.list('bin-checkout')]}")

    # 3. Route one inbound payload to multiple destinations.
    destinations = [
        Destination(
            d["destination_id"], d["bin_id"], d["url"],
            transform_id=d["transform_id"], signing_config=d["signing_config"],
            headers=d["headers"], retry_policy=d["retry_policy"],
            enabled=d["enabled"], weight=d["weight"], delivery_mode=d["delivery_mode"],
        )
        for d in destination_store.list("bin-checkout")
    ]

    broadcast = MultiDestinationRouter(destinations, DeliveryMode.BROADCAST)
    print(f"Broadcast routes: {[r['destination_id'][:8] for r in broadcast.route(raw)]}")

    weighted = MultiDestinationRouter(
        [
            Destination("w1", "bin-checkout", "https://a.example.com", weight=1),
            Destination("w2", "bin-checkout", "https://b.example.com", weight=3),
        ],
        DeliveryMode.WEIGHTED,
    )
    picks = {}
    for _ in range(400):
        picked = weighted.next_destination()
        picks[picked.destination_id] = picks.get(picked.destination_id, 0) + 1
    print(f"Weighted picks (w1=1, w2=3): {picks}")

    # 4. Sign the outgoing body for every supported algorithm and verify.
    body = b'{"event": "order.created", "amount": 4200}'
    for algorithm in ("svix", "hookdeck", "github", "custom"):
        signer = OutgoingSigner(algorithm=algorithm, secret="whsec_demo")
        signature = signer.sign(body, timestamp="1720000000")
        headers = signer.build_headers(body, timestamp="1720000000")
        ok = verify_signature(body, signature, "whsec_demo", algorithm, timestamp="1720000000")
        print(
            f"{algorithm}: x-hookrelay-signature={signature[:16]}... "
            f"headers={sorted(headers)} verified={ok}"
        )

    # 5. Cleanup — the scratch database is deleted with its temp directory.
    assert transform_store.delete(rule["transform_id"]) is True
    assert destination_store.delete(primary["destination_id"]) is True
    assert destination_store.delete(canary["destination_id"]) is True
    print("Cleanup complete.")


if __name__ == "__main__":
    main()
