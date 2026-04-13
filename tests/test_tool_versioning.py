import pytest

from engram.server import engram_resolve, engram_status


@pytest.mark.asyncio
async def test_engram_status_exposes_tool_surface_metadata():
    result = await engram_status()

    assert "tool_surface_version" in result
    assert "supported_tool_major_versions" in result
    assert "deprecation_policy" in result


class DummyEngine:
    async def resolve(self, conflict_id, resolution_type, resolution, winning_claim_id=None):
        return {
            "resolved": True,
            "conflict_id": conflict_id,
            "resolution_type": resolution_type,
            "winning_claim_id": winning_claim_id,
        }


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
