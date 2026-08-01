# Hookrelay 1.1 Data Resilience Requirements and Implementation

## Goal

Protect developer request history and operational evidence from failed upgrades, corrupted backups, accidental restore mistakes, and undetected audit-log modification.

## Requirements

### DR-07: Consistent backup

- **Priority:** Must have
- A backup shall represent one transactionally consistent SQLite snapshot.
- A manifest shall include format version, backup ID, creation time, database filename, byte size, SHA-256, schema version, and application version.
- Backup creation shall not require copying SQLite WAL files manually.

### DR-08: Verified atomic restore

- **Priority:** Must have
- Restore shall reject missing, size-mismatched, checksum-mismatched, unsupported, or SQLite-corrupt backups.
- Restore shall copy into a temporary file and atomically replace the destination.
- An existing destination shall first be preserved as `.pre_restore`.
- Server processes shall be stopped before CLI restore.

### DR-09: Tamper-evident audit chain

- **Priority:** Must have
- Each audit record shall contain the previous record hash and its own deterministic SHA-256 hash.
- Hash input shall include identity, action, actor, object, outcome, correlation ID, redacted details, timestamp, and previous hash.
- Verification shall identify the first broken audit ID.
- Pre-1.1 audit rows shall be backfilled without changing their business content.

### DR-10: Audit retention

- **Priority:** Should have
- Audit records older than a positive retention period may be intentionally purged.
- After purge, the remaining records shall be re-rooted into a valid hash chain.
- The purge API shall validate a 1 to 3650 day period.

### DR-11: Administration interfaces

- **Priority:** Should have
- Protected APIs shall create backups, verify the audit chain, and purge old audit records.
- CLI commands shall support backup, restore, and audit verification without requiring the web server.

## Implementation

### New module

- `hookrelay/backup.py`: online SQLite backup, manifest creation, checksum verification, SQLite integrity check, atomic restore, and rollback copy.

### Migration

- Schema version 4 adds `previous_hash` and `record_hash` to `audit_log` and indexes record hashes.

### APIs

```text
POST /api/data/backups
GET  /api/audit/verify
POST /api/audit/purge
```

### CLI

```text
hookrelay data backup
hookrelay data restore
hookrelay data verify-audit
```

## Security and privacy decisions

- Backups contain the same sensitive payload data as the live database and must be protected with filesystem permissions and encrypted storage where appropriate.
- The checksum detects accidental or malicious changes but is not a digital signature. A future release may add signing keys or external attestations.
- Restore verification happens before destination replacement.
- Raw tokens remain excluded from audit details by recursive redaction.

## TDD validation

Seven tests were authored before implementation and cover:

1. Backup/restore round trip
2. Manifest and checksum correctness
3. Tampered backup rejection
4. Audit tamper detection
5. Audit retention and chain rebuilding
6. Backup and audit administration APIs
7. Data CLI command registration
8. Future-schema rejection without modification

Final regression result: **490 passed, 0 failed**.
