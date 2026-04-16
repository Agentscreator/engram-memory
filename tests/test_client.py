"""Tests for the Engram REST client."""

from __future__ import annotations

import json
import urllib.error

import pytest

from engram.client import EngramClient, EngramClientError


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_client_query_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return DummyResponse([{"content": "Auth uses JWT", "scope": "auth"}])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = EngramClient(base_url="http://engram.local/", api_key="ek_test", timeout=5)
    result = client.query("auth tokens", scope="auth", limit=3, agent_id="agent-1")

    assert result == [{"content": "Auth uses JWT", "scope": "auth"}]
    assert captured["url"] == "http://engram.local/api/query"
    assert captured["method"] == "POST"
    assert captured["payload"] == {
        "topic": "auth tokens",
        "limit": 3,
        "scope": "auth",
        "agent_id": "agent-1",
    }
    assert captured["headers"]["Authorization"] == "Bearer ek_test"
    assert captured["timeout"] == 5


def test_client_commit_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse({"fact_id": "fact-1", "duplicate": False})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = EngramClient().commit(
        "Auth uses JWT",
        scope="auth",
        confidence=0.9,
        fact_type="decision",
        provenance="docs/auth.md",
    )

    assert result == {"fact_id": "fact-1", "duplicate": False}
    assert captured["url"] == "http://127.0.0.1:7474/api/commit"
    assert captured["method"] == "POST"
    assert captured["payload"] == {
        "content": "Auth uses JWT",
        "scope": "auth",
        "confidence": 0.9,
        "fact_type": "decision",
        "operation": "add",
        "provenance": "docs/auth.md",
    }


def test_client_batch_commit_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse({"committed": 1, "duplicates": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    facts = [{"content": "Auth uses JWT", "scope": "auth", "confidence": 0.8}]
    result = EngramClient().batch_commit(facts, agent_id="agent-1")

    assert result == {"committed": 1, "duplicates": 0}
    assert captured["url"] == "http://127.0.0.1:7474/api/batch-commit"
    assert captured["payload"] == {"facts": facts, "agent_id": "agent-1"}


def test_client_conflicts_gets_expected_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return DummyResponse([{"id": "conflict-1"}])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = EngramClient().conflicts(scope="auth", status="resolved")

    assert result == [{"id": "conflict-1"}]
    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:7474/api/conflicts?status=resolved&scope=auth"


def test_client_raises_api_error(monkeypatch):
    def fake_urlopen(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=DummyErrorBody({"error": "content is required"}),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(EngramClientError, match="content is required"):
        EngramClient().commit("", scope="auth")


class DummyErrorBody:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        return None
