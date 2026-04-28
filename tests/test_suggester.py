"""Tests for the LLM-powered conflict suggester."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch


from engram.suggester import _build_prompt, _fact_lines, _tier_label, generate_suggestion


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fact(id: str = "fact-a", content: str = "Port is 8080", **kwargs) -> dict:
    return {
        "id": id,
        "content": content,
        "scope": "backend",
        "confidence": 0.9,
        "fact_type": "observation",
        "committed_at": "2026-01-01T00:00:00+00:00",
        "agent_id": "agent-1",
        **kwargs,
    }


def _make_conflict(**kwargs) -> dict:
    return {
        "id": "conflict-1",
        "detection_tier": "tier2_numeric",
        "severity": "high",
        "explanation": "Port values differ",
        **kwargs,
    }


# ── _tier_label ───────────────────────────────────────────────────────────────


def test_tier_label_known_tier():
    assert "entity extraction" in _tier_label("tier0_entity")


def test_tier_label_unknown_tier_returns_raw():
    assert _tier_label("unknown_tier") == "unknown_tier"


def test_tier_label_all_known_tiers():
    known = [
        "tier0_entity",
        "tier1_nli",
        "tier2_numeric",
        "tier2b_cross_scope",
        "tier3_tkg_reversal",
        "tier4_codebase",
    ]
    for tier in known:
        assert _tier_label(tier) != tier


# ── _fact_lines ───────────────────────────────────────────────────────────────


def test_fact_lines_includes_required_fields():
    fact = _make_fact()
    lines = _fact_lines(fact)
    assert "fact-a" in lines
    assert "Port is 8080" in lines
    assert "backend" in lines
    assert "0.90" in lines


def test_fact_lines_includes_provenance_when_present():
    fact = _make_fact(provenance="scan:abc123")
    lines = _fact_lines(fact)
    assert "scan:abc123" in lines


def test_fact_lines_omits_provenance_when_absent():
    fact = _make_fact()
    lines = _fact_lines(fact)
    assert "provenance" not in lines


# ── _build_prompt ─────────────────────────────────────────────────────────────


def test_build_prompt_contains_both_facts():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()
    prompt = _build_prompt(fact_a, fact_b, conflict, None, None)
    assert "Port is 8080" in prompt
    assert "Port is 9090" in prompt


def test_build_prompt_includes_codebase_context():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()
    codebase = [{"entity": "PORT", "code_value": "8080", "source": ".env"}]
    prompt = _build_prompt(fact_a, fact_b, conflict, codebase, None)
    assert "CODEBASE GROUND TRUTH" in prompt
    assert "8080" in prompt
    assert "Fact A matches code" in prompt


def test_build_prompt_includes_tkg_context():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()
    tkg = [
        {
            "entity": "PORT",
            "timeline": [
                {
                    "created_at": "2026-01-01T00:00:00",
                    "agent_id": "agent-1",
                    "source": "PORT",
                    "relation": "has_value",
                    "target": "8080",
                    "is_active": True,
                }
            ],
        }
    ]
    prompt = _build_prompt(fact_a, fact_b, conflict, None, tkg)
    assert "TKG BELIEF HISTORY" in prompt
    assert "PORT" in prompt


def test_build_prompt_without_optional_context():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()
    prompt = _build_prompt(fact_a, fact_b, conflict, None, None)
    assert "CODEBASE GROUND TRUTH" not in prompt
    assert "TKG BELIEF HISTORY" not in prompt


def test_build_prompt_annotates_both_facts_match():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 8080 for staging")
    conflict = _make_conflict()
    codebase = [{"entity": "PORT", "code_value": "8080", "source": ".env"}]
    prompt = _build_prompt(fact_a, fact_b, conflict, codebase, None)
    assert "Both facts consistent" in prompt


# ── generate_suggestion ───────────────────────────────────────────────────────


async def test_generate_suggestion_returns_none_without_api_key():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()

    with patch.dict("os.environ", {}, clear=True):
        result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is None


async def test_generate_suggestion_returns_none_without_anthropic_package():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", side_effect=ImportError):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is None


async def test_generate_suggestion_returns_winner():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()

    llm_response = json.dumps(
        {
            "resolution_type": "winner",
            "winning_fact_id": "a",
            "suggested_resolution": "Fact A is correct per .env config.",
            "reasoning": "Codebase shows PORT=8080.",
        }
    )

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=llm_response)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", return_value=mock_client):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is not None
    assert result["suggested_resolution_type"] == "winner"
    assert result["suggested_winning_fact_id"] == "a"
    assert "suggestion_generated_at" in result


async def test_generate_suggestion_returns_merge():
    fact_a = _make_fact("a", "Port is 8080 in prod")
    fact_b = _make_fact("b", "Port is 9090 in staging")
    conflict = _make_conflict()

    llm_response = json.dumps(
        {
            "resolution_type": "merge",
            "winning_fact_id": None,
            "suggested_resolution": "Both are true in different environments.",
            "reasoning": "Different environments, both valid.",
        }
    )

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=llm_response)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", return_value=mock_client):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is not None
    assert result["suggested_resolution_type"] == "merge"
    assert result["suggested_winning_fact_id"] is None


async def test_generate_suggestion_falls_back_on_invalid_winning_id():
    fact_a = _make_fact("a", "Port is 8080", confidence=0.9)
    fact_b = _make_fact("b", "Port is 9090", confidence=0.5)
    conflict = _make_conflict()

    # LLM returns a winning_fact_id that is neither "a" nor "b"
    llm_response = json.dumps(
        {
            "resolution_type": "winner",
            "winning_fact_id": "nonexistent-id",
            "suggested_resolution": "Resolution.",
            "reasoning": "Some reasoning.",
        }
    )

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=llm_response)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", return_value=mock_client):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    # Falls back to higher confidence fact
    assert result["suggested_winning_fact_id"] == "a"


async def test_generate_suggestion_strips_markdown_fences():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()

    payload = {
        "resolution_type": "dismissed",
        "winning_fact_id": None,
        "suggested_resolution": "False positive.",
        "reasoning": "Different components.",
    }
    # Wrap in markdown fences like some models do
    llm_response = f"```json\n{json.dumps(payload)}\n```"

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=llm_response)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", return_value=mock_client):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is not None
    assert result["suggested_resolution_type"] == "dismissed"


async def test_generate_suggestion_returns_none_on_llm_exception():
    fact_a = _make_fact("a", "Port is 8080")
    fact_b = _make_fact("b", "Port is 9090")
    conflict = _make_conflict()

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("engram.suggester._get_suggester_client", return_value=mock_client):
            result = await generate_suggestion(fact_a, fact_b, conflict)

    assert result is None
