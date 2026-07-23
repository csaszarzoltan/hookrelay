# Changelog

All notable changes to **hookrelay** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-07-23

### Features

- **Webhook relay** — forward webhooks from a public endpoint to localhost via WebSocket tunnel
- **CLI interface** — Typer-based CLI with commands: `forward`, `listen`, `history`, `replay`, `status`
- **Payload inspection** — real-time webhook display with method, headers, body, and query params
- **Request replay** — replay any received webhook with a single `hookrelay replay <id>` command
- **History browser** — search and browse recent webhooks with filters (channel, method, path)
- **Conditional forwarding** — filter by source IP, HTTP method, path pattern, headers, status code
- **SSRF protection** — IP range blocking (IPv4/IPv6), DNS anti-rebinding, protocol whitelist, port validation
- **SQLite persistence** — FTS5-powered search with automatic indexing and pagination
- **Status command** — health check and server info via `hookrelay status`
- **Listen mode** — live listening on a channel with streaming output

### Tests

- 157 tests across 7 test modules (CLI, relay, payload inspection, replay, filters, history, SSRF)
- Interface tests for all public function signatures
- Behavioral tests for error paths, edge cases, and happy paths
- SSRF module: 34 tests covering IP ranges, DNS resolution, protocol validation, and port checking
