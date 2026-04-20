"""Usage metering for Stripe billing integration.

Tracks engram_commit and engram_query calls per workspace per billing period.
Pushes usage records to Stripe's Usage Records API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite


async def init_metering_table(db: aiosqlite.Connection) -> None:
    """Create usage_events table if not exists."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace_id, event_type, period_start)
        )
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_usage_events_workspace
        ON usage_events(workspace_id, period_start)
    """)


async def record_usage(
    db: aiosqlite.Connection,
    workspace_id: str,
    event_type: str,
    period_start: datetime,
    period_end: datetime,
) -> None:
    """Record a usage event or increment count if already exists."""
    await db.execute(
        """
        INSERT INTO usage_events (workspace_id, event_type, period_start, period_end, count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(workspace_id, event_type, period_start)
        DO UPDATE SET count = count + 1
    """,
        (workspace_id, event_type, period_start.date(), period_end.date()),
    )


async def get_usage_summary(
    db: aiosqlite.Connection,
    workspace_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, int]:
    """Get usage counts for a workspace in a billing period."""
    cursor = await db.execute(
        """
        SELECT event_type, SUM(count) as total
        FROM usage_events
        WHERE workspace_id = ?
        AND period_start = ?
        AND period_end = ?
        GROUP BY event_type
    """,
        (workspace_id, period_start.date(), period_end.date()),
    )
    rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_all_workspace_usage(
    db: aiosqlite.Connection,
    period_start: datetime,
    period_end: datetime,
) -> list[dict[str, Any]]:
    """Get usage for all workspaces in a period (admin only)."""
    cursor = await db.execute(
        """
        SELECT workspace_id, event_type, SUM(count) as total
        FROM usage_events
        WHERE period_start = ?
        AND period_end = ?
        GROUP BY workspace_id, event_type
    """,
        (period_start.date(), period_end.date()),
    )
    rows = await cursor.fetchall()
    return [
        {
            "workspace_id": row[0],
            "event_type": row[1],
            "quantity": row[2],
            "period_start": period_start.date(),
            "period_end": period_end.date(),
        }
        for row in rows
    ]


def get_current_period() -> tuple[datetime, datetime]:
    """Get current billing period (monthly).

    Returns (period_start, period_end) for the current month.
    """
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    return period_start, period_end


def format_stripe_usage_item(
    workspace_id: str,
    event_type: str,
    quantity: int,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    """Format usage record for Stripe Usage Records API.

    Stripe expects:
    {
        "name": "mora_workspace_{id}_{event_type}",
        "value": quantity,
        "timestamp": period_start_unix
    }
    """
    return {
        "name": f"mora_{workspace_id}_{event_type}",
        "value": quantity,
        "timestamp": int(period_start.timestamp()),
    }
