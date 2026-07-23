"""Replay and inspect webhooks using the hookrelay client API.

This example demonstrates using hookrelay's client API programmatically
to inspect stored webhooks and replay them.
"""

from __future__ import annotations

import json
from hookrelay.client import connect_and_forward
from hookrelay.storage import Storage


def inspect_history(db_path: str = "/tmp/hookrelay/webhooks.db") -> None:
    """Inspect stored webhook history."""
    store = Storage(db_path)
    requests = store.list_requests(limit=5)

    print(f"📋 Recent webhooks ({len(requests)} found):")
    for req in requests:
        print(f"  [{req.get('method', '?')}] {req.get('path', '/')} "
              f"— {req.get('request_id', '?')[:12]} "
              f"@ {req.get('received_at', '?')}")

    if requests:
        first_id = requests[0]["request_id"]
        detail = store.get_request(first_id)
        if detail:
            print(f"\n🔍 Full detail for {first_id[:12]}:")
            print(json.dumps(detail, indent=2, default=str))


if __name__ == "__main__":
    print("=== hookrelay API Example ===")
    print()
    print("To forward webhooks programmatically:")
    print("  connect_and_forward(")
    print('      server="http://localhost:8000",')
    print('      channel="demo",')
    print('      target="http://localhost:9000/webhook",')
    print("      timeout=30.0,")
    print("  )")
    print()
    print("To inspect history (requires a running relay with stored webhooks):")
    print("  inspect_history('/tmp/hookrelay/webhooks.db')")
    print()
    inspect_history()
