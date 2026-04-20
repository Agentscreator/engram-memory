"""Workspace search API — returns facts and conflicts for the memory graph UI.

POST /workspace/search
  Body: {"engram_id": "ENG-XXXX-XXXX", "invite_key": "ek_live_..."}
  Returns: {"facts": [...], "conflicts": [...], "agents": [...]}
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DB_URL = os.environ.get("ENGRAM_DB_URL", "")
SCHEMA = "engram"

_pool: Any = None

_WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    engram_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    anonymous_mode BOOLEAN NOT NULL DEFAULT false,
    anon_agents BOOLEAN NOT NULL DEFAULT false,
    key_generation INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS storage_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free';
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS display_name TEXT;

CREATE TABLE IF NOT EXISTS invite_keys (
    key_hash TEXT PRIMARY KEY,
    engram_id TEXT NOT NULL REFERENCES workspaces(engram_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    uses_remaining INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stripe_customer_id TEXT
);

CREATE TABLE IF NOT EXISTS user_workspaces (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    engram_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    PRIMARY KEY (user_id, engram_id)
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'general',
    confidence REAL NOT NULL DEFAULT 0.9,
    fact_type TEXT NOT NULL DEFAULT 'observation',
    agent_id TEXT NOT NULL DEFAULT 'agent',
    engineer TEXT,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ,
    memory_op TEXT NOT NULL DEFAULT 'add',
    supersedes_fact_id TEXT,
    workspace_id TEXT NOT NULL,
    durability TEXT NOT NULL DEFAULT 'durable'
);

CREATE TABLE IF NOT EXISTS conflicts (
    id TEXT PRIMARY KEY,
    fact_a_id TEXT NOT NULL,
    fact_b_id TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    explanation TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    resolved_at TIMESTAMPTZ,
    resolution TEXT,
    resolution_type TEXT,
    workspace_id TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_pair_unique ON conflicts(
    workspace_id, LEAST(fact_a_id, fact_b_id), GREATEST(fact_a_id, fact_b_id)
);

CREATE TABLE IF NOT EXISTS dismissed_conflicts (
    conflict_id TEXT PRIMARY KEY REFERENCES conflicts(id),
    workspace_id TEXT NOT NULL,
    dismissed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dismissed_conflicts_workspace
    ON dismissed_conflicts(workspace_id);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    engineer TEXT,
    label TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ,
    total_commits INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, workspace_id)
);
"""

_WORKSPACE_SCHEMA_STMTS = [s.strip() for s in _WORKSPACE_SCHEMA.split(";") if s.strip()]


async def _get_pool() -> Any:
    global _pool
    if not DB_URL:
        raise RuntimeError("ENGRAM_DB_URL environment variable is not set")
    if _pool is None:
        import asyncpg

        async def _set_path(c: Any) -> None:
            await c.execute(f"SET search_path TO {SCHEMA}, public")

        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            await conn.execute(f"SET search_path TO {SCHEMA}, public")
            for stmt in _WORKSPACE_SCHEMA_STMTS:
                await conn.execute(stmt)
        finally:
            await conn.close()

        _pool = await asyncpg.create_pool(
            DB_URL, min_size=1, max_size=3, command_timeout=30, init=_set_path
        )
    return _pool


# ── Invite key auth (mirrored from api/mcp.py) ──────────────────────


def _xor(data: bytes, enc_key: bytes, iv: bytes) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        block = hashlib.sha256(enc_key + iv + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    ks = bytes(stream[: len(data)])
    return bytes(a ^ b for a, b in zip(data, ks))


def _decode_invite_key(invite_key: str) -> dict[str, Any]:
    if not invite_key.startswith("ek_live_"):
        raise ValueError("Invalid invite key format")
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    token = base64.urlsafe_b64decode(b64)
    if len(token) < 81:
        raise ValueError("Invite key too short")
    enc_key = token[:32]
    iv = token[32:48]
    mac = token[48:80]
    ciphertext = token[80:]
    expected = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("Invite key authentication failed")
    payload = json.loads(_xor(ciphertext, enc_key, iv))
    if payload.get("expires_at", 0) < int(time.time()):
        raise ValueError("Invite key has expired")
    return payload


def _invite_key_hash(invite_key: str) -> str:
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    token = base64.urlsafe_b64decode(b64)
    return hashlib.sha256(token[:32]).hexdigest()


async def _validate_key(invite_key: str, engram_id: str, pool: Any) -> bool:
    try:
        payload = _decode_invite_key(invite_key)
        if payload["engram_id"] != engram_id:
            return False
        key_hash = _invite_key_hash(invite_key)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT uses_remaining FROM {SCHEMA}.invite_keys WHERE key_hash = $1 AND engram_id = $2",
                key_hash,
                engram_id,
            )
        if not row:
            return False
        if row["uses_remaining"] is not None and row["uses_remaining"] <= 0:
            return False
        return True
    except Exception:
        return False


# ── Search handler ───────────────────────────────────────────────────


async def handle_search(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = body.get("engram_id", "").strip()
    invite_key = body.get("invite_key", "").strip()

    if not engram_id or not invite_key:
        return JSONResponse({"error": "engram_id and invite_key are required"}, status_code=400)

    try:
        pool = await _get_pool()
    except Exception as exc:
        return JSONResponse({"error": f"Database connection failed: {exc}"}, status_code=500)

    if not await _validate_key(invite_key, engram_id, pool):
        return JSONResponse({"error": "Invalid invite key or workspace ID"}, status_code=401)

    fact_rows: list = []
    conflict_rows: list = []
    agent_rows: list = []
    storage_bytes: int = 0
    try:
        async with pool.acquire() as conn:
            ws_row = await conn.fetchrow(
                f"SELECT storage_bytes FROM {SCHEMA}.workspaces WHERE engram_id = $1",
                engram_id,
            )
            if ws_row:
                storage_bytes = ws_row["storage_bytes"] or 0
            fact_rows = await conn.fetch(
                f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                          committed_at, valid_until, memory_op, supersedes_fact_id, durability
                   FROM {SCHEMA}.facts
                   WHERE workspace_id = $1
                   ORDER BY committed_at DESC
                   LIMIT 500""",
                engram_id,
            )
            conflict_rows = await conn.fetch(
                f"""SELECT id, fact_a_id, fact_b_id, explanation, severity, status, detected_at
                   FROM {SCHEMA}.conflicts
                   WHERE workspace_id = $1
                     AND NOT EXISTS (
                         SELECT 1 FROM {SCHEMA}.dismissed_conflicts dc
                         WHERE dc.conflict_id = {SCHEMA}.conflicts.id
                           AND dc.workspace_id = {SCHEMA}.conflicts.workspace_id
                     )
                   ORDER BY detected_at DESC
                   LIMIT 200""",
                engram_id,
            )
            agent_rows = await conn.fetch(
                f"""SELECT agent_id, engineer, label, last_seen, total_commits
                   FROM {SCHEMA}.agents WHERE workspace_id = $1""",
                engram_id,
            )
    except Exception:
        # Tables may not exist yet if no MCP commits have been made — return empty workspace
        pass

    def _ser(v: Any) -> Any:
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    facts = [{k: _ser(v) for k, v in dict(r).items()} for r in fact_rows]
    conflicts = [{k: _ser(v) for k, v in dict(r).items()} for r in conflict_rows]
    agents = [{k: _ser(v) for k, v in dict(r).items()} for r in agent_rows]

    return JSONResponse(
        {
            "facts": facts,
            "conflicts": conflicts,
            "agents": agents,
            "workspace_id": engram_id,
            "storage_bytes": storage_bytes,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def handle_session_search(request: Request) -> JSONResponse:
    """Session-cookie-authenticated workspace data fetch (for dashboard UI)."""
    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json
    import time as _time
    import base64 as _base64

    def _get_session(req: Request) -> dict | None:
        token = req.cookies.get("engram_session")
        if not token:
            return None
        secret = (
            os.environ.get("ENGRAM_JWT_SECRET") or "engram-dev-secret-change-in-production"
        ).encode()
        parts = token.split(".")
        if len(parts) != 3:
            return None
        hdr, body, sig = parts
        msg = f"{hdr}.{body}".encode()
        expected = (
            _base64.urlsafe_b64encode(_hmac.new(secret, msg, _hashlib.sha256).digest())
            .rstrip(b"=")
            .decode()
        )
        if not _hmac.compare_digest(sig, expected):
            return None
        padded = body + "=" * (4 - len(body) % 4)
        payload = _json.loads(_base64.urlsafe_b64decode(padded))
        if payload.get("exp", 0) < int(_time.time()):
            return None
        return payload

    session = _get_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    engram_id = request.query_params.get("engram_id", "").strip()
    if not engram_id:
        return JSONResponse({"error": "engram_id required"}, status_code=400)

    try:
        pool = await _get_pool()
    except Exception as exc:
        return JSONResponse({"error": f"Database connection failed: {exc}"}, status_code=500)

    # Verify user owns this workspace
    try:
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )
    except Exception:
        owns = None

    if not owns:
        return JSONResponse({"error": "Workspace not found or access denied"}, status_code=403)

    fact_rows: list = []
    conflict_rows: list = []
    agent_rows: list = []
    storage_bytes: int = 0
    try:
        async with pool.acquire() as conn:
            ws_row = await conn.fetchrow(
                f"SELECT storage_bytes FROM {SCHEMA}.workspaces WHERE engram_id = $1",
                engram_id,
            )
            if ws_row:
                storage_bytes = ws_row["storage_bytes"] or 0
            fact_rows = await conn.fetch(
                f"""SELECT id, lineage_id, content, scope, confidence, fact_type,
                          committed_at, valid_until, memory_op, supersedes_fact_id, durability
                   FROM {SCHEMA}.facts
                   WHERE workspace_id = $1
                   ORDER BY committed_at DESC
                   LIMIT 500""",
                engram_id,
            )
            agent_rows = await conn.fetch(
                f"""SELECT agent_id, engineer, label, last_seen, total_commits
                   FROM {SCHEMA}.agents WHERE workspace_id = $1""",
                engram_id,
            )
    except Exception:
        # Tables may not exist yet if no MCP commits have been made — return empty workspace
        pass

    # Run heuristic conflict detection before returning so the dashboard always
    # shows fresh conflicts without waiting for the next commit.
    try:
        from api.mcp import _detect_conflicts_heuristic

        await _detect_conflicts_heuristic(engram_id, pool)
    except Exception:
        pass

    try:
        async with pool.acquire() as conn:
            conflict_rows = await conn.fetch(
                f"""SELECT id, fact_a_id, fact_b_id, explanation, severity, status, detected_at
                   FROM {SCHEMA}.conflicts
                   WHERE workspace_id = $1
                     AND NOT EXISTS (
                         SELECT 1 FROM {SCHEMA}.dismissed_conflicts dc
                         WHERE dc.conflict_id = {SCHEMA}.conflicts.id
                           AND dc.workspace_id = {SCHEMA}.conflicts.workspace_id
                     )
                   ORDER BY detected_at DESC
                   LIMIT 200""",
                engram_id,
            )
    except Exception:
        pass

    def _ser(v: Any) -> Any:
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    facts = [{k: _ser(v) for k, v in dict(r).items()} for r in fact_rows]
    conflicts = [{k: _ser(v) for k, v in dict(r).items()} for r in conflict_rows]
    agents = [{k: _ser(v) for k, v in dict(r).items()} for r in agent_rows]

    return JSONResponse(
        {
            "facts": facts,
            "conflicts": conflicts,
            "agents": agents,
            "workspace_id": engram_id,
            "storage_bytes": storage_bytes,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def handle_options(request: Request) -> Response:
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


app = Starlette(
    routes=[
        Route("/workspace/search", handle_search, methods=["POST"]),
        Route("/workspace/search", handle_options, methods=["OPTIONS"]),
        Route("/workspace/session", handle_session_search, methods=["GET"]),
        Route("/workspace/{path:path}", handle_search, methods=["POST"]),
    ]
)
