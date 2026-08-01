# Hookrelay 1.3 Data Governance Requirements and Implementation

## Goal

Improve accountability and recovery confidence without storing raw credentials or exposing arbitrary filesystem paths.

## Requirements

### DG-01: Safe actor attribution

- **Priority:** Must have
- Protected actions shall record a stable actor identifier derived from the configured token.
- The identifier shall not contain the raw token.
- Equal tokens shall produce equal identifiers; different tokens shall produce different identifiers.
- Local open mode shall continue to use `local-session`.

### DG-02: Signed audit checkpoint

- **Priority:** Must have
- A checkpoint shall attest the current audit record count, chain-head audit ID, and chain-head hash.
- The checkpoint shall use HMAC-SHA256 with a dedicated environment-provided signing key.
- Creation shall fail closed when the key is absent.
- Verification shall detect an invalid signature, an invalid audit chain, or a changed historical chain head.
- Appending later valid audit records shall not invalidate an older checkpoint.

### DG-03: Backup catalog

- **Priority:** Should have
- List complete backup manifests newest first.
- Verify size, checksum, and SQLite integrity for every catalog entry.
- Expose schema/application versions and request, event, and audit counts.
- Inspection shall not modify or restore data.

### SEC-12: Backup path restriction

- **Priority:** Must have
- The inspection API shall only read JSON manifests located directly inside the configured Hookrelay backup directory.
- Parent traversal, alternate directories, and non-JSON paths shall be rejected.

## APIs

```text
POST /api/audit/checkpoints
POST /api/audit/checkpoints/verify
GET  /api/data/backups
GET  /api/data/backups/inspect?manifest_path=...
```

## Checkpoint contract

```json
{
  "checkpoint_version": 1,
  "algorithm": "HMAC-SHA256",
  "created_at": "RFC-3339 timestamp",
  "record_count": 42,
  "head_audit_id": "audit-id",
  "head_hash": "sha256-chain-head",
  "signature": "hmac-sha256"
}
```

The signature covers every field except the signature itself. A checkpoint should be exported to independent storage. Keeping both the database and checkpoint only on the same compromised host provides limited evidence value.

## Actor contract

Authenticated audit actors use:

```text
token:<first 16 hex characters of SHA-256("hookrelay-actor-v1:" + token)>
```

This is a pseudonymous identifier, not user identity or authorization. A future multi-user release should use immutable user or service-principal IDs.

## Backup inspection

Inspection verifies the manifest, file size, SHA-256 checksum, and SQLite integrity. It then opens the backup read-only in practice and counts known tables. It never performs restore or writes into the backup database.

## TDD validation

Six acceptance tests cover:

1. Stable non-reversible actor fingerprints
2. Signed checkpoint creation and verification
3. Wrong-key and audit-tampering detection
4. Later appended audit compatibility
5. Backup catalog and read-only inspection
6. Token-derived actor attribution through a protected API
7. Checkpoint and catalog APIs
8. Missing signing-key failure

Final regression result: **502 passed, 0 failed**.
