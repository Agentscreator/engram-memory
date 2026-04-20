"""Tests for `engram conflicts` CLI commands.

Covers: list (JSON/pipe mode), resolve (flag-driven), dismiss, error paths.

The interactive TUI is not tested here because CliRunner has no TTY.
`engram conflicts` without --json falls back to JSON output in non-TTY
environments, which is what these tests exercise.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
from click.testing import CliRunner

from engram.cli import main
from engram.engine import EngramEngine
from engram.storage import SQLiteStorage


# ── helpers ──────────────────────────────────────────────────────────────────


async def _seed_conflict_db(db_path, monkeypatch) -> tuple[str, str, str]:
    """Commit two contradictory facts; return (conflict_id, fact_a_id, fact_b_id)."""
    monkeypatch.setattr(
        "engram.embeddings.encode",
        lambda text: np.array([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("engram.embeddings.get_model_version", lambda: "test-version")

    storage = SQLiteStorage(db_path=str(db_path), workspace_id="local")
    await storage.connect()
    engine = EngramEngine(storage)

    await engine.commit(
        content="The cache TTL is 60 seconds",
        scope="test-conflicts",
        confidence=0.9,
        agent_id="agent-a",
        fact_type="observation",
    )
    await engine.commit(
        content="The cache TTL is 300 seconds",
        scope="test-conflicts",
        confidence=0.9,
        agent_id="agent-b",
        fact_type="observation",
    )

    # get_conflicts calls _detect_sync internally — no need to drain the queue
    conflicts = await engine.get_conflicts(scope="test-conflicts", status="open")
    await storage.close()

    assert conflicts, "Seed failed: no conflict was detected between contradictory facts"
    c = conflicts[0]
    return c["conflict_id"], c["fact_a"]["fact_id"], c["fact_b"]["fact_id"]


def _patch_workspace(monkeypatch, db_path) -> None:
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setattr("engram.workspace.is_configured", lambda: True)
    monkeypatch.setenv("ENGRAM_DB_URL", "")


# ── list (non-TTY → JSON mode) ────────────────────────────────────────────────


def test_conflicts_lists_open_conflicts_as_json(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    # CliRunner has no TTY → non-interactive JSON output
    result = runner.invoke(main, ["conflicts"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["conflict_id"].startswith(conflict_id[:8])
    assert (
        "60 seconds" in data[0]["fact_a"]["content"] or "60 seconds" in data[0]["fact_b"]["content"]
    )


def test_conflicts_json_flag_outputs_valid_json(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(main, ["conflicts", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "conflict_id" in data[0]
    assert "fact_a" in data[0]
    assert "fact_b" in data[0]


def test_conflicts_status_all_includes_open(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(main, ["conflicts", "--status", "all", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1


def test_conflicts_no_conflicts_returns_empty_json(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    _patch_workspace(monkeypatch, db_path)

    monkeypatch.setattr(
        "engram.embeddings.encode",
        lambda text: np.array([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("engram.embeddings.get_model_version", lambda: "test-version")

    runner = CliRunner()
    result = runner.invoke(main, ["conflicts", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == []


# ── resolve (flag-driven) ─────────────────────────────────────────────────────


def test_conflicts_resolve_winner_a(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--winner", "A", "--note", "A is correct"],
    )

    assert result.exit_code == 0, result.output
    assert "Resolved" in result.output
    assert "winner" in result.output


def test_conflicts_resolve_winner_b(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--winner", "B", "--note", "B is correct"],
    )

    assert result.exit_code == 0, result.output
    assert "Resolved" in result.output


def test_conflicts_resolve_merge(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--merge", "--note", "Both superseded"],
    )

    assert result.exit_code == 0, result.output
    assert "Resolved" in result.output
    assert "merge" in result.output


def test_conflicts_resolve_requires_note(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--winner", "A"],
    )

    assert result.exit_code != 0
    assert "--note" in result.output


def test_conflicts_resolve_requires_resolution_flag(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--note", "some note"],
    )

    assert result.exit_code != 0
    assert "interactive" in result.output.lower() or "--winner" in result.output


def test_conflicts_resolve_rejects_multiple_flags(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "conflicts",
            "resolve",
            conflict_id[:8],
            "--winner",
            "A",
            "--merge",
            "--note",
            "oops",
        ],
    )

    assert result.exit_code != 0
    assert "--winner" in result.output or "only one" in result.output.lower()


def test_conflicts_resolve_unknown_id_fails(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["conflicts", "resolve", "nonexistent", "--winner", "A", "--note", "x"],
    )

    assert result.exit_code != 0
    assert "nonexistent" in result.output


def test_conflicts_resolve_already_resolved_gives_clear_error(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    # Resolve once
    runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--winner", "A", "--note", "first"],
    )
    # Try to resolve again
    result = runner.invoke(
        main,
        ["conflicts", "resolve", conflict_id[:8], "--winner", "B", "--note", "second"],
    )

    assert result.exit_code != 0
    assert "already" in result.output.lower()


# ── dismiss ───────────────────────────────────────────────────────────────────


def test_conflicts_dismiss_removes_open_conflict(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(main, ["conflicts", "dismiss", conflict_id[:8]])

    assert result.exit_code == 0, result.output
    assert "Dismissed" in result.output
    assert conflict_id[:8] in result.output


def test_conflicts_dismiss_with_note(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(
        main, ["conflicts", "dismiss", conflict_id[:8], "--note", "not a real conflict"]
    )

    assert result.exit_code == 0, result.output
    assert "Dismissed" in result.output


def test_conflicts_dismiss_unknown_id_fails(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    result = runner.invoke(main, ["conflicts", "dismiss", "doesnotexist"])

    assert result.exit_code != 0
    assert "doesnotexist" in result.output


def test_conflicts_after_dismiss_no_longer_in_open_list(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    conflict_id, _, _ = asyncio.run(_seed_conflict_db(db_path, monkeypatch))
    _patch_workspace(monkeypatch, db_path)

    runner = CliRunner()
    runner.invoke(main, ["conflicts", "dismiss", conflict_id[:8]])

    result = runner.invoke(main, ["conflicts", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    open_ids = [c["conflict_id"] for c in data if c.get("status") == "open"]
    assert not any(cid.startswith(conflict_id[:8]) for cid in open_ids)
