"""Tests for the optional LangChain adapter."""

from __future__ import annotations

import pytest

from engram.integrations import langchain as langchain_adapter
from engram.integrations.langchain import format_facts


class FakeClient:
    def __init__(self):
        self.queries = []
        self.commits = []

    def query(self, topic, *, scope=None, limit=10):
        self.queries.append({"topic": topic, "scope": scope, "limit": limit})
        return [
            {
                "content": "Auth uses JWT session tokens",
                "scope": "auth",
                "effective_confidence": 0.91,
            }
        ]

    def commit(self, content, **kwargs):
        self.commits.append({"content": content, **kwargs})
        return {"fact_id": "fact-1", "duplicate": False}


def test_format_facts_includes_scope_content_and_confidence():
    output = format_facts(
        [
            {
                "content": "Auth uses JWT",
                "scope": "auth",
                "effective_confidence": 0.91,
            }
        ]
    )

    assert output == "- [auth] Auth uses JWT (confidence: 0.91)"


def test_format_facts_handles_empty_results():
    assert format_facts([]) == "No Engram memory found."


def test_memory_loads_variables_when_langchain_available():
    client = FakeClient()
    memory = langchain_adapter.EngramMemory(
        client=client,
        scope="auth",
        memory_key="team_memory",
        input_key="question",
        limit=2,
    )

    result = memory.load_memory_variables({"question": "How does auth work?"})

    assert result == {"team_memory": "- [auth] Auth uses JWT session tokens (confidence: 0.91)"}
    assert client.queries == [{"topic": "How does auth work?", "scope": "auth", "limit": 2}]


def test_memory_can_build_client_from_connection_options():
    memory = langchain_adapter.EngramMemory(
        base_url="http://engram.local",
        api_key="ek_test",
        timeout=3.0,
    )

    assert memory.client.base_url == "http://engram.local"
    assert memory.client.api_key == "ek_test"
    assert memory.client.timeout == 3.0


def test_memory_save_context_does_not_commit_when_langchain_available():
    client = FakeClient()
    memory = langchain_adapter.EngramMemory(client=client, scope="auth")

    memory.save_context({"input": "remember this"}, {"output": "ok"})

    assert client.commits == []


def test_memory_commit_fact_is_explicit_when_langchain_available():
    client = FakeClient()
    memory = langchain_adapter.EngramMemory(client=client, scope="auth")

    result = memory.commit_fact(
        "Auth uses JWT",
        confidence=0.9,
        provenance="docs/auth.md",
        agent_id="agent-1",
    )

    assert result == {"fact_id": "fact-1", "duplicate": False}
    assert client.commits == [
        {
            "content": "Auth uses JWT",
            "scope": "auth",
            "confidence": 0.9,
            "fact_type": "observation",
            "provenance": "docs/auth.md",
            "agent_id": "agent-1",
        }
    ]


def test_adapter_reports_whether_base_memory_is_available():
    assert isinstance(langchain_adapter.LANGCHAIN_BASE_MEMORY_AVAILABLE, bool)


def test_memory_uses_langchain_base_memory_when_available():
    if not langchain_adapter.LANGCHAIN_BASE_MEMORY_AVAILABLE:
        pytest.skip("installed LangChain does not expose BaseMemory")

    assert isinstance(langchain_adapter.EngramMemory(), langchain_adapter.BaseMemory)
