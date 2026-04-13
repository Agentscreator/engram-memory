"""Tests for workspace isolation in SQLiteStorage.

Verifies that every mutating and querying method in SQLiteStorage is scoped
to self.workspace_id, preventing cross-workspace data leaks in multi-tenant
SQLite setups (e.g. a single shared ~/.engram/knowledge.db used by multiple
engram_id workspaces).

Each test uses two storage instances (ws_alpha / ws_beta) that share the
same on-disk SQLite file but have different workspace_id values.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from engram.storage import SQLiteStorage


# ── helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_fact(
    scope: str = "auth",
    workspace_id: str = "alpha",
    entities: list | None = None,
    fact_type: str = "observation",
    ttl_days: int | None = None,
    durability: str = "durable",
    committed_at: str | None = None,
    content: str | None = None,
) -> dict:
    """Build a minimal valid fact dict for direct insertion."""
    now = committed_at or _now_iso()
    return {
        "id": uuid.uuid4().hex,
        "lineage_id": uuid.uuid4().hex,
        "content": content or f"test fact {uuid.uuid4().hex[:8]}",
        "content_hash": uuid.uuid4().hex,
        "scope": scope,
        "confidence": 0.9,
        "fact_type": fact_type,
        "agent_id": "agent-test",
        "engineer": None,
        "provenance": None,
        "keywords": "[]",
        "entities": json.dumps(entities or []),
        "artifact_hash": None,
        "embedding": None,
        "embedding_model": "test",
        "embedding_ver": "1.0",
        "committed_at": now,
        "valid_from": now,
        "valid_until": None,
        "ttl_days": ttl_days,
        "memory_op": "add",
        "supersedes_fact_id": None,
        "workspace_id": workspace_id,
        "durability": durability,
    }


def _make_conflict(fact_a_id: str, fact_b_id: str, workspace_id: str = "alpha") -> dict:
    """Build a minimal conflict dict for direct insertion."""
    return {
        "id": uuid.uuid4().hex,
        "fact_a_id": fact_a_id,
        "fact_b_id": fact_b_id,
        "detected_at": _now_iso(),
        "detection_tier": "tier0",
        "nli_score": None,
        "explanation": "test conflict",
        "severity": "medium",
        "status": "open",
        "workspace_id": workspace_id,
    }


# ── fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ws_alpha(tmp_path: Path):
    """Storage instance for workspace 'alpha'."""
    s = SQLiteStorage(db_path=tmp_path / "shared.db", workspace_id="alpha")
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def ws_beta(tmp_path: Path):
    """Storage instance for workspace 'beta', sharing the same database file."""
    s = SQLiteStorage(db_path=tmp_path / "shared.db", workspace_id="beta")
    await s.connect()
    yield s
    await s.close()


# ── find_duplicate ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_duplicate_does_not_cross_workspaces(ws_alpha, ws_beta):
    """A duplicate check in beta must not match alpha's fact with the same content hash."""
    fact = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact)

    # Same content_hash + scope, but looked up from beta
    result = await ws_beta.find_duplicate(fact["content_hash"], fact["scope"])
    assert result is None, "find_duplicate must not match facts from another workspace"


@pytest.mark.asyncio
async def test_find_duplicate_within_same_workspace(ws_alpha):
    """Duplicate detection must still work within the same workspace."""
    fact = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact)

    result = await ws_alpha.find_duplicate(fact["content_hash"], fact["scope"])
    assert result == fact["id"], "find_duplicate must find the existing fact in the same workspace"


# ── close_validity_window ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_validity_window_by_lineage_does_not_cross_workspaces(ws_alpha, ws_beta):
    """Closing a lineage in beta must not affect alpha's fact with the same lineage_id."""
    lineage_id = uuid.uuid4().hex
    fact_a = _make_fact(workspace_id="alpha")
    fact_a["lineage_id"] = lineage_id
    await ws_alpha.insert_fact(fact_a)

    # beta closes the same lineage_id (simulates UUID collision or shared lineage)
    fact_b = _make_fact(workspace_id="beta")
    fact_b["lineage_id"] = lineage_id
    await ws_beta.insert_fact(fact_b)

    await ws_beta.close_validity_window(lineage_id=lineage_id)

    # Alpha's fact must still be open
    alpha_fact = await ws_alpha.get_fact_by_id(fact_a["id"])
    assert alpha_fact["valid_until"] is None, (
        "close_validity_window(lineage) must not retire facts in other workspaces"
    )

    # Beta's fact must be closed
    beta_fact = await ws_beta.get_fact_by_id(fact_b["id"])
    assert beta_fact["valid_until"] is not None, "Beta's own fact must be closed"


@pytest.mark.asyncio
async def test_close_validity_window_by_fact_id_scoped_to_workspace(ws_alpha, ws_beta):
    """Closing by fact_id from beta must not affect alpha's fact."""
    fact_a = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    # Beta tries to close alpha's fact_id (simulates an attacker or mis-routed call)
    await ws_beta.close_validity_window(fact_id=fact_a["id"])

    alpha_fact = await ws_alpha.get_fact_by_id(fact_a["id"])
    assert alpha_fact["valid_until"] is None, (
        "close_validity_window(fact_id) must not affect facts in other workspaces"
    )


# ── expire_ttl_facts ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expire_ttl_facts_isolated_by_workspace(ws_alpha, ws_beta):
    """TTL expiry in beta must not expire alpha's facts."""
    # Use ttl_days=0 + ephemeral durability to ensure immediate expiry
    fact_a = _make_fact(
        workspace_id="alpha", ttl_days=0, committed_at=_past_iso(1), durability="ephemeral"
    )
    fact_a["valid_from"] = fact_a["committed_at"]
    await ws_alpha.insert_fact(fact_a)

    fact_b = _make_fact(
        workspace_id="beta", ttl_days=0, committed_at=_past_iso(1), durability="ephemeral"
    )
    fact_b["valid_from"] = fact_b["committed_at"]
    await ws_beta.insert_fact(fact_b)

    # Only expire in beta
    count = await ws_beta.expire_ttl_facts()
    assert count == 1, "Should expire exactly one fact in beta"

    # Alpha's fact must still be active
    alpha_fact = await ws_alpha.get_fact_by_id(fact_a["id"])
    assert alpha_fact["valid_until"] is None, (
        "expire_ttl_facts must not expire facts in other workspaces"
    )

    # Beta's fact must be expired
    beta_fact = await ws_beta.get_fact_by_id(fact_b["id"])
    assert beta_fact["valid_until"] is not None, "Beta's TTL fact should be expired"


# ── get_current_facts_in_scope ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_current_facts_in_scope_isolated(ws_alpha, ws_beta):
    """Query results must only include facts from the calling workspace."""
    fact_a = _make_fact(scope="infra", workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    fact_b = _make_fact(scope="infra", workspace_id="beta")
    await ws_beta.insert_fact(fact_b)

    alpha_results = await ws_alpha.get_current_facts_in_scope(scope="infra")
    beta_results = await ws_beta.get_current_facts_in_scope(scope="infra")

    alpha_ids = {f["id"] for f in alpha_results}
    beta_ids = {f["id"] for f in beta_results}

    assert fact_a["id"] in alpha_ids
    assert fact_b["id"] not in alpha_ids, "Alpha must not see beta's facts"

    assert fact_b["id"] in beta_ids
    assert fact_a["id"] not in beta_ids, "Beta must not see alpha's facts"


# ── get_facts_by_rowids (FTS post-filter) ─────────────────────────────


@pytest.mark.asyncio
async def test_get_facts_by_rowids_filters_by_workspace(ws_alpha, ws_beta):
    """get_facts_by_rowids must filter out facts belonging to other workspaces."""
    fact_a = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    # Retrieve the rowid of alpha's fact via direct DB query
    cursor = await ws_alpha.db.execute("SELECT rowid FROM facts WHERE id = ?", (fact_a["id"],))
    row = await cursor.fetchone()
    alpha_rowid = row[0]

    # Ask beta to fetch by that rowid — it should return nothing
    results = await ws_beta.get_facts_by_rowids([alpha_rowid])
    assert results == [], "get_facts_by_rowids must not return facts from other workspaces"

    # Alpha itself can retrieve it
    results = await ws_alpha.get_facts_by_rowids([alpha_rowid])
    assert len(results) == 1
    assert results[0]["id"] == fact_a["id"]


# ── get_promotable_ephemeral_facts ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_promotable_ephemeral_facts_isolated(ws_alpha, ws_beta):
    """Promotable ephemeral facts must only come from the calling workspace."""
    fact_a = _make_fact(workspace_id="alpha", durability="ephemeral")
    await ws_alpha.insert_fact(fact_a)
    await ws_alpha.db.execute("UPDATE facts SET query_hits = 5 WHERE id = ?", (fact_a["id"],))
    await ws_alpha.db.commit()

    # Beta should not see alpha's promotable ephemeral facts
    beta_promotable = await ws_beta.get_promotable_ephemeral_facts(min_hits=2)
    beta_ids = {f["id"] for f in beta_promotable}
    assert fact_a["id"] not in beta_ids, "Beta must not see alpha's promotable facts"

    # Alpha should see its own
    alpha_promotable = await ws_alpha.get_promotable_ephemeral_facts(min_hits=2)
    alpha_ids = {f["id"] for f in alpha_promotable}
    assert fact_a["id"] in alpha_ids


# ── retire_stale_facts ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retire_stale_facts_isolated_by_workspace(ws_alpha, ws_beta):
    """retire_stale_facts in beta must not retire alpha's stale inferences."""
    old_date = _past_iso(40)  # 40 days ago, older than 30-day inference threshold

    fact_a = _make_fact(
        workspace_id="alpha",
        fact_type="inference",
        committed_at=old_date,
    )
    fact_a["valid_from"] = old_date
    await ws_alpha.insert_fact(fact_a)

    # Beta retires its stale facts
    count = await ws_beta.retire_stale_facts()
    assert count == 0, "Beta has no stale facts to retire"

    # Alpha's stale inference should still be active
    alpha_fact = await ws_alpha.get_fact_by_id(fact_a["id"])
    assert alpha_fact["valid_until"] is None, (
        "retire_stale_facts must not retire facts in other workspaces"
    )

    # Alpha retiring its own stale facts should work
    count = await ws_alpha.retire_stale_facts()
    assert count == 1
    alpha_fact = await ws_alpha.get_fact_by_id(fact_a["id"])
    assert alpha_fact["valid_until"] is not None


# ── conflict_exists ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_exists_does_not_cross_workspaces(ws_alpha, ws_beta):
    """conflict_exists in beta must not be suppressed by alpha's conflicts."""
    fact_a1 = _make_fact(workspace_id="alpha")
    fact_a2 = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a1)
    await ws_alpha.insert_fact(fact_a2)

    conflict = _make_conflict(fact_a1["id"], fact_a2["id"], workspace_id="alpha")
    await ws_alpha.insert_conflict(conflict)

    # Beta checks for the same fact IDs — should return False (not its conflict)
    exists_in_beta = await ws_beta.conflict_exists(fact_a1["id"], fact_a2["id"])
    assert not exists_in_beta, "conflict_exists must not find conflicts from another workspace"

    # Alpha checks — should return True
    exists_in_alpha = await ws_alpha.conflict_exists(fact_a1["id"], fact_a2["id"])
    assert exists_in_alpha, "conflict_exists must find conflicts within the same workspace"


# ── insert_conflict + get_conflicts ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_conflicts_isolated_by_workspace(ws_alpha, ws_beta):
    """get_conflicts must only return conflicts belonging to the calling workspace."""
    fact_a1 = _make_fact(workspace_id="alpha")
    fact_a2 = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a1)
    await ws_alpha.insert_fact(fact_a2)

    conflict_a = _make_conflict(fact_a1["id"], fact_a2["id"], workspace_id="alpha")
    await ws_alpha.insert_conflict(conflict_a)

    fact_b1 = _make_fact(workspace_id="beta")
    fact_b2 = _make_fact(workspace_id="beta")
    await ws_beta.insert_fact(fact_b1)
    await ws_beta.insert_fact(fact_b2)

    conflict_b = _make_conflict(fact_b1["id"], fact_b2["id"], workspace_id="beta")
    await ws_beta.insert_conflict(conflict_b)

    alpha_conflicts = await ws_alpha.get_conflicts(status="all")
    beta_conflicts = await ws_beta.get_conflicts(status="all")

    alpha_conflict_ids = {c["id"] for c in alpha_conflicts}
    beta_conflict_ids = {c["id"] for c in beta_conflicts}

    assert conflict_a["id"] in alpha_conflict_ids
    assert conflict_b["id"] not in alpha_conflict_ids, "Alpha must not see beta's conflicts"

    assert conflict_b["id"] in beta_conflict_ids
    assert conflict_a["id"] not in beta_conflict_ids, "Beta must not see alpha's conflicts"


@pytest.mark.asyncio
async def test_insert_conflict_sets_workspace_id(ws_alpha):
    """insert_conflict must persist workspace_id from the storage instance."""
    fact1 = _make_fact(workspace_id="alpha")
    fact2 = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact1)
    await ws_alpha.insert_fact(fact2)

    conflict = _make_conflict(fact1["id"], fact2["id"])
    # Omit workspace_id from the dict — storage should fill it from self.workspace_id
    conflict.pop("workspace_id", None)
    await ws_alpha.insert_conflict(conflict)

    cursor = await ws_alpha.db.execute(
        "SELECT workspace_id FROM conflicts WHERE id = ?", (conflict["id"],)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "alpha", "insert_conflict must tag the row with self.workspace_id"


# ── count_facts ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_count_facts_isolated_by_workspace(ws_alpha, ws_beta):
    """count_facts must only count facts in the calling workspace."""
    for _ in range(3):
        await ws_alpha.insert_fact(_make_fact(workspace_id="alpha"))
    for _ in range(5):
        await ws_beta.insert_fact(_make_fact(workspace_id="beta"))

    assert await ws_alpha.count_facts() == 3
    assert await ws_beta.count_facts() == 5


# ── count_conflicts ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_count_conflicts_isolated_by_workspace(ws_alpha, ws_beta):
    """count_conflicts must only count conflicts in the calling workspace."""
    # Insert 2 conflicts in alpha
    for _ in range(2):
        f1 = _make_fact(workspace_id="alpha")
        f2 = _make_fact(workspace_id="alpha")
        await ws_alpha.insert_fact(f1)
        await ws_alpha.insert_fact(f2)
        await ws_alpha.insert_conflict(_make_conflict(f1["id"], f2["id"], workspace_id="alpha"))

    # Insert 1 conflict in beta
    f1 = _make_fact(workspace_id="beta")
    f2 = _make_fact(workspace_id="beta")
    await ws_beta.insert_fact(f1)
    await ws_beta.insert_fact(f2)
    await ws_beta.insert_conflict(_make_conflict(f1["id"], f2["id"], workspace_id="beta"))

    assert await ws_alpha.count_conflicts() == 2
    assert await ws_beta.count_conflicts() == 1


# ── get_fact_timeline ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_fact_timeline_isolated_by_workspace(ws_alpha, ws_beta):
    """Timeline view must only include facts from the calling workspace."""
    fact_a = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    fact_b = _make_fact(workspace_id="beta")
    await ws_beta.insert_fact(fact_b)

    alpha_timeline = await ws_alpha.get_fact_timeline()
    beta_timeline = await ws_beta.get_fact_timeline()

    alpha_ids = {f["id"] for f in alpha_timeline}
    beta_ids = {f["id"] for f in beta_timeline}

    assert fact_a["id"] in alpha_ids
    assert fact_b["id"] not in alpha_ids, "Alpha timeline must not contain beta's facts"

    assert fact_b["id"] in beta_ids
    assert fact_a["id"] not in beta_ids, "Beta timeline must not contain alpha's facts"


# ── get_open_conflict_fact_ids ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_open_conflict_fact_ids_isolated(ws_alpha, ws_beta):
    """Open conflict fact IDs must only come from the calling workspace."""
    f1 = _make_fact(workspace_id="alpha")
    f2 = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(f1)
    await ws_alpha.insert_fact(f2)
    await ws_alpha.insert_conflict(_make_conflict(f1["id"], f2["id"], workspace_id="alpha"))

    beta_ids = await ws_beta.get_open_conflict_fact_ids()
    assert f1["id"] not in beta_ids, "Beta must not see alpha's conflict fact IDs"
    assert f2["id"] not in beta_ids

    alpha_ids = await ws_alpha.get_open_conflict_fact_ids()
    assert f1["id"] in alpha_ids
    assert f2["id"] in alpha_ids


# ── get_stale_open_conflicts ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stale_open_conflicts_isolated(ws_alpha, ws_beta):
    """Stale conflict escalation must only touch conflicts in the calling workspace."""
    f1 = _make_fact(workspace_id="alpha")
    f2 = _make_fact(workspace_id="alpha")
    await ws_alpha.insert_fact(f1)
    await ws_alpha.insert_fact(f2)

    # Insert a conflict that looks old
    stale_conflict = _make_conflict(f1["id"], f2["id"], workspace_id="alpha")
    stale_conflict["detected_at"] = _past_iso(4)  # 4 days ago > 72h threshold
    await ws_alpha.insert_conflict(stale_conflict)

    # Beta should not see alpha's stale conflicts
    beta_stale = await ws_beta.get_stale_open_conflicts(older_than_hours=1)
    beta_ids = {c["id"] for c in beta_stale}
    assert stale_conflict["id"] not in beta_ids

    # Alpha should see its own stale conflict
    alpha_stale = await ws_alpha.get_stale_open_conflicts(older_than_hours=1)
    alpha_ids = {c["id"] for c in alpha_stale}
    assert stale_conflict["id"] in alpha_ids


# ── get_facts_by_lineage ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_facts_by_lineage_isolated(ws_alpha, ws_beta):
    """Lineage lookup must not return facts from another workspace."""
    lineage_id = uuid.uuid4().hex

    fact_a = _make_fact(workspace_id="alpha")
    fact_a["lineage_id"] = lineage_id
    await ws_alpha.insert_fact(fact_a)

    # A different fact in beta using the same lineage_id
    fact_b = _make_fact(workspace_id="beta")
    fact_b["lineage_id"] = lineage_id
    await ws_beta.insert_fact(fact_b)

    alpha_lineage = await ws_alpha.get_facts_by_lineage(lineage_id)
    beta_lineage = await ws_beta.get_facts_by_lineage(lineage_id)

    alpha_ids = {f["id"] for f in alpha_lineage}
    beta_ids = {f["id"] for f in beta_lineage}

    assert fact_a["id"] in alpha_ids
    assert fact_b["id"] not in alpha_ids, "Alpha lineage must not contain beta's facts"

    assert fact_b["id"] in beta_ids
    assert fact_a["id"] not in beta_ids, "Beta lineage must not contain alpha's facts"


# ── get_active_facts_with_embeddings ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_active_facts_with_embeddings_isolated(ws_alpha, ws_beta):
    """Embedding-based retrieval must not return facts from another workspace."""
    import struct

    # Create a dummy embedding blob
    dummy_embedding = struct.pack("f" * 4, 0.1, 0.2, 0.3, 0.4)

    fact_a = _make_fact(scope="infra", workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)
    await ws_alpha.update_fact_embedding(fact_a["id"], dummy_embedding)

    fact_b = _make_fact(scope="infra", workspace_id="beta")
    await ws_beta.insert_fact(fact_b)
    await ws_beta.update_fact_embedding(fact_b["id"], dummy_embedding)

    alpha_results = await ws_alpha.get_active_facts_with_embeddings("infra")
    beta_results = await ws_beta.get_active_facts_with_embeddings("infra")

    alpha_ids = {f["id"] for f in alpha_results}
    beta_ids = {f["id"] for f in beta_results}

    assert fact_a["id"] in alpha_ids
    assert fact_b["id"] not in alpha_ids, "Alpha must not see beta's embeddings"

    assert fact_b["id"] in beta_ids
    assert fact_a["id"] not in beta_ids, "Beta must not see alpha's embeddings"


# ── entity conflict detection (pre-existing tests, kept for completeness) ─


@pytest.mark.asyncio
async def test_find_entity_conflicts_isolated_by_workspace(ws_alpha, ws_beta):
    """Tier 0: entity conflicts must not leak across workspaces."""
    entity = {"name": "rate_limit", "type": "numeric", "value": 500}

    fact_a = _make_fact(scope="auth", entities=[entity], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    entity_b = {"name": "rate_limit", "type": "numeric", "value": 1000}
    fact_b = _make_fact(scope="auth", entities=[entity_b], workspace_id="beta")
    await ws_beta.insert_fact(fact_b)

    conflicts_from_beta = await ws_beta.find_entity_conflicts(
        entity_name="rate_limit",
        entity_type="numeric",
        entity_value="1000",
        scope="auth",
        exclude_id=fact_b["id"],
    )
    assert len(conflicts_from_beta) == 0, (
        "Workspace beta must not see workspace alpha's facts as conflicts"
    )

    conflicts_from_alpha = await ws_alpha.find_entity_conflicts(
        entity_name="rate_limit",
        entity_type="numeric",
        entity_value="500",
        scope="auth",
        exclude_id=fact_a["id"],
    )
    assert len(conflicts_from_alpha) == 0, (
        "Workspace alpha must not see workspace beta's facts as conflicts"
    )


@pytest.mark.asyncio
async def test_find_entity_conflicts_within_same_workspace(ws_alpha):
    """Tier 0: conflicts within the same workspace must still be detected."""
    entity_500 = {"name": "rate_limit", "type": "numeric", "value": 500}
    entity_1000 = {"name": "rate_limit", "type": "numeric", "value": 1000}

    fact_1 = _make_fact(scope="auth", entities=[entity_500], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_1)

    fact_2 = _make_fact(scope="auth", entities=[entity_1000], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_2)

    conflicts = await ws_alpha.find_entity_conflicts(
        entity_name="rate_limit",
        entity_type="numeric",
        entity_value="1000",
        scope="auth",
        exclude_id=fact_2["id"],
    )
    assert len(conflicts) == 1, "Conflict within the same workspace must be detected"
    assert conflicts[0]["id"] == fact_1["id"]


@pytest.mark.asyncio
async def test_cross_scope_entity_matches_isolated_by_workspace(ws_alpha, ws_beta):
    """Tier 2b: cross-scope entity matches must not leak across workspaces."""
    entity = {"name": "rate_limit", "type": "numeric", "value": 500}

    fact_a = _make_fact(scope="auth", entities=[entity], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_a)

    entity_b = {"name": "rate_limit", "type": "numeric", "value": 1000}
    fact_b = _make_fact(scope="payments", entities=[entity_b], workspace_id="beta")
    await ws_beta.insert_fact(fact_b)

    matches_from_beta = await ws_beta.find_cross_scope_entity_matches(
        entity_name="rate_limit",
        entity_type="numeric",
        entity_value="1000",
        exclude_id=fact_b["id"],
    )
    assert len(matches_from_beta) == 0, (
        "Workspace beta must not see workspace alpha's facts in cross-scope matches"
    )


@pytest.mark.asyncio
async def test_cross_scope_entity_matches_within_same_workspace(ws_alpha):
    """Tier 2b: cross-scope matches within the same workspace must still work."""
    entity_500 = {"name": "rate_limit", "type": "numeric", "value": 500}
    entity_1000 = {"name": "rate_limit", "type": "numeric", "value": 1000}

    fact_auth = _make_fact(scope="auth", entities=[entity_500], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_auth)

    fact_payments = _make_fact(scope="payments", entities=[entity_1000], workspace_id="alpha")
    await ws_alpha.insert_fact(fact_payments)

    matches = await ws_alpha.find_cross_scope_entity_matches(
        entity_name="rate_limit",
        entity_type="numeric",
        entity_value="1000",
        exclude_id=fact_payments["id"],
    )
    assert len(matches) == 1, "Cross-scope match within the same workspace must be detected"
    assert matches[0]["id"] == fact_auth["id"]
