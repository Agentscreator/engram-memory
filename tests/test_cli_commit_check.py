from __future__ import annotations

import json

from click.testing import CliRunner

from engram.cli import main


def test_commit_check_requires_some_input():
    runner = CliRunner()
    result = runner.invoke(main, ["commit-check"])
    assert result.exit_code == 0
    assert "Nothing to scan" in result.output


def test_commit_check_json_output(monkeypatch):
    monkeypatch.setattr(
        "engram.cli.load_credentials",
        lambda cwd=None: ("http://127.0.0.1:7474", "ek_live_test"),
        raising=False,
    )
    monkeypatch.setattr(
        "engram.commit_check.load_credentials",
        lambda cwd=None: ("http://127.0.0.1:7474", "ek_live_test"),
    )
    monkeypatch.setattr(
        "engram.commit_check.query_workspace",
        lambda base_url, invite_key, topic, limit=5: [
            {
                "content": "Redis was rejected due to memory cost at scale.",
                "scope": "cache",
                "agent_id": "agent-cache",
                "confidence": 0.9,
                "relevance_score": 0.8,
                "committed_at": "2026-04-10T10:00:00Z",
            }
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["commit-check", "--message", "switch to Redis for session caching", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["matches_found"] == 1
    assert "switch to Redis" in payload["query"]


def test_commit_check_strict_mode_exits_nonzero(monkeypatch):
    monkeypatch.setattr(
        "engram.commit_check.load_credentials",
        lambda cwd=None: ("http://127.0.0.1:7474", "ek_live_test"),
    )
    monkeypatch.setattr(
        "engram.commit_check.query_workspace",
        lambda base_url, invite_key, topic, limit=5: [
            {
                "content": "Redis was rejected due to memory cost at scale.",
                "scope": "cache",
                "agent_id": "agent-cache",
                "confidence": 0.9,
                "relevance_score": 0.8,
                "committed_at": "2026-04-10T10:00:00Z",
            }
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["commit-check", "--message", "switch to Redis", "--strict"],
    )

    assert result.exit_code == 1
    assert "Strict mode enabled" in result.output


def test_commit_check_handles_query_failure(monkeypatch):
    monkeypatch.setattr(
        "engram.commit_check.load_credentials",
        lambda cwd=None: ("http://127.0.0.1:7474", "ek_live_test"),
    )

    def _boom(base_url, invite_key, topic, limit=5):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("engram.commit_check.query_workspace", _boom)

    runner = CliRunner()
    result = runner.invoke(main, ["commit-check", "--message", "switch auth provider"])

    assert result.exit_code == 0
    assert "Engram commit check skipped" in result.output
