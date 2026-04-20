"""Tests for the storage layer (SQLiteStorage).

Covers: fact CRUD, dedup, conflict lifecycle, agents, TTL/stale retirement,
workspace stats, timelines, and the new batch helpers.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from engram.storage import Storage


# ── helpers ──────────────────────────────────────────────────────────


def _ts(offset_days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


def _fact(
    *,
    content: str = "Redis latency is 2ms",
    scope: str = "infra",
    confidence: float = 0.9,
    agent_id: str = "agent-1",
    engineer: str = "alice",
    fact_type: str = "observation",
    entities: list | None = None,
    durability: str = "durable",
    ttl_days: int | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    committed_at: str | None = None,
) -> dict:
    now = _ts()
    return {
        "id": uuid.uuid4().hex,
        "lineage_id": uuid.uuid4().hex,
        "content": content,
        "content_hash": uuid.uuid4().hex,
        "scope": scope,
        "confidence": confidence,
        "fact_type": fact_type,
        "agent_id": agent_id,
        "engineer": engineer,
        "provenance": None,
        "keywords": "[]",
        "entities": json.dumps(entities or []),
        "artifact_hash": None,
        "embedding": None,
        "embedding_model": "test",
        "embedding_ver": "1.0",
        "durability": durability,
        "ttl_days": ttl_days,
        "committed_at": committed_at or now,
        "valid_from": valid_from or now,
        "valid_until": valid_until,
    }


def _conflict(
    fact_a_id: str, fact_b_id: str, status: str = "open", tier: str = "tier0_entity"
) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "fact_a_id": fact_a_id,
        "fact_b_id": fact_b_id,
        "detected_at": _ts(),
        "detection_tier": tier,
        "nli_score": None,
        "explanation": "test conflict",
        "severity": "high",
        "status": status,
    }


# ── basic fact CRUD ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_and_retrieve_fact(storage: Storage):
    f = _fact(content="The auth service rate-limits to 1000 req/s", scope="auth")
    await storage.insert_fact(f)

    retrieved = await storage.get_fact_by_id(f["id"])
    assert retrieved is not None
    assert retrieved["content"] == f["content"]
    assert retrieved["scope"] == "auth"


@pytest.mark.asyncio
async def test_dedup_check(storage: Storage):
    f = _fact()
    await storage.insert_fact(f)

    dup = await storage.find_duplicate(f["content_hash"], f["scope"])
    assert dup == f["id"]

    no_dup = await storage.find_duplicate("different_hash", f["scope"])
    assert no_dup is None


@pytest.mark.asyncio
async def test_get_facts_by_ids_batch(storage: Storage):
    f1 = _fact(content="fact one", scope="s1")
    f2 = _fact(content="fact two", scope="s2")
    f3 = _fact(content="fact three", scope="s3")
    for f in (f1, f2, f3):
        await storage.insert_fact(f)

    result = await storage.get_facts_by_ids([f1["id"], f3["id"]])
    assert set(result.keys()) == {f1["id"], f3["id"]}
    assert result[f1["id"]]["content"] == "fact one"
    assert result[f3["id"]]["content"] == "fact three"


@pytest.mark.asyncio
async def test_get_facts_by_ids_empty_list(storage: Storage):
    result = await storage.get_facts_by_ids([])
    assert result == {}


@pytest.mark.asyncio
async def test_get_facts_by_ids_unknown_ids(storage: Storage):
    result = await storage.get_facts_by_ids(["nonexistent-id"])
    assert result == {}


@pytest.mark.asyncio
async def test_count_facts(storage: Storage):
    assert await storage.count_facts() == 0
    await storage.insert_fact(_fact())
    await storage.insert_fact(_fact())
    assert await storage.count_facts() == 2


# ── conflict lifecycle ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_and_query_conflict(storage: Storage):
    f1 = _fact(content="rate limit is 100")
    f2 = _fact(content="rate limit is 200")
    for f in (f1, f2):
        await storage.insert_fact(f)

    c = _conflict(f1["id"], f2["id"])
    await storage.insert_conflict(c)

    open_conflicts = await storage.get_conflicts(status="open")
    assert any(x["id"] == c["id"] for x in open_conflicts)


@pytest.mark.asyncio
async def test_conflict_exists(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    for f in (f1, f2):
        await storage.insert_fact(f)

    assert not await storage.conflict_exists(f1["id"], f2["id"])
    await storage.insert_conflict(_conflict(f1["id"], f2["id"]))
    assert await storage.conflict_exists(f1["id"], f2["id"])
    # Check symmetric lookup
    assert await storage.conflict_exists(f2["id"], f1["id"])


@pytest.mark.asyncio
async def test_duplicate_conflict_pair_is_inserted_once(storage: Storage):
    f1 = _fact(content="rate limit is 100")
    f2 = _fact(content="rate limit is 200")
    for f in (f1, f2):
        await storage.insert_fact(f)

    await storage.insert_conflict(_conflict(f1["id"], f2["id"]))
    await storage.insert_conflict(_conflict(f2["id"], f1["id"]))

    conflicts = await storage.get_conflicts(status="all")
    assert len(conflicts) == 1
    assert await storage.count_conflicts("all") == 1


@pytest.mark.asyncio
async def test_get_conflicting_fact_ids(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    f3 = _fact()
    for f in (f1, f2, f3):
        await storage.insert_fact(f)

    await storage.insert_conflict(_conflict(f1["id"], f2["id"]))
    await storage.insert_conflict(_conflict(f1["id"], f3["id"]))

    result = await storage.get_conflicting_fact_ids(f1["id"])
    assert result == {f2["id"], f3["id"]}

    # f2 is in one conflict (with f1)
    result2 = await storage.get_conflicting_fact_ids(f2["id"])
    assert f1["id"] in result2


@pytest.mark.asyncio
async def test_get_conflicting_fact_ids_no_conflicts(storage: Storage):
    f = _fact()
    await storage.insert_fact(f)
    result = await storage.get_conflicting_fact_ids(f["id"])
    assert result == set()


@pytest.mark.asyncio
async def test_resolve_conflict(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    for f in (f1, f2):
        await storage.insert_fact(f)

    c = _conflict(f1["id"], f2["id"])
    await storage.insert_conflict(c)

    resolved = await storage.resolve_conflict(
        conflict_id=c["id"],
        resolution_type="winner",
        resolution="f1 is correct",
        resolved_by="alice",
    )
    assert resolved is True

    resolved_list = await storage.get_conflicts(status="resolved")
    assert any(x["id"] == c["id"] for x in resolved_list)
    open_list = await storage.get_conflicts(status="open")
    assert not any(x["id"] == c["id"] for x in open_list)


@pytest.mark.asyncio
async def test_auto_resolve_conflict(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    for f in (f1, f2):
        await storage.insert_fact(f)

    c = _conflict(f1["id"], f2["id"])
    await storage.insert_conflict(c)

    ok = await storage.auto_resolve_conflict(
        conflict_id=c["id"],
        resolution_type="winner",
        resolution="auto-escalated",
        resolved_by="system:escalation",
        escalated_at=_ts(),
    )
    assert ok is True
    resolved_list = await storage.get_conflicts(status="resolved")
    assert any(x["id"] == c["id"] for x in resolved_list)


@pytest.mark.asyncio
async def test_count_conflicts(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    f3 = _fact()
    for f in (f1, f2, f3):
        await storage.insert_fact(f)

    await storage.insert_conflict(_conflict(f1["id"], f2["id"]))
    await storage.insert_conflict(_conflict(f1["id"], f3["id"]))

    assert await storage.count_conflicts(status="open") == 2
    assert await storage.count_conflicts(status="resolved") == 0


@pytest.mark.asyncio
async def test_get_open_conflict_fact_ids(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    for f in (f1, f2):
        await storage.insert_fact(f)

    await storage.insert_conflict(_conflict(f1["id"], f2["id"]))
    ids = await storage.get_open_conflict_fact_ids()
    assert f1["id"] in ids
    assert f2["id"] in ids


# ── agent upsert / increment ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_agent_creates_record(storage: Storage):
    await storage.upsert_agent("bot-1", engineer="alice")
    agent = await storage.get_agent("bot-1")
    assert agent is not None
    assert agent["agent_id"] == "bot-1"


@pytest.mark.asyncio
async def test_upsert_agent_idempotent(storage: Storage):
    await storage.upsert_agent("bot-1", engineer="alice")
    await storage.upsert_agent("bot-1", engineer="alice")
    agent = await storage.get_agent("bot-1")
    assert agent is not None  # no duplicate / no error


@pytest.mark.asyncio
async def test_increment_agent_commits(storage: Storage):
    await storage.upsert_agent("bot-1")
    await storage.increment_agent_commits("bot-1")
    await storage.increment_agent_commits("bot-1")
    agent = await storage.get_agent("bot-1")
    assert agent["total_commits"] >= 2


@pytest.mark.asyncio
async def test_increment_agent_flagged(storage: Storage):
    await storage.upsert_agent("bot-1")
    await storage.increment_agent_flagged("bot-1")
    agent = await storage.get_agent("bot-1")
    assert agent["flagged_commits"] >= 1


# ── TTL / stale retirement ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expire_ttl_facts(storage: Storage):
    # A fact whose TTL already expired (committed 10 days ago, ttl_days=1)
    past = _ts(-10)
    expired = _fact(committed_at=past, ttl_days=1, durability="ephemeral")
    expired["valid_from"] = past
    # A fact that is still live (ttl_days=30, also ephemeral but not yet expired)
    live = _fact(ttl_days=30, durability="ephemeral")

    await storage.insert_fact(expired)
    await storage.insert_fact(live)

    retired = await storage.expire_ttl_facts()
    assert retired >= 1

    # expired fact should now have valid_until set
    row = await storage.get_fact_by_id(expired["id"])
    assert row["valid_until"] is not None

    # live fact should still be active
    row2 = await storage.get_fact_by_id(live["id"])
    assert row2["valid_until"] is None


@pytest.mark.asyncio
async def test_retire_stale_facts(storage: Storage):
    # A very old inference with zero corroboration committed 100 days ago
    old_ts = _ts(-100)
    stale = _fact(
        content="old inference",
        fact_type="inference",
        committed_at=old_ts,
    )
    stale["valid_from"] = old_ts

    fresh = _fact(content="fresh fact")

    await storage.insert_fact(stale)
    await storage.insert_fact(fresh)

    retired = await storage.retire_stale_facts()
    assert retired >= 1

    row = await storage.get_fact_by_id(stale["id"])
    assert row["valid_until"] is not None

    row2 = await storage.get_fact_by_id(fresh["id"])
    assert row2["valid_until"] is None


# ── get_expiring_facts ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_expiring_facts(storage: Storage):
    # get_expiring_facts looks for facts where valid_until IS NOT NULL and
    # is within the window.  We pre-set valid_until directly.
    soon = _fact(ttl_days=3, content="expiring soon", valid_until=_ts(+3))  # expires in 3 days
    later = _fact(
        ttl_days=30, content="not expiring soon", valid_until=_ts(+30)
    )  # expires in 30 days
    no_ttl = _fact(content="no ttl fact")

    for f in (soon, later, no_ttl):
        await storage.insert_fact(f)

    expiring = await storage.get_expiring_facts(days_ahead=7)
    ids = [f["id"] for f in expiring]
    assert soon["id"] in ids
    assert later["id"] not in ids
    assert no_ttl["id"] not in ids


# ── get_fact_timeline ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_fact_timeline_returns_facts(storage: Storage):
    for i in range(3):
        await storage.insert_fact(_fact(content=f"timeline fact {i}", scope="audit"))

    timeline = await storage.get_fact_timeline(scope="audit", limit=10)
    assert len(timeline) == 3


@pytest.mark.asyncio
async def test_get_fact_timeline_no_scope_filter(storage: Storage):
    await storage.insert_fact(_fact(scope="alpha"))
    await storage.insert_fact(_fact(scope="beta"))

    timeline = await storage.get_fact_timeline(limit=10)
    assert len(timeline) >= 2


# ── workspace stats ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_workspace_stats_empty(storage: Storage):
    stats = await storage.get_workspace_stats()
    # Should return dict with facts/conflicts/agents keys
    assert "facts" in stats
    assert "conflicts" in stats
    assert "agents" in stats


@pytest.mark.asyncio
async def test_get_workspace_stats_counts(storage: Storage):
    await storage.insert_fact(_fact(content="fact one", scope="infra"))
    await storage.insert_fact(_fact(content="fact two", scope="infra"))
    await storage.insert_fact(_fact(content="fact three", scope="auth"))

    stats = await storage.get_workspace_stats()
    assert stats["facts"]["total"] >= 3
    assert stats["facts"]["current"] >= 3


@pytest.mark.asyncio
async def test_get_workspace_stats_by_scope(storage: Storage):
    await storage.insert_fact(_fact(scope="payments"))
    await storage.insert_fact(_fact(scope="payments"))
    await storage.insert_fact(_fact(scope="auth"))

    stats = await storage.get_workspace_stats()
    by_scope = stats["facts"].get("by_scope", {})
    assert by_scope.get("payments", 0) >= 2
    assert by_scope.get("auth", 0) >= 1


@pytest.mark.asyncio
async def test_get_workspace_stats_conflict_counts(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    for f in (f1, f2):
        await storage.insert_fact(f)

    c = _conflict(f1["id"], f2["id"])
    await storage.insert_conflict(c)

    stats = await storage.get_workspace_stats()
    # stats["conflicts"] has keys: open, resolved, dismissed, total, by_tier
    assert stats["conflicts"]["open"] >= 1
    assert stats["conflicts"]["total"] >= 1


@pytest.mark.asyncio
async def test_get_workspace_stats_most_queried_is_privacy_preserving(storage: Storage):
    f1 = _fact(content="secret implementation detail", scope="auth")
    f2 = _fact(content="another private fact", scope="billing")
    await storage.insert_fact(f1)
    await storage.insert_fact(f2)
    await storage.db.execute("UPDATE facts SET query_hits = ? WHERE id = ?", (5, f1["id"]))
    await storage.db.execute("UPDATE facts SET query_hits = ? WHERE id = ?", (2, f2["id"]))
    await storage.db.commit()

    stats = await storage.get_workspace_stats()
    most_queried = stats["facts"]["most_queried"]

    assert [fact["id"] for fact in most_queried[:2]] == [f1["id"], f2["id"]]
    assert most_queried[0]["query_hits"] == 5
    assert most_queried[0]["scope"] == "auth"
    assert "content" not in most_queried[0]
    assert "engineer" not in most_queried[0]
    assert "provenance" not in most_queried[0]


@pytest.mark.asyncio
async def test_get_workspace_stats_most_active_agents(storage: Storage):
    await storage.upsert_agent("agent-low")
    await storage.upsert_agent("agent-high")
    await storage.increment_agent_commits("agent-low")
    await storage.increment_agent_commits("agent-high")
    await storage.increment_agent_commits("agent-high")
    await storage.increment_agent_flagged("agent-high")

    stats = await storage.get_workspace_stats()
    most_active = stats["agents"]["most_active"]

    assert most_active[0]["agent_id"] == "agent-high"
    assert most_active[0]["total_commits"] == 2
    assert most_active[0]["flagged_commits"] == 1
    assert "last_seen" in most_active[0]


@pytest.mark.asyncio
async def test_get_workspace_stats_conflict_rate_and_over_time(storage: Storage):
    f1 = _fact()
    f2 = _fact()
    f3 = _fact()
    for f in (f1, f2, f3):
        await storage.insert_fact(f)

    open_conflict = _conflict(f1["id"], f2["id"], status="open")
    open_conflict["detected_at"] = "2026-04-01T10:00:00+00:00"
    resolved_conflict = _conflict(f2["id"], f3["id"], status="resolved")
    resolved_conflict["detected_at"] = "2026-04-01T12:00:00+00:00"
    dismissed_conflict = _conflict(f1["id"], f3["id"], status="dismissed")
    dismissed_conflict["detected_at"] = "2026-04-02T09:00:00+00:00"
    for conflict in (open_conflict, resolved_conflict, dismissed_conflict):
        await storage.insert_conflict(conflict)

    stats = await storage.get_workspace_stats()

    assert stats["conflicts"]["rate"] == 1.0
    assert stats["conflicts"]["over_time"] == [
        {"date": "2026-04-01", "open": 1, "resolved": 1, "dismissed": 0, "total": 2},
        {"date": "2026-04-02", "open": 0, "resolved": 0, "dismissed": 1, "total": 1},
    ]


# ── close_validity_window ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_validity_window_by_fact_id(storage: Storage):
    f = _fact()
    await storage.insert_fact(f)

    row = await storage.get_fact_by_id(f["id"])
    assert row["valid_until"] is None

    await storage.close_validity_window(fact_id=f["id"])

    row = await storage.get_fact_by_id(f["id"])
    assert row["valid_until"] is not None


@pytest.mark.asyncio
async def test_close_validity_window_by_lineage(storage: Storage):
    lineage = uuid.uuid4().hex
    f1 = _fact()
    f1["lineage_id"] = lineage
    f2 = _fact()
    f2["lineage_id"] = lineage
    await storage.insert_fact(f1)
    await storage.insert_fact(f2)

    await storage.close_validity_window(lineage_id=lineage)

    row1 = await storage.get_fact_by_id(f1["id"])
    row2 = await storage.get_fact_by_id(f2["id"])
    assert row1["valid_until"] is not None
    assert row2["valid_until"] is not None
