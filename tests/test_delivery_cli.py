"""Tests for the v1.5 delivery / DLQ CLI subcommands.

Covers ``hookrelay delivery list|status`` and ``hookrelay dlq list|requeue``,
which expose the library-only delivery infrastructure from the terminal.
"""

from __future__ import annotations

import pytest
import typer

from hookrelay import _storage
from hookrelay.cli import get_app
from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.delivery import DeadLetterQueue, RetryQueue
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path):
    store = Storage(str(tmp_path / "cli.db"))
    _storage.set(store)
    return store


def _seed_delivery(store, delivery_id="dlv-1", endpoint_id="ep-1"):
    RetryQueue(store).enqueue(
        delivery_id=delivery_id, request_id=f"req-{delivery_id}",
        endpoint_id=endpoint_id, target_url="https://example.com/hook",
        method="POST", headers={}, body=None,
    )
    return delivery_id


def _seed_dlq(store, delivery_id="dlv-dead"):
    RetryQueue(store).enqueue(
        delivery_id=delivery_id, request_id=f"req-{delivery_id}",
        endpoint_id="ep-1", target_url="https://example.com/hook",
        method="POST", headers={}, body=None,
        policy=RetryPolicy(max_retries=0, jitter=False),
    )
    RetryQueue(store).record_attempt(delivery_id, success=False, error="boom")
    return DeadLetterQueue(store).list_entries()[0]["entry_id"]


# ============================================================
# delivery list
# ============================================================


class TestDeliveryListCli:
    def test_registered_as_delivery_subcommand(self):
        app = get_app()
        assert hasattr(app, "registered_groups")
        names = [group.name for group in app.registered_groups]
        assert "delivery" in names

    def test_lists_seeded_deliveries(self, store, capsys):
        _seed_delivery(store)
        from hookrelay.cli import delivery_list

        delivery_list()
        out = capsys.readouterr().out
        assert "dlv-1" in out
        assert "pending" in out

    def test_empty_list_prints_no_deliveries(self, store, capsys):
        from hookrelay.cli import delivery_list

        delivery_list()
        out = capsys.readouterr().out
        assert "No deliveries" in out


# ============================================================
# delivery status
# ============================================================


class TestDeliveryStatusCli:
    def test_status_prints_delivery_json(self, store, capsys):
        _seed_delivery(store)
        from hookrelay.cli import delivery_status

        delivery_status("dlv-1")
        out = capsys.readouterr().out
        assert "dlv-1" in out
        assert "pending" in out

    def test_status_unknown_raises_exit(self, store):
        from hookrelay.cli import delivery_status

        with pytest.raises(typer.Exit):
            delivery_status("missing")


# ============================================================
# dlq list
# ============================================================


class TestDlqListCli:
    def test_registered_as_dlq_subcommand(self):
        app = get_app()
        assert hasattr(app, "registered_groups")
        names = [group.name for group in app.registered_groups]
        assert "dlq" in names

    def test_lists_dead_letter_entries(self, store, capsys):
        _seed_dlq(store)
        from hookrelay.cli import dlq_list

        dlq_list()
        out = capsys.readouterr().out
        assert "dlv-dead" in out
        assert "max retries exceeded" in out

    def test_empty_dlq_prints_message(self, store, capsys):
        from hookrelay.cli import dlq_list

        dlq_list()
        out = capsys.readouterr().out
        assert "No dead-letter" in out


# ============================================================
# dlq requeue
# ============================================================


class TestDlqRequeueCli:
    def test_requeue_moves_delivery_back_to_pending(self, store, capsys):
        entry_id = _seed_dlq(store)
        from hookrelay.cli import dlq_requeue

        dlq_requeue(entry_id)
        out = capsys.readouterr().out
        assert "dlv-dead" in out
        assert DeadLetterQueue(store).count() == 0
        assert RetryQueue(store).get("dlv-dead")["status"] == "pending"

    def test_requeue_unknown_entry_raises_exit(self, store):
        from hookrelay.cli import dlq_requeue

        with pytest.raises(typer.Exit):
            dlq_requeue("missing-entry")
