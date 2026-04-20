import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from engram.cli import main
from engram.importer import (
    chunk_document,
    discover_import_files,
    import_documents,
    prepare_import_fact,
)
from engram.storage import SQLiteStorage


async def _read_current_facts(db_path: Path) -> list[dict]:
    storage = SQLiteStorage(db_path=db_path, workspace_id="local")
    await storage.connect()
    try:
        return await storage.get_current_facts_in_scope(limit=50)
    finally:
        await storage.close()


def _patch_import_environment(monkeypatch, db_path: Path, statements: list[str] | Exception):
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setenv("ENGRAM_DB_URL", "")
    monkeypatch.setattr(
        "engram.embeddings.encode",
        lambda text: np.array([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("engram.embeddings.get_model_version", lambda: "test-version")

    async def fake_extract(chunk: str, source: str) -> list[str]:
        if isinstance(statements, Exception):
            raise statements
        return statements

    monkeypatch.setattr("engram.importer.extract_atomic_statements", fake_extract)


def test_discover_import_files_supports_markdown_and_text(tmp_path):
    (tmp_path / "notes.md").write_text("# Notes")
    (tmp_path / "runbook.txt").write_text("Runbook")
    (tmp_path / "data.json").write_text("{}")
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "ignored.md").write_text("Ignore me")

    files = discover_import_files(tmp_path)

    assert files == [tmp_path / "notes.md", tmp_path / "runbook.txt"]


def test_chunk_document_splits_large_markdown():
    text = "# Heading\n\n" + ("Sentence one. " * 500) + "\n\n## Next\n\nSentence two."

    chunks = chunk_document(text, max_chars=200)

    assert len(chunks) > 1
    assert all(len(chunk) <= 220 for chunk in chunks)


def test_prepare_import_fact_uses_import_defaults():
    fact = prepare_import_fact(
        "The auth service uses JWT session tokens.",
        "docs/auth.md",
        "docs",
    )

    assert fact == {
        "content": "The auth service uses JWT session tokens.",
        "scope": "docs",
        "confidence": 0.7,
        "fact_type": "observation",
        "provenance": "docs/auth.md",
    }


def test_import_markdown_commits_extracted_facts(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "auth.md"
    source.write_text("# Auth\n\nThe auth service uses JWT session tokens.")
    _patch_import_environment(
        monkeypatch,
        db_path,
        ["The auth service uses JWT session tokens."],
    )

    result = CliRunner().invoke(main, ["import", str(docs), "--scope", "docs"])

    assert result.exit_code == 0, result.output
    assert "Files scanned   : 1" in result.output
    assert "Facts extracted : 1" in result.output
    assert "Committed       : 1" in result.output

    facts = asyncio.run(_read_current_facts(db_path))
    assert len(facts) == 1
    assert facts[0]["content"] == "The auth service uses JWT session tokens."
    assert facts[0]["scope"] == "docs"
    assert facts[0]["confidence"] == 0.7
    assert facts[0]["fact_type"] == "observation"
    assert facts[0]["provenance"] == str(source)


def test_import_text_file_commits_fact(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    source = tmp_path / "runbook.txt"
    source.write_text("Payments retries failed webhooks with exponential backoff.")
    _patch_import_environment(
        monkeypatch,
        db_path,
        ["Payments retries failed webhooks with exponential backoff."],
    )

    result = CliRunner().invoke(main, ["import", str(source), "--scope", "payments"])

    assert result.exit_code == 0, result.output
    facts = asyncio.run(_read_current_facts(db_path))
    assert len(facts) == 1
    assert facts[0]["scope"] == "payments"
    assert facts[0]["provenance"] == str(source)


def test_import_dry_run_does_not_write(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    source = tmp_path / "notes.md"
    source.write_text("The dashboard runs at /dashboard.")
    _patch_import_environment(monkeypatch, db_path, ["The dashboard runs at /dashboard."])

    result = CliRunner().invoke(main, ["import", str(source), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Facts extracted : 1" in result.output
    assert "Committed       : 0" in result.output
    assert "Dry run facts:" in result.output
    assert not db_path.exists()


def test_import_pattern_skips_unsupported_files(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    (tmp_path / "data.json").write_text(json.dumps({"fact": "ignore me"}))
    _patch_import_environment(monkeypatch, db_path, ["This should not be imported."])

    result = CliRunner().invoke(main, ["import", str(tmp_path), "--pattern", "*.json"])

    assert result.exit_code == 0, result.output
    assert "Files scanned   : 0" in result.output
    assert "Facts extracted : 0" in result.output
    facts = asyncio.run(_read_current_facts(db_path))
    assert facts == []


def test_import_reports_extractor_failure(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    source = tmp_path / "notes.md"
    source.write_text("The queue has a dead-letter policy.")
    _patch_import_environment(monkeypatch, db_path, RuntimeError("extractor failed"))

    result = CliRunner().invoke(main, ["import", str(source)])

    assert result.exit_code == 0, result.output
    assert "Skipped         : 1" in result.output
    assert "extractor failed" in result.output


def test_import_reports_duplicate_commits(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "one.md").write_text("Redis runs on port 6379.")
    (docs / "two.md").write_text("Redis runs on port 6379.")
    _patch_import_environment(monkeypatch, db_path, ["Redis runs on port 6379."])

    result = CliRunner().invoke(main, ["import", str(docs), "--scope", "infra"])

    assert result.exit_code == 0, result.output
    assert "Facts extracted : 2" in result.output
    assert "Committed       : 1" in result.output
    assert "Duplicates      : 1" in result.output


def test_import_reports_rejected_secret(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    source = tmp_path / "secrets.md"
    source.write_text("The API key is documented here.")
    _patch_import_environment(
        monkeypatch,
        db_path,
        ["API key is sk-abc123def456ghi789jkl012mno345pqr"],
    )

    result = CliRunner().invoke(main, ["import", str(source)])

    assert result.exit_code == 0, result.output
    assert "Skipped         : 1" in result.output
    assert "appears to contain a secret" in result.output


@pytest.mark.asyncio
async def test_import_does_not_block_event_loop(tmp_path, monkeypatch):
    """File discovery and reads run in threads, so the event loop stays free during imports."""
    source = tmp_path / "notes.md"
    source.write_text("The event loop stays responsive during imports.")

    import engram.importer as importer_mod

    original_discover = importer_mod.discover_import_files

    def slow_discover(path, pattern="*"):
        time.sleep(0.05)  # synchronous pause — would stall the event loop without to_thread
        return original_discover(path, pattern)

    monkeypatch.setattr("engram.importer.discover_import_files", slow_discover)

    async def fake_extract(chunk, source):
        return ["The event loop stays responsive."]

    monkeypatch.setattr("engram.importer.extract_atomic_statements", fake_extract)

    class FakeEngine:
        async def commit_batch(self, facts, scope, agent_id):
            return [{"success": True, "duplicate": False} for _ in facts]

    ticks: list[int] = []

    async def ticker():
        for i in range(5):
            await asyncio.sleep(0)
            ticks.append(i)

    ticker_task = asyncio.create_task(ticker())
    await import_documents(FakeEngine(), tmp_path, scope="test")
    await ticker_task

    assert len(ticks) == 5
