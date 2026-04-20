"""Tests for usage metering."""

import aiosqlite
from datetime import datetime, timezone

from engram.metering import (
    init_metering_table,
    record_usage,
    get_usage_summary,
    get_all_workspace_usage,
    get_current_period,
    format_stripe_usage_item,
)


async def test_init_metering_table():
    """Creates usage_events table."""
    db = await aiosqlite.connect(":memory:")
    await init_metering_table(db)
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_events'"
    )
    row = await cursor.fetchone()
    assert row is not None
    await db.close()


async def test_record_usage():
    """Records and increments usage counts."""
    db = await aiosqlite.connect(":memory:")
    await init_metering_table(db)

    period_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 5, 1, tzinfo=timezone.utc)

    await record_usage(db, "ws-001", "engram_commit", period_start, period_end)
    await record_usage(db, "ws-001", "engram_commit", period_start, period_end)
    await record_usage(db, "ws-001", "engram_query", period_start, period_end)

    summary = await get_usage_summary(db, "ws-001", period_start, period_end)
    assert summary["engram_commit"] == 2
    assert summary["engram_query"] == 1
    await db.close()


async def test_get_usage_summary_empty():
    """Returns empty dict when no usage."""
    db = await aiosqlite.connect(":memory:")
    await init_metering_table(db)

    period_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 5, 1, tzinfo=timezone.utc)

    summary = await get_usage_summary(db, "ws-nonexistent", period_start, period_end)
    assert summary == {}
    await db.close()


async def test_get_all_workspace_usage():
    """Returns usage for all workspaces."""
    db = await aiosqlite.connect(":memory:")
    await init_metering_table(db)

    period_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 5, 1, tzinfo=timezone.utc)

    await record_usage(db, "ws-001", "engram_commit", period_start, period_end)
    await record_usage(db, "ws-002", "engram_commit", period_start, period_end)
    await record_usage(db, "ws-002", "engram_query", period_start, period_end)

    all_usage = await get_all_workspace_usage(db, period_start, period_end)
    assert len(all_usage) == 3
    await db.close()


async def test_get_current_period():
    """Returns current month boundaries."""
    period_start, period_end = get_current_period()
    assert period_start.day == 1
    assert period_end.day == 1


async def test_format_stripe_usage_item():
    """Formats usage for Stripe API."""
    period = datetime(2026, 4, 1, tzinfo=timezone.utc)
    item = format_stripe_usage_item("ws-001", "engram_commit", 100, period, period)
    assert item["name"] == "mora_ws-001_engram_commit"
    assert item["value"] == 100
    assert item["timestamp"] == int(period.timestamp())
