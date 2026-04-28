"""Tests for the overnight deferred scan processor."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest_asyncio

from engram.overnight import (
    _midnight_tonight,
    _now_iso,
    _read_codebase_snapshot,
    build_deferred_scan,
    run_overnight,
)
from engram.storage import Storage


@pytest_asyncio.fixture
async def storage(tmp_path: Path):
    s = Storage(db_path=tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


# ── Pure function tests ───────────────────────────────────────────────────────


def test_now_iso_returns_utc_iso_string():
    result = _now_iso()
    dt = datetime.fromisoformat(result)
    assert dt.tzinfo is not None


def test_midnight_tonight_is_in_the_future():
    midnight = datetime.fromisoformat(_midnight_tonight())
    now = datetime.now(timezone.utc)
    assert midnight > now


def test_midnight_tonight_is_at_midnight():
    midnight = datetime.fromisoformat(_midnight_tonight())
    assert midnight.hour == 0
    assert midnight.minute == 0
    assert midnight.second == 0


def test_build_deferred_scan_returns_required_fields():
    scan = build_deferred_scan({"context": "test context"})
    assert "id" in scan
    assert "queued_at" in scan
    assert "scheduled_for" in scan
    assert "payload" in scan


def test_build_deferred_scan_serializes_context():
    scan = build_deferred_scan({"context": "hello"})
    payload = json.loads(scan["payload"])
    assert payload["context"] == "hello"


def test_build_deferred_scan_without_context():
    scan = build_deferred_scan()
    payload = json.loads(scan["payload"])
    assert payload == {}


def test_build_deferred_scan_unique_ids():
    scan_a = build_deferred_scan()
    scan_b = build_deferred_scan()
    assert scan_a["id"] != scan_b["id"]


def test_read_codebase_snapshot_returns_list_on_missing_git(tmp_path):
    # Non-git directory — subprocess returns no output, result is empty list
    result = _read_codebase_snapshot(str(tmp_path))
    assert isinstance(result, list)


def test_read_codebase_snapshot_respects_max_files(tmp_path):
    # Even if git returns files, max_files caps the result
    result = _read_codebase_snapshot(str(tmp_path), max_files=0)
    assert result == []


# ── run_overnight integration tests ──────────────────────────────────────────


async def test_run_overnight_returns_zero_when_no_pending_scans(storage, tmp_path):
    committed = await run_overnight(storage, cwd=str(tmp_path))
    assert committed == 0


async def test_run_overnight_skips_scans_scheduled_in_future(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan()
    # Force scheduled_for far in the future
    scan["scheduled_for"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    committed = await run_overnight(storage, cwd=str(tmp_path))
    assert committed == 0


async def test_run_overnight_processes_past_due_scan_without_api_key(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan({"context": "test"})
    # Force scheduled_for in the past so it is picked up
    scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    # Without ANTHROPIC_API_KEY the LLM call returns None → 0 facts committed
    with patch.dict("os.environ", {}, clear=True):
        committed = await run_overnight(storage, cwd=str(tmp_path))

    assert committed == 0


async def test_run_overnight_commits_llm_insights(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan({"context": "test context"})
    scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='["Insight one.", "Insight two."]')]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("engram.overnight._get_overnight_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            committed = await run_overnight(storage, cwd=str(tmp_path))

    assert committed == 2


async def test_run_overnight_deduplicates_insights(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    # Enqueue two scans with identical insights
    for _ in range(2):
        scan = build_deferred_scan({"context": "test"})
        scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await storage.enqueue_deferred_scan(scan)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='["Duplicate insight."]')]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("engram.overnight._get_overnight_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            committed = await run_overnight(storage, cwd=str(tmp_path))

    # Second scan deduplicates — only 1 fact total
    assert committed == 1


async def test_run_overnight_handles_malformed_llm_response(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan()
    scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json at all")]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("engram.overnight._get_overnight_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            committed = await run_overnight(storage, cwd=str(tmp_path))

    assert committed == 0


async def test_run_overnight_marks_scan_done_after_processing(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan()
    scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    with patch.dict("os.environ", {}, clear=True):
        await run_overnight(storage, cwd=str(tmp_path))

    # No more pending scans — scan was marked done
    pending = await storage.get_pending_deferred_scans(before=_now_iso())
    assert pending == []


async def test_run_overnight_caps_insights_at_five(storage, tmp_path):
    from engram.overnight import build_deferred_scan

    scan = build_deferred_scan()
    scan["scheduled_for"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.enqueue_deferred_scan(scan)

    insights = ["Insight %d." % i for i in range(10)]
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(insights))]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("engram.overnight._get_overnight_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            committed = await run_overnight(storage, cwd=str(tmp_path))

    assert committed <= 5
