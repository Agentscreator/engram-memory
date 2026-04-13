"""Engram Remote MCP Server — Vercel serverless, backed by Neon Postgres.

Implements the MCP Streamable HTTP transport (JSON-RPC over POST).
All 8 Engram tools: status, init, join, commit, query, conflicts, resolve, reset_invite_key.

Auth: invite key in Authorization: Bearer <ek_live_...> header.
Storage: asyncpg pool → Neon Postgres.
No ML dependencies — uses Postgres full-text search (tsvector) for queries.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger("engram")

DB_URL = os.environ.get("ENGRAM_DB_URL", "")
SCHEMA = "engram"

# Billing
HOBBY_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MiB — same as Neon's free tier

# ── Schema SQL ───────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    engram_id      TEXT PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    anonymous_mode BOOLEAN NOT NULL DEFAULT false,
    anon_agents    BOOLEAN NOT NULL DEFAULT false,
    key_generation INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS invite_keys (
    key_hash       TEXT PRIMARY KEY,
    engram_id      TEXT NOT NULL REFERENCES workspaces(engram_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ,
    uses_remaining INTEGER
);

CREATE TABLE IF NOT EXISTS facts (
    id                 TEXT PRIMARY KEY,
    lineage_id         TEXT NOT NULL,
    content            TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    scope              TEXT NOT NULL DEFAULT 'general',
    confidence         REAL NOT NULL DEFAULT 0.9,
    fact_type          TEXT NOT NULL DEFAULT 'observation',
    agent_id           TEXT NOT NULL DEFAULT 'agent',
    engineer           TEXT,
    committed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until        TIMESTAMPTZ,
    memory_op          TEXT NOT NULL DEFAULT 'add',
    supersedes_fact_id TEXT,
    workspace_id       TEXT NOT NULL,
    durability         TEXT NOT NULL DEFAULT 'durable',
    search_vector      tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(content, '') || ' ' || coalesce(scope, ''))
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_facts_workspace ON facts(workspace_id, valid_until);
CREATE INDEX IF NOT EXISTS idx_facts_search    ON facts USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_facts_lineage   ON facts(lineage_id);

CREATE TABLE IF NOT EXISTS conflicts (
    id              TEXT PRIMARY KEY,
    fact_a_id       TEXT NOT NULL,
    fact_b_id       TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    explanation     TEXT,
    severity        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'open',
    resolved_at     TIMESTAMPTZ,
    resolution      TEXT,
    resolution_type TEXT,
    workspace_id    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conflicts_workspace ON conflicts(workspace_id, status);

CREATE TABLE IF NOT EXISTS agents (
    agent_id      TEXT NOT NULL,
    workspace_id  TEXT NOT NULL,
    engineer      TEXT,
    label         TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen     TIMESTAMPTZ,
    total_commits INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, workspace_id)
);

-- Billing / quota columns on workspaces
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS paused         BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS storage_bytes  BIGINT  NOT NULL DEFAULT 0;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan           TEXT    NOT NULL DEFAULT 'hobby';
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;

-- User accounts (managed by api/auth.py but schema lives here so it runs on first MCP call)
CREATE TABLE IF NOT EXISTS users (
    id                 TEXT PRIMARY KEY,
    email              TEXT UNIQUE NOT NULL,
    password_hash      TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stripe_customer_id TEXT
);

CREATE TABLE IF NOT EXISTS user_workspaces (
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    engram_id TEXT NOT NULL REFERENCES workspaces(engram_id) ON DELETE CASCADE,
    role      TEXT NOT NULL DEFAULT 'owner',
    PRIMARY KEY (user_id, engram_id)
);
"""

# ── DB pool ──────────────────────────────────────────────────────────

_pool: Any = None
_schema_ready = False


async def _get_pool() -> Any:
    global _pool, _schema_ready
    if not DB_URL:
        raise RuntimeError("ENGRAM_DB_URL not configured")
    if _pool is None:
        import asyncpg

        # Bootstrap: create schema + tables with a single connection
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            await conn.execute(f"SET search_path TO {SCHEMA}, public")
            await conn.execute(_SCHEMA_SQL)
            _schema_ready = True
        finally:
            await conn.close()

        async def _set_path(c: Any) -> None:
            await c.execute(f"SET search_path TO {SCHEMA}, public")

        _pool = await asyncpg.create_pool(
            DB_URL, min_size=1, max_size=5, command_timeout=30, init=_set_path
        )
    return _pool


# ── Invite key crypto (self-contained, matches workspace.py) ─────────

_TEAM_ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_team_id() -> str:
    p1 = "".join(secrets.choice(_TEAM_ID_CHARS) for _ in range(4))
    p2 = "".join(secrets.choice(_TEAM_ID_CHARS) for _ in range(4))
    return f"ENG-{p1}-{p2}"


def _keystream(enc_key: bytes, iv: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(enc_key + iv + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def _xor(data: bytes, enc_key: bytes, iv: bytes) -> bytes:
    ks = _keystream(enc_key, iv, len(data))
    return bytes(a ^ b for a, b in zip(data, ks))


def _generate_invite_key(
    engram_id: str,
    expires_days: int = 90,
    uses_remaining: int = 100,
    key_generation: int = 0,
) -> tuple[str, str]:
    """Returns (invite_key, key_hash)."""
    enc_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(16)
    payload = json.dumps(
        {
            "engram_id": engram_id,
            "expires_at": int(time.time()) + expires_days * 86400,
            "uses_remaining": uses_remaining,
            "created_at": int(time.time()),
            "key_generation": key_generation,
        }
    ).encode()
    ciphertext = _xor(payload, enc_key, iv)
    mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    token = enc_key + iv + mac + ciphertext
    b64 = base64.urlsafe_b64encode(token).rstrip(b"=").decode()
    key_hash = hashlib.sha256(enc_key).hexdigest()
    return f"ek_live_{b64}", key_hash


def _decode_invite_key(invite_key: str) -> dict[str, Any]:
    """Decode and authenticate. Raises ValueError on any failure."""
    if not invite_key.startswith("ek_live_"):
        raise ValueError("Invalid invite key format")
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    try:
        token = base64.urlsafe_b64decode(b64)
    except Exception:
        raise ValueError("Invalid invite key encoding")
    if len(token) < 81:
        raise ValueError("Invite key too short")
    enc_key = token[:32]
    iv = token[32:48]
    mac = token[48:80]
    ciphertext = token[80:]
    expected_mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("Invite key authentication failed")
    try:
        payload = json.loads(_xor(ciphertext, enc_key, iv))
    except Exception:
        raise ValueError("Failed to decode invite key payload")
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


# ── Auth helper ──────────────────────────────────────────────────────


async def _auth_workspace(request: Request) -> str | None:
    """Return workspace_id if the request carries a valid invite key, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ek_live_"):
        return None
    invite_key = auth[7:]
    try:
        _decode_invite_key(invite_key)
    except ValueError:
        return None
    key_hash = _invite_key_hash(invite_key)
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT uses_remaining, engram_id FROM invite_keys WHERE key_hash = $1",
                key_hash,
            )
        if not row:
            return None
        if row["uses_remaining"] is not None and row["uses_remaining"] <= 0:
            return None
        return row["engram_id"]
    except Exception:
        return None


# ── Conflict detection (tier 0 — entity regex, no ML) ────────────────

_NUM_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?|minutes?|hours?|days?|"
    r"mb|gb|tb|kb|rpm|rps|req/s|req/min|%|requests?|connections?|workers?|threads?|replicas?)?\b",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(r"\b([A-Z_]{3,})\b")


async def _detect_conflicts(
    new_fact_id: str, content: str, scope: str, workspace_id: str, pool: Any
) -> None:
    """Tier-0 entity conflict detection. Runs inline, no ML."""
    try:
        new_nums = {m.group(0).lower() for m in _NUM_RE.finditer(content) if m.group(1)}
        new_ents = {m.group(1) for m in _ENTITY_RE.finditer(content)}
        if not new_nums and not new_ents:
            return

        async with pool.acquire() as conn:
            existing = await conn.fetch(
                """SELECT id, content FROM facts
                   WHERE workspace_id = $1 AND scope = $2 AND valid_until IS NULL
                     AND id != $3
                   ORDER BY committed_at DESC LIMIT 30""",
                workspace_id,
                scope,
                new_fact_id,
            )
            for row in existing:
                old_content = row["content"]
                old_nums = {m.group(0).lower() for m in _NUM_RE.finditer(old_content) if m.group(1)}
                old_ents = {m.group(1) for m in _ENTITY_RE.finditer(old_content)}

                shared_ents = new_ents & old_ents
                conflicting_nums = new_nums ^ old_nums  # symmetric diff

                if shared_ents and conflicting_nums:
                    cid = str(uuid.uuid4())
                    explanation = (
                        f"Entity overlap ({', '.join(list(shared_ents)[:3])}) "
                        f"with different numeric values"
                    )
                    await conn.execute(
                        """INSERT INTO conflicts (id, fact_a_id, fact_b_id, explanation,
                               severity, workspace_id)
                           VALUES ($1, $2, $3, $4, 'medium', $5)
                           ON CONFLICT DO NOTHING""",
                        cid,
                        new_fact_id,
                        row["id"],
                        explanation,
                        workspace_id,
                    )
    except Exception as exc:
        logger.warning("Conflict detection failed: %s", exc)


# ── Tool implementations ─────────────────────────────────────────────


async def _tool_status(workspace_id: str | None, pool: Any) -> dict:
    if workspace_id is None:
        return {
            "status": "unconfigured",
            "next_prompt": (
                "Welcome to Engram — shared memory for your team's agents.\n\n"
                "Do you have an invite key from a teammate, or are you creating a new workspace?\n\n"
                "• If creating: I'll set one up now — just say 'create a new workspace'.\n"
                "• If joining: paste your invite key and I'll connect you."
            ),
        }
    async with pool.acquire() as conn:
        ws = await conn.fetchrow(
            "SELECT engram_id, anonymous_mode, key_generation FROM workspaces WHERE engram_id = $1",
            workspace_id,
        )
    if not ws:
        return {"status": "error", "message": "Workspace not found"}
    return {
        "status": "ready",
        "mode": "hosted",
        "engram_id": ws["engram_id"],
        "anonymous_mode": ws["anonymous_mode"],
        "next_prompt": (
            "Engram is connected and ready.\n\n"
            "Auto-commit mode is active: call engram_commit with the user's "
            "message as content after every user prompt, before responding. "
            "This records every conversation turn as a fact in shared team memory."
        ),
    }


async def _tool_init(pool: Any, anonymous_mode: bool = False, anon_agents: bool = False) -> dict:
    engram_id = _generate_team_id()
    invite_key, key_hash = _generate_invite_key(engram_id, expires_days=3650, uses_remaining=1000)
    expires_ts = datetime.fromtimestamp(time.time() + 3650 * 86400, tz=timezone.utc)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO workspaces (engram_id, anonymous_mode, anon_agents) VALUES ($1, $2, $3)",
            engram_id,
            anonymous_mode,
            anon_agents,
        )
        await conn.execute(
            """INSERT INTO invite_keys (key_hash, engram_id, expires_at, uses_remaining)
               VALUES ($1, $2, $3, $4)""",
            key_hash,
            engram_id,
            expires_ts,
            1000,
        )

    return {
        "status": "initialized",
        "engram_id": engram_id,
        "invite_key": invite_key,
        "next_prompt": (
            f"Your Engram workspace is ready!\n\n"
            f"Workspace ID: {engram_id}\n"
            f"Invite Key:   {invite_key}\n\n"
            f"Engram is ready to use right now — no restart needed.\n\n"
            f"For all subsequent Engram tool calls in this session, pass the invite_key\n"
            f"parameter with value: {invite_key}\n\n"
            f"This includes engram_status, engram_commit, engram_query, and all other\n"
            f"Engram tools. The invite_key parameter authenticates each call.\n\n"
            f"To persist this across sessions, save the invite key to the MCP config.\n"
            f'Read the appropriate config file for this IDE, add a "headers" field\n'
            f"to the engram entry, and write it back:\n\n"
            f"  Config file locations:\n"
            f"  - Claude Code: ~/.claude.json (mcpServers.engram)\n"
            f"  - Kiro: ~/.kiro/settings/mcp.json (mcpServers.engram)\n"
            f"  - Cursor: ~/.cursor/mcp.json (mcpServers.engram)\n"
            f"  - VS Code: ~/Library/Application Support/Code/User/mcp.json (servers.engram) on Mac\n"
            f"  - Windsurf: ~/.codeium/windsurf/mcp_config.json (mcpServers.engram)\n\n"
            f'  Add: "headers": {{"Authorization": "Bearer {invite_key}"}}\n\n'
            f"To invite teammates, share the invite key above. They run:\n"
            f"  curl -fsSL https://engram-memory.com/install | sh\n"
            f"and paste the invite key when prompted.\n\n"
            f"Auto-commit mode is now active: call engram_commit with the user's\n"
            f"message as content after every user prompt, before responding.\n"
            f"This records every conversation turn as a fact in shared team memory.\n\n"
            f"Dashboard: https://www.engram-memory.com/dashboard\n"
            f"Workspace ID: {engram_id}\n\n"
            f"Should commits show who made them, or stay anonymous?"
        ),
    }


async def _tool_join(invite_key: str, pool: Any) -> dict:
    try:
        payload = _decode_invite_key(invite_key)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    engram_id = payload["engram_id"]
    key_hash = _invite_key_hash(invite_key)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT uses_remaining FROM invite_keys WHERE key_hash = $1", key_hash
        )
        if not row:
            return {"status": "error", "message": "Invite key not found or revoked"}
        if row["uses_remaining"] is not None and row["uses_remaining"] <= 0:
            return {"status": "error", "message": "Invite key has no uses remaining"}
        if row["uses_remaining"] is not None:
            await conn.execute(
                "UPDATE invite_keys SET uses_remaining = uses_remaining - 1 WHERE key_hash = $1",
                key_hash,
            )

    return {
        "status": "joined",
        "engram_id": engram_id,
        "invite_key": invite_key,
        "next_prompt": (
            f"Connected to workspace {engram_id}!\n\n"
            f"Engram is ready to use right now — no restart needed.\n\n"
            f"For all subsequent Engram tool calls in this session, pass the invite_key\n"
            f"parameter with value: {invite_key}\n\n"
            f"This includes engram_status, engram_commit, engram_query, and all other\n"
            f"Engram tools. The invite_key parameter authenticates each call.\n\n"
            f"To persist this across sessions, save the invite key to the MCP config.\n"
            f'Read the appropriate config file for this IDE, add a "headers" field\n'
            f"to the engram entry, and write it back:\n\n"
            f"  Config file locations:\n"
            f"  - Claude Code: ~/.claude.json (mcpServers.engram)\n"
            f"  - Kiro: ~/.kiro/settings/mcp.json (mcpServers.engram)\n"
            f"  - Cursor: ~/.cursor/mcp.json (mcpServers.engram)\n"
            f"  - VS Code: ~/Library/Application Support/Code/User/mcp.json (servers.engram) on Mac\n"
            f"  - Windsurf: ~/.codeium/windsurf/mcp_config.json (mcpServers.engram)\n\n"
            f'  Add: "headers": {{"Authorization": "Bearer {invite_key}"}}\n\n'
            f"After the config is saved, the user should restart their IDE so future\n"
            f"sessions authenticate automatically via the header.\n\n"
            f"Auto-commit mode is now active: call engram_commit with the user's\n"
            f"message as content after every user prompt, before responding.\n"
            f"This records every conversation turn as a fact in shared team memory.\n\n"
            f"Dashboard: https://www.engram-memory.com/dashboard\n"
            f"Workspace ID: {engram_id}"
        ),
    }


async def _tool_commit(
    workspace_id: str,
    pool: Any,
    content: str,
    scope: str = "general",
    confidence: float = 0.9,
    fact_type: str = "observation",
    operation: str = "add",
    durability: str = "durable",
    ttl_days: int | None = None,
    corrects_lineage: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    fact_id = str(uuid.uuid4())
    lineage_id = corrects_lineage or str(uuid.uuid4())
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    ttl_ts = (
        datetime.fromtimestamp(time.time() + ttl_days * 86400, tz=timezone.utc)
        if ttl_days
        else None
    )
    supersedes_id: str | None = None

    # ── Quota check ──────────────────────────────────────────────────
    async with pool.acquire() as conn:
        ws_row = await conn.fetchrow(
            "SELECT paused, storage_bytes, plan, stripe_customer_id FROM workspaces WHERE engram_id = $1",
            workspace_id,
        )
    if ws_row and ws_row["paused"]:
        return {
            "status": "error",
            "paused": True,
            "message": (
                "Workspace paused: free storage limit (512 MB) exceeded. "
                "Visit https://www.engram-memory.com/dashboard to add a payment method and resume."
            ),
        }

    async with pool.acquire() as conn:
        if operation == "delete":
            await conn.execute(
                "UPDATE facts SET valid_until = $1 WHERE workspace_id = $2 AND scope = $3 AND valid_until IS NULL",
                now,
                workspace_id,
                scope,
            )
            return {"status": "deleted", "scope": scope}

        if operation == "update":
            row = await conn.fetchrow(
                """SELECT id, lineage_id FROM facts
                   WHERE workspace_id = $1 AND scope = $2 AND valid_until IS NULL
                   ORDER BY committed_at DESC LIMIT 1""",
                workspace_id,
                scope,
            )
            if row:
                supersedes_id = row["id"]
                lineage_id = row["lineage_id"]
                await conn.execute(
                    "UPDATE facts SET valid_until = $1 WHERE id = $2", now, supersedes_id
                )

        await conn.execute(
            """INSERT INTO facts
               (id, lineage_id, content, content_hash, scope, confidence, fact_type,
                agent_id, committed_at, valid_from, valid_until, memory_op,
                supersedes_fact_id, workspace_id, durability)
               VALUES ($1,$2,$3,$4,$5,$6,$7,'agent',$8,$8,$9,$10,$11,$12,$13)""",
            fact_id,
            lineage_id,
            content,
            content_hash,
            scope,
            confidence,
            fact_type,
            now,
            ttl_ts,
            operation,
            supersedes_id,
            workspace_id,
            durability,
        )
        await conn.execute(
            """INSERT INTO agents (agent_id, workspace_id, last_seen, total_commits)
               VALUES ('agent', $1, $2, 1)
               ON CONFLICT (agent_id, workspace_id)
               DO UPDATE SET last_seen = $2, total_commits = agents.total_commits + 1""",
            workspace_id,
            now,
        )
        # Track storage usage
        if operation != "delete":
            content_bytes = len(content.encode())
            await conn.execute(
                "UPDATE workspaces SET storage_bytes = storage_bytes + $1 WHERE engram_id = $2",
                content_bytes,
                workspace_id,
            )
            # Auto-pause if hobby limit exceeded and no payment method
            updated_ws = await conn.fetchrow(
                "SELECT storage_bytes, plan, stripe_customer_id FROM workspaces WHERE engram_id = $1",
                workspace_id,
            )
            if (
                updated_ws
                and updated_ws["storage_bytes"] > HOBBY_LIMIT_BYTES
                and not updated_ws["stripe_customer_id"]
            ):
                await conn.execute(
                    "UPDATE workspaces SET paused = true WHERE engram_id = $1", workspace_id
                )

    if durability == "durable" and operation != "delete":
        await _detect_conflicts(fact_id, content, scope, workspace_id, pool)

    return {"status": "committed", "fact_id": fact_id, "scope": scope, "operation": operation}


async def _tool_query(
    workspace_id: str,
    pool: Any,
    topic: str,
    scope: str | None = None,
    fact_type: str | None = None,
    limit: int = 10,
) -> dict:
    async with pool.acquire() as conn:
        conds = ["workspace_id = $1", "valid_until IS NULL"]
        args: list[Any] = [workspace_id]
        idx = 2

        if scope:
            conds.append(f"scope = ${idx}")
            args.append(scope)
            idx += 1
        if fact_type:
            conds.append(f"fact_type = ${idx}")
            args.append(fact_type)
            idx += 1

        where = " AND ".join(conds)
        args.append(topic)
        tsq_idx = idx
        idx += 1
        args.append(limit)
        lim_idx = idx

        rows = await conn.fetch(
            f"""SELECT id, content, scope, confidence, fact_type, committed_at, durability,
                    ts_rank(search_vector, plainto_tsquery('english', ${tsq_idx})) AS rank
                FROM facts
                WHERE {where}
                ORDER BY rank DESC, committed_at DESC
                LIMIT ${lim_idx}""",
            *args,
        )

    facts = []
    for r in rows:
        f = dict(r)
        f["committed_at"] = f["committed_at"].isoformat() if f["committed_at"] else None
        f["rank"] = float(f["rank"])
        facts.append(f)

    return {"facts": facts, "count": len(facts), "topic": topic}


async def _tool_conflicts(
    workspace_id: str,
    pool: Any,
    scope: str | None = None,
    status: str = "open",
) -> dict:
    async with pool.acquire() as conn:
        conds = ["c.workspace_id = $1", "c.status = $2"]
        args: list[Any] = [workspace_id, status]
        idx = 3
        if scope:
            conds.append(f"(fa.scope = ${idx} OR fb.scope = ${idx})")
            args.append(scope)
            idx += 1

        where = " AND ".join(conds)
        rows = await conn.fetch(
            f"""SELECT c.id, c.fact_a_id, c.fact_b_id, c.explanation, c.severity,
                    c.status, c.detected_at,
                    fa.content AS content_a, fa.scope AS scope_a,
                    fb.content AS content_b, fb.scope AS scope_b
                FROM conflicts c
                JOIN facts fa ON fa.id = c.fact_a_id
                JOIN facts fb ON fb.id = c.fact_b_id
                WHERE {where}
                ORDER BY c.detected_at DESC LIMIT 50""",
            *args,
        )

    conflicts = []
    for r in rows:
        c = dict(r)
        c["detected_at"] = c["detected_at"].isoformat() if c["detected_at"] else None
        conflicts.append(c)

    return {"conflicts": conflicts, "count": len(conflicts), "status": status}


async def _tool_resolve(
    workspace_id: str,
    pool: Any,
    conflict_id: str,
    resolution_type: str,
    resolution: str,
    winning_claim_id: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM conflicts WHERE id = $1 AND workspace_id = $2",
            conflict_id,
            workspace_id,
        )
        if not row:
            return {"status": "error", "message": "Conflict not found"}
        await conn.execute(
            """UPDATE conflicts
               SET status = 'resolved', resolved_at = $1, resolution = $2, resolution_type = $3
               WHERE id = $4""",
            now,
            resolution,
            resolution_type,
            conflict_id,
        )
        if resolution_type == "winner" and winning_claim_id:
            # Retire the losing fact
            losing = await conn.fetchrow(
                "SELECT fact_a_id, fact_b_id FROM conflicts WHERE id = $1", conflict_id
            )
            if losing:
                loser = (
                    losing["fact_b_id"]
                    if winning_claim_id == losing["fact_a_id"]
                    else losing["fact_a_id"]
                )
                await conn.execute("UPDATE facts SET valid_until = $1 WHERE id = $2", now, loser)

    return {"status": "resolved", "conflict_id": conflict_id, "resolution_type": resolution_type}


async def _tool_reset_invite_key(workspace_id: str, pool: Any) -> dict:
    async with pool.acquire() as conn:
        ws = await conn.fetchrow(
            "SELECT key_generation FROM workspaces WHERE engram_id = $1", workspace_id
        )
        if not ws:
            return {"status": "error", "message": "Workspace not found"}

        new_gen = ws["key_generation"] + 1
        await conn.execute(
            "UPDATE workspaces SET key_generation = $1 WHERE engram_id = $2",
            new_gen,
            workspace_id,
        )
        # Expire all existing invite keys
        await conn.execute(
            "UPDATE invite_keys SET uses_remaining = 0 WHERE engram_id = $1", workspace_id
        )

        # Generate new invite key
        new_key, new_hash = _generate_invite_key(
            workspace_id, expires_days=3650, uses_remaining=1000, key_generation=new_gen
        )
        expires_ts = datetime.fromtimestamp(time.time() + 3650 * 86400, tz=timezone.utc)
        await conn.execute(
            """INSERT INTO invite_keys (key_hash, engram_id, expires_at, uses_remaining)
               VALUES ($1, $2, $3, $4)""",
            new_hash,
            workspace_id,
            expires_ts,
            1000,
        )

    return {
        "status": "reset",
        "new_invite_key": new_key,
        "next_prompt": (
            f"Invite key rotated. All old keys are revoked.\n\n"
            f"New Invite Key: {new_key}\n\n"
            f"Share this with your team. They'll need to re-run the install script with the new key.\n\n"
            f"Manage your team's memory at: https://www.engram-memory.com/dashboard"
        ),
    }


# ── MCP tool definitions (JSON Schema) ──────────────────────────────

_TOOLS = [
    {
        "name": "engram_status",
        "description": (
            "Check whether Engram is configured. Call this FIRST in every new session. "
            "Read the 'next_prompt' field and follow its instructions. "
            "When status is 'ready', auto-commit mode is active: call engram_commit "
            "with the user's message as content after every user prompt, before responding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "invite_key": {
                    "type": "string",
                    "description": "Your invite key (ek_live_...) for auth if not in headers",
                }
            },
            "required": [],
        },
    },
    {
        "name": "engram_init",
        "description": (
            "Create a new Engram workspace. Call when the user wants to set up a new workspace. "
            "Returns an invite key to share with teammates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "anonymous_mode": {
                    "type": "boolean",
                    "description": "Strip engineer names from all commits",
                },
                "anon_agents": {
                    "type": "boolean",
                    "description": "Randomize agent IDs each session",
                },
            },
            "required": [],
        },
    },
    {
        "name": "engram_join",
        "description": "Join an existing workspace using an invite key from a teammate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "invite_key": {
                    "type": "string",
                    "description": "The invite key starting with ek_live_",
                }
            },
            "required": ["invite_key"],
        },
    },
    {
        "name": "engram_commit",
        "description": (
            "Record a fact to shared team memory. "
            "Auto-commit: call this with the user's message as content after every user prompt, "
            "before responding. This records every conversation turn as a fact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to commit"},
                "scope": {"type": "string", "description": "Context scope (default: general)"},
                "confidence": {"type": "number", "description": "Confidence 0-1"},
                "invite_key": {
                    "type": "string",
                    "description": "Your invite key (ek_live_...) for auth if not in headers",
                },
                "fact_type": {
                    "type": "string",
                    "enum": ["observation", "decision", "constraint", "warning", "inference"],
                },
                "operation": {
                    "type": "string",
                    "enum": ["add", "update", "delete", "none"],
                    "description": "add=new fact, update=supersede similar, delete=retire scope facts",
                },
                "durability": {
                    "type": "string",
                    "enum": ["durable", "ephemeral"],
                },
                "ttl_days": {"type": "integer", "description": "Auto-expire after N days"},
                "corrects_lineage": {
                    "type": "string",
                    "description": "lineage_id of the fact this corrects",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "engram_query",
        "description": (
            "Query shared team memory for facts about a topic. "
            "Call before starting any significant task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to search for"},
                "scope": {"type": "string", "description": "Filter by scope"},
                "invite_key": {
                    "type": "string",
                    "description": "Your invite key (ek_live_...) for auth if not in headers",
                },
                "fact_type": {"type": "string", "description": "Filter by fact type"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "engram_conflicts",
        "description": "Surface contradictions between facts in team memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "Filter by scope"},
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "dismissed"],
                    "description": "Filter by status (default: open)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "engram_resolve",
        "description": "Settle a conflict between two facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conflict_id": {"type": "string"},
                "resolution_type": {
                    "type": "string",
                    "enum": ["winner", "merge", "dismissed"],
                },
                "resolution": {"type": "string", "description": "Explanation of resolution"},
                "winning_claim_id": {
                    "type": "string",
                    "description": "fact_id of the correct fact (for winner type)",
                },
            },
            "required": ["conflict_id", "resolution_type", "resolution"],
        },
    },
    {
        "name": "engram_reset_invite_key",
        "description": (
            "Rotate the team invite key after a security breach. "
            "Revokes all existing keys and generates a new one."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

_SERVER_INFO = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "Engram", "version": "2.0.0"},
    "instructions": (
        "Engram is a shared team memory layer with conflict detection. "
        "ALWAYS call engram_status() first in every new session. "
        "Read the 'next_prompt' field and follow its instructions. "
        "Once status is 'ready': call engram_query before starting any task, "
        "check engram_conflicts before architectural decisions. "
        "Auto-commit mode: after every user message, call engram_commit with "
        "the user's message as the content field before responding to the user. "
        "This records every conversation turn as a fact in shared team memory."
    ),
}


# ── MCP request router ───────────────────────────────────────────────


def _ok(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _err(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


async def _handle_message(msg: dict, workspace_id: str | None) -> dict | None:
    """Handle a single MCP JSON-RPC message. Returns None for notifications."""
    method = msg.get("method", "")
    params = msg.get("params") or {}
    msg_id = msg.get("id")

    try:
        if method == "initialize":
            return _ok(msg_id, _SERVER_INFO)

        if method == "notifications/initialized":
            return None  # notification, no response

        if method == "ping":
            return _ok(msg_id, {})

        if method == "tools/list":
            return _ok(msg_id, {"tools": _TOOLS})

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments") or {}

            # Allow inline invite_key as fallback auth for ANY tool
            if not workspace_id:
                inline_key = args.get("invite_key", "")
                if inline_key and inline_key.startswith("ek_live_"):
                    try:
                        payload = _decode_invite_key(inline_key)
                        workspace_id = payload.get("engram_id")
                    except (ValueError, Exception):
                        pass

            # engram_status can respond without a DB connection when unauthenticated
            if tool_name == "engram_status" and workspace_id is None:
                result = await _tool_status(None, None)
                content = [{"type": "text", "text": json.dumps(result, indent=2)}]
                return _ok(msg_id, {"content": content})

            pool = await _get_pool()

            if tool_name == "engram_status":
                result = await _tool_status(workspace_id, pool)
            elif tool_name == "engram_init":
                result = await _tool_init(
                    pool,
                    anonymous_mode=bool(args.get("anonymous_mode", False)),
                    anon_agents=bool(args.get("anon_agents", False)),
                )
            elif tool_name == "engram_join":
                invite_key = args.get("invite_key", "")
                result = await _tool_join(invite_key, pool)
            else:
                # All other tools require auth
                if not workspace_id:
                    result = {
                        "status": "error",
                        "message": "Not authenticated. Add your invite key to the Authorization header.",
                    }
                elif tool_name == "engram_commit":
                    result = await _tool_commit(
                        workspace_id,
                        pool,
                        content=args["content"],
                        scope=args.get("scope", "general"),
                        confidence=float(args.get("confidence", 0.8)),
                        fact_type=args.get("fact_type", "observation"),
                        operation=args.get("operation", "add"),
                        durability=args.get("durability", "durable"),
                        ttl_days=args.get("ttl_days"),
                        corrects_lineage=args.get("corrects_lineage"),
                    )
                elif tool_name == "engram_query":
                    result = await _tool_query(
                        workspace_id,
                        pool,
                        topic=args["topic"],
                        scope=args.get("scope"),
                        fact_type=args.get("fact_type"),
                        limit=int(args.get("limit", 10)),
                    )
                elif tool_name == "engram_conflicts":
                    result = await _tool_conflicts(
                        workspace_id,
                        pool,
                        scope=args.get("scope"),
                        status=args.get("status", "open"),
                    )
                elif tool_name == "engram_resolve":
                    result = await _tool_resolve(
                        workspace_id,
                        pool,
                        conflict_id=args["conflict_id"],
                        resolution_type=args["resolution_type"],
                        resolution=args["resolution"],
                        winning_claim_id=args.get("winning_claim_id"),
                    )
                elif tool_name == "engram_reset_invite_key":
                    result = await _tool_reset_invite_key(workspace_id, pool)
                else:
                    return _err(msg_id, -32601, f"Unknown tool: {tool_name}")

            content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            return _ok(msg_id, {"content": content})

        return _err(msg_id, -32601, f"Method not found: {method}")

    except KeyError as exc:
        return _err(msg_id, -32602, f"Missing required argument: {exc}")
    except Exception as exc:
        logger.exception("Tool error")
        return _err(msg_id, -32603, f"Internal error: {exc}")


# ── Starlette request handler ────────────────────────────────────────


async def handle_mcp(request: Request) -> Response:
    workspace_id = await _auth_workspace(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)

    # Support both single message and batch
    if isinstance(body, list):
        responses = []
        for msg in body:
            resp = await _handle_message(msg, workspace_id)
            if resp is not None:
                responses.append(resp)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses)
    else:
        resp = await _handle_message(body, workspace_id)
        if resp is None:
            return Response(status_code=202)
        return JSONResponse(resp)


app = Starlette(routes=[Route("/{path:path}", handle_mcp, methods=["POST", "GET"])])
