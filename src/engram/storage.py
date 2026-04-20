"""Storage layer: async SQLite (local mode) + abstract BaseStorage interface.

Local mode: SQLiteStorage — aiosqlite, WAL mode, FTS5.
Team mode:  PostgresStorage (postgres_storage.py) — asyncpg, tsvector, pgvector.

The Storage alias keeps existing imports working.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from engram.schema import POST_MIGRATION_INDEXES, SCHEMA_SQL, SCHEMA_VERSION

DEFAULT_DB_PATH = Path.home() / ".engram" / "knowledge.db"
ANALYTICS_BUCKET_LIMIT = 30
ANALYTICS_TOP_LIMIT = 10


class BaseStorage(ABC):
    """Abstract storage interface. Both SQLiteStorage and PostgresStorage implement this."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def insert_fact(self, fact: dict[str, Any]) -> int: ...

    @abstractmethod
    async def find_duplicate(self, content_hash: str, scope: str) -> str | None: ...

    @abstractmethod
    async def close_validity_window(
        self, *, lineage_id: str | None = None, fact_id: str | None = None
    ) -> None: ...

    @abstractmethod
    async def expire_ttl_facts(self, as_of: str | None = None) -> int: ...

    @abstractmethod
    async def get_current_facts_in_scope(
        self,
        scope: str | None = None,
        fact_type: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
        offset: int = 0,
        include_ephemeral: bool = False,
    ) -> list[dict]: ...

    @abstractmethod
    async def fts_search(self, query: str, limit: int = 20, offset: int = 0) -> list[int]: ...

    @abstractmethod
    async def generate_agents_md(self) -> str: ...

    @abstractmethod
    async def get_facts_by_rowids(self, rowids: list[int]) -> list[dict]: ...

    @abstractmethod
    async def get_distinct_scopes(self) -> list[str]:
        """Return all unique scope values for the workspace."""
        ...

    @abstractmethod
    async def get_fact_by_id(self, fact_id: str) -> dict | None: ...

    @abstractmethod
    async def get_facts_by_ids(self, ids: list[str]) -> dict[str, dict]:
        """Batch-fetch multiple facts by ID. Returns {id: fact_row}."""
        ...

    @abstractmethod
    async def get_conflicting_fact_ids(self, fact_id: str, status: str = "open") -> set[str]:
        """Return fact IDs that have conflicts with fact_id."""
        ...

    @abstractmethod
    async def promote_fact(self, fact_id: str) -> bool:
        """Promote an ephemeral fact to durable. Returns True if promoted."""
        ...

    @abstractmethod
    async def increment_query_hits(self, fact_ids: list[str]) -> None:
        """Increment query_hits counter for the given fact IDs."""
        ...

    @abstractmethod
    async def get_promotable_ephemeral_facts(self, min_hits: int = 2) -> list[dict]:
        """Return ephemeral facts that have been queried enough times to auto-promote."""
        ...

    @abstractmethod
    async def get_facts_by_durability(self, durability: str) -> list[dict]:
        """Return all facts with the given durability level."""
        ...

    @abstractmethod
    async def retire_stale_facts(self) -> int:
        """Retire stale, low-value facts via importance-based decay.

        Targets:
        1. Unverified inferences older than 30 days
        2. Unverified, uncorroborated observations older than 90 days
        Decisions and facts with provenance or corroboration are protected.
        Returns count of retired facts.
        """
        ...

    @abstractmethod
    async def find_entity_conflicts(
        self, entity_name: str, entity_type: str, entity_value: str, scope: str, exclude_id: str
    ) -> list[dict]: ...

    @abstractmethod
    async def find_cross_scope_entity_matches(
        self, entity_name: str, entity_type: str, entity_value: str, exclude_id: str
    ) -> list[dict]: ...

    @abstractmethod
    async def insert_conflict(self, conflict: dict[str, Any]) -> None: ...

    @abstractmethod
    async def conflict_exists(self, fact_a_id: str, fact_b_id: str, include_resolved: bool = False) -> bool: ...

    @abstractmethod
    async def get_conflicts(self, scope: str | None = None, status: str = "open") -> list[dict]: ...

    @abstractmethod
    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str | None = None,
    ) -> bool: ...

    @abstractmethod
    async def get_conflict_by_id(self, conflict_id: str) -> dict | None: ...

    @abstractmethod
    async def get_conflict_with_facts(self, conflict_id: str) -> dict | None: ...

    @abstractmethod
    async def update_conflict_suggestion(
        self,
        conflict_id: str,
        suggested_resolution: str,
        suggested_resolution_type: str,
        suggested_winning_fact_id: str | None,
        suggestion_reasoning: str,
        suggestion_generated_at: str,
    ) -> None: ...

    @abstractmethod
    async def auto_resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str,
        escalated_at: str | None = None,
    ) -> bool: ...

    @abstractmethod
    async def get_stale_open_conflicts(self, older_than_hours: int = 72) -> list[dict]: ...

    @abstractmethod
    async def insert_detection_feedback(self, conflict_id: str, feedback: str) -> None: ...

    @abstractmethod
    async def upsert_agent(self, agent_id: str, engineer: str = "unknown") -> None: ...

    @abstractmethod
    async def increment_agent_commits(self, agent_id: str) -> None: ...

    @abstractmethod
    async def increment_agent_flagged(self, agent_id: str) -> None: ...

    @abstractmethod
    async def get_agent(self, agent_id: str) -> dict | None: ...

    @abstractmethod
    async def get_scope_permission(self, agent_id: str, scope: str) -> dict | None: ...

    @abstractmethod
    async def set_scope_permission(
        self,
        agent_id: str,
        scope: str,
        can_read: bool = True,
        can_write: bool = True,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None: ...

    @abstractmethod
    async def get_facts_by_lineage(self, lineage_id: str) -> list[dict]: ...

    @abstractmethod
    async def get_active_facts_with_embeddings(self, scope: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def update_fact_embedding(self, fact_id: str, embedding: bytes) -> None: ...

    @abstractmethod
    async def get_distinct_embedding_models(self) -> list[str]: ...

    @abstractmethod
    async def get_facts_by_embedding_model(
        self, embedding_model: str, limit: int = 100, offset: int = 0
    ) -> list[dict]: ...

    @abstractmethod
    async def update_fact_embedding_with_model(
        self, fact_id: str, embedding: bytes, embedding_model: str, embedding_ver: str
    ) -> None: ...

    @abstractmethod
    async def update_fact_entities(self, fact_id: str, entities_json: str) -> None: ...

    @abstractmethod
    async def get_facts_with_empty_entities(
        self, limit: int = 200, offset: int = 0
    ) -> list[dict]: ...

    @abstractmethod
    async def get_facts_since(
        self, after: str, scope_prefix: str | None = None, limit: int = 1000
    ) -> list[dict]: ...

    @abstractmethod
    async def get_facts_added_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]: ...

    @abstractmethod
    async def get_facts_retired_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]: ...

    @abstractmethod
    async def get_conflicts_resolved_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]: ...

    @abstractmethod
    async def ingest_remote_fact(self, fact: dict[str, Any]) -> bool: ...

    @abstractmethod
    async def count_facts(self, current_only: bool = True) -> int: ...

    @abstractmethod
    async def count_conflicts(self, status: str = "open") -> int: ...

    async def get_workspace_stats(self) -> dict:
        """Return aggregate workspace statistics for the /api/stats endpoint.

        Default no-op implementation for backends that haven't implemented it yet.
        SQLiteStorage provides a full implementation.
        """
        return {}

    @abstractmethod
    async def get_agents(self) -> list[dict]: ...

    @abstractmethod
    async def get_agents_by_ids(self, agent_ids: set[str]) -> dict[str, dict]: ...

    @abstractmethod
    async def get_expiring_facts(self, days_ahead: int = 7) -> list[dict]: ...

    @abstractmethod
    async def get_fact_timeline(self, scope: str | None = None, limit: int = 100) -> list[dict]: ...

    @abstractmethod
    async def get_detection_feedback_stats(self) -> dict[str, int]: ...

    @abstractmethod
    async def get_open_conflict_fact_ids(self) -> set[str]: ...

    @abstractmethod
    async def increment_corroboration(self, fact_id: str) -> None: ...

    # ── Workspace / invite key methods (Phase 0) ─────────────────────

    async def ensure_workspace(
        self, engram_id: str, anonymous_mode: bool, anon_agents: bool
    ) -> None:
        """Create workspace row if it doesn't exist. Default no-op for local mode."""

    async def get_workspace(self, engram_id: str) -> dict | None:
        """Return workspace row or None."""
        return None

    async def update_workspace_display_name(self, engram_id: str, display_name: str) -> None:
        """Update the display name for a workspace. Default no-op for local mode."""

    async def delete_workspace(self, engram_id: str) -> None:
        """Delete a workspace and all associated facts, conflicts, and invite keys. Default no-op."""

    async def insert_invite_key(
        self,
        key_hash: str,
        engram_id: str,
        expires_at: str | None,
        uses_remaining: int | None,
    ) -> None:
        """Store an invite key hash. Default no-op for local mode."""

    async def validate_invite_key(self, key_hash: str) -> dict | None:
        """Return invite key row if valid (not expired, uses remaining). Default None."""
        return None

    async def consume_invite_key(self, key_hash: str) -> dict | None:
        """Atomically validate and decrement uses_remaining. Returns the key row if consumed, None if exhausted/expired."""
        return None

    async def get_key_generation(self, engram_id: str) -> int:
        """Return the current key_generation for a workspace. Default 0."""
        return 0

    async def bump_key_generation(self, engram_id: str) -> int:
        """Increment key_generation and return the new value. Default no-op."""
        return 0

    async def get_invite_keys(self) -> list[dict]:
        """Return list of active invite keys. Default empty list."""
        return []

    async def revoke_all_invite_keys(
        self,
        engram_id: str,
        *,
        grace_minutes: int = 15,
        reason: str | None = None,
    ) -> None:
        """Soft-revoke all active invite keys for a workspace.

        If grace_minutes > 0, keys are marked revoked but kept in the table
        until grace_until expires, allowing existing sessions to continue.
        If grace_minutes == 0, keys are hard-deleted immediately.
        Expired grace keys are always cleaned up as a side-effect.
        Default no-op for local mode.
        """

    async def get_active_grace_until(self, engram_id: str) -> str | None:
        """Return the latest grace_until among revoked-but-not-yet-expired keys.

        Returns None if no grace window is currently active.
        Default None for local mode.
        """
        return None

    async def cleanup_expired_grace_keys(self, engram_id: str) -> int:
        """Hard-delete revoked invite keys whose grace_until has passed.

        Returns the number of rows deleted. Default 0 for local mode.
        """
        return 0

    async def get_key_rotation_history(self, engram_id: str, limit: int = 20) -> list[dict]:
        """Return audit_log entries with operation='key_rotation' for the workspace.

        Ordered by timestamp descending. Default empty list for local mode.
        """
        return []

    # ── Webhook methods ───────────────────────────────────────────────

    @abstractmethod
    async def insert_webhook(self, webhook: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_webhooks(self) -> list[dict]: ...

    @abstractmethod
    async def get_webhook_by_id(self, webhook_id: str) -> dict | None: ...

    @abstractmethod
    async def delete_webhook(self, webhook_id: str) -> bool: ...

    @abstractmethod
    async def queue_webhook_delivery(self, delivery: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_pending_deliveries(self) -> list[dict]: ...

    @abstractmethod
    async def mark_delivery_done(self, delivery_id: str) -> None: ...

    @abstractmethod
    async def mark_delivery_failed(self, delivery_id: str) -> None: ...

    # ── Resolution rule methods ───────────────────────────────────────

    @abstractmethod
    async def insert_rule(self, rule: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_rules(self) -> list[dict]: ...

    @abstractmethod
    async def get_rule_by_id(self, rule_id: str) -> dict | None: ...

    @abstractmethod
    async def delete_rule(self, rule_id: str) -> bool: ...

    # ── Scope registry methods ────────────────────────────────────────

    @abstractmethod
    async def upsert_scope(self, scope_data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_scopes(self) -> list[dict]: ...

    @abstractmethod
    async def get_scope_by_name(self, scope: str) -> dict | None: ...

    @abstractmethod
    async def get_scope_analytics(self, scope: str) -> dict: ...

    # ── Audit log methods ─────────────────────────────────────────────

    @abstractmethod
    async def insert_audit_entry(self, entry: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_audit_log(
        self,
        agent_id: str | None = None,
        operation: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict]: ...

    @abstractmethod
    async def record_usage_event(
        self, event_type: str, quantity: int = 1, billing_period: str | None = None
    ) -> None: ...

    @abstractmethod
    async def get_usage_events(
        self, event_type: str | None = None, billing_period: str | None = None
    ) -> list[dict]: ...

    @abstractmethod
    async def get_unsynced_usage_events(self, billing_period: str) -> list[dict]: ...

    @abstractmethod
    async def mark_usage_events_synced(self, event_ids: list[str]) -> None: ...

    # ── Temporal Knowledge Graph (TKG) ───────────────────────────────

    @abstractmethod
    async def insert_tkg_node(self, node: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_tkg_node_by_name(self, name: str) -> dict | None: ...

    @abstractmethod
    async def get_tkg_node_by_id(self, node_id: str) -> dict | None: ...

    @abstractmethod
    async def update_tkg_node_seen(self, node_id: str, timestamp: str) -> None: ...

    @abstractmethod
    async def insert_tkg_edge(self, edge: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_active_tkg_edges(self, source_node_id: str, relation_type: str) -> list[dict]: ...

    @abstractmethod
    async def expire_tkg_edge(self, edge_id: str, expired_at: str) -> None: ...

    @abstractmethod
    async def get_tkg_edges_for_node(
        self,
        node_id: str,
        relation_type: str | None = None,
        include_expired: bool = True,
    ) -> list[dict]: ...

    @abstractmethod
    async def get_tkg_nodes_with_expired_edges(self, scope: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def get_old_active_tkg_edges(
        self, max_age_days: int = 30, scope: str | None = None
    ) -> list[dict]: ...

    @abstractmethod
    async def get_newer_tkg_edges(self, source_node_id: str, after: str) -> list[dict]: ...

    @abstractmethod
    async def get_tkg_multi_agent_edges(self, scope: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def get_tkg_stats(self, scope: str | None = None) -> dict[str, int]: ...

    @abstractmethod
    async def update_tkg_node_summary(self, node_id: str, summary: str) -> None: ...

    @abstractmethod
    async def get_all_tkg_nodes(self) -> list[dict]: ...

    @abstractmethod
    async def enqueue_deferred_scan(self, scan: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_pending_deferred_scans(self, before: str) -> list[dict]: ...

    @abstractmethod
    async def update_deferred_scan_status(
        self, scan_id: str, status: str, fact_count: int = 0, completed_at: str | None = None
    ) -> None: ...


class SQLiteStorage(BaseStorage):
    """Async SQLite storage with WAL mode and FTS5."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, workspace_id: str = "local") -> None:
        self.db_path = Path(db_path)
        self.workspace_id = workspace_id
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row

        # Check if this is an existing database that needs migrations
        # BEFORE running the full schema (which references columns that
        # may not exist yet on old tables).
        try:
            cursor = await self._db.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            )
            row = await cursor.fetchone()
        except Exception:
            row = None  # Fresh database — schema_meta doesn't exist yet

        if row is not None:
            # Existing database: run migrations first so columns exist
            # before SCHEMA_SQL tries to create indexes on them.
            from engram.schema import MIGRATIONS

            current_version = int(row["value"])
            for version in range(current_version + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(version, []):
                    try:
                        await self._db.execute(stmt)
                    except Exception:
                        pass  # Column/table already exists — idempotent
            await self._db.commit()

        # Now safe to run full schema: CREATE TABLE IF NOT EXISTS is a
        # no-op for existing tables, and all columns exist for indexes.
        await self._db.executescript(SCHEMA_SQL)

        # Create indexes that depend on migration-added columns.
        # Separated so the main SCHEMA_SQL executescript doesn't fail
        # mid-way on older databases before migrations have run.
        await self._db.executescript(POST_MIGRATION_INDEXES)

        await self._db.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._db

    # ── Fact operations ──────────────────────────────────────────────

    async def insert_fact(self, fact: dict[str, Any]) -> int:
        """Insert a fact row. Returns the rowid for FTS5 sync."""
        import hashlib
        import uuid

        # Work on a copy so we don't mutate the caller's dict
        fact = dict(fact)

        # Auto-generate content_hash if not provided
        if not fact.get("content_hash"):
            content = fact.get("content", "")
            normalized = " ".join(content.lower().split())
            fact["content_hash"] = hashlib.sha256(normalized.encode()).hexdigest()

        # Fill in other required NOT NULL fields with sensible defaults
        now = _now_iso()
        fact.setdefault("id", str(uuid.uuid4()))
        fact.setdefault("lineage_id", str(uuid.uuid4()))
        fact.setdefault("scope", "general")
        fact.setdefault("confidence", 0.8)
        fact.setdefault("fact_type", "observation")
        fact.setdefault("agent_id", "unknown")
        fact.setdefault("embedding_model", "")
        fact.setdefault("embedding_ver", "")
        fact.setdefault("committed_at", now)
        fact.setdefault("valid_from", now)
        fact.setdefault("memory_op", "add")
        fact.setdefault("durability", "durable")
        fact.setdefault("workspace_id", self.workspace_id)

        cols = [
            "id",
            "lineage_id",
            "content",
            "content_hash",
            "scope",
            "confidence",
            "fact_type",
            "agent_id",
            "engineer",
            "provenance",
            "keywords",
            "entities",
            "artifact_hash",
            "embedding",
            "embedding_model",
            "embedding_ver",
            "committed_at",
            "valid_from",
            "valid_until",
            "ttl_days",
            "memory_op",
            "supersedes_fact_id",
            "workspace_id",
            "durability",
        ]
        defaults = {"memory_op": "add", "durability": "durable", "workspace_id": self.workspace_id}
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [fact.get(c, defaults.get(c)) for c in cols]
        cursor = await self.db.execute(
            f"INSERT INTO facts ({col_names}) VALUES ({placeholders})", values
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def find_duplicate(self, content_hash: str, scope: str) -> str | None:
        """Check for exact content duplicate in the same scope and workspace (current facts only)."""
        cursor = await self.db.execute(
            "SELECT id FROM facts WHERE content_hash = ? AND scope = ? AND valid_until IS NULL AND workspace_id = ?",
            (content_hash, scope, self.workspace_id),
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    async def close_validity_window(
        self, *, lineage_id: str | None = None, fact_id: str | None = None
    ) -> None:
        """Set valid_until = now on current facts matching lineage or id."""
        now = _now_iso()
        if lineage_id:
            await self.db.execute(
                "UPDATE facts SET valid_until = ? WHERE lineage_id = ? AND valid_until IS NULL AND workspace_id = ?",
                (now, lineage_id, self.workspace_id),
            )
        elif fact_id:
            await self.db.execute(
                "UPDATE facts SET valid_until = ? WHERE id = ? AND valid_until IS NULL AND workspace_id = ?",
                (now, fact_id, self.workspace_id),
            )
        await self.db.commit()

    async def expire_ttl_facts(self, as_of: str | None = None) -> int:
        """Close validity windows for TTL-expired facts in this workspace. Returns count.

        ``as_of`` overrides the current time, enabling deterministic tests.
        Only ephemeral facts are eligible — promoted (durable) facts are exempt
        even when they retain a ``ttl_days`` value from before promotion.
        """
        now = as_of or _now_iso()
        cursor = await self.db.execute(
            """UPDATE facts SET valid_until = ?
               WHERE ttl_days IS NOT NULL
                 AND valid_until IS NULL
                 AND durability = 'ephemeral'
                 AND workspace_id = ?
                 AND datetime(substr(valid_from, 1, 19), '+' || ttl_days || ' days') < datetime('now')""",
            (now, self.workspace_id),
        )
        await self.db.commit()
        return cursor.rowcount

    # ── Query operations ─────────────────────────────────────────────

    async def get_current_facts_in_scope(
        self,
        scope: str | None = None,
        fact_type: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
        offset: int = 0,
        include_ephemeral: bool = False,
    ) -> list[dict]:
        """Retrieve currently valid facts, optionally filtered."""
        conditions = ["workspace_id = ?"]
        params: list[Any] = [self.workspace_id]

        if as_of:
            conditions.append("valid_from <= ?")
            params.append(as_of)
            conditions.append("(valid_until IS NULL OR valid_until > ?)")
            params.append(as_of)
        else:
            conditions.append("valid_until IS NULL")

        if scope:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope, scope])

        if fact_type:
            conditions.append("fact_type = ?")
            params.append(fact_type)

        if not include_ephemeral:
            conditions.append("durability = 'durable'")

        where = " AND ".join(conditions)
        params.append(limit)
        params.append(offset)

        cursor = await self.db.execute(
            f"SELECT * FROM facts WHERE {where} ORDER BY pinned DESC, committed_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def pin_fact(self, fact_id: str) -> bool:
        """Pin a fact to always appear at top of queries."""
        from datetime import datetime, timezone

        cursor = await self.db.execute(
            "UPDATE facts SET pinned = 1, pinned_at = ? WHERE id = ? AND workspace_id = ?",
            (datetime.now(timezone.utc).isoformat(), fact_id, self.workspace_id),
        )
        return cursor.rowcount > 0

    async def unpin_fact(self, fact_id: str) -> bool:
        """Unpin a fact."""
        cursor = await self.db.execute(
            "UPDATE facts SET pinned = 0, pinned_at = NULL WHERE id = ? AND workspace_id = ?",
            (fact_id, self.workspace_id),
        )
        return cursor.rowcount > 0

    async def endorse_fact(self, fact_id: str) -> bool:
        """Endorse a fact (human approval)."""
        cursor = await self.db.execute(
            "UPDATE facts SET endorsements = endorsements + 1 WHERE id = ? AND workspace_id = ?",
            (fact_id, self.workspace_id),
        )
        return cursor.rowcount > 0

    async def downvote_fact(self, fact_id: str) -> bool:
        """Downvote a fact (human disapproval)."""
        cursor = await self.db.execute(
            "UPDATE facts SET downvotes = downvotes + 1 WHERE id = ? AND workspace_id = ?",
            (fact_id, self.workspace_id),
        )
        return cursor.rowcount > 0

    async def auto_tag_facts(self, fact_ids: list[str] | None = None) -> int:
        """Automatically tag facts with taxonomy categories based on content.

        Categories: code, docs, config, business, personal, technical, other
        Returns number of facts tagged.
        """
        import re

        tag_patterns = {
            "code": r"\b(function|class|def |import |return |var |let |const |=>|->|\.py|\.js|\.ts)\b",
            "docs": r"\b(documentation|readme|guide|manual|how-to|tutorial|example)\b",
            "config": r"\b(config|setting|option|parameter|env|yaml|json|toml)\b",
            "business": r"\b(customer|pricing|revenue|order|payment|invoice|contract)\b",
            "personal": r"\b(todo|reminder|meeting|schedule|personal|private)\b",
            "technical": r"\b(api|database|server|network|deploy|build|test)\b",
        }

        conditions = ["workspace_id = ?"]
        params: list[Any] = [self.workspace_id]

        if fact_ids:
            placeholders = ",".join("?" * len(fact_ids))
            conditions.append(f"id IN ({placeholders})")
            params.extend(fact_ids)

        cursor = await self.db.execute(
            f"SELECT id, content, keywords FROM facts WHERE {' AND '.join(conditions)}",
            params,
        )
        rows = await cursor.fetchall()

        tagged = 0
        for row in rows:
            content = row.get("content", "")
            current_keywords = row.get("keywords", "") or ""
            tags = []

            for tag, pattern in tag_patterns.items():
                if re.search(pattern, content, re.IGNORECASE):
                    tags.append(tag)

            if tags:
                new_keywords = ",".join(sorted(set(tags + current_keywords.split(","))))
                await self.db.execute(
                    "UPDATE facts SET keywords = ? WHERE id = ?",
                    (new_keywords, row["id"]),
                )
                tagged += 1

        return tagged

    async def fts_search(self, query: str, limit: int = 20, offset: int = 0) -> list[int]:
        """FTS5 BM25 search. Returns rowids ordered by relevance."""
        cursor = await self.db.execute(
            "SELECT rowid, rank FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT ? OFFSET ?",
            (query, limit, offset),
        )
        rows = await cursor.fetchall()
        return [r["rowid"] for r in rows]

    async def get_facts_by_rowids(self, rowids: list[int]) -> list[dict]:
        if not rowids:
            return []
        placeholders = ",".join(["?"] * len(rowids))
        cursor = await self.db.execute(
            f"SELECT * FROM facts WHERE rowid IN ({placeholders}) AND workspace_id = ?",
            [*rowids, self.workspace_id],
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_distinct_scopes(self) -> list[str]:
        """Return all unique scope values for the workspace."""
        cursor = await self.db.execute(
            "SELECT DISTINCT scope FROM facts WHERE workspace_id = ? AND valid_until IS NULL",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        return [r["scope"] for r in rows]

    async def get_fact_by_id(self, fact_id: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_facts_by_ids(self, ids: list[str]) -> dict[str, dict]:
        """Batch-fetch multiple facts by ID in a single query. Returns {id: fact_row}."""
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        cursor = await self.db.execute(
            f"SELECT * FROM facts WHERE id IN ({placeholders}) AND workspace_id = ?",
            (*ids, self.workspace_id),
        )
        rows = await cursor.fetchall()
        return {row["id"]: dict(row) for row in rows}

    async def get_conflicting_fact_ids(self, fact_id: str, status: str = "open") -> set[str]:
        """Return fact IDs that have OPEN conflicts with fact_id.
        
        Args:
            fact_id: The fact to check
            status: Filter by status - "open", "resolved", "dismissed", or "all" (default: "open")
        """
        if status == "all":
            status_filter = ""
        else:
            status_filter = f"AND status = '{status}'"
        cursor = await self.db.execute(
            f"""SELECT fact_a_id, fact_b_id FROM conflicts
               WHERE workspace_id = ?
                 AND (fact_a_id = ? OR fact_b_id = ?)
                 {status_filter}""",
            (self.workspace_id, fact_id, fact_id),
        )
        rows = await cursor.fetchall()
        result: set[str] = set()
        for r in rows:
            other = r["fact_b_id"] if r["fact_a_id"] == fact_id else r["fact_a_id"]
            result.add(other)
        return result

    async def promote_fact(self, fact_id: str) -> bool:
        """Promote an ephemeral fact to durable. Returns True if promoted.

        Clears ``valid_until`` and ``ttl_days`` so the fact is no longer
        subject to TTL expiry — making the promotion a permanent override.
        """
        cursor = await self.db.execute(
            "UPDATE facts SET durability = 'durable', valid_until = NULL, ttl_days = NULL"
            " WHERE id = ? AND durability = 'ephemeral'",
            (fact_id,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def increment_query_hits(self, fact_ids: list[str]) -> None:
        """Increment query_hits counter for the given fact IDs."""
        if not fact_ids:
            return
        placeholders = ",".join(["?"] * len(fact_ids))
        await self.db.execute(
            f"UPDATE facts SET query_hits = query_hits + 1 WHERE id IN ({placeholders})",
            fact_ids,
        )
        await self.db.commit()

    async def get_promotable_ephemeral_facts(self, min_hits: int = 2) -> list[dict]:
        """Return ephemeral facts in this workspace that have been queried enough times to auto-promote."""
        cursor = await self.db.execute(
            "SELECT * FROM facts WHERE durability = 'ephemeral' AND valid_until IS NULL "
            "AND workspace_id = ? AND query_hits >= ?",
            (self.workspace_id, min_hits),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_facts_by_durability(self, durability: str) -> list[dict]:
        """Return all facts with the given durability level."""
        cursor = await self.db.execute(
            "SELECT * FROM facts WHERE durability = ? AND valid_until IS NULL AND workspace_id = ?",
            (durability, self.workspace_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def retire_stale_facts(self) -> int:
        """Retire stale, low-value facts via importance-based decay."""
        now = _now_iso()
        total = 0

        # 1. Unverified inferences older than 30 days
        cursor = await self.db.execute(
            """UPDATE facts SET valid_until = ?
               WHERE valid_until IS NULL
                 AND workspace_id = ?
                 AND fact_type = 'inference'
                 AND provenance IS NULL
                 AND corroborating_agents = 0
                 AND datetime(committed_at, '+30 days') < ?""",
            (now, self.workspace_id, now),
        )
        total += cursor.rowcount
        await self.db.commit()

        # 2. Unverified, uncorroborated observations older than 90 days
        cursor = await self.db.execute(
            """UPDATE facts SET valid_until = ?
               WHERE valid_until IS NULL
                 AND workspace_id = ?
                 AND fact_type = 'observation'
                 AND provenance IS NULL
                 AND corroborating_agents = 0
                 AND datetime(committed_at, '+90 days') < ?""",
            (now, self.workspace_id, now),
        )
        total += cursor.rowcount
        await self.db.commit()

        return total

    # ── Entity-based lookups (for Tier 0 / Tier 2b detection) ────────

    async def find_entity_conflicts(
        self, entity_name: str, entity_type: str, entity_value: str, scope: str, exclude_id: str
    ) -> list[dict]:
        """Find current facts with same entity name but different value in scope."""
        cursor = await self.db.execute(
            """SELECT f.* FROM facts f, json_each(f.entities) e
               WHERE f.valid_until IS NULL
                 AND f.workspace_id = ?
                 AND f.id != ?
                 AND f.scope = ?
                 AND json_extract(e.value, '$.name') = ?
                 AND json_extract(e.value, '$.type') = ?
                 AND json_extract(e.value, '$.value') IS NOT NULL
                 AND CAST(json_extract(e.value, '$.value') AS TEXT) != ?""",
            (self.workspace_id, exclude_id, scope, entity_name, entity_type, str(entity_value)),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def find_cross_scope_entity_matches(
        self, entity_name: str, entity_type: str, entity_value: str, exclude_id: str
    ) -> list[dict]:
        """Find current facts across ALL scopes with same entity name (Tier 2b)."""
        cursor = await self.db.execute(
            """SELECT f.* FROM facts f, json_each(f.entities) e
               WHERE f.valid_until IS NULL
                 AND f.workspace_id = ?
                 AND f.id != ?
                 AND json_extract(e.value, '$.name') = ?
                 AND json_extract(e.value, '$.type') = ?
                 AND (json_extract(e.value, '$.value') IS NULL
                      OR CAST(json_extract(e.value, '$.value') AS TEXT) != ?)""",
            (self.workspace_id, exclude_id, entity_name, entity_type, str(entity_value)),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Conflict operations ──────────────────────────────────────────

    async def insert_conflict(self, conflict: dict[str, Any]) -> None:
        # Normalize pair order so the unique index (idx_conflicts_pair_unique) treats (A,B) == (B,A).
        a, b = conflict.get("fact_a_id", ""), conflict.get("fact_b_id", "")
        if a > b:
            conflict = {**conflict, "fact_a_id": b, "fact_b_id": a}

        cursor = await self.db.execute(
            """SELECT 1 FROM conflicts
               WHERE workspace_id = ?
                 AND fact_a_id = ?
                 AND fact_b_id = ?
               LIMIT 1""",
            (self.workspace_id, conflict.get("fact_a_id"), conflict.get("fact_b_id")),
        )
        if await cursor.fetchone():
            return

        cursor = await self.db.execute(
            """SELECT 1 FROM dismissed_conflicts
               WHERE conflict_id = ? AND workspace_id = ?
               LIMIT 1""",
            (conflict.get("id"), self.workspace_id),
        )
        if await cursor.fetchone():
            return

        cols = [
            "id",
            "fact_a_id",
            "fact_b_id",
            "detected_at",
            "detection_tier",
            "nli_score",
            "explanation",
            "severity",
            "status",
            "conflict_type",
            "workspace_id",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        defaults = {"workspace_id": self.workspace_id, "conflict_type": "genuine"}
        values = [conflict.get(c, defaults.get(c)) for c in cols]
        await self.db.execute(
            f"INSERT OR IGNORE INTO conflicts ({col_names}) VALUES ({placeholders})", values
        )
        await self.db.commit()

    async def conflict_exists(self, fact_a_id: str, fact_b_id: str, include_resolved: bool = False) -> bool:
        """Check if an OPEN conflict already exists between two facts.
        
        Args:
            fact_a_id: First fact ID
            fact_b_id: Second fact ID
            include_resolved: If True, also check resolved/dismissed conflicts (default: False)
        """
        if include_resolved:
            status_filter = ""
        else:
            status_filter = "AND status = 'open'"
        cursor = await self.db.execute(
            f"""SELECT 1 FROM conflicts
               WHERE workspace_id = ?
                 AND ((fact_a_id = ? AND fact_b_id = ?)
                  OR  (fact_a_id = ? AND fact_b_id = ?))
                 {status_filter}""",
            (self.workspace_id, fact_a_id, fact_b_id, fact_b_id, fact_a_id),
        )
        return await cursor.fetchone() is not None

    async def get_conflicts(self, scope: str | None = None, status: str = "open") -> list[dict]:
        conditions = [
            "c.workspace_id = ?",
            """NOT EXISTS (
                SELECT 1 FROM dismissed_conflicts dc
                WHERE dc.conflict_id = c.id AND dc.workspace_id = c.workspace_id
            )""",
        ]
        params: list[Any] = [self.workspace_id]

        if status != "all":
            conditions.append("c.status = ?")
            params.append(status)

        if scope:
            conditions.append(
                "(fa.scope = ? OR fa.scope LIKE ? || '/%' OR fb.scope = ? OR fb.scope LIKE ? || '/%')"
            )
            params.extend([scope, scope, scope, scope])

        where = " AND ".join(conditions)

        cursor = await self.db.execute(
            f"""SELECT c.*, fa.content as fact_a_content, fa.scope as fact_a_scope,
                       fa.agent_id as fact_a_agent, fa.confidence as fact_a_confidence,
                       fb.content as fact_b_content, fb.scope as fact_b_scope,
                       fb.agent_id as fact_b_agent, fb.confidence as fact_b_confidence
                FROM conflicts c
                JOIN facts fa ON c.fact_a_id = fa.id
                JOIN facts fb ON c.fact_b_id = fb.id
                WHERE {where}
                ORDER BY
                    CASE c.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    c.detected_at DESC""",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str | None = None,
    ) -> bool:
        now = _now_iso()
        cursor = await self.db.execute(
            """UPDATE conflicts
               SET status = ?, resolution_type = ?, resolution = ?,
                   resolved_by = ?, resolved_at = ?
               WHERE id = ? AND status = 'open'""",
            (
                "dismissed" if resolution_type == "dismissed" else "resolved",
                resolution_type,
                resolution,
                resolved_by,
                now,
                conflict_id,
            ),
        )
        if cursor.rowcount > 0 and resolution_type == "dismissed":
            await self.db.execute(
                """INSERT OR REPLACE INTO dismissed_conflicts(conflict_id, workspace_id, dismissed_at)
                   VALUES (?, ?, ?)""",
                (conflict_id, self.workspace_id, now),
            )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_conflict_by_id(self, conflict_id: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_conflict_with_facts(self, conflict_id: str) -> dict | None:
        """Fetch a single conflict with both facts' content joined in (for rendering)."""
        cursor = await self.db.execute(
            """SELECT c.*,
                      fa.content as fact_a_content, fa.scope as fact_a_scope,
                      fa.agent_id as fact_a_agent, fa.confidence as fact_a_confidence,
                      fb.content as fact_b_content, fb.scope as fact_b_scope,
                      fb.agent_id as fact_b_agent, fb.confidence as fact_b_confidence
               FROM conflicts c
               JOIN facts fa ON c.fact_a_id = fa.id
               JOIN facts fb ON c.fact_b_id = fb.id
               WHERE c.id = ?""",
            (conflict_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_conflict_suggestion(
        self,
        conflict_id: str,
        suggested_resolution: str,
        suggested_resolution_type: str,
        suggested_winning_fact_id: str | None,
        suggestion_reasoning: str,
        suggestion_generated_at: str,
    ) -> None:
        """Store the LLM-generated resolution suggestion on a conflict."""
        await self.db.execute(
            """UPDATE conflicts SET
               suggested_resolution = ?,
               suggested_resolution_type = ?,
               suggested_winning_fact_id = ?,
               suggestion_reasoning = ?,
               suggestion_generated_at = ?
               WHERE id = ?""",
            (
                suggested_resolution,
                suggested_resolution_type,
                suggested_winning_fact_id,
                suggestion_reasoning,
                suggestion_generated_at,
                conflict_id,
            ),
        )
        await self.db.commit()

    async def auto_resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str,
        escalated_at: str | None = None,
    ) -> bool:
        """Resolve a conflict programmatically (system-driven). Sets auto_resolved=1."""
        now = _now_iso()
        cursor = await self.db.execute(
            """UPDATE conflicts
               SET status = ?,
                   resolution_type = ?,
                   resolution = ?,
                   resolved_by = ?,
                   resolved_at = ?,
                   auto_resolved = 1,
                   escalated_at = ?
               WHERE id = ? AND status = 'open'""",
            (
                "dismissed" if resolution_type == "dismissed" else "resolved",
                resolution_type,
                resolution,
                resolved_by,
                now,
                escalated_at,
                conflict_id,
            ),
        )
        if cursor.rowcount > 0 and resolution_type == "dismissed":
            await self.db.execute(
                """INSERT OR REPLACE INTO dismissed_conflicts(conflict_id, workspace_id, dismissed_at)
                   VALUES (?, ?, ?)""",
                (conflict_id, self.workspace_id, now),
            )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_stale_open_conflicts(self, older_than_hours: int = 72) -> list[dict]:
        """Return open conflicts in this workspace that have gone unreviewed past the escalation window."""
        cursor = await self.db.execute(
            """SELECT * FROM conflicts
               WHERE status = 'open'
                 AND workspace_id = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM dismissed_conflicts dc
                     WHERE dc.conflict_id = conflicts.id AND dc.workspace_id = conflicts.workspace_id
                 )
                 AND datetime(detected_at) < datetime('now', ? || ' hours')
               ORDER BY detected_at ASC""",
            (
                self.workspace_id,
                f"-{older_than_hours}",
            ),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_detection_feedback(self, conflict_id: str, feedback: str) -> None:
        await self.db.execute(
            "INSERT INTO detection_feedback(conflict_id, feedback, recorded_at) VALUES (?, ?, ?)",
            (conflict_id, feedback, _now_iso()),
        )
        await self.db.commit()

    # ── Agent operations ─────────────────────────────────────────────

    async def upsert_agent(self, agent_id: str, engineer: str = "unknown") -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO agents(agent_id, engineer, registered_at, last_seen, total_commits)
               VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(agent_id) DO UPDATE SET last_seen = ?""",
            (agent_id, engineer, now, now, now),
        )
        await self.db.commit()

    async def increment_agent_commits(self, agent_id: str) -> None:
        await self.db.execute(
            "UPDATE agents SET total_commits = total_commits + 1 WHERE agent_id = ?",
            (agent_id,),
        )
        await self.db.commit()

    async def increment_agent_flagged(self, agent_id: str) -> None:
        await self.db.execute(
            "UPDATE agents SET flagged_commits = flagged_commits + 1 WHERE agent_id = ?",
            (agent_id,),
        )
        await self.db.commit()

    async def get_agent(self, agent_id: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Scope permissions ────────────────────────────────────────────

    async def get_scope_permission(self, agent_id: str, scope: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM scope_permissions WHERE agent_id = ? AND scope = ?",
            (agent_id, scope),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def set_scope_permission(
        self,
        agent_id: str,
        scope: str,
        can_read: bool = True,
        can_write: bool = True,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO scope_permissions(agent_id, scope, can_read, can_write, valid_from, valid_until)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id, scope) DO UPDATE SET
                   can_read = ?, can_write = ?, valid_from = ?, valid_until = ?""",
            (
                agent_id,
                scope,
                int(can_read),
                int(can_write),
                valid_from,
                valid_until,
                int(can_read),
                int(can_write),
                valid_from,
                valid_until,
            ),
        )
        await self.db.commit()

    async def get_facts_by_lineage(self, lineage_id: str) -> list[dict]:
        """Return all facts with the given lineage_id in this workspace, most recent first."""
        cursor = await self.db.execute(
            "SELECT * FROM facts WHERE lineage_id = ? AND workspace_id = ? ORDER BY committed_at DESC",
            (lineage_id, self.workspace_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_active_facts_with_embeddings(self, scope: str, limit: int = 20) -> list[dict]:
        """Return active facts in scope and workspace that have embeddings (for auto-update scoring)."""
        cursor = await self.db.execute(
            """SELECT * FROM facts
               WHERE scope = ?
                 AND workspace_id = ?
                 AND valid_until IS NULL
                 AND embedding IS NOT NULL
               ORDER BY committed_at DESC
               LIMIT ?""",
            (scope, self.workspace_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_fact_embedding(self, fact_id: str, embedding: bytes) -> None:
        """Update the embedding for an existing fact.

        Used when a fact was ingested without an embedding (e.g. via federation,
        which strips binary BLOBs from JSON responses) and needs to be re-embedded
        locally so it participates in semantic search and NLI conflict detection.
        """
        await self.db.execute(
            "UPDATE facts SET embedding = ? WHERE id = ?",
            (embedding, fact_id),
        )
        await self.db.commit()

    async def get_distinct_embedding_models(self) -> list[str]:
        """Return list of distinct embedding_model values in the workspace."""
        cursor = await self.db.execute(
            "SELECT DISTINCT embedding_model FROM facts WHERE embedding_model IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return [row["embedding_model"] for row in rows]

    async def get_facts_by_embedding_model(
        self, embedding_model: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """Return facts with a specific embedding_model for re-embedding."""
        cursor = await self.db.execute(
            """SELECT * FROM facts
               WHERE embedding_model = ? AND valid_until IS NULL
               ORDER BY committed_at DESC
               LIMIT ? OFFSET ?""",
            (embedding_model, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_fact_embedding_with_model(
        self, fact_id: str, embedding: bytes, embedding_model: str, embedding_ver: str
    ) -> None:
        """Update embedding, model, and version for a fact."""
        await self.db.execute(
            """UPDATE facts 
               SET embedding = ?, embedding_model = ?, embedding_ver = ?
               WHERE id = ?""",
            (embedding, embedding_model, embedding_ver, fact_id),
        )
        await self.db.commit()

    async def update_fact_entities(self, fact_id: str, entities_json: str) -> None:
        """Overwrite the entities column for an existing fact."""
        await self.db.execute(
            "UPDATE facts SET entities = ? WHERE id = ?",
            (entities_json, fact_id),
        )
        await self.db.commit()

    async def get_facts_with_empty_entities(self, limit: int = 200, offset: int = 0) -> list[dict]:
        """Return current facts whose entities column is NULL or the empty JSON array.

        Used by the startup entity backfill to re-extract entities for facts that
        were committed before the entity extractor was updated.
        """
        cursor = await self.db.execute(
            """SELECT id, content, scope FROM facts
               WHERE valid_until IS NULL
                 AND (entities IS NULL OR entities = '[]' OR entities = '')
               ORDER BY committed_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Federation: facts since watermark ─────────────────────────────

    async def get_facts_since(
        self, after: str, scope_prefix: str | None = None, limit: int = 1000
    ) -> list[dict]:
        """Pull facts committed after a watermark timestamp (for federation)."""
        conditions = ["committed_at > ?"]
        params: list[Any] = [after]
        if scope_prefix:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope_prefix, scope_prefix])
        params.append(limit)
        where = " AND ".join(conditions)
        cursor = await self.db.execute(
            f"SELECT * FROM facts WHERE {where} ORDER BY committed_at ASC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_facts_added_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        """Return facts committed within a time window."""
        conditions = ["workspace_id = ?", "committed_at >= ?", "committed_at <= ?"]
        params: list[Any] = [self.workspace_id, start, end]
        if scope:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope, scope])
        params.append(limit)
        where = " AND ".join(conditions)
        cursor = await self.db.execute(
            f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                       agent_id, engineer, committed_at, valid_from, valid_until,
                       supersedes_fact_id, durability
                FROM facts
                WHERE {where}
                ORDER BY committed_at ASC
                LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_facts_retired_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        """Return facts whose validity window closed within a time window."""
        conditions = ["workspace_id = ?", "valid_until >= ?", "valid_until <= ?"]
        params: list[Any] = [self.workspace_id, start, end]
        if scope:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope, scope])
        params.append(limit)
        where = " AND ".join(conditions)
        cursor = await self.db.execute(
            f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                       agent_id, engineer, committed_at, valid_from, valid_until,
                       supersedes_fact_id, durability
                FROM facts
                WHERE {where}
                ORDER BY valid_until ASC
                LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_conflicts_resolved_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        """Return conflicts resolved or dismissed within a time window."""
        conditions = [
            "c.workspace_id = ?",
            "c.resolved_at >= ?",
            "c.resolved_at <= ?",
            "c.status != 'open'",
        ]
        params: list[Any] = [self.workspace_id, start, end]
        if scope:
            conditions.append(
                "(fa.scope = ? OR fa.scope LIKE ? || '/%' OR fb.scope = ? OR fb.scope LIKE ? || '/%')"
            )
            params.extend([scope, scope, scope, scope])
        params.append(limit)
        where = " AND ".join(conditions)
        cursor = await self.db.execute(
            f"""SELECT c.*,
                       fa.content AS fact_a_content, fa.scope AS fact_a_scope,
                       fb.content AS fact_b_content, fb.scope AS fact_b_scope
                FROM conflicts c
                JOIN facts fa ON c.fact_a_id = fa.id
                JOIN facts fb ON c.fact_b_id = fb.id
                WHERE {where}
                ORDER BY c.resolved_at ASC
                LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def ingest_remote_fact(self, fact: dict[str, Any]) -> bool:
        """Ingest a fact from a remote Engram instance (federation).

        Returns True if inserted, False if already exists (dedup by id).
        """
        existing = await self.get_fact_by_id(fact["id"])
        if existing:
            return False
        await self.insert_fact(fact)
        return True

    # ── Dashboard query helpers ──────────────────────────────────────

    async def count_facts(self, current_only: bool = True) -> int:
        if current_only:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as cnt FROM facts WHERE valid_until IS NULL AND workspace_id = ?",
                (self.workspace_id,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as cnt FROM facts WHERE workspace_id = ?",
                (self.workspace_id,),
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_conflicts(self, status: str = "open") -> int:
        if status == "all":
            cursor = await self.db.execute(
                """SELECT COUNT(*) as cnt FROM conflicts
                   WHERE workspace_id = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM dismissed_conflicts dc
                         WHERE dc.conflict_id = conflicts.id AND dc.workspace_id = conflicts.workspace_id
                     )""",
                (self.workspace_id,),
            )
        else:
            cursor = await self.db.execute(
                """SELECT COUNT(*) as cnt FROM conflicts
                   WHERE status = ? AND workspace_id = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM dismissed_conflicts dc
                         WHERE dc.conflict_id = conflicts.id AND dc.workspace_id = conflicts.workspace_id
                     )""",
                (status, self.workspace_id),
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_memory_health_score(self) -> dict[str, Any]:
        """Calculate memory health score based on various metrics."""
        total_facts = await self.count_facts(current_only=False)
        current_facts = await self.count_facts(current_only=True)
        open_conflicts = await self.count_conflicts("open")
        resolved_conflicts = await self.count_conflicts("resolved")

        # Calculate health score (0-100)
        # Start with 100, subtract for issues
        score = 100.0

        # Deduct for open conflicts (major issue)
        if total_facts > 0:
            conflict_ratio = open_conflicts / total_facts
            score -= conflict_ratio * 40  # Up to 40 points for conflicts

        # Deduct for low fact retention
        if total_facts > 0:
            retention_ratio = current_facts / total_facts
            score -= (1 - retention_ratio) * 20  # Up to 20 points for expired facts

        score = max(0, min(100, score))  # Clamp to 0-100

        return {
            "score": int(score),
            "total_facts": total_facts,
            "current_facts": current_facts,
            "open_conflicts": open_conflicts,
            "resolved_conflicts": resolved_conflicts,
            "status": "healthy" if score >= 70 else "warning" if score >= 40 else "critical",
        }

    async def get_agents(self) -> list[dict]:
        cursor = await self.db.execute("SELECT * FROM agents ORDER BY last_seen DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_agents_by_ids(self, agent_ids: set[str]) -> dict[str, dict]:
        """Fetch multiple agents by ID in a single query. Returns {agent_id: agent}."""
        if not agent_ids:
            return {}
        placeholders = ",".join(["?"] * len(agent_ids))
        cursor = await self.db.execute(
            f"SELECT * FROM agents WHERE agent_id IN ({placeholders})",
            list(agent_ids),
        )
        rows = await cursor.fetchall()
        return {r["agent_id"]: dict(r) for r in rows}

    async def get_expiring_facts(self, days_ahead: int = 7) -> list[dict]:
        """Get facts with TTL in this workspace that will expire within days_ahead days."""
        cursor = await self.db.execute(
            """SELECT * FROM facts
               WHERE ttl_days IS NOT NULL
                 AND workspace_id = ?
                 AND valid_until IS NOT NULL
                 AND valid_until > datetime('now')
                 AND valid_until < datetime('now', '+' || ? || ' days')
               ORDER BY valid_until ASC""",
            (self.workspace_id, days_ahead),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_fact_timeline(self, scope: str | None = None, limit: int = 100) -> list[dict]:
        """Get facts in this workspace ordered by valid_from for timeline view."""
        conditions: list[str] = ["workspace_id = ?"]
        params: list[Any] = [self.workspace_id]
        if scope:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope, scope])
        where = " AND ".join(conditions)
        params.append(limit)
        cursor = await self.db.execute(
            f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                       agent_id, engineer, committed_at, valid_from, valid_until, ttl_days
                FROM facts WHERE {where}
                ORDER BY valid_from DESC LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_detection_feedback_stats(self) -> dict[str, int]:
        """Get counts of true_positive vs false_positive feedback."""
        cursor = await self.db.execute(
            "SELECT feedback, COUNT(*) as cnt FROM detection_feedback GROUP BY feedback"
        )
        rows = await cursor.fetchall()
        return {r["feedback"]: r["cnt"] for r in rows}

    # ── Workspace stats ───────────────────────────────────────────────

    async def get_workspace_stats(self) -> dict:
        """Return aggregate statistics for the current workspace.

        Runs several focused queries and assembles a single stats dict used
        by the /api/stats REST endpoint and the engram_stats MCP tool.
        """
        ws = self.workspace_id

        # ── facts ──────────────────────────────────────────────────
        cur = await self.db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN valid_until IS NULL THEN 1 ELSE 0 END) as current_count "
            "FROM facts WHERE workspace_id = ?",
            (ws,),
        )
        row = await cur.fetchone()
        total_facts = row["total"] or 0
        current_facts = row["current_count"] or 0

        cur = await self.db.execute(
            "SELECT scope, COUNT(*) as cnt FROM facts "
            "WHERE valid_until IS NULL AND workspace_id = ? "
            "GROUP BY scope ORDER BY cnt DESC LIMIT 10",
            (ws,),
        )
        by_scope = {r["scope"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self.db.execute(
            "SELECT fact_type, COUNT(*) as cnt FROM facts "
            "WHERE valid_until IS NULL AND workspace_id = ? GROUP BY fact_type",
            (ws,),
        )
        by_type = {r["fact_type"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self.db.execute(
            "SELECT durability, COUNT(*) as cnt FROM facts "
            "WHERE valid_until IS NULL AND workspace_id = ? GROUP BY durability",
            (ws,),
        )
        by_durability = {r["durability"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self.db.execute(
            """SELECT id, scope, fact_type, query_hits
               FROM facts
               WHERE valid_until IS NULL
                 AND workspace_id = ?
                 AND query_hits > 0
               ORDER BY query_hits DESC, committed_at DESC
               LIMIT ?""",
            (ws, ANALYTICS_TOP_LIMIT),
        )
        most_queried = [dict(r) for r in await cur.fetchall()]

        cur = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM facts "
            "WHERE ttl_days IS NOT NULL AND valid_until IS NULL AND workspace_id = ? "
            "AND datetime(valid_from, '+' || ttl_days || ' days') < datetime('now', '+7 days')",
            (ws,),
        )
        row = await cur.fetchone()
        expiring_soon = row["cnt"] or 0

        # ── conflicts ───────────────────────────────────────────────
        cur = await self.db.execute(
            "SELECT status, COUNT(*) as cnt FROM conflicts WHERE workspace_id = ? GROUP BY status",
            (ws,),
        )
        conflict_by_status: dict[str, int] = {}
        for r in await cur.fetchall():
            conflict_by_status[r["status"]] = r["cnt"]
        total_conflicts = sum(conflict_by_status.values())
        conflict_rate = round(total_conflicts / total_facts, 4) if total_facts else 0.0

        cur = await self.db.execute(
            "SELECT detection_tier, COUNT(*) as cnt FROM conflicts "
            "WHERE workspace_id = ? GROUP BY detection_tier",
            (ws,),
        )
        conflict_by_tier = {r["detection_tier"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self.db.execute(
            "SELECT conflict_type, COUNT(*) as cnt FROM conflicts "
            "WHERE workspace_id = ? GROUP BY conflict_type",
            (ws,),
        )
        conflict_by_type = {r["conflict_type"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self.db.execute(
            """SELECT substr(detected_at, 1, 10) AS date,
                      status,
                      COUNT(*) AS cnt
               FROM conflicts
               WHERE workspace_id = ?
               GROUP BY date, status
               ORDER BY date DESC
               LIMIT ?""",
            (ws, ANALYTICS_BUCKET_LIMIT * 3),
        )
        buckets: dict[str, dict[str, int | str]] = {}
        for r in await cur.fetchall():
            date = r["date"]
            bucket = buckets.setdefault(
                date,
                {"date": date, "open": 0, "resolved": 0, "dismissed": 0, "total": 0},
            )
            status = r["status"] if r["status"] in {"open", "resolved", "dismissed"} else "total"
            if status != "total":
                bucket[status] = int(bucket[status]) + r["cnt"]
            bucket["total"] = int(bucket["total"]) + r["cnt"]
        conflict_over_time = sorted(buckets.values(), key=lambda item: str(item["date"]))

        # ── agents ──────────────────────────────────────────────────
        cur = await self.db.execute(
            "SELECT agent_id, total_commits, flagged_commits, last_seen FROM agents "
            "WHERE workspace_id = ? ORDER BY total_commits DESC",
            (ws,),
        )
        agent_rows = await cur.fetchall()
        total_agents = len(agent_rows)
        most_active = [
            {
                "agent_id": r["agent_id"],
                "total_commits": r["total_commits"],
                "flagged_commits": r["flagged_commits"],
                "last_seen": r["last_seen"],
            }
            for r in agent_rows[:ANALYTICS_TOP_LIMIT]
        ]
        trust_scores = [
            1.0 - (r["flagged_commits"] / r["total_commits"]) if r["total_commits"] > 0 else 0.8
            for r in agent_rows
        ]
        avg_trust = round(sum(trust_scores) / len(trust_scores), 3) if trust_scores else None

        # ── detection feedback ──────────────────────────────────────
        cur = await self.db.execute(
            "SELECT df.feedback, COUNT(*) as cnt FROM detection_feedback df "
            "JOIN conflicts c ON df.conflict_id = c.id "
            "WHERE c.workspace_id = ? GROUP BY df.feedback",
            (ws,),
        )
        feedback = {r["feedback"]: r["cnt"] for r in await cur.fetchall()}

        return {
            "facts": {
                "total": total_facts,
                "current": current_facts,
                "expiring_soon": expiring_soon,
                "by_scope": by_scope,
                "by_type": by_type,
                "by_durability": by_durability,
                "most_queried": most_queried,
            },
            "conflicts": {
                "open": conflict_by_status.get("open", 0),
                "resolved": conflict_by_status.get("resolved", 0),
                "dismissed": conflict_by_status.get("dismissed", 0),
                "total": total_conflicts,
                "rate": conflict_rate,
                "over_time": conflict_over_time,
                "by_tier": conflict_by_tier,
                "by_type": conflict_by_type,
            },
            "agents": {
                "total": total_agents,
                "most_active": most_active,
                "avg_trust_score": avg_trust,
            },
            "detection": {
                "true_positives": feedback.get("true_positive", 0),
                "false_positives": feedback.get("false_positive", 0),
            },
        }

    # ── Open conflict check for query enrichment ─────────────────────

    async def get_open_conflict_fact_ids(self) -> set[str]:
        cursor = await self.db.execute(
            """SELECT fact_a_id, fact_b_id FROM conflicts
               WHERE status = 'open'
                 AND workspace_id = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM dismissed_conflicts dc
                     WHERE dc.conflict_id = conflicts.id AND dc.workspace_id = conflicts.workspace_id
                 )""",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        ids: set[str] = set()
        for r in rows:
            ids.add(r["fact_a_id"])
            ids.add(r["fact_b_id"])
        return ids

    async def increment_corroboration(self, fact_id: str) -> None:
        """Increment the corroboration counter for a fact (Phase 2: multi-agent consensus)."""
        await self.db.execute(
            "UPDATE facts SET corroborating_agents = corroborating_agents + 1 WHERE id = ?",
            (fact_id,),
        )
        await self.db.commit()

    # ── Workspace / invite key methods (Phase 0) ─────────────────────

    async def ensure_workspace(
        self, engram_id: str, anonymous_mode: bool, anon_agents: bool
    ) -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT OR IGNORE INTO workspaces(engram_id, created_at, anonymous_mode, anon_agents)
               VALUES (?, ?, ?, ?)""",
            (engram_id, now, int(anonymous_mode), int(anon_agents)),
        )
        await self.db.commit()

    async def get_workspace(self, engram_id: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM workspaces WHERE engram_id = ?", (engram_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_workspace_display_name(self, engram_id: str, display_name: str) -> None:
        await self.db.execute(
            "UPDATE workspaces SET display_name = ? WHERE engram_id = ?",
            (display_name, engram_id),
        )
        await self.db.commit()

    async def delete_workspace(self, engram_id: str) -> None:
        await self.db.execute("DELETE FROM invite_keys WHERE engram_id = ?", (engram_id,))
        await self.db.execute(
            "DELETE FROM conflicts WHERE fact_a_id IN (SELECT id FROM facts WHERE workspace_id = ?)",
            (engram_id,),
        )
        await self.db.execute("DELETE FROM facts WHERE workspace_id = ?", (engram_id,))
        await self.db.execute("DELETE FROM workspaces WHERE engram_id = ?", (engram_id,))
        await self.db.commit()

    async def insert_invite_key(
        self,
        key_hash: str,
        engram_id: str,
        expires_at: str | None,
        uses_remaining: int | None,
    ) -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT OR IGNORE INTO invite_keys(key_hash, engram_id, created_at, expires_at, uses_remaining)
               VALUES (?, ?, ?, ?, ?)""",
            (key_hash, engram_id, now, expires_at, uses_remaining),
        )
        await self.db.commit()

    async def validate_invite_key(self, key_hash: str) -> dict | None:
        cursor = await self.db.execute(
            """SELECT * FROM invite_keys
               WHERE key_hash = ?
                 AND (expires_at IS NULL OR expires_at > ?)
                 AND (uses_remaining IS NULL OR uses_remaining > 0)
                 AND revoked_at IS NULL""",
            (key_hash, _now_iso()),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def consume_invite_key(self, key_hash: str) -> dict | None:
        cursor = await self.db.execute(
            """UPDATE invite_keys
               SET uses_remaining = uses_remaining - 1
               WHERE key_hash = ?
                 AND (expires_at IS NULL OR expires_at > ?)
                 AND (uses_remaining IS NULL OR uses_remaining > 0)
                 AND revoked_at IS NULL
               RETURNING *""",
            (key_hash, _now_iso()),
        )
        row = await cursor.fetchone()
        await self.db.commit()
        return dict(row) if row else None

    async def get_key_generation(self, engram_id: str) -> int:
        cursor = await self.db.execute(
            "SELECT key_generation FROM workspaces WHERE engram_id = ?", (engram_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def bump_key_generation(self, engram_id: str) -> int:
        await self.db.execute(
            "UPDATE workspaces SET key_generation = key_generation + 1 WHERE engram_id = ?",
            (engram_id,),
        )
        await self.db.commit()
        return await self.get_key_generation(engram_id)

    async def revoke_all_invite_keys(
        self,
        engram_id: str,
        *,
        grace_minutes: int = 15,
        reason: str | None = None,
    ) -> None:
        # Purge any already-expired grace keys as a side-effect.
        await self.db.execute(
            "DELETE FROM invite_keys WHERE engram_id = ? AND revoked_at IS NOT NULL AND grace_until < datetime('now')",
            (engram_id,),
        )
        if grace_minutes > 0:
            await self.db.execute(
                """UPDATE invite_keys
                   SET revoked_at      = datetime('now'),
                       grace_until     = datetime('now', ? || ' minutes'),
                       rotation_reason = ?
                   WHERE engram_id = ? AND revoked_at IS NULL""",
                (f"+{grace_minutes}", reason, engram_id),
            )
        else:
            await self.db.execute(
                "DELETE FROM invite_keys WHERE engram_id = ? AND revoked_at IS NULL",
                (engram_id,),
            )
        await self.db.commit()

    async def get_active_grace_until(self, engram_id: str) -> str | None:
        cursor = await self.db.execute(
            """SELECT MAX(grace_until) FROM invite_keys
               WHERE engram_id = ?
                 AND revoked_at IS NOT NULL
                 AND grace_until > datetime('now')""",
            (engram_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

    async def cleanup_expired_grace_keys(self, engram_id: str) -> int:
        cursor = await self.db.execute(
            "DELETE FROM invite_keys WHERE engram_id = ? AND revoked_at IS NOT NULL AND grace_until < datetime('now')",
            (engram_id,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def get_key_rotation_history(self, engram_id: str, limit: int = 20) -> list[dict]:
        # In SQLite mode workspace_id in audit_log is self.workspace_id, not engram_id.
        cursor = await self.db.execute(
            """SELECT * FROM audit_log
               WHERE operation = 'key_rotation' AND workspace_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (self.workspace_id, max(1, min(limit, 200))),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_invite_keys(self) -> list[dict]:
        """Return list of active invite keys."""
        cursor = await self.db.execute(
            "SELECT * FROM invite_keys WHERE engram_id = ? ORDER BY created_at DESC",
            (self.engram_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ── Webhook methods ───────────────────────────────────────────────

    async def insert_webhook(self, webhook: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO webhooks(id, url, events, secret, active, created_at, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                webhook["id"],
                webhook["url"],
                webhook["events"],
                webhook.get("secret"),
                1,
                webhook.get("created_at", _now_iso()),
                self.workspace_id,
            ),
        )
        await self.db.commit()

    async def get_webhooks(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM webhooks WHERE workspace_id = ? AND active = 1 ORDER BY created_at DESC",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_webhook_by_id(self, webhook_id: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM webhooks WHERE id = ? AND workspace_id = ?",
            (webhook_id, self.workspace_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_webhook(self, webhook_id: str) -> bool:
        cursor = await self.db.execute(
            "UPDATE webhooks SET active = 0 WHERE id = ? AND workspace_id = ?",
            (webhook_id, self.workspace_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def queue_webhook_delivery(self, delivery: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO webhook_deliveries(id, webhook_id, event, payload, status, attempts, created_at, workspace_id)
               VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)""",
            (
                delivery["id"],
                delivery["webhook_id"],
                delivery["event"],
                delivery["payload"],
                delivery.get("created_at", _now_iso()),
                self.workspace_id,
            ),
        )
        await self.db.commit()

    async def get_pending_deliveries(self) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT * FROM webhook_deliveries
               WHERE status = 'pending' AND attempts < 3 AND workspace_id = ?
               ORDER BY created_at ASC LIMIT 100""",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_delivery_done(self, delivery_id: str) -> None:
        await self.db.execute(
            "UPDATE webhook_deliveries SET status = 'done', attempts = attempts + 1 WHERE id = ?",
            (delivery_id,),
        )
        await self.db.commit()

    async def mark_delivery_failed(self, delivery_id: str) -> None:
        await self.db.execute(
            """UPDATE webhook_deliveries
               SET attempts = attempts + 1,
                   status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END
               WHERE id = ?""",
            (delivery_id,),
        )
        await self.db.commit()

    # ── Resolution rule methods ───────────────────────────────────────

    async def insert_rule(self, rule: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO resolution_rules(id, scope_prefix, condition_type, condition_value,
               resolution_type, created_at, active, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                rule["id"],
                rule["scope_prefix"],
                rule["condition_type"],
                rule["condition_value"],
                rule["resolution_type"],
                rule.get("created_at", _now_iso()),
                self.workspace_id,
            ),
        )
        await self.db.commit()

    async def get_rules(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM resolution_rules WHERE workspace_id = ? AND active = 1 ORDER BY created_at DESC",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_rule_by_id(self, rule_id: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM resolution_rules WHERE id = ? AND workspace_id = ?",
            (rule_id, self.workspace_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_rule(self, rule_id: str) -> bool:
        cursor = await self.db.execute(
            "UPDATE resolution_rules SET active = 0 WHERE id = ? AND workspace_id = ?",
            (rule_id, self.workspace_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # ── Scope registry methods ────────────────────────────────────────

    async def upsert_scope(self, scope_data: dict[str, Any]) -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO scopes(scope, description, owner_agent_id, retention_days, created_at, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(scope, workspace_id) DO UPDATE SET
                   description = COALESCE(excluded.description, description),
                   owner_agent_id = COALESCE(excluded.owner_agent_id, owner_agent_id),
                   retention_days = COALESCE(excluded.retention_days, retention_days)""",
            (
                scope_data["scope"],
                scope_data.get("description"),
                scope_data.get("owner_agent_id"),
                scope_data.get("retention_days"),
                now,
                self.workspace_id,
            ),
        )
        await self.db.commit()

    async def get_scopes(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM scopes WHERE workspace_id = ? ORDER BY scope ASC",
            (self.workspace_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_scope_by_name(self, scope: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM scopes WHERE scope = ? AND workspace_id = ?",
            (scope, self.workspace_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_scope_analytics(self, scope: str) -> dict:
        """Return analytics for a given scope: fact counts, conflict rate, top agent, avg confidence."""
        # Total fact count (all, including retired)
        cur = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM facts WHERE scope = ? AND workspace_id = ?",
            (scope, self.workspace_id),
        )
        row = await cur.fetchone()
        fact_count = row["cnt"] if row else 0

        # Active fact count
        cur = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM facts WHERE scope = ? AND workspace_id = ? AND valid_until IS NULL",
            (scope, self.workspace_id),
        )
        row = await cur.fetchone()
        active_fact_count = row["cnt"] if row else 0

        # Conflict count
        cur = await self.db.execute(
            """SELECT COUNT(*) as cnt FROM conflicts c
               JOIN facts fa ON c.fact_a_id = fa.id
               WHERE fa.scope = ? AND c.workspace_id = ?""",
            (scope, self.workspace_id),
        )
        row = await cur.fetchone()
        conflict_count = row["cnt"] if row else 0

        conflict_rate = round(conflict_count / fact_count, 4) if fact_count > 0 else 0.0

        # Most active agent
        cur = await self.db.execute(
            """SELECT agent_id, COUNT(*) as cnt FROM facts
               WHERE scope = ? AND workspace_id = ?
               GROUP BY agent_id ORDER BY cnt DESC LIMIT 1""",
            (scope, self.workspace_id),
        )
        row = await cur.fetchone()
        most_active_agent = row["agent_id"] if row else None

        # Average confidence
        cur = await self.db.execute(
            "SELECT AVG(confidence) as avg_conf FROM facts WHERE scope = ? AND workspace_id = ? AND valid_until IS NULL",
            (scope, self.workspace_id),
        )
        row = await cur.fetchone()
        avg_confidence = (
            round(float(row["avg_conf"]), 4) if row and row["avg_conf"] is not None else 0.0
        )

        return {
            "scope": scope,
            "fact_count": fact_count,
            "active_fact_count": active_fact_count,
            "conflict_count": conflict_count,
            "conflict_rate": conflict_rate,
            "most_active_agent": most_active_agent,
            "avg_confidence": avg_confidence,
        }

    # ── Audit log methods ─────────────────────────────────────────────

    async def insert_audit_entry(self, entry: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO audit_log(id, operation, agent_id, fact_id, conflict_id, extra, timestamp, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["id"],
                entry["operation"],
                entry.get("agent_id"),
                entry.get("fact_id"),
                entry.get("conflict_id"),
                entry.get("extra"),
                entry.get("timestamp", _now_iso()),
                self.workspace_id,
            ),
        )
        await self.db.commit()

    async def get_audit_log(
        self,
        agent_id: str | None = None,
        operation: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        conditions = ["workspace_id = ?"]
        params: list[Any] = [self.workspace_id]

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if operation:
            conditions.append("operation = ?")
            params.append(operation)
        if from_ts:
            conditions.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts:
            conditions.append("timestamp <= ?")
            params.append(to_ts)

        where = " AND ".join(conditions)
        params.append(limit)
        cursor = await self.db.execute(
            f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def record_usage_event(
        self, event_type: str, quantity: int = 1, billing_period: str | None = None
    ) -> None:
        import uuid

        if billing_period is None:
            from datetime import datetime

            now = datetime.now(timezone.utc)
            billing_period = f"{now.year}-{now.month:02d}"

        await self.db.execute(
            "INSERT INTO usage_events (id, workspace_id, event_type, quantity, billing_period, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                self.workspace_id,
                event_type,
                quantity,
                billing_period,
                _now_iso(),
            ),
        )
        await self.db.commit()

    async def get_usage_events(
        self, event_type: str | None = None, billing_period: str | None = None
    ) -> list[dict]:
        conditions = ["workspace_id = ?"]
        params: list[Any] = [self.workspace_id]

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if billing_period:
            conditions.append("billing_period = ?")
            params.append(billing_period)

        where = " AND ".join(conditions)
        cursor = await self.db.execute(
            f"SELECT * FROM usage_events WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_unsynced_usage_events(self, billing_period: str) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM usage_events WHERE workspace_id = ? AND billing_period = ? AND synced_to_stripe = 0 ORDER BY created_at",
            (self.workspace_id, billing_period),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_usage_events_synced(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" * len(event_ids))
        await self.db.execute(
            f"UPDATE usage_events SET synced_to_stripe = 1 WHERE id IN ({placeholders})",
            event_ids,
        )
        await self.db.commit()

    async def generate_agents_md(self) -> str:
        """Generate AGENTS.md content from workspace facts."""
        current_facts = await self.get_current_facts_in_scope(limit=1000)

        lines = [
            "# AGENTS.md - Agent Guidelines",
            "",
            "This file is auto-generated from workspace knowledge.",
            "",
            "## Project Context",
            "",
        ]

        scopes: dict[str, list[dict]] = {}
        for fact in current_facts:
            scope = fact.get("scope", "general")
            if scope not in scopes:
                scopes[scope] = []
            scopes[scope].append(fact)

        for scope in ["general", "project", "architecture", "setup", "guidelines"]:
            if scope in scopes and scopes[scope]:
                lines.append(f"## {scope.title()}")
                lines.append("")
                for fact in scopes[scope][:5]:
                    lines.append(f"- {fact.get('content', '')[:200]}")
                lines.append("")

        lines.append("## Recent Knowledge")
        lines.append("")
        for fact in current_facts[:10]:
            lines.append(f"- [{fact.get('scope', '')}] {fact.get('content', '')[:150]}")
        lines.append("")

        return "\n".join(lines)

    # ── GDPR subject-erasure ──────────────────────────────────────────

    async def gdpr_soft_erase_agent(self, agent_id: str) -> dict[str, int]:
        """Soft-erase: redact PII, preserve fact content and validity."""
        stats: dict[str, int] = {
            "facts_updated": 0,
            "conflicts_scrubbed": 0,
            "agents_updated": 0,
            "conflicts_closed": 0,
            "scope_permissions_deleted": 0,
            "scopes_updated": 0,
            "audit_rows_scrubbed": 0,
        }

        # 1. Redact engineer + provenance on all fact versions
        cur = await self.db.execute(
            "UPDATE facts SET engineer = '[redacted]', provenance = NULL"
            " WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        stats["facts_updated"] = cur.rowcount

        # 2. Collect fact IDs belonging to this agent
        cur = await self.db.execute(
            "SELECT id FROM facts WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        fact_ids = {r["id"] for r in await cur.fetchall()}

        # 3. Scrub conflict free-text for conflicts touching agent's facts
        if fact_ids:
            placeholders = ",".join("?" * len(fact_ids))
            cur = await self.db.execute(
                f"""UPDATE conflicts
                    SET explanation = '[redacted]',
                        suggested_resolution = NULL,
                        suggested_resolution_type = NULL,
                        suggested_winning_fact_id = NULL,
                        suggestion_reasoning = NULL,
                        suggestion_generated_at = NULL
                    WHERE workspace_id = ?
                      AND (fact_a_id IN ({placeholders}) OR fact_b_id IN ({placeholders}))""",
                (self.workspace_id, *fact_ids, *fact_ids),
            )
            stats["conflicts_scrubbed"] = cur.rowcount

        # 4. Redact agents table
        cur = await self.db.execute(
            "UPDATE agents SET engineer = '[redacted]' WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        stats["agents_updated"] = cur.rowcount

        # 5. Scrub audit log rows where agent_id matches
        cur = await self.db.execute(
            "UPDATE audit_log SET agent_id = NULL WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        stats["audit_rows_scrubbed"] = cur.rowcount

        await self.db.commit()
        return stats

    async def gdpr_hard_erase_agent(self, agent_id: str) -> dict[str, int]:
        """Hard-erase: wipe content, close validity, dismiss open conflicts."""
        now = _now_iso()
        stats: dict[str, int] = {
            "facts_updated": 0,
            "conflicts_closed": 0,
            "conflicts_scrubbed": 0,
            "agents_updated": 0,
            "scope_permissions_deleted": 0,
            "scopes_updated": 0,
            "audit_rows_scrubbed": 0,
        }

        # 1. Collect all fact IDs for this agent
        cur = await self.db.execute(
            "SELECT id, valid_until FROM facts WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        rows = await cur.fetchall()
        fact_ids = [r["id"] for r in rows]

        if fact_ids:
            # 2. Wipe content, keywords, entities, embedding; close open validity windows
            for row in rows:
                fid = row["id"]
                new_valid_until = row["valid_until"] if row["valid_until"] is not None else now
                await self.db.execute(
                    """UPDATE facts
                       SET content = ?,
                           content_hash = ?,
                           engineer = '[redacted]',
                           provenance = NULL,
                           keywords = NULL,
                           entities = NULL,
                           embedding = NULL,
                           valid_until = ?
                       WHERE id = ? AND workspace_id = ?""",
                    (
                        f"[gdpr:erased:{fid}]",
                        f"gdpr:{fid}",
                        new_valid_until,
                        fid,
                        self.workspace_id,
                    ),
                )
            stats["facts_updated"] = len(fact_ids)

            # 3. Sync FTS — delete erased facts from the FTS index
            cur2 = await self.db.execute(
                f"SELECT rowid FROM facts WHERE id IN ({','.join('?' * len(fact_ids))}) AND workspace_id = ?",
                (*fact_ids, self.workspace_id),
            )
            for r in await cur2.fetchall():
                await self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (r[0],))

            placeholders = ",".join("?" * len(fact_ids))

            # 4. Dismiss open conflicts referencing erased facts
            cur = await self.db.execute(
                f"""UPDATE conflicts
                    SET status = 'dismissed',
                        resolution_type = 'gdpr_erasure',
                        resolution = '[redacted]',
                        explanation = '[redacted]',
                        suggested_resolution = NULL,
                        suggested_resolution_type = NULL,
                        suggested_winning_fact_id = NULL,
                        suggestion_reasoning = NULL,
                        suggestion_generated_at = NULL
                    WHERE workspace_id = ?
                      AND status = 'open'
                      AND (fact_a_id IN ({placeholders}) OR fact_b_id IN ({placeholders}))""",
                (self.workspace_id, *fact_ids, *fact_ids),
            )
            stats["conflicts_closed"] = cur.rowcount

            # 5. Scrub free-text on already-resolved conflicts
            cur = await self.db.execute(
                f"""UPDATE conflicts
                    SET explanation = '[redacted]',
                        resolution = '[redacted]',
                        suggested_resolution = NULL,
                        suggested_resolution_type = NULL,
                        suggested_winning_fact_id = NULL,
                        suggestion_reasoning = NULL,
                        suggestion_generated_at = NULL
                    WHERE workspace_id = ?
                      AND status != 'open'
                      AND (fact_a_id IN ({placeholders}) OR fact_b_id IN ({placeholders}))""",
                (self.workspace_id, *fact_ids, *fact_ids),
            )
            stats["conflicts_scrubbed"] = cur.rowcount

        # 6. Redact agents table
        cur = await self.db.execute(
            "UPDATE agents SET engineer = '[redacted]' WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        stats["agents_updated"] = cur.rowcount

        # 7. Delete scope_permissions (no workspace_id column)
        cur = await self.db.execute(
            "DELETE FROM scope_permissions WHERE agent_id = ?",
            (agent_id,),
        )
        stats["scope_permissions_deleted"] = cur.rowcount

        # 8. Null owner_agent_id on scopes owned by this agent
        cur = await self.db.execute(
            "UPDATE scopes SET owner_agent_id = NULL WHERE owner_agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        stats["scopes_updated"] = cur.rowcount

        # 9. Scrub audit log — by actor and by fact_id
        cur = await self.db.execute(
            "UPDATE audit_log SET agent_id = NULL WHERE agent_id = ? AND workspace_id = ?",
            (agent_id, self.workspace_id),
        )
        scrubbed = cur.rowcount
        if fact_ids:
            placeholders = ",".join("?" * len(fact_ids))
            cur = await self.db.execute(
                f"UPDATE audit_log SET fact_id = NULL"
                f" WHERE fact_id IN ({placeholders}) AND workspace_id = ?",
                (*fact_ids, self.workspace_id),
            )
            scrubbed += cur.rowcount
        stats["audit_rows_scrubbed"] = scrubbed

        await self.db.commit()
        return stats

    # ── Temporal Knowledge Graph (TKG) ───────────────────────────────

    async def insert_tkg_node(self, node: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO tkg_nodes (id, name, entity_type, summary, first_seen, last_seen, fact_count, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node["id"],
                node["name"],
                node["entity_type"],
                node.get("summary", ""),
                node["first_seen"],
                node["last_seen"],
                node.get("fact_count", 1),
                node.get("workspace_id", self.workspace_id),
            ),
        )
        await self.db.commit()

    async def get_tkg_node_by_name(self, name: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM tkg_nodes WHERE name = ? AND workspace_id = ?",
            (name, self.workspace_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)

    async def get_tkg_node_by_id(self, node_id: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM tkg_nodes WHERE id = ?",
            (node_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)

    async def update_tkg_node_seen(self, node_id: str, timestamp: str) -> None:
        await self.db.execute(
            "UPDATE tkg_nodes SET last_seen = ?, fact_count = fact_count + 1 WHERE id = ?",
            (timestamp, node_id),
        )
        await self.db.commit()

    async def insert_tkg_edge(self, edge: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO tkg_edges
               (id, source_node_id, target_node_id, relation_type, fact_label,
                fact_id, agent_id, scope, created_at, expired_at, valid_at,
                invalid_at, confidence, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                edge["id"],
                edge["source_node_id"],
                edge["target_node_id"],
                edge["relation_type"],
                edge["fact_label"],
                edge["fact_id"],
                edge["agent_id"],
                edge["scope"],
                edge["created_at"],
                edge.get("expired_at"),
                edge.get("valid_at"),
                edge.get("invalid_at"),
                edge.get("confidence", 0.8),
                edge.get("workspace_id", self.workspace_id),
            ),
        )
        await self.db.commit()

    async def get_active_tkg_edges(self, source_node_id: str, relation_type: str) -> list[dict]:
        cur = await self.db.execute(
            """SELECT * FROM tkg_edges
               WHERE source_node_id = ? AND relation_type = ? AND expired_at IS NULL
               AND workspace_id = ?""",
            (source_node_id, relation_type, self.workspace_id),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def expire_tkg_edge(self, edge_id: str, expired_at: str) -> None:
        await self.db.execute(
            "UPDATE tkg_edges SET expired_at = ? WHERE id = ?",
            (expired_at, edge_id),
        )
        await self.db.commit()

    async def get_tkg_edges_for_node(
        self,
        node_id: str,
        relation_type: str | None = None,
        include_expired: bool = True,
    ) -> list[dict]:
        if relation_type:
            if include_expired:
                cur = await self.db.execute(
                    """SELECT * FROM tkg_edges
                       WHERE (source_node_id = ? OR target_node_id = ?)
                       AND relation_type = ? AND workspace_id = ?
                       ORDER BY created_at""",
                    (node_id, node_id, relation_type, self.workspace_id),
                )
            else:
                cur = await self.db.execute(
                    """SELECT * FROM tkg_edges
                       WHERE (source_node_id = ? OR target_node_id = ?)
                       AND relation_type = ? AND expired_at IS NULL AND workspace_id = ?
                       ORDER BY created_at""",
                    (node_id, node_id, relation_type, self.workspace_id),
                )
        else:
            if include_expired:
                cur = await self.db.execute(
                    """SELECT * FROM tkg_edges
                       WHERE (source_node_id = ? OR target_node_id = ?)
                       AND workspace_id = ?
                       ORDER BY created_at""",
                    (node_id, node_id, self.workspace_id),
                )
            else:
                cur = await self.db.execute(
                    """SELECT * FROM tkg_edges
                       WHERE (source_node_id = ? OR target_node_id = ?)
                       AND expired_at IS NULL AND workspace_id = ?
                       ORDER BY created_at""",
                    (node_id, node_id, self.workspace_id),
                )
        return [dict(r) for r in await cur.fetchall()]

    async def get_tkg_nodes_with_expired_edges(self, scope: str | None = None) -> list[dict]:
        if scope:
            cur = await self.db.execute(
                """SELECT DISTINCT n.* FROM tkg_nodes n
                   JOIN tkg_edges e ON n.id = e.source_node_id
                   WHERE e.expired_at IS NOT NULL AND e.scope = ?
                   AND n.workspace_id = ?""",
                (scope, self.workspace_id),
            )
        else:
            cur = await self.db.execute(
                """SELECT DISTINCT n.* FROM tkg_nodes n
                   JOIN tkg_edges e ON n.id = e.source_node_id
                   WHERE e.expired_at IS NOT NULL
                   AND n.workspace_id = ?""",
                (self.workspace_id,),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def get_old_active_tkg_edges(
        self, max_age_days: int = 30, scope: str | None = None
    ) -> list[dict]:
        cutoff = datetime.now(timezone.utc).isoformat()
        # Use string comparison for ISO timestamps — works for SQLite
        if scope:
            cur = await self.db.execute(
                """SELECT * FROM tkg_edges
                   WHERE expired_at IS NULL AND scope = ?
                   AND julianday(?) - julianday(created_at) > ?
                   AND workspace_id = ?""",
                (scope, cutoff, max_age_days, self.workspace_id),
            )
        else:
            cur = await self.db.execute(
                """SELECT * FROM tkg_edges
                   WHERE expired_at IS NULL
                   AND julianday(?) - julianday(created_at) > ?
                   AND workspace_id = ?""",
                (cutoff, max_age_days, self.workspace_id),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def get_newer_tkg_edges(self, source_node_id: str, after: str) -> list[dict]:
        cur = await self.db.execute(
            """SELECT * FROM tkg_edges
               WHERE source_node_id = ? AND created_at > ?
               AND workspace_id = ?""",
            (source_node_id, after, self.workspace_id),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_tkg_multi_agent_edges(self, scope: str | None = None) -> list[dict]:
        """Return active edges where the same source+relation has edges from multiple agents."""
        if scope:
            cur = await self.db.execute(
                """SELECT e.* FROM tkg_edges e
                   WHERE e.expired_at IS NULL AND e.scope = ? AND e.workspace_id = ?
                   AND EXISTS (
                       SELECT 1 FROM tkg_edges e2
                       WHERE e2.source_node_id = e.source_node_id
                       AND e2.relation_type = e.relation_type
                       AND e2.agent_id != e.agent_id
                       AND e2.expired_at IS NULL
                       AND e2.workspace_id = e.workspace_id
                   )""",
                (scope, self.workspace_id),
            )
        else:
            cur = await self.db.execute(
                """SELECT e.* FROM tkg_edges e
                   WHERE e.expired_at IS NULL AND e.workspace_id = ?
                   AND EXISTS (
                       SELECT 1 FROM tkg_edges e2
                       WHERE e2.source_node_id = e.source_node_id
                       AND e2.relation_type = e.relation_type
                       AND e2.agent_id != e.agent_id
                       AND e2.expired_at IS NULL
                       AND e2.workspace_id = e.workspace_id
                   )""",
                (self.workspace_id,),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def get_tkg_stats(self, scope: str | None = None) -> dict[str, int]:
        stats: dict[str, int] = {}
        cur = await self.db.execute(
            "SELECT COUNT(*) FROM tkg_nodes WHERE workspace_id = ?",
            (self.workspace_id,),
        )
        stats["total_nodes"] = (await cur.fetchone())[0]

        if scope:
            cur = await self.db.execute(
                "SELECT COUNT(*) FROM tkg_edges WHERE workspace_id = ? AND scope = ?",
                (self.workspace_id, scope),
            )
        else:
            cur = await self.db.execute(
                "SELECT COUNT(*) FROM tkg_edges WHERE workspace_id = ?",
                (self.workspace_id,),
            )
        stats["total_edges"] = (await cur.fetchone())[0]

        if scope:
            cur = await self.db.execute(
                "SELECT COUNT(*) FROM tkg_edges WHERE expired_at IS NULL AND workspace_id = ? AND scope = ?",
                (self.workspace_id, scope),
            )
        else:
            cur = await self.db.execute(
                "SELECT COUNT(*) FROM tkg_edges WHERE expired_at IS NULL AND workspace_id = ?",
                (self.workspace_id,),
            )
        stats["active_edges"] = (await cur.fetchone())[0]
        stats["expired_edges"] = stats["total_edges"] - stats["active_edges"]

        cur = await self.db.execute(
            "SELECT COUNT(DISTINCT relation_type) FROM tkg_edges WHERE workspace_id = ?",
            (self.workspace_id,),
        )
        stats["unique_relations"] = (await cur.fetchone())[0]

        return stats

    async def update_tkg_node_summary(self, node_id: str, summary: str) -> None:
        await self.db.execute(
            "UPDATE tkg_nodes SET summary = ? WHERE id = ?",
            (summary, node_id),
        )
        await self.db.commit()

    async def get_all_tkg_nodes(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM tkg_nodes WHERE workspace_id = ?",
            (self.workspace_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def enqueue_deferred_scan(self, scan: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT INTO deferred_scans
               (id, workspace_id, queued_at, scheduled_for, status, payload)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (
                scan["id"],
                self.workspace_id,
                scan["queued_at"],
                scan["scheduled_for"],
                scan.get("payload", "{}"),
            ),
        )
        await self.db.commit()

    async def get_pending_deferred_scans(self, before: str) -> list[dict]:
        cur = await self.db.execute(
            """SELECT * FROM deferred_scans
               WHERE workspace_id = ? AND status = 'pending' AND scheduled_for <= ?
               ORDER BY scheduled_for""",
            (self.workspace_id, before),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def update_deferred_scan_status(
        self, scan_id: str, status: str, fact_count: int = 0, completed_at: str | None = None
    ) -> None:
        await self.db.execute(
            """UPDATE deferred_scans
               SET status = ?, result_fact_count = ?, completed_at = ?
               WHERE id = ?""",
            (status, fact_count, completed_at, scan_id),
        )
        await self.db.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Backward-compatible alias — existing imports of `Storage` still work
Storage = SQLiteStorage
