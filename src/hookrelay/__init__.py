"""hookrelay — Webhook relay tool for local development."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"


class _StorageHolder:
    """Module-level storage holder for sharing across modules."""

    def __init__(self) -> None:
        self._store: Any = None

    def get(self) -> Any:
        return self._store

    def set(self, store: Any) -> None:
        self._store = store


_storage = _StorageHolder()
