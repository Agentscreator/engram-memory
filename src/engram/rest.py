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

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
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
        operation = body.get("operation", "add")

        # Basic validation
        if not content or not str(content).strip():
            return _error("'content' is required and cannot be empty or whitespace.")
        if not scope or not str(scope).strip():
            return _error("'scope' is required and cannot be empty or whitespace.")
        if confidence is None:
            return _error("'confidence' is required.")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return _error("'confidence' must be a number between 0.0 and 1.0.")
        if not 0.0 <= confidence <= 1.0:
            return _error("'confidence' must be between 0.0 and 1.0.")
        if fact_type not in ("observation", "inference", "decision"):
            return _error("'fact_type' must be 'observation', 'inference', or 'decision'.")
        if operation not in ("add", "update", "delete", "none"):
            return _error("'operation' must be 'add', 'update', 'delete', or 'none'.")
        if ttl_days is not None:
            if not isinstance(ttl_days, int) or ttl_days <= 0:
                return _error("'ttl_days' must be a positive integer.")

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
                operation=operation,
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

        if as_of is not None:
            try:
                from datetime import datetime

                datetime.fromisoformat(str(as_of))
            except (TypeError, ValueError):
                return _error(
                    "'as_of' must be a valid ISO 8601 datetime string (e.g. '2024-01-01T00:00:00Z')."
                )

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

        if status not in ("open", "resolved", "dismissed", "all"):
            return _error("'status' must be one of: 'open', 'resolved', 'dismissed', 'all'.")

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
        if resolution_type not in ("winner", "merge", "dismissed"):
            return _error("'resolution_type' must be 'winner', 'merge', or 'dismissed'.")
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

    async def api_batch_commit(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        facts = body.get("facts")
        agent_id = body.get("agent_id")
        engineer = body.get("engineer")

        if facts is None:
            return _error("'facts' is required.")
        if not isinstance(facts, list):
            return _error("'facts' must be an array.")
        if len(facts) == 0:
            return _error("'facts' must contain at least one fact.")
        if len(facts) > 100:
            return _error("'facts' must contain at most 100 facts per batch.")

        # Validate each fact has required fields
        for i, fact in enumerate(facts):
            if not isinstance(fact, dict):
                return _error(f"facts[{i}] must be an object.")
            if not fact.get("content") or not str(fact["content"]).strip():
                return _error(f"facts[{i}].content is required and cannot be empty.")
            if not fact.get("scope") or not str(fact["scope"]).strip():
                return _error(f"facts[{i}].scope is required and cannot be empty.")
            if fact.get("confidence") is None:
                return _error(f"facts[{i}].confidence is required.")
            try:
                c = float(fact["confidence"])
            except (TypeError, ValueError):
                return _error(f"facts[{i}].confidence must be a number between 0.0 and 1.0.")
            if not 0.0 <= c <= 1.0:
                return _error(f"facts[{i}].confidence must be between 0.0 and 1.0.")

        try:
            result = await engine.batch_commit(
                facts=facts,
                default_agent_id=agent_id,
                default_engineer=engineer,
            )
        except Exception as exc:
            logger.exception("REST /api/batch-commit error")
            return _error(str(exc), status=500)

        return JSONResponse(result)

    async def api_stats(request: Request) -> JSONResponse:
        try:
            result = await engine.get_stats()
        except Exception as exc:
            logger.exception("REST /api/stats error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_feedback(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        conflict_id = body.get("conflict_id", "")
        feedback = body.get("feedback", "")

        if not conflict_id:
            return _error("'conflict_id' is required.")
        if feedback not in ("true_positive", "false_positive"):
            return _error("'feedback' must be 'true_positive' or 'false_positive'.")

        try:
            result = await engine.record_feedback(conflict_id=conflict_id, feedback=feedback)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/feedback error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_timeline(request: Request) -> JSONResponse:
        scope = request.query_params.get("scope")
        try:
            limit = int(request.query_params.get("limit", "50"))
        except (TypeError, ValueError):
            limit = 50

        try:
            result = await engine.get_timeline(scope=scope, limit=limit)
        except Exception as exc:
            logger.exception("REST /api/timeline error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_agents(request: Request) -> JSONResponse:
        try:
            result = await engine.get_agents()
        except Exception as exc:
            logger.exception("REST /api/agents error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_facts(request: Request) -> JSONResponse:
        scope = request.query_params.get("scope")
        fact_type = request.query_params.get("fact_type")
        try:
            limit = int(request.query_params.get("limit", "50"))
        except (TypeError, ValueError):
            limit = 50

        if fact_type and fact_type not in ("observation", "inference", "decision"):
            return _error("'fact_type' must be 'observation', 'inference', or 'decision'.")

        try:
            result = await engine.list_facts(scope=scope, fact_type=fact_type, limit=limit)
        except Exception as exc:
            logger.exception("REST /api/facts error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_fact_by_id(request: Request) -> JSONResponse:
        fact_id = request.path_params.get("fact_id", "")
        if not fact_id:
            return _error("'fact_id' is required.")
        try:
            result = await engine.get_fact(fact_id)
        except Exception as exc:
            logger.exception("REST /api/facts/{fact_id} error")
            return _error(str(exc), status=500)
        if result is None:
            return _error(f"Fact '{fact_id}' not found.", status=404)
        return JSONResponse(result)

    async def api_lineage(request: Request) -> JSONResponse:
        lineage_id = request.path_params.get("lineage_id", "")
        if not lineage_id:
            return _error("'lineage_id' is required.")
        try:
            result = await engine.get_lineage(lineage_id)
        except Exception as exc:
            logger.exception("REST /api/lineage/{lineage_id} error")
            return _error(str(exc), status=500)
        if not result:
            return _error(f"Lineage '{lineage_id}' not found.", status=404)
        return JSONResponse(result)

    async def api_expiring(request: Request) -> JSONResponse:
        try:
            days_ahead = int(request.query_params.get("days_ahead", "7"))
        except (TypeError, ValueError):
            days_ahead = 7
        try:
            result = await engine.get_expiring_facts(days_ahead=days_ahead)
        except Exception as exc:
            logger.exception("REST /api/expiring error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_bulk_dismiss(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")

        conflict_ids = body.get("conflict_ids")
        reason = body.get("reason", "")
        dismissed_by = body.get("dismissed_by")

        if conflict_ids is None:
            return _error("'conflict_ids' is required.")
        if not isinstance(conflict_ids, list):
            return _error("'conflict_ids' must be an array.")
        if len(conflict_ids) == 0:
            return _error("'conflict_ids' must contain at least one ID.")
        if len(conflict_ids) > 100:
            return _error("'conflict_ids' must contain at most 100 IDs.")
        if not reason or not str(reason).strip():
            return _error("'reason' is required.")

        try:
            result = await engine.bulk_dismiss(
                conflict_ids=conflict_ids,
                reason=reason,
                dismissed_by=dismissed_by,
            )
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/conflicts/bulk-dismiss error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_health(request: Request) -> JSONResponse:
        try:
            fact_count = await storage.count_facts()
            conflict_count = await storage.count_conflicts(status="open")
        except Exception:
            return JSONResponse({"status": "degraded"}, status_code=503)
        return JSONResponse(
            {
                "status": "ok",
                "facts": fact_count,
                "open_conflicts": conflict_count,
            }
        )

    async def api_export(request: Request) -> JSONResponse:
        fmt = request.query_params.get("format", "json")
        scope = request.query_params.get("scope")

        if fmt not in ("json", "markdown"):
            return _error(f"Invalid format '{fmt}'. Supported: json, markdown")

        try:
            result = await engine.export_workspace(format=fmt, scope=scope)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/export error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    # ── Webhooks ──────────────────────────────────────────────────────

    async def api_create_webhook(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")
        url = body.get("url", "")
        events = body.get("events")
        secret = body.get("secret")
        if not url:
            return _error("'url' is required.")
        if not url.startswith(("http://", "https://")):
            return _error("'url' must be a valid http/https URL.")
        if not events or not isinstance(events, list) or len(events) == 0:
            return _error("'events' must be a non-empty array of event type strings.")
        try:
            result = await engine.create_webhook(url=url, events=events, secret=secret)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/webhooks POST error")
            return _error(str(exc), status=500)
        return JSONResponse(result, status_code=201)

    async def api_list_webhooks(request: Request) -> JSONResponse:
        try:
            result = await engine.list_webhooks()
        except Exception as exc:
            logger.exception("REST /api/webhooks GET error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_delete_webhook(request: Request) -> JSONResponse:
        webhook_id = request.path_params.get("webhook_id", "")
        if not webhook_id:
            return _error("'webhook_id' is required.")
        try:
            result = await engine.delete_webhook(webhook_id)
        except ValueError as exc:
            return _error(str(exc), status=404)
        except Exception as exc:
            logger.exception("REST /api/webhooks/{webhook_id} DELETE error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    # ── Rules ─────────────────────────────────────────────────────────

    async def api_create_rule(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")
        scope_prefix = body.get("scope_prefix", "")
        condition_type = body.get("condition_type", "")
        condition_value = body.get("condition_value", "")
        resolution_type = body.get("resolution_type", "winner")
        if not scope_prefix:
            return _error("'scope_prefix' is required.")
        valid_condition_types = ("latest_wins", "highest_confidence", "confidence_delta")
        if condition_type not in valid_condition_types:
            return _error(f"'condition_type' must be one of: {', '.join(valid_condition_types)}.")
        try:
            result = await engine.create_rule(
                scope_prefix=scope_prefix,
                condition_type=condition_type,
                condition_value=str(condition_value),
                resolution_type=resolution_type,
            )
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/rules POST error")
            return _error(str(exc), status=500)
        return JSONResponse(result, status_code=201)

    async def api_list_rules(request: Request) -> JSONResponse:
        try:
            result = await engine.list_rules()
        except Exception as exc:
            logger.exception("REST /api/rules GET error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_delete_rule(request: Request) -> JSONResponse:
        rule_id = request.path_params.get("rule_id", "")
        if not rule_id:
            return _error("'rule_id' is required.")
        try:
            result = await engine.delete_rule(rule_id)
        except ValueError as exc:
            return _error(str(exc), status=404)
        except Exception as exc:
            logger.exception("REST /api/rules/{rule_id} DELETE error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    # ── Export / Import ───────────────────────────────────────────────

    async def api_import(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")
        facts = body.get("facts")
        agent_id = body.get("agent_id")
        engineer = body.get("engineer")
        if facts is None:
            return _error("'facts' is required.")
        if not isinstance(facts, list):
            return _error("'facts' must be an array.")
        try:
            result = await engine.import_workspace(facts=facts, agent_id=agent_id, engineer=engineer)
        except Exception as exc:
            logger.exception("REST /api/import error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    # ── SSE Watch ─────────────────────────────────────────────────────

    async def api_watch(request: Request) -> StreamingResponse:
        scope = request.query_params.get("scope", "")

        async def event_generator():
            queue = engine.subscribe(scope_prefix=scope)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                        payload = json.dumps(event)
                        yield f"data: {payload}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive comment
                        yield ": keepalive\n\n"
                    except asyncio.CancelledError:
                        break
            finally:
                engine.unsubscribe(queue, scope_prefix=scope)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # ── Scopes ────────────────────────────────────────────────────────

    async def api_register_scope(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error("Request body must be valid JSON.")
        scope = body.get("scope", "")
        if not scope or not scope.strip():
            return _error("'scope' is required.")
        description = body.get("description")
        owner_agent_id = body.get("owner_agent_id")
        retention_days = body.get("retention_days")
        try:
            result = await engine.register_scope(
                scope=scope,
                description=description,
                owner_agent_id=owner_agent_id,
                retention_days=retention_days,
            )
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("REST /api/scopes POST error")
            return _error(str(exc), status=500)
        return JSONResponse(result, status_code=201)

    async def api_list_scopes(request: Request) -> JSONResponse:
        try:
            result = await engine.list_scopes()
        except Exception as exc:
            logger.exception("REST /api/scopes GET error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    async def api_get_scope(request: Request) -> JSONResponse:
        scope_name = request.path_params.get("scope_name", "")
        if not scope_name:
            return _error("'scope_name' is required.")
        try:
            result = await engine.get_scope_info(scope_name)
        except Exception as exc:
            logger.exception("REST /api/scopes/{scope_name} GET error")
            return _error(str(exc), status=500)
        if result is None:
            return _error(f"Scope '{scope_name}' not found.", status=404)
        return JSONResponse(result)

    # ── Diff ──────────────────────────────────────────────────────────

    async def api_diff(request: Request) -> JSONResponse:
        fact_id_a = request.path_params.get("fact_id_a", "")
        fact_id_b = request.path_params.get("fact_id_b", "")
        if not fact_id_a or not fact_id_b:
            return _error("Both 'fact_id_a' and 'fact_id_b' are required.")
        try:
            result = await engine.diff_facts(fact_id_a, fact_id_b)
        except ValueError as exc:
            return _error(str(exc), status=404)
        except Exception as exc:
            logger.exception("REST /api/diff error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    # ── Audit ─────────────────────────────────────────────────────────

    async def api_audit(request: Request) -> JSONResponse:
        agent_id = request.query_params.get("agent_id")
        operation = request.query_params.get("operation")
        from_ts = request.query_params.get("from")
        to_ts = request.query_params.get("to")
        try:
            limit = int(request.query_params.get("limit", "100"))
        except (TypeError, ValueError):
            limit = 100
        try:
            result = await engine.get_audit_log(
                agent_id=agent_id,
                operation=operation,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
            )
        except Exception as exc:
            logger.exception("REST /api/audit error")
            return _error(str(exc), status=500)
        return JSONResponse(result)

    return [
        Route("/api/commit", api_commit, methods=["POST"]),
        Route("/api/query", api_query, methods=["POST"]),
        Route("/api/conflicts", api_conflicts, methods=["GET"]),
        Route("/api/resolve", api_resolve, methods=["POST"]),
        Route("/api/batch-commit", api_batch_commit, methods=["POST"]),
        Route("/api/stats", api_stats, methods=["GET"]),
        Route("/api/feedback", api_feedback, methods=["POST"]),
        Route("/api/timeline", api_timeline, methods=["GET"]),
        Route("/api/agents", api_agents, methods=["GET"]),
        Route("/api/health", api_health, methods=["GET"]),
        Route("/api/facts", api_facts, methods=["GET"]),
        Route("/api/facts/{fact_id}", api_fact_by_id, methods=["GET"]),
        Route("/api/lineage/{lineage_id}", api_lineage, methods=["GET"]),
        Route("/api/expiring", api_expiring, methods=["GET"]),
        Route("/api/conflicts/bulk-dismiss", api_bulk_dismiss, methods=["POST"]),
        # Webhooks
        Route("/api/webhooks", api_create_webhook, methods=["POST"]),
        Route("/api/webhooks", api_list_webhooks, methods=["GET"]),
        Route("/api/webhooks/{webhook_id}", api_delete_webhook, methods=["DELETE"]),
        # Rules
        Route("/api/rules", api_create_rule, methods=["POST"]),
        Route("/api/rules", api_list_rules, methods=["GET"]),
        Route("/api/rules/{rule_id}", api_delete_rule, methods=["DELETE"]),
        # Export / Import
        Route("/api/export", api_export, methods=["GET"]),
        Route("/api/import", api_import, methods=["POST"]),
        # SSE Watch
        Route("/api/watch", api_watch, methods=["GET"]),
        # Scopes
        Route("/api/scopes", api_register_scope, methods=["POST"]),
        Route("/api/scopes", api_list_scopes, methods=["GET"]),
        Route("/api/scopes/{scope_name}", api_get_scope, methods=["GET"]),
        # Diff
        Route("/api/diff/{fact_id_a}/{fact_id_b}", api_diff, methods=["GET"]),
        # Audit
        Route("/api/audit", api_audit, methods=["GET"]),
    ]
