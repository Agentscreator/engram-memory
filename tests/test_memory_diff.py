"""Tests for memory diff over workspace time windows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner
import pytest

from engram.cli import main
from engram.engine import EngramEngine


def _ts(hours: int = 0) -> str:
    base = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=hours)).isoformat()


def _fact(
    *,
    content: str,
    scope: str = "api",
    committed_at: str | None = None,
    valid_until: str | None = None,
) -> dict:
    now = committed_at or _ts()
    return {
        "id": uuid.uuid4().hex,
        "lineage_id": uuid.uuid4().hex,
        "content": content,
        "content_hash": uuid.uuid4().hex,
        "scope": scope,
        "confidence": 0.8,
        "fact_type": "observation",
        "agent_id": "agent-1",
        "engineer": "Tunde",
        "provenance": None,
        "keywords": "[]",
        "entities": "[]",
        "artifact_hash": None,
        "embedding": None,
        "embedding_model": "test",
        "embedding_ver": "test",
        "committed_at": now,
        "valid_from": now,
        "valid_until": valid_until,
        "ttl_days": None,
        "memory_op": "add",
        "supersedes_fact_id": None,
        "durability": "durable",
    }


@pytest.mark.asyncio
async def test_diff_memory_reports_added_retired_and_resolved_conflicts(engine: EngramEngine):
    added = _fact(content="The API timeout is 30 seconds", committed_at=_ts(1))
    outside = _fact(content="Outside the window", committed_at=_ts(-5))
    retired = _fact(
        content="Old API timeout was 10 seconds",
        committed_at=_ts(-4),
        valid_until=_ts(2),
    )
    conflict_a = _fact(content="Auth timeout is 30 seconds", scope="auth", committed_at=_ts(-3))
    conflict_b = _fact(content="Auth timeout is 60 seconds", scope="auth", committed_at=_ts(-2))

    for fact in (added, outside, retired, conflict_a, conflict_b):
        await engine.storage.insert_fact(fact)

    conflict_id = uuid.uuid4().hex
    await engine.storage.insert_conflict(
        {
            "id": conflict_id,
            "fact_a_id": conflict_a["id"],
            "fact_b_id": conflict_b["id"],
            "detected_at": _ts(-1),
            "detection_tier": "tier2_numeric",
            "entailment_score": 0.1,
            "contradiction_score": 0.9,
            "explanation": "timeout differs",
            "severity": "high",
            "status": "open",
        }
    )
    assert await engine.storage.resolve_conflict(
        conflict_id,
        resolution_type="dismissed",
        resolution="false positive",
        resolved_by="agent-reviewer",
    )
    await engine.storage.db.execute(
        "UPDATE conflicts SET resolved_at = ? WHERE id = ?",
        (_ts(2), conflict_id),
    )
    await engine.storage.db.commit()

    result = await engine.diff_memory(_ts(0), _ts(3))

    assert result["summary"] == {
        "added": 1,
        "superseded": 1,
        "resolved_conflicts": 1,
    }
    assert [fact["id"] for fact in result["added"]] == [added["id"]]
    assert [fact["id"] for fact in result["superseded"]] == [retired["id"]]
    assert [conflict["id"] for conflict in result["resolved_conflicts"]] == [conflict_id]


@pytest.mark.asyncio
async def test_diff_memory_applies_scope_filter(engine: EngramEngine):
    auth_fact = _fact(content="Auth uses JWT", scope="auth/jwt", committed_at=_ts(1))
    payments_fact = _fact(content="Payments use Stripe", scope="payments", committed_at=_ts(1))
    await engine.storage.insert_fact(auth_fact)
    await engine.storage.insert_fact(payments_fact)

    result = await engine.diff_memory(_ts(0), _ts(2), scope="auth")

    assert result["summary"]["added"] == 1
    assert result["added"][0]["id"] == auth_fact["id"]


@pytest.mark.asyncio
async def test_diff_memory_rejects_invalid_window(engine: EngramEngine):
    with pytest.raises(ValueError, match="earlier"):
        await engine.diff_memory(_ts(2), _ts(1))


@pytest.mark.asyncio
async def test_diff_memory_rejects_invalid_timestamp(engine: EngramEngine):
    with pytest.raises(ValueError, match="ISO-8601"):
        await engine.diff_memory("yesterday", _ts(1))


def test_diff_command_outputs_json(monkeypatch):
    async def fake_diff_once(from_time, to_time, scope, limit, as_json):
        assert from_time == "2026-04-15T00:00:00Z"
        assert to_time == "2026-04-16T00:00:00Z"
        assert scope == "auth"
        assert limit == 1000
        assert as_json is True
        return json.dumps({"summary": {"added": 1}})

    monkeypatch.setattr("engram.cli._diff_once", fake_diff_once)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "diff",
            "--from",
            "2026-04-15T00:00:00Z",
            "--to",
            "2026-04-16T00:00:00Z",
            "--scope",
            "auth",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"summary": {"added": 1}}


def test_diff_command_outputs_text(monkeypatch):
    async def fake_diff_once(from_time, to_time, scope, limit, as_json):
        assert as_json is False
        return "Memory diff\n  Added facts       : 0"

    monkeypatch.setattr("engram.cli._diff_once", fake_diff_once)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", "--from", "2026-04-15T00:00:00Z", "--to", "2026-04-16T00:00:00Z"],
    )

    assert result.exit_code == 0
    assert "Memory diff" in result.output
