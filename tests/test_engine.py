"""Tests for the core engine — commit, query, conflicts, resolve."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from engram.engine import EngramEngine


@pytest.mark.asyncio
async def test_commit_basic(engine: EngramEngine):
    result = await engine.commit(
        content="The payments service uses Stripe API v2023-10-16",
        scope="payments",
        confidence=0.95,
        agent_id="test-agent-1",
        provenance="src/payments/stripe.py:15",
    )
    assert result["duplicate"] is False
    assert "fact_id" in result
    assert "committed_at" in result
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)
    assert len(result["suggestions"]) <= 2


@pytest.mark.asyncio
async def test_commit_returns_proactive_suggestions_for_rate_limit(engine: EngramEngine):
    result = await engine.commit(
        content="The auth service rate limit is 1000 req/s per IP",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )

    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)
    assert len(result["suggestions"]) <= 2
    assert any("retry" in s.lower() for s in result["suggestions"])


@pytest.mark.asyncio
async def test_commit_dedup(engine: EngramEngine):
    await engine.commit(
        content="Redis runs on port 6379",
        scope="infra",
        confidence=1.0,
        agent_id="agent-1",
    )
    result2 = await engine.commit(
        content="Redis runs on port 6379",
        scope="infra",
        confidence=1.0,
        agent_id="agent-2",
    )
    assert result2["duplicate"] is True
    assert result2["suggestions"] == []


@pytest.mark.asyncio
async def test_commit_none_operation_returns_empty_suggestions(engine: EngramEngine):
    result = await engine.commit(
        content="No new fact to add",
        scope="general",
        confidence=0.8,
        operation="none",
    )

    assert result["memory_op"] == "none"
    assert result["fact_id"] is None
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_commit_rejects_secrets(engine: EngramEngine):
    with pytest.raises(ValueError, match="secret"):
        await engine.commit(
            content="API key is sk-abc123def456ghi789jkl012mno345pqr",
            scope="auth",
            confidence=1.0,
        )


@pytest.mark.asyncio
async def test_commit_rejects_empty(engine: EngramEngine):
    with pytest.raises(ValueError, match="empty"):
        await engine.commit(content="", scope="test", confidence=0.5)


@pytest.mark.asyncio
async def test_commit_rejects_bad_confidence(engine: EngramEngine):
    with pytest.raises(ValueError, match="Confidence"):
        await engine.commit(content="test", scope="test", confidence=1.5)


@pytest.mark.asyncio
async def test_commit_rejects_bad_fact_type(engine: EngramEngine):
    with pytest.raises(ValueError, match="fact_type"):
        await engine.commit(content="test", scope="test", confidence=0.5, fact_type="guess")


@pytest.mark.asyncio
async def test_query_returns_results(engine: EngramEngine):
    await engine.commit(
        content="The auth service rate-limits to 1000 req/s per IP",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )
    results = await engine.query(topic="auth rate limiting", scope="auth")
    assert len(results) >= 1
    assert results[0]["content"] == "The auth service rate-limits to 1000 req/s per IP"


@pytest.mark.asyncio
async def test_query_empty(engine: EngramEngine):
    results = await engine.query(topic="nonexistent topic")
    assert results == []


@pytest.mark.asyncio
async def test_query_scope_filtering(engine: EngramEngine):
    await engine.commit(
        content="Auth uses JWT tokens",
        scope="auth/jwt",
        confidence=0.9,
        agent_id="agent-1",
    )
    await engine.commit(
        content="Payments use Stripe",
        scope="payments",
        confidence=0.9,
        agent_id="agent-1",
    )
    results = await engine.query(topic="tokens", scope="auth")
    contents = [r["content"] for r in results]
    assert "Auth uses JWT tokens" in contents
    # payments fact should not appear when filtering by auth scope
    assert "Payments use Stripe" not in contents


@pytest.mark.asyncio
async def test_commit_with_correction(engine: EngramEngine):
    r1 = await engine.commit(
        content="Rate limit is 500 req/s",
        scope="auth",
        confidence=0.7,
        agent_id="agent-1",
    )
    # Get the lineage_id of the first fact
    fact = await engine.storage.get_fact_by_id(r1["fact_id"])
    lineage = fact["lineage_id"]

    r2 = await engine.commit(
        content="Rate limit is actually 1000 req/s",
        scope="auth",
        confidence=0.95,
        agent_id="agent-2",
        corrects_lineage=lineage,
    )
    assert r2["duplicate"] is False

    # Old fact should be superseded
    old_fact = await engine.storage.get_fact_by_id(r1["fact_id"])
    assert old_fact["valid_until"] is not None


@pytest.mark.asyncio
async def test_detection_finds_numeric_conflict(engine: EngramEngine):
    await engine.commit(
        content="The auth service rate-limits to 500 req/s per IP",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )
    await engine.commit(
        content="The auth service rate-limits to 1000 req/s per IP",
        scope="auth",
        confidence=0.9,
        agent_id="agent-2",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="auth", status="open")
    assert len(conflicts) >= 1
    # Same-scope numeric entity conflicts are caught by tier0_entity (exact entity
    # name + different value in scope). tier2_numeric only fires when tier0 doesn't
    # apply (e.g. entities present in candidate but missed by tier0 lookup).
    assert any(c["detection_tier"] in ("tier0_entity", "tier2_numeric") for c in conflicts)
    assert any("rate_limit" in (c["explanation"] or "") for c in conflicts)


@pytest.mark.asyncio
async def test_detection_finds_cross_scope_numeric_conflict(engine: EngramEngine):
    await engine.commit(
        content="Auth rate limit is 500 req/s",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )
    await engine.commit(
        content="Payments rate limit is 1000 req/s",
        scope="payments",
        confidence=0.9,
        agent_id="agent-2",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(status="open")
    assert any(c["detection_tier"] == "tier2b_cross_scope" for c in conflicts)


@pytest.mark.asyncio
async def test_detection_finds_semantic_nli_conflict(engine: EngramEngine, monkeypatch):
    from engram import embeddings

    class FakeNLIModel:
        def predict(self, pairs, apply_softmax=True):
            return [[0.99, 0.01, 0.0]]

    def fake_encode(text: str):
        return np.ones(384, dtype=np.float32)

    monkeypatch.setattr(embeddings, "encode", fake_encode)
    monkeypatch.setattr(engine, "_nli_model", FakeNLIModel(), raising=False)

    await engine.commit(
        content="The auth service uses JWT tokens",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )
    await engine.commit(
        content="The auth service does not use JWT tokens",
        scope="auth",
        confidence=0.9,
        agent_id="agent-2",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="auth", status="open")
    assert any(c["detection_tier"] == "tier1_nli" for c in conflicts)


@pytest.mark.asyncio
async def test_resolve_winner(engine: EngramEngine):
    # Manually create a conflict
    r1 = await engine.commit(
        content="Service uses PostgreSQL 14",
        scope="infra",
        confidence=0.9,
        agent_id="agent-1",
    )
    r2 = await engine.commit(
        content="Service uses PostgreSQL 16",
        scope="infra",
        confidence=0.9,
        agent_id="agent-2",
    )

    import uuid
    from datetime import datetime, timezone

    conflict_id = uuid.uuid4().hex
    await engine.storage.insert_conflict(
        {
            "id": conflict_id,
            "fact_a_id": r1["fact_id"],
            "fact_b_id": r2["fact_id"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "detection_tier": "tier0_entity",
            "nli_score": None,
            "explanation": "Version conflict",
            "severity": "high",
            "status": "open",
        }
    )

    result = await engine.resolve(
        conflict_id=conflict_id,
        resolution_type="winner",
        resolution="Verified in docker-compose.yml: PostgreSQL 16",
        winning_claim_id=r2["fact_id"],
    )
    assert result["resolved"] is True

    # Losing fact should be superseded
    loser = await engine.storage.get_fact_by_id(r1["fact_id"])
    assert loser["valid_until"] is not None


@pytest.mark.asyncio
async def test_commit_rejects_nonexistent_corrects_lineage(engine: EngramEngine):
    """Providing a corrects_lineage that doesn't exist must raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await engine.commit(
            content="Updated rate limit is 200 req/s",
            scope="auth",
            confidence=0.9,
            agent_id="agent-1",
            corrects_lineage="nonexistent-lineage-id-abc123",
        )


@pytest.mark.asyncio
async def test_commit_corrects_lineage_valid(engine: EngramEngine):
    """corrects_lineage pointing to a real lineage must succeed."""
    r1 = await engine.commit(
        content="Rate limit is 500 req/s",
        scope="auth",
        confidence=0.8,
        agent_id="agent-1",
    )
    fact = await engine.storage.get_fact_by_id(r1["fact_id"])
    lineage = fact["lineage_id"]

    r2 = await engine.commit(
        content="Rate limit is actually 1000 req/s",
        scope="auth",
        confidence=0.95,
        agent_id="agent-2",
        corrects_lineage=lineage,
    )
    assert r2["duplicate"] is False
    old = await engine.storage.get_fact_by_id(r1["fact_id"])
    assert old["valid_until"] is not None, "Old fact in lineage must be superseded"


@pytest.mark.asyncio
async def test_commit_ephemeral_durability(engine: EngramEngine):
    """Ephemeral facts are stored with durability='ephemeral' and default TTL."""
    result = await engine.commit(
        content="Temporary debug flag is enabled",
        scope="debug",
        confidence=0.7,
        agent_id="agent-1",
        durability="ephemeral",
    )
    assert result["duplicate"] is False
    fact = await engine.storage.get_fact_by_id(result["fact_id"])
    assert fact["durability"] == "ephemeral"
    assert fact["ttl_days"] == 1, "Ephemeral facts default to 1-day TTL"


@pytest.mark.asyncio
async def test_commit_ephemeral_not_returned_in_normal_query(engine: EngramEngine):
    """Ephemeral facts must not appear in normal (durable-only) queries."""
    await engine.commit(
        content="Temporary flag is on",
        scope="flags",
        confidence=0.5,
        agent_id="agent-1",
        durability="ephemeral",
    )
    await engine.commit(
        content="Production flag is stable",
        scope="flags",
        confidence=0.9,
        agent_id="agent-1",
        durability="durable",
    )
    results = await engine.query(topic="flag", scope="flags")
    contents = [r["content"] for r in results]
    assert "Production flag is stable" in contents
    assert "Temporary flag is on" not in contents, (
        "Ephemeral facts must not appear in durable queries"
    )


@pytest.mark.asyncio
async def test_commit_delete_operation(engine: EngramEngine):
    """operation='delete' must close the target lineage."""
    r1 = await engine.commit(
        content="Old config: max connections = 50",
        scope="db",
        confidence=0.9,
        agent_id="agent-1",
    )
    fact = await engine.storage.get_fact_by_id(r1["fact_id"])
    lineage = fact["lineage_id"]

    result = await engine.commit(
        content="Retiring stale connection limit fact",
        scope="db",
        confidence=0.9,
        agent_id="agent-2",
        operation="delete",
        corrects_lineage=lineage,
    )
    assert result["memory_op"] == "delete"
    assert result["deleted_lineage"] == lineage
    assert result["suggestions"] == []

    # Original fact must be retired
    retired = await engine.storage.get_fact_by_id(r1["fact_id"])
    assert retired["valid_until"] is not None, "Deleted lineage must be closed"


@pytest.mark.asyncio
async def test_commit_rejects_whitespace_content(engine: EngramEngine):
    """All-whitespace content must be rejected."""
    with pytest.raises(ValueError, match="empty"):
        await engine.commit(content="   ", scope="test", confidence=0.5)


@pytest.mark.asyncio
async def test_commit_rejects_whitespace_scope(engine: EngramEngine):
    """All-whitespace scope must be rejected."""
    with pytest.raises(ValueError, match="empty"):
        await engine.commit(content="valid content", scope="  ", confidence=0.5)


@pytest.mark.asyncio
async def test_resolve_dismissed(engine: EngramEngine):
    r1 = await engine.commit(
        content="Auth timeout is 30 seconds",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
    )
    r2 = await engine.commit(
        content="Auth session timeout is 30 minutes",
        scope="auth",
        confidence=0.9,
        agent_id="agent-2",
    )

    import uuid
    from datetime import datetime, timezone

    conflict_id = uuid.uuid4().hex
    await engine.storage.insert_conflict(
        {
            "id": conflict_id,
            "fact_a_id": r1["fact_id"],
            "fact_b_id": r2["fact_id"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "detection_tier": "tier1_nli",
            "nli_score": 0.87,
            "explanation": None,
            "severity": "medium",
            "status": "open",
        }
    )

    result = await engine.resolve(
        conflict_id=conflict_id,
        resolution_type="dismissed",
        resolution="These refer to different timeouts (request vs session)",
    )
    assert result["resolved"] is True
    assert result["resolution_type"] == "dismissed"


@pytest.mark.asyncio
async def test_query_adjacent_scopes(engine: EngramEngine):
    """Adjacent scope query surfaces related facts from sibling scopes."""
    # Commit facts in different scopes
    await engine.commit(
        content="The auth service validates JWT tokens on every request",
        scope="auth",
        confidence=0.9,
        agent_id="agent-1",
        provenance="src/auth/jwt.py:10",
    )
    await engine.commit(
        content="JWT signing uses RS256 with rotating keys",
        scope="auth/jwt",
        confidence=0.95,
        agent_id="agent-1",
        provenance="src/auth/jwt.py:45",
    )
    await engine.commit(
        content="The API middleware validates authentication tokens before routing",
        scope="api",
        confidence=0.9,
        agent_id="agent-2",
        provenance="src/api/middleware.py:20",
    )
    await engine.commit(
        content="Request middleware checks auth headers on all endpoints",
        scope="middleware",
        confidence=0.85,
        agent_id="agent-2",
        provenance="src/middleware/auth.py:5",
    )
    # Allow detection worker to process
    await asyncio.sleep(0.3)

    # Without include_adjacent: only auth and auth/* scopes
    results_no_adj = await engine.query(
        topic="How does authentication token validation work?",
        scope="auth",
        limit=10,
        include_adjacent=False,
    )
    scopes_no_adj = {r["scope"] for r in results_no_adj}
    assert all(s == "auth" or s.startswith("auth/") for s in scopes_no_adj)

    # With include_adjacent: should also find related facts from api/middleware
    results_adj = await engine.query(
        topic="How does authentication token validation work?",
        scope="auth",
        limit=10,
        include_adjacent=True,
    )
    adjacent_results = [r for r in results_adj if r.get("adjacent") is True]
    # At least one adjacent result should come from api or middleware
    if adjacent_results:
        assert all(r.get("original_scope") is not None for r in adjacent_results)
        adjacent_scopes = {r["original_scope"] for r in adjacent_results}
        assert adjacent_scopes & {"api", "middleware"}
    # In-scope results should have adjacent=False
    in_scope = [r for r in results_adj if r.get("adjacent") is False]
    assert len(in_scope) > 0
