from types import SimpleNamespace

import pytest

from engram.server import engram_resolve, engram_status


@pytest.mark.asyncio
async def test_engram_status_exposes_tool_surface_metadata():
    result = await engram_status()

    assert "tool_surface_version" in result
    assert "supported_tool_major_versions" in result
    assert "deprecation_policy" in result


class DummyEngine:
    async def get_stats(self):
        return {
            "conflicts": {
                "open": 2,
                "resolved": 3,
                "dismissed": 1,
                "total": 6,
                "by_tier": {"tier1_nli": 4, "tier2_numeric": 2},
                "by_type": {"genuine": 5, "evolution": 1},
            }
        }

    async def resolve(self, conflict_id, resolution_type, resolution, winning_claim_id=None):
        return {
            "resolved": True,
            "conflict_id": conflict_id,
            "resolution_type": resolution_type,
            "winning_claim_id": winning_claim_id,
        }


class BrokenStatsEngine:
    async def get_stats(self):
        raise RuntimeError("stats unavailable")


@pytest.mark.asyncio
async def test_engram_resolve_accepts_deprecated_alias(monkeypatch):
    from engram import server

    monkeypatch.setattr(server, "_engine", DummyEngine())

    result = await engram_resolve(
        conflict_id="c1",
        resolution_type="winner",
        resolution="Resolved in favor of newer evidence.",
        winning_fact_id="fact-123",
    )

    assert result["resolved"] is True
    assert result["winning_claim_id"] == "fact-123"
    assert "deprecation_warnings" in result
    assert result["deprecation_warnings"][0]["parameter"] == "winning_fact_id"


@pytest.mark.asyncio
async def test_engram_resolve_current_param_has_no_warning(monkeypatch):
    from engram import server

    monkeypatch.setattr(server, "_engine", DummyEngine())

    result = await engram_resolve(
        conflict_id="c1",
        resolution_type="winner",
        resolution="Resolved in favor of newer evidence.",
        winning_claim_id="claim-123",
    )

    assert result["resolved"] is True
    assert result["winning_claim_id"] == "claim-123"
    assert "deprecation_warnings" not in result


@pytest.mark.asyncio
async def test_engram_status_exposes_conflict_detection_summary(monkeypatch, tmp_path):
    from engram import server, workspace

    marker = tmp_path / "workspace.json"
    marker.write_text("{}")
    ws = SimpleNamespace(
        db_url=None,
        engram_id="local",
        schema="engram",
        anonymous_mode=False,
        key_generation=0,
    )

    monkeypatch.setattr(server, "_engine", DummyEngine())
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_read_engram_env", lambda: None)
    monkeypatch.setattr(workspace, "read_workspace", lambda: ws)
    monkeypatch.setattr(workspace, "WORKSPACE_PATH", marker)

    result = await engram_status()

    assert result["status"] == "ready"
    assert result["conflict_detection"] == {
        "status": "available",
        "open": 2,
        "resolved": 3,
        "dismissed": 1,
        "total": 6,
        "by_tier": {"tier1_nli": 4, "tier2_numeric": 2},
        "by_type": {"genuine": 5, "evolution": 1},
    }
    assert "tool_surface_version" in result


@pytest.mark.asyncio
async def test_engram_status_keeps_ready_when_conflict_stats_unavailable(monkeypatch, tmp_path):
    from engram import server, workspace

    marker = tmp_path / "workspace.json"
    marker.write_text("{}")
    ws = SimpleNamespace(
        db_url=None,
        engram_id="local",
        schema="engram",
        anonymous_mode=False,
        key_generation=0,
    )

    monkeypatch.setattr(server, "_engine", BrokenStatsEngine())
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_read_engram_env", lambda: None)
    monkeypatch.setattr(workspace, "read_workspace", lambda: ws)
    monkeypatch.setattr(workspace, "WORKSPACE_PATH", marker)

    result = await engram_status()

    assert result["status"] == "ready"
    assert result["conflict_detection"] == {
        "status": "unavailable",
        "open": 0,
        "resolved": 0,
        "dismissed": 0,
        "total": 0,
        "by_tier": {},
        "by_type": {},
    }
