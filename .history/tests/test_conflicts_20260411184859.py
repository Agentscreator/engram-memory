"""Conflict detection and resolution tests.

Validates that contradictory facts are surfaced as conflicts, that
the classification tier is consistent, and that the resolution path
correctly settles disagreements — leaving only the winning fact active.
"""

from __future__ import annotations

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
        content="Max database connections is set to 50",
        scope="conflicts",
        confidence=0.85,
        agent_id="agent-a",
    )
    await engine.commit(
        content="Max database connections is set to 200",
        scope="conflicts",
        confidence=0.85,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()

    conflicts = await engine.get_conflicts(scope="conflicts", status="open")
    assert len(conflicts) >= 1
    tiers = {c["detection_tier"] for c in conflicts}
    # Both tier0_entity and tier2_numeric are valid for this case
    assert tiers & {"tier0_entity", "tier2_numeric"}


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
async def test_dismissed_resolution_leaves_both_facts_active(engine: EngramEngine, storage: Storage):
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
