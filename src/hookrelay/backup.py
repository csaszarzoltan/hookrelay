"""Consistent SQLite backup and checksum-verified restore utilities."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

if TYPE_CHECKING:
    from hookrelay.storage import Storage


class BackupIntegrityError(RuntimeError):
    """Raised when a backup does not match its signed manifest metadata."""


@dataclass(frozen=True, slots=True)
class BackupBundle:
    database_path: Path
    manifest_path: Path
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _derive_encryption_key(secret: str, salt: bytes, iterations: int) -> bytes:
    if not secret:
        raise ValueError("encryption key must not be empty")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    ).derive(secret.encode("utf-8"))


def _decrypt_to_path(
    source: Path,
    manifest: dict,
    destination: Path,
    encryption_key: str | None,
) -> None:
    if not encryption_key:
        raise BackupIntegrityError("backup encryption key is required")
    encryption = manifest.get("encryption", {})
    try:
        salt = base64.b64decode(encryption["salt_b64"])
        nonce = base64.b64decode(encryption["nonce_b64"])
        iterations = int(encryption["kdf_iterations"])
        key = _derive_encryption_key(encryption_key, salt, iterations)
        plaintext = AESGCM(key).decrypt(
            nonce,
            source.read_bytes(),
            manifest["backup_id"].encode("utf-8"),
        )
    except (InvalidTag, KeyError, ValueError, TypeError) as exc:
        raise BackupIntegrityError("could not decrypt backup with the supplied encryption key") from exc
    destination.write_bytes(plaintext)


def create_backup(
    storage: Storage,
    destination: str | Path,
    encryption_key: str | None = None,
) -> BackupBundle:
    """Create a consistent backup, optionally encrypted with AES-256-GCM."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    backup_id = f"hookrelay-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    encrypted = bool(encryption_key)
    final_path = destination / f"{backup_id}.db.enc" if encrypted else destination / f"{backup_id}.db"
    temporary_plain = destination / f".{backup_id}.plain.tmp"
    try:
        with sqlite3.connect(temporary_plain) as target:
            storage._conn.backup(target)
        plain_size = temporary_plain.stat().st_size
        encryption_metadata = None
        if encrypted:
            salt = os.urandom(16)
            nonce = os.urandom(12)
            iterations = 600_000
            key = _derive_encryption_key(encryption_key or "", salt, iterations)
            ciphertext = AESGCM(key).encrypt(
                nonce,
                temporary_plain.read_bytes(),
                backup_id.encode("utf-8"),
            )
            final_path.write_bytes(ciphertext)
            encryption_metadata = {
                "algorithm": "AES-256-GCM",
                "kdf": "PBKDF2-HMAC-SHA256",
                "kdf_iterations": iterations,
                "salt_b64": base64.b64encode(salt).decode("ascii"),
                "nonce_b64": base64.b64encode(nonce).decode("ascii"),
                "associated_data": "backup_id",
            }
        else:
            temporary_plain.replace(final_path)
        checksum = _sha256(final_path)
        manifest_path = destination / f"{backup_id}.json"
        manifest = {
            "backup_format_version": 2 if encrypted else 1,
            "backup_id": backup_id,
            "created_at": datetime.now(UTC).isoformat(),
            "database_file": final_path.name,
            "database_size_bytes": final_path.stat().st_size,
            "plaintext_size_bytes": plain_size,
            "sha256": checksum,
            "schema_version": storage.schema_version,
            "application_version": __import__("hookrelay").__version__,
            "encrypted": encrypted,
        }
        if encryption_metadata:
            manifest["encryption"] = encryption_metadata
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return BackupBundle(final_path, manifest_path, checksum)
    finally:
        temporary_plain.unlink(missing_ok=True)


def restore_backup(
    manifest_path: str | Path,
    destination: str | Path,
    encryption_key: str | None = None,
) -> Path:
    """Verify, decrypt when needed, and atomically restore a backup."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("backup_format_version") not in {1, 2}:
        raise BackupIntegrityError("unsupported backup manifest version")
    source = manifest_path.parent / manifest["database_file"]
    if not source.is_file():
        raise BackupIntegrityError("backup database file is missing")
    if source.stat().st_size != manifest.get("database_size_bytes"):
        raise BackupIntegrityError("backup size does not match its manifest")
    if _sha256(source) != manifest.get("sha256"):
        raise BackupIntegrityError("backup checksum does not match its manifest")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restore.tmp")
    temporary.unlink(missing_ok=True)
    if manifest.get("encrypted"):
        _decrypt_to_path(source, manifest, temporary, encryption_key)
    else:
        shutil.copy2(source, temporary)
    check = sqlite3.connect(temporary)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupIntegrityError(f"SQLite integrity check failed: {result}")
    finally:
        check.close()
    if destination.exists():
        rollback = destination.with_suffix(destination.suffix + ".pre_restore")
        shutil.copy2(destination, rollback)
    temporary.replace(destination)
    return destination


def prune_backups(destination: str | Path, keep_last: int) -> dict[str, int]:
    """Keep the newest complete backup bundles and remove older pairs."""
    if keep_last < 1:
        raise ValueError("keep_last must be at least 1")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    bundles: list[tuple[str, Path, Path]] = []
    for manifest_path in destination.glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            database_path = destination / manifest["database_file"]
            created_at = str(manifest["created_at"])
        except (KeyError, json.JSONDecodeError, OSError):
            continue
        if database_path.is_file():
            bundles.append((created_at, manifest_path, database_path))
    bundles.sort(key=lambda item: item[0], reverse=True)
    deleted = 0
    for _, manifest_path, database_path in bundles[keep_last:]:
        manifest_path.unlink(missing_ok=True)
        database_path.unlink(missing_ok=True)
        deleted += 1
    return {
        "deleted_bundles": deleted,
        "remaining_bundles": max(0, len(bundles) - deleted),
    }


def inspect_backup(
    manifest_path: str | Path,
    encryption_key: str | None = None,
) -> dict[str, object]:
    """Verify and inspect a backup without restoring it."""
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        database_path = manifest_path.parent / manifest["database_file"]
        checksum_valid = (
            database_path.is_file()
            and database_path.stat().st_size == manifest["database_size_bytes"]
            and _sha256(database_path) == manifest["sha256"]
        )
    except (OSError, KeyError, json.JSONDecodeError):
        return {"valid": False, "manifest_path": str(manifest_path)}
    encrypted = bool(manifest.get("encrypted"))
    integrity = "encrypted" if encrypted else "not_checked"
    content_access = "key_required" if encrypted and not encryption_key else "verified"
    counts: dict[str, int | None] = {
        "requests": None if encrypted and not encryption_key else 0,
        "events": None if encrypted and not encryption_key else 0,
        "audit_records": None if encrypted and not encryption_key else 0,
    }
    inspection_path = database_path
    temporary_path: Path | None = None
    try:
        if checksum_valid and encrypted and encryption_key:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
                temporary_path = Path(handle.name)
            try:
                _decrypt_to_path(database_path, manifest, temporary_path, encryption_key)
            except BackupIntegrityError:
                content_access = "invalid_key"
                return {
                    **manifest,
                    "manifest_path": str(manifest_path.resolve()),
                    "database_path": str(database_path.resolve()),
                    "checksum_valid": checksum_valid,
                    "integrity": "not_checked",
                    "content_access": content_access,
                    "counts": counts,
                    "valid": False,
                }
            inspection_path = temporary_path
        if checksum_valid and (not encrypted or encryption_key):
            connection = sqlite3.connect(inspection_path)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                mapping = {
                    "requests": "webhooks",
                    "events": "event_log",
                    "audit_records": "audit_log",
                }
                for key, table in mapping.items():
                    if table in tables:
                        counts[key] = connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
            finally:
                connection.close()
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
    valid = checksum_valid and (
        (encrypted and not encryption_key) or integrity == "ok"
    )
    return {
        **manifest,
        "manifest_path": str(manifest_path.resolve()),
        "database_path": str(database_path.resolve()),
        "checksum_valid": checksum_valid,
        "integrity": integrity,
        "content_access": content_access,
        "counts": counts,
        "valid": valid,
    }


def list_backups(destination: str | Path) -> list[dict[str, object]]:
    """Return newest-first verified backup catalog entries."""
    destination = Path(destination)
    if not destination.exists():
        return []
    items = [inspect_backup(path) for path in destination.glob("*.json")]
    return sorted(items, key=lambda item: str(item.get("created_at", "")), reverse=True)
