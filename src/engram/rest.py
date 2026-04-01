"""REST JSON API for non-MCP clients (e.g. open-multi-agent TypeScript agents).

Exposes the same four Engram tools as simple JSON endpoints so agents
that don't have an MCP client can call Engram via plain HTTP:

    POST /api/commit        → engram_commit
    POST /api/query         → engram_query
    GET  /api/conflicts     → engram_conflicts
    POST /api/resolve       → engram_resolve

Request and response bodies are JSON.  Error responses follow:
    {"error": "<message>", "status": <http_status_code>}

These endpoints honour the same auth and rate-limiting rules as the MCP
tools when the server is started with --auth / --rate-limit.

open-multi-agent usage
----------------------
Register Engram as custom tools in your ToolRegistry so agents can call
engram_commit / engram_query before and after each task.  Example
(TypeScript, run `engram serve --http` first):

    import { defineTool, ToolRegistry } from '@jackchen_me/open-multi-agent'
    import { z } from 'zod'

    const ENGRAM = 'http://localhost:7474'

    const engramCommit = defineTool({
      name: 'engram_commit',
      description: 'Persist a verified discovery to shared team memory.',
      inputSchema: z.object({
        content:    z.string(),
        scope:      z.string(),
        confidence: z.number().min(0).max(1),
        agent_id:   z.string().optional(),
        engineer:   z.string().optional(),
        fact_type:  z.enum(['observation', 'inference', 'decision']).optional(),
        provenance: z.string().optional(),
        ttl_days:   z.number().int().positive().optional(),
      }),
      async execute(input) {
        const res = await fetch(`${ENGRAM}/api/commit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramQuery = defineTool({
      name: 'engram_query',
      description: 'Query what your team knows. Call BEFORE starting work.',
      inputSchema: z.object({
        topic:    z.string(),
        scope:    z.string().optional(),
        limit:    z.number().int().positive().max(50).optional(),
        as_of:    z.string().optional(),
        fact_type: z.string().optional(),
        agent_id: z.string().optional(),
      }),
      async execute(input) {
        const res = await fetch(`${ENGRAM}/api/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramConflicts = defineTool({
      name: 'engram_conflicts',
      description: 'Check where agents disagree. Review before arch decisions.',
      inputSchema: z.object({
        scope:  z.string().optional(),
        status: z.enum(['open', 'resolved', 'dismissed', 'all']).optional(),
      }),
      async execute(input) {
        const params = new URLSearchParams()
        if (input.scope)  params.set('scope', input.scope)
        if (input.status) params.set('status', input.status)
        const res = await fetch(`${ENGRAM}/api/conflicts?${params}`)
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramResolve = defineTool({
      name: 'engram_resolve',
      description: 'Settle a conflict between claims.',
      inputSchema: z.object({
        conflict_id:      z.string(),
        resolution_type:  z.enum(['winner', 'merge', 'dismissed']),
        resolution:       z.string(),
        winning_claim_id: z.string().optional(),
      }),
      async execute(input) {
        const res = await fetch(`${ENGRAM}/api/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    // Register and use with open-multi-agent:
    const registry = new ToolRegistry()
    registry.register(engramCommit)
    registry.register(engramQuery)
    registry.register(engramConflicts)
    registry.register(engramResolve)
    // Then pass registry to Agent / OpenMultiAgent as usual.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from engram.engine import EngramEngine
    from engram.storage import Storage

logger = logging.getLogger("engram")


def build_rest_routes(
    engine: "EngramEngine",
    storage: "Storage",
    auth_enabled: bool = False,
    rate_limiter: Any = None,
) -> list[Route]:
    """Build REST API routes for non-MCP clients such as open-multi-agent."""

    def _error(msg: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": msg, "status": status}, status_code=status)

    async def api_commit(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        content = body.get("content", "")
        scope = body.get("scope", "")
        confidence = body.get("confidence")
        agent_id = body.get("agent_id")
        engineer = body.get("engineer")
        corrects_lineage = body.get("corrects_lineage")
        provenance = body.get("provenance")
        fact_type = body.get("fact_type", "observation")
        ttl_days = body.get("ttl_days")

        # Basic validation
        if not content:
            return _error("'content' is required.")
        if not scope:
            return _error("'scope' is required.")
        if confidence is None:
            return _error("'confidence' is required.")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return _error("'confidence' must be a number between 0.0 and 1.0.")

        # Rate limiting
        effective_agent = agent_id or "anonymous"
        if rate_limiter is not None:
            if not rate_limiter.check(effective_agent):
                return _error(
                    f"Rate limit exceeded for agent '{effective_agent}'. "
                    f"Max {rate_limiter.max_per_hour} commits per hour.",
                    status=429,
                )

        # Scope permission check
        if auth_enabled and agent_id:
            from engram.auth import check_scope_permission
            allowed = await check_scope_permission(storage, agent_id, scope, "write")
            if not allowed:
                return _error(
                    f"Agent '{agent_id}' does not have write permission for scope '{scope}'.",
                    status=403,
                )

        try:
            result = await engine.commit(
                content=content,
                scope=scope,
                confidence=confidence,
                agent_id=agent_id,
                engineer=engineer,
                corrects_lineage=corrects_lineage,
                provenance=provenance,
                fact_type=fact_type,
                ttl_days=ttl_days,
            )
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/commit error")
            return _error(str(exc), status=500)

        if rate_limiter is not None:
            rate_limiter.record(effective_agent)

        return JSONResponse(result)

    async def api_query(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        topic = body.get("topic", "")
        if not topic:
            return _error("'topic' is required.")

        scope = body.get("scope")
        limit = body.get("limit", 10)
        as_of = body.get("as_of")
        fact_type = body.get("fact_type")
        agent_id = body.get("agent_id")

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10

        # Scope read permission check
        if auth_enabled and agent_id and scope:
            from engram.auth import check_scope_permission
            allowed = await check_scope_permission(storage, agent_id, scope, "read")
            if not allowed:
                return _error(
                    f"Agent '{agent_id}' does not have read permission for scope '{scope}'.",
                    status=403,
                )

        try:
            results = await engine.query(
                topic=topic,
                scope=scope,
                limit=limit,
                as_of=as_of,
                fact_type=fact_type,
            )
        except Exception as exc:
            logger.exception("REST /api/query error")
            return _error(str(exc), status=500)

        return JSONResponse(results)

    async def api_conflicts(request: Request) -> JSONResponse:
        scope = request.query_params.get("scope")
        status = request.query_params.get("status", "open")

        try:
            results = await engine.get_conflicts(scope=scope, status=status)
        except Exception as exc:
            logger.exception("REST /api/conflicts error")
            return _error(str(exc), status=500)

        return JSONResponse(results)

    async def api_resolve(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        conflict_id = body.get("conflict_id", "")
        resolution_type = body.get("resolution_type", "")
        resolution = body.get("resolution", "")
        winning_claim_id = body.get("winning_claim_id")

        if not conflict_id:
            return _error("'conflict_id' is required.")
        if not resolution_type:
            return _error("'resolution_type' is required.")
        if not resolution:
            return _error("'resolution' is required.")

        try:
            result = await engine.resolve(
                conflict_id=conflict_id,
                resolution_type=resolution_type,
                resolution=resolution,
                winning_claim_id=winning_claim_id,
            )
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/resolve error")
            return _error(str(exc), status=500)

        return JSONResponse(result)

    return [
        Route("/api/commit",    api_commit,    methods=["POST"]),
        Route("/api/query",     api_query,     methods=["POST"]),
        Route("/api/conflicts", api_conflicts, methods=["GET"]),
        Route("/api/resolve",   api_resolve,   methods=["POST"]),
    ]
