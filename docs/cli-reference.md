# CLI Reference

## `hookrelay forward`

Forward webhooks from a channel to a local target URL.

```bash
hookrelay forward <channel> <target> [--server URL] [--timeout SECONDS]
```

**Arguments:**

| Argument | Description |
|---|---|
| `channel` | Channel name to listen on (required) |
| `target` | Local URL to forward webhooks to (required) |

**Options:**

| Option | Default | Description |
|---|---|---|
| `--server`, `-s` | `http://localhost:8000` | Relay server URL |
| `--timeout`, `-t` | `30.0` | Connection timeout in seconds |

**Example:**
```bash
hookrelay forward stripe-events http://localhost:3000/webhooks/stripe
```

## `hookrelay listen`

Listen for incoming webhooks on a channel and print them to stdout.

```bash
hookrelay listen <channel> [--server URL]
```

**Example:**
```bash
hookrelay listen mychannel
```

## `hookrelay history`

Browse recent webhook requests.

```bash
hookrelay history [--channel CHANNEL] [--limit N] [--method METHOD] [--path PATH] [--id REQUEST_ID]
```

**Options:**

| Option | Description |
|---|---|
| `--channel`, `-c` | Filter by channel name |
| `--limit`, `-n` | Max results (default: 20) |
| `--method`, `-m` | Filter by HTTP method (GET, POST, etc.) |
| `--path`, `-p` | Filter by path pattern |
| `--id` | View full details of a specific request |

**Example:**
```bash
hookrelay history
hookrelay history --method POST --limit 50
hookrelay history --id abc123def456
```

## `hookrelay replay`

Replay a stored webhook request.

```bash
hookrelay replay <request_id> [--target URL] [--server URL]
```

**Arguments:**

| Argument | Description |
|---|---|
| `request_id` | The ID of the request to replay (required) |

**Options:**

| Option | Description |
|---|---|
| `--target`, `-t` | Override the target URL for this replay |
| `--server`, `-s` | `http://localhost:8000` | Relay server URL |

**Example:**
```bash
hookrelay replay abc123
hookrelay replay abc123 --target http://localhost:5000/debug
```

## `hookrelay status`

Check the relay server health and version.

```bash
hookrelay status [--server URL]
```

**Example:**
```bash
hookrelay status
hookrelay status --server https://relay.example.com
```
