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
from typing import Any

import numpy as np

from engram import embeddings
from engram.entities import extract_entities, extract_keywords
from engram.secrets import scan_for_secrets
from engram.storage import Storage

logger = logging.getLogger("engram")


class EngramEngine:
    """Core engine coordinating commit, query, detection, and resolution."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._detection_queue: asyncio.Queue[str] = asyncio.Queue()
        self._suggestion_queue: asyncio.Queue[str] = asyncio.Queue()
        self._detection_task: asyncio.Task[None] | None = None
        self._ttl_task: asyncio.Task[None] | None = None
        self._calibration_task: asyncio.Task[None] | None = None
        self._suggestion_task: asyncio.Task[None] | None = None
        self._escalation_task: asyncio.Task[None] | None = None
        self._nli_model: Any = None
        self._nli_threshold_high: float = 0.85
        self._nli_threshold_low: float = 0.50

    async def start(self) -> None:
        """Start the background detection worker and periodic tasks."""
        self._detection_task = asyncio.create_task(self._detection_worker())
        self._ttl_task = asyncio.create_task(self._ttl_expiry_loop())
        self._calibration_task = asyncio.create_task(self._calibration_loop())
        self._suggestion_task = asyncio.create_task(self._suggestion_worker())
        self._escalation_task = asyncio.create_task(self._escalation_loop())
        logger.info("Detection worker started")

    async def stop(self) -> None:
        """Stop all background tasks."""
        for task in (
            self._detection_task, self._ttl_task, self._calibration_task,
            self._suggestion_task, self._escalation_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._detection_task = None
        self._ttl_task = None
        self._calibration_task = None
        self._suggestion_task = None
        self._escalation_task = None

    # ── engram_commit ────────────────────────────────────────────────

    async def commit(
        self,
        content: str,
        scope: str,
        confidence: float,
        agent_id: str | None = None,
        engineer: str | None = None,
        corrects_lineage: str | None = None,
        provenance: str | None = None,
        fact_type: str = "observation",
        ttl_days: int | None = None,
        artifact_hash: str | None = None,
    ) -> dict[str, Any]:
        """Commit a fact to shared memory. Returns immediately; detection is async."""

        # Step 1: Validate
        if not content or not content.strip():
            raise ValueError("Content cannot be empty.")
        if not scope or not scope.strip():
            raise ValueError("Scope cannot be empty.")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0.")
        if fact_type not in ("observation", "inference", "decision"):
            raise ValueError("fact_type must be 'observation', 'inference', or 'decision'.")

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
            }

        # Step 5: Generate embedding
        emb = embeddings.encode(content)
        emb_bytes = embeddings.embedding_to_bytes(emb)

        # Step 6: Extract keywords and entities
        keywords = extract_keywords(content)
        entities = extract_entities(content)

        # Step 7: Determine agent_id
        if not agent_id:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"

        # Step 8: Register/update agent
        await self.storage.upsert_agent(agent_id, engineer or "unknown")

        # Step 9: Determine lineage_id
        if corrects_lineage:
            lineage_id = corrects_lineage
            # Close the old fact's validity window
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
        }

        # Step 11: INSERT (write lock held ~1ms)
        await self.storage.insert_fact(fact)

        # Step 12: Increment agent commit count
        await self.storage.increment_agent_commits(agent_id)

        # Step 13: Queue for async detection
        await self._detection_queue.put(fact_id)

        return {
            "fact_id": fact_id,
            "committed_at": now,
            "duplicate": False,
            "conflicts_detected": False,  # detection is async
        }

    # ── engram_query ─────────────────────────────────────────────────

    async def query(
        self,
        topic: str,
        scope: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
        fact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query what the team's agents collectively know about a topic."""
        limit = min(limit, 50)

        # Get candidate facts
        candidates = await self.storage.get_current_facts_in_scope(
            scope=scope, fact_type=fact_type, as_of=as_of, limit=200
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

        # Score candidates using RRF fusion
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

            # Recency signal
            try:
                committed = datetime.fromisoformat(fact["committed_at"])
                days_old = (datetime.now(timezone.utc) - committed).days
                recency = math.exp(-0.05 * days_old)
            except (ValueError, TypeError):
                recency = 0.5

            # Agent trust signal
            agent = agent_map.get(fact.get("agent_id", ""))
            if agent and agent["total_commits"] > 0:
                trust = 1.0 - (agent["flagged_commits"] / agent["total_commits"])
            else:
                trust = 0.8  # default for unknown agents

            score = relevance + 0.2 * recency + 0.15 * trust

            # Penalize facts with unresolved conflicts — value shouldn't
            # require a human to review before the ranking reflects uncertainty
            if fid in open_conflict_ids:
                score *= 0.7

            scored.append((score, fact))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Build response
        results: list[dict[str, Any]] = []
        for score, fact in scored[:limit]:
            results.append({
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
                "relevance_score": round(score, 4),
            })

        return results

    # ── engram_conflicts ─────────────────────────────────────────────

    async def get_conflicts(
        self, scope: str | None = None, status: str = "open"
    ) -> list[dict[str, Any]]:
        """Get conflicts, optionally filtered by scope and status."""
        rows = await self.storage.get_conflicts(scope=scope, status=status)
        results = []
        for r in rows:
            results.append({
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
            })
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

        return {
            "resolved": success,
            "conflict_id": conflict_id,
            "resolution_type": resolution_type,
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
                task = asyncio.create_task(
                    self._detect_with_semaphore(fact_id, semaphore)
                )
                active.add(task)
                task.add_done_callback(active.discard)
        except asyncio.CancelledError:
            for t in list(active):
                t.cancel()

    async def _detect_with_semaphore(
        self, fact_id: str, semaphore: asyncio.Semaphore
    ) -> None:
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

        # ── Tier 0: Entity exact-match conflicts ─────────────────────
        tier0_flagged: set[str] = set()
        for entity in entities:
            if entity.get("type") in ("numeric", "config_key", "version") and entity.get("value") is not None:
                conflicts = await self.storage.find_entity_conflicts(
                    entity_name=entity["name"],
                    entity_type=entity["type"],
                    entity_value=str(entity["value"]),
                    scope=fact["scope"],
                    exclude_id=fact_id,
                )
                for c in conflicts:
                    if c["id"] not in tier0_flagged:
                        already = await self.storage.conflict_exists(fact_id, c["id"])
                        if not already:
                            conflict_id = uuid.uuid4().hex
                            await self.storage.insert_conflict({
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
                            })
                            await self._suggestion_queue.put(conflict_id)
                            tier0_flagged.add(c["id"])

        # ── Tier 2b: Cross-scope entity detection ────────────────────
        tier2b_flagged: set[str] = set()
        for entity in entities:
            if entity.get("type") in ("numeric", "config_key", "version", "technology") and entity.get("value") is not None:
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
                        already = await self.storage.conflict_exists(fact_id, c["id"])
                        if not already:
                            conflict_id = uuid.uuid4().hex
                            await self.storage.insert_conflict({
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
                            })
                            await self._suggestion_queue.put(conflict_id)
                            tier2b_flagged.add(c["id"])

        # ── Tier 2: Numeric and temporal rules (parallel with Tier 1) ────
        tier2_flagged: set[str] = set()
        scope_facts = await self.storage.get_current_facts_in_scope(
            scope=fact["scope"], limit=50
        )
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
                    if e_new["name"] == e_cand["name"] and str(e_new["value"]) != str(e_cand["value"]):
                        if candidate["id"] not in tier2_flagged:
                            already = await self.storage.conflict_exists(fact_id, candidate["id"])
                            if not already:
                                conflict_id = uuid.uuid4().hex
                                await self.storage.insert_conflict({
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
                                })
                                await self._suggestion_queue.put(conflict_id)
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
                        severity = "high" if fact.get("engineer") != candidate.get("engineer") else "medium"
                        conflict_id = uuid.uuid4().hex
                        await self.storage.insert_conflict({
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
                        })
                        await self._suggestion_queue.put(conflict_id)

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

        fact_a = await self.storage.get_fact_by_id(conflict["fact_a_id"])
        fact_b = await self.storage.get_fact_by_id(conflict["fact_b_id"])
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
                for conflict in stale:
                    try:
                        await self._escalate_conflict(conflict)
                    except Exception:
                        logger.exception("Escalation error for conflict %s", conflict["id"])
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Escalation loop error")

    async def _escalate_conflict(self, conflict: dict[str, Any]) -> None:
        """Auto-resolve a stale conflict by preferring the more recent fact.

        Closes the older fact's validity window and records a clear audit trail
        indicating this was a system action, not a human decision.
        """
        fact_a = await self.storage.get_fact_by_id(conflict["fact_a_id"])
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
            conflict["id"][:12], winner["id"][:8],
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

    # ── Periodic TTL expiry ──────────────────────────────────────────

    async def _ttl_expiry_loop(self) -> None:
        """Periodically expire TTL facts (every 60 seconds)."""
        while True:
            try:
                await asyncio.sleep(60)
                expired = await self.storage.expire_ttl_facts()
                if expired:
                    logger.info("TTL expiry: closed %d fact(s)", expired)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("TTL expiry loop error")

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
                            self._nli_threshold_high, new_threshold, fp_rate, total,
                        )
                        self._nli_threshold_high = new_threshold
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Calibration loop error")


def _content_hash(content: str) -> str:
    """SHA-256 of lowercased, whitespace-normalized content."""
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
