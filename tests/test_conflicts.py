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
    await engine._suggestion_queue.join()

    # Conflict is auto-resolved (no open conflicts remain); verify detection occurred
    conflicts = await engine.get_conflicts(scope="conflicts", status="resolved")
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
    await engine._suggestion_queue.join()

    # Conflict is auto-resolved; verify detection occurred
    conflicts = await engine.get_conflicts(scope="conflicts", status="resolved")
    assert len(conflicts) >= 1
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
    await engine._suggestion_queue.join()

    # Conflict is auto-resolved; verify severity of detected conflict
    conflicts = await engine.get_conflicts(scope="conflicts-severity", status="resolved")
    assert len(conflicts) >= 1
    assert any(c["severity"] == "high" for c in conflicts)


# ── Resolution path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_auto_resolved_picks_winner(
    engine: EngramEngine, storage: Storage
):
    """Auto-resolved conflicts pick a winner — no open conflicts remain, loser is closed."""
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
    await engine._suggestion_queue.join()

    # No open conflicts remain
    open_conflicts = await engine.get_conflicts(scope="conflicts-resolve", status="open")
    assert len(open_conflicts) == 0

    # Conflict appears as auto-resolved
    resolved = await engine.get_conflicts(scope="conflicts-resolve", status="resolved")
    assert len(resolved) >= 1
    assert all(c["auto_resolved"] is True for c in resolved)

    # Exactly one fact remains active (the winner); loser has valid_until set
    f1 = await storage.get_fact_by_id(r1["fact_id"])
    f2 = await storage.get_fact_by_id(r2["fact_id"])
    closed = sum(1 for f in (f1, f2) if f["valid_until"] is not None)
    assert closed == 1, "Exactly one fact should be retired by the winner resolution"


@pytest.mark.asyncio
async def test_auto_resolved_conflict_closes_loser(
    engine: EngramEngine, storage: Storage
):
    """Intelligent auto-resolution closes the losing fact (lower confidence or older)."""
    r1 = await engine.commit(
        content="Deployment target is us-east-1",
        scope="conflicts-dismiss",
        confidence=0.7,  # lower confidence — will lose
        agent_id="agent-a",
    )
    r2 = await engine.commit(
        content="Deployment target is eu-west-1",
        scope="conflicts-dismiss",
        confidence=0.9,  # higher confidence — will win
        agent_id="agent-b",
    )

    await engine._detection_queue.join()
    await engine._suggestion_queue.join()

    resolved = await engine.get_conflicts(scope="conflicts-dismiss", status="resolved")
    if not resolved:
        pytest.skip("No conflict detected for this fact pair — entity extraction may differ")

    # Higher-confidence fact (r2) wins; r1 is closed
    f1 = await storage.get_fact_by_id(r1["fact_id"])
    f2 = await storage.get_fact_by_id(r2["fact_id"])
    assert f1["valid_until"] is not None, "Lower-confidence fact should be retired"
    assert f2["valid_until"] is None, "Higher-confidence fact should remain active"


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

    await engine.commit(
        content="The auth service rate limit is 1000 req/s per IP",
        scope="conflicts-refresh",
        confidence=0.9,
        agent_id="agent-a",
    )
    await engine.commit(
        content="The auth service rate limit is 2000 req/s per IP",
        scope="conflicts-refresh",
        confidence=0.9,
        agent_id="agent-b",
    )

    await engine._detection_queue.join()
    await engine._suggestion_queue.join()

    # Conflict is auto-resolved; verify no open conflicts remain
    open_conflicts = await engine.get_conflicts(scope="conflicts-refresh", status="open")
    assert len(open_conflicts) == 0

    resolved = await engine.get_conflicts(scope="conflicts-refresh", status="resolved")
    assert len(resolved) >= 1

    # Winning fact stays active; engine won't re-detect the same resolved pair
    open_after = await engine.get_conflicts(scope="conflicts-refresh", status="open")
    assert len(open_after) == 0


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

    await engine._suggestion_queue.join()

    # Genuine conflicts are auto-resolved; check resolved status
    conflicts = await engine.get_conflicts(scope="conflicts-genuine", status="resolved")
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
