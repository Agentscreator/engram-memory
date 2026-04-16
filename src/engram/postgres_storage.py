"""PostgreSQL storage backend for team mode (ENGRAM_DB_URL set).

Uses asyncpg. Implements the same BaseStorage interface as SQLiteStorage.
Install the team extra to get asyncpg: pip install engram-team[team]

Key differences from SQLiteStorage:
- $1/$2/... placeholders instead of ?
- JSONB for entities column (native JSON operators)
- tsvector GENERATED column for full-text search (GIN index)
- pgvector for embedding similarity (vector type)
- TIMESTAMPTZ instead of TEXT for timestamps
- ON CONFLICT DO UPDATE / INSERT ... ON CONFLICT for upserts
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from engram.schema import POSTGRES_SCHEMA_SQL
from engram.storage import ANALYTICS_BUCKET_LIMIT, ANALYTICS_TOP_LIMIT, BaseStorage

logger = logging.getLogger("engram")


class PostgresStorage(BaseStorage):
    """Async PostgreSQL storage using asyncpg."""

    def __init__(self, db_url: str, workspace_id: str = "local", schema: str = "engram") -> None:
        self.db_url = db_url
        self.workspace_id = workspace_id
        self.schema = schema
        self._pool: Any = None  # asyncpg.Pool

    async def connect(self) -> None:
        try:
            import asyncpg
        except ImportError:
            raise RuntimeError(
                "asyncpg is required for team mode. Install it with: pip install engram-team[team]"
            )

        async def _set_path(conn: Any) -> None:
            await conn.execute(f"SET search_path TO {self.schema}, public")

        self._pool = await asyncpg.create_pool(self.db_url, min_size=2, max_size=10, init=_set_path)
        async with self._pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            await conn.execute(f"SET search_path TO {self.schema}, public")
            await conn.execute(POSTGRES_SCHEMA_SQL)
        logger.info(
            "PostgreSQL connected (workspace: %s, schema: %s)", self.workspace_id, self.schema
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("PostgresStorage not connected. Call connect() first.")
        return self._pool

    class _ConnectionWrapper:
        def __init__(self, pool: Any, postgres_storage: "PostgresStorage"):
            self._pool = pool
            self._ps = postgres_storage
            self._conn = None

        async def __aenter__(self) -> Any:
            self._conn = await self._pool.acquire()
            await self._conn.execute(f"SET search_path TO {self._ps.schema}, public")
            return self._conn

        async def __aexit__(self, *args: Any) -> None:
            if self._conn:
                await self._pool.release(self._conn)

    def acquire(self) -> _ConnectionWrapper:
        return self._ConnectionWrapper(self._pool, self)

    @property
    def connected(self) -> bool:
        return self._pool is not None

    # ── Fact operations ──────────────────────────────────────────────

    async def insert_fact(self, fact: dict[str, Any]) -> int:
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
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        col_names = ", ".join(cols)

        # entities must be a JSON string for asyncpg to handle as jsonb
        values = []
        for c in cols:
            v = fact.get(c)
            if c == "workspace_id" and v is None:
                v = self.workspace_id
            if c == "entities" and isinstance(v, str):
                # Already a JSON string — asyncpg needs the raw value for jsonb
                try:
                    v = json.loads(v)
                except Exception:
                    v = None
            values.append(v)

        async with self.acquire() as conn:
            # asyncpg returns the row; we use id as the "rowid" equivalent
            await conn.execute(f"INSERT INTO facts ({col_names}) VALUES ({placeholders})", *values)
            # For FTS compatibility, return 0 (PostgreSQL uses generated tsvector)
            return 0

    async def find_duplicate(self, content_hash: str, scope: str) -> str | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM facts WHERE content_hash = $1 AND scope = $2 "
                "AND valid_until IS NULL AND workspace_id = $3",
                content_hash,
                scope,
                self.workspace_id,
            )
        return row["id"] if row else None

    async def close_validity_window(
        self, *, lineage_id: str | None = None, fact_id: str | None = None
    ) -> None:
        now = _now_ts()
        async with self.acquire() as conn:
            if lineage_id:
                await conn.execute(
                    "UPDATE facts SET valid_until = $1 WHERE lineage_id = $2 "
                    "AND valid_until IS NULL AND workspace_id = $3",
                    now,
                    lineage_id,
                    self.workspace_id,
                )
            elif fact_id:
                await conn.execute(
                    "UPDATE facts SET valid_until = $1 WHERE id = $2 "
                    "AND valid_until IS NULL AND workspace_id = $3",
                    now,
                    fact_id,
                    self.workspace_id,
                )

    async def expire_ttl_facts(self) -> int:
        now = _now_ts()
        async with self.acquire() as conn:
            await conn.execute(f"SET search_path TO {self.schema}, public")
            result = await conn.execute(
                "UPDATE facts SET valid_until = $1 "
                "WHERE ttl_days IS NOT NULL AND valid_until IS NULL "
                "AND workspace_id = $2 "
                "AND valid_from + (ttl_days * INTERVAL '1 day') < $1",
                now,
                self.workspace_id,
            )
        # asyncpg returns "UPDATE N"
        return int(result.split()[-1])

    # ── Query operations ─────────────────────────────────────────────

    async def get_distinct_scopes(self) -> list[str]:
        """Return all unique scope values for the workspace."""
        rows = await self.pool.fetch(
            "SELECT DISTINCT scope FROM facts WHERE workspace_id = $1 AND valid_until IS NULL",
            self.workspace_id,
        )
        return [r["scope"] for r in rows]

    async def get_current_facts_in_scope(
        self,
        scope: str | None = None,
        fact_type: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
        include_ephemeral: bool = False,
    ) -> list[dict]:
        conditions = ["workspace_id = $1"]
        params: list[Any] = [self.workspace_id]
        idx = 2

        if as_of:
            conditions.append(f"valid_from <= ${idx}")
            params.append(as_of)
            idx += 1
            conditions.append(f"(valid_until IS NULL OR valid_until > ${idx})")
            params.append(as_of)
            idx += 1
        else:
            conditions.append("valid_until IS NULL")

        if scope:
            conditions.append(f"(scope = ${idx} OR scope LIKE ${idx} || '/%')")
            params.append(scope)
            idx += 1

        if fact_type:
            conditions.append(f"fact_type = ${idx}")
            params.append(fact_type)
            idx += 1

        if not include_ephemeral:
            conditions.append("durability = 'durable'")

        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM facts WHERE {where} ORDER BY committed_at DESC LIMIT ${idx}",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def fts_search(self, query: str, limit: int = 20, offset: int = 0) -> list[int]:
        """Full-text search using tsvector. Returns a list of pseudo-rowids (not used in PG)."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank "
                "FROM facts WHERE search_vector @@ plainto_tsquery('english', $1) "
                "AND workspace_id = $2 AND valid_until IS NULL "
                "ORDER BY rank DESC LIMIT $3 OFFSET $4",
                query,
                self.workspace_id,
                limit,
                offset,
            )
        return [r["id"] for r in rows]

    async def generate_agents_md(self) -> str:
        """Generate AGENTS.md content from workspace facts.

        Creates a CONTRIBUTING.md-style document with project context,
        key facts, and important guidelines extracted from workspace memory.
        """
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

        main_scopes = ["general", "project", "architecture", "setup", "guidelines"]
        for scope in main_scopes:
            if scope in scopes and scopes[scope]:
                lines.append(f"## {scope.title()}")
                lines.append("")
                for fact in scopes[scope][:5]:
                    content = fact.get("content", "")[:200]
                    lines.append(f"- {content}")
                lines.append("")

        lines.append("## Recent Knowledge")
        lines.append("")
        for fact in current_facts[:10]:
            content = fact.get("content", "")[:150]
            scope = fact.get("scope", "")
            lines.append(f"- [{scope}] {content}")
        lines.append("")

        return "\n".join(lines)

    async def get_facts_by_rowids(self, rowids: list[int]) -> list[dict]:
        """In PostgreSQL mode rowids are actually fact IDs (strings) from fts_search."""
        if not rowids:
            return []
        placeholders = ", ".join(f"${i + 2}" for i in range(len(rowids)))
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM facts WHERE workspace_id = $1 AND id IN ({placeholders})",
                self.workspace_id,
                *rowids,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_fact_by_id(self, fact_id: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM facts WHERE id = $1 AND workspace_id = $2",
                fact_id,
                self.workspace_id,
            )
        return _row_to_dict(row) if row else None

    async def get_facts_by_ids(self, ids: list[str]) -> dict[str, dict]:
        """Batch-fetch multiple facts by ID in a single query. Returns {id: fact_row}."""
        if not ids:
            return {}
        placeholders = ", ".join(f"${i + 2}" for i in range(len(ids)))
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM facts WHERE workspace_id = $1 AND id IN ({placeholders})",
                self.workspace_id,
                *ids,
            )
        return {r["id"]: _row_to_dict(r) for r in rows}

    async def get_conflicting_fact_ids(self, fact_id: str) -> set[str]:
        """Return all fact IDs that already have any conflict (any status) with fact_id."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT fact_a_id, fact_b_id FROM conflicts "
                "WHERE workspace_id = $1 AND (fact_a_id = $2 OR fact_b_id = $2)",
                self.workspace_id,
                fact_id,
            )
        result: set[str] = set()
        for r in rows:
            other = r["fact_b_id"] if r["fact_a_id"] == fact_id else r["fact_a_id"]
            result.add(other)
        return result

    async def promote_fact(self, fact_id: str) -> bool:
        """Promote an ephemeral fact to durable. Returns True if promoted."""
        async with self.acquire() as conn:
            result = await conn.execute(
                "UPDATE facts SET durability = 'durable' "
                "WHERE id = $1 AND durability = 'ephemeral' AND workspace_id = $2",
                fact_id,
                self.workspace_id,
            )
        return result.split()[-1] != "0"

    async def increment_query_hits(self, fact_ids: list[str]) -> None:
        """Increment query_hits counter for the given fact IDs."""
        if not fact_ids:
            return
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE facts SET query_hits = query_hits + 1 "
                "WHERE id = ANY($1::text[]) AND workspace_id = $2",
                fact_ids,
                self.workspace_id,
            )

    async def get_promotable_ephemeral_facts(self, min_hits: int = 2) -> list[dict]:
        """Return ephemeral facts that have been queried enough times to auto-promote."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM facts WHERE durability = 'ephemeral' AND valid_until IS NULL "
                "AND query_hits >= $1 AND workspace_id = $2",
                min_hits,
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_facts_by_durability(self, durability: str) -> list[dict]:
        """Return all facts with the given durability level."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM facts WHERE durability = $1 AND valid_until IS NULL "
                "AND workspace_id = $2",
                durability,
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    async def retire_stale_facts(self) -> int:
        """Retire stale, low-value facts via importance-based decay."""
        now = _now_ts()
        total = 0
        async with self.acquire() as conn:
            # 1. Unverified inferences older than 30 days
            result = await conn.execute(
                "UPDATE facts SET valid_until = $1 "
                "WHERE valid_until IS NULL "
                "AND fact_type = 'inference' "
                "AND provenance IS NULL "
                "AND corroborating_agents = 0 "
                "AND workspace_id = $2 "
                "AND committed_at + INTERVAL '30 days' < $1",
                now,
                self.workspace_id,
            )
            total += int(result.split()[-1])

            # 2. Unverified, uncorroborated observations older than 90 days
            result = await conn.execute(
                "UPDATE facts SET valid_until = $1 "
                "WHERE valid_until IS NULL "
                "AND fact_type = 'observation' "
                "AND provenance IS NULL "
                "AND corroborating_agents = 0 "
                "AND workspace_id = $2 "
                "AND committed_at + INTERVAL '90 days' < $1",
                now,
                self.workspace_id,
            )
            total += int(result.split()[-1])

        return total

    # ── Entity-based lookups ─────────────────────────────────────────

    async def find_entity_conflicts(
        self, entity_name: str, entity_type: str, entity_value: str, scope: str, exclude_id: str
    ) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """SELECT f.* FROM facts f,
                   jsonb_array_elements(f.entities) AS e
                   WHERE f.valid_until IS NULL
                     AND f.workspace_id = $1
                     AND f.id != $2
                     AND f.scope = $3
                     AND e->>'name' = $4
                     AND e->>'type' = $5
                     AND e->>'value' IS NOT NULL
                     AND e->>'value' != $6""",
                self.workspace_id,
                exclude_id,
                scope,
                entity_name,
                entity_type,
                str(entity_value),
            )
        return [_row_to_dict(r) for r in rows]

    async def find_cross_scope_entity_matches(
        self, entity_name: str, entity_type: str, entity_value: str, exclude_id: str
    ) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """SELECT f.* FROM facts f,
                   jsonb_array_elements(f.entities) AS e
                   WHERE f.valid_until IS NULL
                     AND f.workspace_id = $1
                     AND f.id != $2
                     AND e->>'name' = $3
                     AND e->>'type' = $4
                     AND (e->>'value' IS NULL OR e->>'value' != $5)""",
                self.workspace_id,
                exclude_id,
                entity_name,
                entity_type,
                str(entity_value),
            )
        return [_row_to_dict(r) for r in rows]

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
            "conflict_type",
            "workspace_id",
        ]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        col_names = ", ".join(cols)
        _defaults = {"workspace_id": self.workspace_id, "conflict_type": "genuine"}
        values = [conflict.get(c, _defaults.get(c)) for c in cols]
        async with self.acquire() as conn:
            await conn.execute(
                f"INSERT INTO conflicts ({col_names}) VALUES ({placeholders})", *values
            )

    async def conflict_exists(self, fact_a_id: str, fact_b_id: str) -> bool:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM conflicts WHERE "
                "((fact_a_id = $1 AND fact_b_id = $2) OR (fact_a_id = $2 AND fact_b_id = $1)) "
                "AND workspace_id = $3",
                fact_a_id,
                fact_b_id,
                self.workspace_id,
            )
        return row is not None

    async def get_conflicts(self, scope: str | None = None, status: str = "open") -> list[dict]:
        conditions = ["c.workspace_id = $1"]
        params: list[Any] = [self.workspace_id]
        idx = 2

        if status != "all":
            conditions.append(f"c.status = ${idx}")
            params.append(status)
            idx += 1

        if scope:
            conditions.append(
                f"(fa.scope = ${idx} OR fa.scope LIKE ${idx} || '/%' "
                f"OR fb.scope = ${idx} OR fb.scope LIKE ${idx} || '/%')"
            )
            params.append(scope)
            idx += 1

        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT c.*,
                           fa.content AS fact_a_content, fa.scope AS fact_a_scope,
                           fa.agent_id AS fact_a_agent, fa.confidence AS fact_a_confidence,
                           fb.content AS fact_b_content, fb.scope AS fact_b_scope,
                           fb.agent_id AS fact_b_agent, fb.confidence AS fact_b_confidence
                    FROM conflicts c
                    JOIN facts fa ON c.fact_a_id = fa.id
                    JOIN facts fb ON c.fact_b_id = fb.id
                    WHERE {where}
                    ORDER BY
                        CASE c.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                        c.detected_at DESC""",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str | None = None,
    ) -> bool:
        now = _now_ts()
        new_status = "dismissed" if resolution_type == "dismissed" else "resolved"
        async with self.acquire() as conn:
            result = await conn.execute(
                "UPDATE conflicts SET status=$1, resolution_type=$2, resolution=$3, "
                "resolved_by=$4, resolved_at=$5 "
                "WHERE id=$6 AND status='open' AND workspace_id=$7",
                new_status,
                resolution_type,
                resolution,
                resolved_by,
                now,
                conflict_id,
                self.workspace_id,
            )
        return result == "UPDATE 1"

    async def get_conflict_by_id(self, conflict_id: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM conflicts WHERE id = $1 AND workspace_id = $2",
                conflict_id,
                self.workspace_id,
            )
        return _row_to_dict(row) if row else None

    async def get_conflict_with_facts(self, conflict_id: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT c.*,
                          fa.content AS fact_a_content, fa.scope AS fact_a_scope,
                          fa.agent_id AS fact_a_agent, fa.confidence AS fact_a_confidence,
                          fb.content AS fact_b_content, fb.scope AS fact_b_scope,
                          fb.agent_id AS fact_b_agent, fb.confidence AS fact_b_confidence
                   FROM conflicts c
                   JOIN facts fa ON c.fact_a_id = fa.id
                   JOIN facts fb ON c.fact_b_id = fb.id
                   WHERE c.id = $1 AND c.workspace_id = $2""",
                conflict_id,
                self.workspace_id,
            )
        return _row_to_dict(row) if row else None

    async def update_conflict_suggestion(
        self,
        conflict_id: str,
        suggested_resolution: str,
        suggested_resolution_type: str,
        suggested_winning_fact_id: str | None,
        suggestion_reasoning: str,
        suggestion_generated_at: str,
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE conflicts SET suggested_resolution=$1, suggested_resolution_type=$2, "
                "suggested_winning_fact_id=$3, suggestion_reasoning=$4, "
                "suggestion_generated_at=$5 WHERE id=$6 AND workspace_id=$7",
                suggested_resolution,
                suggested_resolution_type,
                suggested_winning_fact_id,
                suggestion_reasoning,
                suggestion_generated_at,
                conflict_id,
                self.workspace_id,
            )

    async def auto_resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        resolved_by: str,
        escalated_at: str | None = None,
    ) -> bool:
        now = _now_ts()
        new_status = "dismissed" if resolution_type == "dismissed" else "resolved"
        async with self.acquire() as conn:
            result = await conn.execute(
                "UPDATE conflicts SET status=$1, resolution_type=$2, resolution=$3, "
                "resolved_by=$4, resolved_at=$5, auto_resolved=TRUE, escalated_at=$6 "
                "WHERE id=$7 AND status='open' AND workspace_id=$8",
                new_status,
                resolution_type,
                resolution,
                resolved_by,
                now,
                escalated_at,
                conflict_id,
                self.workspace_id,
            )
        return result == "UPDATE 1"

    async def get_stale_open_conflicts(self, older_than_hours: int = 72) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM conflicts WHERE status='open' AND workspace_id=$1 "
                "AND detected_at < NOW() - ($2 * INTERVAL '1 hour') "
                "ORDER BY detected_at ASC",
                self.workspace_id,
                older_than_hours,
            )
        return [_row_to_dict(r) for r in rows]

    async def insert_detection_feedback(self, conflict_id: str, feedback: str) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "INSERT INTO detection_feedback(conflict_id, feedback, recorded_at) "
                "VALUES ($1, $2, $3)",
                conflict_id,
                feedback,
                _now_ts(),
            )

    # ── Agent operations ─────────────────────────────────────────────

    async def upsert_agent(self, agent_id: str, engineer: str = "unknown") -> None:
        now = _now_ts()
        async with self.acquire() as conn:
            await conn.execute(
                """INSERT INTO agents(agent_id, engineer, registered_at, last_seen, total_commits, workspace_id)
                   VALUES ($1, $2, $3, $3, 0, $4)
                   ON CONFLICT(agent_id) DO UPDATE SET last_seen = $3""",
                agent_id,
                engineer,
                now,
                self.workspace_id,
            )

    async def increment_agent_commits(self, agent_id: str) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE agents SET total_commits = total_commits + 1 "
                "WHERE agent_id = $1 AND workspace_id = $2",
                agent_id,
                self.workspace_id,
            )

    async def increment_agent_flagged(self, agent_id: str) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE agents SET flagged_commits = flagged_commits + 1 "
                "WHERE agent_id = $1 AND workspace_id = $2",
                agent_id,
                self.workspace_id,
            )

    async def get_agent(self, agent_id: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agents WHERE agent_id = $1 AND workspace_id = $2",
                agent_id,
                self.workspace_id,
            )
        return _row_to_dict(row) if row else None

    # ── Scope permissions ────────────────────────────────────────────

    async def get_scope_permission(self, agent_id: str, scope: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM scope_permissions WHERE agent_id = $1 AND scope = $2",
                agent_id,
                scope,
            )
        return _row_to_dict(row) if row else None

    async def set_scope_permission(
        self,
        agent_id: str,
        scope: str,
        can_read: bool = True,
        can_write: bool = True,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """INSERT INTO scope_permissions(agent_id, scope, can_read, can_write, valid_from, valid_until)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT(agent_id, scope) DO UPDATE SET
                       can_read=$3, can_write=$4, valid_from=$5, valid_until=$6""",
                agent_id,
                scope,
                can_read,
                can_write,
                valid_from,
                valid_until,
            )

    async def get_facts_by_lineage(self, lineage_id: str) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM facts WHERE lineage_id = $1 AND workspace_id = $2 "
                "ORDER BY committed_at DESC",
                lineage_id,
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_active_facts_with_embeddings(self, scope: str, limit: int = 20) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM facts WHERE scope = $1 AND valid_until IS NULL "
                "AND embedding IS NOT NULL AND workspace_id = $2 "
                "ORDER BY committed_at DESC LIMIT $3",
                scope,
                self.workspace_id,
                limit,
            )
        return [_row_to_dict(r) for r in rows]

    async def update_fact_embedding(self, fact_id: str, embedding: bytes) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE facts SET embedding = $1 WHERE id = $2 AND workspace_id = $3",
                embedding,
                fact_id,
                self.workspace_id,
            )

    async def get_distinct_embedding_models(self) -> list[str]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT embedding_model FROM facts 
                   WHERE embedding_model IS NOT NULL AND workspace_id = $1""",
                self.workspace_id,
            )
        return [r["embedding_model"] for r in rows]

    async def get_facts_by_embedding_model(
        self, embedding_model: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM facts
                   WHERE embedding_model = $1 AND valid_until IS NULL AND workspace_id = $2
                   ORDER BY committed_at DESC
                   LIMIT $3 OFFSET $4""",
                embedding_model,
                self.workspace_id,
                limit,
                offset,
            )
        return [_row_to_dict(r) for r in rows]

    async def update_fact_embedding_with_model(
        self, fact_id: str, embedding: bytes, embedding_model: str, embedding_ver: str
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """UPDATE facts 
                   SET embedding = $1, embedding_model = $2, embedding_ver = $3
                   WHERE id = $4 AND workspace_id = $5""",
                embedding,
                embedding_model,
                embedding_ver,
                fact_id,
                self.workspace_id,
            )

    async def update_fact_entities(self, fact_id: str, entities_json: str) -> None:
        # entities is JSONB in PostgreSQL; asyncpg requires a Python object, not a raw string.
        try:
            entities_value = json.loads(entities_json)
        except Exception:
            entities_value = []
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE facts SET entities = $1 WHERE id = $2 AND workspace_id = $3",
                entities_value,
                fact_id,
                self.workspace_id,
            )

    async def get_facts_with_empty_entities(self, limit: int = 200, offset: int = 0) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, content, scope FROM facts
                   WHERE workspace_id = $1
                     AND valid_until IS NULL
                     AND (entities IS NULL OR entities = '[]'::jsonb OR entities = ''::jsonb)
                   ORDER BY committed_at DESC
                   LIMIT $2 OFFSET $3""",
                self.workspace_id,
                limit,
                offset,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_facts_since(
        self, after: str, scope_prefix: str | None = None, limit: int = 1000
    ) -> list[dict]:
        conditions = ["committed_at > $1", "workspace_id = $2"]
        params: list[Any] = [after, self.workspace_id]
        idx = 3
        if scope_prefix:
            conditions.append(f"(scope = ${idx} OR scope LIKE ${idx} || '/%')")
            params.append(scope_prefix)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM facts WHERE {where} ORDER BY committed_at ASC LIMIT ${idx}",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def ingest_remote_fact(self, fact: dict[str, Any]) -> bool:
        existing = await self.get_fact_by_id(fact["id"])
        if existing:
            return False
        await self.insert_fact(fact)
        return True

    # ── Dashboard helpers ────────────────────────────────────────────

    async def count_facts(self, current_only: bool = True) -> int:
        cond = (
            "WHERE valid_until IS NULL AND workspace_id = $1"
            if current_only
            else "WHERE workspace_id = $1"
        )
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) AS cnt FROM facts {cond}", self.workspace_id
            )
        return row["cnt"] if row else 0

    async def count_conflicts(self, status: str = "open") -> int:
        async with self.acquire() as conn:
            if status == "all":
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM conflicts WHERE workspace_id = $1",
                    self.workspace_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM conflicts WHERE status = $1 AND workspace_id = $2",
                    status,
                    self.workspace_id,
                )
        return row["cnt"] if row else 0

    async def get_agents(self) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agents WHERE workspace_id = $1 ORDER BY last_seen DESC",
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_agents_by_ids(self, agent_ids: set[str]) -> dict[str, dict]:
        if not agent_ids:
            return {}
        placeholders = ", ".join(f"${i + 2}" for i in range(len(agent_ids)))
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM agents WHERE workspace_id = $1 AND agent_id IN ({placeholders})",
                self.workspace_id,
                *list(agent_ids),
            )
        return {r["agent_id"]: _row_to_dict(r) for r in rows}

    async def get_expiring_facts(self, days_ahead: int = 7) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM facts WHERE ttl_days IS NOT NULL AND valid_until IS NOT NULL "
                "AND valid_until > NOW() "
                "AND valid_until < NOW() + ($1 * INTERVAL '1 day') "
                "AND workspace_id = $2 ORDER BY valid_until ASC",
                days_ahead,
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_facts_added_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        conditions = ["workspace_id = $1", "committed_at >= $2", "committed_at <= $3"]
        params: list[Any] = [self.workspace_id, start, end]
        idx = 4
        if scope:
            conditions.append(f"(scope = ${idx} OR scope LIKE ${idx} || '/%')")
            params.append(scope)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                          agent_id, engineer, committed_at, valid_from, valid_until,
                          supersedes_fact_id, durability
                   FROM facts
                   WHERE {where}
                   ORDER BY committed_at ASC
                   LIMIT ${idx}""",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_facts_retired_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        conditions = ["workspace_id = $1", "valid_until >= $2", "valid_until <= $3"]
        params: list[Any] = [self.workspace_id, start, end]
        idx = 4
        if scope:
            conditions.append(f"(scope = ${idx} OR scope LIKE ${idx} || '/%')")
            params.append(scope)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                          agent_id, engineer, committed_at, valid_from, valid_until,
                          supersedes_fact_id, durability
                   FROM facts
                   WHERE {where}
                   ORDER BY valid_until ASC
                   LIMIT ${idx}""",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_conflicts_resolved_between(
        self, start: str, end: str, scope: str | None = None, limit: int = 1000
    ) -> list[dict]:
        conditions = [
            "c.workspace_id = $1",
            "c.resolved_at >= $2",
            "c.resolved_at <= $3",
            "c.status != 'open'",
        ]
        params: list[Any] = [self.workspace_id, start, end]
        idx = 4
        if scope:
            conditions.append(
                f"(fa.scope = ${idx} OR fa.scope LIKE ${idx} || '/%' "
                f"OR fb.scope = ${idx} OR fb.scope LIKE ${idx} || '/%')"
            )
            params.append(scope)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT c.*,
                          fa.content AS fact_a_content, fa.scope AS fact_a_scope,
                          fb.content AS fact_b_content, fb.scope AS fact_b_scope
                   FROM conflicts c
                   JOIN facts fa ON c.fact_a_id = fa.id
                   JOIN facts fb ON c.fact_b_id = fb.id
                   WHERE {where}
                   ORDER BY c.resolved_at ASC
                   LIMIT ${idx}""",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_fact_timeline(self, scope: str | None = None, limit: int = 100) -> list[dict]:
        conditions = ["workspace_id = $1"]
        params: list[Any] = [self.workspace_id]
        idx = 2
        if scope:
            conditions.append(f"(scope = ${idx} OR scope LIKE ${idx} || '/%')")
            params.append(scope)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, lineage_id, content, scope, confidence, fact_type, "
                f"agent_id, engineer, committed_at, valid_from, valid_until, ttl_days "
                f"FROM facts WHERE {where} ORDER BY valid_from DESC LIMIT ${idx}",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    async def get_detection_feedback_stats(self) -> dict[str, int]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT feedback, COUNT(*) AS cnt FROM detection_feedback "
                "JOIN conflicts ON detection_feedback.conflict_id = conflicts.id "
                "WHERE conflicts.workspace_id = $1 GROUP BY feedback",
                self.workspace_id,
            )
        return {r["feedback"]: r["cnt"] for r in rows}

    async def get_open_conflict_fact_ids(self) -> set[str]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT fact_a_id, fact_b_id FROM conflicts "
                "WHERE status = 'open' AND workspace_id = $1",
                self.workspace_id,
            )
        ids: set[str] = set()
        for r in rows:
            ids.add(r["fact_a_id"])
            ids.add(r["fact_b_id"])
        return ids

    async def increment_corroboration(self, fact_id: str) -> None:
        """Increment the corroboration counter for a fact (Phase 2: multi-agent consensus)."""
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE facts SET corroborating_agents = corroborating_agents + 1 "
                "WHERE id = $1 AND workspace_id = $2",
                fact_id,
                self.workspace_id,
            )

    async def get_workspace_stats(self) -> dict:
        """Return aggregate workspace statistics (Postgres implementation)."""
        ws = self.workspace_id
        async with self.acquire() as conn:
            # facts totals
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN valid_until IS NULL THEN 1 ELSE 0 END) AS current_count "
                "FROM facts WHERE workspace_id = $1",
                ws,
            )
            total_facts = row["total"] or 0
            current_facts = row["current_count"] or 0

            # by scope (top 10)
            scope_rows = await conn.fetch(
                "SELECT scope, COUNT(*) AS cnt FROM facts "
                "WHERE valid_until IS NULL AND workspace_id = $1 "
                "GROUP BY scope ORDER BY cnt DESC LIMIT 10",
                ws,
            )
            by_scope = {r["scope"]: r["cnt"] for r in scope_rows}

            # by type
            type_rows = await conn.fetch(
                "SELECT fact_type, COUNT(*) AS cnt FROM facts "
                "WHERE valid_until IS NULL AND workspace_id = $1 GROUP BY fact_type",
                ws,
            )
            by_type = {r["fact_type"]: r["cnt"] for r in type_rows}

            # by durability
            dur_rows = await conn.fetch(
                "SELECT durability, COUNT(*) AS cnt FROM facts "
                "WHERE valid_until IS NULL AND workspace_id = $1 GROUP BY durability",
                ws,
            )
            by_durability = {r["durability"]: r["cnt"] for r in dur_rows}

            most_queried_rows = await conn.fetch(
                """SELECT id, scope, fact_type, query_hits
                   FROM facts
                   WHERE valid_until IS NULL
                     AND workspace_id = $1
                     AND query_hits > 0
                   ORDER BY query_hits DESC, committed_at DESC
                   LIMIT $2""",
                ws,
                ANALYTICS_TOP_LIMIT,
            )
            most_queried = [_row_to_dict(r) for r in most_queried_rows]

            # expiring soon (within 7 days)
            exp_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM facts "
                "WHERE ttl_days IS NOT NULL AND valid_until IS NULL AND workspace_id = $1 "
                "AND valid_from + (ttl_days * INTERVAL '1 day') < NOW() + INTERVAL '7 days'",
                ws,
            )
            expiring_soon = exp_row["cnt"] or 0

            # conflicts by status
            conflict_rows = await conn.fetch(
                "SELECT status, COUNT(*) AS cnt FROM conflicts "
                "WHERE workspace_id = $1 GROUP BY status",
                ws,
            )
            conflict_by_status: dict[str, int] = {r["status"]: r["cnt"] for r in conflict_rows}
            total_conflicts = sum(conflict_by_status.values())
            conflict_rate = round(total_conflicts / total_facts, 4) if total_facts else 0.0

            # conflicts by tier
            tier_rows = await conn.fetch(
                "SELECT detection_tier, COUNT(*) AS cnt FROM conflicts "
                "WHERE workspace_id = $1 GROUP BY detection_tier",
                ws,
            )
            conflict_by_tier = {r["detection_tier"]: r["cnt"] for r in tier_rows}

            # conflicts by type
            type_conflict_rows = await conn.fetch(
                "SELECT conflict_type, COUNT(*) AS cnt FROM conflicts "
                "WHERE workspace_id = $1 GROUP BY conflict_type",
                ws,
            )
            conflict_by_type = {r["conflict_type"]: r["cnt"] for r in type_conflict_rows}

            over_time_rows = await conn.fetch(
                """SELECT to_char(detected_at, 'YYYY-MM-DD') AS date,
                          status,
                          COUNT(*) AS cnt
                   FROM conflicts
                   WHERE workspace_id = $1
                   GROUP BY to_char(detected_at, 'YYYY-MM-DD'), status
                   ORDER BY date DESC
                   LIMIT $2""",
                ws,
                ANALYTICS_BUCKET_LIMIT * 3,
            )
            buckets: dict[str, dict[str, int | str]] = {}
            for r in over_time_rows:
                date = r["date"]
                bucket = buckets.setdefault(
                    date,
                    {"date": date, "open": 0, "resolved": 0, "dismissed": 0, "total": 0},
                )
                status = (
                    r["status"] if r["status"] in {"open", "resolved", "dismissed"} else "total"
                )
                if status != "total":
                    bucket[status] = int(bucket[status]) + r["cnt"]
                bucket["total"] = int(bucket["total"]) + r["cnt"]
            conflict_over_time = sorted(buckets.values(), key=lambda item: str(item["date"]))

            # agents
            agent_rows = await conn.fetch(
                "SELECT agent_id, total_commits, flagged_commits, last_seen FROM agents "
                "WHERE workspace_id = $1 ORDER BY total_commits DESC",
                ws,
            )
            total_agents = len(agent_rows)
            most_active = [
                {
                    "agent_id": r["agent_id"],
                    "total_commits": r["total_commits"],
                    "flagged_commits": r["flagged_commits"],
                    "last_seen": r["last_seen"].isoformat()
                    if isinstance(r["last_seen"], datetime)
                    else r["last_seen"],
                }
                for r in agent_rows[:ANALYTICS_TOP_LIMIT]
            ]
            trust_scores = [
                1.0 - (r["flagged_commits"] / r["total_commits"]) if r["total_commits"] > 0 else 0.8
                for r in agent_rows
            ]
            avg_trust = round(sum(trust_scores) / len(trust_scores), 3) if trust_scores else None

            # detection feedback
            fb_rows = await conn.fetch(
                "SELECT df.feedback, COUNT(*) AS cnt FROM detection_feedback df "
                "JOIN conflicts c ON df.conflict_id = c.id "
                "WHERE c.workspace_id = $1 GROUP BY df.feedback",
                ws,
            )
            feedback = {r["feedback"]: r["cnt"] for r in fb_rows}

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

    # ── Workspace / invite key methods ───────────────────────────────

    async def ensure_workspace(
        self, engram_id: str, anonymous_mode: bool, anon_agents: bool
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """INSERT INTO workspaces(engram_id, created_at, anonymous_mode, anon_agents)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT(engram_id) DO NOTHING""",
                engram_id,
                _now_ts(),
                anonymous_mode,
                anon_agents,
            )

    async def get_workspace(self, engram_id: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM workspaces WHERE engram_id = $1", engram_id)
        return _row_to_dict(row) if row else None

    async def update_workspace_display_name(self, engram_id: str, display_name: str) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE workspaces SET display_name = $1 WHERE engram_id = $2",
                display_name,
                engram_id,
            )

    async def delete_workspace(self, engram_id: str) -> None:
        async with self.acquire() as conn:
            await conn.execute("DELETE FROM invite_keys WHERE engram_id = $1", engram_id)
            await conn.execute(
                "DELETE FROM conflicts WHERE fact_a_id IN "
                "(SELECT id FROM facts WHERE workspace_id = $1)",
                engram_id,
            )
            await conn.execute("DELETE FROM facts WHERE workspace_id = $1", engram_id)
            await conn.execute("DELETE FROM workspaces WHERE engram_id = $1", engram_id)

    async def insert_invite_key(
        self,
        key_hash: str,
        engram_id: str,
        expires_at: str | None,
        uses_remaining: int | None,
    ) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """INSERT INTO invite_keys(key_hash, engram_id, created_at, expires_at, uses_remaining)
                   VALUES ($1, $2, $3, $4, $5) ON CONFLICT(key_hash) DO NOTHING""",
                key_hash,
                engram_id,
                _now_ts(),
                expires_at,
                uses_remaining,
            )

    async def validate_invite_key(self, key_hash: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM invite_keys WHERE key_hash = $1 "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "AND (uses_remaining IS NULL OR uses_remaining > 0)",
                key_hash,
            )
        return _row_to_dict(row) if row else None

    async def consume_invite_key(self, key_hash: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE invite_keys SET uses_remaining = uses_remaining - 1 "
                "WHERE key_hash = $1 "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "AND (uses_remaining IS NULL OR uses_remaining > 0) "
                "AND revoked_at IS NULL "
                "RETURNING *",
                key_hash,
            )
        return _row_to_dict(row) if row else None

    async def get_key_generation(self, engram_id: str) -> int:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT key_generation FROM workspaces WHERE engram_id = $1", engram_id
            )
        return row["key_generation"] if row else 0

    async def bump_key_generation(self, engram_id: str) -> int:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE workspaces SET key_generation = key_generation + 1 "
                "WHERE engram_id = $1 RETURNING key_generation",
                engram_id,
            )
        return row["key_generation"] if row else 0

    async def revoke_all_invite_keys(
        self,
        engram_id: str,
        *,
        grace_minutes: int = 15,
        reason: str | None = None,
    ) -> None:
        async with self.acquire() as conn:
            # Purge already-expired grace keys as a side-effect.
            await conn.execute(
                "DELETE FROM invite_keys WHERE engram_id = $1 AND revoked_at IS NOT NULL AND grace_until < NOW()",
                engram_id,
            )
            if grace_minutes > 0:
                await conn.execute(
                    "UPDATE invite_keys "
                    "SET revoked_at = NOW(), "
                    "    grace_until = NOW() + ($2 || ' minutes')::INTERVAL, "
                    "    rotation_reason = $3 "
                    "WHERE engram_id = $1 AND revoked_at IS NULL",
                    engram_id,
                    str(grace_minutes),
                    reason,
                )
            else:
                await conn.execute(
                    "DELETE FROM invite_keys WHERE engram_id = $1 AND revoked_at IS NULL",
                    engram_id,
                )

    async def get_active_grace_until(self, engram_id: str) -> str | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT MAX(grace_until) AS grace_until FROM invite_keys "
                "WHERE engram_id = $1 AND revoked_at IS NOT NULL AND grace_until > NOW()",
                engram_id,
            )
        if row and row["grace_until"] is not None:
            val = row["grace_until"]
            return val.isoformat() if isinstance(val, datetime) else str(val)
        return None

    async def cleanup_expired_grace_keys(self, engram_id: str) -> int:
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM invite_keys WHERE engram_id = $1 AND revoked_at IS NOT NULL AND grace_until < NOW()",
                engram_id,
            )
        return int(result.split()[-1])

    async def get_key_rotation_history(self, engram_id: str, limit: int = 20) -> list[dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_log "
                "WHERE operation = 'key_rotation' AND workspace_id = $1 "
                "ORDER BY timestamp DESC LIMIT $2",
                engram_id,
                max(1, min(limit, 200)),
            )
        return [_row_to_dict(r) for r in rows]

    async def insert_audit_entry(self, entry: dict[str, Any]) -> None:
        import json as _json

        extra = entry.get("extra")
        if isinstance(extra, str):
            try:
                extra = _json.loads(extra)
            except Exception:
                extra = {"raw": extra}

        async with self.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_log(id, operation, agent_id, fact_id, conflict_id, extra, timestamp, workspace_id) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)",
                entry["id"],
                entry["operation"],
                entry.get("agent_id"),
                entry.get("fact_id"),
                entry.get("conflict_id"),
                _json.dumps(extra) if extra is not None else "{}",
                entry.get("timestamp", _now_ts().isoformat()),
                self.workspace_id,
            )

    async def get_audit_log(
        self,
        agent_id: str | None = None,
        operation: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        conditions = ["workspace_id = $1"]
        params: list[Any] = [self.workspace_id]
        idx = 2
        if agent_id:
            conditions.append(f"agent_id = ${idx}")
            params.append(agent_id)
            idx += 1
        if operation:
            conditions.append(f"operation = ${idx}")
            params.append(operation)
            idx += 1
        if from_ts:
            conditions.append(f"timestamp >= ${idx}")
            params.append(from_ts)
            idx += 1
        if to_ts:
            conditions.append(f"timestamp <= ${idx}")
            params.append(to_ts)
            idx += 1
        params.append(max(1, min(limit, 1000)))
        sql = (
            f"SELECT * FROM audit_log WHERE {' AND '.join(conditions)} "
            f"ORDER BY timestamp DESC LIMIT ${idx}"
        )
        async with self.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_dict(r) for r in rows]

    async def get_invite_keys(self) -> list[dict]:
        """Return list of active invite keys."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM invite_keys WHERE engram_id = $1 ORDER BY created_at DESC",
                self.workspace_id,
            )
        return [_row_to_dict(r) for r in rows]

    # ── GDPR subject-erasure ─────────────────────────────────────────

    async def gdpr_soft_erase_agent(self, agent_id: str) -> dict[str, int]:
        """Soft-erase: redact engineer/provenance on all facts; scrub related rows.

        All statements run inside a single asyncpg transaction.
        """
        wid = self.workspace_id
        async with self.acquire() as conn:
            async with conn.transaction():
                r = await conn.execute(
                    "UPDATE facts SET engineer = '[redacted]', provenance = NULL "
                    "WHERE agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                facts_updated = int(r.split()[-1])

                r = await conn.execute(
                    """UPDATE conflicts
                       SET explanation            = '[redacted]',
                           suggested_resolution   = NULL,
                           suggested_resolution_type = NULL,
                           suggestion_reasoning   = NULL
                       WHERE workspace_id = $1
                         AND (fact_a_id IN (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1)
                              OR fact_b_id IN (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1))""",
                    wid,
                    agent_id,
                )
                conflicts_scrubbed = int(r.split()[-1])

                r = await conn.execute(
                    "UPDATE agents SET engineer = '[redacted]', label = NULL "
                    "WHERE agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                agents_updated = int(r.split()[-1])

                r = await conn.execute(
                    "UPDATE audit_log SET agent_id = NULL, extra = '{}' "
                    "WHERE agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                audit_rows_scrubbed = int(r.split()[-1])

        return {
            "facts_updated": facts_updated,
            "conflicts_scrubbed": conflicts_scrubbed,
            "agents_updated": agents_updated,
            "conflicts_closed": 0,
            "scope_permissions_deleted": 0,
            "scopes_updated": 0,
            "audit_rows_scrubbed": audit_rows_scrubbed,
        }

    async def gdpr_hard_erase_agent(self, agent_id: str) -> dict[str, int]:
        """Hard-erase: wipe fact payload, retire current versions, cascade conflicts.

        Postgres search_vector is a GENERATED column so UPDATE on content/keywords
        automatically refreshes the GIN index — no extra trigger is needed.
        All statements run inside a single asyncpg transaction.
        """
        now = _now_ts()
        wid = self.workspace_id
        async with self.acquire() as conn:
            async with conn.transaction():
                r = await conn.execute(
                    """UPDATE facts
                       SET content      = '[gdpr:erased:' || id || ']',
                           content_hash = 'gdpr:erased:' || id,
                           engineer     = '[redacted]',
                           provenance   = NULL,
                           keywords     = NULL,
                           entities     = NULL,
                           embedding    = NULL,
                           valid_until  = COALESCE(valid_until, $1)
                       WHERE agent_id = $2 AND workspace_id = $3""",
                    now,
                    agent_id,
                    wid,
                )
                facts_updated = int(r.split()[-1])

                r = await conn.execute(
                    """UPDATE conflicts
                       SET status                    = 'dismissed',
                           resolution_type           = 'gdpr_erasure',
                           resolution                = '[gdpr:erased]',
                           resolved_at               = $1,
                           resolved_by               = 'gdpr',
                           explanation               = '[redacted]',
                           suggested_resolution      = NULL,
                           suggested_resolution_type = NULL,
                           suggested_winning_fact_id = NULL,
                           suggestion_reasoning      = NULL
                       WHERE workspace_id = $2
                         AND status = 'open'
                         AND (fact_a_id IN (SELECT id FROM facts WHERE agent_id = $3 AND workspace_id = $2)
                              OR fact_b_id IN (SELECT id FROM facts WHERE agent_id = $3 AND workspace_id = $2))""",
                    now,
                    wid,
                    agent_id,
                )
                conflicts_closed = int(r.split()[-1])

                r = await conn.execute(
                    """UPDATE conflicts
                       SET explanation               = '[redacted]',
                           resolution                = '[redacted]',
                           suggested_resolution      = NULL,
                           suggested_resolution_type = NULL,
                           suggestion_reasoning      = NULL
                       WHERE workspace_id = $1
                         AND status != 'open'
                         AND (fact_a_id IN (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1)
                              OR fact_b_id IN (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1))""",
                    wid,
                    agent_id,
                )
                conflicts_scrubbed = int(r.split()[-1])

                await conn.execute(
                    """UPDATE conflicts
                       SET suggested_winning_fact_id = NULL
                       WHERE workspace_id = $1
                         AND suggested_winning_fact_id IN
                             (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1)""",
                    wid,
                    agent_id,
                )

                r = await conn.execute(
                    "UPDATE agents SET engineer = '[redacted]', label = NULL "
                    "WHERE agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                agents_updated = int(r.split()[-1])

                r = await conn.execute(
                    "DELETE FROM scope_permissions WHERE agent_id = $1",
                    agent_id,
                )
                scope_permissions_deleted = int(r.split()[-1])

                r = await conn.execute(
                    "UPDATE scopes SET owner_agent_id = NULL "
                    "WHERE owner_agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                scopes_updated = int(r.split()[-1])

                r = await conn.execute(
                    "UPDATE audit_log SET agent_id = NULL, extra = '{}' "
                    "WHERE agent_id = $1 AND workspace_id = $2",
                    agent_id,
                    wid,
                )
                audit_actor = int(r.split()[-1])

                r = await conn.execute(
                    """UPDATE audit_log
                       SET fact_id = NULL, extra = '{}'
                       WHERE workspace_id = $1
                         AND fact_id IN
                             (SELECT id FROM facts WHERE agent_id = $2 AND workspace_id = $1)""",
                    wid,
                    agent_id,
                )
                audit_fact = int(r.split()[-1])

        return {
            "facts_updated": facts_updated,
            "conflicts_closed": conflicts_closed,
            "conflicts_scrubbed": conflicts_scrubbed,
            "agents_updated": agents_updated,
            "scope_permissions_deleted": scope_permissions_deleted,
            "scopes_updated": scopes_updated,
            "audit_rows_scrubbed": audit_actor + audit_fact,
        }


# ── Helpers ──────────────────────────────────────────────────────────


def _now_ts() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: Any) -> dict:
    """Convert an asyncpg Record to a plain dict."""
    if row is None:
        return {}
    d = dict(row)
    # Serialize datetime objects to ISO strings for compatibility with SQLiteStorage consumers
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d
