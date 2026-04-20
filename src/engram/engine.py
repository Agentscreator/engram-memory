"""Phase 2+3 — Core engine: commit pipeline, query, conflict detection.

The engine orchestrates storage, embeddings, entity extraction, secret
scanning, and the async detection worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from engram import embeddings
from engram.entities import extract_entities, extract_keywords
from engram.secrets import scan_for_secrets
from engram.storage import BaseStorage
from engram.tkg import TemporalKnowledgeGraph

logger = logging.getLogger("engram")

SEMANTIC_DEDUP_THRESHOLD = 0.95


def _load_entities(raw: Any) -> list[dict[str, Any]]:
    """Return a parsed entity list from a fact row's entities field.

    SQLite stores entities as a JSON string; PostgreSQL (JSONB) returns a
    Python list directly.  Both cases are handled here so callers never need
    to branch on storage backend.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    # str (SQLite) or bytes
    return json.loads(raw) if raw else []


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _fact_age_days(fact: dict[str, Any], now: datetime | None = None) -> int:
    try:
        committed = datetime.fromisoformat(fact["committed_at"])
        if committed.tzinfo is None:
            committed = committed.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        return max(0, (reference - committed).days)
    except (KeyError, ValueError, TypeError):
        return 0


def _effective_confidence(
    fact: dict[str, Any],
    *,
    has_open_conflict: bool = False,
    now: datetime | None = None,
) -> float:
    """Compute query-time confidence without mutating the stored value."""
    base = _clamp(float(fact.get("confidence") or 0.0))
    query_hits = max(0, int(fact.get("query_hits") or 0))
    corroborating_agents = max(0, int(fact.get("corroborating_agents") or 0))
    days_old = _fact_age_days(fact, now=now)

    unreinforced = query_hits == 0 and corroborating_agents == 0
    decay_rate = 0.006 if unreinforced else 0.003
    confidence = base * math.exp(-decay_rate * days_old)

    confidence += min(0.15, 0.06 * math.log1p(corroborating_agents))
    confidence += min(0.10, 0.025 * math.log1p(query_hits))

    if has_open_conflict:
        confidence -= 0.20

    return _clamp(confidence)


def _has_numeric_entity_conflict(
    left_entities: list[dict[str, Any]],
    right_entities: list[dict[str, Any]],
) -> bool:
    """Return True when two facts name the same numeric entity with different values."""
    right_numeric: dict[tuple[str, str | None], Any] = {}
    for entity in right_entities:
        if entity.get("type") != "numeric":
            continue
        key = (str(entity.get("name") or ""), entity.get("unit"))
        right_numeric[key] = entity.get("value")

    for entity in left_entities:
        if entity.get("type") != "numeric":
            continue
        key = (str(entity.get("name") or ""), entity.get("unit"))
        if key in right_numeric and right_numeric[key] != entity.get("value"):
            return True
    return False


def _has_negation_mismatch(left: str, right: str) -> bool:
    """Avoid semantic dedup when one fact explicitly negates the other."""
    negation_terms = ("not", "never", "no", "without", "disabled")
    left_tokens = {token.strip(".,:;!?()[]{}\"'").lower() for token in left.split()}
    right_tokens = {token.strip(".,:;!?()[]{}\"'").lower() for token in right.split()}
    return bool(left_tokens.intersection(negation_terms)) != bool(
        right_tokens.intersection(negation_terms)
    )


def _parse_window_timestamp(value: str, label: str) -> datetime:
    """Parse a CLI/API timestamp and normalize naive values to UTC."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class EngramEngine:
    """Core engine coordinating commit, query, detection, and resolution."""

    def __init__(self, storage: BaseStorage) -> None:
        self.storage = storage
        self.tkg = TemporalKnowledgeGraph(storage)
        # Detection queue: fact IDs waiting for async conflict scan
        self._detection_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._suggestion_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._ttl_task: asyncio.Task[None] | None = None
        self._decay_task: asyncio.Task[None] | None = None
        self._detection_task: asyncio.Task[None] | None = None
        self._suggestion_task: asyncio.Task[None] | None = None
        self._escalation_task: asyncio.Task[None] | None = None
        self._webhook_task: asyncio.Task[None] | None = None
        self._sse_subscribers: dict[str, list[asyncio.Queue]] = {}
        self._recent_queries: dict[
            str, list[tuple[str, float]]
        ] = {}  # agent_id -> [(topic, timestamp)]
        self._nli_model: Any = None
        self._codebase_task: asyncio.Task[None] | None = None
        self._codebase_snapshot: dict[str, Any] | None = None

    async def start(self) -> None:
        """Start background periodic tasks."""
        self._ttl_task = asyncio.create_task(self._ttl_expiry_loop())
        self._decay_task = asyncio.create_task(self._decay_loop())
        self._detection_task = asyncio.create_task(self._detection_worker())
        self._suggestion_task = asyncio.create_task(self._suggestion_worker())
        self._escalation_task = asyncio.create_task(self._escalation_loop())
        self._webhook_task = asyncio.create_task(self._webhook_delivery_worker())
        self._codebase_task = asyncio.create_task(self._codebase_verification_loop())
        logger.info("Engine started")

    async def stop(self) -> None:
        """Stop all background tasks."""
        for task in (
            self._ttl_task,
            self._decay_task,
            self._detection_task,
            self._suggestion_task,
            self._escalation_task,
            self._webhook_task,
            self._codebase_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ttl_task = None
        self._decay_task = None
        self._detection_task = None
        self._suggestion_task = None
        self._escalation_task = None
        self._webhook_task = None
        self._codebase_task = None

    def _build_commit_suggestions(
        self,
        content: str,
        scope: str,
        keywords: list[str] | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        text = content.lower()
        suggestions: list[str] = []

        def add(msg: str) -> None:
            if msg not in suggestions and len(suggestions) < 2:
                suggestions.append(msg)

        if "rate limit" in text or "rate-limit" in text:
            add("Consider also committing the retry strategy.")
            add("Consider also committing the circuit breaker threshold.")

        if "retry" in text or "backoff" in text:
            add("Consider also committing the max retry count.")
            add("Consider also committing the timeout behavior.")

        if "timeout" in text:
            add("Consider also committing the retry policy.")
            add("Consider also committing the circuit breaker threshold.")

        if "webhook" in text:
            add("Consider also committing the retry behavior.")
            add("Consider also committing the signature validation rule.")

        if "cache" in text:
            add("Consider also committing the cache TTL.")
            add("Consider also committing the invalidation strategy.")

        if "queue" in text or "worker" in text:
            add("Consider also committing the retry policy.")
            add("Consider also committing the dead-letter queue behavior.")

        if "database" in text or "postgres" in text or "mysql" in text:
            add("Consider also committing the connection pool settings.")
            add("Consider also committing the migration or schema dependency.")

        if "auth" in text or "token" in text or "jwt" in text:
            add("Consider also committing the token expiry behavior.")
            add("Consider also committing the refresh or revocation flow.")

        return suggestions

    # ── engram_commit ────────────────────────────────────────────────

    async def commit(
        self,
        content: str,
        scope: str = "general",
        confidence: float = 0.8,
        agent_id: str | None = None,
        engineer: str | None = None,
        corrects_lineage: str | None = None,
        provenance: str | None = None,
        fact_type: str = "observation",
        ttl_days: int | None = None,
        artifact_hash: str | None = None,
        operation: str = "add",
        durability: str = "durable",
    ) -> dict[str, Any]:
        """Commit a fact to shared memory. Returns immediately; detection is async.

        The ``durability`` parameter controls the fact's lifecycle:
        - ``durable`` (default) — persists until superseded or expired.
          Included in query results by default.  Triggers conflict detection.
        - ``ephemeral`` — short-lived scratchpad memory.  Excluded from
          query results unless explicitly requested.  Skips conflict
          detection.  Auto-expires after ``ttl_days`` (default 1 day for
          ephemeral).  Automatically promoted to durable when queried
          at least twice (the "proved useful more than once" heuristic).

        The ``operation`` parameter follows the MemFactory CRUD pattern:
        - ``add``    (default) — insert a new independent fact.
        - ``update`` — supersede the most semantically similar active fact in
                       the same scope.  If ``corrects_lineage`` is supplied it
                       is used directly; otherwise the engine runs an embedding
                       search and picks the best match above the 0.75 threshold.
        - ``delete`` — retire an existing fact without replacement.
                       ``corrects_lineage`` must identify the lineage to close.
                       ``content`` should briefly explain why it is being retired.
        - ``none``   — no-op.  Useful when a retrieval was sufficient and the
                       agent wants to signal it has nothing new to commit.
        """

        # Step 1: Validate
        if operation not in ("add", "update", "delete", "none"):
            raise ValueError("operation must be 'add', 'update', 'delete', or 'none'.")
        if durability not in ("durable", "ephemeral"):
            raise ValueError("durability must be 'durable' or 'ephemeral'.")

        # none — caller signals no new information; return without writing
        if operation == "none":
            return {
                "fact_id": None,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "duplicate": False,
                "conflicts_detected": False,
                "memory_op": "none",
                "suggestions": [],
            }

        # delete — close an existing lineage and return without a new fact
        if operation == "delete":
            if not corrects_lineage:
                raise ValueError(
                    "operation='delete' requires corrects_lineage (lineage_id to retire)."
                )
            await self.storage.close_validity_window(lineage_id=corrects_lineage)
            logger.info("Memory delete: closed lineage %s by agent %s", corrects_lineage, agent_id)
            return {
                "fact_id": None,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "duplicate": False,
                "conflicts_detected": False,
                "memory_op": "delete",
                "deleted_lineage": corrects_lineage,
                "suggestions": [],
            }

        if not content or not content.strip():
            raise ValueError("Content cannot be empty.")
        if not scope or not scope.strip():
            raise ValueError("Scope cannot be empty.")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0.")
        if fact_type not in ("observation", "inference", "decision"):
            raise ValueError("fact_type must be 'observation', 'inference', or 'decision'.")

        # Ephemeral facts default to 1-day TTL if none specified
        if durability == "ephemeral" and ttl_days is None:
            ttl_days = 1

        # Step 1b: Privacy enforcement — strip engineer/agent_id if workspace requires it
        try:
            from engram.workspace import read_workspace

            ws = read_workspace()
            if ws:
                if ws.anonymous_mode:
                    engineer = None
                if ws.anon_agents and agent_id:
                    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        except Exception:
            pass  # workspace module not available — no enforcement needed

        # Step 2: Secret scan (<1ms)
        secret_match = scan_for_secrets(content)
        if secret_match:
            raise ValueError(
                f"Commit rejected: content appears to contain a secret — {secret_match}. "
                "Remove secrets before committing."
            )

        # Step 3: Content hash for dedup
        content_hash = _content_hash(content)

        # Step 4: Dedup check
        existing_id = await self.storage.find_duplicate(content_hash, scope)
        if existing_id:
            return {
                "fact_id": existing_id,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "duplicate": True,
                "conflicts_detected": False,
                "suggestions": [],
            }

        # Step 5: Generate embedding
        emb = embeddings.encode(content)
        emb_bytes = embeddings.embedding_to_bytes(emb)

        # Step 6: Extract keywords and entities
        keywords = extract_keywords(content)
        entities = extract_entities(content)

        suggestions = self._build_commit_suggestions(
            content=content,
            scope=scope,
            keywords=keywords,
            entities=entities,
        )

        # Step 7: Determine agent_id
        if not agent_id:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"

        # Step 8: Register/update agent
        await self.storage.upsert_agent(agent_id, engineer or "unknown")

        # Step 9: Semantic dedup for near-identical add commits.
        # Updates/corrections intentionally bypass this path because the caller
        # is asking to change lineage, not reinforce an existing fact.
        if operation == "add" and not corrects_lineage:
            semantic_duplicate = await self._find_semantic_duplicate(
                content=content,
                content_embedding=emb,
                entities=entities,
                scope=scope,
                agent_id=agent_id,
            )
            if semantic_duplicate:
                return {
                    "fact_id": semantic_duplicate["fact_id"],
                    "committed_at": datetime.now(timezone.utc).isoformat(),
                    "duplicate": True,
                    "dedup_reason": "semantic",
                    "semantic_similarity": round(semantic_duplicate["similarity"], 4),
                    "corroborated": semantic_duplicate["corroborated"],
                    "conflicts_detected": False,
                    "suggestions": [],
                }

        # Step 10: Determine lineage_id and handle update/auto-update
        supersedes_fact_id: str | None = None

        # Validate user-supplied corrects_lineage before using it.
        # If the lineage doesn't exist the caller made an error — fail loudly
        # rather than silently creating an orphaned lineage with no history.
        if corrects_lineage:
            existing_in_lineage = await self.storage.get_facts_by_lineage(corrects_lineage)
            if not existing_in_lineage:
                raise ValueError(
                    f"corrects_lineage '{corrects_lineage}' not found. "
                    "Cannot update a lineage that does not exist in this workspace."
                )

        if operation == "update" and not corrects_lineage:
            # Auto-updater: find the most semantically similar active fact in scope
            # and supersede it (MemFactory's semantic Updater pattern)
            candidates = await self.storage.get_active_facts_with_embeddings(scope=scope, limit=20)
            best_sim = 0.0
            best_fact = None
            for candidate in candidates:
                if candidate.get("embedding"):
                    c_emb = embeddings.bytes_to_embedding(candidate["embedding"])
                    sim = embeddings.cosine_similarity(emb, c_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_fact = candidate
            if best_fact and best_sim >= 0.75:
                corrects_lineage = best_fact["lineage_id"]
                supersedes_fact_id = best_fact["id"]
                logger.info(
                    "Auto-updater: new fact will supersede fact %s (sim=%.3f) in scope '%s'",
                    best_fact["id"][:12],
                    best_sim,
                    scope,
                )
            else:
                logger.debug(
                    "Auto-updater: no match above threshold (best_sim=%.3f) in scope '%s'; "
                    "falling back to add",
                    best_sim,
                    scope,
                )

        if corrects_lineage:
            lineage_id = corrects_lineage
            # Record the most recent fact in the lineage for audit trail
            if not supersedes_fact_id:
                all_lineage = await self.storage.get_facts_by_lineage(corrects_lineage)
                if all_lineage:
                    supersedes_fact_id = all_lineage[0]["id"]
            await self.storage.close_validity_window(lineage_id=corrects_lineage)
        else:
            lineage_id = uuid.uuid4().hex

        # Step 11: Build fact record
        now = datetime.now(timezone.utc).isoformat()
        fact_id = uuid.uuid4().hex

        valid_until = None
        if ttl_days is not None and ttl_days > 0:
            from datetime import timedelta

            expiry = datetime.now(timezone.utc) + timedelta(days=ttl_days)
            valid_until = expiry.isoformat()

        fact = {
            "id": fact_id,
            "lineage_id": lineage_id,
            "content": content,
            "content_hash": content_hash,
            "scope": scope,
            "confidence": confidence,
            "fact_type": fact_type,
            "agent_id": agent_id,
            "engineer": engineer,
            "provenance": provenance,
            "keywords": json.dumps(keywords),
            "entities": json.dumps(entities),
            "artifact_hash": artifact_hash,
            "embedding": emb_bytes,
            "embedding_model": embeddings.get_model_name(),
            "embedding_ver": embeddings.get_model_version(),
            "committed_at": now,
            "valid_from": now,
            "valid_until": valid_until,
            "ttl_days": ttl_days,
            "memory_op": operation,
            "supersedes_fact_id": supersedes_fact_id,
            "durability": durability,
        }

        # Step 12: INSERT (write lock held ~1ms)
        await self.storage.insert_fact(fact)

        # Step 13: Increment agent commit count
        await self.storage.increment_agent_commits(agent_id)

        # Step 14: Check for corroboration (Phase 2: multi-agent consensus)
        # Find semantically similar facts from different agents in the same scope
        await self._check_corroboration(fact_id, emb, agent_id, scope)

        # Queue durable facts for async conflict detection
        detection_queued = False
        if durability == "durable":
            try:
                self._detection_queue.put_nowait(fact_id)
                detection_queued = True
            except asyncio.QueueFull:
                logger.warning("Detection queue full, skipping conflict check for %s", fact_id[:12])

        result = {
            "fact_id": fact_id,
            "committed_at": now,
            "duplicate": False,
            "conflicts_detected": False,  # detection is async
            "conflict_check_queued": detection_queued,
            "detection_skipped": durability == "durable" and not detection_queued,
            "conflict_risk": self._estimate_conflict_risk(content, scope),
            "memory_op": operation,
            "supersedes_fact_id": supersedes_fact_id,
            "durability": durability,
            "suggestions": suggestions,
        }

        # Audit + fire event (fire-and-forget; errors must not block the commit)
        try:
            await self._audit("commit", agent_id=agent_id, fact_id=fact_id)
        except Exception:
            pass
        try:
            asyncio.ensure_future(
                self._fire_event(
                    "fact.committed",
                    {
                        "fact_id": fact_id,
                        "scope": scope,
                        "agent_id": agent_id,
                        "committed_at": now,
                    },
                )
            )
        except Exception:
            pass

        return result

    async def commit_batch(
        self,
        facts: list[dict[str, Any]],
        scope: str = "general",
        agent_id: str | None = None,
        engineer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Commit multiple facts in a single batch call.

        More efficient than calling commit() multiple times.

        Args:
            facts: List of fact dicts with optional 'content', 'confidence', 'fact_type', 'provenance'
            scope: Default scope for facts without explicit scope
            agent_id: Agent identifier
            engineer: Engineer identifier

        Returns:
            List of result dicts for each committed fact
        """
        results = []
        for fact in facts:
            content = fact.get("content", "")
            if not content:
                results.append({"error": "content is required", "success": False})
                continue

            try:
                result = await self.commit(
                    content=content,
                    scope=fact.get("scope", scope),
                    confidence=fact.get("confidence", 0.8),
                    agent_id=agent_id,
                    engineer=engineer,
                    provenance=fact.get("provenance"),
                    fact_type=fact.get("fact_type", "observation"),
                    ttl_days=fact.get("ttl_days"),
                    durability=fact.get("durability", "durable"),
                )
                results.append({"success": True, **result})
            except Exception as e:
                results.append({"success": False, "error": str(e)})

        return results

    # ── engram_query ─────────────────────────────────────────────────

    async def query(
        self,
        topic: str,
        scope: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
        fact_type: str | None = None,
        include_ephemeral: bool = False,
        include_adjacent: bool = False,
        include_history: bool = False,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query what the team's agents collectively know about a topic.

        Enhanced scoring (Phase 1 + Phase 2):
        - Prioritizes decisions over inferences over observations
        - Boosts facts with provenance (verified claims)
        - Rewards multi-agent corroboration
        - Penalizes facts with open conflicts

        When ``include_ephemeral`` is True, ephemeral (scratchpad) facts are
        included in results alongside durable facts.  Ephemeral facts that
        appear in query results have their ``query_hits`` counter incremented;
        once a fact reaches 2 hits it is automatically promoted to durable
        (the "proved useful more than once" heuristic).

        When ``include_adjacent`` is True and a scope is provided, the query
        also searches sibling and parent scopes for semantically related facts.
        Adjacent results are marked with ``adjacent=True`` and include their
        ``original_scope`` so agents can distinguish in-scope from related facts.
        """
        limit = min(limit, 50)

        # Get candidate facts
        candidates = await self.storage.get_current_facts_in_scope(
            scope=scope,
            fact_type=fact_type,
            as_of=as_of,
            limit=200,
            include_ephemeral=include_ephemeral,
        )
        if not candidates:
            return []

        # Generate query embedding
        query_emb = embeddings.encode(topic)

        # FTS5 search for lexical matches
        fts_ids: set[str] = set()
        try:
            fts_rowids = await self.storage.fts_search(topic, limit=20)
            if fts_rowids:
                fts_facts = await self.storage.get_facts_by_rowids(fts_rowids)
                fts_ids = {f["id"] for f in fts_facts}
        except Exception:
            pass  # FTS may fail on complex queries; fall back to embedding only

        # Score candidates using RRF fusion + enhanced signals
        open_conflict_ids = await self.storage.get_open_conflict_fact_ids()

        # Batch-fetch all agents referenced by candidates (avoids N+1 per fact)
        agent_ids = {f["agent_id"] for f in candidates if f.get("agent_id")}
        agent_map = await self.storage.get_agents_by_ids(agent_ids)

        # Build embedding rank map
        emb_scores: list[tuple[float, dict]] = []
        for fact in candidates:
            if fact.get("embedding"):
                fact_emb = embeddings.bytes_to_embedding(fact["embedding"])
                sim = embeddings.cosine_similarity(query_emb, fact_emb)
            else:
                sim = 0.0
            emb_scores.append((sim, fact))
        emb_scores.sort(key=lambda x: x[0], reverse=True)

        emb_rank: dict[str, int] = {}
        for rank, (_, fact) in enumerate(emb_scores, start=1):
            emb_rank[fact["id"]] = rank

        # Build FTS rank map (facts present in FTS results get their position)
        fts_rank: dict[str, int] = {}
        for rank, fid in enumerate(fts_ids, start=1):
            fts_rank[fid] = rank

        scored: list[tuple[float, dict]] = []
        k = 60  # RRF constant

        for sim, fact in emb_scores:
            fid = fact["id"]
            # Reciprocal Rank Fusion
            rrf = 1.0 / (k + emb_rank.get(fid, len(candidates)))
            if fid in fts_rank:
                rrf += 1.0 / (k + fts_rank[fid])
            relevance = rrf

            # Recency signal — steeper decay to prevent old facts from
            # crowding out recent knowledge at 100k+ scale.
            # Half-life ~7 days: a 30-day-old fact gets 0.12 (was 0.22).
            # A 90-day-old fact gets 0.001 — effectively invisible.
            try:
                committed = datetime.fromisoformat(fact["committed_at"])
                days_old = (datetime.now(timezone.utc) - committed).days
                recency = math.exp(-0.1 * days_old)
            except (ValueError, TypeError):
                recency = 0.5

            # Agent trust signal
            agent = agent_map.get(fact.get("agent_id", ""))
            if agent and agent["total_commits"] > 0:
                trust = 1.0 - (agent["flagged_commits"] / agent["total_commits"])
            else:
                trust = 0.8  # default for unknown agents

            # Phase 1: Fact type weighting (decision > inference > observation)
            # Decisions are architectural choices — high retention value.
            # Inferences are conclusions — moderate, but decay faster.
            # Observations are raw sightings — lowest retention value.
            fact_type_weight = {
                "decision": 1.0,
                "inference": 0.3,
                "observation": 0.0,
            }.get(fact.get("fact_type", "observation"), 0.0)

            # Phase 1: Provenance boost (verified facts rank higher)
            provenance_weight = 1.0 if fact.get("provenance") else 0.0

            # Phase 2: Corroboration boost (multi-agent consensus)
            corroboration_count = fact.get("corroborating_agents", 0)
            corroboration_weight = math.log(1 + corroboration_count)

            # Phase 1: Entity density (facts with structured entities are more actionable)
            try:
                entities = _load_entities(fact.get("entities"))
                entity_density = min(1.0, len(entities) / 5.0)  # cap at 5 entities
            except (json.JSONDecodeError, TypeError):
                entity_density = 0.0

            # Supersession penalty — facts that have been corrected in their
            # lineage should rank lower even if they're technically still valid
            # (edge case: valid_until not yet set due to async processing)
            supersession_penalty = 1.0
            if fact.get("supersedes_fact_id"):
                # This fact IS a correction — boost it slightly
                supersession_penalty = 1.05

            has_open_conflict = fid in open_conflict_ids
            effective_confidence = _effective_confidence(
                fact,
                has_open_conflict=has_open_conflict,
            )

            # Combined score — weights tuned for relevance at scale.
            # Recency is the strongest signal after relevance because at
            # 100k+ facts, old context is the primary source of noise.
            score = (
                relevance
                + 0.25 * recency
                + 0.2 * effective_confidence
                + 0.15 * trust
                + 0.15 * fact_type_weight
                + 0.1 * provenance_weight
                + 0.1 * corroboration_weight
                + 0.05 * entity_density
            ) * supersession_penalty

            # Unverified inferences older than 14 days get heavily penalized.
            # These are the primary source of "weird assumptions" — old guesses
            # that were never confirmed but never expired either.
            if (
                fact.get("fact_type") == "inference"
                and not fact.get("provenance")
                and days_old > 14
            ):
                score *= 0.3

            # Ephemeral facts rank lower than durable facts
            if fact.get("durability") == "ephemeral":
                score *= 0.6

            # Penalize facts with unresolved conflicts — disputed facts
            # should not confidently inform agent decisions
            if has_open_conflict:
                score *= 0.5

            scored.append((score, fact))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Build response
        results: list[dict[str, Any]] = []
        ephemeral_ids: list[str] = []
        for score, fact in scored[:limit]:
            is_ephemeral = fact.get("durability") == "ephemeral"
            if is_ephemeral:
                ephemeral_ids.append(fact["id"])
            has_open_conflict = fact["id"] in open_conflict_ids
            results.append(
                {
                    "fact_id": fact["id"],
                    "content": fact["content"],
                    "scope": fact["scope"],
                    "confidence": fact["confidence"],
                    "effective_confidence": round(
                        _effective_confidence(
                            fact,
                            has_open_conflict=has_open_conflict,
                        ),
                        4,
                    ),
                    "fact_type": fact["fact_type"],
                    "agent_id": fact["agent_id"],
                    "committed_at": fact["committed_at"],
                    "has_open_conflict": has_open_conflict,
                    "verified": fact.get("provenance") is not None,
                    "provenance": fact.get("provenance"),
                    "corroborating_agents": fact.get("corroborating_agents", 0),
                    "query_hits": fact.get("query_hits", 0),
                    "relevance_score": round(score, 4),
                    "durability": fact.get("durability", "durable"),
                    "adjacent": False,
                }
            )

        # Surface related facts from adjacent (sibling/parent) scopes
        if include_adjacent and scope:
            in_scope_ids = {r["fact_id"] for r in results}
            adjacent_results = await self._query_adjacent_scopes(
                topic=topic,
                scope=scope,
                query_emb=query_emb,
                exclude_ids=in_scope_ids,
                open_conflict_ids=open_conflict_ids,
                fact_type=fact_type,
                as_of=as_of,
                include_ephemeral=include_ephemeral,
            )
            results.extend(adjacent_results)
            results.sort(key=lambda r: r["relevance_score"], reverse=True)
            results = results[:limit]

        # Track query hits for confidence reinforcement. Ephemeral facts also
        # use query hits for auto-promotion.
        returned_ids = [str(r["fact_id"]) for r in results]
        if returned_ids:
            await self.storage.increment_query_hits(returned_ids)
        ephemeral_ids = [str(r["fact_id"]) for r in results if r.get("durability") == "ephemeral"]
        if ephemeral_ids:
            # Auto-promote ephemeral facts that have now been queried enough
            promotable = await self.storage.get_promotable_ephemeral_facts(min_hits=2)
            for pf in promotable:
                promoted = await self.storage.promote_fact(pf["id"])
                if promoted:
                    logger.info(
                        "Auto-promoted ephemeral fact %s to durable (query_hits >= 2)",
                        pf["id"][:12],
                    )

        # Detect query loops (repeated queries from same agent)
        if agent_id:
            loop_warning = self._check_query_loop(agent_id, topic)
            if loop_warning:
                logger.warning(loop_warning)

        # Enrich results with lineage history so agents understand how each
        # fact evolved over time — only for facts that have prior versions.
        if include_history:
            for result in results:
                lid = result.get("lineage_id")
                if not lid:
                    result["history"] = []
                    continue
                all_versions = await self.storage.get_facts_by_lineage(lid)
                # Exclude the current fact (already in results), oldest-first
                prior = [
                    {
                        "content": f["content"],
                        "committed_at": f["committed_at"],
                        "agent_id": f["agent_id"],
                        "fact_type": f.get("fact_type", "observation"),
                        "confidence": f.get("confidence"),
                        "superseded": f.get("valid_until") is not None,
                    }
                    for f in reversed(all_versions)
                    if f["id"] != result.get("fact_id")
                ]
                result["history"] = prior

        return results

    async def _query_adjacent_scopes(
        self,
        topic: str,
        scope: str,
        query_emb: "np.ndarray",
        exclude_ids: set[str],
        open_conflict_ids: set[str],
        fact_type: str | None = None,
        as_of: str | None = None,
        include_ephemeral: bool = False,
        similarity_threshold: float = 0.6,
        score_penalty: float = 0.8,
    ) -> list[dict[str, Any]]:
        """Fetch semantically related facts from sibling and parent scopes."""
        all_scopes = await self.storage.get_distinct_scopes()

        # Determine parent scope
        parent_scope = scope.rsplit("/", 1)[0] if "/" in scope else None

        # Find sibling scopes (same parent prefix, excluding current scope and its children)
        if "/" in scope:
            parent_prefix = scope.rsplit("/", 1)[0] + "/"
        else:
            parent_prefix = ""

        adjacent_scopes: list[str] = []
        for s in all_scopes:
            # Skip the queried scope and its children
            if s == scope or s.startswith(scope + "/"):
                continue
            # Include parent scope
            if parent_scope and s == parent_scope:
                adjacent_scopes.append(s)
                continue
            # Include siblings (share the same parent prefix)
            if parent_prefix and s.startswith(parent_prefix):
                adjacent_scopes.append(s)
                continue
            # For top-level scopes, all other top-level scopes are siblings
            if not parent_prefix and "/" not in s:
                adjacent_scopes.append(s)

        if not adjacent_scopes:
            return []

        # Fetch facts from adjacent scopes
        adjacent_facts: list[dict] = []
        for adj_scope in adjacent_scopes:
            facts = await self.storage.get_current_facts_in_scope(
                scope=adj_scope,
                fact_type=fact_type,
                as_of=as_of,
                limit=50,
                include_ephemeral=include_ephemeral,
            )
            adjacent_facts.extend(facts)

        # Score by cosine similarity and filter
        results: list[dict[str, Any]] = []
        for fact in adjacent_facts:
            if fact["id"] in exclude_ids:
                continue
            if not fact.get("embedding"):
                continue

            fact_emb = embeddings.bytes_to_embedding(fact["embedding"])
            sim = embeddings.cosine_similarity(query_emb, fact_emb)

            if sim < similarity_threshold:
                continue

            has_open_conflict = fact["id"] in open_conflict_ids
            effective_confidence = _effective_confidence(
                fact,
                has_open_conflict=has_open_conflict,
            )
            score = (sim + 0.2 * effective_confidence) * score_penalty

            results.append(
                {
                    "fact_id": fact["id"],
                    "content": fact["content"],
                    "scope": fact["scope"],
                    "confidence": fact["confidence"],
                    "effective_confidence": round(effective_confidence, 4),
                    "fact_type": fact["fact_type"],
                    "agent_id": fact["agent_id"],
                    "committed_at": fact["committed_at"],
                    "has_open_conflict": has_open_conflict,
                    "verified": fact.get("provenance") is not None,
                    "provenance": fact.get("provenance"),
                    "corroborating_agents": fact.get("corroborating_agents", 0),
                    "query_hits": fact.get("query_hits", 0),
                    "relevance_score": round(score, 4),
                    "durability": fact.get("durability", "durable"),
                    "adjacent": True,
                    "original_scope": fact["scope"],
                }
            )

        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return results

    def _check_query_loop(self, agent_id: str, topic: str) -> str | None:
        """Detect if an agent is repeatedly querying the same topic (potential loop).

        Returns a warning message if a loop is detected, None otherwise.
        """
        import time
        from collections import deque

        now = time.time()
        window_seconds = 300  # 5 minute window

        if agent_id not in self._recent_queries:
            self._recent_queries[agent_id] = deque()

        # Add current query
        self._recent_queries[agent_id].append((topic, now))

        # Clean old entries outside the window
        while (
            self._recent_queries[agent_id]
            and self._recent_queries[agent_id][0][1] < now - window_seconds
        ):
            self._recent_queries[agent_id].popleft()

        # Check for repeated queries
        queries = self._recent_queries[agent_id]
        if len(queries) >= 5:
            # Count unique topics in recent queries
            topics = [q[0] for q in queries]
            if len(set(topics)) == 1:
                return f"Query loop detected: Agent '{agent_id}' has queried '{topic}' {len(queries)} times in 5 minutes. This may indicate an agent loop."

        return None

    # ── engram_promote ──────────────────────────────────────────────

    async def promote(self, fact_id: str) -> dict[str, Any]:
        """Promote an ephemeral fact to durable.

        This makes the fact visible in default queries and enables conflict
        detection for it.  Use this when an ephemeral observation has proven
        its value and should become part of the team's persistent knowledge.
        """
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact:
            raise ValueError(f"Fact {fact_id} not found.")
        if fact.get("durability") != "ephemeral":
            raise ValueError(f"Fact {fact_id} is already durable.")
        # Allow promoting a fact whose TTL hasn't elapsed yet (valid_until is in
        # the future).  Reject only facts that are definitively expired (valid_until
        # in the past) or superseded (set by close_validity_window).
        valid_until = fact.get("valid_until")
        if valid_until is not None:
            expiry = datetime.fromisoformat(valid_until)
            if expiry <= datetime.now(timezone.utc):
                raise ValueError(f"Fact {fact_id} has already expired or been superseded.")

        promoted = await self.storage.promote_fact(fact_id)
        if not promoted:
            raise ValueError(f"Failed to promote fact {fact_id}.")

        # Now that it's durable, queue it for conflict detection
        try:
            await asyncio.wait_for(self._detection_queue.put(fact_id), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Detection queue full, skipping conflict check for %s",
                fact_id[:12],
            )

        logger.info("Promoted ephemeral fact %s to durable", fact_id[:12])
        return {
            "promoted": True,
            "fact_id": fact_id,
            "durability": "durable",
        }

    # ── Conflict Detection ───────────────────────────────────────────

    async def _detection_worker(self) -> None:
        """Async worker: dequeue fact IDs and run conflict scan for each."""
        logger.info("Detection worker running")
        try:
            while True:
                fact_id = await self._detection_queue.get()
                try:
                    # Re-generate embedding for facts that arrived without one
                    # (e.g. federated facts ingested from remote workspaces)
                    await self._ensure_embedding(fact_id)
                    # Ingest into the temporal knowledge graph
                    await self._ingest_into_tkg(fact_id)
                    await self._scan_fact_for_conflicts(fact_id)
                    # Also verify against codebase if snapshot is available
                    if self._codebase_snapshot:
                        await self._verify_fact_against_codebase(fact_id)
                except Exception:
                    logger.exception("Detection error for fact %s", fact_id)
                finally:
                    self._detection_queue.task_done()
        except asyncio.CancelledError:
            pass

    # ── Tier 0: Codebase ground-truth verification ────────────────────

    async def _codebase_verification_loop(self) -> None:
        """Background loop: scan codebase on startup, then periodically verify facts.

        Runs immediately when the engine starts, then re-scans every 10 minutes.
        Creates high-severity conflicts when facts contradict the code.
        """
        logger.info("Codebase verification worker starting")
        try:
            # Initial scan — run immediately on startup
            await self._run_codebase_scan()

            # Then re-scan periodically (every 10 minutes)
            while True:
                await asyncio.sleep(600)
                await self._run_codebase_scan()
        except asyncio.CancelledError:
            pass

    async def _run_codebase_scan(self) -> None:
        """Scan the codebase and verify all current facts against it."""
        try:
            from engram.codebase import scan_codebase, verify_fact_against_codebase

            # Run the filesystem scan in a thread to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            snapshot = await loop.run_in_executor(None, scan_codebase)
            if not snapshot:
                logger.debug("Codebase scan returned empty — skipping verification")
                return

            self._codebase_snapshot = snapshot
            logger.info(
                "Codebase scanned: %d config keys, %d ports, %d technologies, %d versions",
                len(snapshot.get("config_keys", {})),
                len(snapshot.get("ports", [])),
                len(snapshot.get("technologies", {})),
                len(snapshot.get("versions", {})),
            )

            # Verify all current durable facts
            facts = await self.storage.get_current_facts_in_scope(
                scope=None, limit=500, include_ephemeral=False
            )
            conflicts_found = 0
            for fact in facts:
                try:
                    mismatches = verify_fact_against_codebase(fact, snapshot)
                    for mismatch in mismatches:
                        created = await self._create_codebase_conflict(fact, mismatch)
                        if created:
                            conflicts_found += 1
                except Exception:
                    logger.debug(
                        "Codebase verification failed for fact %s",
                        fact.get("id", "?")[:12],
                    )

            if conflicts_found:
                logger.info(
                    "Codebase verification: %d new conflict(s) detected", conflicts_found
                )
        except Exception:
            logger.debug("Codebase scan failed", exc_info=True)

    async def _verify_fact_against_codebase(self, fact_id: str) -> None:
        """Verify a single newly committed fact against the codebase snapshot."""
        if not self._codebase_snapshot:
            return
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact:
            return
        try:
            from engram.codebase import verify_fact_against_codebase

            mismatches = verify_fact_against_codebase(fact, self._codebase_snapshot)
            for mismatch in mismatches:
                await self._create_codebase_conflict(fact, mismatch)
        except Exception:
            logger.debug("Codebase verification failed for fact %s", fact_id[:12])

    async def _create_codebase_conflict(
        self, fact: dict[str, Any], mismatch: dict[str, str]
    ) -> bool:
        """Create a codebase conflict for a fact-vs-code mismatch.

        Uses a synthetic 'codebase' fact_id to represent the ground truth.
        Returns True if a new conflict was created.
        """
        fact_id = fact["id"]
        # Create a stable synthetic ID for the codebase evidence so we can
        # deduplicate — same entity + same code value = same synthetic fact
        entity_name = mismatch["entity_name"]
        code_value = mismatch["code_value"]
        synthetic_id = hashlib.sha256(
            f"codebase:{entity_name}:{code_value}".encode()
        ).hexdigest()[:32]

        # Check if we already flagged this exact mismatch
        if await self.storage.conflict_exists(fact_id, synthetic_id):
            return False

        # Ensure the synthetic codebase fact exists in storage
        # (so the conflict can reference it and the dashboard can show it)
        existing = await self.storage.get_fact_by_id(synthetic_id)
        if not existing:
            now = datetime.now(timezone.utc).isoformat()
            codebase_fact = {
                "id": synthetic_id,
                "lineage_id": f"codebase-{entity_name}",
                "content": f"[Codebase ground truth] {entity_name}={code_value} (from {mismatch['evidence']})",
                "content_hash": hashlib.sha256(
                    f"codebase:{entity_name}:{code_value}".encode()
                ).hexdigest(),
                "scope": fact.get("scope", "general"),
                "confidence": 1.0,
                "fact_type": "observation",
                "agent_id": "codebase-scanner",
                "engineer": None,
                "provenance": mismatch["evidence"],
                "keywords": json.dumps([entity_name.lower(), "codebase", "ground-truth"]),
                "entities": json.dumps([]),
                "artifact_hash": None,
                "embedding": None,
                "embedding_model": "",
                "embedding_ver": "",
                "committed_at": now,
                "valid_from": now,
                "valid_until": None,
                "ttl_days": None,
                "memory_op": "add",
                "supersedes_fact_id": None,
                "durability": "durable",
            }
            await self.storage.insert_fact(codebase_fact)

        now = datetime.now(timezone.utc).isoformat()
        conflict_id = uuid.uuid4().hex
        await self.storage.insert_conflict({
            "id": conflict_id,
            "fact_a_id": fact_id,
            "fact_b_id": synthetic_id,
            "detected_at": now,
            "detection_tier": "tier0_codebase",
            "nli_score": None,
            "explanation": mismatch["explanation"],
            "severity": "high",
            "status": "open",
            "conflict_type": "genuine",
        })

        logger.info(
            "Codebase conflict: fact %s claims %s=%s but code has %s (%s)",
            fact_id[:8],
            mismatch["entity_name"],
            mismatch["fact_value"],
            mismatch["code_value"],
            mismatch["evidence"],
        )

        try:
            await self._fire_event(
                "conflict.detected",
                {
                    "conflict_id": conflict_id,
                    "fact_a_id": fact_id,
                    "fact_b_id": synthetic_id,
                    "detection_tier": "tier0_codebase",
                    "conflict_type": "genuine",
                    "severity": "high",
                },
            )
        except Exception:
            pass

        return True

    async def _ensure_embedding(self, fact_id: str) -> None:
        """Generate and store an embedding for a fact that doesn't have one yet."""
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact or fact.get("embedding") is not None:
            return  # already has an embedding
        try:
            emb = embeddings.encode(fact["content"])
            emb_bytes = embeddings.embedding_to_bytes(emb)
            await self.storage.update_fact_embedding(fact_id, emb_bytes)
            logger.debug("Re-generated embedding for fact %s", fact_id[:12])
        except Exception:
            logger.debug("Failed to generate embedding for fact %s", fact_id[:12])

    async def _ingest_into_tkg(self, fact_id: str) -> None:
        """Decompose a fact into TKG nodes and edges."""
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact:
            return
        try:
            entities = _load_entities(fact.get("entities"))
            edges = await self.tkg.ingest_fact(
                fact_id=fact_id,
                content=fact.get("content", ""),
                scope=fact.get("scope", "general"),
                agent_id=fact.get("agent_id", "unknown"),
                committed_at=fact.get("committed_at", ""),
                confidence=float(fact.get("confidence", 0.8)),
                entities=entities,
            )
            if edges:
                logger.debug(
                    "TKG: ingested fact %s → %d edge(s)",
                    fact_id[:12],
                    len(edges),
                )
        except Exception:
            logger.debug("TKG ingestion failed for fact %s", fact_id[:12])

    def _classify_conflict_type(
        self, fact: dict[str, Any], other: dict[str, Any], nli_score: float | None = None
    ) -> tuple[str, str]:
        """Classify a detected conflict and choose a severity label.

        Returns ``(conflict_type, severity)`` where *conflict_type* is one of:

        - ``"genuine"``   — cross-agent factual contradiction (highest signal)
        - ``"evolution"`` — same agent correcting itself (lower urgency)
        - ``"ambiguous"`` — borderline NLI score or insufficient evidence
        """
        same_agent = fact.get("agent_id") == other.get("agent_id")

        if nli_score is not None and nli_score <= 0.5:
            return "ambiguous", "low"
        if same_agent:
            return "evolution", "medium"
        return "genuine", "high"

    async def _scan_fact_for_conflicts(self, fact_id: str) -> None:
        """Compare a single fact against all current facts in its scope and cross-scope.

        Runs three detection tiers:
        - tier2_numeric: same-scope numeric entity value conflicts
        - tier1_nli: semantic contradiction via NLI cross-encoder (when available)
        - tier2b_cross_scope: numeric conflicts across different scopes
        """
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact or fact.get("valid_until") is not None:
            return  # expired or superseded — skip

        scope = fact.get("scope")
        now = datetime.now(timezone.utc).isoformat()

        new_entities = extract_entities(fact.get("content") or "")
        new_nums = {
            e["name"]: e["value"]
            for e in new_entities
            if e["type"] == "numeric" and e.get("value") is not None
        }

        # Fetch same-scope candidates once — used by both numeric and NLI tiers
        candidates = await self.storage.get_current_facts_in_scope(scope=scope, limit=200)

        async def _already_settled(a: dict, b: dict) -> bool:
            """True if this pair or their lineages already have a resolved/dismissed conflict."""
            if await self.storage.conflict_exists(a["id"], b["id"]):
                return True
            la, lb = a.get("lineage_id"), b.get("lineage_id")
            if la and lb and la != lb:
                return await self.storage.lineage_conflict_exists(la, lb)
            return False

        # ── Tier 2: Same-scope numeric entity conflicts ───────────────
        if new_nums:
            for other in candidates:
                if other["id"] == fact_id:
                    continue
                if fact.get("lineage_id") and fact.get("lineage_id") == other.get("lineage_id"):
                    continue
                if await _already_settled(fact, other):
                    continue

                other_entities = extract_entities(other.get("content") or "")
                other_nums = {
                    e["name"]: e["value"]
                    for e in other_entities
                    if e["type"] == "numeric" and e.get("value") is not None
                }

                conflicts_on = []
                for name in set(new_nums) & set(other_nums):
                    val_new = new_nums[name]
                    val_other = other_nums[name]
                    if str(val_new) == str(val_other):
                        continue
                    label_new = "unlimited" if val_new == -1 else str(val_new)
                    label_other = "unlimited" if val_other == -1 else str(val_other)
                    conflicts_on.append(f"'{name}': {label_new} vs {label_other}")

                if conflicts_on:
                    conflict_type, severity = self._classify_conflict_type(fact, other)
                    cid = uuid.uuid4().hex
                    await self.storage.insert_conflict(
                        {
                            "id": cid,
                            "fact_a_id": fact_id,
                            "fact_b_id": other["id"],
                            "detected_at": now,
                            "detection_tier": "tier2_numeric",
                            "nli_score": None,
                            "explanation": (
                                f"Numeric conflict(s) on {', '.join(conflicts_on)}: "
                                f'"{fact["content"][:60]}…" vs "{other["content"][:60]}…"'
                            ),
                            "severity": severity,
                            "status": "open",
                            "conflict_type": conflict_type,
                        }
                    )
                    if conflict_type == "evolution":
                        await self._auto_resolve_evolution(cid, fact, other)
                    else:
                        try:
                            self._suggestion_queue.put_nowait(cid)
                        except asyncio.QueueFull:
                            pass
                    await self._fire_event(
                        "conflict.detected",
                        {
                            "conflict_id": cid,
                            "fact_a_id": fact_id,
                            "fact_b_id": other["id"],
                            "detection_tier": "tier2_numeric",
                            "conflict_type": conflict_type,
                            "severity": severity,
                        },
                    )
                    logger.info(
                        "Conflict detected (same-scope numeric): %s (facts %s, %s)",
                        ", ".join(conflicts_on),
                        fact_id[:8],
                        other["id"][:8],
                    )

        # ── Tier 1: NLI semantic contradiction ───────────────────────
        nli_model = self._get_nli_model()
        if nli_model is not None and candidates:
            new_emb = None
            try:
                new_emb = (
                    embeddings.bytes_to_embedding(fact.get("embedding"))
                    if fact.get("embedding")
                    else None
                )
            except Exception:
                pass

            for other in candidates:
                if other["id"] == fact_id:
                    continue
                if fact.get("lineage_id") and fact.get("lineage_id") == other.get("lineage_id"):
                    continue
                if await _already_settled(fact, other):
                    continue

                # Only run NLI on semantically similar pairs (cosine > 0.5)
                if new_emb is not None and other.get("embedding"):
                    try:
                        other_emb = embeddings.bytes_to_embedding(other["embedding"])
                        sim = embeddings.cosine_similarity(new_emb, other_emb)
                        if sim < 0.5:
                            continue
                    except Exception:
                        pass

                try:
                    scores = nli_model.predict(
                        [(fact["content"], other["content"])], apply_softmax=True
                    )
                    contradiction_score = scores[0][0]
                    if contradiction_score > 0.5:
                        conflict_type, severity = self._classify_conflict_type(
                            fact, other, nli_score=float(contradiction_score)
                        )
                        cid = uuid.uuid4().hex
                        await self.storage.insert_conflict(
                            {
                                "id": cid,
                                "fact_a_id": fact_id,
                                "fact_b_id": other["id"],
                                "detected_at": now,
                                "detection_tier": "tier1_nli",
                                "nli_score": float(contradiction_score),
                                "explanation": (
                                    f"Semantic contradiction detected (NLI score: {contradiction_score:.2f}): "
                                    f'"{fact["content"][:60]}…" vs "{other["content"][:60]}…"'
                                ),
                                "severity": severity,
                                "status": "open",
                                "conflict_type": conflict_type,
                            }
                        )
                        if conflict_type == "evolution":
                            await self._auto_resolve_evolution(cid, fact, other)
                        else:
                            try:
                                self._suggestion_queue.put_nowait(cid)
                            except asyncio.QueueFull:
                                pass
                        await self._fire_event(
                            "conflict.detected",
                            {
                                "conflict_id": cid,
                                "fact_a_id": fact_id,
                                "fact_b_id": other["id"],
                                "detection_tier": "tier1_nli",
                                "conflict_type": conflict_type,
                                "severity": severity,
                                "nli_score": float(contradiction_score),
                            },
                        )
                        logger.info(
                            "NLI conflict detected (score=%.2f): facts %s, %s",
                            contradiction_score,
                            fact_id[:8],
                            other["id"][:8],
                        )
                except Exception:
                    logger.debug(
                        "NLI prediction failed for facts %s, %s", fact_id[:8], other["id"][:8]
                    )

        # ── Tier 2b: Cross-scope numeric conflicts ────────────────────
        if new_nums:
            all_scopes = await self.storage.get_distinct_scopes()
            for other_scope in all_scopes:
                if other_scope == scope:
                    continue
                cross_candidates = await self.storage.get_current_facts_in_scope(
                    scope=other_scope, limit=100
                )
                for other in cross_candidates:
                    if other["id"] == fact_id:
                        continue
                    if fact.get("lineage_id") and fact.get("lineage_id") == other.get("lineage_id"):
                        continue
                    if await _already_settled(fact, other):
                        continue

                    other_entities = extract_entities(other.get("content") or "")
                    other_nums = {
                        e["name"]: e["value"]
                        for e in other_entities
                        if e["type"] == "numeric" and e.get("value") is not None
                    }

                    conflicts_on = []
                    for name in set(new_nums) & set(other_nums):
                        val_new = new_nums[name]
                        val_other = other_nums[name]
                        if str(val_new) == str(val_other):
                            continue
                        label_new = "unlimited" if val_new == -1 else str(val_new)
                        label_other = "unlimited" if val_other == -1 else str(val_other)
                        conflicts_on.append(f"'{name}': {label_new} vs {label_other}")

                    if conflicts_on:
                        conflict_type, severity = self._classify_conflict_type(fact, other)
                        cid = uuid.uuid4().hex
                        await self.storage.insert_conflict(
                            {
                                "id": cid,
                                "fact_a_id": fact_id,
                                "fact_b_id": other["id"],
                                "detected_at": now,
                                "detection_tier": "tier2b_cross_scope",
                                "nli_score": None,
                                "explanation": (
                                    f"Cross-scope numeric conflict(s) on {', '.join(conflicts_on)}: "
                                    f'scope "{scope}" vs scope "{other_scope}"'
                                ),
                                "severity": severity,
                                "status": "open",
                                "conflict_type": conflict_type,
                            }
                        )
                        if conflict_type == "evolution":
                            await self._auto_resolve_evolution(cid, fact, other)
                        else:
                            try:
                                self._suggestion_queue.put_nowait(cid)
                            except asyncio.QueueFull:
                                pass
                        await self._fire_event(
                            "conflict.detected",
                            {
                                "conflict_id": cid,
                                "fact_a_id": fact_id,
                                "fact_b_id": other["id"],
                                "detection_tier": "tier2b_cross_scope",
                                "conflict_type": conflict_type,
                                "severity": severity,
                            },
                        )
                        logger.info(
                            "Conflict detected (cross-scope numeric): %s (facts %s, %s)",
                            ", ".join(conflicts_on),
                            fact_id[:8],
                            other["id"][:8],
                        )

        # ── Tier 3: TKG reversal detection ────────────────────────────
        # After ingesting the fact into the TKG (done in _detection_worker),
        # check if this fact created any reversal patterns (A→B→A).
        try:
            reversals = await self.tkg.detect_reversals(scope=scope)
            for rev in reversals:
                # Find the fact IDs involved in the reversal
                seq = rev.get("sequence", [])
                if len(seq) < 3:
                    continue
                # The conflict is between the first and last assertions
                # (which assert the same thing, creating confusion)
                first_fact_id = None

                # Try to find the first fact in the sequence via TKG edges
                entity_name = rev.get("entity", "")
                relation = rev.get("relation", "")
                timeline = await self.tkg.get_entity_timeline(entity_name, relation)
                if len(timeline) >= 3:
                    first_fact_id = timeline[0].get("fact_id")

                if first_fact_id and first_fact_id != fact_id:
                    # Check we haven't already flagged this pair
                    if not await self.storage.conflict_exists(first_fact_id, fact_id):
                        first_fact = await self.storage.get_fact_by_id(first_fact_id)
                        conflict_type, severity = self._classify_conflict_type(
                            first_fact or {}, fact
                        )
                        cid = uuid.uuid4().hex
                        await self.storage.insert_conflict(
                            {
                                "id": cid,
                                "fact_a_id": first_fact_id,
                                "fact_b_id": fact_id,
                                "detected_at": now,
                                "detection_tier": "tier3_tkg_reversal",
                                "nli_score": None,
                                "explanation": rev["explanation"],
                                "severity": severity,
                                "status": "open",
                                "conflict_type": conflict_type,
                            }
                        )
                        if conflict_type == "evolution":
                            await self._auto_resolve_evolution(cid, first_fact or {}, fact)
                        else:
                            try:
                                self._suggestion_queue.put_nowait(cid)
                            except asyncio.QueueFull:
                                pass
                        await self._fire_event(
                            "conflict.detected",
                            {
                                "conflict_id": cid,
                                "fact_a_id": first_fact_id,
                                "fact_b_id": fact_id,
                                "detection_tier": "tier3_tkg_reversal",
                                "conflict_type": conflict_type,
                                "severity": severity,
                            },
                        )
                        logger.info(
                            "TKG reversal detected: %s (facts %s, %s)",
                            rev["explanation"][:80],
                            first_fact_id[:8],
                            fact_id[:8],
                        )
        except Exception:
            logger.debug("TKG reversal detection failed for fact %s", fact_id[:8])

    async def get_conflicts(
        self, scope: str | None = None, status: str = "open"
    ) -> list[dict[str, Any]]:
        """Return conflicts, running a fresh entity scan first to catch any missed."""
        # Run a synchronous scan over all current facts in scope to catch
        # conflicts that may have been missed by the async worker (e.g. on
        # first load or after a restart).
        await self._detect_sync(scope=scope)
        rows = await self.storage.get_conflicts(scope=scope, status=status)
        results = []
        for r in rows:
            results.append(
                {
                    "conflict_id": r["id"],
                    "fact_a": {
                        "fact_id": r["fact_a_id"],
                        "content": r["fact_a_content"],
                        "scope": r["fact_a_scope"],
                        "agent_id": r["fact_a_agent"],
                        "confidence": r["fact_a_confidence"],
                    },
                    "fact_b": {
                        "fact_id": r["fact_b_id"],
                        "content": r["fact_b_content"],
                        "scope": r["fact_b_scope"],
                        "agent_id": r["fact_b_agent"],
                        "confidence": r["fact_b_confidence"],
                    },
                    "detection_tier": r["detection_tier"],
                    "nli_score": r["nli_score"],
                    "explanation": r["explanation"],
                    "severity": r["severity"],
                    "status": r["status"],
                    "detected_at": r["detected_at"],
                    "resolution": r.get("resolution"),
                    "resolution_type": r.get("resolution_type"),
                    "auto_resolved": bool(r.get("auto_resolved")),
                    "escalated_at": r.get("escalated_at"),
                    "suggested_resolution": r.get("suggested_resolution"),
                    "suggested_resolution_type": r.get("suggested_resolution_type"),
                    "suggested_winning_fact_id": r.get("suggested_winning_fact_id"),
                    "suggestion_reasoning": r.get("suggestion_reasoning"),
                    "suggestion_generated_at": r.get("suggestion_generated_at"),
                    "conflict_type": r.get("conflict_type", "genuine"),
                }
            )
        return results

    async def _detect_sync(self, scope: str | None = None) -> None:
        """Synchronous pairwise scan — called on-demand from get_conflicts().

        Complements the async worker: catches any conflicts that slipped
        through (e.g. after a restart or for facts committed before the
        worker was running).
        """
        facts = await self.storage.get_current_facts_in_scope(scope=scope, limit=200)
        if len(facts) < 2:
            return

        now = datetime.now(timezone.utc).isoformat()
        entity_map: dict[str, list[dict[str, Any]]] = {
            f["id"]: extract_entities(f.get("content") or "") for f in facts
        }

        for i, a in enumerate(facts):
            a_nums = {
                e["name"]: e["value"]
                for e in entity_map[a["id"]]
                if e["type"] == "numeric" and e.get("value") is not None
            }
            if not a_nums:
                continue

            for b in facts[i + 1 :]:
                if a.get("lineage_id") and a.get("lineage_id") == b.get("lineage_id"):
                    continue
                if await self.storage.conflict_exists(a["id"], b["id"]):
                    continue

                b_nums = {
                    e["name"]: e["value"]
                    for e in entity_map[b["id"]]
                    if e["type"] == "numeric" and e.get("value") is not None
                }

                conflicts_on = []
                for name in set(a_nums) & set(b_nums):
                    val_a = a_nums[name]
                    val_b = b_nums[name]
                    if str(val_a) == str(val_b):
                        continue
                    label_a = "unlimited" if val_a == -1 else str(val_a)
                    label_b = "unlimited" if val_b == -1 else str(val_b)
                    conflicts_on.append(f"'{name}': {label_a} vs {label_b}")

                if conflicts_on:
                    conflict_type, severity = self._classify_conflict_type(a, b)
                    cid = uuid.uuid4().hex
                    await self.storage.insert_conflict(
                        {
                            "id": cid,
                            "fact_a_id": a["id"],
                            "fact_b_id": b["id"],
                            "detected_at": now,
                            "detection_tier": "tier2_numeric",
                            "nli_score": None,
                            "explanation": (
                                f"Numeric conflict(s) on {', '.join(conflicts_on)}: "
                                f'"{a["content"][:60]}…" vs "{b["content"][:60]}…"'
                            ),
                            "severity": severity,
                            "status": "open",
                            "conflict_type": conflict_type,
                        }
                    )
                    if conflict_type == "evolution":
                        await self._auto_resolve_evolution(cid, a, b)

    async def _auto_resolve_evolution(
        self, conflict_id: str, fact_a: dict[str, Any], fact_b: dict[str, Any]
    ) -> None:
        """Auto-resolve an evolution conflict by keeping the newer fact.

        Called immediately after inserting a conflict classified as 'evolution'
        (same-agent self-correction). The fact with the later committed_at wins;
        the older one's validity window is closed so it no longer appears in
        current-facts queries.
        """
        committed_a = fact_a.get("committed_at") or ""
        committed_b = fact_b.get("committed_at") or ""
        if committed_a >= committed_b:
            winner_id, loser_id = fact_a["id"], fact_b["id"]
        else:
            winner_id, loser_id = fact_b["id"], fact_a["id"]

        await self.storage.close_validity_window(fact_id=loser_id)
        await self.storage.auto_resolve_conflict(
            conflict_id=conflict_id,
            resolution_type="winner",
            resolution=(
                f"Auto-resolved: same-agent self-correction. "
                f"Newer fact {winner_id[:12]} supersedes older fact {loser_id[:12]}."
            ),
            resolved_by="engram-auto",
        )
        asyncio.ensure_future(
            self._fire_event(
                "conflict.resolved",
                {
                    "conflict_id": conflict_id,
                    "resolution_type": "winner",
                    "auto_resolved": True,
                    "winner_id": winner_id,
                    "loser_id": loser_id,
                },
            )
        )
        logger.info(
            "Auto-resolved evolution conflict %s: winner=%s loser=%s",
            conflict_id[:12],
            winner_id[:12],
            loser_id[:12],
        )

    # ── engram_resolve ───────────────────────────────────────────────

    async def resolve(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        winning_claim_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a conflict by picking a winner, merging, or dismissing."""
        if resolution_type not in ("winner", "merge", "dismissed"):
            raise ValueError("resolution_type must be 'winner', 'merge', or 'dismissed'.")

        conflict = await self.storage.get_conflict_by_id(conflict_id)
        if not conflict:
            raise ValueError(f"Conflict {conflict_id} not found.")
        if conflict["status"] != "open":
            raise ValueError(f"Conflict {conflict_id} is already {conflict['status']}.")

        if resolution_type == "winner":
            if not winning_claim_id:
                raise ValueError("winning_claim_id is required for 'winner' resolution.")
            loser_id = (
                conflict["fact_b_id"]
                if winning_claim_id == conflict["fact_a_id"]
                else conflict["fact_a_id"]
            )
            await self.storage.close_validity_window(fact_id=loser_id)
            loser_fact = await self.storage.get_fact_by_id(loser_id)
            if loser_fact:
                await self.storage.increment_agent_flagged(loser_fact["agent_id"])

        elif resolution_type == "merge":
            await self.storage.close_validity_window(fact_id=conflict["fact_a_id"])
            await self.storage.close_validity_window(fact_id=conflict["fact_b_id"])

        elif resolution_type == "dismissed":
            await self.storage.insert_detection_feedback(conflict_id, "false_positive")

        success = await self.storage.resolve_conflict(
            conflict_id=conflict_id,
            resolution_type=resolution_type,
            resolution=resolution,
        )

        if success:
            try:
                await self._audit("resolve", conflict_id=conflict_id)
            except Exception:
                pass
            try:
                asyncio.ensure_future(
                    self._fire_event(
                        "conflict.resolved",
                        {"conflict_id": conflict_id, "resolution_type": resolution_type},
                    )
                )
            except Exception:
                pass

        return {
            "resolved": success,
            "conflict_id": conflict_id,
            "resolution_type": resolution_type,
        }

    # ── engram_batch_commit ──────────────────────────────────────────

    async def batch_commit(
        self,
        facts: list[dict],
        default_agent_id: str | None = None,
        default_engineer: str | None = None,
    ) -> dict:
        """Commit multiple facts in one call.

        Each fact is committed through the full pipeline (dedup, secret scan,
        embedding, entity extraction, async detection).  Facts are processed
        sequentially; a validation error on one fact does not abort the rest.

        Args:
            facts: List of fact dicts.  Each may contain: content, scope,
                confidence, fact_type, agent_id, engineer, provenance,
                ttl_days, operation, durability, corrects_lineage.
            default_agent_id: Fallback agent_id for facts that omit it.
            default_engineer: Fallback engineer for facts that omit it.

        Returns:
            {total, committed, duplicates, failed,
             results: [{index, status, fact_id?, duplicate?, error?}]}
        """
        if not facts:
            raise ValueError("facts list cannot be empty.")
        if len(facts) > 100:
            raise ValueError("Batch size cannot exceed 100 facts.")

        results: list[dict] = []
        committed = 0
        duplicates = 0
        failed = 0

        for i, item in enumerate(facts):
            if not isinstance(item, dict):
                results.append(
                    {"index": i, "status": "error", "error": "Each fact must be a JSON object."}
                )
                failed += 1
                continue

            try:
                result = await self.commit(
                    content=item.get("content", ""),
                    scope=item.get("scope", "general"),
                    confidence=float(item.get("confidence", 0.8)),
                    agent_id=item.get("agent_id") or default_agent_id,
                    engineer=item.get("engineer") or default_engineer,
                    corrects_lineage=item.get("corrects_lineage"),
                    provenance=item.get("provenance"),
                    fact_type=item.get("fact_type", "observation"),
                    ttl_days=item.get("ttl_days"),
                    operation=item.get("operation", "add"),
                    durability=item.get("durability", "durable"),
                )
                is_dup = result.get("duplicate", False)
                if is_dup:
                    duplicates += 1
                else:
                    committed += 1
                results.append(
                    {
                        "index": i,
                        "status": "duplicate" if is_dup else "ok",
                        "fact_id": result.get("fact_id"),
                        "duplicate": is_dup,
                    }
                )
            except Exception as exc:
                failed += 1
                results.append({"index": i, "status": "error", "error": str(exc)})

        return {
            "total": len(facts),
            "committed": committed,
            "duplicates": duplicates,
            "failed": failed,
            "results": results,
        }

    # ── engram_stats ─────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Return aggregate workspace statistics.

        Delegates to the storage layer for efficient SQL aggregation.
        """
        return await self.storage.get_workspace_stats()

    # ── engram_feedback ───────────────────────────────────────────────

    async def record_feedback(self, conflict_id: str, feedback: str) -> dict:
        """Record human or agent feedback on a conflict detection.

        Args:
            conflict_id: The conflict to annotate.
            feedback: 'true_positive' (real conflict) or 'false_positive' (false alarm).

        Returns:
            {recorded: True, conflict_id, feedback}
        """
        if feedback not in ("true_positive", "false_positive"):
            raise ValueError("feedback must be 'true_positive' or 'false_positive'.")
        conflict = await self.storage.get_conflict_by_id(conflict_id)
        if not conflict:
            raise ValueError(f"Conflict '{conflict_id}' not found.")
        await self.storage.insert_detection_feedback(conflict_id, feedback)
        try:
            await self._audit(
                "feedback", conflict_id=conflict_id, extra=json.dumps({"feedback": feedback})
            )
        except Exception:
            pass
        return {"recorded": True, "conflict_id": conflict_id, "feedback": feedback}

    # ── engram_timeline ───────────────────────────────────────────────

    async def get_timeline(self, scope: str | None = None, limit: int = 50) -> list[dict]:
        """Return facts ordered by valid_from for audit/timeline view.

        Args:
            scope: Optional scope prefix to filter by.
            limit: Maximum number of facts to return (capped at 200).

        Returns:
            List of fact summaries ordered chronologically.
        """
        limit = max(1, min(limit, 200))
        return await self.storage.get_fact_timeline(scope=scope, limit=limit)

    # ── engram_agents ─────────────────────────────────────────────────

    async def get_agents(self) -> list[dict]:
        """Return all registered agents and their commit/flag stats."""
        return await self.storage.get_agents()

    # ── fact lookup / listing ─────────────────────────────────────────

    async def get_fact(self, fact_id: str) -> dict | None:
        """Fetch a single fact by ID. Returns None if not found."""
        return await self.storage.get_fact_by_id(fact_id)

    async def list_facts(
        self,
        scope: str | None = None,
        fact_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List current (non-retired) durable facts, optionally filtered.

        Args:
            scope: Optional scope prefix to filter by.
            fact_type: Optional fact type filter ('observation', 'inference', 'decision').
            limit: Maximum results (capped at 200).

        Returns:
            List of fact dicts ordered by committed_at descending.
        """
        limit = max(1, min(limit, 200))
        return await self.storage.get_current_facts_in_scope(
            scope=scope, fact_type=fact_type, limit=limit
        )

    # ── engram_export ──────────────────────────────────────────────────

    async def export_workspace(
        self,
        format: Literal["json", "markdown"] = "json",
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Export workspace as a portable JSON or Markdown snapshot.

        Retrieves all current facts (durable + ephemeral) and all conflicts,
        then delegates to the export formatters in engram.export.

        Args:
            format: "json" or "markdown".
            scope: Optional scope prefix filter.

        Returns:
            Export document dict (structure depends on format).
        """
        from engram.export import build_json_export, build_markdown_export

        if format not in ("json", "markdown"):
            raise ValueError(f"Invalid format '{format}'. Supported: json, markdown")

        now_iso = datetime.now(timezone.utc).isoformat()
        facts = await self.storage.get_current_facts_in_scope(
            scope=scope,
            limit=10000,
            include_ephemeral=True,
            as_of=now_iso,
        )
        if len(facts) >= 10000:
            logger.warning("Export hit fact limit (10000) — some facts may be missing")

        open_conflict_ids = await self.storage.get_open_conflict_fact_ids()
        for fact in facts:
            fact["has_open_conflict"] = fact["id"] in open_conflict_ids

        conflicts = await self.get_conflicts(scope=scope, status="all")

        workspace_id = "local"
        anonymous_mode = False
        try:
            from engram.workspace import read_workspace

            ws = read_workspace()
            if ws:
                workspace_id = ws.engram_id
                anonymous_mode = ws.anonymous_mode
        except Exception:
            pass

        if format == "markdown":
            return build_markdown_export(
                workspace_id=workspace_id,
                facts=facts,
                conflicts=conflicts,
                scope_filter=scope,
                anonymous_mode=anonymous_mode,
            )

        return build_json_export(
            workspace_id=workspace_id,
            facts=facts,
            conflicts=conflicts,
            scope_filter=scope,
            anonymous_mode=anonymous_mode,
        )

    # ── engram_diff ───────────────────────────────────────────────────

    async def diff_memory(
        self,
        from_time: str,
        to_time: str,
        scope: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return memory changes over a time window.

        The diff is read-only and groups changes into added facts, retired or
        superseded facts, and resolved/dismissed conflicts.
        """
        start = _parse_window_timestamp(from_time, "--from")
        end = _parse_window_timestamp(to_time, "--to")
        if start >= end:
            raise ValueError("--from must be earlier than --to.")

        limit = max(1, min(limit, 1000))
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        added = await self.storage.get_facts_added_between(
            start_iso, end_iso, scope=scope, limit=limit
        )
        superseded = await self.storage.get_facts_retired_between(
            start_iso, end_iso, scope=scope, limit=limit
        )
        resolved_conflicts = await self.storage.get_conflicts_resolved_between(
            start_iso, end_iso, scope=scope, limit=limit
        )

        return {
            "from": start_iso,
            "to": end_iso,
            "scope": scope,
            "summary": {
                "added": len(added),
                "superseded": len(superseded),
                "resolved_conflicts": len(resolved_conflicts),
            },
            "added": added,
            "superseded": superseded,
            "resolved_conflicts": resolved_conflicts,
        }

    # ── lineage ───────────────────────────────────────────────────────

    async def get_lineage(self, lineage_id: str) -> list[dict]:
        """Return the full version history of a fact lineage.

        All facts sharing a lineage_id represent successive versions of the
        same piece of knowledge. The list is ordered newest-first so the
        current (valid_until IS NULL) fact is always first.

        Args:
            lineage_id: The lineage UUID to look up.

        Returns:
            List of fact dicts. Empty list if lineage_id not found.
        """
        return await self.storage.get_facts_by_lineage(lineage_id)

    # ── expiring facts ────────────────────────────────────────────────

    async def get_expiring_facts(self, days_ahead: int = 7) -> list[dict]:
        """Return facts whose TTL will expire within days_ahead days.

        Args:
            days_ahead: Look-ahead window in days (1–30, default 7).

        Returns:
            List of facts ordered by valid_until ascending (soonest first).
        """
        days_ahead = max(1, min(days_ahead, 30))
        return await self.storage.get_expiring_facts(days_ahead=days_ahead)

    # ── bulk conflict dismiss ─────────────────────────────────────────

    async def bulk_dismiss(
        self,
        conflict_ids: list[str],
        reason: str,
        dismissed_by: str | None = None,
    ) -> dict:
        """Dismiss multiple open conflicts in one call (max 100)."""
        if not conflict_ids:
            raise ValueError("conflict_ids cannot be empty.")
        if len(conflict_ids) > 100:
            raise ValueError("Cannot dismiss more than 100 conflicts at once.")

        results = []
        dismissed = 0
        failed = 0

        for cid in conflict_ids:
            try:
                ok = await self.storage.resolve_conflict(
                    conflict_id=cid,
                    resolution_type="dismissed",
                    resolution=reason,
                    resolved_by=dismissed_by or "api",
                )
                if ok:
                    dismissed += 1
                    results.append({"conflict_id": cid, "status": "dismissed"})
                else:
                    failed += 1
                    results.append(
                        {
                            "conflict_id": cid,
                            "status": "skipped",
                            "error": "not found or already resolved",
                        }
                    )
            except Exception as exc:
                failed += 1
                results.append({"conflict_id": cid, "status": "error", "error": str(exc)})

        return {
            "total": len(conflict_ids),
            "dismissed": dismissed,
            "failed": failed,
            "results": results,
        }

    # ── Temporal Knowledge Graph queries ─────────────────────────────

    async def get_entity_timeline(
        self,
        entity_name: str,
        relation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the chronological belief history for an entity.

        Shows how beliefs about this entity evolved over time, including
        which agent made each assertion and when edges were invalidated.
        """
        return await self.tkg.get_entity_timeline(entity_name, relation_type)

    async def get_tkg_reversals(
        self,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect A→B→A reversal patterns in the temporal knowledge graph.

        Returns a list of reversal descriptions with the entity, relation,
        sequence of changes, and severity.
        """
        return await self.tkg.detect_reversals(scope=scope)

    async def get_tkg_stale_edges(
        self,
        max_age_days: int = 30,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find active TKG edges that may be stale."""
        return await self.tkg.detect_stale_edges(max_age_days=max_age_days, scope=scope)

    async def get_tkg_belief_drift(
        self,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect belief drift across agents in the TKG."""
        return await self.tkg.detect_belief_drift(scope=scope)

    async def get_tkg_summary(
        self,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Return a summary of the temporal knowledge graph state."""
        return await self.tkg.get_graph_summary(scope=scope)

    # ── Suggestion Worker ────────────────────────────────────────────

    async def _suggestion_worker(self) -> None:
        """Consume conflict IDs and generate LLM resolution suggestions."""
        logger.info("Suggestion worker running")
        try:
            while True:
                conflict_id = await self._suggestion_queue.get()
                try:
                    await self._generate_and_store_suggestion(conflict_id)
                except Exception:
                    logger.exception("Suggestion generation error for conflict %s", conflict_id)
                finally:
                    self._suggestion_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _generate_and_store_suggestion(self, conflict_id: str) -> None:
        """Generate an LLM suggestion for one conflict and persist it."""
        from engram import suggester

        conflict = await self.storage.get_conflict_by_id(conflict_id)
        if not conflict or conflict["status"] != "open":
            return
        if conflict.get("suggested_resolution"):
            return  # already has a suggestion

        facts_by_id = await self.storage.get_facts_by_ids(
            [conflict["fact_a_id"], conflict["fact_b_id"]]
        )
        fact_a = facts_by_id.get(conflict["fact_a_id"])
        fact_b = facts_by_id.get(conflict["fact_b_id"])
        if not fact_a or not fact_b:
            return

        suggestion = await suggester.generate_suggestion(fact_a, fact_b, conflict)
        if suggestion:
            await self.storage.update_conflict_suggestion(conflict_id, **suggestion)
            logger.debug("Suggestion stored for conflict %s", conflict_id)

    # ── 72-hour escalation loop ──────────────────────────────────────

    async def _escalation_loop(self) -> None:
        """Every hour: auto-resolve conflicts open for 72h+ without review."""
        while True:
            try:
                await asyncio.sleep(3600)
                stale = await self.storage.get_stale_open_conflicts(older_than_hours=72)
                if stale:
                    all_ids = list(
                        {c["fact_a_id"] for c in stale} | {c["fact_b_id"] for c in stale}
                    )
                    facts_by_id = await self.storage.get_facts_by_ids(all_ids)
                    for conflict in stale:
                        try:
                            await self._escalate_conflict(
                                conflict,
                                facts_by_id.get(conflict["fact_a_id"]),
                                facts_by_id.get(conflict["fact_b_id"]),
                            )
                        except Exception:
                            logger.exception("Escalation error for conflict %s", conflict["id"])
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Escalation loop error")

    async def _escalate_conflict(
        self,
        conflict: dict[str, Any],
        fact_a: dict[str, Any] | None = None,
        fact_b: dict[str, Any] | None = None,
    ) -> None:
        """Auto-resolve a stale conflict by preferring the more recent fact."""
        if fact_a is None:
            fact_a = await self.storage.get_fact_by_id(conflict["fact_a_id"])
        if fact_b is None:
            fact_b = await self.storage.get_fact_by_id(conflict["fact_b_id"])
        if not fact_a or not fact_b:
            return

        a_time = fact_a.get("committed_at", "")
        b_time = fact_b.get("committed_at", "")
        winner, loser = (fact_a, fact_b) if a_time >= b_time else (fact_b, fact_a)

        await self.storage.close_validity_window(fact_id=loser["id"])
        await self.storage.increment_agent_flagged(loser["agent_id"])

        now = datetime.now(timezone.utc).isoformat()
        await self.storage.auto_resolve_conflict(
            conflict_id=conflict["id"],
            resolution_type="winner",
            resolution=(
                f"Auto-escalated after 72h without human review. "
                f"Preferred newer fact '{winner['id'][:8]}' "
                f"(committed {winner.get('committed_at', 'unknown')[:19]}). "
                f"Human review recommended — override via engram_resolve."
            ),
            resolved_by="system:escalation",
            escalated_at=now,
        )
        logger.info(
            "Auto-escalated conflict %s — preferred newer fact %s",
            conflict["id"][:12],
            winner["id"][:8],
        )

    def _get_nli_model(self) -> Any:
        """Lazy-load the NLI cross-encoder model."""
        if self._nli_model is None:
            try:
                from sentence_transformers import CrossEncoder

                self._nli_model = CrossEncoder("cross-encoder/nli-MiniLM2-L6-H768")
                logger.info("NLI model loaded: cross-encoder/nli-MiniLM2-L6-H768")
            except Exception:
                logger.warning("NLI model not available. Tier 1 detection disabled.")
                return None
        return self._nli_model

    # ── Conflict Risk Estimation ─────────────────────────────────────

    def _estimate_conflict_risk(self, content: str, scope: str) -> str:
        """Return a rough conflict risk level ('low', 'medium', 'high') for a commit.

        Uses lightweight heuristics — no ML, no DB queries — so it runs
        synchronously in the commit hot path without adding latency.
        """
        content_lower = content.lower()
        # High-risk: numeric values, config keys, version strings, or
        # explicit contradiction language tend to conflict more often.
        high_signals = [
            any(c.isdigit() for c in content),  # contains a number
            "version" in content_lower,
            "config" in content_lower,
            "deprecated" in content_lower,
            "removed" in content_lower,
            "changed" in content_lower,
            "now uses" in content_lower,
            "switched to" in content_lower,
        ]
        medium_signals = [
            "should" in content_lower,
            "must" in content_lower,
            "always" in content_lower,
            "never" in content_lower,
        ]
        if sum(high_signals) >= 1:
            return "high"
        if sum(medium_signals) >= 1:
            return "medium"
        return "low"

    # ── Corroboration Detection (Phase 2) ────────────────────────────

    async def _check_corroboration(
        self, fact_id: str, fact_emb: np.ndarray, agent_id: str, scope: str
    ) -> None:
        """Check if this fact corroborates existing facts from other agents.

        When multiple independent agents commit semantically similar facts,
        increment the corroboration counter on all matching facts. This signals
        multi-agent consensus without requiring explicit quorum commits.

        Threshold: 0.85 cosine similarity (high semantic overlap)
        """
        try:
            # Get active facts in scope with embeddings (exclude same agent)
            candidates = await self.storage.get_active_facts_with_embeddings(scope=scope, limit=50)

            corroborated_ids: list[str] = []
            for candidate in candidates:
                # Skip facts from the same agent (not independent corroboration)
                if candidate["agent_id"] == agent_id:
                    continue

                # Skip the fact we just inserted
                if candidate["id"] == fact_id:
                    continue

                if candidate.get("embedding"):
                    c_emb = embeddings.bytes_to_embedding(candidate["embedding"])
                    sim = embeddings.cosine_similarity(fact_emb, c_emb)

                    # High similarity = corroboration
                    if sim >= 0.85:
                        corroborated_ids.append(candidate["id"])

            # Increment corroboration count on all matching facts (including new one)
            if corroborated_ids:
                await self.storage.increment_corroboration(fact_id)
                for cid in corroborated_ids:
                    await self.storage.increment_corroboration(cid)

                logger.debug(
                    "Corroboration detected: fact %s matches %d existing fact(s) from other agents",
                    fact_id[:12],
                    len(corroborated_ids),
                )
        except Exception:
            logger.exception("Corroboration check failed for fact %s", fact_id)

    async def _find_semantic_duplicate(
        self,
        *,
        content: str,
        content_embedding: np.ndarray,
        entities: list[dict[str, Any]],
        scope: str,
        agent_id: str,
        threshold: float = SEMANTIC_DEDUP_THRESHOLD,
    ) -> dict[str, Any] | None:
        """Find a high-confidence near-duplicate fact in the same scope.

        This is intentionally conservative: numeric disagreements and facts
        already linked to conflicts are left alone so conflict detection can
        handle them instead of silently collapsing disputed memory.
        """
        try:
            candidates = await self.storage.get_active_facts_with_embeddings(scope=scope, limit=50)
            best_fact: dict[str, Any] | None = None
            best_similarity = 0.0

            for candidate in candidates:
                if not candidate.get("embedding"):
                    continue
                if await self.storage.get_conflicting_fact_ids(candidate["id"]):
                    continue
                if _has_negation_mismatch(content, candidate.get("content") or ""):
                    continue

                candidate_entities = _load_entities(candidate.get("entities"))
                if _has_numeric_entity_conflict(entities, candidate_entities):
                    continue

                candidate_embedding = embeddings.bytes_to_embedding(candidate["embedding"])
                similarity = embeddings.cosine_similarity(content_embedding, candidate_embedding)
                if similarity >= threshold and similarity > best_similarity:
                    best_similarity = similarity
                    best_fact = candidate

            if best_fact is None:
                return None

            if best_fact.get("agent_id") != agent_id:
                await self.storage.increment_corroboration(best_fact["id"])

            return {
                "fact_id": best_fact["id"],
                "similarity": best_similarity,
                "corroborated": best_fact.get("agent_id") != agent_id,
            }
        except Exception:
            logger.exception("Semantic dedup check failed in scope %s", scope)
            return None

    # ── Startup entity backfill ──────────────────────────────────────

    async def _entity_backfill(self) -> None:
        """Re-extract and store entities for facts that have an empty entities column.

        Facts committed before entity extraction was introduced (or before new
        patterns were added) have entities = NULL or '[]'. This one-time startup
        task fixes them so Tier 0/2 conflict detection can compare them against
        newly committed facts.

        After updating each fact's entities, the fact is queued for detection so
        any conflicts against already-stored facts are surfaced immediately.
        """
        # Brief delay so the detection worker is warm before we flood the queue.
        await asyncio.sleep(2)
        offset = 0
        batch = 200
        total_updated = 0
        while True:
            facts = await self.storage.get_facts_with_empty_entities(limit=batch, offset=offset)
            if not facts:
                break
            for fact in facts:
                try:
                    new_entities = extract_entities(fact["content"])
                    if not new_entities:
                        continue
                    await self.storage.update_fact_entities(fact["id"], json.dumps(new_entities))
                    try:
                        self._detection_queue.put_nowait(fact["id"])
                    except asyncio.QueueFull:
                        pass
                    total_updated += 1
                except Exception:
                    logger.exception("Entity backfill failed for fact %s", fact["id"])
            offset += batch
        if total_updated:
            logger.info("Entity backfill complete: updated %d facts", total_updated)

    # ── Periodic TTL expiry ──────────────────────────────────────────

    async def _ttl_expiry_loop(self) -> None:
        """Periodically expire TTL facts (every 60 seconds)."""
        while True:
            try:
                await asyncio.sleep(60)
                expired = await self.storage.expire_ttl_facts()
                if expired:
                    logger.info("TTL expiry: closed %d fact(s)", expired)
                    asyncio.ensure_future(
                        self._fire_event(
                            "fact.expired",
                            {
                                "count": expired,
                            },
                        )
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("TTL expiry loop error")

    # ── Importance-based decay (FiFA-inspired) ───────────────────────

    async def _decay_loop(self) -> None:
        """Periodically retire stale, low-value facts to prevent memory bloat.

        Runs every 10 minutes.  Targets:
        1. Unverified inferences older than 30 days — these are the primary
           source of "weird assumptions" that taint agent decisions.
        2. Observations older than 90 days with no provenance and no
           corroboration — raw sightings that were never confirmed.

        This implements the FiFA paper's insight: principled forgetting-by-design
        improves coherence by removing context that no longer earns its place.
        Facts with provenance, corroboration, or decision type are protected.
        """
        while True:
            try:
                await asyncio.sleep(600)  # every 10 minutes
                retired = await self.storage.retire_stale_facts()
                if retired:
                    logger.info("Decay: retired %d stale fact(s)", retired)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Decay loop error")

    # ── NLI threshold calibration ────────────────────────────────────

    async def _calibration_loop(self) -> None:
        """Periodically recalibrate NLI threshold from detection feedback.

        After 100 feedback events, adjust:
          threshold = threshold - 0.05 * (false_positive_rate - 0.1)
        """
        while True:
            try:
                await asyncio.sleep(300)  # every 5 minutes
                stats = await self.storage.get_detection_feedback_stats()
                tp = stats.get("true_positive", 0)
                fp = stats.get("false_positive", 0)
                total = tp + fp
                if total >= 100:
                    fp_rate = fp / total
                    adjustment = 0.05 * (fp_rate - 0.1)
                    new_threshold = max(0.5, min(0.95, self._nli_threshold_high - adjustment))
                    if abs(new_threshold - self._nli_threshold_high) > 0.001:
                        logger.info(
                            "NLI calibration: threshold %.3f -> %.3f (fp_rate=%.2f, n=%d)",
                            self._nli_threshold_high,
                            new_threshold,
                            fp_rate,
                            total,
                        )
                        self._nli_threshold_high = new_threshold
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Calibration loop error")

    # ── Webhooks ─────────────────────────────────────────────────────

    async def create_webhook(
        self,
        url: str,
        events: list[str],
        secret: str | None = None,
    ) -> dict[str, Any]:
        """Register a new webhook for event notifications."""
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError("url must be a valid http/https URL.")
        if not events or not isinstance(events, list):
            raise ValueError("events must be a non-empty list of event type strings.")
        webhook_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        webhook = {
            "id": webhook_id,
            "url": url,
            "events": json.dumps(events),
            "secret": secret,
            "active": 1,
            "created_at": now,
        }
        await self.storage.insert_webhook(webhook)
        await self._audit("webhook_create", extra=json.dumps({"url": url, "events": events}))
        return {"webhook_id": webhook_id, "url": url, "events": events, "created_at": now}

    async def list_webhooks(self) -> list[dict[str, Any]]:
        """Return all active webhooks."""
        rows = await self.storage.get_webhooks()
        result = []
        for r in rows:
            events = r.get("events", "[]")
            try:
                events = json.loads(events)
            except Exception:
                pass
            result.append(
                {
                    "webhook_id": r["id"],
                    "url": r["url"],
                    "events": events,
                    "created_at": r["created_at"],
                }
            )
        return result

    async def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Deactivate a webhook."""
        ok = await self.storage.delete_webhook(webhook_id)
        if not ok:
            raise ValueError(f"Webhook '{webhook_id}' not found.")
        return {"deleted": True, "webhook_id": webhook_id}

    async def _fire_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Queue webhook deliveries and broadcast to SSE subscribers for an event."""
        # Broadcast to SSE subscribers
        scope = payload.get("scope", "")
        await self._broadcast(event_type, scope, payload)

        # Queue webhook deliveries
        try:
            webhooks = await self.storage.get_webhooks()
        except Exception:
            return
        for webhook in webhooks:
            events_str = webhook.get("events", "[]")
            try:
                subscribed = json.loads(events_str)
            except Exception:
                subscribed = []
            if event_type in subscribed or "*" in subscribed:
                delivery = {
                    "id": uuid.uuid4().hex,
                    "webhook_id": webhook["id"],
                    "event": event_type,
                    "payload": json.dumps({"event": event_type, "data": payload}),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    await self.storage.queue_webhook_delivery(delivery)
                except Exception:
                    logger.warning("Failed to queue webhook delivery for webhook %s", webhook["id"])

    async def _webhook_delivery_worker(self) -> None:
        """Background worker: polls pending deliveries and POSTs to webhook URLs."""
        while True:
            try:
                await asyncio.sleep(5)
                try:
                    deliveries = await self.storage.get_pending_deliveries()
                except Exception:
                    continue
                if not deliveries:
                    continue
                try:
                    import aiohttp
                except ImportError:
                    logger.warning("aiohttp not available — webhook delivery disabled.")
                    continue
                for delivery in deliveries:
                    webhook = await self.storage.get_webhook_by_id(delivery["webhook_id"])
                    if not webhook:
                        await self.storage.mark_delivery_done(delivery["id"])
                        continue
                    url = webhook["url"]
                    body = delivery["payload"]
                    secret = webhook.get("secret")
                    headers: dict[str, str] = {"Content-Type": "application/json"}
                    if secret:
                        import hmac

                        sig = hmac.new(
                            secret.encode(),
                            body.encode() if isinstance(body, str) else body,
                            hashlib.sha256,
                        ).hexdigest()
                        headers["X-Engram-Signature"] = f"sha256={sig}"
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                url,
                                data=body,
                                headers=headers,
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as resp:
                                if resp.status < 300:
                                    await self.storage.mark_delivery_done(delivery["id"])
                                    logger.debug(
                                        "Webhook delivery %s -> %s OK (%d)",
                                        delivery["id"][:8],
                                        url,
                                        resp.status,
                                    )
                                else:
                                    await self.storage.mark_delivery_failed(delivery["id"])
                                    logger.warning(
                                        "Webhook delivery %s -> %s failed (%d)",
                                        delivery["id"][:8],
                                        url,
                                        resp.status,
                                    )
                    except Exception as exc:
                        await self.storage.mark_delivery_failed(delivery["id"])
                        logger.warning(
                            "Webhook delivery %s -> %s error: %s", delivery["id"][:8], url, exc
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Webhook delivery worker error")

    # ── SSE ──────────────────────────────────────────────────────────

    def subscribe(self, scope_prefix: str = "") -> asyncio.Queue:
        """Create and register an SSE subscriber queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        if scope_prefix not in self._sse_subscribers:
            self._sse_subscribers[scope_prefix] = []
        self._sse_subscribers[scope_prefix].append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue, scope_prefix: str = "") -> None:
        """Remove an SSE subscriber queue."""
        subscribers = self._sse_subscribers.get(scope_prefix, [])
        try:
            subscribers.remove(queue)
        except ValueError:
            pass

    async def _broadcast(self, event_type: str, scope: str, payload: dict[str, Any]) -> None:
        """Push an event to all matching SSE subscribers."""
        event = {"event": event_type, "scope": scope, "data": payload}
        for prefix, queues in list(self._sse_subscribers.items()):
            if prefix == "" or scope.startswith(prefix):
                for q in list(queues):
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass  # Slow consumer — drop event

    # ── Auto-Resolution Rules ────────────────────────────────────────

    async def create_rule(
        self,
        scope_prefix: str,
        condition_type: str,
        condition_value: str,
        resolution_type: str,
    ) -> dict[str, Any]:
        """Create an auto-resolution rule."""
        valid_condition_types = ("latest_wins", "highest_confidence", "confidence_delta")
        if condition_type not in valid_condition_types:
            raise ValueError(f"condition_type must be one of: {', '.join(valid_condition_types)}.")
        if not scope_prefix:
            raise ValueError("scope_prefix is required.")
        rule_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        rule = {
            "id": rule_id,
            "scope_prefix": scope_prefix,
            "condition_type": condition_type,
            "condition_value": condition_value,
            "resolution_type": resolution_type,
            "created_at": now,
        }
        await self.storage.insert_rule(rule)
        await self._audit(
            "rule_create",
            extra=json.dumps(
                {
                    "scope_prefix": scope_prefix,
                    "condition_type": condition_type,
                }
            ),
        )
        return {"rule_id": rule_id, **rule}

    async def list_rules(self) -> list[dict[str, Any]]:
        """Return all active auto-resolution rules."""
        return await self.storage.get_rules()

    async def delete_rule(self, rule_id: str) -> dict[str, Any]:
        """Deactivate an auto-resolution rule."""
        ok = await self.storage.delete_rule(rule_id)
        if not ok:
            raise ValueError(f"Rule '{rule_id}' not found.")
        return {"deleted": True, "rule_id": rule_id}

    async def _apply_rules(self, conflict_id: str) -> None:
        """Check active rules and auto-resolve conflict if a matching rule applies."""
        conflict = await self.storage.get_conflict_by_id(conflict_id)
        if not conflict or conflict.get("status") != "open":
            return

        fact_a = await self.storage.get_fact_by_id(conflict["fact_a_id"])
        fact_b = await self.storage.get_fact_by_id(conflict["fact_b_id"])
        if not fact_a or not fact_b:
            return

        scope = fact_a.get("scope", "")
        rules = await self.storage.get_rules()
        for rule in rules:
            if not scope.startswith(rule["scope_prefix"]):
                continue

            condition_type = rule["condition_type"]
            condition_value = rule["condition_value"]
            resolution_type = rule["resolution_type"]
            resolved = False

            if condition_type == "latest_wins":
                winner = (
                    fact_a
                    if (fact_a.get("committed_at", "") >= fact_b.get("committed_at", ""))
                    else fact_b
                )
                loser = fact_b if winner is fact_a else fact_a
                await self.storage.close_validity_window(fact_id=loser["id"])
                await self.storage.auto_resolve_conflict(
                    conflict_id=conflict_id,
                    resolution_type=resolution_type or "winner",
                    resolution=f"Auto-resolved by rule '{rule['id'][:8]}' (latest_wins)",
                    resolved_by="system:rules",
                )
                resolved = True

            elif condition_type == "highest_confidence":
                conf_a = float(fact_a.get("confidence", 0))
                conf_b = float(fact_b.get("confidence", 0))
                if conf_a != conf_b:
                    winner = fact_a if conf_a > conf_b else fact_b
                    loser = fact_b if winner is fact_a else fact_a
                    await self.storage.close_validity_window(fact_id=loser["id"])
                    await self.storage.auto_resolve_conflict(
                        conflict_id=conflict_id,
                        resolution_type=resolution_type or "winner",
                        resolution=f"Auto-resolved by rule '{rule['id'][:8]}' (highest_confidence)",
                        resolved_by="system:rules",
                    )
                    resolved = True

            elif condition_type == "confidence_delta":
                try:
                    min_delta = float(condition_value)
                except (TypeError, ValueError):
                    continue
                conf_a = float(fact_a.get("confidence", 0))
                conf_b = float(fact_b.get("confidence", 0))
                delta = abs(conf_a - conf_b)
                if delta >= min_delta:
                    winner = fact_a if conf_a > conf_b else fact_b
                    loser = fact_b if winner is fact_a else fact_a
                    await self.storage.close_validity_window(fact_id=loser["id"])
                    await self.storage.auto_resolve_conflict(
                        conflict_id=conflict_id,
                        resolution_type=resolution_type or "winner",
                        resolution=(
                            f"Auto-resolved by rule '{rule['id'][:8]}' "
                            f"(confidence_delta={delta:.2f} >= {min_delta})"
                        ),
                        resolved_by="system:rules",
                    )
                    resolved = True

            if resolved:
                logger.info(
                    "Auto-resolved conflict %s via rule %s (%s)",
                    conflict_id[:12],
                    rule["id"][:8],
                    condition_type,
                )
                return  # Apply at most one rule per conflict

    # ── Knowledge Import ─────────────────────────────────────────────

    async def import_workspace(
        self,
        facts: list[dict],
        agent_id: str | None = None,
        engineer: str | None = None,
    ) -> dict[str, Any]:
        """Import a list of fact dicts by committing each through the pipeline."""
        total = len(facts)
        imported = 0
        duplicates = 0
        failed = 0

        for fact in facts:
            try:
                result = await self.commit(
                    content=fact.get("content", ""),
                    scope=fact.get("scope", "general"),
                    confidence=float(fact.get("confidence", 0.8)),
                    agent_id=fact.get("agent_id") or agent_id,
                    engineer=fact.get("engineer") or engineer,
                    provenance=fact.get("provenance"),
                    fact_type=fact.get("fact_type", "observation"),
                    ttl_days=fact.get("ttl_days"),
                    operation="add",
                    durability=fact.get("durability", "durable"),
                )
                if result.get("duplicate"):
                    duplicates += 1
                else:
                    imported += 1
            except Exception as exc:
                logger.warning("Import failed for fact: %s", exc)
                failed += 1

        await self._audit("import", extra=json.dumps({"total": total, "imported": imported}))
        return {"total": total, "imported": imported, "duplicates": duplicates, "failed": failed}

    # ── Scope Registry ────────────────────────────────────────────────

    async def register_scope(
        self,
        scope: str,
        description: str | None = None,
        owner_agent_id: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Register or update a scope in the scope registry."""
        if not scope or not scope.strip():
            raise ValueError("scope is required.")
        await self.storage.upsert_scope(
            {
                "scope": scope,
                "description": description,
                "owner_agent_id": owner_agent_id,
                "retention_days": retention_days,
            }
        )
        return {"scope": scope, "registered": True}

    async def list_scopes(self) -> list[dict[str, Any]]:
        """Return all registered scopes."""
        return await self.storage.get_scopes()

    async def get_scope_info(self, scope: str) -> dict[str, Any] | None:
        """Return scope metadata and analytics."""
        reg = await self.storage.get_scope_by_name(scope)
        analytics = await self.storage.get_scope_analytics(scope)
        return {"registration": reg, "analytics": analytics}

    # ── Fact Diffing ─────────────────────────────────────────────────

    async def diff_facts(self, fact_id_a: str, fact_id_b: str) -> dict[str, Any]:
        """Compute a field-level and entity-level diff between two facts."""
        fact_a = await self.storage.get_fact_by_id(fact_id_a)
        if not fact_a:
            raise ValueError(f"Fact '{fact_id_a}' not found.")
        fact_b = await self.storage.get_fact_by_id(fact_id_b)
        if not fact_b:
            raise ValueError(f"Fact '{fact_id_b}' not found.")

        # Field-level diff
        diff_fields = ("content", "scope", "confidence", "fact_type", "agent_id")
        changes = []
        for field in diff_fields:
            val_a = fact_a.get(field)
            val_b = fact_b.get(field)
            if val_a != val_b:
                changes.append({"field": field, "old": val_a, "new": val_b})

        # Entity diff
        def _parse_entities(fact: dict) -> list[dict]:
            raw = fact.get("entities") or "[]"
            try:
                return json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                return []

        entities_a = {e.get("name"): e for e in _parse_entities(fact_a)}
        entities_b = {e.get("name"): e for e in _parse_entities(fact_b)}

        added = [e for name, e in entities_b.items() if name not in entities_a]
        removed = [e for name, e in entities_a.items() if name not in entities_b]
        changed = []
        for name in entities_a:
            if name in entities_b and entities_a[name] != entities_b[name]:
                changed.append({"name": name, "old": entities_a[name], "new": entities_b[name]})

        # Strip binary embedding from returned facts
        def _clean(f: dict) -> dict:
            c = dict(f)
            if "embedding" in c:
                c["embedding"] = None
            return c

        return {
            "fact_a": _clean(fact_a),
            "fact_b": _clean(fact_b),
            "changes": changes,
            "entity_changes": {"added": added, "removed": removed, "changed": changed},
        }

    # ── Audit Trail ──────────────────────────────────────────────────

    async def _audit(
        self,
        operation: str,
        agent_id: str | None = None,
        fact_id: str | None = None,
        conflict_id: str | None = None,
        extra: str | None = None,
    ) -> None:
        """Insert an audit log entry."""
        try:
            await self.storage.insert_audit_entry(
                {
                    "id": uuid.uuid4().hex,
                    "operation": operation,
                    "agent_id": agent_id,
                    "fact_id": fact_id,
                    "conflict_id": conflict_id,
                    "extra": extra,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            logger.warning("Audit log insert failed for operation '%s'", operation)

    async def get_audit_log(
        self,
        agent_id: str | None = None,
        operation: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return audit log entries with optional filters."""
        limit = max(1, min(limit, 1000))
        return await self.storage.get_audit_log(
            agent_id=agent_id,
            operation=operation,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )

    # ── Invite key lifecycle ─────────────────────────────────────────

    async def rotate_invite_key(
        self,
        *,
        expires_days: int = 90,
        uses: int = 10,
        grace_minutes: int = 15,
        reason: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Rotate the workspace invite key with audit trail and webhook notification.

        Soft-revokes all active keys (with an optional grace period so agents
        mid-session can finish their work), bumps the workspace key generation,
        generates a fresh invite key, and fires an ``invite_key.rotated`` webhook
        event for downstream consumers.

        Args:
            expires_days: Validity period for the new key in days (default 90).
            uses: Maximum number of times the new key can be consumed (default 10).
            grace_minutes: How long revoked keys remain valid for *existing* sessions
                (not new joins). 0 = immediate revocation (default 15).
            reason: Optional human-readable reason stored in the audit log.
            actor: Identity of the person triggering the rotation (for audit).

        Returns:
            dict with ``invite_key``, ``new_generation``, ``old_generation``,
            and ``grace_until`` (ISO string or None).

        Raises:
            ValueError: If the workspace is not in team mode.
            PermissionError: If the caller is not the workspace creator.
        """
        import time

        from engram.workspace import (
            WorkspaceConfig,
            generate_invite_key,
            read_workspace,
            write_workspace,
        )

        ws = read_workspace()
        if ws is None or not ws.db_url:
            raise ValueError(
                "No team workspace configured. rotate_invite_key is only usable in team mode."
            )
        if not ws.is_creator:
            raise PermissionError(
                "Invite key rotation is restricted to the workspace creator. "
                "Only the founder who ran engram_init may perform this operation."
            )

        old_gen = ws.key_generation

        # Soft-revoke all active keys (existing sessions continue during grace period).
        await self.storage.revoke_all_invite_keys(
            ws.engram_id, grace_minutes=grace_minutes, reason=reason
        )

        # Bump the generation counter — this is what _check_key_generation observes.
        new_gen = await self.storage.bump_key_generation(ws.engram_id)

        # Generate and store the new invite key.
        invite_key, key_hash = generate_invite_key(
            db_url=ws.db_url,
            engram_id=ws.engram_id,
            expires_days=expires_days,
            uses_remaining=uses,
            schema=ws.schema,
            key_generation=new_gen,
        )
        expires_ts = datetime.fromtimestamp(
            time.time() + expires_days * 86400, tz=timezone.utc
        ).isoformat()
        await self.storage.insert_invite_key(
            key_hash=key_hash,
            engram_id=ws.engram_id,
            expires_at=expires_ts,
            uses_remaining=uses,
        )

        # Persist updated generation to local workspace.json.
        updated_config = WorkspaceConfig(
            engram_id=ws.engram_id,
            db_url=ws.db_url,
            schema=ws.schema,
            anonymous_mode=ws.anonymous_mode,
            anon_agents=ws.anon_agents,
            key_generation=new_gen,
            is_creator=True,
        )
        write_workspace(updated_config)

        grace_until: str | None = None
        if grace_minutes > 0:
            from datetime import timedelta

            grace_until = (
                datetime.now(timezone.utc) + timedelta(minutes=grace_minutes)
            ).isoformat()

        # Audit log entry — no PII.
        import json as _json

        await self._audit(
            "key_rotation",
            extra=_json.dumps(
                {
                    "old_generation": old_gen,
                    "new_generation": new_gen,
                    "grace_minutes": grace_minutes,
                    "grace_until": grace_until,
                    "reason": reason or "",
                    "actor": actor or "unknown",
                }
            ),
        )

        # Webhook notification via existing delivery worker.
        asyncio.ensure_future(
            self._fire_event(
                "invite_key.rotated",
                {
                    "workspace_id": ws.engram_id,
                    "old_generation": old_gen,
                    "new_generation": new_gen,
                    "rotated_by": actor or "unknown",
                    "grace_until": grace_until,
                    "reason": reason or "",
                },
            )
        )

        logger.warning(
            "Invite key rotated: workspace=%s old_gen=%d new_gen=%d grace_minutes=%d actor=%s",
            ws.engram_id,
            old_gen,
            new_gen,
            grace_minutes,
            actor or "unknown",
        )

        return {
            "invite_key": invite_key,
            "old_generation": old_gen,
            "new_generation": new_gen,
            "grace_until": grace_until,
        }

    async def get_rotation_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return invite key rotation audit entries for this workspace.

        Ordered most-recent first. Capped at 200 entries.
        """
        from engram.workspace import read_workspace

        ws = read_workspace()
        if ws is None:
            return []
        engram_id = ws.engram_id if ws.db_url else "local"
        return await self.storage.get_key_rotation_history(engram_id, limit=max(1, min(limit, 200)))

    # ── GDPR subject erasure ─────────────────────────────────────────

    async def gdpr_erase_agent(
        self,
        agent_id: str,
        mode: Literal["soft", "hard"],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Erase all personal data for a given agent from this workspace.

        Gated to workspace creators only.  Use ``mode='soft'`` to redact
        attribution fields while keeping fact content intact, or
        ``mode='hard'`` to also wipe fact content, close validity windows,
        and cascade-dismiss related open conflicts.

        Args:
            agent_id: The agent whose data should be erased.
            mode: ``'soft'`` or ``'hard'``.
            actor: Identity of the person triggering the erasure (for audit).

        Returns:
            A summary dict with counts of affected rows per table.

        Raises:
            ValueError: If agent_id is empty or mode is invalid.
            PermissionError: If the caller is not a workspace creator.
        """
        if not agent_id or not agent_id.strip():
            raise ValueError("agent_id must be a non-empty string.")
        if mode not in ("soft", "hard"):
            raise ValueError("mode must be 'soft' or 'hard'.")

        # Creator-only gate — read local workspace.json
        try:
            from engram.workspace import read_workspace

            ws = read_workspace()
            if ws is None or not ws.is_creator:
                raise PermissionError(
                    "GDPR erasure is restricted to the workspace creator. "
                    "Only the founder who ran engram_init may perform this operation."
                )
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError(f"Unable to verify workspace creator status: {exc}") from exc

        if mode == "soft":
            stats = await self.storage.gdpr_soft_erase_agent(agent_id)
        else:
            stats = await self.storage.gdpr_hard_erase_agent(agent_id)

        await self._audit(
            "gdpr_erase",
            agent_id=None,  # do not store the erased agent_id in the audit trail
            extra=f'{{"mode":"{mode}","facts_updated":{stats["facts_updated"]},'
            f'"conflicts_closed":{stats["conflicts_closed"]},'
            f'"actor":"{actor or "unknown"}"}}',
        )

        return {
            "erased_agent_id": agent_id,
            "mode": mode,
            "stats": stats,
        }


def _content_hash(content: str) -> str:
    """SHA-256 of lowercased, whitespace-normalized content."""
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
