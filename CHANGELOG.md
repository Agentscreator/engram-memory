# Changelog

## 0.1.1

### Bug Fixes

- Fixed `TypeError: Can't instantiate abstract class SQLiteStorage without an implementation for abstract methods 'gdpr_hard_erase_agent', 'gdpr_soft_erase_agent'` that crashed the MCP server on startup for users running stale cached installs via `uvx`.
- `engram serve` now emits a clear upgrade message instead of a raw traceback when the storage backend fails to instantiate.

## Unreleased

### Tool Surface Migrations

### MCP Tool Surface v1.0.0

Initial explicit versioning policy for Engram MCP tools.

- Current tool surface: `1.0.0`
- Supported major versions: `1`
- Deprecation lifecycle: announce -> warn -> remove
- Compatibility policy: current major plus previous major when available

### Migration Guide

- Prefer `winning_claim_id` over deprecated alias `winning_fact_id`.
- Clients should read `tool_surface_version`, `supported_tool_major_versions`, and `deprecation_policy` from `engram_status`.
