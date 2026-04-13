# CLAUDE.md — Engram Developer Guide

This file provides Claude Code with Engram-specific guidance for contributing to this codebase.

## Setup

```bash
uv sync            # Install all dependencies (uses uv, not pip)
```

## Running Tests

```bash
pytest tests/ -x                   # Run all, exit on first failure
pytest tests/test_engine.py -x     # Run a specific test file
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. Storage fixtures use `tmp_path` (no persistent test DB needed).

## Running the Server

```bash
python -m engram.cli serve --http
# HTTP:      http://localhost:7474
# Dashboard: http://localhost:7474/dashboard
```

## Module Map

All source lives under `src/engram/`.

| Module | Purpose |
|--------|---------|
| `server.py` | MCP server (FastMCP) with 15 tools — the I/O layer |
| `engine.py` | Core memory engine: commit pipeline, conflict detection (5-tier async), GDPR erasure, invite key rotation |
| `storage.py` | SQLite backend (async, WAL mode, FTS5) |
| `postgres_storage.py` | PostgreSQL backend (pgvector, tsvector, TIMESTAMPTZ) |
| `schema.py` | Database schema definitions and migrations (currently v10) |
| `cli.py` | CLI commands: `serve`, `verify`, `install`, `config`, `gdpr`, `completion`, `re-embed` |
| `rest.py` | REST API for non-MCP clients (`/api/commit`, `/api/query`, etc.) |
| `dashboard.py` | HTML dashboard with HTMX at `/dashboard` |
| `workspace.py` | Workspace configuration (team ID, db_url, schema) |
| `auth.py` | Authentication and workspace join flow |
| `embeddings.py` | Embedding generation for semantic search |
| `entities.py` | Entity extraction pipeline |
| `export.py` | Data export (JSON, Markdown snapshots) |
| `federation.py` | Replication journal for cross-workspace sync |
| `secrets.py` | Secret scanning (runs on every commit) |
| `suggester.py` | LLM-powered conflict resolution suggestions |

## Schema Version Invariant

- Database schema version is tracked in `src/engram/schema.py` (currently **v11**)
- When adding new tables or columns, increment `SCHEMA_VERSION` and add a migration entry
- Document the migration path in `docs/MIGRATION_SCHEMA.md`

## Before Editing Engine Code

1. **Read `docs/IMPLEMENTATION.md`** — Contains architecture decisions, the 5-tier detection design, and the bitemporal data model
2. **Run existing tests** — `pytest tests/ -x` to ensure nothing breaks
3. **Check `docs/MIGRATION_SCHEMA.md`** — If changes affect the database, document the migration path

## MCP Tools (15 total)

**Onboarding:**
- `engram_status` — Check workspace state, guide setup
- `engram_init` — Create new workspace (founder)
- `engram_join` — Join workspace via invite key
- `engram_reset_invite_key` — Rotate invite key (creator only)

**Core operations:**
- `engram_commit` — Write a verified fact (secret scan → dedup → entity extract → insert)
- `engram_query` — Read team knowledge (BM25 ranking, temporal filtering)
- `engram_conflicts` — Surface contradictions, grouped by severity
- `engram_resolve` — Settle a disagreement

**Extended:**
- `engram_batch_commit` — Write multiple facts atomically
- `engram_promote` — Graduate ephemeral fact to durable memory
- `engram_feedback` — Submit NLI calibration feedback
- `engram_timeline` — Historical view of fact versions
- `engram_agents` — List registered agents and stats
- `engram_lineage` — All versions of a fact family
- `engram_expiring` — Facts with TTL approaching expiry
- `engram_bulk_dismiss` — Batch dismiss conflicts
- `engram_export` — Export data (JSON, Markdown)

**Compliance:**
- `engram_gdpr_erase` — GDPR right-to-erasure for an agent (founder only; soft or hard mode)
- `engram_reset_invite_key` — now accepts `grace_minutes` (default 15) and `reason` params; fires `invite_key.rotated` webhook event and writes audit log entry

## Rules

### Code Style
- Use Ruff for formatting: `uv run ruff format`
- Check linting: `uv run ruff check`
- All new code must pass ruff checks before committing

### Testing
- Run tests before every commit: `uv run pytest tests/ -x`
- Write tests for new features (location: tests/)
- One test file per module: test_engine.py, test_storage.py, etc.

### Commit Messages
- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`
- Keep PRs focused — one feature/fix per PR
- Include issue number in commit if applicable

## Key Documentation

- `CONTRIBUTING.md` — Contribution workflow and PR guidelines
- `AGENTS.md` — Universal AI assistant guidance
- `HIRING.md` — Paid contract opportunities ($125-185/hour)
- `docs/IMPLEMENTATION.md` — Architecture and phase delivery plan
- `docs/MIGRATION_SCHEMA.md` — Database migration guide (current: v11)
- `docs/PRIVACY_ARCHITECTURE.md` — GDPR erasure, anonymous mode, zero-knowledge design, invite key lifecycle
