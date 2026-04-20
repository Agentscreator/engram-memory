# ARCHITECTURE.md — Engram Module Map for Contributors

> **Read this first.** This is the map a new contributor — human or agent — should
> read before touching anything in `src/engram/`. For design rationale, see
> `docs/IMPLEMENTATION.md`. For schema migrations, see `docs/MIGRATION_SCHEMA.md`.

## Data Flow

```
  Agent (Claude, Cursor, VS Code Copilot, …)
    │
    │  MCP (stdio or Streamable HTTP)
    ▼
 server.py ──────────────────────────────────────────────┐
    │         REST (JSON)          HTML (HTMX)           │
    │            │                    │                   │
    │        rest.py            dashboard.py              │
    │            │                    │                   │
    │            └────────┬───────────┘                   │
    │                     ▼                               │
    │               engine.py                             │
    │          ┌───────┬──┴──┬──────────┐                 │
    │          ▼       ▼     ▼          ▼                 │
    │    embeddings  entities secrets  suggester.py       │
    │       .py       .py     .py   (async, optional)    │
    │                     │                               │
    │                     ▼                               │
    │    storage.py (BaseStorage ABC)                     │
    │       ├── SQLiteStorage          (local mode)       │
    │       └── postgres_storage.py    (team mode)        │
    │                     │                               │
    │               schema.py  (DDL + migrations)         │
    │                                                     │
    │  Cross-cutting:                                     │
    │    workspace.py  auth.py  federation.py  export.py  │
    └─────────────────────────────────────────────────────┘

  CLI entry point: cli.py  (engram serve / install / verify)
```

## Module Map

Each section states what the module does, its key public interface, and what it
**must not** do.

---

### Conflict Detection — Two Implementations

Engram has two conflict detection mechanisms depending on deployment mode:

- **Local server** (`src/engram/engine.py`): A four-tier deterministic + ML pipeline
  (entity exact-match → NLI cross-encoder → numeric rules → LLM escalation). Runs
  entirely on-device with no external API dependencies. See `docs/IMPLEMENTATION.md`
  § Phase 3 for the full design.

- **Hosted service** (`api/mcp.py`): A narrative coherence detective that reads the
  workspace's entire commit history as a chronological story and identifies where a
  new agent would get confused. Uses `gpt-4o-mini` with a probabilistic forgetting
  curve to focus on signal over noise. See **`docs/CONFLICT_DETECTIVE.md`** for the
  full design.

---

### engine.py — Core Orchestrator

`EngramEngine` owns the entire commit/query/conflict-detection pipeline. On
commit it runs a 14-step pipeline: validate, strip PII (anonymous mode), scan
for secrets, deduplicate, generate embeddings, extract entities and keywords,
register the agent, determine lineage, insert the fact, detect conflicts, and
check corroboration. On query it fuses embedding similarity and FTS via
Reciprocal Rank Fusion with recency decay, agent trust, fact-type weighting,
and corroboration boosts. It also runs six background async workers (conflict
detection, TTL expiry, importance decay, NLI calibration, LLM suggestion
queuing, and 72-hour auto-escalation).

**Public interface:** `commit()`, `query()`, `promote()`, `get_conflicts()`,
`resolve()`, `batch_commit()`, `get_stats()`, `record_feedback()`,
`get_timeline()`, `get_agents()`, `get_fact()`, `list_facts()`,
`export_workspace()`, `get_lineage()`, `get_expiring_facts()`,
`bulk_dismiss()`, `gdpr_erase_agent()`.

**Must not:** access the database directly — all persistence goes through a
`BaseStorage` implementation. Must not import or depend on any transport layer
(`server.py`, `rest.py`, `dashboard.py`).

---

### server.py — MCP Tool Surface

Defines 17 MCP tools via FastMCP. Each tool is a thin adapter: validate input,
call the corresponding `EngramEngine` method, format the response. Behavioral
guidance (tool descriptions that steer agent behavior) lives here.

**Public interface:** The MCP tool set — `engram_status`, `engram_init`,
`engram_join`, `engram_reset_invite_key`, `engram_commit`, `engram_query`,
`engram_conflicts`, `engram_resolve`, `engram_promote`, `engram_gdpr_erase`,
and others.

**Must not:** contain business logic. No conflict detection, no query scoring,
no direct database calls. If a tool needs new behavior, add it to `engine.py`
and call it from here.

---

### storage.py — Local Storage (SQLite)

Defines `BaseStorage`, the abstract interface (~45 methods) that all storage
backends implement. Also provides `SQLiteStorage`, the local-mode
implementation using aiosqlite with WAL mode, FTS5 full-text search, and BLOB
embedding storage.

**Public interface:** `BaseStorage` (ABC), `SQLiteStorage`. Key methods:
`insert_fact()`, `query_facts()`, `get_conflicts()`, `resolve_conflict()`,
`upsert_agent()`, `get_workspace_stats()`, `gdpr_soft_erase_agent()`,
`gdpr_hard_erase_agent()`, plus ~40 more CRUD operations.

**Must not:** contain business logic or orchestration. Storage executes queries
and returns rows — it does not decide *what* to store or *when* to detect
conflicts. That is `engine.py`'s job.

---

### postgres_storage.py — Team Storage (PostgreSQL)

`PostgresStorage` implements `BaseStorage` for team deployments. Uses asyncpg
connection pooling (min=2, max=10), pgvector for embedding similarity search
(IVFFlat index), tsvector generated columns for GIN-indexed full-text search,
JSONB for entities, and schema isolation (`SET search_path`) for multi-tenancy.

**Public interface:** `PostgresStorage` (same `BaseStorage` contract).

**Must not:** diverge from the `BaseStorage` interface. Any new storage method
must be added to `BaseStorage` first, then implemented in both backends.

---

### schema.py — DDL and Migrations

Contains all database DDL (`SCHEMA_SQL` for SQLite, `POSTGRES_SCHEMA_SQL` for
PostgreSQL) and incremental migration definitions (v2 through v10). Tables:
`workspaces`, `facts`, `conflicts`, `invite_keys`, `agents`, `audit_log`,
`scopes`, `webhooks`, plus FTS5 virtual tables and triggers (including the
`facts_au` update trigger added in v10 for GDPR hard-erase FTS consistency).

**Public interface:** `SCHEMA_SQL`, `POSTGRES_SCHEMA_SQL`, `MIGRATIONS`,
`SCHEMA_VERSION`.

**Must not:** execute migrations itself — storage backends read from here and
apply. When adding tables or columns, increment `SCHEMA_VERSION` and document
the migration in `docs/MIGRATION_SCHEMA.md`.

---

### entities.py — Entity Extraction

Regex-based entity extraction and keyword generation for Tier 0/2 conflict
detection and FTS enrichment. Extracts five entity types: numeric (with units),
config keys (ALL_CAPS identifiers), service names, technology names, and version
strings. Also provides stop-word filtered keyword extraction.

**Public interface:** `extract_entities(text) -> list[dict]`,
`extract_keywords(text) -> list[str]`.

**Must not:** touch the database or import engine/storage. It is a pure
function module — text in, structured data out.

---

### embeddings.py — Vector Encoding

Lazy-loads the `all-MiniLM-L6-v2` sentence-transformer model and produces
384-dimensional embeddings for semantic search and NLI candidate sourcing.

**Public interface:** `encode(text) -> list[float]`.

**Must not:** manage model lifecycle beyond lazy loading. Must not query the
database or make network calls. It is a pure function: text in, vector out.

---

### secrets.py — Pre-commit Secret Scanner

Deterministic regex scanner with 11 patterns (AWS keys, JWT tokens, SSH private
keys, database connection strings, etc.). Runs in <1ms. Called by the engine's
commit pipeline to reject facts that contain secrets before they reach storage.

**Public interface:** `scan_for_secrets(text) -> list[dict]`.

**Must not:** store, log, or transmit the secrets it detects. Must not make
network calls. It is a pure function: text in, match list out.

---

### workspace.py — Workspace Config and Invite Keys

Manages workspace identity (`WorkspaceConfig` dataclass: engram_id, db_url,
schema, privacy settings) persisted to `~/.engram/workspace.json` (mode 600).
Also implements invite key cryptography: self-contained encrypted tokens using a
32-byte AES-256 key, 16-byte IV, HMAC-SHA256 authentication, and XOR stream
cipher. Payload includes db_url, engram_id, schema, expiration, and use count.

**Public interface:** `WorkspaceConfig`, `read_workspace()`,
`write_workspace()`, `generate_team_id()`, `generate_invite_key()`,
`decode_invite_key()`.

**Must not:** import engine or storage. Workspace config is read by the CLI and
server at startup; the engine receives a ready-to-use storage instance.

---

### auth.py — Authentication and Rate Limiting

Custom JWT implementation (HMAC-SHA256, no external dependencies) for team-mode
token auth. Includes a per-agent sliding-window rate limiter and hierarchical,
temporal scope permission checking.

**Public interface:** `create_token()`, `verify_token()`, `RateLimiter`,
`check_scope_permission()`.

**Must not:** manage user accounts, passwords, or sessions — those concerns
live in the hosted layer (`api/auth.py`). This module handles only agent-level
token auth for the local/team server.

---

### cli.py — CLI Entry Point

Click-based CLI providing the `engram` command group. Commands: `serve` (start
MCP server, optionally with `--http` for Streamable HTTP on port 7474),
`install` (auto-configure 30+ MCP clients), `verify` (check schema and
workspace health), `token` (issue agent tokens), `config` (show/set workspace
settings).

**Public interface:** `main` (Click group), invoked as `engram <command>`.

**Must not:** contain business logic. CLI commands wire together workspace
config, engine initialization, and server startup. Logic belongs in `engine.py`.

---

### rest.py — REST API

Starlette-based JSON API providing 16 endpoints (`/api/commit`, `/api/query`,
`/api/conflicts`, etc.) for non-MCP clients. Each handler validates input, calls
the engine, and returns JSON.

**Public interface:** `create_rest_app(engine) -> Starlette`.

**Must not:** contain business logic or query the database directly. Like
`server.py`, it is a thin transport adapter over `engine.py`. Note: REST routes
are defined but not mounted in `engram serve --http`; they are available for
manual integration by downstream consumers.

---

### dashboard.py — HTML Dashboard

Server-rendered HTMX dashboard mounted at `/dashboard`. Views: knowledge base,
conflict queue, agent activity timeline, expiring facts. Progressive
enhancement — works without JavaScript for basic views.

**Public interface:** Dashboard route handlers, mounted as Starlette routes.
Routes: `/dashboard`, `/dashboard/conflicts`, `/dashboard/activity`,
`/dashboard/agents`, `/dashboard/expiring`.

**Must not:** contain business logic. Calls `engine.py` methods, renders HTML.
Must not write to the database.

---

### federation.py — Cross-team Sync

Pull-based cross-team fact synchronization via aiohttp. A workspace can pull
facts from a federated peer, deduplicating and re-embedding as needed.

**Public interface:** Federation route handlers, exposed at `/federation/facts`.

**Must not:** push facts to peers (pull-only design). Must not bypass the engine
commit pipeline when ingesting federated facts.

---

### export.py — Workspace Snapshots

Produces portable JSON and Markdown snapshots of a workspace. Supports secret
redaction (re-scans facts through `secrets.py`) and anonymous mode (strips
agent/engineer identifiers).

**Public interface:** `build_json_export()`, `build_markdown_export()`.

**Must not:** write files to disk — it returns the export content. The caller
(engine or server tool) decides where to write it.

---

### suggester.py — LLM Conflict Resolution

Generates resolution suggestions for detected conflicts using Claude Haiku.
Queued asynchronously by the engine's suggestion background worker. Requires
`ANTHROPIC_API_KEY` to be set; silently no-ops otherwise.

**Public interface:** `generate_suggestion(conflict, facts) -> str`.

**Must not:** resolve conflicts — it only *suggests*. Resolution authority
remains with `engine.py` (via `resolve()`). Must not be called synchronously in
the commit or query hot path.

---

### GDPR Subject-Erasure Path

When a workspace creator calls `engram_gdpr_erase` (MCP), `engram gdpr erase`
(CLI), or `POST /api/gdpr/erase` (REST), the following happens:

```
Caller (MCP / REST / CLI)
    │
    │  creator-only gate (read_workspace().is_creator)
    ▼
EngramEngine.gdpr_erase_agent(agent_id, mode="soft"|"hard")
    │
    ├── mode="soft"
    │       └── storage.gdpr_soft_erase_agent(agent_id)
    │               UPDATE facts  SET engineer='[redacted]', provenance=NULL
    │               UPDATE conflicts  (scrub explanation / suggestion fields)
    │               UPDATE agents     SET engineer='[redacted]'
    │               UPDATE audit_log  (clear agent_id)
    │               COMMIT (atomic)
    │
    └── mode="hard"
            └── storage.gdpr_hard_erase_agent(agent_id)
                    UPDATE facts  (replace content, null embedding/keywords,
                                   close valid_until)          ← facts_au trigger
                                                                  keeps FTS in sync
                    UPDATE conflicts  (dismiss open, scrub resolved)
                    UPDATE agents / DELETE scope_permissions / UPDATE scopes
                    UPDATE audit_log  (clear agent_id + fact_id)
                    COMMIT (atomic)
    │
    └── _audit("gdpr_erase", ...)  — records counts, mode; no agent PII
```

**Conflict cascade rules:**
- Open conflicts referencing an erased fact: status → `dismissed`,
  `resolution_type → 'gdpr_erasure'`, all free-text fields scrubbed.
- Already-resolved conflicts: only free-text fields scrubbed
  (`explanation`, `resolution`, suggestions).
- `suggested_winning_fact_id` is nulled if it pointed at an erased fact.

For full operational guidance see `docs/PRIVACY_ARCHITECTURE.md` §"GDPR Subject Erasure".

---

### __init__.py — Package Metadata

Defines the package version (`0.1.0`) and public imports.

**Must not:** contain logic. Version bump only.