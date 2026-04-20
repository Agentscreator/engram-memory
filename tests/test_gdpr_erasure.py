"""Tests for the GDPR subject-erasure pipeline.

Covers:
- Soft erase: engineer/provenance redacted, fact content preserved.
- Hard erase: content wiped, valid_until closed, embedding nulled, keywords/entities cleared.
- FTS sanity: erased content no longer returned by full-text search.
- Conflict cascade: open conflicts dismissed, resolved conflicts text-scrubbed,
  suggested_winning_fact_id nulled.
- Agents table: engineer name redacted in registry.
- scope_permissions deleted (hard erase only).
- scopes.owner_agent_id nulled (hard erase).
- Audit log: agent_id and fact_id cleared.
- Control-agent isolation: facts from other agents are untouched.
- Engine-level permission gate: PermissionError when not creator.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from engram.engine import EngramEngine
from engram.storage import Storage


# ── helpers ──────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact(
    *,
    agent_id: str = "agent-alice",
    engineer: str = "alice@example.com",
    content: str = "Cache TTL is 300s",
    scope: str = "infra",
    keywords: str = '["cache","ttl"]',
    entities: str = "[]",
    provenance: str | None = "alice's notes",
    embedding: bytes | None = b"\x00\x01\x02",
    valid_until: str | None = None,
) -> dict[str, Any]:
    now = _ts()
    return {
        "id": uuid.uuid4().hex,
        "lineage_id": uuid.uuid4().hex,
        "content": content,
        "content_hash": uuid.uuid4().hex,
        "scope": scope,
        "confidence": 0.9,
        "fact_type": "observation",
        "agent_id": agent_id,
        "engineer": engineer,
        "provenance": provenance,
        "keywords": keywords,
        "entities": entities,
        "artifact_hash": None,
        "embedding": embedding,
        "embedding_model": "test",
        "embedding_ver": "1.0",
        "durability": "durable",
        "ttl_days": None,
        "committed_at": now,
        "valid_from": now,
        "valid_until": valid_until,
    }


def _conflict(
    fact_a_id: str,
    fact_b_id: str,
    *,
    status: str = "open",
    explanation: str = "Contradiction detected",
) -> dict[str, Any]:
    """Minimal conflict dict matching the columns insert_conflict accepts."""
    return {
        "id": uuid.uuid4().hex,
        "fact_a_id": fact_a_id,
        "fact_b_id": fact_b_id,
        "detected_at": _ts(),
        "detection_tier": "tier1_nli",
        "nli_score": 0.9,
        "explanation": explanation,
        "severity": "high",
        "status": status,
    }


async def _insert_audit(storage: Storage, agent_id: str, fact_id: str | None = None) -> str:
    entry_id = uuid.uuid4().hex
    await storage.insert_audit_entry(
        {
            "id": entry_id,
            "operation": "commit",
            "agent_id": agent_id,
            "fact_id": fact_id,
            "conflict_id": None,
            "extra": '{"scope":"infra"}',
            "timestamp": _ts(),
        }
    )
    return entry_id


# ── storage-level soft erase ─────────────────────────────────────────


@pytest_asyncio.fixture
async def storage(tmp_path: Path):
    db_path = tmp_path / "test.db"
    s = Storage(db_path=db_path)
    await s.connect()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_soft_erase_redacts_engineer(storage: Storage):
    """Engineer and provenance are cleared; content is preserved."""
    f = _fact(agent_id="agent-alice", engineer="alice@example.com", content="Cache TTL is 300s")
    await storage.insert_fact(f)

    stats = await storage.gdpr_soft_erase_agent("agent-alice")

    row = await storage.get_fact_by_id(f["id"])
    assert row is not None
    assert row["engineer"] == "[redacted]"
    assert row["provenance"] is None
    # Content untouched in soft mode
    assert row["content"] == "Cache TTL is 300s"
    assert stats["facts_updated"] == 1


@pytest.mark.asyncio
async def test_soft_erase_all_versions_same_agent(storage: Storage):
    """Soft erase covers every version (all rows) for the agent."""
    f1 = _fact(agent_id="agent-alice", content="Version 1")
    f2 = _fact(agent_id="agent-alice", content="Version 2")
    await storage.insert_fact(f1)
    await storage.insert_fact(f2)

    stats = await storage.gdpr_soft_erase_agent("agent-alice")

    assert stats["facts_updated"] == 2
    for fid in (f1["id"], f2["id"]):
        row = await storage.get_fact_by_id(fid)
        assert row["engineer"] == "[redacted]"


@pytest.mark.asyncio
async def test_soft_erase_does_not_touch_other_agents(storage: Storage):
    """Facts from other agents are completely untouched."""
    alice = _fact(agent_id="agent-alice", engineer="alice@example.com")
    bob = _fact(agent_id="agent-bob", engineer="bob@example.com", content="Bob's fact")
    await storage.insert_fact(alice)
    await storage.insert_fact(bob)

    await storage.gdpr_soft_erase_agent("agent-alice")

    bob_row = await storage.get_fact_by_id(bob["id"])
    assert bob_row["engineer"] == "bob@example.com"
    assert bob_row["content"] == "Bob's fact"


@pytest.mark.asyncio
async def test_soft_erase_scrubs_conflict_text(storage: Storage):
    """Conflict explanation and suggestion fields are scrubbed for conflicts
    touching the erased agent's facts."""
    alice_fact = _fact(agent_id="agent-alice")
    bob_fact = _fact(agent_id="agent-bob")
    await storage.insert_fact(alice_fact)
    await storage.insert_fact(bob_fact)

    c = _conflict(alice_fact["id"], bob_fact["id"], explanation="alice says X but bob says Y")
    await storage.insert_conflict(c)
    # Seed suggestion columns (separate call, matching production flow)
    await storage.update_conflict_suggestion(
        c["id"],
        "Prefer alice's version",
        "winner",
        alice_fact["id"],
        "alice is senior",
        _ts(),
    )

    stats = await storage.gdpr_soft_erase_agent("agent-alice")
    assert stats["conflicts_scrubbed"] >= 1

    rows = await storage.get_conflicts(status="all")
    hit = next(r for r in rows if r["id"] == c["id"])
    assert hit["explanation"] == "[redacted]"
    assert hit["suggested_resolution"] is None
    assert hit["suggestion_reasoning"] is None
    # Status is still open — soft erase does not close conflicts
    assert hit["status"] == "open"


@pytest.mark.asyncio
async def test_soft_erase_updates_agents_registry(storage: Storage):
    """The agents table row has engineer redacted."""
    await storage.upsert_agent("agent-alice", "alice@example.com")

    await storage.gdpr_soft_erase_agent("agent-alice")

    agent = await storage.get_agent("agent-alice")
    assert agent is not None
    assert agent["engineer"] == "[redacted]"


@pytest.mark.asyncio
async def test_soft_erase_scrubs_audit_log(storage: Storage):
    """Audit rows where agent_id matches are scrubbed."""
    f = _fact(agent_id="agent-alice")
    await storage.insert_fact(f)
    audit_id = await _insert_audit(storage, "agent-alice", f["id"])

    await storage.gdpr_soft_erase_agent("agent-alice")

    # agent_id column is cleared — cannot fetch by agent_id any more
    logs = await storage.get_audit_log(agent_id="agent-alice")
    assert not any(r["id"] == audit_id for r in logs)


# ── storage-level hard erase ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_hard_erase_wipes_content(storage: Storage):
    """Fact content is replaced with a deterministic placeholder."""
    f = _fact(agent_id="agent-alice", content="Secret design doc content")
    await storage.insert_fact(f)

    await storage.gdpr_hard_erase_agent("agent-alice")

    row = await storage.get_fact_by_id(f["id"])
    assert row is not None
    assert row["content"] == f"[gdpr:erased:{f['id']}]"
    assert row["engineer"] == "[redacted]"
    assert row["provenance"] is None
    assert row["keywords"] is None
    assert row["entities"] is None
    assert row["embedding"] is None


@pytest.mark.asyncio
async def test_hard_erase_closes_validity_window(storage: Storage):
    """Current facts (valid_until IS NULL) are retired."""
    f = _fact(agent_id="agent-alice", valid_until=None)
    await storage.insert_fact(f)

    await storage.gdpr_hard_erase_agent("agent-alice")

    row = await storage.get_fact_by_id(f["id"])
    assert row["valid_until"] is not None


@pytest.mark.asyncio
async def test_hard_erase_preserves_already_closed_valid_until(storage: Storage):
    """If valid_until was already set, it is not overwritten."""
    closed_ts = "2025-01-01T00:00:00+00:00"
    f = _fact(agent_id="agent-alice", valid_until=closed_ts)
    await storage.insert_fact(f)

    await storage.gdpr_hard_erase_agent("agent-alice")

    row = await storage.get_fact_by_id(f["id"])
    assert row["valid_until"] == closed_ts


@pytest.mark.asyncio
async def test_hard_erase_content_hash_unique_per_row(storage: Storage):
    """Each erased fact gets a distinct content_hash to prevent false dedup."""
    f1 = _fact(agent_id="agent-alice", content="Fact 1")
    f2 = _fact(agent_id="agent-alice", content="Fact 2")
    await storage.insert_fact(f1)
    await storage.insert_fact(f2)

    await storage.gdpr_hard_erase_agent("agent-alice")

    r1 = await storage.get_fact_by_id(f1["id"])
    r2 = await storage.get_fact_by_id(f2["id"])
    assert r1["content_hash"] != r2["content_hash"]


@pytest.mark.asyncio
async def test_hard_erase_dismisses_open_conflicts(storage: Storage):
    """Open conflicts referencing an erased fact are dismissed with gdpr_erasure."""
    alice_fact = _fact(agent_id="agent-alice")
    bob_fact = _fact(agent_id="agent-bob")
    await storage.insert_fact(alice_fact)
    await storage.insert_fact(bob_fact)

    c = _conflict(alice_fact["id"], bob_fact["id"], status="open")
    await storage.insert_conflict(c)

    stats = await storage.gdpr_hard_erase_agent("agent-alice")
    assert stats["conflicts_closed"] == 1

    rows = await storage.get_conflicts(status="all")
    hit = next(r for r in rows if r["id"] == c["id"])
    assert hit["status"] == "dismissed"
    assert hit["resolution_type"] == "gdpr_erasure"
    assert hit["explanation"] == "[redacted]"
    assert hit["suggested_resolution"] is None


@pytest.mark.asyncio
async def test_hard_erase_scrubs_resolved_conflicts(storage: Storage):
    """Already-resolved conflicts have their free-text fields scrubbed."""
    alice_fact = _fact(agent_id="agent-alice")
    bob_fact = _fact(agent_id="agent-bob")
    await storage.insert_fact(alice_fact)
    await storage.insert_fact(bob_fact)

    c = _conflict(alice_fact["id"], bob_fact["id"], explanation="alice contradicts bob")
    await storage.insert_conflict(c)
    # Seed suggestion fields
    await storage.update_conflict_suggestion(
        c["id"],
        "Use alice's version",
        "winner",
        alice_fact["id"],
        "alice is correct",
        _ts(),
    )
    # Resolve it so status='resolved' with a resolution string
    await storage.resolve_conflict(c["id"], "winner", "human resolution text", "human")

    stats = await storage.gdpr_hard_erase_agent("agent-alice")
    assert stats["conflicts_scrubbed"] >= 1

    rows = await storage.get_conflicts(status="all")
    hit = next(r for r in rows if r["id"] == c["id"])
    assert hit["status"] == "resolved"  # status unchanged by hard erase (only open → dismissed)
    assert hit["explanation"] == "[redacted]"
    assert hit["resolution"] == "[redacted]"
    assert hit["suggested_resolution"] is None
    assert hit["suggestion_reasoning"] is None


@pytest.mark.asyncio
async def test_hard_erase_nulls_suggested_winning_fact_id(storage: Storage):
    """suggested_winning_fact_id is nulled when it points at an erased fact."""
    alice_fact = _fact(agent_id="agent-alice")
    bob_fact = _fact(agent_id="agent-bob")
    await storage.insert_fact(alice_fact)
    await storage.insert_fact(bob_fact)

    c = _conflict(alice_fact["id"], bob_fact["id"])
    await storage.insert_conflict(c)
    # Point suggested_winning_fact_id at alice's fact
    await storage.update_conflict_suggestion(
        c["id"],
        "Pick alice",
        "winner",
        alice_fact["id"],  # <-- this should be nulled
        "alice is newer",
        _ts(),
    )

    await storage.gdpr_hard_erase_agent("agent-alice")

    rows = await storage.get_conflicts(status="all")
    hit = next(r for r in rows if r["id"] == c["id"])
    assert hit["suggested_winning_fact_id"] is None


@pytest.mark.asyncio
async def test_hard_erase_deletes_scope_permissions(storage: Storage):
    """scope_permissions rows for the agent are removed."""
    await storage.set_scope_permission("agent-alice", "infra")

    stats = await storage.gdpr_hard_erase_agent("agent-alice")
    assert stats["scope_permissions_deleted"] == 1

    perm = await storage.get_scope_permission("agent-alice", "infra")
    assert perm is None


@pytest.mark.asyncio
async def test_hard_erase_scrubs_audit_log(storage: Storage):
    """Audit rows by actor and by fact_id are scrubbed."""
    f = _fact(agent_id="agent-alice")
    await storage.insert_fact(f)
    actor_audit_id = await _insert_audit(storage, "agent-alice", None)
    fact_audit_id = await _insert_audit(storage, "agent-other", f["id"])

    stats = await storage.gdpr_hard_erase_agent("agent-alice")
    assert stats["audit_rows_scrubbed"] >= 2

    # Actor row: agent_id cleared
    actor_logs = await storage.get_audit_log(agent_id="agent-alice")
    assert not any(r["id"] == actor_audit_id for r in actor_logs)

    # Fact-tied row: fact_id cleared (we can still fetch by id via get_audit_log
    # — fact_id is cleared, so we cannot filter by it; check absence another way)
    all_logs = await storage.get_audit_log(limit=1000)
    fact_log = next((r for r in all_logs if r["id"] == fact_audit_id), None)
    assert fact_log is not None
    assert fact_log["fact_id"] is None


@pytest.mark.asyncio
async def test_hard_erase_does_not_touch_other_agents(storage: Storage):
    """Facts, conflicts, and audit rows belonging to other agents are untouched."""
    alice = _fact(agent_id="agent-alice", content="Alice's fact")
    bob = _fact(agent_id="agent-bob", engineer="bob@example.com", content="Bob's fact")
    await storage.insert_fact(alice)
    await storage.insert_fact(bob)

    # Conflict between two bob facts — should not be touched
    bob2 = _fact(agent_id="agent-bob", content="Bob's second fact")
    await storage.insert_fact(bob2)
    c_bob = _conflict(bob["id"], bob2["id"], explanation="bob conflict")
    await storage.insert_conflict(c_bob)

    await storage.gdpr_hard_erase_agent("agent-alice")

    bob_row = await storage.get_fact_by_id(bob["id"])
    assert bob_row["engineer"] == "bob@example.com"
    assert bob_row["content"] == "Bob's fact"

    rows = await storage.get_conflicts(status="all")
    bob_conflict = next(r for r in rows if r["id"] == c_bob["id"])
    assert bob_conflict["status"] == "open"
    assert bob_conflict["explanation"] == "bob conflict"


# ── FTS sanity (hard erase) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_hard_erase_removes_content_from_fts(storage: Storage):
    """After hard erase the unique token in the erased fact cannot be found via FTS."""
    unique_token = "xQzR7YpL2mNv9wK"
    f = _fact(agent_id="agent-alice", content=f"Super secret token is {unique_token}")
    await storage.insert_fact(f)

    # Confirm it is reachable before erase
    rowids_before = await storage.fts_search(unique_token, limit=10)
    assert rowids_before, "Token should appear in FTS before erase"

    await storage.gdpr_hard_erase_agent("agent-alice")

    rowids_after = await storage.fts_search(unique_token, limit=10)
    # The placeholder content does not contain the token, so FTS must return nothing
    assert not rowids_after, "Token must not appear in FTS after hard erase"


# ── engine-level permission gate ─────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_gdpr_erase_requires_creator(storage: Storage):
    """PermissionError raised when workspace is not a creator workspace."""
    engine = EngramEngine(storage)

    mock_ws = MagicMock()
    mock_ws.is_creator = False

    with patch("engram.workspace.read_workspace", return_value=mock_ws):
        with pytest.raises(PermissionError, match="workspace creator"):
            await engine.gdpr_erase_agent("agent-alice", "soft")


@pytest.mark.asyncio
async def test_engine_gdpr_erase_no_workspace_raises(storage: Storage):
    """PermissionError raised when no workspace.json is present."""
    engine = EngramEngine(storage)

    with patch("engram.workspace.read_workspace", return_value=None):
        with pytest.raises(PermissionError):
            await engine.gdpr_erase_agent("agent-alice", "soft")


@pytest.mark.asyncio
async def test_engine_gdpr_erase_soft_succeeds_as_creator(storage: Storage):
    """Engine soft erase succeeds when is_creator=True."""
    engine = EngramEngine(storage)
    f = _fact(agent_id="agent-alice")
    await storage.insert_fact(f)

    mock_ws = MagicMock()
    mock_ws.is_creator = True

    with patch("engram.workspace.read_workspace", return_value=mock_ws):
        result = await engine.gdpr_erase_agent("agent-alice", "soft", actor="test")

    assert result["erased_agent_id"] == "agent-alice"
    assert result["mode"] == "soft"
    assert result["stats"]["facts_updated"] == 1
    row = await storage.get_fact_by_id(f["id"])
    assert row["engineer"] == "[redacted]"


@pytest.mark.asyncio
async def test_engine_gdpr_erase_hard_succeeds_as_creator(storage: Storage):
    """Engine hard erase closes facts and returns expected stats."""
    engine = EngramEngine(storage)
    f = _fact(agent_id="agent-alice")
    await storage.insert_fact(f)
    await storage.upsert_agent("agent-alice", "alice@example.com")

    mock_ws = MagicMock()
    mock_ws.is_creator = True

    with patch("engram.workspace.read_workspace", return_value=mock_ws):
        result = await engine.gdpr_erase_agent("agent-alice", "hard", actor="test")

    assert result["mode"] == "hard"
    row = await storage.get_fact_by_id(f["id"])
    assert row["valid_until"] is not None
    assert row["content"].startswith("[gdpr:erased:")


@pytest.mark.asyncio
async def test_engine_gdpr_erase_invalid_mode_raises(storage: Storage):
    """ValueError is raised before the workspace check, so no patch needed."""
    engine = EngramEngine(storage)

    with pytest.raises(ValueError, match="mode must be"):
        await engine.gdpr_erase_agent("agent-alice", "delete")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_engine_gdpr_erase_empty_agent_id_raises(storage: Storage):
    """ValueError is raised before the workspace check, so no patch needed."""
    engine = EngramEngine(storage)

    with pytest.raises(ValueError, match="non-empty"):
        await engine.gdpr_erase_agent("", "soft")


# ── return value shape ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_erase_stats_keys(storage: Storage):
    """Return dict contains all expected keys."""
    stats = await storage.gdpr_soft_erase_agent("nonexistent-agent")
    expected = {
        "facts_updated",
        "conflicts_scrubbed",
        "agents_updated",
        "conflicts_closed",
        "scope_permissions_deleted",
        "scopes_updated",
        "audit_rows_scrubbed",
    }
    assert set(stats.keys()) == expected


@pytest.mark.asyncio
async def test_hard_erase_stats_keys(storage: Storage):
    """Return dict contains all expected keys."""
    stats = await storage.gdpr_hard_erase_agent("nonexistent-agent")
    expected = {
        "facts_updated",
        "conflicts_closed",
        "conflicts_scrubbed",
        "agents_updated",
        "scope_permissions_deleted",
        "scopes_updated",
        "audit_rows_scrubbed",
    }
    assert set(stats.keys()) == expected


@pytest.mark.asyncio
async def test_erase_nonexistent_agent_is_zero_noop(storage: Storage):
    """Erasing an agent_id that has no data returns zeros and does not error."""
    stats_soft = await storage.gdpr_soft_erase_agent("agent-nobody")
    assert stats_soft["facts_updated"] == 0

    stats_hard = await storage.gdpr_hard_erase_agent("agent-nobody")
    assert stats_hard["facts_updated"] == 0
    assert stats_hard["conflicts_closed"] == 0
