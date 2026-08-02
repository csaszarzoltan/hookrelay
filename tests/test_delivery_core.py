"""Pre-development tests for T1 core delivery infrastructure.

Covers RetryQueue, DeadLetterQueue, DeliveryTracker/DeliveryStatus, and
IdempotencyManager from analysis-brief.md §T1.

Two categories:
- Interface tests (Test*Interface): imports, class existence, signatures,
  type hints, keyword-only markers, defaults. MUST pass immediately against
  the stubs.
- Behavioral tests (Test*Behavioral): expected behavior encoded as assertions.
  MUST fail with NotImplementedError during the RED phase (stubs raise),
  and pass once the developer implements the modules.

Run: .venv/bin/python -m pytest tests/test_delivery_core.py -q
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from hookrelay.delivery import dlq as dlq_module
from hookrelay.delivery import idempotency as idempotency_module
from hookrelay.delivery import retry_queue as retry_queue_module
from hookrelay.delivery import tracker as tracker_module
from hookrelay.delivery.dlq import DeadLetterQueue
from hookrelay.delivery.idempotency import IdempotencyManager
from hookrelay.delivery.retry_queue import RetryQueue
from hookrelay.delivery.tracker import DeliveryStatus, DeliveryTracker
from hookrelay.storage import Storage

# ============================================================
# Helpers
# ============================================================

def _ann_ok(annotation, *expected):
    """True if annotation matches any expected form (string or live type).

    With `from __future__ import annotations`, inspect returns string
    annotations; after implementation they may be live types.
    """
    return any(annotation == exp for exp in expected)


def _delivery_kwargs(**overrides: Any) -> dict[str, Any]:
    """Standard keyword args for RetryQueue.enqueue."""
    kwargs = {
        "delivery_id": "dlv-0001",
        "request_id": "req-0001",
        "endpoint_id": "ep-0001",
        "target_url": "https://example.com/hook",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": b'{"event": "created"}',
        "idempotency_key": None,
        "policy": None,
    }
    kwargs.update(overrides)
    return kwargs


class _FakeRetryPolicy:
    """Duck-typed stand-in for T2 RetryPolicy (not yet implemented).

    Mirrors the T2 RetryPolicy contract: max_retries, backoff_factor,
    base_delay_seconds, max_backoff_seconds, jitter, and backoff_delay(attempt).
    """

    def __init__(
        self,
        max_retries: int = 5,
        backoff_factor: float = 2.0,
        base_delay_seconds: float = 1.0,
        max_backoff_seconds: float = 3600.0,
        jitter: bool = False,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.base_delay_seconds = base_delay_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.jitter = jitter

    def backoff_delay(self, attempt: int) -> float:
        delay = self.base_delay_seconds * (self.backoff_factor**attempt)
        return min(self.max_backoff_seconds, delay)


# ============================================================
# Interface tests — module + class existence
# ============================================================


class TestDeliveryPackageInterface:
    """Verify the delivery package and its modules import cleanly."""

    def test_retry_queue_module_importable(self):
        assert retry_queue_module is not None
        assert hasattr(retry_queue_module, "RetryQueue")

    def test_dlq_module_importable(self):
        assert dlq_module is not None
        assert hasattr(dlq_module, "DeadLetterQueue")

    def test_tracker_module_importable(self):
        assert tracker_module is not None
        assert hasattr(tracker_module, "DeliveryTracker")
        assert hasattr(tracker_module, "DeliveryStatus")

    def test_idempotency_module_importable(self):
        assert idempotency_module is not None
        assert hasattr(idempotency_module, "IdempotencyManager")

    def test_all_classes_are_classes(self):
        assert inspect.isclass(RetryQueue)
        assert inspect.isclass(DeadLetterQueue)
        assert inspect.isclass(DeliveryTracker)
        assert inspect.isclass(DeliveryStatus)
        assert inspect.isclass(IdempotencyManager)


# ============================================================
# Interface tests — DeliveryStatus constants
# ============================================================


class TestDeliveryStatusInterface:
    """Verify DeliveryStatus constant values."""

    def test_pending_constant(self):
        assert DeliveryStatus.PENDING == "pending"

    def test_delivered_constant(self):
        assert DeliveryStatus.DELIVERED == "delivered"

    def test_failed_constant(self):
        assert DeliveryStatus.FAILED == "failed"

    def test_in_dlq_constant(self):
        assert DeliveryStatus.IN_DLQ == "in-dlq"

    def test_all_tuple_contains_every_status(self):
        assert isinstance(DeliveryStatus.ALL, tuple)
        assert set(DeliveryStatus.ALL) == {
            "pending",
            "delivered",
            "failed",
            "in-dlq",
        }


# ============================================================
# Interface tests — RetryQueue
# ============================================================


class TestRetryQueueInterface:
    """Verify RetryQueue method signatures and type hints."""

    def test_init_signature(self):
        sig = inspect.signature(RetryQueue.__init__)
        params = sig.parameters
        assert "self" in params
        assert "storage" in params

    def test_enqueue_is_keyword_only(self):
        sig = inspect.signature(RetryQueue.enqueue)
        for name in (
            "delivery_id",
            "request_id",
            "endpoint_id",
            "target_url",
            "method",
            "headers",
            "body",
            "idempotency_key",
            "policy",
        ):
            assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name

    def test_enqueue_defaults(self):
        sig = inspect.signature(RetryQueue.enqueue)
        assert sig.parameters["idempotency_key"].default is None
        assert sig.parameters["policy"].default is None

    def test_enqueue_type_hints(self):
        sig = inspect.signature(RetryQueue.enqueue)
        assert _ann_ok(sig.parameters["headers"].annotation, "dict[str, str]", dict[str, str])
        assert _ann_ok(sig.parameters["body"].annotation, "bytes | None", bytes | None)
        assert _ann_ok(sig.parameters["idempotency_key"].annotation, "str | None", str | None)
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_dequeue_due_signature(self):
        sig = inspect.signature(RetryQueue.dequeue_due)
        assert sig.parameters["limit"].default == 100
        assert sig.parameters["now"].default is None
        assert _ann_ok(sig.parameters["limit"].annotation, "int", int)
        assert _ann_ok(sig.parameters["now"].annotation, "datetime | None", None)
        assert _ann_ok(sig.return_annotation, "list[dict]", list[dict])

    def test_record_attempt_signature(self):
        sig = inspect.signature(RetryQueue.record_attempt)
        params = sig.parameters
        assert "delivery_id" in params
        assert params["delivery_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for name in ("success", "response_status", "duration_ms", "error"):
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert params["success"].default is inspect.Parameter.empty
        assert params["response_status"].default is None
        assert params["duration_ms"].default is None
        assert params["error"].default is None
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_backoff_delay_is_staticmethod(self):
        assert isinstance(
            inspect.getattr_static(RetryQueue, "backoff_delay"), staticmethod
        )

    def test_backoff_delay_signature(self):
        sig = inspect.signature(RetryQueue.backoff_delay)
        params = sig.parameters
        assert "attempt" in params
        assert params["attempt"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert params["base_delay"].default == 1.0
        assert params["backoff_factor"].default == 2.0
        assert params["max_backoff"].default == 3600.0
        assert params["jitter"].default is True
        assert _ann_ok(sig.return_annotation, "float", float)

    def test_pending_count_signature(self):
        sig = inspect.signature(RetryQueue.pending_count)
        assert _ann_ok(sig.return_annotation, "int", int)

    def test_get_signature(self):
        sig = inspect.signature(RetryQueue.get)
        assert "delivery_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "dict | None", dict | None)

    def test_delete_signature(self):
        sig = inspect.signature(RetryQueue.delete)
        assert "delivery_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "bool", bool)


# ============================================================
# Interface tests — DeadLetterQueue
# ============================================================


class TestDeadLetterQueueInterface:
    """Verify DeadLetterQueue method signatures and type hints."""

    def test_init_signature(self):
        sig = inspect.signature(DeadLetterQueue.__init__)
        assert "storage" in sig.parameters

    def test_dead_letter_signature(self):
        sig = inspect.signature(DeadLetterQueue.dead_letter)
        params = sig.parameters
        assert "delivery_id" in params
        assert params["delivery_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert params["reason"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["error"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["error"].default is None
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_list_entries_signature(self):
        sig = inspect.signature(DeadLetterQueue.list_entries)
        assert sig.parameters["limit"].default == 100
        assert sig.parameters["endpoint_id"].default is None
        assert _ann_ok(sig.return_annotation, "list[dict]", list[dict])

    def test_requeue_signature(self):
        sig = inspect.signature(DeadLetterQueue.requeue)
        assert "entry_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_count_signature(self):
        sig = inspect.signature(DeadLetterQueue.count)
        assert _ann_ok(sig.return_annotation, "int", int)

    def test_get_signature(self):
        sig = inspect.signature(DeadLetterQueue.get)
        assert "entry_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "dict | None", dict | None)


# ============================================================
# Interface tests — DeliveryTracker
# ============================================================


class TestDeliveryTrackerInterface:
    """Verify DeliveryTracker method signatures and type hints."""

    def test_init_signature(self):
        sig = inspect.signature(DeliveryTracker.__init__)
        assert "storage" in sig.parameters

    def test_create_keyword_only(self):
        sig = inspect.signature(DeliveryTracker.create)
        for name in ("request_id", "endpoint_id", "idempotency_key"):
            assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert sig.parameters["idempotency_key"].default is None
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_get_status_signature(self):
        sig = inspect.signature(DeliveryTracker.get_status)
        assert "delivery_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "str", str)

    def test_transition_signature(self):
        sig = inspect.signature(DeliveryTracker.transition)
        assert "delivery_id" in sig.parameters
        assert "new_status" in sig.parameters
        assert _ann_ok(sig.return_annotation, "None", None)

    def test_list_signature(self):
        sig = inspect.signature(DeliveryTracker.list)
        assert sig.parameters["status"].default is None
        assert sig.parameters["endpoint_id"].default is None
        assert sig.parameters["limit"].default == 100
        assert _ann_ok(sig.return_annotation, "list[dict]", list[dict])

    def test_count_by_status_signature(self):
        sig = inspect.signature(DeliveryTracker.count_by_status)
        assert _ann_ok(sig.return_annotation, "dict[str, int]", dict[str, int])


# ============================================================
# Interface tests — IdempotencyManager
# ============================================================


class TestIdempotencyManagerInterface:
    """Verify IdempotencyManager method signatures and type hints."""

    def test_init_signature(self):
        sig = inspect.signature(IdempotencyManager.__init__)
        assert "storage" in sig.parameters
        assert sig.parameters["ttl_seconds"].default == 86400
        assert _ann_ok(sig.parameters["ttl_seconds"].annotation, "int", int)

    def test_register_signature(self):
        sig = inspect.signature(IdempotencyManager.register)
        assert "key" in sig.parameters
        assert "delivery_id" in sig.parameters
        assert _ann_ok(sig.return_annotation, "bool", bool)

    def test_lookup_signature(self):
        sig = inspect.signature(IdempotencyManager.lookup)
        assert "key" in sig.parameters
        assert _ann_ok(sig.return_annotation, "str | None", str | None)

    def test_is_active_signature(self):
        sig = inspect.signature(IdempotencyManager.is_active)
        assert "key" in sig.parameters
        assert _ann_ok(sig.return_annotation, "bool", bool)

    def test_purge_expired_signature(self):
        sig = inspect.signature(IdempotencyManager.purge_expired)
        assert _ann_ok(sig.return_annotation, "int", int)


# ============================================================
# Behavioral tests — RetryQueue.backoff_delay (pure function)
# ============================================================


class TestBackoffDelayBehavioral:
    """RED: exponential backoff formula, cap, and jitter bounds."""

    def test_backoff_attempt_zero_is_base(self):
        assert RetryQueue.backoff_delay(0, jitter=False) == 1.0

    def test_backoff_exponential_growth(self):
        assert RetryQueue.backoff_delay(1, jitter=False) == 2.0
        assert RetryQueue.backoff_delay(2, jitter=False) == 4.0
        assert RetryQueue.backoff_delay(3, jitter=False) == 8.0

    def test_backoff_respects_max_backoff(self):
        assert RetryQueue.backoff_delay(100, jitter=False) == 3600.0

    def test_backoff_custom_params(self):
        assert (
            RetryQueue.backoff_delay(
                2, base_delay=0.5, backoff_factor=3.0, max_backoff=100.0, jitter=False
            )
            == 4.5
        )

    def test_backoff_jitter_within_bounds(self):
        samples = [RetryQueue.backoff_delay(1, jitter=True) for _ in range(50)]
        assert all(0.0 <= s < 4.0 for s in samples), samples
        # jitter must actually perturb the deterministic value (2.0)
        assert any(s != 2.0 for s in samples)


# ============================================================
# Behavioral tests — RetryQueue queue lifecycle
# ============================================================


@pytest.fixture
def storage(tmp_path):
    """Isolated Storage DB per test."""
    return Storage(str(tmp_path / "delivery.db"))


class TestRetryQueueBehavioral:
    """RED: enqueue/dequeue/attempt lifecycle."""

    def test_enqueue_returns_delivery_id(self, storage):
        queue = RetryQueue(storage)
        result = queue.enqueue(**_delivery_kwargs())
        assert result == "dlv-0001"

    def test_enqueue_sets_pending_status(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs())
        row = queue.get("dlv-0001")
        assert row is not None
        assert row["status"] == "pending"

    def test_enqueue_duplicate_idempotency_key_raises(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs(idempotency_key="idem-1"))
        with pytest.raises(ValueError):
            queue.enqueue(
                **_delivery_kwargs(delivery_id="dlv-0002", idempotency_key="idem-1")
            )

    def test_enqueue_ssrf_chokepoint(self, storage):
        # R1 regression: the enqueue chokepoint must reject link-local SSRF
        # targets (cloud metadata endpoint) while still accepting public ones.
        queue = RetryQueue(storage)
        with pytest.raises(ValueError):
            queue.enqueue(
                **_delivery_kwargs(
                    target_url="http://169.254.169.254/latest/meta-data/"
                )
            )
        assert queue.enqueue(**_delivery_kwargs()) == "dlv-0001"

    def test_dequeue_due_returns_due_deliveries(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs())
        due = queue.dequeue_due()
        assert isinstance(due, list)
        assert len(due) == 1
        assert due[0]["delivery_id"] == "dlv-0001"

    def test_dequeue_due_respects_limit(self, storage):
        queue = RetryQueue(storage)
        for i in range(3):
            queue.enqueue(**_delivery_kwargs(delivery_id=f"dlv-{i:04d}"))
        due = queue.dequeue_due(limit=2)
        assert len(due) == 2

    def test_record_attempt_success_returns_delivered(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs())
        status = queue.record_attempt("dlv-0001", success=True, response_status=200)
        assert status == "delivered"

    def test_record_attempt_failure_keeps_pending_when_retries_left(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(
            **_delivery_kwargs(policy=_FakeRetryPolicy(max_retries=3))
        )
        status = queue.record_attempt("dlv-0001", success=False, error="timeout")
        assert status == "pending"

    def test_record_attempt_failure_past_max_retries_moves_to_dlq(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(
            **_delivery_kwargs(policy=_FakeRetryPolicy(max_retries=2))
        )
        queue.record_attempt("dlv-0001", success=False, error="500")
        status = queue.record_attempt("dlv-0001", success=False, error="500")
        assert status == "in-dlq"

    def test_pending_count_zero_initial(self, storage):
        queue = RetryQueue(storage)
        assert queue.pending_count() == 0

    def test_pending_count_increments_after_enqueue(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs())
        assert queue.pending_count() == 1

    def test_get_returns_none_for_missing(self, storage):
        queue = RetryQueue(storage)
        assert queue.get("does-not-exist") is None

    def test_delete_removes_delivery(self, storage):
        queue = RetryQueue(storage)
        queue.enqueue(**_delivery_kwargs())
        assert queue.delete("dlv-0001") is True
        assert queue.get("dlv-0001") is None


# ============================================================
# Behavioral tests — DeadLetterQueue
# ============================================================


class TestDeadLetterQueueBehavioral:
    """RED: dead-letter placement, listing, requeue."""

    def test_dead_letter_returns_entry_id(self, storage):
        dq = DeadLetterQueue(storage)
        entry_id = dq.dead_letter("dlv-0001", reason="max retries exceeded")
        assert isinstance(entry_id, str)
        assert entry_id

    def test_dead_letter_persists_reason(self, storage):
        dq = DeadLetterQueue(storage)
        entry_id = dq.dead_letter("dlv-0001", reason="max retries exceeded")
        row = dq.get(entry_id)
        assert row is not None
        assert row["reason"] == "max retries exceeded"

    def test_dead_letter_sets_delivery_status_in_dlq(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        dq = DeadLetterQueue(storage)
        dq.dead_letter(delivery_id, reason="permanent failure")
        assert tracker.get_status(delivery_id) == "in-dlq"

    def test_count_increments(self, storage):
        dq = DeadLetterQueue(storage)
        assert dq.count() == 0
        dq.dead_letter("dlv-0001", reason="r1")
        dq.dead_letter("dlv-0002", reason="r2")
        assert dq.count() == 2

    def test_list_entries_returns_all(self, storage):
        dq = DeadLetterQueue(storage)
        dq.dead_letter("dlv-0001", reason="r1")
        dq.dead_letter("dlv-0002", reason="r2")
        entries = dq.list_entries()
        assert len(entries) == 2

    def test_list_entries_filters_by_endpoint(self, storage):
        dq = DeadLetterQueue(storage)
        dq.dead_letter("dlv-0001", reason="r1", error=None)
        dq.dead_letter("dlv-0002", reason="r2")
        entries = dq.list_entries(endpoint_id="ep-0001")
        assert isinstance(entries, list)
        assert all(e["endpoint_id"] == "ep-0001" for e in entries)

    def test_requeue_returns_delivery_id(self, storage):
        dq = DeadLetterQueue(storage)
        entry_id = dq.dead_letter("dlv-0001", reason="r1")
        result = dq.requeue(entry_id)
        assert result == "dlv-0001"

    def test_requeue_resets_status_to_pending(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        dq = DeadLetterQueue(storage)
        entry_id = dq.dead_letter(delivery_id, reason="r1")
        dq.requeue(entry_id)
        assert tracker.get_status(delivery_id) == "pending"

    def test_requeue_removes_dlq_entry(self, storage):
        dq = DeadLetterQueue(storage)
        entry_id = dq.dead_letter("dlv-0001", reason="r1")
        dq.requeue(entry_id)
        assert dq.get(entry_id) is None
        assert dq.count() == 0


# ============================================================
# Behavioral tests — DeliveryTracker status machine
# ============================================================


class TestDeliveryTrackerBehavioral:
    """RED: create, status reads, transitions, invalid edges."""

    def test_create_returns_delivery_id(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        assert isinstance(delivery_id, str)
        assert delivery_id

    def test_get_status_pending_after_create(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        assert tracker.get_status(delivery_id) == "pending"

    def test_transition_pending_to_delivered(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "delivered")
        assert tracker.get_status(delivery_id) == "delivered"

    def test_transition_pending_to_failed(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "failed")
        assert tracker.get_status(delivery_id) == "failed"

    def test_transition_failed_to_in_dlq(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "failed")
        tracker.transition(delivery_id, "in-dlq")
        assert tracker.get_status(delivery_id) == "in-dlq"

    def test_transition_in_dlq_to_pending_requeue(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "failed")
        tracker.transition(delivery_id, "in-dlq")
        tracker.transition(delivery_id, "pending")
        assert tracker.get_status(delivery_id) == "pending"

    def test_transition_delivered_to_failed_raises(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "delivered")
        with pytest.raises(ValueError):
            tracker.transition(delivery_id, "failed")

    def test_transition_pending_to_in_dlq_allowed(self, storage):
        """pending->in-dlq is a valid edge (retry queue handoff to DLQ)."""
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "in-dlq")
        assert tracker.get_status(delivery_id) == "in-dlq"

    def test_transition_pending_to_pending_allowed(self, storage):
        """pending->pending is a valid edge (retry rescheduling)."""
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.transition(delivery_id, "pending")
        assert tracker.get_status(delivery_id) == "pending"

    def test_transition_unknown_status_raises(self, storage):
        tracker = DeliveryTracker(storage)
        delivery_id = tracker.create(request_id="req-1", endpoint_id="ep-1")
        with pytest.raises(ValueError):
            tracker.transition(delivery_id, "bogus-status")

    def test_list_returns_deliveries(self, storage):
        tracker = DeliveryTracker(storage)
        tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.create(request_id="req-2", endpoint_id="ep-2")
        rows = tracker.list()
        assert len(rows) == 2

    def test_list_filters_by_status(self, storage):
        tracker = DeliveryTracker(storage)
        d1 = tracker.create(request_id="req-1", endpoint_id="ep-1")
        tracker.create(request_id="req-2", endpoint_id="ep-2")
        tracker.transition(d1, "delivered")
        rows = tracker.list(status="delivered")
        assert len(rows) == 1
        assert rows[0]["delivery_id"] == d1

    def test_count_by_status(self, storage):
        tracker = DeliveryTracker(storage)
        d1 = tracker.create(request_id="req-1", endpoint_id="ep-1")
        d2 = tracker.create(request_id="req-2", endpoint_id="ep-1")
        tracker.transition(d1, "delivered")
        tracker.transition(d2, "failed")
        counts = tracker.count_by_status()
        assert counts["pending"] == 0
        assert counts["delivered"] == 1
        assert counts["failed"] == 1
        assert counts["in-dlq"] == 0


# ============================================================
# Behavioral tests — IdempotencyManager
# ============================================================


class TestIdempotencyManagerBehavioral:
    """RED: dedup, lookup, TTL purge."""

    def test_register_returns_true_first_time(self, storage):
        manager = IdempotencyManager(storage)
        assert manager.register("key-1", "dlv-0001") is True

    def test_register_duplicate_returns_false(self, storage):
        manager = IdempotencyManager(storage)
        manager.register("key-1", "dlv-0001")
        assert manager.register("key-1", "dlv-0002") is False

    def test_lookup_returns_first_delivery_id(self, storage):
        manager = IdempotencyManager(storage)
        manager.register("key-1", "dlv-0001")
        assert manager.lookup("key-1") == "dlv-0001"

    def test_lookup_unknown_returns_none(self, storage):
        manager = IdempotencyManager(storage)
        assert manager.lookup("missing-key") is None

    def test_is_active_after_register(self, storage):
        manager = IdempotencyManager(storage)
        manager.register("key-1", "dlv-0001")
        assert manager.is_active("key-1") is True

    def test_is_active_false_for_unknown(self, storage):
        manager = IdempotencyManager(storage)
        assert manager.is_active("missing-key") is False

    def test_purge_expired_removes_stale_keys(self, storage):
        manager = IdempotencyManager(storage, ttl_seconds=-1)
        manager.register("stale-key", "dlv-0001")
        purged = manager.purge_expired()
        assert purged == 1
        assert manager.is_active("stale-key") is False
        assert manager.lookup("stale-key") is None
