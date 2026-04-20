"""Temporal Knowledge Graph (TKG) tests.

Validates the TKG layer inspired by Zep's Graphiti approach (arXiv:2501.13956):
- Relationship extraction from fact content
- Entity node upsert and deduplication
- Bi-temporal edge creation and invalidation
- Reversal detection (A→B→A patterns)
- Belief drift detection across agents
- Stale edge detection
- TKG integration with the conflict detection pipeline
"""

from __future__ import annotations

import pytest

from engram.engine import EngramEngine
from engram.storage import Storage
from engram.tkg import (
    TemporalKnowledgeGraph,
    extract_relationships,
)


# ── Relationship extraction ──────────────────────────────────────────


class TestRelationshipExtraction:
    """Test the regex-based relationship extraction pipeline."""

    def test_uses_relationship(self):
        rels = extract_relationships("The auth service uses Redis for session storage")
        assert len(rels) >= 1
        uses_rels = [r for r in rels if r["relation"] == "uses"]
        assert len(uses_rels) >= 1
        assert uses_rels[0]["subject"] == "auth service"
        assert uses_rels[0]["object"] == "redis"

    def test_depends_on_relationship(self):
        rels = extract_relationships("The payment worker depends on Kafka for event streaming")
        assert len(rels) >= 1
        dep_rels = [r for r in rels if r["relation"] == "depends_on"]
        assert len(dep_rels) >= 1
        assert dep_rels[0]["subject"] == "payment worker"
        assert dep_rels[0]["object"] == "kafka"

    def test_switched_from_to(self):
        rels = extract_relationships("We switched from REST to GraphQL for the API")
        assert len(rels) >= 1
        replaced = [r for r in rels if r["relation"] == "replaced_by"]
        assert len(replaced) >= 1
        assert replaced[0]["subject"] == "rest"
        assert replaced[0]["object"] == "graphql"

    def test_migrated_from_to(self):
        rels = extract_relationships("We migrated from MySQL to PostgreSQL")
        assert len(rels) >= 1
        replaced = [r for r in rels if r["relation"] == "replaced_by"]
        assert len(replaced) >= 1
        assert replaced[0]["subject"] == "mysql"
        assert replaced[0]["object"] == "postgresql"

    def test_configured_as(self):
        rels = extract_relationships("The cache is configured as LRU")
        assert len(rels) >= 1
        config_rels = [r for r in rels if r["relation"] == "configured_as"]
        assert len(config_rels) >= 1

    def test_runs_on(self):
        rels = extract_relationships("The API runs on Kubernetes")
        assert len(rels) >= 1
        runs = [r for r in rels if r["relation"] == "runs_on"]
        assert len(runs) >= 1
        assert runs[0]["object"] == "kubernetes"

    def test_no_relationships_in_plain_text(self):
        rels = extract_relationships("The weather is nice today")
        # Should not extract spurious relationships
        assert len(rels) == 0

    def test_stop_words_filtered(self):
        rels = extract_relationships("It uses something")
        # "it" is a stop word, should be filtered
        uses_rels = [r for r in rels if r["relation"] == "uses"]
        assert all(r["subject"] != "it" for r in uses_rels)

    def test_multiple_relationships(self):
        content = "The auth service uses Redis and the API runs on Kubernetes"
        rels = extract_relationships(content)
        relations = {r["relation"] for r in rels}
        assert "uses" in relations
        assert "runs_on" in relations


# ── TKG Node and Edge operations ─────────────────────────────────────


@pytest.mark.asyncio
async def test_tkg_node_creation(storage: Storage):
    """Ingesting a fact creates entity nodes in the TKG."""
    tkg = TemporalKnowledgeGraph(storage)
    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis for caching",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    # Should have created nodes for "auth service" and "redis"
    auth_node = await storage.get_tkg_node_by_name("auth service")
    redis_node = await storage.get_tkg_node_by_name("redis")
    assert auth_node is not None
    assert redis_node is not None
    assert auth_node["entity_type"] in ("service", "component")
    assert redis_node["entity_type"] == "technology"


@pytest.mark.asyncio
async def test_tkg_edge_creation(storage: Storage):
    """Ingesting a fact creates temporal edges between nodes."""
    tkg = TemporalKnowledgeGraph(storage)
    edges = await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis for caching",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    assert len(edges) >= 1
    uses_edges = [e for e in edges if e.relation_type == "uses"]
    assert len(uses_edges) >= 1
    assert uses_edges[0].fact_id == "fact-001"
    assert uses_edges[0].agent_id == "agent-a"
    assert uses_edges[0].scope == "infra"
    assert uses_edges[0].is_active


@pytest.mark.asyncio
async def test_tkg_node_dedup(storage: Storage):
    """Ingesting multiple facts about the same entity reuses the node."""
    tkg = TemporalKnowledgeGraph(storage)
    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses PostgreSQL",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )

    # "auth service" node should exist only once, with fact_count >= 2
    node = await storage.get_tkg_node_by_name("auth service")
    assert node is not None
    assert node["fact_count"] >= 2


@pytest.mark.asyncio
async def test_tkg_edge_invalidation(storage: Storage):
    """A new edge on the same source+relation invalidates the old one."""
    tkg = TemporalKnowledgeGraph(storage)

    # First: auth service uses Redis
    edges1 = await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    assert len(edges1) >= 1
    assert edges1[0].is_active

    # Second: auth service uses Memcached (should invalidate Redis edge)
    edges2 = await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )
    assert len(edges2) >= 1
    assert edges2[0].is_active

    # The Redis edge should now be expired
    auth_node = await storage.get_tkg_node_by_name("auth service")
    all_edges = await storage.get_tkg_edges_for_node(auth_node["id"])
    uses_edges = [e for e in all_edges if e["relation_type"] == "uses"]
    active = [e for e in uses_edges if e["expired_at"] is None]
    expired = [e for e in uses_edges if e["expired_at"] is not None]
    assert len(active) >= 1
    assert len(expired) >= 1


# ── Bi-temporal metadata ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bitemporal_fields(storage: Storage):
    """Edges carry both database time (created_at/expired_at) and real-world time (valid_at)."""
    tkg = TemporalKnowledgeGraph(storage)
    edges = await tkg.ingest_fact(
        fact_id="fact-001",
        content="The API runs on Kubernetes",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    assert len(edges) >= 1
    edge = edges[0]
    # Database time
    assert edge.created_at == "2025-01-15T10:00:00+00:00"
    assert edge.expired_at is None
    # Real-world time (defaults to committed_at when not explicitly extracted)
    assert edge.valid_at == "2025-01-15T10:00:00+00:00"
    assert edge.invalid_at is None


# ── Entity timeline ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_timeline(storage: Storage):
    """get_entity_timeline returns chronological edge history."""
    tkg = TemporalKnowledgeGraph(storage)

    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )

    timeline = await tkg.get_entity_timeline("auth service", "uses")
    assert len(timeline) >= 2
    # First entry should be the older one (Redis)
    assert timeline[0]["created_at"] <= timeline[1]["created_at"]
    # First should be expired, second active
    assert timeline[0]["is_active"] is False
    assert timeline[1]["is_active"] is True


# ── Reversal detection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reversal_detection(storage: Storage):
    """Detect A→B→A reversal patterns."""
    tkg = TemporalKnowledgeGraph(storage)

    # Step 1: auth service uses Redis
    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    # Step 2: auth service uses Memcached (invalidates Redis)
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )
    # Step 3: auth service uses Redis again (reversal!)
    await tkg.ingest_fact(
        fact_id="fact-003",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-17T10:00:00+00:00",
    )

    reversals = await tkg.detect_reversals(scope="infra")
    assert len(reversals) >= 1
    rev = reversals[0]
    assert rev["type"] == "reversal"
    assert rev["entity"] == "auth service"
    assert rev["relation"] == "uses"
    assert len(rev["sequence"]) == 3
    # A→B→A: first and third targets should match
    assert rev["sequence"][0]["target"] == rev["sequence"][2]["target"]
    assert rev["sequence"][0]["target"] != rev["sequence"][1]["target"]


@pytest.mark.asyncio
async def test_no_reversal_for_linear_progression(storage: Storage):
    """A→B→C is not a reversal — it's natural progression."""
    tkg = TemporalKnowledgeGraph(storage)

    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )
    await tkg.ingest_fact(
        fact_id="fact-003",
        content="The auth service uses Valkey",
        scope="infra",
        agent_id="agent-c",
        committed_at="2025-01-17T10:00:00+00:00",
    )

    reversals = await tkg.detect_reversals(scope="infra")
    assert len(reversals) == 0


# ── Belief drift detection ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_belief_drift_detection(storage: Storage):
    """Detect when multiple agents assert different values for the same entity."""
    tkg = TemporalKnowledgeGraph(storage)

    # Two agents assert different things about the same entity
    # Using has_value via structured entities
    await tkg.ingest_fact(
        fact_id="fact-001",
        content="Rate limit configuration",
        scope="config",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
        entities=[{"name": "rate_limit", "type": "numeric", "value": 1000}],
    )
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="Rate limit configuration",
        scope="config",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
        entities=[{"name": "rate_limit", "type": "numeric", "value": 2000}],
    )

    drift = await tkg.detect_belief_drift(scope="config")
    assert len(drift) >= 1
    assert drift[0]["type"] == "belief_drift"
    assert drift[0]["entity"] == "rate_limit"


# ── Graph summary ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_summary(storage: Storage):
    """get_graph_summary returns correct counts."""
    tkg = TemporalKnowledgeGraph(storage)

    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )

    summary = await tkg.get_graph_summary()
    assert summary["total_nodes"] >= 3  # auth service, redis, memcached
    assert summary["total_edges"] >= 2
    assert summary["active_edges"] >= 1
    assert summary["expired_edges"] >= 1


# ── Engine integration ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_populates_tkg(engine: EngramEngine, storage: Storage):
    """Committing a fact through the engine populates the TKG."""
    await engine.commit(
        content="The payment service uses Stripe for billing",
        scope="billing",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine._detection_queue.join()

    # TKG should have nodes for "payment service" and "stripe"
    payment_node = await storage.get_tkg_node_by_name("payment service")
    stripe_node = await storage.get_tkg_node_by_name("stripe")
    assert payment_node is not None
    assert stripe_node is not None


@pytest.mark.asyncio
async def test_engine_tkg_reversal_creates_conflict(engine: EngramEngine):
    """A reversal pattern detected by TKG creates a tier3_tkg_reversal conflict."""
    # Step 1: auth service uses Redis
    await engine.commit(
        content="The auth service uses Redis for session caching",
        scope="tkg-reversal",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine._detection_queue.join()

    # Step 2: auth service uses Memcached
    await engine.commit(
        content="The auth service uses Memcached for session caching",
        scope="tkg-reversal",
        confidence=0.9,
        agent_id="agent-b",
    )
    await engine._detection_queue.join()

    # Step 3: auth service uses Redis again (reversal!) — different wording to avoid dedup
    await engine.commit(
        content="We reverted: the auth service uses Redis again for session caching",
        scope="tkg-reversal",
        confidence=0.9,
        agent_id="agent-c",
    )
    await engine._detection_queue.join()

    # Check for TKG reversal conflicts
    conflicts = await engine.get_conflicts(scope="tkg-reversal", status="open")
    tkg_conflicts = [c for c in conflicts if c["detection_tier"] == "tier3_tkg_reversal"]
    assert len(tkg_conflicts) >= 1
    assert "reversal" in tkg_conflicts[0]["explanation"].lower()


@pytest.mark.asyncio
async def test_engine_entity_timeline(engine: EngramEngine):
    """Engine exposes entity timeline from the TKG."""
    await engine.commit(
        content="The API runs on Docker",
        scope="infra",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine._detection_queue.join()

    await engine.commit(
        content="The API runs on Kubernetes",
        scope="infra",
        confidence=0.9,
        agent_id="agent-b",
    )
    await engine._detection_queue.join()

    timeline = await engine.get_entity_timeline("api", "runs_on")
    assert len(timeline) >= 2
    # Chronological order
    assert timeline[0]["created_at"] <= timeline[1]["created_at"]


@pytest.mark.asyncio
async def test_engine_tkg_summary(engine: EngramEngine):
    """Engine exposes TKG graph summary."""
    await engine.commit(
        content="The auth service uses Redis",
        scope="infra",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine._detection_queue.join()

    summary = await engine.get_tkg_summary()
    assert summary["total_nodes"] >= 2
    assert summary["total_edges"] >= 1


# ── Structured entity edges ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_numeric_entities_create_edges(storage: Storage):
    """Structured numeric entities from extract_entities also create TKG edges."""
    tkg = TemporalKnowledgeGraph(storage)
    edges = await tkg.ingest_fact(
        fact_id="fact-001",
        content="Configuration updated",
        scope="config",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
        entities=[{"name": "rate_limit", "type": "numeric", "value": 1000, "unit": "req/s"}],
    )

    has_value_edges = [e for e in edges if e.relation_type == "has_value"]
    assert len(has_value_edges) >= 1
    assert has_value_edges[0].fact_label == "rate_limit = 1000"


# ── Graphiti-inspired features ───────────────────────────────────────


@pytest.mark.asyncio
async def test_edge_dedup_skips_exact_duplicate(storage: Storage):
    """Ingesting the same relationship twice does not create a duplicate edge.

    Aligned with Graphiti's edge dedup: if an active edge with the same
    source+relation+target already exists, the new fact is treated as a
    corroborating episode rather than a new edge.
    """
    tkg = TemporalKnowledgeGraph(storage)

    edges1 = await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )
    assert len(edges1) >= 1

    # Same relationship, different fact
    edges2 = await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Redis for caching",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-16T10:00:00+00:00",
    )
    # Should not create a new edge — the triplet already exists
    uses_edges = [e for e in edges2 if e.relation_type == "uses"]
    assert len(uses_edges) == 0

    # Total edges in graph should still be 1 for this relation
    auth_node = await storage.get_tkg_node_by_name("auth service")
    all_edges = await storage.get_tkg_edges_for_node(auth_node["id"])
    uses_all = [e for e in all_edges if e["relation_type"] == "uses"]
    assert len(uses_all) == 1


@pytest.mark.asyncio
async def test_node_summary_evolves(storage: Storage):
    """Entity node summaries evolve as new edges reference them.

    Aligned with Graphiti's EntityNode.summary field that gets updated
    as new edges are extracted.
    """
    tkg = TemporalKnowledgeGraph(storage)

    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    node = await storage.get_tkg_node_by_name("auth service")
    assert node is not None
    # Summary should contain the fact label
    summary = node.get("summary", "")
    assert "auth service" in summary.lower() or "redis" in summary.lower()


@pytest.mark.asyncio
async def test_temporal_ordering_respects_valid_at(storage: Storage):
    """Temporal contradiction resolution uses valid_at ordering.

    Aligned with Graphiti's resolve_edge_contradictions: when a new edge
    has a later valid_at than an existing conflicting edge, the existing
    edge is expired with invalid_at set to the new edge's valid_at.
    """
    tkg = TemporalKnowledgeGraph(storage)

    # First: auth service uses Redis (valid_at = Jan 15)
    await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    # Second: auth service uses Memcached (valid_at = Jan 20, later)
    await tkg.ingest_fact(
        fact_id="fact-002",
        content="The auth service uses Memcached",
        scope="infra",
        agent_id="agent-b",
        committed_at="2025-01-20T10:00:00+00:00",
    )

    # The Redis edge should be expired because its valid_at is earlier
    auth_node = await storage.get_tkg_node_by_name("auth service")
    all_edges = await storage.get_tkg_edges_for_node(auth_node["id"])
    uses_edges = [e for e in all_edges if e["relation_type"] == "uses"]

    expired = [e for e in uses_edges if e["expired_at"] is not None]
    active = [e for e in uses_edges if e["expired_at"] is None]

    assert len(expired) == 1  # Redis edge expired
    assert len(active) == 1  # Memcached edge active

    # The expired edge's expired_at should be the new edge's valid_at
    assert expired[0]["expired_at"] == "2025-01-20T10:00:00+00:00"


@pytest.mark.asyncio
async def test_edge_carries_episode_ids(storage: Storage):
    """Edges track which facts (episodes) produced them.

    Aligned with Graphiti's EntityEdge.episodes field that tracks
    all episode UUIDs referencing the edge.
    """
    tkg = TemporalKnowledgeGraph(storage)

    edges = await tkg.ingest_fact(
        fact_id="fact-001",
        content="The auth service uses Redis",
        scope="infra",
        agent_id="agent-a",
        committed_at="2025-01-15T10:00:00+00:00",
    )

    assert len(edges) >= 1
    assert edges[0].episode_ids == ["fact-001"]
    assert edges[0].fact_id == "fact-001"
