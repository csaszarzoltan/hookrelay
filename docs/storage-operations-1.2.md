# Hookrelay 1.2 Storage Operations Requirements and Implementation

## Goal

Make backup protection and storage health visible and operable in daily use, rather than requiring manual database inspection or ad hoc scripts.

## Requirements

### DR-12: Storage health visibility

- **Priority:** Must have
- Report SQLite integrity, schema version, database path and size, WAL size, journal mode, major table counts, and audit-chain validity.
- Expose the same information through a protected API and the Settings interface.
- Do not expose request bodies or secrets in health output.

### DR-13: Persistent backup policy

- **Priority:** Must have
- Persist whether periodic backups are enabled.
- Accept an interval from 1 to 720 hours.
- Accept a retained backup count from 1 to 365.
- Default to disabled, 24-hour interval, and seven retained bundles.

### DR-14: Due detection and execution

- **Priority:** Must have
- A backup is due when policy is enabled and no previous backup exists, or when the configured interval elapsed.
- A forced run shall create a backup regardless of due state.
- A non-due non-forced run shall return a clear `not_due` result.
- Successful runs shall persist completion time and append an audit record.

### DR-15: Complete-bundle pruning

- **Priority:** Must have
- Retention shall operate on complete manifest/database pairs.
- Incomplete or malformed files shall not be counted as valid bundles.
- The newest configured number of complete bundles shall remain.
- Both files of an expired bundle shall be deleted together.

### UX-13: Operable Settings workflow

- **Priority:** Should have
- Show storage health in compact cards.
- Provide labeled enablement, interval, and retained-count controls.
- Provide Save policy and Run backup now actions.
- Announce progress, errors, completion, checksum, and last-completed time through an accessible status region.

## APIs

```text
GET  /api/data/health
GET  /api/data/backup-policy
PUT  /api/data/backup-policy
POST /api/data/backups/run
```

The APIs remain covered by Hookrelay's optional token authentication middleware.

## Scheduling model

Hookrelay stores and evaluates the schedule but does not start a hidden background thread. An external scheduler, service manager, or future dedicated worker should call `POST /api/data/backups/run` without `force` at the desired cadence. The method returns `409` with `status: not_due` when no work is required.

This model avoids duplicate in-process jobs under reloads or future multi-worker deployments.

## Testing

Six TDD-first acceptance tests cover:

1. Complete-bundle pruning
2. Storage-health diagnostics
3. Backup-policy persistence
4. Due-state calculation
5. Scheduled backup execution and retention
6. Health and backup-policy APIs
7. Settings dashboard controls

Final result: **496 passed, 0 failed**.
