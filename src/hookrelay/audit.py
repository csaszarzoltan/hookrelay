"""Audit actor identifiers and externally verifiable checkpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hookrelay.storage import Storage


def actor_fingerprint(token: str) -> str:
    """Return a stable, non-reversible short identifier for an access token."""
    digest = hashlib.sha256(("hookrelay-actor-v1:" + token).encode()).hexdigest()
    return "token:" + digest[:16]


def _checkpoint_payload(checkpoint: dict[str, Any]) -> bytes:
    fields = {
        "checkpoint_version": checkpoint["checkpoint_version"],
        "algorithm": checkpoint["algorithm"],
        "created_at": checkpoint["created_at"],
        "record_count": checkpoint["record_count"],
        "head_audit_id": checkpoint["head_audit_id"],
        "head_hash": checkpoint["head_hash"],
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()


def create_audit_checkpoint(storage: Storage, signing_key: str) -> dict[str, Any]:
    """Create an HMAC checkpoint for the current verified audit-chain head."""
    if not signing_key:
        raise ValueError("signing key must not be empty")
    chain = storage.verify_audit_chain()
    if not chain["valid"]:
        raise RuntimeError("cannot checkpoint an invalid audit chain")
    row = storage._conn.execute(
        "SELECT audit_id, record_hash FROM audit_log ORDER BY created_at DESC, audit_id DESC LIMIT 1"
    ).fetchone()
    checkpoint = {
        "checkpoint_version": 1,
        "algorithm": "HMAC-SHA256",
        "created_at": datetime.now(UTC).isoformat(),
        "record_count": chain["checked"],
        "head_audit_id": row["audit_id"] if row else None,
        "head_hash": row["record_hash"] if row else "",
    }
    checkpoint["signature"] = hmac.new(
        signing_key.encode(), _checkpoint_payload(checkpoint), hashlib.sha256
    ).hexdigest()
    return checkpoint


def verify_audit_checkpoint(
    storage: Storage,
    checkpoint: dict[str, Any],
    signing_key: str,
) -> dict[str, Any]:
    """Verify checkpoint signature and the historical audit head it attests."""
    try:
        expected = hmac.new(
            signing_key.encode(), _checkpoint_payload(checkpoint), hashlib.sha256
        ).hexdigest()
    except (KeyError, TypeError, AttributeError):
        return {"valid": False, "reason": "invalid_checkpoint"}
    if not hmac.compare_digest(str(checkpoint.get("signature", "")), expected):
        return {"valid": False, "reason": "invalid_signature"}
    chain = storage.verify_audit_chain()
    if not chain["valid"]:
        return {
            "valid": False,
            "reason": "audit_chain_invalid",
            "broken_audit_id": chain["broken_audit_id"],
        }
    count = storage._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    if checkpoint["record_count"] == 0:
        historical_valid = checkpoint["head_audit_id"] is None and checkpoint["head_hash"] == ""
    else:
        row = storage._conn.execute(
            "SELECT record_hash FROM audit_log WHERE audit_id = ?",
            (checkpoint["head_audit_id"],),
        ).fetchone()
        historical_valid = bool(row and row["record_hash"] == checkpoint["head_hash"])
    return {
        "valid": historical_valid,
        "reason": None if historical_valid else "checkpoint_head_mismatch",
        "checkpoint_records": checkpoint["record_count"],
        "current_records": count,
    }
