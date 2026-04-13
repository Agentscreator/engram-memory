"""Database schema and migrations for Engram.

Schema version 4 adds:
- workspaces table (engram_id, privacy settings)
- invite_keys table (for join flow)
- workspace_id column on facts, conflicts, agents (multi-tenancy)

Two schemas are maintained:
- SCHEMA_SQL: SQLite (local mode, aiosqlite)
- POSTGRES_SCHEMA_SQL: PostgreSQL (team mode, asyncpg)
"""

SCHEMA_VERSION = 9

# Incremental ALTER TABLE migrations keyed by target version.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE conflicts ADD COLUMN suggested_resolution TEXT",
        "ALTER TABLE conflicts ADD COLUMN suggested_resolution_type TEXT",
        "ALTER TABLE conflicts ADD COLUMN suggested_winning_fact_id TEXT",
        "ALTER TABLE conflicts ADD COLUMN suggestion_reasoning TEXT",
        "ALTER TABLE conflicts ADD COLUMN suggestion_generated_at TEXT",
        "ALTER TABLE conflicts ADD COLUMN auto_resolved INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conflicts ADD COLUMN escalated_at TEXT",
    ],
    3: [
        "ALTER TABLE facts ADD COLUMN memory_op TEXT NOT NULL DEFAULT 'add'",
        "ALTER TABLE facts ADD COLUMN supersedes_fact_id TEXT",
    ],
    4: [
        # Multi-tenancy: workspace_id on core tables
        "ALTER TABLE facts ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE conflicts ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE agents ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'local'",
        # Workspace and invite key tables
        """CREATE TABLE IF NOT EXISTS workspaces (
            engram_id        TEXT PRIMARY KEY,
            created_at       TEXT NOT NULL,
            anonymous_mode   INTEGER NOT NULL DEFAULT 0,
            anon_agents      INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS invite_keys (
            key_hash         TEXT PRIMARY KEY,
            engram_id        TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            expires_at       TEXT,
            uses_remaining   INTEGER
        )""",
    ],
    5: [
        # Phase 2: Corroboration tracking for multi-agent consensus
        "ALTER TABLE facts ADD COLUMN corroborating_agents INTEGER NOT NULL DEFAULT 0",
    ],
    6: [
        # Ephemeral memory: durability tier + query hit tracking for auto-promotion
        "ALTER TABLE facts ADD COLUMN durability TEXT NOT NULL DEFAULT 'durable'",
        "ALTER TABLE facts ADD COLUMN query_hits INTEGER NOT NULL DEFAULT 0",
    ],
    7: [
        # Security key rotation: generation counter on workspaces
        "ALTER TABLE workspaces ADD COLUMN key_generation INTEGER NOT NULL DEFAULT 0",
    ],
    8: [
        # Webhooks / Event Subscriptions
        """CREATE TABLE IF NOT EXISTS webhooks (
            id           TEXT PRIMARY KEY,
            url          TEXT NOT NULL,
            events       TEXT NOT NULL,
            secret       TEXT,
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT 'local'
        )""",
        """CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id           TEXT PRIMARY KEY,
            webhook_id   TEXT NOT NULL,
            event        TEXT NOT NULL,
            payload      TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            attempts     INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT 'local'
        )""",
        # Auto-Resolution Rules Engine
        """CREATE TABLE IF NOT EXISTS resolution_rules (
            id               TEXT PRIMARY KEY,
            scope_prefix     TEXT NOT NULL,
            condition_type   TEXT NOT NULL,
            condition_value  TEXT NOT NULL,
            resolution_type  TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            active           INTEGER NOT NULL DEFAULT 1,
            workspace_id     TEXT NOT NULL DEFAULT 'local'
        )""",
        # Scope Registry
        """CREATE TABLE IF NOT EXISTS scopes (
            scope            TEXT NOT NULL,
            description      TEXT,
            owner_agent_id   TEXT,
            retention_days   INTEGER,
            created_at       TEXT NOT NULL,
            workspace_id     TEXT NOT NULL DEFAULT 'local',
            PRIMARY KEY (scope, workspace_id)
        )""",
        # Audit Trail
        """CREATE TABLE IF NOT EXISTS audit_log (
            id           TEXT PRIMARY KEY,
            operation    TEXT NOT NULL,
            agent_id     TEXT,
            fact_id      TEXT,
            conflict_id  TEXT,
            extra        TEXT,
            timestamp    TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT 'local'
        )""",
    ],
    9: [
        # Workspace display name and description (issue #64)
        "ALTER TABLE workspaces ADD COLUMN display_name TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE workspaces ADD COLUMN description TEXT NOT NULL DEFAULT ''",
    ],
}

# ── SQLite schema (local mode) ───────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- Core fact store: append-only, bitemporal
CREATE TABLE IF NOT EXISTS facts (
    id               TEXT PRIMARY KEY,
    lineage_id       TEXT NOT NULL,
    content          TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    scope            TEXT NOT NULL,
    confidence       REAL NOT NULL,
    fact_type        TEXT NOT NULL DEFAULT 'observation',
    agent_id         TEXT NOT NULL,
    engineer         TEXT,
    provenance       TEXT,
    keywords         TEXT,
    entities         TEXT,
    artifact_hash    TEXT,
    embedding        BLOB,
    embedding_model  TEXT NOT NULL,
    embedding_ver    TEXT NOT NULL,
    committed_at     TEXT NOT NULL,
    valid_from       TEXT NOT NULL,
    valid_until      TEXT,
    ttl_days         INTEGER,
    memory_op        TEXT NOT NULL DEFAULT 'add',
    supersedes_fact_id TEXT,
    workspace_id     TEXT NOT NULL DEFAULT 'local',
    corroborating_agents INTEGER NOT NULL DEFAULT 0,
    durability       TEXT NOT NULL DEFAULT 'durable',
    query_hits       INTEGER NOT NULL DEFAULT 0,
    pinned           INTEGER NOT NULL DEFAULT 0,
    pinned_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_validity     ON facts(scope, valid_until);
CREATE INDEX IF NOT EXISTS idx_facts_content_hash ON facts(content_hash);
CREATE INDEX IF NOT EXISTS idx_facts_lineage      ON facts(lineage_id);
CREATE INDEX IF NOT EXISTS idx_facts_agent        ON facts(agent_id);
CREATE INDEX IF NOT EXISTS idx_facts_type         ON facts(fact_type);

-- FTS5 for lexical retrieval
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content, scope, keywords,
    content=facts, content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, scope, keywords)
    VALUES (new.rowid, new.content, new.scope, new.keywords);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, scope, keywords)
    VALUES ('delete', old.rowid, old.content, old.scope, old.keywords);
END;

-- Conflict tracking
CREATE TABLE IF NOT EXISTS conflicts (
    id                          TEXT PRIMARY KEY,
    fact_a_id                   TEXT NOT NULL REFERENCES facts(id),
    fact_b_id                   TEXT NOT NULL REFERENCES facts(id),
    detected_at                 TEXT NOT NULL,
    detection_tier              TEXT NOT NULL,
    nli_score                   REAL,
    explanation                 TEXT,
    severity                    TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'open',
    resolved_by                 TEXT,
    resolved_at                 TEXT,
    resolution                  TEXT,
    resolution_type             TEXT,
    suggested_resolution        TEXT,
    suggested_resolution_type   TEXT,
    suggested_winning_fact_id   TEXT,
    suggestion_reasoning        TEXT,
    suggestion_generated_at     TEXT,
    auto_resolved               INTEGER NOT NULL DEFAULT 0,
    escalated_at                TEXT,
    workspace_id                TEXT NOT NULL DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS idx_conflicts_status    ON conflicts(status);
CREATE INDEX IF NOT EXISTS idx_conflicts_fact_a    ON conflicts(fact_a_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_fact_b    ON conflicts(fact_b_id);

-- Agent registry
CREATE TABLE IF NOT EXISTS agents (
    agent_id         TEXT PRIMARY KEY,
    engineer         TEXT NOT NULL,
    label            TEXT,
    registered_at    TEXT NOT NULL,
    last_seen        TEXT,
    total_commits    INTEGER DEFAULT 0,
    flagged_commits  INTEGER DEFAULT 0,
    workspace_id     TEXT NOT NULL DEFAULT 'local'
);

-- NLI feedback
CREATE TABLE IF NOT EXISTS detection_feedback (
    conflict_id    TEXT NOT NULL REFERENCES conflicts(id),
    feedback       TEXT NOT NULL,
    recorded_at    TEXT NOT NULL
);

-- Scope permissions
CREATE TABLE IF NOT EXISTS scope_permissions (
    agent_id    TEXT NOT NULL,
    scope       TEXT NOT NULL,
    can_read    INTEGER NOT NULL DEFAULT 1,
    can_write   INTEGER NOT NULL DEFAULT 1,
    valid_from  TEXT,
    valid_until TEXT,
    PRIMARY KEY (agent_id, scope)
);

-- Workspaces (multi-tenancy + privacy settings)
CREATE TABLE IF NOT EXISTS workspaces (
    engram_id        TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    anonymous_mode   INTEGER NOT NULL DEFAULT 0,
    anon_agents      INTEGER NOT NULL DEFAULT 0,
    key_generation   INTEGER NOT NULL DEFAULT 0,
    display_name     TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT ''
);

-- Invite keys (db_url is encrypted into the key token, NOT stored here)
CREATE TABLE IF NOT EXISTS invite_keys (
    key_hash         TEXT PRIMARY KEY,
    engram_id        TEXT NOT NULL REFERENCES workspaces(engram_id),
    created_at       TEXT NOT NULL,
    expires_at       TEXT,
    uses_remaining   INTEGER
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Webhooks (event subscriptions)
CREATE TABLE IF NOT EXISTS webhooks (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    events       TEXT NOT NULL,
    secret       TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);

-- Webhook deliveries (outbound event queue)
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           TEXT PRIMARY KEY,
    webhook_id   TEXT NOT NULL,
    event        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    attempts     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);

-- Auto-resolution rules engine
CREATE TABLE IF NOT EXISTS resolution_rules (
    id               TEXT PRIMARY KEY,
    scope_prefix     TEXT NOT NULL,
    condition_type   TEXT NOT NULL,
    condition_value  TEXT NOT NULL,
    resolution_type  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    workspace_id     TEXT NOT NULL DEFAULT 'local'
);

-- Scope registry
CREATE TABLE IF NOT EXISTS scopes (
    scope            TEXT NOT NULL,
    description      TEXT,
    owner_agent_id   TEXT,
    retention_days   INTEGER,
    created_at       TEXT NOT NULL,
    workspace_id     TEXT NOT NULL DEFAULT 'local',
    PRIMARY KEY (scope, workspace_id)
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    operation    TEXT NOT NULL,
    agent_id     TEXT,
    fact_id      TEXT,
    conflict_id  TEXT,
    extra        TEXT,
    timestamp    TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);
"""

# ── Post-migration indexes (SQLite) ─────────────────────────────────
# Indexes on columns added by migrations (workspace_id, durability).
# These must run AFTER migrations so the columns exist on older databases.

POST_MIGRATION_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_facts_workspace    ON facts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_facts_durability   ON facts(durability, valid_until);
CREATE INDEX IF NOT EXISTS idx_conflicts_workspace ON conflicts(workspace_id);
"""

# ── PostgreSQL schema (team mode) ────────────────────────────────────

POSTGRES_SCHEMA_SQL = """
-- Enable pgvector extension (if available; falls back to bytea if not)
CREATE EXTENSION IF NOT EXISTS vector;

-- Core fact store: append-only, bitemporal
CREATE TABLE IF NOT EXISTS facts (
    id               TEXT PRIMARY KEY,
    lineage_id       TEXT NOT NULL,
    content          TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    scope            TEXT NOT NULL,
    confidence       REAL NOT NULL,
    fact_type        TEXT NOT NULL DEFAULT 'observation',
    agent_id         TEXT NOT NULL,
    engineer         TEXT,
    provenance       TEXT,
    keywords         TEXT,
    entities         JSONB,
    artifact_hash    TEXT,
    embedding        vector(384),
    embedding_model  TEXT NOT NULL,
    embedding_ver    TEXT NOT NULL,
    committed_at     TIMESTAMPTZ NOT NULL,
    valid_from       TIMESTAMPTZ NOT NULL,
    valid_until      TIMESTAMPTZ,
    ttl_days         INTEGER,
    memory_op        TEXT NOT NULL DEFAULT 'add',
    supersedes_fact_id TEXT,
    workspace_id     TEXT NOT NULL DEFAULT 'local',
    corroborating_agents INTEGER NOT NULL DEFAULT 0,
    durability       TEXT NOT NULL DEFAULT 'durable',
    query_hits       INTEGER NOT NULL DEFAULT 0,
    search_vector    tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(content, '') || ' ' || coalesce(scope, '') || ' ' || coalesce(keywords, ''))
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_facts_validity     ON facts(scope, valid_until);
CREATE INDEX IF NOT EXISTS idx_facts_content_hash ON facts(content_hash);
CREATE INDEX IF NOT EXISTS idx_facts_lineage      ON facts(lineage_id);
CREATE INDEX IF NOT EXISTS idx_facts_agent        ON facts(agent_id);
CREATE INDEX IF NOT EXISTS idx_facts_type         ON facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_facts_workspace    ON facts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_facts_durability   ON facts(durability, valid_until);
CREATE INDEX IF NOT EXISTS idx_facts_fts          ON facts USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_facts_embedding    ON facts USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100);

-- Conflict tracking
CREATE TABLE IF NOT EXISTS conflicts (
    id                          TEXT PRIMARY KEY,
    fact_a_id                   TEXT NOT NULL REFERENCES facts(id),
    fact_b_id                   TEXT NOT NULL REFERENCES facts(id),
    detected_at                 TIMESTAMPTZ NOT NULL,
    detection_tier              TEXT NOT NULL,
    nli_score                   REAL,
    explanation                 TEXT,
    severity                    TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'open',
    resolved_by                 TEXT,
    resolved_at                 TIMESTAMPTZ,
    resolution                  TEXT,
    resolution_type             TEXT,
    suggested_resolution        TEXT,
    suggested_resolution_type   TEXT,
    suggested_winning_fact_id   TEXT,
    suggestion_reasoning        TEXT,
    suggestion_generated_at     TIMESTAMPTZ,
    auto_resolved               INTEGER NOT NULL DEFAULT 0,
    escalated_at                TIMESTAMPTZ,
    workspace_id                TEXT NOT NULL DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS idx_conflicts_status    ON conflicts(status);
CREATE INDEX IF NOT EXISTS idx_conflicts_fact_a    ON conflicts(fact_a_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_fact_b    ON conflicts(fact_b_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_workspace ON conflicts(workspace_id);

-- Agent registry
CREATE TABLE IF NOT EXISTS agents (
    agent_id         TEXT PRIMARY KEY,
    engineer         TEXT NOT NULL,
    label            TEXT,
    registered_at    TIMESTAMPTZ NOT NULL,
    last_seen        TIMESTAMPTZ,
    total_commits    INTEGER DEFAULT 0,
    flagged_commits  INTEGER DEFAULT 0,
    workspace_id     TEXT NOT NULL DEFAULT 'local'
);

-- NLI feedback
CREATE TABLE IF NOT EXISTS detection_feedback (
    conflict_id    TEXT NOT NULL REFERENCES conflicts(id),
    feedback       TEXT NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL
);

-- Scope permissions
CREATE TABLE IF NOT EXISTS scope_permissions (
    agent_id    TEXT NOT NULL,
    scope       TEXT NOT NULL,
    can_read    BOOLEAN NOT NULL DEFAULT TRUE,
    can_write   BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from  TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    PRIMARY KEY (agent_id, scope)
);

-- Workspaces
CREATE TABLE IF NOT EXISTS workspaces (
    engram_id        TEXT PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL,
    anonymous_mode   BOOLEAN NOT NULL DEFAULT FALSE,
    anon_agents      BOOLEAN NOT NULL DEFAULT FALSE,
    key_generation   INTEGER NOT NULL DEFAULT 0,
    display_name     TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT ''
);

-- Invite keys (db_url encrypted into token, NOT stored here)
CREATE TABLE IF NOT EXISTS invite_keys (
    key_hash         TEXT PRIMARY KEY,
    engram_id        TEXT NOT NULL REFERENCES workspaces(engram_id),
    created_at       TIMESTAMPTZ NOT NULL,
    expires_at       TIMESTAMPTZ,
    uses_remaining   INTEGER
);

-- Webhooks (event subscriptions)
CREATE TABLE IF NOT EXISTS webhooks (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    events       JSONB NOT NULL,
    secret       TEXT,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);

-- Webhook deliveries
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           TEXT PRIMARY KEY,
    webhook_id   TEXT NOT NULL,
    event        TEXT NOT NULL,
    payload      JSONB NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    attempts     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);

-- Auto-resolution rules engine
CREATE TABLE IF NOT EXISTS resolution_rules (
    id               TEXT PRIMARY KEY,
    scope_prefix     TEXT NOT NULL,
    condition_type   TEXT NOT NULL,
    condition_value  TEXT NOT NULL,
    resolution_type  TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    workspace_id     TEXT NOT NULL DEFAULT 'local'
);

-- Scope registry
CREATE TABLE IF NOT EXISTS scopes (
    scope            TEXT NOT NULL,
    description      TEXT,
    owner_agent_id   TEXT,
    retention_days   INTEGER,
    created_at       TIMESTAMPTZ NOT NULL,
    workspace_id     TEXT NOT NULL DEFAULT 'local',
    PRIMARY KEY (scope, workspace_id)
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    operation    TEXT NOT NULL,
    agent_id     TEXT,
    fact_id      TEXT,
    conflict_id  TEXT,
    extra        JSONB,
    timestamp    TIMESTAMPTZ NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'local'
);
"""
