"""Tests for the invite key rotation lifecycle.

Covers:
- Soft-revoke with grace period: revoked_at set, grace_until in the future.
- Grace window allows existing sessions (get_active_grace_until returns future ts).
- Grace window expiry: after grace_until passes, get_active_grace_until returns None.
- New join attempts blocked on revoked keys (consume_invite_key returns None).
- Immediate revocation (grace_minutes=0): hard DELETE, no grace.
- Cleanup: cleanup_expired_grace_keys removes expired revoked rows, leaves active rows.
- Audit log: rotation writes a key_rotation entry with correct extra JSON.
- Rotation history: get_key_rotation_history returns entries newest-first.
- Multiple rotations: second rotation cleans up expired grace rows and re-revokes.
- Engine-level permission gate: rotate_invite_key raises PermissionError when not creator.
- Isolation: rotating workspace A does not affect workspace B's keys.
- validate_invite_key: revoked keys are rejected even within grace period.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from engram.engine import EngramEngine
from engram.storage import Storage


# ── helpers ──────────────────────────────────────────────────────────


ENGRAM_ID_A = "ENG-TEST-AAAA"
ENGRAM_ID_B = "ENG-TEST-BBBB"


def _ts(delta_seconds: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _key_hash() -> str:
    return uuid.uuid4().hex * 2  # 64-char hex, like SHA256


async def _seed_workspace(storage: Storage, engram_id: str = ENGRAM_ID_A) -> None:
    """Insert a workspace row so invite_keys FK constraint is satisfied."""
    await storage.ensure_workspace(engram_id, anonymous_mode=False, anon_agents=False)


async def _seed_key(
    storage: Storage,
    engram_id: str = ENGRAM_ID_A,
    *,
    expires_at: str | None = None,
    uses_remaining: int | None = 5,
) -> str:
    """Insert an active invite key and return its hash."""
    kh = _key_hash()
    await storage.insert_invite_key(
        key_hash=kh,
        engram_id=engram_id,
        expires_at=expires_at,
        uses_remaining=uses_remaining,
    )
    return kh


# ── fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def storage(tmp_path: Path) -> Storage:
    db_path = tmp_path / "test.db"
    s = Storage(db_path=db_path)
    await s.connect()
    await _seed_workspace(s, ENGRAM_ID_A)
    yield s
    await s.close()


@pytest_asyncio.fixture
async def storage_two_workspaces(tmp_path: Path) -> Storage:
    db_path = tmp_path / "test_two.db"
    s = Storage(db_path=db_path)
    await s.connect()
    await _seed_workspace(s, ENGRAM_ID_A)
    await _seed_workspace(s, ENGRAM_ID_B)
    yield s
    await s.close()


# ── storage-level: soft revoke with grace ─────────────────────────────


async def test_revoke_with_grace_sets_revoked_at(storage: Storage):
    """After revoke_all_invite_keys(grace_minutes=15), revoked_at is populated."""
    kh = await _seed_key(storage)

    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    cursor = await storage.db.execute(
        "SELECT revoked_at, grace_until FROM invite_keys WHERE key_hash = ?", (kh,)
    )
    row = await cursor.fetchone()
    assert row is not None, "Key row should still exist (soft revoke keeps it)"
    assert row["revoked_at"] is not None, "revoked_at must be set after soft revoke"
    assert row["grace_until"] is not None, "grace_until must be set when grace_minutes > 0"


async def test_revoke_with_grace_grace_until_in_future(storage: Storage):
    """grace_until should be approximately now + grace_minutes in the future."""
    kh = await _seed_key(storage)
    grace_minutes = 10

    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=grace_minutes)

    cursor = await storage.db.execute(
        "SELECT grace_until FROM invite_keys WHERE key_hash = ?", (kh,)
    )
    row = await cursor.fetchone()
    assert row is not None
    grace_until_str = row["grace_until"]
    # SQLite stores naive timestamps; compare as naive UTC.
    # SQLite stores naive UTC timestamps; compare naive-to-naive.
    grace_until = datetime.fromisoformat(grace_until_str)
    assert grace_until > datetime.now(timezone.utc).replace(tzinfo=None), (
        "grace_until must be in the future"
    )


async def test_get_active_grace_until_returns_future_ts(storage: Storage):
    """get_active_grace_until returns a future ISO string when grace is active."""
    await _seed_key(storage)
    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    grace_until = await storage.get_active_grace_until(ENGRAM_ID_A)

    assert grace_until is not None, "Should return a grace_until string while in grace period"
    # SQLite returns naive timestamps; strip tz info for comparison.
    grace_str = grace_until.replace("+00:00", "").rstrip("Z")
    grace_dt = datetime.fromisoformat(grace_str)
    assert grace_dt > datetime.now(timezone.utc).replace(tzinfo=None), (
        "Returned grace_until must be in the future"
    )


async def test_get_active_grace_until_none_when_no_revoked_keys(storage: Storage):
    """get_active_grace_until returns None when there are no revoked keys at all."""
    await _seed_key(storage)  # active key, not revoked

    grace_until = await storage.get_active_grace_until(ENGRAM_ID_A)

    assert grace_until is None


async def test_get_active_grace_until_none_after_grace_expires(storage: Storage):
    """get_active_grace_until returns None once grace_until is in the past."""
    kh = await _seed_key(storage)
    # Manually insert a revoked key with an already-expired grace_until
    await storage.db.execute(
        "UPDATE invite_keys SET revoked_at = datetime('now', '-1 minute'), "
        "grace_until = datetime('now', '-30 seconds') WHERE key_hash = ?",
        (kh,),
    )
    await storage.db.commit()

    grace_until = await storage.get_active_grace_until(ENGRAM_ID_A)

    assert grace_until is None, "Expired grace windows must not be returned"


# ── storage-level: new join blocked on revoked key ────────────────────


async def test_consume_invite_key_blocked_when_revoked(storage: Storage):
    """consume_invite_key returns None for a revoked key even within grace period."""
    kh = await _seed_key(storage)
    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    result = await storage.consume_invite_key(kh)

    assert result is None, "Revoked key must not be consumable for new joins"


async def test_consume_invite_key_works_for_active_key(storage: Storage):
    """consume_invite_key succeeds for a non-revoked, valid key."""
    kh = await _seed_key(storage, uses_remaining=3)

    result = await storage.consume_invite_key(kh)

    assert result is not None, "Active key should be consumable"
    assert result["uses_remaining"] == 2


async def test_validate_invite_key_blocked_when_revoked(storage: Storage):
    """validate_invite_key returns None for revoked keys."""
    kh = await _seed_key(storage)
    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    result = await storage.validate_invite_key(kh)

    assert result is None, "Revoked key must not pass validation"


# ── storage-level: immediate revocation (grace_minutes=0) ────────────


async def test_immediate_revoke_hard_deletes_keys(storage: Storage):
    """grace_minutes=0 performs a hard DELETE, leaving no rows."""
    kh = await _seed_key(storage)

    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=0)

    cursor = await storage.db.execute("SELECT key_hash FROM invite_keys WHERE key_hash = ?", (kh,))
    row = await cursor.fetchone()
    assert row is None, "Immediate revocation must hard-delete the key row"


async def test_immediate_revoke_no_active_grace(storage: Storage):
    """After grace_minutes=0 revocation, get_active_grace_until returns None."""
    await _seed_key(storage)
    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=0)

    grace_until = await storage.get_active_grace_until(ENGRAM_ID_A)

    assert grace_until is None


# ── storage-level: cleanup expired grace keys ─────────────────────────


async def test_cleanup_expired_grace_keys_removes_expired_rows(storage: Storage):
    """cleanup_expired_grace_keys deletes rows whose grace_until has passed."""
    kh = await _seed_key(storage)
    # Manually set an already-expired grace
    await storage.db.execute(
        "UPDATE invite_keys SET revoked_at = datetime('now', '-2 minutes'), "
        "grace_until = datetime('now', '-1 minute') WHERE key_hash = ?",
        (kh,),
    )
    await storage.db.commit()

    deleted = await storage.cleanup_expired_grace_keys(ENGRAM_ID_A)

    assert deleted == 1
    cursor = await storage.db.execute("SELECT key_hash FROM invite_keys WHERE key_hash = ?", (kh,))
    assert await cursor.fetchone() is None


async def test_cleanup_does_not_remove_active_or_grace_rows(storage: Storage):
    """cleanup_expired_grace_keys does not touch active keys or live grace windows."""
    kh_active = await _seed_key(storage)
    kh_grace = await _seed_key(storage)

    # Soft-revoke one (future grace)
    await storage.db.execute(
        "UPDATE invite_keys SET revoked_at = datetime('now'), "
        "grace_until = datetime('now', '+30 minutes') WHERE key_hash = ?",
        (kh_grace,),
    )
    await storage.db.commit()

    deleted = await storage.cleanup_expired_grace_keys(ENGRAM_ID_A)

    assert deleted == 0
    for kh in (kh_active, kh_grace):
        cursor = await storage.db.execute(
            "SELECT key_hash FROM invite_keys WHERE key_hash = ?", (kh,)
        )
        assert await cursor.fetchone() is not None


# ── storage-level: rotation history via audit log ─────────────────────


async def test_get_key_rotation_history_returns_entries(storage: Storage):
    """get_key_rotation_history returns key_rotation audit entries newest-first."""
    # Insert two synthetic rotation entries
    for i in range(2):
        await storage.insert_audit_entry(
            {
                "id": uuid.uuid4().hex,
                "operation": "key_rotation",
                "agent_id": None,
                "fact_id": None,
                "conflict_id": None,
                "extra": json.dumps({"old_generation": i, "new_generation": i + 1}),
                "timestamp": _ts(delta_seconds=i),
                "workspace_id": ENGRAM_ID_A,
            }
        )

    entries = await storage.get_key_rotation_history(ENGRAM_ID_A, limit=10)

    assert len(entries) == 2
    # Newest first
    extra_0 = (
        json.loads(entries[0]["extra"])
        if isinstance(entries[0]["extra"], str)
        else entries[0]["extra"]
    )
    extra_1 = (
        json.loads(entries[1]["extra"])
        if isinstance(entries[1]["extra"], str)
        else entries[1]["extra"]
    )
    assert extra_0["new_generation"] > extra_1["new_generation"]


async def test_get_key_rotation_history_empty_when_none(storage: Storage):
    """get_key_rotation_history returns [] when no rotations have occurred."""
    entries = await storage.get_key_rotation_history(ENGRAM_ID_A)
    assert entries == []


# ── storage-level: multiple rotations ────────────────────────────────


async def test_second_rotation_cleans_up_expired_grace(storage: Storage):
    """When rotating again, previously expired grace keys are hard-deleted."""
    kh = await _seed_key(storage)
    # First rotation — set grace to already-expired
    await storage.db.execute(
        "UPDATE invite_keys SET revoked_at = datetime('now', '-5 minutes'), "
        "grace_until = datetime('now', '-1 minute') WHERE key_hash = ?",
        (kh,),
    )
    await storage.db.commit()

    # Insert a new active key and rotate again
    kh2 = await _seed_key(storage)
    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    # Expired row (kh) should be gone; kh2 should be soft-revoked
    cursor = await storage.db.execute(
        "SELECT key_hash, revoked_at FROM invite_keys WHERE key_hash IN (?, ?)", (kh, kh2)
    )
    rows = {r["key_hash"]: r for r in await cursor.fetchall()}
    assert kh not in rows, "Expired grace key must be cleaned up on subsequent rotation"
    assert kh2 in rows
    assert rows[kh2]["revoked_at"] is not None


# ── storage-level: workspace isolation ───────────────────────────────


async def test_revoke_does_not_affect_other_workspace(storage_two_workspaces: Storage):
    """Revoking keys for workspace A must not touch workspace B's keys."""
    storage = storage_two_workspaces
    kh_a = await _seed_key(storage, ENGRAM_ID_A)
    kh_b = await _seed_key(storage, ENGRAM_ID_B)

    await storage.revoke_all_invite_keys(ENGRAM_ID_A, grace_minutes=15)

    cursor_b = await storage.db.execute(
        "SELECT revoked_at FROM invite_keys WHERE key_hash = ?", (kh_b,)
    )
    row_b = await cursor_b.fetchone()
    assert row_b is not None
    assert row_b["revoked_at"] is None, "Workspace B key must remain untouched"

    cursor_a = await storage.db.execute(
        "SELECT revoked_at FROM invite_keys WHERE key_hash = ?", (kh_a,)
    )
    row_a = await cursor_a.fetchone()
    assert row_a["revoked_at"] is not None


# ── engine-level: rotate_invite_key ──────────────────────────────────


@pytest.fixture
def mock_creator_ws():
    """Return a mock WorkspaceConfig that identifies the caller as creator."""
    ws = MagicMock()
    ws.db_url = "sqlite:///test.db"
    ws.engram_id = ENGRAM_ID_A
    ws.schema = "engram"
    ws.anonymous_mode = False
    ws.anon_agents = False
    ws.key_generation = 0
    ws.is_creator = True
    return ws


@pytest.fixture
def mock_non_creator_ws():
    """Return a mock WorkspaceConfig that identifies the caller as NOT creator."""
    ws = MagicMock()
    ws.db_url = "sqlite:///test.db"
    ws.engram_id = ENGRAM_ID_A
    ws.is_creator = False
    return ws


async def test_engine_rotate_raises_permission_error_for_non_creator(storage: Storage):
    """rotate_invite_key raises PermissionError when is_creator is False."""
    engine = EngramEngine(storage)

    with patch("engram.workspace.read_workspace") as mock_rw:
        mock_rw.return_value = MagicMock(
            db_url="sqlite:///test.db",
            engram_id=ENGRAM_ID_A,
            is_creator=False,
        )
        with pytest.raises(PermissionError, match="workspace creator"):
            await engine.rotate_invite_key(grace_minutes=15)


async def test_engine_rotate_raises_value_error_when_no_workspace(storage: Storage):
    """rotate_invite_key raises ValueError when no workspace is configured."""
    engine = EngramEngine(storage)

    with patch("engram.workspace.read_workspace") as mock_rw:
        mock_rw.return_value = None
        with pytest.raises(ValueError, match="No team workspace"):
            await engine.rotate_invite_key(grace_minutes=15)


async def test_engine_rotate_writes_audit_log(storage: Storage, mock_creator_ws: MagicMock):
    """rotate_invite_key writes a key_rotation audit log entry."""
    engine = EngramEngine(storage)
    await _seed_workspace(storage)  # ensure workspace row exists

    with (
        patch("engram.workspace.read_workspace", return_value=mock_creator_ws),
        patch("engram.workspace.write_workspace"),
        patch("engram.workspace.generate_invite_key", return_value=("ek_live_test", _key_hash())),
        patch("engram.workspace.WorkspaceConfig"),
    ):
        await engine.rotate_invite_key(grace_minutes=10, reason="test rotation", actor="test-user")

    entries = await storage.get_key_rotation_history(ENGRAM_ID_A, limit=5)
    assert len(entries) >= 1
    extra = entries[0].get("extra")
    if isinstance(extra, str):
        extra = json.loads(extra)
    assert extra["reason"] == "test rotation"
    assert extra["actor"] == "test-user"
    assert extra["grace_minutes"] == 10
    assert "new_generation" in extra


async def test_engine_rotate_bumps_key_generation(storage: Storage, mock_creator_ws: MagicMock):
    """rotate_invite_key increments the key_generation in the DB."""
    engine = EngramEngine(storage)
    await _seed_workspace(storage)

    gen_before = await storage.get_key_generation(ENGRAM_ID_A)

    with (
        patch("engram.workspace.read_workspace", return_value=mock_creator_ws),
        patch("engram.workspace.write_workspace"),
        patch("engram.workspace.generate_invite_key", return_value=("ek_live_test", _key_hash())),
        patch("engram.workspace.WorkspaceConfig"),
    ):
        result = await engine.rotate_invite_key(grace_minutes=5)

    gen_after = await storage.get_key_generation(ENGRAM_ID_A)
    assert gen_after == gen_before + 1
    assert result["new_generation"] == gen_after
    assert result["old_generation"] == gen_before


async def test_engine_rotate_returns_grace_until_when_grace_set(
    storage: Storage, mock_creator_ws: MagicMock
):
    """rotate_invite_key returns a grace_until string when grace_minutes > 0."""
    engine = EngramEngine(storage)
    await _seed_workspace(storage)

    with (
        patch("engram.workspace.read_workspace", return_value=mock_creator_ws),
        patch("engram.workspace.write_workspace"),
        patch("engram.workspace.generate_invite_key", return_value=("ek_live_test", _key_hash())),
        patch("engram.workspace.WorkspaceConfig"),
    ):
        result = await engine.rotate_invite_key(grace_minutes=20)

    assert result["grace_until"] is not None
    grace_str = result["grace_until"].replace("+00:00", "").rstrip("Z")
    grace_dt = datetime.fromisoformat(grace_str)
    assert grace_dt > datetime.now(timezone.utc).replace(tzinfo=None)


async def test_engine_rotate_returns_none_grace_when_immediate(
    storage: Storage, mock_creator_ws: MagicMock
):
    """rotate_invite_key returns None for grace_until when grace_minutes=0."""
    engine = EngramEngine(storage)
    await _seed_workspace(storage)

    with (
        patch("engram.workspace.read_workspace", return_value=mock_creator_ws),
        patch("engram.workspace.write_workspace"),
        patch("engram.workspace.generate_invite_key", return_value=("ek_live_test", _key_hash())),
        patch("engram.workspace.WorkspaceConfig"),
    ):
        result = await engine.rotate_invite_key(grace_minutes=0)

    assert result["grace_until"] is None
