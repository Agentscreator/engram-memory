"""GET /api/conflicts — REST endpoint for the Engram TUI and CLI.

Auth: Authorization: Bearer ek_live_... (invite key)
Returns the same JSON shape that the TUI's _format_conflicts() renders.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DB_URL = os.environ.get("ENGRAM_DB_URL", "")
SCHEMA = "engram"

_pool: Any = None


async def _get_pool() -> Any:
    global _pool
    if _pool is None:
        import asyncpg

        async def _init(conn: Any) -> None:
            await conn.execute(f"SET search_path TO {SCHEMA}, public")

        _pool = await asyncpg.create_pool(
            DB_URL, min_size=1, max_size=3, command_timeout=30, init=_init
        )
    return _pool


def _invite_key_hash(invite_key: str) -> str:
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    raw = base64.urlsafe_b64decode(b64)
    # First 32 bytes are the enc_key; hash that
    enc_key = raw[:32]
    return hashlib.sha256(enc_key).hexdigest()


async def _auth_workspace(request: Request) -> str | None:
    """Return workspace_id if the request carries a valid invite key, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ek_live_"):
        return None
    invite_key = auth[len("Bearer ") :]
    try:
        key_hash = _invite_key_hash(invite_key)
    except Exception:
        return None
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT engram_id FROM invite_keys WHERE key_hash = $1", key_hash)
    return row["engram_id"] if row else None


async def handle_conflicts(request: Request) -> Response:
    workspace_id = await _auth_workspace(request)
    if not workspace_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    status_filter = request.query_params.get("status", "open")
    scope = request.query_params.get("scope") or None

    pool = await _get_pool()
    async with pool.acquire() as conn:
        conds = [
            "c.workspace_id = $1",
            "c.status = $2",
            """NOT EXISTS (
                SELECT 1 FROM dismissed_conflicts dc
                WHERE dc.conflict_id = c.id AND dc.workspace_id = c.workspace_id
            )""",
        ]
        args: list[Any] = [workspace_id, status_filter]
        if scope:
            conds.append("(fa.scope = $3 OR fb.scope = $3)")
            args.append(scope)
        where = " AND ".join(conds)
        rows = await conn.fetch(
            f"""SELECT c.id, c.explanation, c.severity, c.status,
                    fa.content AS content_a, fa.scope AS scope_a,
                    fb.content AS content_b, fb.scope AS scope_b
                FROM conflicts c
                JOIN facts fa ON fa.id = c.fact_a_id
                JOIN facts fb ON fb.id = c.fact_b_id
                WHERE {where}
                ORDER BY c.detected_at DESC LIMIT 50""",
            *args,
        )

    out = [
        {
            "conflict_id": r["id"],
            "explanation": r["explanation"] or "",
            "severity": r["severity"],
            "status": r["status"],
            "fact_a": {"content": r["content_a"], "scope": r["scope_a"]},
            "fact_b": {"content": r["content_b"], "scope": r["scope_b"]},
        }
        for r in rows
    ]
    return JSONResponse(out)


async def handle_options(request: Request) -> Response:
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
        }
    )


app = Starlette(
    routes=[
        Route("/api/conflicts", handle_conflicts, methods=["GET"]),
        Route("/api/conflicts", handle_options, methods=["OPTIONS"]),
        Route("/{path:path}", handle_conflicts, methods=["GET"]),
    ]
)
