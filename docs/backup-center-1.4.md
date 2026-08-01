# Hookrelay 1.4 Backup Center Requirements and Implementation

## Goal

Turn backup recovery points into a visible, understandable, and safely manageable daily workflow without exposing a dangerous in-process restore action.

## Requirements

### UX-14: Backup center navigation

- **Priority:** Must have
- Primary dashboard pages shall expose a Backups navigation item.
- The Backup center shall summarize total, verified, invalid, and total-byte metrics.
- The empty state shall explain why backups matter and provide a direct creation action.

### FR-15: Verified recovery-point cards

- **Priority:** Must have
- Each bundle shall display creation time, application version, schema version, byte size, request count, SQLite integrity, and checksum state.
- Valid and invalid bundles shall be visually and textually distinct.
- Status shall not rely on color alone.

### FR-16: Read-only restore preview

- **Priority:** Must have
- Inspection shall verify manifest, byte size, SHA-256, and SQLite integrity.
- Inspection shall report request, event, and audit counts.
- Inspection shall not restore, modify, or attach the backup to the live database.
- Results shall appear inline without navigating away from the catalog.

### FR-17: Safe backup deletion

- **Priority:** Must have
- Deletion shall require `confirm=true` and a browser confirmation interaction.
- Deletion shall remove the manifest and its paired database file.
- Deletion shall be restricted to the configured managed backup directory.
- Successful deletion shall append `data.backup.delete` with the authenticated pseudonymous actor.

### BR-05: Restore remains an offline operation

- **Priority:** Must have
- The web application shall not replace its active SQLite database.
- Operators shall use `hookrelay data restore` while the server is stopped.
- The Backup center may inspect recovery points but shall not provide deceptive or unsafe online restore controls.

## APIs

```text
GET    /api/data/backups/summary
DELETE /api/data/backups?manifest_path=...&confirm=true
```

Existing APIs used by the center:

```text
GET  /api/data/backups
GET  /api/data/backups/inspect
POST /api/data/backups/run
```

## Security decisions

- Paths are canonicalized and must point directly into the managed backup directory.
- Only `.json` manifests are accepted as bundle entry points.
- The paired database path from the manifest is canonicalized and rechecked before deletion.
- Arbitrary filesystem browsing is not exposed.
- Invalid manifests cannot be deleted through the paired-file path logic until corrected or removed by an operator with filesystem access.

## UX behavior

- Create backup announces progress and completion through an `aria-live` region.
- Inspection expands a formatted JSON recovery preview inside the selected card.
- Deletion requires confirmation, removes only the selected card after success, and announces completion.
- Invalid bundles are visible rather than silently ignored, so operators can investigate retention or filesystem issues.

## TDD validation

Six acceptance tests cover:

1. Verified bundle rendering and request count
2. Actionable empty state
3. Catalog summary metrics
4. Confirmation-protected pair deletion
5. Audit recording for deletion
6. Managed-directory escape rejection
7. Backup navigation on primary pages

Final regression result: **508 passed, 0 failed**.
