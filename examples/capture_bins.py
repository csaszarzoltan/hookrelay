"""Webhook capture bins example (hookrelay v1.6.0).

Shows how to create a persistent, webhook.site-style capture bin, capture
requests into it, inspect the captured payloads, forward one to a target
(SSRF-guarded), and delete the bin.

No server is required — the example drives BinService directly against a
scratch SQLite database in a temp directory.

Usage:
    python examples/capture_bins.py

To also exercise a real forward round-trip, set HOOKRELAY_FORWARD_TARGET to a
public URL (the SSRF guard blocks private/loopback/system-port targets):

    HOOKRELAY_FORWARD_TARGET=https://example.com/webhook python examples/capture_bins.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from hookrelay.bins.forward import forward_captured_request
from hookrelay.bins.service import BinService
from hookrelay.storage import Storage


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-bins-")) / "bins.db"
    storage = Storage(str(db))
    service = BinService(storage)

    # 1. Create a bin — the bin id doubles as the webhooks channel, so
    #    captured requests persist like any other stored webhook.
    created = service.create_bin(description="stripe tests")
    print(f"Created bin {created.bin_id[:8]}... -> {created.url}")

    # 2. Capture requests into the bin (method/headers/body/query/source).
    captured = service.capture(
        bin_id=created.bin_id,
        method="POST",
        headers={"content-type": "application/json", "x-custom": "yes"},
        body=b'{"event": "invoice.paid", "amount": 4200}',
        query_params={"src": "stripe"},
        source_ip="203.0.113.5",
    )
    service.capture(
        bin_id=created.bin_id,
        method="GET",
        headers={},
        body=b"",
        query_params={},
        source_ip="203.0.113.5",
    )
    print(f"Captured request {captured.request_id[:8]}... ({captured.method})")

    # 3. Inspect the bin: request count and paginated listing.
    bins = service.list_bins()
    print(f"Bin request_count: {bins[0].request_count}")
    listing = service.list_requests(created.bin_id, limit=20, offset=0)
    print(f"Captured requests: {listing['total']}")

    # 4. Full payload view of one request.
    detail = service.get_request(created.bin_id, captured.request_id)
    assert detail is not None, "expected the captured request to exist"
    print(
        f"Payload: method={detail['method']} query={detail['query_params']} "
        f"source_ip={detail['source_ip']} body={detail['body']!r}"
    )

    # 5. One-click forward. The SSRF guard rejects private/loopback targets
    #    with a ValueError; a public target (HOOKRELAY_FORWARD_TARGET) is
    #    forwarded for real and the outcome recorded.
    target = os.environ.get("HOOKRELAY_FORWARD_TARGET")
    if target:
        result = forward_captured_request(
            created.bin_id, captured.request_id, target, storage=storage
        )
        print(
            f"Forwarded -> {result.target_url}: HTTP {result.status_code} "
            f"in {result.latency_ms:.1f} ms"
        )
    else:
        try:
            forward_captured_request(
                created.bin_id,
                captured.request_id,
                "http://127.0.0.1:9999/internal",
                storage=storage,
            )
        except ValueError as exc:
            print(f"SSRF guard blocked private target: {exc}")

    # 6. Delete the bin (cascades its captured requests).
    deleted = service.delete_bin(created.bin_id)
    print(f"Deleted bin: {deleted}  Remaining bins: {len(service.list_bins())}")


if __name__ == "__main__":
    main()
