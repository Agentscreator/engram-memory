# API Versioning

Engram versions its MCP tool surface separately from the Python package
version and database schema version.

## Tool Surface Version

The current MCP tool surface is `1.0.0`.

Agents and clients can discover this by calling `engram_status`, which returns:

- `tool_surface_version`
- `supported_tool_major_versions`
- `deprecation_policy`

## Semantic Versioning

Patch releases may clarify tool descriptions, improve validation, or add
response metadata without removing existing fields.

Minor releases may add optional parameters, optional response fields, or new
tools.

Major releases are required for removing tools, removing parameters, renaming
parameters, changing required parameters, or removing response fields.

## Deprecation Lifecycle

Engram uses an announce -> warn -> remove lifecycle.

1. Announce the upcoming change in `CHANGELOG.md`.
2. Warn by accepting the deprecated form and returning `deprecation_warnings`.
3. Remove only in the next unsupported major version.

## Compatibility Policy

Engram supports the current major MCP tool surface and the previous major
version when available.

## Migration Guides

Every tool-surface migration must be documented in `CHANGELOG.md` with:

- old parameter or tool name
- replacement
- version deprecated
- version removed
- before and after examples
