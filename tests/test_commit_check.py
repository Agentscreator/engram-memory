from __future__ import annotations

from pathlib import Path

from engram.commit_check import (
    build_commit_query,
    fetch_open_conflicts,
    filter_relevant_facts,
    format_conflict_blocker,
    format_commit_warning,
    load_credentials,
    load_project_credentials,
    mcp_url_to_base_url,
    summarize_staged_diff,
)


def test_mcp_url_to_base_url_strips_mcp_suffix():
    assert mcp_url_to_base_url("https://engram.example.com/mcp") == "https://engram.example.com"


def test_mcp_url_to_base_url_keeps_base_url():
    assert mcp_url_to_base_url("http://127.0.0.1:7474") == "http://127.0.0.1:7474"


def test_summarize_staged_diff_extracts_changed_lines():
    diff = """diff --git a/a.py b/a.py
@@ -1,2 +1,2 @@
-old line
+new line
 unchanged
+another line
"""
    summary = summarize_staged_diff(diff)
    assert "old line" in summary
    assert "new line" in summary
    assert "another line" in summary
    assert "diff --git" not in summary


def test_build_commit_query_combines_message_files_and_diff():
    query = build_commit_query(
        "switch to Redis for session caching",
        ["src/cache/redis.py", "tests/test_cache.py"],
        "+use redis cache\n-old cache path",
    )
    assert "switch to Redis for session caching" in query
    assert "src/cache" in query
    assert "tests" in query
    assert "use redis cache" in query


def test_build_commit_query_works_without_message():
    query = build_commit_query(None, ["src/auth/token.py"], "+rotate signing keys")
    assert "src/auth" in query
    assert "rotate signing keys" in query


def test_filter_relevant_facts_respects_threshold():
    facts = [
        {"content": "a", "relevance_score": 0.9},
        {"content": "b", "relevance_score": 0.2},
    ]
    filtered = filter_relevant_facts(facts, 0.3)
    assert [fact["content"] for fact in filtered] == ["a"]


def test_format_commit_warning_empty():
    assert "No relevant Engram facts found" in format_commit_warning([], threshold=0.35)


def test_format_commit_warning_lists_matches():
    warning = format_commit_warning(
        [
            {
                "content": "Redis was evaluated and rejected due to memory cost.",
                "scope": "cache",
                "agent_id": "agent-cache",
                "confidence": 0.91,
                "relevance_score": 0.82,
                "committed_at": "2026-04-10T10:00:00Z",
            }
        ],
        threshold=0.35,
        strict=False,
    )
    assert "Redis was evaluated and rejected" in warning
    assert "Advisory only" in warning
    assert "agent=agent-cache" in warning


def test_load_credentials_prefers_project_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    creds_dir = home / ".engram"
    creds_dir.mkdir()
    (creds_dir / "credentials").write_text(
        "ENGRAM_SERVER_URL=https://shared.example.com\nENGRAM_INVITE_KEY=ek_live_shared\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".engram.env").write_text(
        "ENGRAM_SERVER_URL=https://local.example.com\nENGRAM_INVITE_KEY=ek_live_local\n"
    )

    monkeypatch.setattr(Path, "home", lambda: home)
    server_url, invite_key = load_credentials(project)

    assert server_url == "https://local.example.com"
    assert invite_key == "ek_live_local"


def test_load_project_credentials_reads_dot_engram_env(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".engram.env").write_text(
        "ENGRAM_MCP_URL=https://engram.example.com/mcp\nENGRAM_INVITE_KEY=ek_live_local\n"
    )

    server_url, invite_key = load_project_credentials(project)

    assert server_url == "https://engram.example.com"
    assert invite_key == "ek_live_local"


def test_format_conflict_blocker_lists_conflicts():
    blocker = format_conflict_blocker(
        [
            {
                "conflict_id": "conflict-1234567890",
                "explanation": "Rate limit disagreement",
                "fact_a": {"scope": "auth", "content": "Limit is 1000 req/s"},
                "fact_b": {"scope": "auth", "content": "Limit is 2000 req/s"},
            }
        ]
    )

    assert "blocked this commit" in blocker
    assert "Rate limit disagreement" in blocker
    assert "Limit is 1000 req/s" in blocker
    assert "Limit is 2000 req/s" in blocker


def test_fetch_open_conflicts_accepts_list_payload(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'[{"conflict_id":"c1"}]'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=10: _Response())

    conflicts = fetch_open_conflicts("https://engram.example.com", "ek_live_test")

    assert conflicts == [{"conflict_id": "c1"}]
