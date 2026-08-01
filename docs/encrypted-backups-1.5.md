# Hookrelay 1.5 Encrypted Backup Requirements and Implementation

## Goal

Protect webhook payloads, headers, response diagnostics, audit records, and configuration contained in backup database files when backup storage is lost or copied.

## Requirements

### SEC-13: Authenticated backup encryption

- **Priority:** Must have
- Backup encryption shall use AES-256-GCM.
- Every backup shall use a fresh random 96-bit nonce.
- The backup ID shall be authenticated as associated data.
- Authentication failure shall prevent restore and inspection.

### SEC-14: Passphrase-based key derivation

- **Priority:** Must have
- A textual environment secret shall be transformed into a 256-bit key with PBKDF2-HMAC-SHA256.
- Every backup shall use a fresh random 128-bit salt.
- The KDF iteration count shall be recorded in the manifest and default to 600,000.
- The raw encryption secret shall never be persisted.

### FR-18: Encryption-aware backup lifecycle

- **Priority:** Must have
- API, dashboard, scheduled, and CLI backups shall encrypt when `HOOKRELAY_BACKUP_ENCRYPTION_KEY` is configured.
- Restore shall require the matching key.
- Wrong and missing keys shall fail before replacing the destination database.
- Temporary plaintext files shall be deleted after encryption, decryption, or inspection.

### FR-19: Locked backup catalog

- **Priority:** Should have
- The catalog shall identify encrypted bundles.
- Without a key, checksum and encrypted-file integrity metadata shall remain visible.
- Content counts shall be unavailable and labeled as key-required.
- With a configured key, inspection shall decrypt to a temporary file, run SQLite integrity checks, calculate counts, then remove the temporary file.

### COMP-03: Plaintext backward compatibility

- **Priority:** Must have
- Existing format-v1 plaintext bundles shall remain restorable and inspectable.
- Encryption shall be opt-in through the environment variable.
- Retention and deletion shall handle `.db` and `.db.enc` files through manifest pairing.

## Format v2

The readable JSON manifest contains:

```json
{
  "backup_format_version": 2,
  "database_file": "hookrelay-...db.enc",
  "encrypted": true,
  "encryption": {
    "algorithm": "AES-256-GCM",
    "kdf": "PBKDF2-HMAC-SHA256",
    "kdf_iterations": 600000,
    "salt_b64": "...",
    "nonce_b64": "...",
    "associated_data": "backup_id"
  }
}
```

The manifest checksum covers the encrypted file. AES-GCM separately authenticates the decrypted bytes and backup ID.

## Security considerations

- The encryption key should be a long random secret, not a human password where avoidable.
- Store it in a secrets manager or protected service environment.
- Do not store it beside the backup files.
- Key loss is permanent data loss for encrypted bundles.
- Key rotation creates new backups with the new key but does not re-encrypt old bundles.
- The readable manifest exposes timestamps, versions, file size, and encryption parameters, but not webhook payload content.

## TDD validation

Six acceptance tests cover:

1. No SQLite header or known payload plaintext in encrypted output
2. Correct-key restore
3. Missing-key and wrong-key rejection
4. Locked and unlocked inspection behavior
5. API encryption through environment configuration
6. Backup center encrypted labeling
7. Plaintext format-v1 compatibility

Final regression result: **514 passed, 0 failed**.
