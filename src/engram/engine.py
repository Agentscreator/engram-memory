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

logger = logging.getLogger("engram")


class EngramEngine:
    """Core engine coordinating commit, query, detection, and resolution."""

    def __init__(self, storage: BaseStorage) -> None:
        self.storage = storage
        self._detection_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._suggestion_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._detection_task: asyncio.Task[None] | None = None
        self._ttl_task: asyncio.Task[None] | None = None
        self._decay_task: asyncio.Task[None] | None = None
        self._calibration_task: asyncio.Task[None] | None = None
        self._suggestion_task: asyncio.Task[None] | None = None
        self._escalation_task: asyncio.Task[None] | None = None
        self._webhook_task: asyncio.Task[None] | None = None
        self._nli_model: Any = None
        self._nli_threshold_high: float = 0.85
        self._nli_threshold_low: float = 0.50
        self._sse_subscribers: dict[str, list[asyncio.Queue]] = {}

    async def start(self) -> None:
        """Start the background detection worker and periodic tasks."""
        self._detection_task = asyncio.create_task(self._detection_worker())
        self._ttl_task = asyncio.create_task(self._ttl_expiry_loop())
        self._decay_task = asyncio.create_task(self._decay_loop())
        self._calibration_task = asyncio.create_task(self._calibration_loop())
        self._suggestion_task = asyncio.create_task(self._suggestion_worker())
        self._escalation_task = asyncio.create_task(self._escalation_loop())
        self._webhook_task = asyncio.create_task(self._webhook_delivery_worker())
        logger.info("Detection worker started")

    async def stop(self) -> None:
        """Stop all background tasks."""
        for task in (
            self._detection_task,
            self._ttl_task,
            self._decay_task,
            self._calibration_task,
            self._suggestion_task,
            self._escalation_task,
            self._webhook_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._detection_task = None
        self._ttl_task = None
        self._decay_task = None
        self._calibration_task = None
        self._suggestion_task = None
        self._escalation_task = None
        self._webhook_task = None

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

        # Step 9: Determine lineage_id and handle update/auto-update
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

        # Step 10: Build fact record
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

        # Step 11: INSERT (write lock held ~1ms)
        await self.storage.insert_fact(fact)

        # Step 12: Increment agent commit count
        await self.storage.increment_agent_commits(agent_id)

        # Step 13: Queue for async detection (skip for ephemeral facts)
        if durability == "durable":
            try:
                await asyncio.wait_for(self._detection_queue.put(fact_id), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Detection queue full, skipping conflict check for %s",
                    fact_id[:12],
                )

        # Step 14: Check for corroboration (Phase 2: multi-agent consensus)
        # Find semantically similar facts from different agents in the same scope
        await self._check_corroboration(fact_id, emb, agent_id, scope)

        result = {
            "fact_id": fact_id,
            "committed_at": now,
            "duplicate": False,
            "conflicts_detected": False,  # detection is async
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
                entities = json.loads(fact.get("entities") or "[]")
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

            # Combined score — weights tuned for relevance at scale.
            # Recency is the strongest signal after relevance because at
            # 100k+ facts, old context is the primary source of noise.
            score = (
                relevance
                + 0.25 * recency
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
            if fid in open_conflict_ids:
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
            results.append(
                {
                    "fact_id": fact["id"],
                    "content": fact["content"],
                    "scope": fact["scope"],
                    "confidence": fact["confidence"],
                    "fact_type": fact["fact_type"],
                    "agent_id": fact["agent_id"],
                    "committed_at": fact["committed_at"],
                    "has_open_conflict": fact["id"] in open_conflict_ids,
                    "verified": fact.get("provenance") is not None,
                    "provenance": fact.get("provenance"),
                    "corroborating_agents": fact.get("corroborating_agents", 0),
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

        # Track query hits on ephemeral facts and auto-promote if threshold met
        if ephemeral_ids:
            await self.storage.increment_query_hits(ephemeral_ids)
            # Auto-promote ephemeral facts that have now been queried enough
            promotable = await self.storage.get_promotable_ephemeral_facts(min_hits=2)
            for pf in promotable:
                promoted = await self.storage.promote_fact(pf["id"])
                if promoted:
                    logger.info(
                        "Auto-promoted ephemeral fact %s to durable (query_hits >= 2)",
                        pf["id"][:12],
                    )

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

            score = sim * score_penalty

            results.append(
                {
                    "fact_id": fact["id"],
                    "content": fact["content"],
                    "scope": fact["scope"],
                    "confidence": fact["confidence"],
                    "fact_type": fact["fact_type"],
                    "agent_id": fact["agent_id"],
                    "committed_at": fact["committed_at"],
                    "has_open_conflict": fact["id"] in open_conflict_ids,
                    "verified": fact.get("provenance") is not None,
                    "provenance": fact.get("provenance"),
                    "corroborating_agents": fact.get("corroborating_agents", 0),
                    "relevance_score": round(score, 4),
                    "durability": fact.get("durability", "durable"),
                    "adjacent": True,
                    "original_scope": fact["scope"],
                }
            )

        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return results

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
        if fact.get("valid_until") is not None:
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

    # ── engram_conflicts ─────────────────────────────────────────────

    async def get_conflicts(
        self, scope: str | None = None, status: str = "open"
    ) -> list[dict[str, Any]]:
        """Get conflicts, optionally filtered by scope and status."""
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
                }
            )
        return results

    # ── engram_resolve ───────────────────────────────────────────────

    async def resolve(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
        winning_claim_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a conflict."""
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
            # Close the losing fact's validity window
            loser_id = (
                conflict["fact_b_id"]
                if winning_claim_id == conflict["fact_a_id"]
                else conflict["fact_a_id"]
            )
            await self.storage.close_validity_window(fact_id=loser_id)
            # Flag the losing agent
            loser_fact = await self.storage.get_fact_by_id(loser_id)
            if loser_fact:
                await self.storage.increment_agent_flagged(loser_fact["agent_id"])

        elif resolution_type == "merge":
            # Both originals get their windows closed
            await self.storage.close_validity_window(fact_id=conflict["fact_a_id"])
            await self.storage.close_validity_window(fact_id=conflict["fact_b_id"])

        elif resolution_type == "dismissed":
            # Record false positive feedback for NLI calibration
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
                        {
                            "conflict_id": conflict_id,
                            "resolution_type": resolution_type,
                        },
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
        """Dismiss multiple open conflicts in one call.

        Useful for clearing noise from detection (e.g. false positives flagged
        by feedback, or old conflicts after a major refactor). Each conflict
        is dismissed individually; a failure on one does not abort the rest.

        Args:
            conflict_ids: List of conflict IDs to dismiss (max 100).
            reason: Human-readable reason recorded on each conflict.
            dismissed_by: Agent or user performing the dismissal.

        Returns:
            {total, dismissed, failed, results: [{conflict_id, status, error?}]}
        """
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

    # ── Detection Worker (Phase 3) ───────────────────────────────────

    async def _detection_worker(self) -> None:
        """Background worker consuming from the detection queue.

        Runs up to 3 detections concurrently so a burst of commits from
        multiple agents doesn't serialize behind a slow NLI call.
        """
        logger.info("Detection worker running")
        semaphore = asyncio.Semaphore(3)
        active: set[asyncio.Task[None]] = set()
        try:
            while True:
                fact_id = await self._detection_queue.get()
                task = asyncio.create_task(self._detect_with_semaphore(fact_id, semaphore))
                active.add(task)
                task.add_done_callback(active.discard)
        except asyncio.CancelledError:
            for t in list(active):
                t.cancel()
            for t in list(active):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _detect_with_semaphore(self, fact_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                await self._run_detection(fact_id)
            except Exception:
                logger.exception("Detection error for fact %s", fact_id)
            finally:
                self._detection_queue.task_done()

    async def _run_detection(self, fact_id: str) -> None:
        """Run the tiered detection pipeline for a newly committed fact."""
        fact = await self.storage.get_fact_by_id(fact_id)
        if not fact or fact.get("valid_until"):
            return  # Already superseded or not found

        # Re-generate embedding if missing.
        # Facts ingested via federation arrive without embeddings because binary
        # BLOBs are stripped from the JSON federation response. Re-embed locally
        # so the fact participates in semantic search and Tier 1 NLI detection.
        if not fact.get("embedding"):
            try:
                emb = embeddings.encode(fact["content"])
                emb_bytes = embeddings.embedding_to_bytes(emb)
                await self.storage.update_fact_embedding(fact_id, emb_bytes)
                fact["embedding"] = emb_bytes
                logger.debug("Re-generated embedding for fact %s (was missing)", fact_id)
            except Exception:
                logger.warning(
                    "Could not re-generate embedding for fact %s; "
                    "Tier 1 NLI detection will be skipped for this fact.",
                    fact_id,
                )

        entities = json.loads(fact.get("entities") or "[]")
        now = datetime.now(timezone.utc).isoformat()

        # Pre-fetch all fact IDs that already have a conflict with fact_id.
        # This single query replaces the per-candidate conflict_exists() calls
        # in Tier 0, Tier 2b, and Tier 2, avoiding N+1 query patterns.
        existing_conflict_ids = await self.storage.get_conflicting_fact_ids(fact_id)

        # ── Tier 0: Entity exact-match conflicts ─────────────────────
        tier0_flagged: set[str] = set()
        for entity in entities:
            if (
                entity.get("type") in ("numeric", "config_key", "version")
                and entity.get("value") is not None
            ):
                conflicts = await self.storage.find_entity_conflicts(
                    entity_name=entity["name"],
                    entity_type=entity["type"],
                    entity_value=str(entity["value"]),
                    scope=fact["scope"],
                    exclude_id=fact_id,
                )
                for c in conflicts:
                    if c["id"] not in tier0_flagged:
                        if c["id"] not in existing_conflict_ids:
                            conflict_id = uuid.uuid4().hex
                            await self.storage.insert_conflict(
                                {
                                    "id": conflict_id,
                                    "fact_a_id": fact_id,
                                    "fact_b_id": c["id"],
                                    "detected_at": now,
                                    "detection_tier": "tier0_entity",
                                    "nli_score": None,
                                    "explanation": (
                                        f"Entity '{entity['name']}' has conflicting values: "
                                        f"'{entity['value']}' vs existing value in fact {c['id'][:8]}..."
                                    ),
                                    "severity": "high",
                                    "status": "open",
                                }
                            )
                            try:
                                self._suggestion_queue.put_nowait(conflict_id)
                            except asyncio.QueueFull:
                                logger.warning(
                                    "Suggestion queue full, skipping suggestion for conflict %s",
                                    conflict_id[:12],
                                )
                            asyncio.ensure_future(self._apply_rules(conflict_id))
                            asyncio.ensure_future(
                                self._fire_event(
                                    "conflict.detected",
                                    {
                                        "conflict_id": conflict_id,
                                        "fact_a_id": fact_id,
                                        "fact_b_id": c["id"],
                                        "scope": fact["scope"],
                                        "detection_tier": "tier0_entity",
                                    },
                                )
                            )
                            tier0_flagged.add(c["id"])

        # ── Tier 2b: Cross-scope entity detection ────────────────────
        tier2b_flagged: set[str] = set()
        for entity in entities:
            if (
                entity.get("type") in ("numeric", "config_key", "version", "technology")
                and entity.get("value") is not None
            ):
                cross_matches = await self.storage.find_cross_scope_entity_matches(
                    entity_name=entity["name"],
                    entity_type=entity["type"],
                    entity_value=str(entity["value"]),
                    exclude_id=fact_id,
                )
                for c in cross_matches:
                    if c["id"] not in tier0_flagged and c["id"] not in tier2b_flagged:
                        if c["scope"] == fact["scope"]:
                            continue  # Already handled by Tier 0
                        if c["id"] not in existing_conflict_ids:
                            conflict_id = uuid.uuid4().hex
                            await self.storage.insert_conflict(
                                {
                                    "id": conflict_id,
                                    "fact_a_id": fact_id,
                                    "fact_b_id": c["id"],
                                    "detected_at": now,
                                    "detection_tier": "tier2b_cross_scope",
                                    "nli_score": None,
                                    "explanation": (
                                        f"Cross-scope entity conflict: '{entity['name']}' differs "
                                        f"between scope '{fact['scope']}' and '{c['scope']}'"
                                    ),
                                    "severity": "high",
                                    "status": "open",
                                }
                            )
                            try:
                                self._suggestion_queue.put_nowait(conflict_id)
                            except asyncio.QueueFull:
                                logger.warning(
                                    "Suggestion queue full, skipping suggestion for conflict %s",
                                    conflict_id[:12],
                                )
                            asyncio.ensure_future(self._apply_rules(conflict_id))
                            asyncio.ensure_future(
                                self._fire_event(
                                    "conflict.detected",
                                    {
                                        "conflict_id": conflict_id,
                                        "fact_a_id": fact_id,
                                        "fact_b_id": c["id"],
                                        "scope": fact["scope"],
                                        "detection_tier": "tier2b_cross_scope",
                                    },
                                )
                            )
                            tier2b_flagged.add(c["id"])

        # ── Tier 2: Numeric and temporal rules (parallel with Tier 1) ────
        tier2_flagged: set[str] = set()
        scope_facts = await self.storage.get_current_facts_in_scope(scope=fact["scope"], limit=50)
        for candidate in scope_facts:
            if candidate["id"] == fact_id:
                continue
            if candidate["id"] in tier0_flagged or candidate["id"] in tier2b_flagged:
                continue
            c_entities = json.loads(candidate.get("entities") or "[]")
            for e_new in entities:
                if e_new.get("type") != "numeric" or e_new.get("value") is None:
                    continue
                for e_cand in c_entities:
                    if e_cand.get("type") != "numeric" or e_cand.get("value") is None:
                        continue
                    if e_new["name"] == e_cand["name"] and str(e_new["value"]) != str(
                        e_cand["value"]
                    ):
                        if candidate["id"] not in tier2_flagged:
                            if candidate["id"] not in existing_conflict_ids:
                                conflict_id = uuid.uuid4().hex
                                await self.storage.insert_conflict(
                                    {
                                        "id": conflict_id,
                                        "fact_a_id": fact_id,
                                        "fact_b_id": candidate["id"],
                                        "detected_at": now,
                                        "detection_tier": "tier2_numeric",
                                        "nli_score": None,
                                        "explanation": (
                                            f"Numeric conflict: '{e_new['name']}' = {e_new['value']} "
                                            f"vs {e_cand['value']}"
                                        ),
                                        "severity": "high",
                                        "status": "open",
                                    }
                                )
                                try:
                                    self._suggestion_queue.put_nowait(conflict_id)
                                except asyncio.QueueFull:
                                    logger.warning(
                                        "Suggestion queue full, skipping suggestion for conflict %s",
                                        conflict_id[:12],
                                    )
                                asyncio.ensure_future(self._apply_rules(conflict_id))
                                asyncio.ensure_future(
                                    self._fire_event(
                                        "conflict.detected",
                                        {
                                            "conflict_id": conflict_id,
                                            "fact_a_id": fact_id,
                                            "fact_b_id": candidate["id"],
                                            "scope": fact["scope"],
                                            "detection_tier": "tier2_numeric",
                                        },
                                    )
                                )
                                tier2_flagged.add(candidate["id"])

        # ── Tier 1: NLI cross-encoder ────────────────────────────────
        # Gather candidates via three parallel paths:
        # Path A: embedding-similar facts in scope (top 20)
        # Path B: FTS5 BM25 lexical matches (top 10)
        # Path C: entity-overlapping facts (already found above)
        already_flagged = tier0_flagged | tier2b_flagged | tier2_flagged

        # Path A: embedding similarity
        emb_candidates: dict[str, dict] = {}
        if fact.get("embedding"):
            fact_emb = embeddings.bytes_to_embedding(fact["embedding"])
            scored_emb = []
            for c in scope_facts:
                if c["id"] == fact_id or c["id"] in already_flagged:
                    continue
                if c.get("embedding"):
                    c_emb = embeddings.bytes_to_embedding(c["embedding"])
                    sim = embeddings.cosine_similarity(fact_emb, c_emb)
                    scored_emb.append((sim, c))
            scored_emb.sort(key=lambda x: x[0], reverse=True)
            for _, c in scored_emb[:20]:
                emb_candidates[c["id"]] = c

        # Path B: FTS5 lexical matches
        try:
            fts_rowids = await self.storage.fts_search(fact["content"][:200], limit=10)
            if fts_rowids:
                fts_facts = await self.storage.get_facts_by_rowids(fts_rowids)
                for c in fts_facts:
                    if c["id"] != fact_id and c["id"] not in already_flagged:
                        emb_candidates.setdefault(c["id"], c)
        except Exception:
            pass  # FTS may fail on complex content

        # Union, dedup, cap at 30
        nli_candidates = list(emb_candidates.values())[:30]

        if not nli_candidates:
            return

        # Run NLI on candidates
        nli_model = self._get_nli_model()
        if nli_model is None:
            return  # NLI model not available

        for candidate in nli_candidates:
            try:
                scores = nli_model.predict(
                    [(fact["content"], candidate["content"])],
                    apply_softmax=True,
                )
                if hasattr(scores, "tolist"):
                    scores = scores.tolist()
                if isinstance(scores[0], list):
                    scores = scores[0]

                # scores: [contradiction, entailment, neutral]
                contradiction_score = float(scores[0])
                entailment_score = float(scores[1])

                # Stale supersession: same lineage + high entailment
                if (
                    fact.get("lineage_id")
                    and candidate.get("lineage_id") == fact["lineage_id"]
                    and entailment_score > 0.85
                ):
                    await self.storage.close_validity_window(fact_id=candidate["id"])
                    continue

                if contradiction_score > self._nli_threshold_high:
                    already = await self.storage.conflict_exists(fact_id, candidate["id"])
                    if not already:
                        severity = (
                            "high"
                            if fact.get("engineer") != candidate.get("engineer")
                            else "medium"
                        )
                        conflict_id = uuid.uuid4().hex
                        await self.storage.insert_conflict(
                            {
                                "id": conflict_id,
                                "fact_a_id": fact_id,
                                "fact_b_id": candidate["id"],
                                "detected_at": now,
                                "detection_tier": "tier1_nli",
                                "nli_score": contradiction_score,
                                "explanation": (
                                    f"Semantic contradiction (NLI score: {contradiction_score:.2f}): "
                                    f'"{fact["content"][:80]}..." vs '
                                    f'"{candidate["content"][:80]}..."'
                                ),
                                "severity": severity,
                                "status": "open",
                            }
                        )
                        try:
                            self._suggestion_queue.put_nowait(conflict_id)
                        except asyncio.QueueFull:
                            logger.warning(
                                "Suggestion queue full, skipping suggestion for conflict %s",
                                conflict_id[:12],
                            )
                        asyncio.ensure_future(self._apply_rules(conflict_id))
                        asyncio.ensure_future(
                            self._fire_event(
                                "conflict.detected",
                                {
                                    "conflict_id": conflict_id,
                                    "fact_a_id": fact_id,
                                    "fact_b_id": candidate["id"],
                                    "scope": fact["scope"],
                                    "detection_tier": "tier1_nli",
                                },
                            )
                        )

            except Exception:
                logger.exception("NLI inference failed for pair %s / %s", fact_id, candidate["id"])

    # ── Suggestion Worker (async, post-detection) ────────────────────

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
            return  # Already has a suggestion

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
        """Every hour: auto-resolve conflicts that have been open for 72h+ without review."""
        while True:
            try:
                await asyncio.sleep(3600)  # check every hour
                stale = await self.storage.get_stale_open_conflicts(older_than_hours=72)
                if stale:
                    # Batch-fetch all referenced facts in one query instead of
                    # two get_fact_by_id() calls per conflict (N+1 avoidance).
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
        """Auto-resolve a stale conflict by preferring the more recent fact.

        Closes the older fact's validity window and records a clear audit trail
        indicating this was a system action, not a human decision.

        fact_a / fact_b may be pre-fetched by the caller (escalation loop batch)
        to avoid repeated get_fact_by_id() queries.
        """
        if fact_a is None:
            fact_a = await self.storage.get_fact_by_id(conflict["fact_a_id"])
        if fact_b is None:
            fact_b = await self.storage.get_fact_by_id(conflict["fact_b_id"])
        if not fact_a or not fact_b:
            return

        # Prefer the more recently committed fact
        a_time = fact_a.get("committed_at", "")
        b_time = fact_b.get("committed_at", "")
        if a_time >= b_time:
            winner, loser = fact_a, fact_b
        else:
            winner, loser = fact_b, fact_a

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


def _content_hash(content: str) -> str:
    """SHA-256 of lowercased, whitespace-normalized content."""
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
