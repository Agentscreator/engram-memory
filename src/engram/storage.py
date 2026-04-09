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
    async def expire_ttl_facts(self) -> int: ...

    @abstractmethod
    async def get_current_facts_in_scope(
        self,
        scope: str | None = None,
        fact_type: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
        include_ephemeral: bool = False,
    ) -> list[dict]: ...

    @abstractmethod
    async def fts_search(self, query: str, limit: int = 20) -> list[int]: ...

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
    async def get_conflicting_fact_ids(self, fact_id: str) -> set[str]:
        """Return all fact IDs that already have any conflict with fact_id."""
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
    async def conflict_exists(self, fact_a_id: str, fact_b_id: str) -> bool: ...

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
    async def get_facts_since(
        self, after: str, scope_prefix: str | None = None, limit: int = 1000
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

    async def revoke_all_invite_keys(self, engram_id: str) -> None:
        """Delete all invite keys for a workspace. Default no-op."""

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
            "durability",
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

    async def expire_ttl_facts(self) -> int:
        """Close validity windows for TTL-expired facts in this workspace. Returns count."""
        now = _now_iso()
        cursor = await self.db.execute(
            """UPDATE facts SET valid_until = ?
               WHERE ttl_days IS NOT NULL
                 AND valid_until IS NULL
                 AND workspace_id = ?
                 AND datetime(valid_from, '+' || ttl_days || ' days') < ?""",
            (now, self.workspace_id, now),
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

        cursor = await self.db.execute(
            f"SELECT * FROM facts WHERE {where} ORDER BY committed_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def fts_search(self, query: str, limit: int = 20) -> list[int]:
        """FTS5 BM25 search. Returns rowids ordered by relevance."""
        cursor = await self.db.execute(
            "SELECT rowid, rank FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
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

    async def get_conflicting_fact_ids(self, fact_id: str) -> set[str]:
        """Return all fact IDs that already have any conflict (any status) with fact_id."""
        cursor = await self.db.execute(
            """SELECT fact_a_id, fact_b_id FROM conflicts
               WHERE workspace_id = ?
                 AND (fact_a_id = ? OR fact_b_id = ?)""",
            (self.workspace_id, fact_id, fact_id),
        )
        rows = await cursor.fetchall()
        result: set[str] = set()
        for r in rows:
            other = r["fact_b_id"] if r["fact_a_id"] == fact_id else r["fact_a_id"]
            result.add(other)
        return result

    async def promote_fact(self, fact_id: str) -> bool:
        """Promote an ephemeral fact to durable. Returns True if promoted."""
        cursor = await self.db.execute(
            "UPDATE facts SET durability = 'durable' WHERE id = ? AND durability = 'ephemeral'",
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
            "workspace_id",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        defaults = {"workspace_id": self.workspace_id}
        values = [conflict.get(c, defaults.get(c)) for c in cols]
        await self.db.execute(
            f"INSERT INTO conflicts ({col_names}) VALUES ({placeholders})", values
        )
        await self.db.commit()

    async def conflict_exists(self, fact_a_id: str, fact_b_id: str) -> bool:
        """Check if a conflict already exists between two facts (in either order) within this workspace."""
        cursor = await self.db.execute(
            """SELECT 1 FROM conflicts
               WHERE workspace_id = ?
                 AND ((fact_a_id = ? AND fact_b_id = ?)
                  OR  (fact_a_id = ? AND fact_b_id = ?))""",
            (self.workspace_id, fact_a_id, fact_b_id, fact_b_id, fact_a_id),
        )
        return await cursor.fetchone() is not None

    async def get_conflicts(self, scope: str | None = None, status: str = "open") -> list[dict]:
        conditions = ["c.workspace_id = ?"]
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
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_stale_open_conflicts(self, older_than_hours: int = 72) -> list[dict]:
        """Return open conflicts in this workspace that have gone unreviewed past the escalation window."""
        cursor = await self.db.execute(
            """SELECT * FROM conflicts
               WHERE status = 'open'
                 AND workspace_id = ?
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
                "SELECT COUNT(*) as cnt FROM conflicts WHERE workspace_id = ?",
                (self.workspace_id,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as cnt FROM conflicts WHERE status = ? AND workspace_id = ?",
                (status, self.workspace_id),
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

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

        cur = await self.db.execute(
            "SELECT detection_tier, COUNT(*) as cnt FROM conflicts "
            "WHERE workspace_id = ? GROUP BY detection_tier",
            (ws,),
        )
        conflict_by_tier = {r["detection_tier"]: r["cnt"] for r in await cur.fetchall()}

        # ── agents ──────────────────────────────────────────────────
        cur = await self.db.execute(
            "SELECT agent_id, total_commits, flagged_commits FROM agents "
            "WHERE workspace_id = ? ORDER BY total_commits DESC",
            (ws,),
        )
        agent_rows = await cur.fetchall()
        total_agents = len(agent_rows)
        most_active = agent_rows[0]["agent_id"] if agent_rows else None
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
            },
            "conflicts": {
                "open": conflict_by_status.get("open", 0),
                "resolved": conflict_by_status.get("resolved", 0),
                "dismissed": conflict_by_status.get("dismissed", 0),
                "total": sum(conflict_by_status.values()),
                "by_tier": conflict_by_tier,
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
            "SELECT fact_a_id, fact_b_id FROM conflicts WHERE status = 'open' AND workspace_id = ?",
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
                 AND (uses_remaining IS NULL OR uses_remaining > 0)""",
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

    async def revoke_all_invite_keys(self, engram_id: str) -> None:
        await self.db.execute("DELETE FROM invite_keys WHERE engram_id = ?", (engram_id,))
        await self.db.commit()

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
        avg_confidence = round(float(row["avg_conf"]), 4) if row and row["avg_conf"] is not None else 0.0

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Backward-compatible alias — existing imports of `Storage` still work
Storage = SQLiteStorage
