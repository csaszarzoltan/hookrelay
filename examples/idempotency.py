"""Idempotency key management example (hookrelay v1.5.0).

Shows how IdempotencyManager prevents duplicate deliveries when the
same webhook event arrives more than once, and how expired keys are
purged from the registry.

Usage:
    python examples/idempotency.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hookrelay.delivery import IdempotencyManager
from hookrelay.storage import Storage


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-idem-")) / "deliveries.db"
    storage = Storage(str(db))
    manager = IdempotencyManager(storage, ttl_seconds=86400)

    key = "stripe_evt_123"
    registered = manager.register(key, "dlv-0001")
    print(f"First register: {registered} (True = newly registered)")
    print(f"is_active({key}): {manager.is_active(key)}")
    print(f"lookup({key}): {manager.lookup(key)}")

    # A duplicate webhook event with the same key is rejected while active.
    duplicate = manager.register(key, "dlv-0002")
    print(f"Duplicate register: {duplicate} (False = already active, rejected)")
    print(f"Original mapping preserved: {manager.lookup(key)}")

    purged = manager.purge_expired()
    print(f"Purged {purged} expired key(s) (this key is still active)")


if __name__ == "__main__":
    main()
