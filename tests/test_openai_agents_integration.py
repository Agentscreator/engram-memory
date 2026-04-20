"""Tests for the optional OpenAI Agents SDK integration."""

from __future__ import annotations

from typing import Any

import pytest

from engram.integrations import openai_agents


class FakeClient:
    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self.commits: list[dict[str, Any]] = []
        self.conflict_requests: list[dict[str, Any]] = []

    def query(self, topic, *, scope=None, limit=10):
        self.queries.append({"topic": topic, "scope": scope, "limit": limit})
        return [{"content": "Auth uses JWT", "scope": scope or "general"}]

    def commit(self, content, **kwargs):
        self.commits.append({"content": content, **kwargs})
        return {"fact_id": "fact-1", "duplicate": False}

    def conflicts(self, *, scope=None, status="open"):
        self.conflict_requests.append({"scope": scope, "status": status})
        return [{"id": "conflict-1", "status": status}]


def identity_tool(func):
    func.is_test_tool = True
    return func


def _tools_by_name(client=None, **kwargs):
    tools = openai_agents.create_engram_tools(
        client=client or FakeClient(),
        tool_decorator=identity_tool,
        **kwargs,
    )
    return {tool.__name__: tool for tool in tools}


def test_create_engram_tools_returns_expected_tool_names():
    tools = _tools_by_name()

    assert set(tools) == {"engram_query", "engram_commit", "engram_conflicts"}
    assert all(tool.is_test_tool for tool in tools.values())


def test_query_tool_calls_client_with_default_scope():
    client = FakeClient()
    tools = _tools_by_name(client=client, default_scope="auth")

    result = tools["engram_query"]("How does auth work?", limit=3)

    assert result == [{"content": "Auth uses JWT", "scope": "auth"}]
    assert client.queries == [{"topic": "How does auth work?", "scope": "auth", "limit": 3}]


def test_query_tool_explicit_scope_overrides_default_scope():
    client = FakeClient()
    tools = _tools_by_name(client=client, default_scope="auth")

    tools["engram_query"]("How does billing work?", scope="billing")

    assert client.queries == [{"topic": "How does billing work?", "scope": "billing", "limit": 10}]


def test_commit_tool_calls_client_with_verified_fact_payload():
    client = FakeClient()
    tools = _tools_by_name(client=client, default_scope="auth")

    result = tools["engram_commit"](
        "Auth validates JWTs on every request",
        confidence=0.9,
        fact_type="decision",
        provenance="docs/auth.md",
    )

    assert result == {"fact_id": "fact-1", "duplicate": False}
    assert client.commits == [
        {
            "content": "Auth validates JWTs on every request",
            "scope": "auth",
            "confidence": 0.9,
            "fact_type": "decision",
            "provenance": "docs/auth.md",
        }
    ]


def test_commit_tool_explicit_scope_overrides_default_scope():
    client = FakeClient()
    tools = _tools_by_name(client=client, default_scope="auth")

    tools["engram_commit"]("Billing retries webhooks.", scope="billing")

    assert client.commits[0]["scope"] == "billing"


def test_conflicts_tool_calls_client():
    client = FakeClient()
    tools = _tools_by_name(client=client, default_scope="auth")

    result = tools["engram_conflicts"](status="resolved")

    assert result == [{"id": "conflict-1", "status": "resolved"}]
    assert client.conflict_requests == [{"scope": "auth", "status": "resolved"}]


def test_factory_builds_client_from_connection_options(monkeypatch):
    created: dict[str, Any] = {}

    class RecordingClient(FakeClient):
        def __init__(self, base_url, *, api_key=None, timeout=30.0):
            super().__init__()
            created["base_url"] = base_url
            created["api_key"] = api_key
            created["timeout"] = timeout

    monkeypatch.setattr(openai_agents, "EngramClient", RecordingClient)

    tools = openai_agents.create_engram_tools(
        base_url="http://engram.local",
        api_key="ek_test",
        timeout=3.0,
        tool_decorator=identity_tool,
    )

    query_tool = {tool.__name__: tool for tool in tools}["engram_query"]
    query_tool("anything")

    assert created == {
        "base_url": "http://engram.local",
        "api_key": "ek_test",
        "timeout": 3.0,
    }


def test_missing_openai_agents_sdk_error_is_actionable(monkeypatch):
    monkeypatch.setattr(openai_agents, "_function_tool", None)
    monkeypatch.setattr(openai_agents, "_OPENAI_AGENTS_IMPORT_ERROR", ImportError("missing"))

    with pytest.raises(ImportError, match="pip install openai-agents"):
        openai_agents.create_engram_tools(client=FakeClient())
