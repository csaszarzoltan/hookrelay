"""TDD acceptance tests for v1.3 actor identity and signed audit checkpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.audit import (
    actor_fingerprint,
    create_audit_checkpoint,
    verify_audit_checkpoint,
)
from hookrelay.backup import create_backup, inspect_backup, list_backups
from hookrelay.server import create_app
from hookrelay.storage import Storage


def test_actor_fingerprint_is_stable_non_reversible_and_labeled():
    first = actor_fingerprint("secret-token")
    second = actor_fingerprint("secret-token")
    other = actor_fingerprint("other-token")
    assert first == second
    assert first.startswith("token:")
    assert first != other
    assert "secret-token" not in first
    assert len(first) == len("token:") + 16


def test_signed_audit_checkpoint_detects_modified_chain_head(tmp_path):
    store = Storage(str(tmp_path / "checkpoint.db"))
    store.record_audit_event("request.received", "system", "request", "r1", "success")
    checkpoint = create_audit_checkpoint(store, "checkpoint-secret")
    assert verify_audit_checkpoint(store, checkpoint, "checkpoint-secret")["valid"] is True
    assert verify_audit_checkpoint(store, checkpoint, "wrong-secret")["valid"] is False
    store.record_audit_event("request.replay", "user:alice", "request", "r1", "success")
    verification = verify_audit_checkpoint(store, checkpoint, "checkpoint-secret")
    assert verification["valid"] is True
    assert verification["current_records"] == 2
    store._conn.execute("UPDATE audit_log SET outcome = 'failure' WHERE audit_id = ?", (checkpoint["head_audit_id"],))
    store._conn.commit()
    assert verify_audit_checkpoint(store, checkpoint, "checkpoint-secret")["valid"] is False


def test_backup_catalog_and_inspection_are_read_only(tmp_path):
    store = Storage(str(tmp_path / "live.db"))
    bundle = create_backup(store, tmp_path / "backups")
    catalog = list_backups(tmp_path / "backups")
    assert catalog[0]["backup_id"]
    assert catalog[0]["valid"] is True
    preview = inspect_backup(bundle.manifest_path)
    assert preview["valid"] is True
    assert preview["schema_version"] == store.schema_version
    assert preview["integrity"] == "ok"
    assert preview["counts"]["requests"] == 0


def test_audit_actor_uses_configured_token_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOKRELAY_API_TOKEN", "shared-secret")
    store = Storage(str(tmp_path / "actor.db"))
    _storage.set(store)
    client = TestClient(create_app())
    response = client.put(
        "/api/settings/retention",
        json={"days": 90},
        headers={"Authorization": "Bearer shared-secret"},
    )
    assert response.status_code == 200
    event = store.list_audit_events(action="retention.update")[0]
    assert event["actor"] == actor_fingerprint("shared-secret")


def test_checkpoint_and_backup_catalog_apis(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOKRELAY_AUDIT_SIGNING_KEY", "checkpoint-secret")
    store = Storage(str(tmp_path / "api.db"))
    store.record_audit_event("api.event", "system", "request", "r1", "success")
    create_backup(store, tmp_path / "backups")
    _storage.set(store)
    client = TestClient(create_app())

    created = client.post("/api/audit/checkpoints")
    assert created.status_code == 201
    assert created.json()["algorithm"] == "HMAC-SHA256"
    verified = client.post("/api/audit/checkpoints/verify", json=created.json())
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    catalog = client.get("/api/data/backups")
    assert catalog.status_code == 200
    assert catalog.json()[0]["valid"] is True
    preview = client.get("/api/data/backups/inspect", params={"manifest_path": catalog.json()[0]["manifest_path"]})
    assert preview.status_code == 200
    assert preview.json()["integrity"] == "ok"


def test_checkpoint_requires_signing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HOOKRELAY_AUDIT_SIGNING_KEY", raising=False)
    store = Storage(str(tmp_path / "no-key.db"))
    _storage.set(store)
    response = TestClient(create_app()).post("/api/audit/checkpoints")
    assert response.status_code == 503
    assert response.json()["code"] == "signing_key_not_configured"
