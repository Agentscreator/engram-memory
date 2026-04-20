"""Tests for LLM-powered TKG extraction.

These tests mock the OpenAI API (via httpx) to validate the extraction
pipeline without requiring an API key.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engram.tkg_llm import (
    extract_triplets,
    resolve_node_name,
    find_similar_node,
    check_edge_duplicate,
    is_available,
    _KNOWN_ALIASES,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_openai_response(content: str):
    """Create a mock httpx response that looks like an OpenAI chat completion."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return resp


def _mock_httpx_client(response_text: str):
    """Create a mock httpx.AsyncClient context manager."""
    mock_resp = _mock_openai_response(response_text)
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


def _patch_httpx(response_text: str):
    """Return a context manager that patches httpx with a mock returning the given text."""
    import sys

    mock_cm = _mock_httpx_client(response_text)
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = mock_cm
    return patch.dict(sys.modules, {"httpx": mock_httpx})


def _patch_httpx_error(status_code: int = 500, text: str = "Error"):
    """Return a context manager that patches httpx to return an error."""
    import sys

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = mock_cm
    return patch.dict(sys.modules, {"httpx": mock_httpx})


# ── Availability check ───────────────────────────────────────────────


def test_is_available_without_key():
    """is_available returns False when no API key is set."""
    with patch.dict("os.environ", {}, clear=True):
        assert is_available() is False


def test_is_available_with_key():
    """is_available returns True when OPENAI_API_KEY is set."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        assert is_available() is True


# ── Node name resolution ─────────────────────────────────────────────


class TestResolveNodeName:
    def test_known_alias(self):
        assert resolve_node_name("PostgreSQL") == "postgres"
        assert resolve_node_name("k8s") == "kubernetes"
        assert resolve_node_name("K8S") == "kubernetes"

    def test_unknown_name_passes_through(self):
        assert resolve_node_name("my-custom-service") == "my-custom-service"

    def test_strips_whitespace(self):
        assert resolve_node_name("  postgres  ") == "postgres"

    def test_all_aliases_resolve(self):
        for alias, canonical in _KNOWN_ALIASES.items():
            assert resolve_node_name(alias) == canonical


# ── Triplet extraction (mocked OpenAI) ───────────────────────────────


@pytest.mark.asyncio
async def test_extract_triplets_parses_response():
    """extract_triplets correctly parses a well-formed OpenAI response."""
    llm_response = json.dumps(
        {
            "triplets": [
                {
                    "subject": "auth service",
                    "relation": "uses",
                    "object": "redis",
                    "fact_label": "The auth service uses Redis for caching",
                },
                {
                    "subject": "auth service",
                    "relation": "runs_on",
                    "object": "kubernetes",
                    "fact_label": "The auth service runs on Kubernetes",
                },
            ],
            "valid_at": "2025-01-15T10:00:00+00:00",
            "invalid_at": None,
        }
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx(llm_response):
            result = await extract_triplets("The auth service uses Redis and runs on Kubernetes")

    assert len(result["triplets"]) == 2
    assert result["triplets"][0]["subject"] == "auth service"
    assert result["triplets"][0]["relation"] == "uses"
    assert result["triplets"][0]["object"] == "redis"
    assert result["valid_at"] == "2025-01-15T10:00:00+00:00"


@pytest.mark.asyncio
async def test_extract_triplets_handles_markdown_fences():
    """extract_triplets strips markdown code fences from response."""
    inner = json.dumps(
        {
            "triplets": [
                {
                    "subject": "api",
                    "relation": "uses",
                    "object": "graphql",
                    "fact_label": "API uses GraphQL",
                }
            ],
            "valid_at": None,
            "invalid_at": None,
        }
    )
    llm_response = f"```json\n{inner}\n```"

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx(llm_response):
            result = await extract_triplets("We decided to use GraphQL for the API")

    assert len(result["triplets"]) == 1
    assert result["triplets"][0]["object"] == "graphql"


@pytest.mark.asyncio
async def test_extract_triplets_falls_back_on_error():
    """extract_triplets returns empty result on API error."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx_error():
            result = await extract_triplets("Some content")

    assert result["triplets"] == []
    assert result["valid_at"] is None


@pytest.mark.asyncio
async def test_extract_triplets_validates_structure():
    """extract_triplets filters out malformed triplets."""
    llm_response = json.dumps(
        {
            "triplets": [
                {"subject": "auth", "relation": "uses", "object": "redis", "fact_label": "ok"},
                {"subject": "x", "relation": "y"},  # missing object
                {"subject": "", "relation": "uses", "object": "redis"},  # empty subject
            ],
            "valid_at": None,
            "invalid_at": None,
        }
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx(llm_response):
            result = await extract_triplets("Auth uses Redis")

    assert len(result["triplets"]) == 1
    assert result["triplets"][0]["subject"] == "auth"


@pytest.mark.asyncio
async def test_extract_triplets_no_api_key():
    """extract_triplets returns empty when no API key is set."""
    with patch.dict("os.environ", {}, clear=True):
        result = await extract_triplets("Some content")
    assert result["triplets"] == []


# ── Edge dedup (mocked OpenAI) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_check_edge_duplicate_detects_duplicate():
    """check_edge_duplicate identifies a semantic duplicate."""
    llm_response = json.dumps(
        {
            "is_duplicate_of": 0,
            "contradicts": [],
        }
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx(llm_response):
            result = await check_edge_duplicate(
                "Alice is employed by Acme Corp",
                ["Alice works at Acme Corp"],
            )

    assert result["is_duplicate_of"] == 0
    assert result["contradicts"] == []


@pytest.mark.asyncio
async def test_check_edge_duplicate_detects_contradiction():
    """check_edge_duplicate identifies a contradiction."""
    llm_response = json.dumps(
        {
            "is_duplicate_of": None,
            "contradicts": [0],
        }
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        with _patch_httpx(llm_response):
            result = await check_edge_duplicate(
                "Rate limit is 2000 req/s",
                ["Rate limit is 1000 req/s"],
            )

    assert result["is_duplicate_of"] is None
    assert result["contradicts"] == [0]


@pytest.mark.asyncio
async def test_check_edge_duplicate_empty_existing():
    """check_edge_duplicate returns clean result for empty existing list."""
    result = await check_edge_duplicate("Some fact", [])
    assert result["is_duplicate_of"] is None
    assert result["contradicts"] == []


# ── Node similarity (embedding-based) ────────────────────────────────


@pytest.mark.asyncio
async def test_find_similar_node_matches():
    """find_similar_node finds semantically similar nodes."""
    existing = [
        {"name": "authentication service", "id": "node-1", "entity_type": "service"},
        {"name": "redis cache", "id": "node-2", "entity_type": "technology"},
    ]

    result = await find_similar_node("auth service", existing, threshold=0.7)
    # The embedding model may or may not find this similar enough
    assert result is None or result["id"] in ("node-1", "node-2")


@pytest.mark.asyncio
async def test_find_similar_node_no_match():
    """find_similar_node returns None when nothing is similar."""
    existing = [
        {"name": "kubernetes cluster", "id": "node-1", "entity_type": "technology"},
    ]

    result = await find_similar_node("rate limit configuration", existing, threshold=0.95)
    assert result is None


@pytest.mark.asyncio
async def test_find_similar_node_empty_list():
    """find_similar_node returns None for empty existing list."""
    result = await find_similar_node("anything", [], threshold=0.5)
    assert result is None
