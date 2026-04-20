"""Tests for scope-based permissions."""

from engram.storage import SQLiteStorage


async def test_set_and_get_scope_permission(tmp_path):
    """Sets and retrieves scope permission."""
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(db_path=str(db_path), workspace_id="test")
    await storage.connect()

    await storage.set_scope_permission(
        agent_id="claude-code",
        scope="auth",
        can_read=True,
        can_write=False,
    )

    perm = await storage.get_scope_permission(agent_id="claude-code", scope="auth")
    assert perm is not None
    assert perm["can_read"] == 1
    assert perm["can_write"] == 0
    await storage.close()


async def test_get_scope_permission_default(tmp_path):
    """Returns default permission when none set."""
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(db_path=str(db_path), workspace_id="test")
    await storage.connect()

    perm = await storage.get_scope_permission(agent_id="claude-code", scope="auth")
    assert perm is None
    await storage.close()
