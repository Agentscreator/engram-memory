# Changelog

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
