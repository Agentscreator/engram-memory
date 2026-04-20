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
import re as _re
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

# ── Plan commit limits (mirrors api/billing.py) ───────────────────────
_PLAN_LIMITS: dict[str, int] = {
    "free": 500,
    "builder": 5_000,
    "team": 25_000,
    "scale": 100_000,
    # legacy aliases
    "hobby": 500,
    "pro": 5_000,
}

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ── Terms of Service ─────────────────────────────────────────────────

ENGRAM_TERMS = (
    "By using Engram, you agree to the following terms:\n\n"
    "1. AUTO-COMMIT: All conversation data between you and your AI agent is\n"
    "   automatically recorded in your team's shared Engram memory.\n\n"
    "2. YOUR DATA IS YOURS: Engram will never sell, read, redistribute, or\n"
    "   use your conversation data for any purpose beyond providing the\n"
    "   Engram service to you and your team.\n\n"
    "3. ENCRYPTION: All data is encrypted in transit (TLS) and at rest.\n"
    "   Only authenticated members of your workspace can access your data.\n\n"
    "4. DELETION: You can delete your data at any time using the Engram\n"
    "   dashboard or GDPR erasure tools.\n\n"
    "Do you accept these terms? Reply 'I accept' to continue."
)

# ── Schema SQL ───────────────────────────────────────────────────────
# IMPORTANT: After editing _SCHEMA_SQL (adding tables, columns, indexes),
# bump _SCHEMA_VERSION below the DB pool section. This ensures the new
# schema runs on the next deployment even on warm Vercel workers.

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_pair_unique ON conflicts(
    workspace_id,
    LEAST(fact_a_id, fact_b_id),
    GREATEST(fact_a_id, fact_b_id)
);
CREATE INDEX IF NOT EXISTS idx_conflicts_workspace ON conflicts(workspace_id, status);

CREATE TABLE IF NOT EXISTS dismissed_conflicts (
    conflict_id   TEXT PRIMARY KEY REFERENCES conflicts(id),
    workspace_id  TEXT NOT NULL,
    dismissed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dismissed_conflicts_workspace
    ON dismissed_conflicts(workspace_id);

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
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan           TEXT    NOT NULL DEFAULT 'free';
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS terms_accepted BOOLEAN NOT NULL DEFAULT false;

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

# Bump this version whenever _SCHEMA_SQL changes (new tables, columns, indexes).
_SCHEMA_VERSION = 4
_pool: Any = None
_schema_version_applied: int = 0


async def _ensure_schema(pool: Any) -> None:
    """Ensure schema tables exist. Runs a cheap check on every request."""
    global _schema_version_applied
    if _schema_version_applied >= _SCHEMA_VERSION:
        return
    async with pool.acquire() as conn:
        # Always set search_path first — Neon may not honor server_settings or init callbacks
        await conn.execute(f"SET search_path TO {SCHEMA}, public")
        # Quick check: does the workspaces table exist?
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = $1 AND table_name = 'workspaces')",
            SCHEMA,
        )
        if exists:
            # Migrate data from old 'engram' schema to public if needed
            old_schema_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'engram' AND table_name = 'workspaces')"
            )
            if old_schema_exists:
                for table in [
                    "workspaces",
                    "invite_keys",
                    "facts",
                    "conflicts",
                    "agents",
                    "users",
                    "user_workspaces",
                ]:
                    try:
                        await conn.execute(
                            f"INSERT INTO public.{table} SELECT * FROM engram.{table} "
                            f"ON CONFLICT DO NOTHING"
                        )
                    except Exception:
                        pass  # Table might not exist in old schema or columns differ
            _schema_version_applied = _SCHEMA_VERSION
            return
        # Tables don't exist — run bootstrap
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        for stmt in _SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(f"SET search_path TO {SCHEMA}, public")
                await conn.execute(stmt)
        _schema_version_applied = _SCHEMA_VERSION


async def _get_pool() -> Any:
    global _pool
    if not DB_URL:
        raise RuntimeError("ENGRAM_DB_URL not configured")

    import asyncpg

    if _pool is None:

        async def _set_path(c: Any) -> None:
            await c.execute(f"SET search_path TO {SCHEMA}, public")

        _pool = await asyncpg.create_pool(
            DB_URL,
            min_size=1,
            max_size=5,
            command_timeout=30,
            init=_set_path,
            server_settings={"search_path": f"{SCHEMA}, public"},
        )

    await _ensure_schema(_pool)
    return _pool


class _SafeConn:
    """Context manager that guarantees search_path is set on every acquire.

    Neon serverless Postgres may reset connection state between requests,
    so the pool ``init`` callback alone is not reliable.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._conn: Any = None

    async def __aenter__(self) -> Any:
        self._conn = await self._pool.acquire()
        await self._conn.execute(f"SET search_path TO {SCHEMA}, public")
        return self._conn

    async def __aexit__(self, *args: Any) -> None:
        if self._conn:
            await self._pool.release(self._conn)


def _safe(pool: Any) -> _SafeConn:
    """Return a context manager that acquires a connection with search_path set."""
    return _SafeConn(pool)


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
        payload = _decode_invite_key(invite_key)
        return payload.get("engram_id")
    except (ValueError, Exception):
        return None


# ── Conflict detection ───────────────────────────────────────────────

_CONFLICT_MODEL = "gpt-4o-mini"
_BATCH_CHAR_LIMIT = 24000  # ~6k tokens of facts per batch

# Regex patterns for simple heuristic contradiction detection
_UNLIMITED_RE = _re.compile(
    r"\bunlimited\b|\bno\s+limit\b|\bno\s+cap\b|\bno\s+maximum\b"
    r"|\bremov\w+\s+\w*\s*(?:cap|limit)\b|\bwithout\s+limit\b",
    _re.IGNORECASE,
)
_LIMIT_RE = _re.compile(
    r"\bmaximum\s+of\s+(\d+)|\bmax\s+(\d+)|\bcap\s+of\s+(\d+)"
    r"|\blimit\s+of\s+(\d+)|\bup\s+to\s+(\d+)|\bonly\s+(\d+)\b"
    r"|\b(\d+)\s+(?:project|repo|seat|user|item|task)",
    _re.IGNORECASE,
)
_BOOL_TRUE_RE = _re.compile(
    r"\bis\s+enabled\b|\bis\s+active\b|\bis\s+on\b|\bexists?\b|\bmust\s+be\s+enforced\b",
    _re.IGNORECASE,
)
_BOOL_FALSE_RE = _re.compile(
    r"\bis\s+disabled\b|\bis\s+inactive\b|\bis\s+off\b|\bdoes\s+not\s+exist\b|\bnot\s+enforced\b",
    _re.IGNORECASE,
)


def _extract_key_nouns(text: str) -> set[str]:
    """Return lowercase words that look like subject nouns (4+ chars, not stopwords)."""
    _STOP = {
        "this",
        "that",
        "with",
        "have",
        "from",
        "they",
        "will",
        "been",
        "more",
        "also",
        "when",
        "their",
        "there",
        "which",
        "were",
        "what",
        "then",
        "than",
        "into",
        "only",
        "some",
        "your",
        "each",
        "must",
        "fact",
        "user",
        "agent",
        "team",
        "site",
        "page",
    }
    words = _re.findall(r"\b[a-z]{4,}\b", text.lower())
    return {w for w in words if w not in _STOP}


def _facts_share_subject(a: str, b: str) -> bool:
    """Return True if two fact contents share at least one key noun."""
    return bool(_extract_key_nouns(a) & _extract_key_nouns(b))


async def _detect_conflicts_heuristic(workspace_id: str, pool: Any) -> None:
    """Rule-based conflict detection that works without any external API.

    Detects:
    - 'unlimited / no limit' vs 'maximum of N / limit of N' in the same scope
    - Boolean contradictions (enabled vs disabled) in the same scope
    """
    try:
        async with _safe(pool) as conn:
            rows = await conn.fetch(
                """SELECT id, content, scope FROM facts
                   WHERE workspace_id = $1 AND valid_until IS NULL
                   ORDER BY committed_at ASC""",
                workspace_id,
            )
        facts = [dict(r) for r in rows]
        if len(facts) < 2:
            return

        to_insert: list[tuple[str, str, str]] = []  # (fa_id, fb_id, explanation)

        # Group by scope for same-scope checks
        by_scope: dict[str, list[dict]] = {}
        for f in facts:
            by_scope.setdefault(f["scope"], []).append(f)

        for scope_facts in by_scope.values():
            if len(scope_facts) < 2:
                continue
            for i, fa in enumerate(scope_facts):
                for fb in scope_facts[i + 1 :]:
                    if not _facts_share_subject(fa["content"], fb["content"]):
                        continue
                    a_unlimited = bool(_UNLIMITED_RE.search(fa["content"]))
                    b_unlimited = bool(_UNLIMITED_RE.search(fb["content"]))
                    a_limited = bool(_LIMIT_RE.search(fa["content"]))
                    b_limited = bool(_LIMIT_RE.search(fb["content"]))
                    a_true = bool(_BOOL_TRUE_RE.search(fa["content"]))
                    b_true = bool(_BOOL_TRUE_RE.search(fb["content"]))
                    a_false = bool(_BOOL_FALSE_RE.search(fa["content"]))
                    b_false = bool(_BOOL_FALSE_RE.search(fb["content"]))

                    explanation: str | None = None
                    if (a_unlimited and b_limited) or (a_limited and b_unlimited):
                        explanation = (
                            "Is the quantity unlimited, or is there a fixed maximum? "
                            "One fact says unlimited, another says there is a cap."
                        )
                    elif (a_true and b_false) or (a_false and b_true):
                        explanation = (
                            "Contradictory state detected: one fact says enabled/active, "
                            "another says disabled/inactive for the same subject."
                        )

                    if explanation:
                        to_insert.append((fa["id"], fb["id"], explanation))

        if not to_insert:
            return

        async with _safe(pool) as conn:
            for fa_id, fb_id, explanation in to_insert:
                # Normalize pair order to match the LEAST/GREATEST unique index.
                norm_a, norm_b = (fa_id, fb_id) if fa_id < fb_id else (fb_id, fa_id)
                existing = await conn.fetchrow(
                    """SELECT 1 FROM conflicts WHERE workspace_id = $1
                         AND fact_a_id = $2 AND fact_b_id = $3""",
                    workspace_id,
                    norm_a,
                    norm_b,
                )
                if existing:
                    continue
                cid = str(uuid.uuid4())
                dismissed = await conn.fetchrow(
                    """SELECT 1 FROM dismissed_conflicts
                       WHERE conflict_id = $1 AND workspace_id = $2""",
                    cid,
                    workspace_id,
                )
                if dismissed:
                    continue
                await conn.execute(
                    """INSERT INTO conflicts
                       (id, fact_a_id, fact_b_id, explanation, severity, workspace_id)
                       VALUES ($1, $2, $3, $4, 'medium', $5)
                       ON CONFLICT (workspace_id, LEAST(fact_a_id, fact_b_id), GREATEST(fact_a_id, fact_b_id))
                       DO NOTHING""",
                    cid,
                    norm_a,
                    norm_b,
                    explanation,
                    workspace_id,
                )
                logger.info("Heuristic conflict: %s vs %s", norm_a[:8], norm_b[:8])
    except Exception as exc:
        logger.warning("Heuristic conflict detection failed: %s", exc)


async def _detect_conflicts(
    new_fact_id: str,
    content: str,
    scope: str,
    workspace_id: str,
    pool: Any,
    plan: str = "free",
) -> None:
    """Narrative coherence detective with probabilistic forgetting.

    Reads the chronological story of the workspace and identifies where
    an agent would get confused. Uses FiFA-inspired forgetting:

    - Facts < 24h old: 60-80% forgotten (keep 20-40%)
    - Facts 1-7 days old: 80-90% forgotten (keep 10-20%)
    - Facts > 7 days old: 90-95% forgotten (keep 5-10%)
    - Facts involved in conflicts survive at higher rates (2x per flag)

    This focuses the detective on the signal, not the noise.
    """
    # Always run heuristic detection first — works without any API key.
    await _detect_conflicts_heuristic(workspace_id, pool)

    if not OPENAI_API_KEY:
        return

    try:
        async with _safe(pool) as conn:
            # Fetch ALL active facts chronologically (oldest first = story order)
            all_facts = await conn.fetch(
                """SELECT id, content, scope, committed_at FROM facts
                   WHERE workspace_id = $1 AND valid_until IS NULL
                   ORDER BY committed_at ASC""",
                workspace_id,
            )

        if len(all_facts) < 2:
            return

        # ── Probabilistic forgetting (FiFA-inspired) ────────────────
        # Recent noise drowns out signal. The detective forgets most
        # recent facts but remembers facts that have been flagged in
        # conflicts — those are the ones that matter.
        from engram.forgetting import apply_forgetting

        now = datetime.now(timezone.utc)

        # Count how many conflicts each fact has been involved in
        conflict_counts: dict[str, int] = {}
        async with _safe(pool) as conn:
            conflict_rows = await conn.fetch(
                """SELECT fact_a_id, fact_b_id FROM conflicts
                   WHERE workspace_id = $1""",
                workspace_id,
            )
        for cr in conflict_rows:
            conflict_counts[cr["fact_a_id"]] = conflict_counts.get(cr["fact_a_id"], 0) + 1
            conflict_counts[cr["fact_b_id"]] = conflict_counts.get(cr["fact_b_id"], 0) + 1

        # Apply forgetting curve — always keep the trigger fact
        surviving_facts = apply_forgetting(
            facts=[dict(row) for row in all_facts],
            conflict_counts=conflict_counts,
            now=now,
            always_keep_ids={new_fact_id},
        )

        # Build the chronological narrative from surviving facts
        story_lines: list[dict] = []
        for row in surviving_facts:
            ts = (
                row["committed_at"].strftime("%Y-%m-%d %H:%M") if row["committed_at"] else "unknown"
            )
            story_lines.append(
                {
                    "id": row["id"],
                    "text": f"[{row['id'][:8]}] {ts} ({row['scope']}) {row['content']}",
                }
            )

        # Batch into context windows, but keep chronological order within each
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_chars = 0
        for line in story_lines:
            line_len = len(line["text"])
            if current_chars + line_len > _BATCH_CHAR_LIMIT and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(line)
            current_chars += line_len
        if current_batch:
            batches.append(current_batch)

        import asyncio as _aio

        async def _check_batch(batch: list[dict]) -> list[dict]:
            story = "\n".join(f"{i + 1}. {f['text']}" for i, f in enumerate(batch))
            prompt = (
                "You are a detective reading the chronological story of a software project's "
                "shared memory. Each line is a fact committed by an AI agent, with timestamp "
                "and scope.\n\n"
                "Read the story and identify points where an agent joining this project "
                "TODAY would get confused. You're looking for:\n\n"
                "• REVERSALS — the story says 'we use X', then later 'we switched to Y', "
                "then even later 'we use X' again. Which is it now?\n"
                "• AMBIGUITY — two facts that are both currently active say different things "
                "about the same subject. An agent wouldn't know which to follow.\n"
                "• STALE CLAIMS — an old fact is clearly outdated based on newer context "
                "but was never explicitly retired.\n\n"
                "DO NOT FLAG:\n"
                "• Natural progression (we did X, then improved to Y) — that's normal\n"
                "• Design iteration and mind-changes — when someone corrects or refines "
                "an earlier decision, the later fact IS the current truth. The earlier "
                "fact is just history. This is how architecture solidifies.\n"
                "• Facts about different subjects, even if they use similar words\n"
                "• Facts from the same conversation (minutes apart, same scope) evolving\n"
                "• Anything where the chronological order makes the current state clear — "
                "if the most recent fact settles the question, there is no confusion\n"
                "• A correction or clarification that supersedes an earlier claim — "
                "the arc 'we thought X → actually it's Y' is resolved, not ambiguous\n\n"
                "The key test: does the MOST RECENT relevant fact leave the question "
                "open, or does it settle it? If it settles it, do not flag. Only flag "
                "when the latest state of the story is genuinely unclear.\n\n"
                "Think about it like this: if a new agent reads these facts top to bottom, "
                "would they know what's true RIGHT NOW? If yes, no confusion. If they'd "
                "have to guess between two equally current-looking facts, that's a "
                "confusion worth flagging.\n\n"
                f"THE STORY (chronological, oldest first):\n{story}\n\n"
                "For each confusion you find, return:\n"
                '- "fact_ids": array of the 8-char IDs of the facts involved\n'
                '- "question": a 1-2 sentence yes/no question a human can answer to '
                "clarify. Frame as: 'Is [specific thing] still the case?'\n\n"
                "Respond with ONLY a JSON array:\n"
                '[{"fact_ids": ["abc12345", "def67890"], "question": "Is the API still using REST, or was it switched to GraphQL?"}]\n\n'
                "If the story is coherent (the common case), respond with: []"
            )
            try:
                import httpx

                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": _CONFLICT_MODEL,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a narrative coherence detective for a team's "
                                        "shared AI memory. Read the chronological story and "
                                        "identify where a new agent would get confused about "
                                        "the current state of things. Normal development "
                                        "progression is not confusion. Design iteration — "
                                        "someone changing their mind and refining a decision — "
                                        "is not confusion. The later fact is the truth; the "
                                        "earlier fact is history. Only flag genuine ambiguity "
                                        "where the most recent facts leave the current state "
                                        "unclear and an agent would have to guess. "
                                        "Respond only with valid JSON arrays."
                                    ),
                                },
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0,
                            "max_tokens": 1024,
                        },
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "OpenAI API returned %d: %s", resp.status_code, resp.text[:200]
                        )
                        return []
                    data = resp.json()
                    raw = data["choices"][0]["message"]["content"].strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    return json.loads(raw)
            except Exception as exc:
                logger.warning("LLM coherence check failed: %s", exc)
                return []

        results = await _aio.gather(*[_check_batch(b) for b in batches])

        # Build ID lookup
        id_lookup: dict[str, str] = {}
        for row in all_facts:
            id_lookup[row["id"][:8]] = row["id"]

        async with _safe(pool) as conn:
            for batch_results in results:
                for confusion in batch_results:
                    if not isinstance(confusion, dict):
                        continue
                    fact_ids = confusion.get("fact_ids", [])
                    if len(fact_ids) < 2:
                        continue
                    # Resolve short IDs to full IDs
                    full_ids = [id_lookup.get(fid) for fid in fact_ids]
                    full_ids = [fid for fid in full_ids if fid]
                    if len(full_ids) < 2:
                        continue
                    # Use first two facts as the conflict pair
                    fa_id, fb_id = full_ids[0], full_ids[1]
                    # Check if already flagged
                    existing = await conn.fetchrow(
                        """SELECT 1 FROM conflicts WHERE workspace_id = $1
                             AND ((fact_a_id = $2 AND fact_b_id = $3)
                               OR (fact_a_id = $3 AND fact_b_id = $2))""",
                        workspace_id,
                        fa_id,
                        fb_id,
                    )
                    if existing:
                        continue
                    cid = str(uuid.uuid4())
                    dismissed = await conn.fetchrow(
                        """SELECT 1 FROM dismissed_conflicts
                           WHERE conflict_id = $1 AND workspace_id = $2""",
                        cid,
                        workspace_id,
                    )
                    if dismissed:
                        continue
                    question = confusion.get("question", "Ambiguous information detected")
                    await conn.execute(
                        """INSERT INTO conflicts
                           (id, fact_a_id, fact_b_id, explanation, severity, workspace_id)
                           VALUES ($1, $2, $3, $4, 'medium', $5)
                           ON CONFLICT DO NOTHING""",
                        cid,
                        fa_id,
                        fb_id,
                        question,
                        workspace_id,
                    )
                    logger.info(
                        "Coherence issue: %s vs %s — %s",
                        fa_id[:8],
                        fb_id[:8],
                        question,
                    )

    except Exception as exc:
        logger.warning("Narrative coherence detection failed: %s", exc)


# ── Tool implementations ─────────────────────────────────────────────


async def _tool_debug_schema(pool: Any) -> dict:
    """Debug: show what tables exist in the engram schema."""
    async with _safe(pool) as conn:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = $1",
            SCHEMA,
        )
        tables = [r["table_name"] for r in rows]
        search_path = await conn.fetchval("SHOW search_path")
        current_schema = await conn.fetchval("SELECT current_schema()")
    return {
        "schema": SCHEMA,
        "search_path": search_path,
        "current_schema": current_schema,
        "tables": tables,
        "schema_version_applied": _schema_version_applied,
        "schema_version_target": _SCHEMA_VERSION,
    }


async def _tool_status(workspace_id: str | None, pool: Any) -> dict:
    if workspace_id is None:
        return {
            "status": "unconfigured",
            "next_prompt": (
                "Welcome to Engram — shared memory for your team's agents.\n\n"
                "FIRST — Check if a .engram.env file exists in the workspace root.\n"
                "If it does, read the ENGRAM_INVITE_KEY value from it and call\n"
                "engram_join with that key. This reconnects you to the team's\n"
                "shared memory automatically — no need to ask the user.\n\n"
                "If .engram.env does not exist:\n"
                "• Create a workspace at https://www.engram-memory.com/dashboard\n"
                "• Join a workspace you already created — paste your invite key from the dashboard\n"
                "• Join a teammate's workspace — paste the invite key they shared with you"
            ),
        }
    async with _safe(pool) as conn:
        ws = await conn.fetchrow(
            "SELECT engram_id, anonymous_mode, key_generation, terms_accepted FROM workspaces WHERE engram_id = $1",
            workspace_id,
        )
    if not ws:
        return {"status": "error", "message": "Workspace not found"}

    terms_accepted = ws["terms_accepted"]
    return {
        "status": "ready",
        "mode": "hosted",
        "engram_id": ws["engram_id"],
        "anonymous_mode": ws["anonymous_mode"],
        "terms_accepted": terms_accepted,
        "next_prompt": (
            "Engram is connected and ready.\n\n"
            "User messages are captured automatically by IDE-level hooks.\n"
            "Use engram_commit to record verified discoveries, decisions,\n"
            "and corrections — not raw user messages.\n\n"
            "Before starting any task, call engram_query to check what the\n"
            "team already knows."
        ),
    }


async def _tool_init(pool: Any, anonymous_mode: bool = False, anon_agents: bool = False) -> dict:
    engram_id = _generate_team_id()
    invite_key, key_hash = _generate_invite_key(engram_id, expires_days=3650, uses_remaining=1000)
    expires_ts = datetime.fromtimestamp(time.time() + 3650 * 86400, tz=timezone.utc)

    async with _safe(pool) as conn:
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
            f"By using Engram, you agree to the following terms:\n"
            f"• All conversation data is automatically recorded in your team's shared memory.\n"
            f"• Engram will never sell, read, redistribute, or use your data.\n"
            f"• All data is encrypted in transit and at rest.\n"
            f"• You can delete your data anytime via the dashboard or GDPR tools.\n\n"
            f"IMPORTANT — Write .engram.env to the workspace root so Engram persists\n"
            f"across sessions and works for every agent (Kiro, Claude Code, Cursor, etc.).\n"
            f"Write this exact content to .engram.env:\n\n"
            f"# Engram — Shared Team Memory\n"
            f"# This file allows all AI agents in this workspace to connect to\n"
            f"# the team's shared Engram memory automatically.\n"
            f"#\n"
            f"# DO NOT DELETE — without this file, agents lose access to shared memory\n"
            f"# and must be given the invite key again each session.\n"
            f"#\n"
            f"# Add .engram.env to your .gitignore — it contains credentials.\n"
            f"ENGRAM_INVITE_KEY={invite_key}\n\n"
            f"Then add .engram.env to .gitignore if it's not already there.\n\n"
            f"SETUP — Also write the MCP config so Engram connects on startup.\n"
            f"Read the config file, set the engram entry to the exact JSON below, write it back.\n\n"
            f"For Kiro (~/.kiro/settings/mcp.json), write the engram entry as:\n"
            f'{{"url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"For Claude Code (~/.claude.json), write the engram entry as:\n"
            f'{{"type": "http", "url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"For Cursor (~/.cursor/mcp.json), write the engram entry as:\n"
            f'{{"url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"Replace any existing engram entry (including command/args based entries)\n"
            f"with the URL-based entry above. This switches from local to hosted Engram.\n\n"
            f"To invite teammates, share the invite key above. They run:\n"
            f"  curl -fsSL https://engram-memory.com/install | sh -s -- --join {invite_key}\n\n"
            f"For this session, pass invite_key to all Engram tool calls:\n"
            f"  invite_key: {invite_key}\n\n"
            f"User messages are captured automatically by IDE-level hooks.\n"
            f"Use engram_commit to record verified discoveries, decisions,\n"
            f"and corrections — not raw user messages.\n\n"
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

    async with _safe(pool) as conn:
        row = await conn.fetchrow("SELECT engram_id FROM invite_keys WHERE key_hash = $1", key_hash)
        if not row:
            return {"status": "error", "message": "Invite key not found or revoked"}

    # Auto-accept terms on join — the terms are presented in the response
    async with _safe(pool) as conn:
        await conn.execute(
            "UPDATE workspaces SET terms_accepted = true WHERE engram_id = $1",
            engram_id,
        )

    return {
        "status": "joined",
        "engram_id": engram_id,
        "invite_key": invite_key,
        "next_prompt": (
            f"Connected to workspace {engram_id}!\n\n"
            f"By using Engram, you agree to the following terms:\n"
            f"• All conversation data is automatically recorded in your team's shared memory.\n"
            f"• Engram will never sell, read, redistribute, or use your data.\n"
            f"• All data is encrypted in transit and at rest.\n"
            f"• You can delete your data anytime via the dashboard or GDPR tools.\n\n"
            f"IMPORTANT — Write .engram.env to the workspace root so Engram persists\n"
            f"across sessions and works for every agent (Kiro, Claude Code, Cursor, etc.).\n"
            f"Write this exact content to .engram.env:\n\n"
            f"# Engram — Shared Team Memory\n"
            f"# This file allows all AI agents in this workspace to connect to\n"
            f"# the team's shared Engram memory automatically.\n"
            f"#\n"
            f"# DO NOT DELETE — without this file, agents lose access to shared memory\n"
            f"# and must be given the invite key again each session.\n"
            f"#\n"
            f"# Add .engram.env to your .gitignore — it contains credentials.\n"
            f"ENGRAM_INVITE_KEY={invite_key}\n\n"
            f"Then add .engram.env to .gitignore if it's not already there.\n\n"
            f"SETUP — Also write the MCP config so Engram connects on startup.\n"
            f"Read the config file, set the engram entry to the exact JSON below, write it back.\n\n"
            f"For Kiro (~/.kiro/settings/mcp.json), write the engram entry as:\n"
            f'{{"url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"For Claude Code (~/.claude.json), write the engram entry as:\n"
            f'{{"type": "http", "url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"For Cursor (~/.cursor/mcp.json), write the engram entry as:\n"
            f'{{"url": "https://www.engram-memory.com/mcp", '
            f'"headers": {{"Authorization": "Bearer {invite_key}"}}}}\n\n'
            f"Replace any existing engram entry (including command/args based entries)\n"
            f"with the URL-based entry above. This switches from local to hosted Engram.\n\n"
            f"For this session, pass invite_key to all Engram tool calls:\n"
            f"  invite_key: {invite_key}\n\n"
            f"User messages are captured automatically by IDE-level hooks.\n"
            f"Use engram_commit to record verified discoveries, decisions,\n"
            f"and corrections — not raw user messages.\n\n"
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
    async with _safe(pool) as conn:
        ws_row = await conn.fetchrow(
            """SELECT paused, plan, stripe_customer_id, stripe_subscription_id,
                      commit_count_month, commit_month,
                      TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM') AS current_month
               FROM workspaces WHERE engram_id = $1""",
            workspace_id,
        )
    if ws_row and ws_row["paused"]:
        return {
            "status": "error",
            "paused": True,
            "message": (
                "Workspace paused. Visit https://www.engram-memory.com/dashboard "
                "to review your plan or resolve any billing issues."
            ),
        }
    if ws_row:
        plan = (ws_row["plan"] or "free").lower()
        commit_limit = _PLAN_LIMITS.get(plan, 500)
        current_month = ws_row["current_month"]
        committed = ws_row["commit_count_month"] or 0
        # Reset counter if month has rolled over
        if ws_row["commit_month"] != current_month:
            committed = 0
        if committed >= commit_limit:
            plan_name = plan.title()
            return {
                "status": "error",
                "limit_reached": True,
                "message": (
                    f"Monthly commit limit reached ({commit_limit:,} commits on {plan_name} plan). "
                    "Upgrade at https://www.engram-memory.com/dashboard to continue."
                ),
            }

    async with _safe(pool) as conn:
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
        # Track monthly commit count (reset when month changes)
        if operation != "delete":
            content_bytes = len(content.encode())
            await conn.execute(
                "UPDATE workspaces SET storage_bytes = storage_bytes + $1 WHERE engram_id = $2",
                content_bytes,
                workspace_id,
            )
            await conn.execute(
                """UPDATE workspaces
                      SET commit_count_month = CASE
                            WHEN commit_month = TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM')
                            THEN commit_count_month + 1
                            ELSE 1
                          END,
                          commit_month = TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM')
                    WHERE engram_id = $1""",
                workspace_id,
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
    async with _safe(pool) as conn:
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
    # Run heuristic scan before returning results so freshly committed
    # contradictions show up immediately without waiting for the next commit.
    await _detect_conflicts_heuristic(workspace_id, pool)

    async with _safe(pool) as conn:
        conds = [
            "c.workspace_id = $1",
            "c.status = $2",
            """NOT EXISTS (
                SELECT 1 FROM dismissed_conflicts dc
                WHERE dc.conflict_id = c.id AND dc.workspace_id = c.workspace_id
            )""",
        ]
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
    async with _safe(pool) as conn:
        row = await conn.fetchrow(
            "SELECT id FROM conflicts WHERE id = $1 AND workspace_id = $2",
            conflict_id,
            workspace_id,
        )
        if not row:
            return {"status": "error", "message": "Conflict not found"}
        await conn.execute(
            """UPDATE conflicts
               SET status = $1, resolved_at = $2, resolution = $3, resolution_type = $4
               WHERE id = $5""",
            "dismissed" if resolution_type == "dismissed" else "resolved",
            now,
            resolution,
            resolution_type,
            conflict_id,
        )
        if resolution_type == "dismissed":
            await conn.execute(
                """INSERT INTO dismissed_conflicts(conflict_id, workspace_id, dismissed_at)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (conflict_id) DO UPDATE
                   SET workspace_id = EXCLUDED.workspace_id,
                       dismissed_at = EXCLUDED.dismissed_at""",
                conflict_id,
                workspace_id,
                now,
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
    async with _safe(pool) as conn:
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
            f"Update .engram.env in the workspace root with the new key:\n"
            f"ENGRAM_INVITE_KEY={new_key}\n\n"
            f"Share this with your team. They'll need to re-run the install script with the new key.\n\n"
            f"Manage your team's memory at: https://www.engram-memory.com/dashboard"
        ),
    }


async def _tool_accept_terms(workspace_id: str, pool: Any) -> dict:
    """Record that the user has accepted the Engram terms of service."""
    async with _safe(pool) as conn:
        await conn.execute(
            "UPDATE workspaces SET terms_accepted = true WHERE engram_id = $1",
            workspace_id,
        )
    return {
        "status": "accepted",
        "next_prompt": (
            "Terms accepted. Thank you!\n\n"
            "User messages are captured automatically by IDE-level hooks.\n"
            "Use engram_commit to record verified discoveries, decisions,\n"
            "and corrections — not raw user messages.\n\n"
            "Before starting any task, call engram_query to check what the\n"
            "team already knows."
        ),
    }


# ── MCP tool definitions (JSON Schema) ──────────────────────────────

_TOOLS = [
    {
        "name": "engram_status",
        "description": (
            "Check whether Engram is configured. Call this FIRST in every new session. "
            "Read the 'next_prompt' field and follow its instructions. "
            "When status is 'ready': call engram_query before starting any task, "
            "and use engram_commit to record verified discoveries and decisions."
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
            "Record a verified discovery, decision, or correction to shared team memory. "
            "Use this for facts your agent has verified — not for raw user messages "
            "(those are captured automatically by IDE-level hooks)."
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
    {
        "name": "engram_accept_terms",
        "description": (
            "Record that the user has accepted the Engram terms of service. "
            "Call this after the user explicitly says 'I accept' or similar affirmative "
            "in response to the terms presented after init or join."
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
        "Use engram_commit to record verified discoveries, decisions, and "
        "corrections — not raw user messages. User messages are captured "
        "automatically by IDE-level hooks."
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
            elif tool_name == "debug_schema":
                result = await _tool_debug_schema(pool)
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
                elif tool_name == "engram_accept_terms":
                    result = await _tool_accept_terms(workspace_id, pool)
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


async def handle_rest_conflicts(request: Request) -> Response:
    """GET /api/conflicts?status=open — REST shortcut for the TUI and CLI."""
    workspace_id = await _auth_workspace(request)
    if not workspace_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    status_filter = request.query_params.get("status", "open")
    scope = request.query_params.get("scope") or None
    pool = await _get_pool()
    result = await _tool_conflicts(workspace_id, pool, scope=scope, status=status_filter)
    conflicts = result.get("conflicts", [])
    # Reshape to match the format the TUI's _format_conflicts() expects
    out = []
    for c in conflicts:
        out.append(
            {
                "conflict_id": c.get("id", ""),
                "explanation": c.get("explanation", ""),
                "severity": c.get("severity", "medium"),
                "status": c.get("status", "open"),
                "fact_a": {"content": c.get("content_a", ""), "scope": c.get("scope_a", "")},
                "fact_b": {"content": c.get("content_b", ""), "scope": c.get("scope_b", "")},
            }
        )
    return JSONResponse(out)


app = Starlette(
    routes=[
        Route("/api/conflicts", handle_rest_conflicts, methods=["GET"]),
        Route("/{path:path}", handle_mcp, methods=["POST", "GET"]),
    ]
)
