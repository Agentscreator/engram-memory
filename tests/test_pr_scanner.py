"""Tests for the GitHub Action PR conflict scanner helpers.

Covers query building from PR context, comment formatting,
and relevance filtering — the core logic of the engram-pr-scanner action.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", ".github", "actions", "engram-pr-scanner")
)

from pr_scanner import build_query, filter_by_relevance, format_comment


# ── build_query ───────────────────────────────────────────────────────


class TestBuildQuery:
    def test_title_only(self):
        result = build_query("Remove rate limit", "", [])
        assert result == "Remove rate limit"

    def test_title_and_body(self):
        result = build_query("Fix auth", "This PR fixes the auth module", [])
        assert "Fix auth" in result
        assert "This PR fixes the auth module" in result

    def test_body_markdown_stripped(self):
        result = build_query("", "## Heading\n**bold** `code` [link](url)", [])
        assert "#" not in result
        assert "*" not in result
        assert "`" not in result
        assert "[" not in result
        assert "]" not in result

    def test_changed_files_directories(self):
        files = [
            "src/engram/engine.py",
            "src/engram/storage.py",
            "tests/test_engine.py",
        ]
        result = build_query("", "", files)
        assert "src/engram" in result
        assert "tests" in result

    def test_full_context(self):
        result = build_query(
            "Switch to Redis for caching",
            "Replaces the in-memory cache with Redis for better scalability.",
            ["src/cache/redis_client.py", "src/cache/config.py"],
        )
        assert "Switch to Redis" in result
        assert "Replaces the in-memory cache" in result
        assert "src/cache" in result

    def test_empty_inputs(self):
        result = build_query("", "", [])
        assert result == ""

    def test_whitespace_only_title(self):
        result = build_query("   ", "", [])
        assert result == ""

    def test_body_truncated_to_200_chars(self):
        long_body = "a" * 500
        result = build_query("", long_body, [])
        assert len(result) <= 500

    def test_max_len_enforced(self):
        result = build_query("x" * 600, "", [], max_len=100)
        assert len(result) <= 100

    def test_max_10_files(self):
        files = [f"src/module{i}/file.py" for i in range(20)]
        result = build_query("", "", files)
        # Should only include dirs from first 10 files
        assert "src/module10" not in result


# ── filter_by_relevance ──────────────────────────────────────────────


class TestFilterByRelevance:
    def test_filters_below_threshold(self):
        facts = [
            {"content": "high", "relevance_score": 0.8},
            {"content": "low", "relevance_score": 0.1},
            {"content": "mid", "relevance_score": 0.3},
        ]
        result = filter_by_relevance(facts, 0.3)
        assert len(result) == 2
        assert result[0]["content"] == "high"
        assert result[1]["content"] == "mid"

    def test_empty_list(self):
        assert filter_by_relevance([], 0.5) == []

    def test_missing_score_treated_as_zero(self):
        facts = [{"content": "no score"}]
        assert filter_by_relevance(facts, 0.1) == []

    def test_zero_threshold_includes_all(self):
        facts = [
            {"content": "a", "relevance_score": 0.01},
            {"content": "b", "relevance_score": 0.0},
        ]
        result = filter_by_relevance(facts, 0.0)
        assert len(result) == 2


# ── format_comment ───────────────────────────────────────────────────


class TestFormatComment:
    def test_empty_facts_returns_empty(self):
        assert format_comment([]) == ""

    def test_single_fact(self):
        facts = [
            {
                "content": "Rate limit is 1000 req/s per contract",
                "scope": "api",
                "agent_id": "gpt-4o",
                "confidence": 0.95,
                "committed_at": "2026-03-12T10:00:00+00:00",
                "relevance_score": 0.75,
            }
        ]
        result = format_comment(facts)
        assert "### Engram Memory Check" in result
        assert "Rate limit is 1000 req/s" in result
        assert "`api`" in result
        assert "`gpt-4o`" in result
        assert "0.95" in result
        assert "2026-03-12" in result
        assert "**1**" in result

    def test_multiple_facts(self):
        facts = [
            {
                "content": "Fact one",
                "scope": "backend",
                "agent_id": "agent1",
                "confidence": 0.9,
                "committed_at": "2026-01-01T00:00:00+00:00",
                "relevance_score": 0.8,
            },
            {
                "content": "Fact two",
                "scope": "frontend",
                "agent_id": "agent2",
                "confidence": 0.7,
                "committed_at": "2026-02-01T00:00:00+00:00",
                "relevance_score": 0.6,
            },
        ]
        result = format_comment(facts)
        assert "**2**" in result
        assert "Fact one" in result
        assert "Fact two" in result

    def test_pipe_characters_escaped(self):
        facts = [
            {
                "content": "Use A | B pattern",
                "scope": "test",
                "agent_id": "a",
                "confidence": 0.5,
                "committed_at": "2026-01-01",
            }
        ]
        result = format_comment(facts)
        assert "A \\| B" in result

    def test_long_content_truncated(self):
        facts = [
            {
                "content": "x" * 200,
                "scope": "s",
                "agent_id": "a",
                "confidence": 0.5,
                "committed_at": "2026-01-01",
            }
        ]
        result = format_comment(facts)
        lines = [line for line in result.split("\n") if line.startswith("| x")]
        assert len(lines) == 1
        # Content cell should be truncated to 120 chars
        content_cell = lines[0].split("|")[1].strip()
        assert len(content_cell) <= 120

    def test_missing_fields_use_defaults(self):
        facts = [{}]
        result = format_comment(facts)
        assert "unknown" in result
        assert "`-`" in result

    def test_footer_contains_engram_link(self):
        facts = [
            {
                "content": "test",
                "scope": "s",
                "agent_id": "a",
                "confidence": 0.5,
                "committed_at": "2026-01-01",
            }
        ]
        result = format_comment(facts)
        assert "Agentscreator/Engram" in result
        assert "pr-scanner.md" in result

    def test_custom_relevance_threshold_in_footer(self):
        facts = [
            {
                "content": "test",
                "scope": "s",
                "agent_id": "a",
                "confidence": 0.5,
                "committed_at": "2026-01-01",
            }
        ]
        result = format_comment(facts, relevance_threshold=0.7)
        assert "0.7" in result
