"""Conflict detection and resolution tests.

Validates that contradictory facts are surfaced as conflicts, that
the classification tier is consistent, and that the resolution path
correctly settles disagreements — leaving only the winning fact active.
"""

from __future__ import annotations


import numpy as np
import pytest

from engram.engine import EngramEngine
from engram.storage import Storage


# ── Direct contradiction ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_direct_numeric_contradiction_raises_conflict(engine: EngramEngine):
    """Two facts with contradictory numeric values in the same scope produce a conflict."""
    await engine.commit(
        content="The auth service rate limit is 1000 req/s per IP",
        scope="conflicts",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine.commit(
        content="The auth service rate limit is 2000 req/s per IP",
        scope="conflicts",
        confidence=0.9,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts", status="open")
    assert len(conflicts) >= 1
    assert any(c["detection_tier"] in ("tier0_entity", "tier2_numeric") for c in conflicts)


# ── Same entity, different value ─────────────────────────────────────


@pytest.mark.asyncio
async def test_same_entity_different_value_produces_conflict(engine: EngramEngine):
    """Two facts naming the same config entity with different values are flagged as conflicting."""
    await engine.commit(
        content="Max database connections is 50 connections",
        scope="conflicts",
        confidence=0.85,
        agent_id="agent-a",
    )
    await engine.commit(
        content="Max database connections is 200 connections",
        scope="conflicts",
        confidence=0.85,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts", status="open")
    assert len(conflicts) >= 1
    # Entity extraction may produce tier0/tier2 or NLI may catch it via tier1
    tiers = {c["detection_tier"] for c in conflicts}
    assert tiers & {"tier0_entity", "tier2_numeric", "tier1_nli"}


@pytest.mark.asyncio
async def test_conflict_classification_is_high_severity_for_cross_agent(engine: EngramEngine):
    """Cross-agent numeric conflicts are classified as high severity."""
    await engine.commit(
        content="Session token TTL is 3600 seconds",
        scope="conflicts-severity",
        confidence=0.9,
        agent_id="agent-x",
        engineer="alice",
    )
    await engine.commit(
        content="Session token TTL is 7200 seconds",
        scope="conflicts-severity",
        confidence=0.9,
        agent_id="agent-y",
        engineer="bob",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts-severity", status="open")
    assert len(conflicts) >= 1
    # Cross-engineer numeric conflict must be high severity
    assert any(c["severity"] == "high" for c in conflicts)


# ── Resolution path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_winner_resolution_closes_losing_fact(engine: EngramEngine, storage: Storage):
    """Resolving a conflict with 'winner' retires the losing fact."""
    r1 = await engine.commit(
        content="Cache TTL is 300 seconds",
        scope="conflicts-resolve",
        confidence=0.9,
        agent_id="agent-a",
    )
    r2 = await engine.commit(
        content="Cache TTL is 600 seconds",
        scope="conflicts-resolve",
        confidence=0.9,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts-resolve", status="open")
    assert len(conflicts) >= 1

    conflict = conflicts[0]
    conflict_id = conflict["conflict_id"]
    winning_id = r1["fact_id"]
    losing_id = r2["fact_id"] if conflict["fact_a"]["fact_id"] == r1["fact_id"] else r1["fact_id"]
    # Determine which fact is actually the loser based on conflict structure
    if conflict["fact_a"]["fact_id"] == winning_id:
        losing_id = conflict["fact_b"]["fact_id"]
    else:
        losing_id = conflict["fact_a"]["fact_id"]
        winning_id = r1["fact_id"]

    result = await engine.resolve(
        conflict_id=conflict_id,
        resolution_type="winner",
        resolution="Confirmed: cache TTL is 300 seconds per ops runbook",
        winning_claim_id=winning_id,
    )

    assert result["resolved"] is True

    # Conflict is now resolved
    resolved = await engine.get_conflicts(scope="conflicts-resolve", status="resolved")
    assert any(c["conflict_id"] == conflict_id for c in resolved)

    # Losing fact is closed (valid_until is set)
    loser = await storage.get_fact_by_id(losing_id)
    assert loser["valid_until"] is not None

    # Winning fact remains active
    winner = await storage.get_fact_by_id(winning_id)
    assert winner["valid_until"] is None


@pytest.mark.asyncio
async def test_dismissed_resolution_leaves_both_facts_active(
    engine: EngramEngine, storage: Storage
):
    """Dismissing a conflict records a false-positive and leaves both facts active."""
    r1 = await engine.commit(
        content="Deployment target is us-east-1",
        scope="conflicts-dismiss",
        confidence=0.9,
        agent_id="agent-a",
    )
    r2 = await engine.commit(
        content="Deployment target is eu-west-1",
        scope="conflicts-dismiss",
        confidence=0.9,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts-dismiss", status="open")
    # These may or may not produce a conflict depending on entity extraction;
    # only proceed if one was detected
    if not conflicts:
        pytest.skip("No conflict detected for this fact pair — entity extraction may differ")

    conflict_id = conflicts[0]["conflict_id"]

    await engine.resolve(
        conflict_id=conflict_id,
        resolution_type="dismissed",
        resolution="Different regions serve different customer segments — not a contradiction",
    )

    # Both facts remain valid
    f1 = await storage.get_fact_by_id(r1["fact_id"])
    f2 = await storage.get_fact_by_id(r2["fact_id"])
    assert f1["valid_until"] is None
    assert f2["valid_until"] is None


@pytest.mark.asyncio
async def test_dismissed_conflict_stays_hidden_after_refresh(
    engine: EngramEngine, storage: Storage, monkeypatch
):
    """Dismissed conflicts should stay hidden even if refresh/detection rechecks the same pair."""
    monkeypatch.setattr(
        "engram.embeddings.encode",
        lambda text: np.array([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("engram.embeddings.get_model_version", lambda: "test-version")

    r1 = await engine.commit(
        content="The auth service rate limit is 1000 req/s per IP",
        scope="conflicts-refresh",
        confidence=0.9,
        agent_id="agent-a",
    )
    r2 = await engine.commit(
        content="The auth service rate limit is 2000 req/s per IP",
        scope="conflicts-refresh",
        confidence=0.9,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts-refresh", status="open")
    assert len(conflicts) == 1

    conflict_id = conflicts[0]["conflict_id"]
    await engine.resolve(
        conflict_id=conflict_id,
        resolution_type="dismissed",
        resolution="Dismissed as a dashboard false positive",
    )

    # Simulate a dashboard refresh/background pass trying to surface the same pair again.
    await storage.insert_conflict(
        {
            "id": "replacement-conflict-id",
            "fact_a_id": r1["fact_id"],
            "fact_b_id": r2["fact_id"],
            "detected_at": conflicts[0]["detected_at"],
            "detection_tier": "tier2_numeric",
            "nli_score": None,
            "explanation": "retry insert after dismiss",
            "severity": "high",
            "status": "open",
            "conflict_type": "genuine",
        }
    )

    refreshed = await engine.get_conflicts(scope="conflicts-refresh", status="all")
    assert refreshed == []


# ── conflict_type classification ─────────────────────────────────────


@pytest.mark.asyncio
async def test_same_agent_conflict_classified_as_evolution(engine: EngramEngine):
    """When the same agent commits contradictory facts the conflict is classified as evolution
    and auto-resolved — it should not appear in the open conflict list."""
    await engine.commit(
        content="Worker pool size is 4 threads",
        scope="conflicts-type",
        confidence=0.9,
        agent_id="agent-self-correct",
    )
    await engine.commit(
        content="Worker pool size is 8 threads",
        scope="conflicts-type",
        confidence=0.9,
        agent_id="agent-self-correct",
    )

    await engine._detection_queue.join()

    # Evolution conflicts are auto-resolved and must not appear as open
    open_conflicts = await engine.get_conflicts(scope="conflicts-type", status="open")
    assert len(open_conflicts) == 0

    # They are visible in the resolved view
    resolved = await engine.get_conflicts(scope="conflicts-type", status="resolved")
    assert len(resolved) >= 1
    assert all(c["conflict_type"] == "evolution" for c in resolved)
    assert all(c["auto_resolved"] is True for c in resolved)


@pytest.mark.asyncio
async def test_evolution_auto_resolve_keeps_newer_fact(engine: EngramEngine, storage: Storage):
    """Auto-resolution of an evolution conflict retires the older fact and keeps the newer one."""
    r1 = await engine.commit(
        content="Cache TTL is 60 seconds",
        scope="conflicts-autoevolve",
        confidence=0.9,
        agent_id="agent-updater",
    )
    r2 = await engine.commit(
        content="Cache TTL is 300 seconds",
        scope="conflicts-autoevolve",
        confidence=0.9,
        agent_id="agent-updater",
    )

    await engine._detection_queue.join()

    # Older fact (r1) must be retired
    old_fact = await storage.get_fact_by_id(r1["fact_id"])
    new_fact = await storage.get_fact_by_id(r2["fact_id"])
    assert old_fact["valid_until"] is not None, "Older fact must be retired"
    assert new_fact["valid_until"] is None, "Newer fact must remain active"


@pytest.mark.asyncio
async def test_cross_agent_conflict_classified_as_genuine(engine: EngramEngine):
    """Cross-agent contradictions are classified as genuine conflicts."""
    await engine.commit(
        content="Queue retry limit is 3 attempts",
        scope="conflicts-genuine",
        confidence=0.9,
        agent_id="agent-alpha",
    )
    await engine.commit(
        content="Queue retry limit is 10 attempts",
        scope="conflicts-genuine",
        confidence=0.9,
        agent_id="agent-beta",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts-genuine", status="open")
    assert len(conflicts) >= 1
    assert any(c["conflict_type"] == "genuine" for c in conflicts)


@pytest.mark.asyncio
async def test_conflict_detected_webhook_fires(engine: EngramEngine):
    """A conflict.detected event is queued as a webhook delivery when a conflict is found."""
    fired: list[dict] = []

    async def _capture(event: str, payload: dict) -> None:  # type: ignore[override]
        if event == "conflict.detected":
            fired.append(payload)

    original = engine._fire_event
    engine._fire_event = _capture  # type: ignore[assignment]

    try:
        await engine.commit(
            content="Timeout is 30 seconds",
            scope="conflicts-webhook",
            confidence=0.9,
            agent_id="agent-p",
        )
        await engine.commit(
            content="Timeout is 60 seconds",
            scope="conflicts-webhook",
            confidence=0.9,
            agent_id="agent-q",
        )
        await engine._detection_queue.join()
    finally:
        engine._fire_event = original  # type: ignore[assignment]

    assert len(fired) >= 1
    assert all("conflict_id" in e for e in fired)
    assert all("conflict_type" in e for e in fired)


@pytest.mark.asyncio
async def test_workspace_stats_includes_conflict_by_type(engine: EngramEngine):
    """get_workspace_stats returns a by_type breakdown of conflicts."""
    await engine.commit(
        content="Max retries is 3",
        scope="conflicts-stats",
        confidence=0.9,
        agent_id="agent-stats-a",
    )
    await engine.commit(
        content="Max retries is 5",
        scope="conflicts-stats",
        confidence=0.9,
        agent_id="agent-stats-b",
    )

    await engine._detection_queue.join()

    stats = await engine.storage.get_workspace_stats()
    assert "by_type" in stats["conflicts"]
    # At least one conflict should be present in the by_type breakdown
    by_type = stats["conflicts"]["by_type"]
    assert sum(by_type.values()) >= 1
