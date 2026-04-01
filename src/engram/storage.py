"""Phase 1 — Storage layer: async SQLite with WAL mode.

Write lock is held only for INSERT (~1ms). Detection runs in a
background worker without holding any lock.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from engram.schema import SCHEMA_SQL, SCHEMA_VERSION

DEFAULT_DB_PATH = Path.home() / ".engram" / "knowledge.db"


class Storage:
    """Async SQLite storage with WAL mode and FTS5."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)

        # Run pending migrations for existing databases.
        # New databases have no schema_meta row yet — skip migrations because
        # SCHEMA_SQL already includes all columns.
        cursor = await self._db.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        )
        row = await cursor.fetchone()
        if row is not None:
            from engram.schema import MIGRATIONS
            current_version = int(row["value"])
            for version in range(current_version + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(version, []):
                    try:
                        await self._db.execute(stmt)
                    except Exception:
                        pass  # Column already exists — migration is idempotent

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
            "id", "lineage_id", "content", "content_hash", "scope",
            "confidence", "fact_type", "agent_id", "engineer", "provenance",
            "keywords", "entities", "artifact_hash", "embedding",
            "embedding_model", "embedding_ver", "committed_at",
            "valid_from", "valid_until", "ttl_days",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [fact.get(c) for c in cols]
        cursor = await self.db.execute(
            f"INSERT INTO facts ({col_names}) VALUES ({placeholders})", values
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def find_duplicate(self, content_hash: str, scope: str) -> str | None:
        """Check for exact content duplicate in the same scope (current facts only)."""
        cursor = await self.db.execute(
            "SELECT id FROM facts WHERE content_hash = ? AND scope = ? AND valid_until IS NULL",
            (content_hash, scope),
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
                "UPDATE facts SET valid_until = ? WHERE lineage_id = ? AND valid_until IS NULL",
                (now, lineage_id),
            )
        elif fact_id:
            await self.db.execute(
                "UPDATE facts SET valid_until = ? WHERE id = ? AND valid_until IS NULL",
                (now, fact_id),
            )
        await self.db.commit()

    async def expire_ttl_facts(self) -> int:
        """Close validity windows for TTL-expired facts. Returns count."""
        now = _now_iso()
        cursor = await self.db.execute(
            """UPDATE facts SET valid_until = ?
               WHERE ttl_days IS NOT NULL
                 AND valid_until IS NULL
                 AND datetime(valid_from, '+' || ttl_days || ' days') < ?""",
            (now, now),
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
    ) -> list[dict]:
        """Retrieve currently valid facts, optionally filtered."""
        conditions = []
        params: list[Any] = []

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

        where = " AND ".join(conditions) if conditions else "1=1"
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
            f"SELECT * FROM facts WHERE rowid IN ({placeholders})", rowids
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_fact_by_id(self, fact_id: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Entity-based lookups (for Tier 0 / Tier 2b detection) ────────

    async def find_entity_conflicts(
        self, entity_name: str, entity_type: str, entity_value: str, scope: str, exclude_id: str
    ) -> list[dict]:
        """Find current facts with same entity name but different value in scope."""
        cursor = await self.db.execute(
            """SELECT f.* FROM facts f, json_each(f.entities) e
               WHERE f.valid_until IS NULL
                 AND f.id != ?
                 AND f.scope = ?
                 AND json_extract(e.value, '$.name') = ?
                 AND json_extract(e.value, '$.type') = ?
                 AND json_extract(e.value, '$.value') IS NOT NULL
                 AND CAST(json_extract(e.value, '$.value') AS TEXT) != ?""",
            (exclude_id, scope, entity_name, entity_type, str(entity_value)),
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
                 AND f.id != ?
                 AND json_extract(e.value, '$.name') = ?
                 AND json_extract(e.value, '$.type') = ?
                 AND (json_extract(e.value, '$.value') IS NULL
                      OR CAST(json_extract(e.value, '$.value') AS TEXT) != ?)""",
            (exclude_id, entity_name, entity_type, str(entity_value)),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Conflict operations ──────────────────────────────────────────

    async def insert_conflict(self, conflict: dict[str, Any]) -> None:
        cols = [
            "id", "fact_a_id", "fact_b_id", "detected_at", "detection_tier",
            "nli_score", "explanation", "severity", "status",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [conflict.get(c) for c in cols]
        await self.db.execute(
            f"INSERT INTO conflicts ({col_names}) VALUES ({placeholders})", values
        )
        await self.db.commit()

    async def conflict_exists(self, fact_a_id: str, fact_b_id: str) -> bool:
        """Check if a conflict already exists between two facts (in either order)."""
        cursor = await self.db.execute(
            """SELECT 1 FROM conflicts
               WHERE (fact_a_id = ? AND fact_b_id = ?)
                  OR (fact_a_id = ? AND fact_b_id = ?)""",
            (fact_a_id, fact_b_id, fact_b_id, fact_a_id),
        )
        return await cursor.fetchone() is not None

    async def get_conflicts(
        self, scope: str | None = None, status: str = "open"
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []

        if status != "all":
            conditions.append("c.status = ?")
            params.append(status)

        if scope:
            conditions.append(
                "(fa.scope = ? OR fa.scope LIKE ? || '/%' OR fb.scope = ? OR fb.scope LIKE ? || '/%')"
            )
            params.extend([scope, scope, scope, scope])

        where = " AND ".join(conditions) if conditions else "1=1"

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
        cursor = await self.db.execute(
            "SELECT * FROM conflicts WHERE id = ?", (conflict_id,)
        )
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
        """Return open conflicts that have gone unreviewed past the escalation window."""
        cursor = await self.db.execute(
            """SELECT * FROM conflicts
               WHERE status = 'open'
                 AND datetime(detected_at) < datetime('now', ? || ' hours')
               ORDER BY detected_at ASC""",
            (f"-{older_than_hours}",),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_detection_feedback(
        self, conflict_id: str, feedback: str
    ) -> None:
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
        cursor = await self.db.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Scope permissions ────────────────────────────────────────────

    async def get_scope_permission(
        self, agent_id: str, scope: str
    ) -> dict | None:
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
                agent_id, scope, int(can_read), int(can_write), valid_from, valid_until,
                int(can_read), int(can_write), valid_from, valid_until,
            ),
        )
        await self.db.commit()

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
        cond = "WHERE valid_until IS NULL" if current_only else ""
        cursor = await self.db.execute(f"SELECT COUNT(*) as cnt FROM facts {cond}")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_conflicts(self, status: str = "open") -> int:
        if status == "all":
            cursor = await self.db.execute("SELECT COUNT(*) as cnt FROM conflicts")
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as cnt FROM conflicts WHERE status = ?", (status,)
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_agents(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agents ORDER BY last_seen DESC"
        )
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
        """Get facts with TTL that will expire within days_ahead days."""
        cursor = await self.db.execute(
            """SELECT * FROM facts
               WHERE ttl_days IS NOT NULL
                 AND valid_until IS NOT NULL
                 AND valid_until > datetime('now')
                 AND valid_until < datetime('now', '+' || ? || ' days')
               ORDER BY valid_until ASC""",
            (days_ahead,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_fact_timeline(
        self, scope: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Get facts ordered by valid_from for timeline view."""
        conditions: list[str] = []
        params: list[Any] = []
        if scope:
            conditions.append("(scope = ? OR scope LIKE ? || '/%')")
            params.extend([scope, scope])
        where = " AND ".join(conditions) if conditions else "1=1"
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

    # ── Open conflict check for query enrichment ─────────────────────

    async def get_open_conflict_fact_ids(self) -> set[str]:
        cursor = await self.db.execute(
            "SELECT fact_a_id, fact_b_id FROM conflicts WHERE status = 'open'"
        )
        rows = await cursor.fetchall()
        ids: set[str] = set()
        for r in rows:
            ids.add(r["fact_a_id"])
            ids.add(r["fact_b_id"])
        return ids


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
