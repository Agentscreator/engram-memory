"""Tests for engram_replay."""

from engram.storage import SQLiteStorage
from datetime import datetime, timezone
import uuid


async def test_replay_with_as_of(tmp_path):
    """Queries workspace at a past timestamp."""
    db_path = tmp_path / "replay_test.db"
    storage = SQLiteStorage(db_path=str(db_path), workspace_id="test")
    await storage.connect()

    lineage_id = str(uuid.uuid4())
    fact_id = await storage.insert_fact(
        {
            "content": "Initial value",
            "lineage_id": lineage_id,
            "scope": "config",
            "agent_id": "test-agent",
            "engineer": "test",
            "valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "ttl_days": 30,
        }
    )

    results = await storage.get_current_facts_in_scope(
        scope="config",
        as_of=datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
        limit=10,
    )

    assert len(results) >= 1
    await storage.close()
