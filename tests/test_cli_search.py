import asyncio
import json

import numpy as np
from click.testing import CliRunner

from engram.cli import main
from engram.engine import EngramEngine
from engram.storage import SQLiteStorage


async def _seed_search_db(db_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "engram.embeddings.encode",
        lambda text: np.array([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("engram.embeddings.get_model_version", lambda: "test-version")

    storage = SQLiteStorage(db_path=db_path, workspace_id="local")
    await storage.connect()
    engine = EngramEngine(storage)

    try:
        await engine.commit(
            content="Payments service retries failed webhooks with exponential backoff.",
            scope="payments",
            confidence=0.95,
            agent_id="agent-pay",
            provenance="src/payments/service.py:42",
            fact_type="observation",
        )
        await engine.commit(
            content="Auth service signs session tokens with rotating keys.",
            scope="auth",
            confidence=0.90,
            agent_id="agent-auth",
            fact_type="observation",
        )
    finally:
        await storage.close()


def test_search_prints_formatted_results(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setenv("ENGRAM_DB_URL", "")

    asyncio.run(_seed_search_db(db_path, monkeypatch))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["search", "payments service", "--scope", "payments", "--limit", "1"],
    )

    assert result.exit_code == 0, f"Exit code: {result.exit_code}, Output: {result.output}"
    assert 'Results for "payments service" (1):' in result.output
    assert (
        "[payments] Payments service retries failed webhooks with exponential backoff."
        in result.output
    )
    assert "provenance=src/payments/service.py:42" in result.output
    assert "Auth service signs session tokens" not in result.output


def test_search_json_outputs_results(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setenv("ENGRAM_DB_URL", "")

    asyncio.run(_seed_search_db(db_path, monkeypatch))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["search", "payments service", "--scope", "payments", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["scope"] == "payments"
    assert (
        data[0]["content"] == "Payments service retries failed webhooks with exponential backoff."
    )
    assert data[0]["verified"] is True


def test_search_limit_applies(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setenv("ENGRAM_DB_URL", "")

    asyncio.run(_seed_search_db(db_path, monkeypatch))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["search", "service", "--limit", "1"],
    )

    assert result.exit_code == 0
    assert 'Results for "service" (1):' in result.output


def test_search_no_results_when_scope_has_no_facts(monkeypatch, tmp_path):
    db_path = tmp_path / "engram.db"
    monkeypatch.setattr("engram.cli.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("engram.workspace.read_workspace", lambda: None)
    monkeypatch.setenv("ENGRAM_DB_URL", "")

    asyncio.run(_seed_search_db(db_path, monkeypatch))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["search", "payments service", "--scope", "billing"],
    )

    assert result.exit_code == 0
    assert 'No results found for "payments service".' in result.output
