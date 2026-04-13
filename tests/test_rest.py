"""Tests for the REST API input validation layer (rest.py).

Verifies that each endpoint returns a clean 400 error for invalid inputs
rather than propagating the request to the engine and returning a 500.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient
from starlette.applications import Starlette

from engram.rest import build_rest_routes


# ── helpers ──────────────────────────────────────────────────────────


def _build_client(
    commit_result=None, query_result=None, conflicts_result=None, resolve_result=None
):
    """Build a Starlette test client with mocked engine and storage."""
    engine = MagicMock()
    engine.commit = AsyncMock(
        return_value=commit_result
        or {"fact_id": "abc", "duplicate": False, "committed_at": "2024-01-01T00:00:00+00:00"}
    )
    engine.query = AsyncMock(return_value=query_result or [])
    engine.get_conflicts = AsyncMock(return_value=conflicts_result or [])
    engine.resolve = AsyncMock(
        return_value=resolve_result or {"resolved": True, "resolution_type": "winner"}
    )
    engine.batch_commit = AsyncMock(return_value={})
    engine.get_stats = AsyncMock(return_value={})
    engine.record_feedback = AsyncMock(return_value={"recorded": True})
    engine.get_timeline = AsyncMock(return_value=[])
    engine.get_agents = AsyncMock(return_value=[])
    engine.list_facts = AsyncMock(return_value=[])
    engine.get_fact = AsyncMock(return_value=None)
    engine.get_lineage = AsyncMock(return_value=[])
    engine.get_expiring_facts = AsyncMock(return_value=[])
    engine.bulk_dismiss = AsyncMock(
        return_value={"total": 0, "dismissed": 0, "failed": 0, "results": []}
    )
    # Round 8: new engine methods
    engine.create_webhook = AsyncMock(
        return_value={
            "webhook_id": "wh1",
            "url": "https://example.com/hook",
            "events": ["fact.committed"],
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )
    engine.list_webhooks = AsyncMock(return_value=[])
    engine.delete_webhook = AsyncMock(return_value={"deleted": True, "webhook_id": "wh1"})
    engine.create_rule = AsyncMock(
        return_value={
            "rule_id": "r1",
            "scope_prefix": "auth",
            "condition_type": "latest_wins",
            "condition_value": "",
            "resolution_type": "winner",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )
    engine.list_rules = AsyncMock(return_value=[])
    engine.delete_rule = AsyncMock(return_value={"deleted": True, "rule_id": "r1"})
    engine.export_workspace = AsyncMock(return_value=[])
    engine.import_workspace = AsyncMock(
        return_value={"total": 0, "imported": 0, "duplicates": 0, "failed": 0}
    )
    engine.subscribe = MagicMock(return_value=asyncio.Queue())
    engine.unsubscribe = MagicMock()
    engine.register_scope = AsyncMock(return_value={"scope": "auth", "registered": True})
    engine.list_scopes = AsyncMock(return_value=[])
    engine.get_scope_info = AsyncMock(
        return_value={
            "registration": None,
            "analytics": {
                "scope": "auth",
                "fact_count": 0,
                "active_fact_count": 0,
                "conflict_count": 0,
                "conflict_rate": 0.0,
                "most_active_agent": None,
                "avg_confidence": 0.0,
            },
        }
    )
    engine.diff_facts = AsyncMock(
        return_value={
            "fact_a": {},
            "fact_b": {},
            "changes": [],
            "entity_changes": {"added": [], "removed": [], "changed": []},
        }
    )
    engine.get_audit_log = AsyncMock(return_value=[])

    storage = MagicMock()
    storage.count_facts = AsyncMock(return_value=0)
    storage.count_conflicts = AsyncMock(return_value=0)

    routes = build_rest_routes(engine, storage, auth_enabled=False, rate_limiter=None)
    app = Starlette(routes=routes)
    return TestClient(app, raise_server_exceptions=False), engine


# ── /api/commit validation ────────────────────────────────────────────


def test_commit_missing_content():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"scope": "auth", "confidence": 0.9})
    assert resp.status_code == 400
    assert "content" in resp.json()["error"].lower()


def test_commit_whitespace_content():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "   ", "scope": "auth", "confidence": 0.9})
    assert resp.status_code == 400
    assert "content" in resp.json()["error"].lower()


def test_commit_missing_scope():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "test", "confidence": 0.9})
    assert resp.status_code == 400
    assert "scope" in resp.json()["error"].lower()


def test_commit_whitespace_scope():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "test", "scope": "  ", "confidence": 0.9})
    assert resp.status_code == 400
    assert "scope" in resp.json()["error"].lower()


def test_commit_missing_confidence():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "test", "scope": "auth"})
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_commit_confidence_not_a_number():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit", json={"content": "test", "scope": "auth", "confidence": "high"}
    )
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_commit_confidence_above_range():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "test", "scope": "auth", "confidence": 1.5})
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_commit_confidence_below_range():
    client, _ = _build_client()
    resp = client.post("/api/commit", json={"content": "test", "scope": "auth", "confidence": -0.1})
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_commit_invalid_fact_type():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "test",
            "scope": "auth",
            "confidence": 0.9,
            "fact_type": "guess",
        },
    )
    assert resp.status_code == 400
    assert "fact_type" in resp.json()["error"].lower()


def test_commit_invalid_operation():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "test",
            "scope": "auth",
            "confidence": 0.9,
            "operation": "upsert",
        },
    )
    assert resp.status_code == 400
    assert "operation" in resp.json()["error"].lower()


def test_commit_invalid_ttl_days_negative():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "test",
            "scope": "auth",
            "confidence": 0.9,
            "ttl_days": -1,
        },
    )
    assert resp.status_code == 400
    assert "ttl_days" in resp.json()["error"].lower()


def test_commit_invalid_ttl_days_zero():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "test",
            "scope": "auth",
            "confidence": 0.9,
            "ttl_days": 0,
        },
    )
    assert resp.status_code == 400
    assert "ttl_days" in resp.json()["error"].lower()


def test_commit_invalid_ttl_days_string():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "test",
            "scope": "auth",
            "confidence": 0.9,
            "ttl_days": "forever",
        },
    )
    assert resp.status_code == 400
    assert "ttl_days" in resp.json()["error"].lower()


def test_commit_invalid_json_body():
    client, _ = _build_client()
    resp = client.post(
        "/api/commit", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


def test_commit_valid_passes_through():
    client, engine = _build_client()
    resp = client.post(
        "/api/commit",
        json={
            "content": "Redis runs on port 6379",
            "scope": "infra",
            "confidence": 0.95,
            "fact_type": "observation",
            "operation": "add",
            "ttl_days": 7,
        },
    )
    assert resp.status_code == 200
    engine.commit.assert_called_once()


# ── /api/query validation ─────────────────────────────────────────────


def test_query_missing_topic():
    client, _ = _build_client()
    resp = client.post("/api/query", json={"scope": "auth"})
    assert resp.status_code == 400
    assert "topic" in resp.json()["error"].lower()


def test_query_invalid_as_of():
    client, _ = _build_client()
    resp = client.post("/api/query", json={"topic": "rate limits", "as_of": "not-a-date"})
    assert resp.status_code == 400
    assert "as_of" in resp.json()["error"].lower()


def test_query_valid_as_of():
    client, _ = _build_client()
    resp = client.post(
        "/api/query",
        json={
            "topic": "rate limits",
            "as_of": "2024-01-15T12:00:00+00:00",
        },
    )
    assert resp.status_code == 200


def test_query_invalid_json():
    client, _ = _build_client()
    resp = client.post(
        "/api/query", content=b"{bad json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


# ── /api/conflicts validation ─────────────────────────────────────────


def test_conflicts_invalid_status():
    client, _ = _build_client()
    resp = client.get("/api/conflicts?status=pending")
    assert resp.status_code == 400
    assert "status" in resp.json()["error"].lower()


def test_conflicts_valid_statuses():
    client, _ = _build_client()
    for status in ("open", "resolved", "dismissed", "all"):
        resp = client.get(f"/api/conflicts?status={status}")
        assert resp.status_code == 200, f"Expected 200 for status={status}"


def test_conflicts_default_status():
    client, engine = _build_client()
    resp = client.get("/api/conflicts")
    assert resp.status_code == 200
    engine.get_conflicts.assert_called_once_with(scope=None, status="open")


# ── /api/resolve validation ───────────────────────────────────────────


def test_resolve_missing_conflict_id():
    client, _ = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "resolution_type": "winner",
            "resolution": "fact A is correct",
        },
    )
    assert resp.status_code == 400
    assert "conflict_id" in resp.json()["error"].lower()


def test_resolve_missing_resolution_type():
    client, _ = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution": "fact A is correct",
        },
    )
    assert resp.status_code == 400
    assert "resolution_type" in resp.json()["error"].lower()


def test_resolve_invalid_resolution_type():
    client, _ = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution_type": "ignore",
            "resolution": "fact A is correct",
        },
    )
    assert resp.status_code == 400
    assert "resolution_type" in resp.json()["error"].lower()


def test_resolve_missing_resolution():
    client, _ = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution_type": "winner",
        },
    )
    assert resp.status_code == 400
    assert "resolution" in resp.json()["error"].lower()


def test_resolve_valid_passes_through():
    client, engine = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution_type": "dismissed",
            "resolution": "These refer to different things",
        },
    )
    assert resp.status_code == 200
    engine.resolve.assert_called_once()


def test_resolve_accepts_deprecated_winning_fact_id():
    client, engine = _build_client(
        resolve_result={
            "resolved": True,
            "conflict_id": "abc123",
            "resolution_type": "winner",
            "winning_claim_id": "fact-123",
        }
    )
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution_type": "winner",
            "resolution": "fact-123 is correct",
            "winning_fact_id": "fact-123",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["winning_claim_id"] == "fact-123"
    assert data["tool_surface_version"] == "1.0.0"
    assert data["deprecation_warnings"][0]["parameter"] == "winning_fact_id"
    engine.resolve.assert_called_once_with(
        conflict_id="abc123",
        resolution_type="winner",
        resolution="fact-123 is correct",
        winning_claim_id="fact-123",
    )


def test_resolve_rejects_both_winning_claim_id_and_winning_fact_id():
    client, engine = _build_client()
    resp = client.post(
        "/api/resolve",
        json={
            "conflict_id": "abc123",
            "resolution_type": "winner",
            "resolution": "pick one winner",
            "winning_claim_id": "claim-123",
            "winning_fact_id": "fact-123",
        },
    )

    assert resp.status_code == 400
    assert "Provide only one" in resp.json()["error"]
    engine.resolve.assert_not_called()


def test_resolve_invalid_json():
    client, _ = _build_client()
    resp = client.post("/api/resolve", content=b"bad", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


# ── /api/batch-commit validation ─────────────────────────────────────


_BATCH_RESULT = {
    "total": 2,
    "committed": 2,
    "duplicates": 0,
    "failed": 0,
    "results": [
        {"index": 0, "status": "ok", "fact_id": "f1", "duplicate": False},
        {"index": 1, "status": "ok", "fact_id": "f2", "duplicate": False},
    ],
}

_VALID_FACTS = [
    {"content": "Redis latency is 2ms", "scope": "infra", "confidence": 0.9},
    {"content": "DB pool is 20 connections", "scope": "infra", "confidence": 0.85},
]


def _build_batch_client():
    engine = MagicMock()
    engine.commit = AsyncMock(return_value={"fact_id": "abc", "duplicate": False})
    engine.query = AsyncMock(return_value=[])
    engine.get_conflicts = AsyncMock(return_value=[])
    engine.resolve = AsyncMock(return_value={"resolved": True})
    engine.batch_commit = AsyncMock(return_value=_BATCH_RESULT)
    engine.get_stats = AsyncMock(return_value={"facts": {}, "conflicts": {}, "agents": {}})
    engine.record_feedback = AsyncMock(
        return_value={"recorded": True, "conflict_id": "c1", "feedback": "true_positive"}
    )
    engine.get_timeline = AsyncMock(return_value=[])
    engine.get_agents = AsyncMock(return_value=[])
    engine.list_facts = AsyncMock(return_value=[])
    engine.get_fact = AsyncMock(return_value=None)
    engine.get_lineage = AsyncMock(return_value=[])
    engine.get_expiring_facts = AsyncMock(return_value=[])
    engine.bulk_dismiss = AsyncMock(
        return_value={"total": 0, "dismissed": 0, "failed": 0, "results": []}
    )
    storage = MagicMock()
    storage.count_facts = AsyncMock(return_value=10)
    storage.count_conflicts = AsyncMock(return_value=2)
    routes = build_rest_routes(engine, storage, auth_enabled=False, rate_limiter=None)
    app = Starlette(routes=routes)
    return TestClient(app, raise_server_exceptions=False), engine


def test_batch_commit_missing_facts():
    client, _ = _build_batch_client()
    resp = client.post("/api/batch-commit", json={"agent_id": "bot"})
    assert resp.status_code == 400
    assert "facts" in resp.json()["error"].lower()


def test_batch_commit_facts_not_list():
    client, _ = _build_batch_client()
    resp = client.post("/api/batch-commit", json={"facts": "not a list"})
    assert resp.status_code == 400
    assert "array" in resp.json()["error"].lower()


def test_batch_commit_empty_list():
    client, _ = _build_batch_client()
    resp = client.post("/api/batch-commit", json={"facts": []})
    assert resp.status_code == 400
    assert "at least one" in resp.json()["error"].lower()


def test_batch_commit_too_many_facts():
    client, _ = _build_batch_client()
    facts = [{"content": f"fact {i}", "scope": "s", "confidence": 0.9} for i in range(101)]
    resp = client.post("/api/batch-commit", json={"facts": facts})
    assert resp.status_code == 400
    assert "100" in resp.json()["error"]


def test_batch_commit_fact_missing_content():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit",
        json={
            "facts": [
                {"scope": "infra", "confidence": 0.9},
            ]
        },
    )
    assert resp.status_code == 400
    assert "content" in resp.json()["error"].lower()


def test_batch_commit_fact_whitespace_content():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit",
        json={
            "facts": [
                {"content": "   ", "scope": "infra", "confidence": 0.9},
            ]
        },
    )
    assert resp.status_code == 400
    assert "content" in resp.json()["error"].lower()


def test_batch_commit_fact_missing_scope():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit",
        json={
            "facts": [
                {"content": "latency is 2ms", "confidence": 0.9},
            ]
        },
    )
    assert resp.status_code == 400
    assert "scope" in resp.json()["error"].lower()


def test_batch_commit_fact_missing_confidence():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit",
        json={
            "facts": [
                {"content": "latency is 2ms", "scope": "infra"},
            ]
        },
    )
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_batch_commit_fact_confidence_out_of_range():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit",
        json={
            "facts": [
                {"content": "latency is 2ms", "scope": "infra", "confidence": 1.5},
            ]
        },
    )
    assert resp.status_code == 400
    assert "confidence" in resp.json()["error"].lower()


def test_batch_commit_fact_not_object():
    client, _ = _build_batch_client()
    resp = client.post("/api/batch-commit", json={"facts": ["not an object"]})
    assert resp.status_code == 400
    assert "object" in resp.json()["error"].lower()


def test_batch_commit_success():
    client, engine = _build_batch_client()
    resp = client.post("/api/batch-commit", json={"facts": _VALID_FACTS, "agent_id": "bot-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["committed"] == 2
    assert data["failed"] == 0
    engine.batch_commit.assert_called_once_with(
        facts=_VALID_FACTS, default_agent_id="bot-1", default_engineer=None
    )


def test_batch_commit_invalid_json():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/batch-commit", content=b"bad", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


def test_batch_commit_partial_failure_propagated():
    """Engine-level per-fact errors are returned in the response body, not as HTTP errors."""
    partial_result = {
        "total": 2,
        "committed": 1,
        "duplicates": 0,
        "failed": 1,
        "results": [
            {"index": 0, "status": "ok", "fact_id": "f1", "duplicate": False},
            {"index": 1, "status": "error", "error": "corrects_lineage not found"},
        ],
    }
    engine = MagicMock()
    engine.batch_commit = AsyncMock(return_value=partial_result)
    engine.get_stats = AsyncMock(return_value={})
    storage = MagicMock()
    routes = build_rest_routes(engine, storage)
    app = Starlette(routes=routes)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/batch-commit", json={"facts": _VALID_FACTS})
    assert resp.status_code == 200
    data = resp.json()
    assert data["failed"] == 1
    assert data["results"][1]["status"] == "error"


# ── /api/stats ────────────────────────────────────────────────────────


_STATS_RESULT = {
    "facts": {
        "total": 42,
        "current": 38,
        "expiring_soon": 3,
        "by_scope": {"infra": 20, "auth": 18, "frontend": 4},
        "by_type": {"observation": 30, "inference": 8, "decision": 4},
        "by_durability": {"durable": 40, "ephemeral": 2},
    },
    "conflicts": {
        "by_status": {"open": 2, "resolved": 5, "dismissed": 1},
        "by_tier": {"tier0_entity": 4, "tier1_nli": 3, "tier2_numeric": 1},
    },
    "agents": {
        "total": 3,
        "most_active": [{"agent_id": "bot-1", "fact_count": 20}],
        "avg_trust_score": 0.87,
    },
}


def test_stats_returns_workspace_data():
    client, engine = _build_batch_client()
    engine.get_stats = AsyncMock(return_value=_STATS_RESULT)
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["facts"]["total"] == 42
    assert data["conflicts"]["by_status"]["open"] == 2
    assert data["agents"]["total"] == 3


def test_stats_called_without_params():
    client, engine = _build_batch_client()
    engine.get_stats = AsyncMock(return_value=_STATS_RESULT)
    client.get("/api/stats")
    engine.get_stats.assert_called_once()


def test_stats_engine_error_returns_500():
    engine = MagicMock()
    engine.batch_commit = AsyncMock(return_value={})
    engine.get_stats = AsyncMock(side_effect=RuntimeError("db down"))
    engine.record_feedback = AsyncMock(return_value={})
    engine.get_timeline = AsyncMock(return_value=[])
    engine.get_agents = AsyncMock(return_value=[])
    storage = MagicMock()
    storage.count_facts = AsyncMock(return_value=0)
    storage.count_conflicts = AsyncMock(return_value=0)
    routes = build_rest_routes(engine, storage)
    app = Starlette(routes=routes)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/stats")
    assert resp.status_code == 500
    assert "error" in resp.json()


# ── /api/feedback validation ──────────────────────────────────────────


def test_feedback_missing_conflict_id():
    client, _ = _build_batch_client()
    resp = client.post("/api/feedback", json={"feedback": "true_positive"})
    assert resp.status_code == 400
    assert "conflict_id" in resp.json()["error"].lower()


def test_feedback_missing_feedback():
    client, _ = _build_batch_client()
    resp = client.post("/api/feedback", json={"conflict_id": "c123"})
    assert resp.status_code == 400
    assert "feedback" in resp.json()["error"].lower()


def test_feedback_invalid_feedback_value():
    client, _ = _build_batch_client()
    resp = client.post("/api/feedback", json={"conflict_id": "c123", "feedback": "maybe"})
    assert resp.status_code == 400
    assert "feedback" in resp.json()["error"].lower()


def test_feedback_valid_true_positive():
    client, engine = _build_batch_client()
    engine.record_feedback = AsyncMock(
        return_value={"recorded": True, "conflict_id": "c123", "feedback": "true_positive"}
    )
    resp = client.post("/api/feedback", json={"conflict_id": "c123", "feedback": "true_positive"})
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    engine.record_feedback.assert_called_once_with(conflict_id="c123", feedback="true_positive")


def test_feedback_valid_false_positive():
    client, engine = _build_batch_client()
    engine.record_feedback = AsyncMock(
        return_value={"recorded": True, "conflict_id": "c123", "feedback": "false_positive"}
    )
    resp = client.post("/api/feedback", json={"conflict_id": "c123", "feedback": "false_positive"})
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "false_positive"


def test_feedback_conflict_not_found_returns_400():
    client, engine = _build_batch_client()
    engine.record_feedback = AsyncMock(side_effect=ValueError("Conflict 'xyz' not found."))
    resp = client.post("/api/feedback", json={"conflict_id": "xyz", "feedback": "true_positive"})
    assert resp.status_code == 400
    assert "not found" in resp.json()["error"].lower()


def test_feedback_invalid_json():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/feedback", content=b"bad", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


# ── /api/timeline ─────────────────────────────────────────────────────


_TIMELINE_RESULT = [
    {
        "id": "f1",
        "content": "Redis latency is 2ms",
        "scope": "infra",
        "valid_from": "2024-01-01T00:00:00+00:00",
    },
    {
        "id": "f2",
        "content": "DB pool is 20",
        "scope": "infra",
        "valid_from": "2024-01-02T00:00:00+00:00",
    },
]


def test_timeline_returns_facts():
    client, engine = _build_batch_client()
    engine.get_timeline = AsyncMock(return_value=_TIMELINE_RESULT)
    resp = client.get("/api/timeline")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_timeline_passes_scope_param():
    client, engine = _build_batch_client()
    engine.get_timeline = AsyncMock(return_value=[])
    client.get("/api/timeline?scope=infra&limit=10")
    engine.get_timeline.assert_called_once_with(scope="infra", limit=10)


def test_timeline_default_limit():
    client, engine = _build_batch_client()
    engine.get_timeline = AsyncMock(return_value=[])
    client.get("/api/timeline")
    engine.get_timeline.assert_called_once_with(scope=None, limit=50)


def test_timeline_engine_error_returns_500():
    client, engine = _build_batch_client()
    engine.get_timeline = AsyncMock(side_effect=RuntimeError("boom"))
    resp = client.get("/api/timeline")
    assert resp.status_code == 500
    assert "error" in resp.json()


# ── /api/agents ───────────────────────────────────────────────────────


_AGENTS_RESULT = [
    {"agent_id": "bot-1", "engineer": "alice", "total_commits": 42, "flagged_commits": 2},
    {"agent_id": "bot-2", "engineer": "bob", "total_commits": 15, "flagged_commits": 0},
]


def test_agents_returns_list():
    client, engine = _build_batch_client()
    engine.get_agents = AsyncMock(return_value=_AGENTS_RESULT)
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["agent_id"] == "bot-1"


def test_agents_empty_workspace():
    client, engine = _build_batch_client()
    engine.get_agents = AsyncMock(return_value=[])
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_agents_engine_error_returns_500():
    client, engine = _build_batch_client()
    engine.get_agents = AsyncMock(side_effect=RuntimeError("db down"))
    resp = client.get("/api/agents")
    assert resp.status_code == 500
    assert "error" in resp.json()


# ── /api/health ───────────────────────────────────────────────────────


def test_health_returns_ok():
    client, _ = _build_batch_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "facts" in data
    assert "open_conflicts" in data


def test_health_returns_counts():
    client, engine = _build_batch_client()
    client.app.state  # touch state
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["facts"], int)
    assert isinstance(data["open_conflicts"], int)


def test_health_degraded_on_storage_error():
    engine = MagicMock()
    engine.batch_commit = AsyncMock(return_value={})
    engine.get_stats = AsyncMock(return_value={})
    engine.record_feedback = AsyncMock(return_value={})
    engine.get_timeline = AsyncMock(return_value=[])
    engine.get_agents = AsyncMock(return_value=[])
    engine.list_facts = AsyncMock(return_value=[])
    engine.get_fact = AsyncMock(return_value=None)
    engine.get_lineage = AsyncMock(return_value=[])
    engine.get_expiring_facts = AsyncMock(return_value=[])
    engine.bulk_dismiss = AsyncMock(return_value={})
    storage = MagicMock()
    storage.count_facts = AsyncMock(side_effect=RuntimeError("db down"))
    storage.count_conflicts = AsyncMock(return_value=0)
    routes = build_rest_routes(engine, storage)
    app = Starlette(routes=routes)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


# ── /api/facts ────────────────────────────────────────────────────────

_FACT_ROW = {
    "id": "f1",
    "content": "Redis latency is 2ms",
    "scope": "infra",
    "confidence": 0.9,
    "fact_type": "observation",
}


def test_facts_returns_list():
    client, engine = _build_batch_client()
    engine.list_facts = AsyncMock(return_value=[_FACT_ROW])
    resp = client.get("/api/facts")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_facts_passes_scope_and_type():
    client, engine = _build_batch_client()
    engine.list_facts = AsyncMock(return_value=[])
    client.get("/api/facts?scope=infra&fact_type=observation&limit=20")
    engine.list_facts.assert_called_once_with(scope="infra", fact_type="observation", limit=20)


def test_facts_invalid_fact_type():
    client, _ = _build_batch_client()
    resp = client.get("/api/facts?fact_type=random")
    assert resp.status_code == 400
    assert "fact_type" in resp.json()["error"].lower()


def test_facts_engine_error_returns_500():
    client, engine = _build_batch_client()
    engine.list_facts = AsyncMock(side_effect=RuntimeError("db down"))
    resp = client.get("/api/facts")
    assert resp.status_code == 500


# ── /api/facts/{fact_id} ──────────────────────────────────────────────


def test_fact_by_id_found():
    client, engine = _build_batch_client()
    engine.get_fact = AsyncMock(return_value=_FACT_ROW)
    resp = client.get("/api/facts/f1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "f1"


def test_fact_by_id_not_found():
    client, engine = _build_batch_client()
    engine.get_fact = AsyncMock(return_value=None)
    resp = client.get("/api/facts/nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


def test_fact_by_id_engine_error():
    client, engine = _build_batch_client()
    engine.get_fact = AsyncMock(side_effect=RuntimeError("boom"))
    resp = client.get("/api/facts/f1")
    assert resp.status_code == 500


# ── /api/lineage/{lineage_id} ─────────────────────────────────────────

_LINEAGE = [
    {"id": "f2", "content": "Redis latency is 1ms", "lineage_id": "lin1", "valid_until": None},
    {
        "id": "f1",
        "content": "Redis latency is 2ms",
        "lineage_id": "lin1",
        "valid_until": "2024-01-02T00:00:00+00:00",
    },
]


def test_lineage_returns_versions():
    client, engine = _build_batch_client()
    engine.get_lineage = AsyncMock(return_value=_LINEAGE)
    resp = client.get("/api/lineage/lin1")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_lineage_not_found_returns_404():
    client, engine = _build_batch_client()
    engine.get_lineage = AsyncMock(return_value=[])
    resp = client.get("/api/lineage/nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


def test_lineage_engine_error_returns_500():
    client, engine = _build_batch_client()
    engine.get_lineage = AsyncMock(side_effect=RuntimeError("boom"))
    resp = client.get("/api/lineage/lin1")
    assert resp.status_code == 500


# ── /api/expiring ─────────────────────────────────────────────────────

_EXPIRING = [
    {"id": "f1", "content": "cache TTL", "ttl_days": 3, "valid_until": "2024-01-04T00:00:00+00:00"}
]


def test_expiring_returns_facts():
    client, engine = _build_batch_client()
    engine.get_expiring_facts = AsyncMock(return_value=_EXPIRING)
    resp = client.get("/api/expiring")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_expiring_passes_days_ahead():
    client, engine = _build_batch_client()
    engine.get_expiring_facts = AsyncMock(return_value=[])
    client.get("/api/expiring?days_ahead=14")
    engine.get_expiring_facts.assert_called_once_with(days_ahead=14)


def test_expiring_default_days_ahead():
    client, engine = _build_batch_client()
    engine.get_expiring_facts = AsyncMock(return_value=[])
    client.get("/api/expiring")
    engine.get_expiring_facts.assert_called_once_with(days_ahead=7)


def test_expiring_engine_error_returns_500():
    client, engine = _build_batch_client()
    engine.get_expiring_facts = AsyncMock(side_effect=RuntimeError("boom"))
    resp = client.get("/api/expiring")
    assert resp.status_code == 500


# ── /api/conflicts/bulk-dismiss ───────────────────────────────────────

_BULK_RESULT = {
    "total": 2,
    "dismissed": 2,
    "failed": 0,
    "results": [
        {"conflict_id": "c1", "status": "dismissed"},
        {"conflict_id": "c2", "status": "dismissed"},
    ],
}


def test_bulk_dismiss_success():
    client, engine = _build_batch_client()
    engine.bulk_dismiss = AsyncMock(return_value=_BULK_RESULT)
    resp = client.post(
        "/api/conflicts/bulk-dismiss",
        json={
            "conflict_ids": ["c1", "c2"],
            "reason": "False positives after refactor",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dismissed"] == 2
    engine.bulk_dismiss.assert_called_once_with(
        conflict_ids=["c1", "c2"],
        reason="False positives after refactor",
        dismissed_by=None,
    )


def test_bulk_dismiss_missing_conflict_ids():
    client, _ = _build_batch_client()
    resp = client.post("/api/conflicts/bulk-dismiss", json={"reason": "cleanup"})
    assert resp.status_code == 400
    assert "conflict_ids" in resp.json()["error"].lower()


def test_bulk_dismiss_not_a_list():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/conflicts/bulk-dismiss", json={"conflict_ids": "c1", "reason": "cleanup"}
    )
    assert resp.status_code == 400
    assert "array" in resp.json()["error"].lower()


def test_bulk_dismiss_empty_list():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/conflicts/bulk-dismiss", json={"conflict_ids": [], "reason": "cleanup"}
    )
    assert resp.status_code == 400
    assert "at least one" in resp.json()["error"].lower()


def test_bulk_dismiss_too_many():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/conflicts/bulk-dismiss",
        json={
            "conflict_ids": [f"c{i}" for i in range(101)],
            "reason": "cleanup",
        },
    )
    assert resp.status_code == 400
    assert "100" in resp.json()["error"]


def test_bulk_dismiss_missing_reason():
    client, _ = _build_batch_client()
    resp = client.post("/api/conflicts/bulk-dismiss", json={"conflict_ids": ["c1"]})
    assert resp.status_code == 400
    assert "reason" in resp.json()["error"].lower()


def test_bulk_dismiss_whitespace_reason():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/conflicts/bulk-dismiss", json={"conflict_ids": ["c1"], "reason": "   "}
    )
    assert resp.status_code == 400
    assert "reason" in resp.json()["error"].lower()


def test_bulk_dismiss_partial_failure_in_body():
    partial = {
        "total": 2,
        "dismissed": 1,
        "failed": 1,
        "results": [
            {"conflict_id": "c1", "status": "dismissed"},
            {"conflict_id": "c2", "status": "skipped", "error": "not found or already resolved"},
        ],
    }
    client, engine = _build_batch_client()
    engine.bulk_dismiss = AsyncMock(return_value=partial)
    resp = client.post(
        "/api/conflicts/bulk-dismiss", json={"conflict_ids": ["c1", "c2"], "reason": "cleanup"}
    )
    assert resp.status_code == 200
    assert resp.json()["failed"] == 1


def test_bulk_dismiss_invalid_json():
    client, _ = _build_batch_client()
    resp = client.post(
        "/api/conflicts/bulk-dismiss", content=b"bad", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


# ── Round 8: /api/webhooks ────────────────────────────────────────────


def test_create_webhook_success():
    client, engine = _build_client()
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["fact.committed"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["webhook_id"] == "wh1"
    engine.create_webhook.assert_called_once()


def test_create_webhook_missing_url():
    client, _ = _build_client()
    resp = client.post("/api/webhooks", json={"events": ["fact.committed"]})
    assert resp.status_code == 400
    assert "url" in resp.json()["error"].lower()


def test_create_webhook_invalid_url():
    client, _ = _build_client()
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "ftp://bad.url",
            "events": ["fact.committed"],
        },
    )
    assert resp.status_code == 400
    assert "url" in resp.json()["error"].lower()


def test_create_webhook_missing_events():
    client, _ = _build_client()
    resp = client.post("/api/webhooks", json={"url": "https://example.com/hook"})
    assert resp.status_code == 400
    assert "events" in resp.json()["error"].lower()


def test_create_webhook_empty_events():
    client, _ = _build_client()
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": [],
        },
    )
    assert resp.status_code == 400
    assert "events" in resp.json()["error"].lower()


def test_list_webhooks_success():
    client, engine = _build_client()
    engine.list_webhooks = AsyncMock(
        return_value=[
            {
                "webhook_id": "wh1",
                "url": "https://x.com",
                "events": ["fact.committed"],
                "created_at": "2024-01-01T00:00:00+00:00",
            },
        ]
    )
    resp = client.get("/api/webhooks")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_webhook_success():
    client, engine = _build_client()
    resp = client.delete("/api/webhooks/wh1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_webhook_not_found():
    client, engine = _build_client()
    engine.delete_webhook = AsyncMock(side_effect=ValueError("Webhook 'wh_miss' not found."))
    resp = client.delete("/api/webhooks/wh_miss")
    assert resp.status_code == 404


# ── Round 8: /api/rules ───────────────────────────────────────────────


def test_create_rule_success():
    client, engine = _build_client()
    resp = client.post(
        "/api/rules",
        json={
            "scope_prefix": "auth",
            "condition_type": "latest_wins",
            "condition_value": "",
            "resolution_type": "winner",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rule_id"] == "r1"


def test_create_rule_invalid_condition():
    client, _ = _build_client()
    resp = client.post(
        "/api/rules",
        json={
            "scope_prefix": "auth",
            "condition_type": "magic_rule",
            "condition_value": "0.5",
        },
    )
    assert resp.status_code == 400
    assert "condition_type" in resp.json()["error"].lower()


def test_create_rule_missing_scope_prefix():
    client, _ = _build_client()
    resp = client.post(
        "/api/rules",
        json={
            "condition_type": "latest_wins",
            "condition_value": "",
        },
    )
    assert resp.status_code == 400
    assert "scope_prefix" in resp.json()["error"].lower()


def test_list_rules_success():
    client, engine = _build_client()
    engine.list_rules = AsyncMock(
        return_value=[
            {"id": "r1", "scope_prefix": "auth", "condition_type": "latest_wins"},
        ]
    )
    resp = client.get("/api/rules")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_rule_success():
    client, engine = _build_client()
    resp = client.delete("/api/rules/r1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_rule_not_found():
    client, engine = _build_client()
    engine.delete_rule = AsyncMock(side_effect=ValueError("Rule 'r_miss' not found."))
    resp = client.delete("/api/rules/r_miss")
    assert resp.status_code == 404


# ── Round 8: /api/export and /api/import ─────────────────────────────


def test_export_returns_facts():
    client, engine = _build_client()
    engine.export_workspace = AsyncMock(
        return_value={
            "facts": [{"id": "f1", "content": "test fact", "scope": "auth", "confidence": 0.9}],
            "metadata": {"workspace_id": "local", "exported_at": "2026-01-01T00:00:00Z"},
        }
    )
    resp = client.get("/api/export")
    assert resp.status_code == 200
    data = resp.json()
    assert "facts" in data or isinstance(data, dict)


def test_export_with_scope_filter():
    client, engine = _build_client()
    engine.export_workspace = AsyncMock(return_value={"facts": [], "metadata": {}})
    resp = client.get("/api/export?scope=auth&format=json")
    assert resp.status_code == 200
    engine.export_workspace.assert_called_once_with(format="json", scope="auth")


def test_import_success():
    client, engine = _build_client()
    engine.import_workspace = AsyncMock(
        return_value={"total": 1, "imported": 1, "duplicates": 0, "failed": 0}
    )
    resp = client.post(
        "/api/import", json={"facts": [{"content": "test", "scope": "auth", "confidence": 0.9}]}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1


def test_import_invalid_data():
    client, _ = _build_client()
    resp = client.post("/api/import", json={"facts": "not-a-list"})
    assert resp.status_code == 400
    assert "array" in resp.json()["error"].lower()


def test_import_missing_facts():
    client, _ = _build_client()
    resp = client.post("/api/import", json={})
    assert resp.status_code == 400
    assert "facts" in resp.json()["error"].lower()


# ── Round 8: /api/scopes ─────────────────────────────────────────────


def test_register_scope_success():
    client, engine = _build_client()
    resp = client.post("/api/scopes", json={"scope": "auth", "description": "Auth scope"})
    assert resp.status_code == 201
    assert resp.json()["scope"] == "auth"


def test_register_scope_missing_scope():
    client, _ = _build_client()
    resp = client.post("/api/scopes", json={"description": "no scope"})
    assert resp.status_code == 400
    assert "scope" in resp.json()["error"].lower()


def test_list_scopes_success():
    client, engine = _build_client()
    engine.list_scopes = AsyncMock(
        return_value=[
            {"scope": "auth", "description": "Auth scope", "workspace_id": "local"},
        ]
    )
    resp = client.get("/api/scopes")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_scope_success():
    client, engine = _build_client()
    resp = client.get("/api/scopes/auth")
    assert resp.status_code == 200
    data = resp.json()
    assert "analytics" in data


def test_get_scope_not_found():
    client, engine = _build_client()
    engine.get_scope_info = AsyncMock(return_value=None)
    resp = client.get("/api/scopes/nonexistent")
    assert resp.status_code == 404


# ── Round 8: /api/diff ────────────────────────────────────────────────


def test_diff_success():
    client, engine = _build_client()
    engine.diff_facts = AsyncMock(
        return_value={
            "fact_a": {"id": "f1", "content": "old", "scope": "auth", "confidence": 0.7},
            "fact_b": {"id": "f2", "content": "new", "scope": "auth", "confidence": 0.9},
            "changes": [{"field": "content", "old": "old", "new": "new"}],
            "entity_changes": {"added": [], "removed": [], "changed": []},
        }
    )
    resp = client.get("/api/diff/f1/f2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["changes"]) == 1
    assert data["changes"][0]["field"] == "content"


def test_diff_fact_not_found():
    client, engine = _build_client()
    engine.diff_facts = AsyncMock(side_effect=ValueError("Fact 'missing' not found."))
    resp = client.get("/api/diff/missing/f2")
    assert resp.status_code == 404


# ── Round 8: /api/audit ───────────────────────────────────────────────


def test_audit_returns_log():
    client, engine = _build_client()
    engine.get_audit_log = AsyncMock(
        return_value=[
            {
                "id": "a1",
                "operation": "commit",
                "agent_id": "agent-1",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
        ]
    )
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["operation"] == "commit"


def test_audit_with_filters():
    client, engine = _build_client()
    engine.get_audit_log = AsyncMock(return_value=[])
    resp = client.get("/api/audit?agent_id=agent-1&operation=commit&limit=50")
    assert resp.status_code == 200
    engine.get_audit_log.assert_called_once_with(
        agent_id="agent-1",
        operation="commit",
        from_ts=None,
        to_ts=None,
        limit=50,
    )


def test_audit_empty_returns_list():
    client, _ = _build_client()
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
