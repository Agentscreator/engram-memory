"""Phase 7 — Dashboard: server-rendered HTML with HTMX.

Co-located with the MCP server on the same process. Endpoint: /dashboard.
Landing page at / for new visitors.
Views: knowledge base, conflict queue, timeline, agent activity,
point-in-time, expiring facts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from engram.storage import Storage

logger = logging.getLogger("engram")


def build_dashboard_routes(storage: Storage, engine: Any = None) -> list[Route]:
    """Build all dashboard routes."""

    async def landing(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_landing())

    async def index(request: Request) -> HTMLResponse:
        # Check workspace connection status
        from engram.workspace import read_workspace

        ws = read_workspace()
        workspace_error = None
        if ws is None:
            workspace_error = "No workspace configured. Run 'engram setup' or 'engram init'."
        elif ws.db_url:
            # Try to verify connection by querying storage
            try:
                await storage.count_facts(current_only=False)
            except Exception as e:
                workspace_error = f"Workspace connection failed: {str(e)[:100]}"

        facts_count = await storage.count_facts(current_only=True)
        total_facts = await storage.count_facts(current_only=False)
        open_conflicts = await storage.count_conflicts("open")
        resolved_conflicts = await storage.count_conflicts("resolved")
        agents = await storage.get_agents()
        expiring = await storage.get_expiring_facts(days_ahead=7)
        recent_activity = await storage.get_fact_timeline(limit=10)
        return HTMLResponse(
            _render_index(
                facts_count=facts_count,
                total_facts=total_facts,
                open_conflicts=open_conflicts,
                resolved_conflicts=resolved_conflicts,
                agents=agents,
                expiring_count=len(expiring),
                workspace_error=workspace_error,
                recent_activity=recent_activity,
            )
        )

    async def fact_detail(request: Request) -> HTMLResponse:
        """Render fact detail panel with lineage and version history."""
        fact_id = request.path_params.get("fact_id", "")

        fact = await storage.get_fact_by_id(fact_id)
        if not fact:
            return HTMLResponse(
                '<div style="padding:2rem;"><h2>Fact not found</h2><a href="/dashboard/facts">Back to Knowledge Base</a></div>',
                status_code=404,
            )

        lineage_id = fact.get("lineage_id")
        lineage = []
        if lineage_id:
            lineage = await storage.get_facts_by_lineage(lineage_id)

        return HTMLResponse(_render_fact_detail(fact, lineage))

    async def fact_lineage(request: Request) -> HTMLResponse:
        """Return lineage version history for a fact (HTMX partial)."""
        fact_id = request.path_params.get("fact_id", "")

        fact = await storage.get_fact_by_id(fact_id)
        if not fact:
            return HTMLResponse("<p>Fact not found</p>", status_code=404)

        lineage_id = fact.get("lineage_id")
        if not lineage_id:
            return HTMLResponse("<p>No lineage history available</p>")

        lineage = await storage.get_facts_by_lineage(lineage_id)
        return HTMLResponse(_render_lineage_timeline(lineage))

    async def knowledge_base(request: Request) -> HTMLResponse:
        scope = request.query_params.get("scope") or ""
        fact_type = request.query_params.get("fact_type") or ""
        as_of = request.query_params.get("as_of") or ""
        search_query = request.query_params.get("q", "").strip()
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 100))

        scope_filter = scope or None
        fact_type_filter = fact_type or None
        as_of_filter = as_of or None

        # Use FTS search if query provided
        if search_query:
            try:
                fts_rowids = await storage.fts_search(search_query, limit=limit, offset=offset)
                if fts_rowids:
                    facts = await storage.get_facts_by_rowids(fts_rowids)
                else:
                    facts = []
            except Exception:
                # FTS fallback - use regular query
                facts = await storage.get_current_facts_in_scope(
                    scope=scope_filter,
                    fact_type=fact_type_filter,
                    as_of=as_of_filter,
                    limit=limit,
                    offset=offset,
                )
        else:
            facts = await storage.get_current_facts_in_scope(
                scope=scope_filter,
                fact_type=fact_type_filter,
                as_of=as_of_filter,
                limit=limit,
                offset=offset,
            )

        if not facts and offset > 0:
            offset = 0
            facts = await storage.get_current_facts_in_scope(
                scope=scope_filter,
                fact_type=fact_type_filter,
                as_of=as_of_filter,
                limit=limit,
                offset=0,
            )

        scopes = await storage.get_distinct_scopes()
        conflict_ids = await storage.get_open_conflict_fact_ids()
        return HTMLResponse(
            _render_facts_table(
                facts,
                conflict_ids,
                search_query=search_query,
                scope=scope,
                fact_type=fact_type,
                as_of=as_of,
                offset=offset,
                limit=limit,
                scopes=scopes,
            )
        )

    async def conflict_queue(request: Request) -> HTMLResponse:
        scope = request.query_params.get("scope") or None
        status = request.query_params.get("status", "open")
        if engine is None:
            return HTMLResponse(
                _render_conflicts_page(
                    [], stats={"open": 0, "resolved": 0}, scope=scope, status=status
                )
            )
        conflicts = await engine.get_conflicts(scope=scope, status=status)
        stats = {
            "open": await storage.count_conflicts("open"),
            "resolved": await storage.count_conflicts("resolved"),
        }
        return HTMLResponse(
            _render_conflicts_page(conflicts, stats=stats, scope=scope, status=status)
        )

    async def approve_suggestion(request: Request) -> Response:
        """HTMX: approve the LLM-suggested resolution for a conflict."""
        conflict_id = request.path_params["conflict_id"]
        if engine is None:
            return HTMLResponse(
                '<p style="color:#dc2626">Engine not available</p>', status_code=503
            )
        conflict = await storage.get_conflict_by_id(conflict_id)
        if not conflict:
            return HTMLResponse('<p style="color:#dc2626">Conflict not found</p>', status_code=404)
        if conflict["status"] != "open":
            full = await storage.get_conflict_with_facts(conflict_id)
            return HTMLResponse(_render_conflict_card(full or conflict))

        resolution_type = conflict.get("suggested_resolution_type") or "winner"
        resolution = conflict.get("suggested_resolution") or "Approved via dashboard."
        winning_id = conflict.get("suggested_winning_fact_id")

        try:
            await engine.resolve(
                conflict_id=conflict_id,
                resolution_type=resolution_type,
                resolution=f"[Dashboard approved] {resolution}",
                winning_claim_id=winning_id,
            )
        except Exception as exc:
            return HTMLResponse(
                f'<p style="color:#dc2626">Error: {_esc(str(exc))}</p>', status_code=400
            )

        updated = await storage.get_conflict_with_facts(conflict_id)
        return HTMLResponse(_render_conflict_card(updated or conflict))

    async def dismiss_conflict(request: Request) -> Response:
        """HTMX: dismiss a conflict as a false positive."""
        conflict_id = request.path_params["conflict_id"]
        if engine is None:
            return HTMLResponse(
                '<p style="color:#dc2626">Engine not available</p>', status_code=503
            )
        conflict = await storage.get_conflict_by_id(conflict_id)
        if not conflict or conflict["status"] != "open":
            full = await storage.get_conflict_with_facts(conflict_id)
            return HTMLResponse(_render_conflict_card(full or conflict or {}))

        try:
            await engine.resolve(
                conflict_id=conflict_id,
                resolution_type="dismissed",
                resolution="Dismissed via dashboard — false positive.",
            )
        except Exception as exc:
            return HTMLResponse(
                f'<p style="color:#dc2626">Error: {_esc(str(exc))}</p>', status_code=400
            )

        updated = await storage.get_conflict_with_facts(conflict_id)
        return HTMLResponse(_render_conflict_card(updated or conflict))

    async def timeline(request: Request) -> HTMLResponse:
        scope = request.query_params.get("scope") or ""
        facts = await storage.get_fact_timeline(scope=scope or None, limit=100)
        scopes = await storage.get_distinct_scopes()
        return HTMLResponse(_render_timeline(facts, scopes=scopes, scope=scope))

    async def agents_view(request: Request) -> HTMLResponse:
        search_query = request.query_params.get("q", "").strip()
        agents = await storage.get_agents()
        feedback = await storage.get_detection_feedback_stats()
        return HTMLResponse(_render_agents(agents, feedback, search_query=search_query))

    async def expiring_view(request: Request) -> HTMLResponse:
        days = int(request.query_params.get("days", "7"))
        facts = await storage.get_expiring_facts(days_ahead=days)
        return HTMLResponse(_render_expiring(facts, days))

    async def settings_view(request: Request) -> HTMLResponse:
        from engram.workspace import read_workspace

        ws = read_workspace()
        workspace_info = None

        if ws:
            workspace_info = {
                "engram_id": ws.engram_id,
                "schema": ws.schema,
                "anonymous_mode": ws.anonymous_mode,
                "anon_agents": ws.anon_agents,
                "is_creator": ws.is_creator,
                "display_name": ws.display_name,
                "description": ws.description,
            }

            # Get invite keys from storage
            try:
                if ws.db_url:
                    from engram.postgres_storage import PostgresStorage

                    pg_storage = PostgresStorage(
                        db_url=ws.db_url, workspace_id=ws.engram_id, schema=ws.schema
                    )
                    await pg_storage.connect()
                    workspace_info["invite_keys"] = await pg_storage.get_invite_keys()
                    await pg_storage.close()
                else:
                    workspace_info["invite_keys"] = await storage.get_invite_keys()
            except Exception:
                workspace_info["invite_keys"] = []

        return HTMLResponse(_render_settings(workspace_info))

    async def rename_workspace(request: Request) -> HTMLResponse:
        from engram.workspace import read_workspace, set_workspace_setting

        error: str | None = None
        ws = read_workspace()

        if ws is None:
            error = "No workspace configured."
        elif not ws.is_creator:
            error = "Only the workspace creator can rename the workspace."
        else:
            try:
                form = await request.form()
                new_name = str(form.get("display_name", "")).strip()
                if not new_name:
                    raise ValueError("Workspace name cannot be empty.")
                set_workspace_setting("display_name", new_name)
                # Persist to database
                if ws.db_url:
                    from engram.postgres_storage import PostgresStorage

                    pg = PostgresStorage(
                        db_url=ws.db_url, workspace_id=ws.engram_id, schema=ws.schema
                    )
                    await pg.connect()
                    await pg.update_workspace_display_name(ws.engram_id, new_name)
                    await pg.close()
                else:
                    await storage.update_workspace_display_name(ws.engram_id, new_name)
            except Exception as exc:
                error = str(exc)

        # Re-read updated config
        ws = read_workspace()
        workspace_info = None
        if ws:
            workspace_info = {
                "engram_id": ws.engram_id,
                "schema": ws.schema,
                "anonymous_mode": ws.anonymous_mode,
                "anon_agents": ws.anon_agents,
                "is_creator": ws.is_creator,
                "display_name": ws.display_name,
                "description": ws.description,
            }
            try:
                if ws.db_url:
                    from engram.postgres_storage import PostgresStorage

                    pg_storage = PostgresStorage(
                        db_url=ws.db_url, workspace_id=ws.engram_id, schema=ws.schema
                    )
                    await pg_storage.connect()
                    workspace_info["invite_keys"] = await pg_storage.get_invite_keys()
                    await pg_storage.close()
                else:
                    workspace_info["invite_keys"] = await storage.get_invite_keys()
            except Exception:
                workspace_info["invite_keys"] = []

        if error and workspace_info:
            workspace_info["rename_error"] = error
        elif workspace_info:
            workspace_info["rename_success"] = True

        return HTMLResponse(_render_settings(workspace_info))

    async def delete_workspace_route(request: Request) -> Response:
        from engram.workspace import clear_workspace_config, read_workspace

        ws = read_workspace()
        if ws is None:
            return HTMLResponse("No workspace configured.", status_code=400)
        if not ws.is_creator:
            return HTMLResponse(
                "Only the workspace creator can delete the workspace.", status_code=403
            )

        try:
            if ws.db_url:
                from engram.postgres_storage import PostgresStorage

                pg = PostgresStorage(db_url=ws.db_url, workspace_id=ws.engram_id, schema=ws.schema)
                await pg.connect()
                await pg.delete_workspace(ws.engram_id)
                await pg.close()
            else:
                await storage.delete_workspace(ws.engram_id)
            clear_workspace_config()
        except Exception as exc:
            logger.error("Failed to delete workspace: %s", exc)
            return HTMLResponse(f"Error deleting workspace: {_esc(str(exc))}", status_code=500)

        from starlette.responses import RedirectResponse

        return RedirectResponse("/dashboard/settings", status_code=303)

    return [
        Route("/dashboard", index, methods=["GET"]),
        Route("/dashboard/facts", knowledge_base, methods=["GET"]),
        Route("/dashboard/facts/{fact_id}", fact_detail, methods=["GET"]),
        Route("/dashboard/facts/{fact_id}/lineage", fact_lineage, methods=["GET"]),
        Route("/dashboard/conflicts", conflict_queue, methods=["GET"]),
        Route("/dashboard/conflicts/{conflict_id}/approve", approve_suggestion, methods=["POST"]),
        Route("/dashboard/conflicts/{conflict_id}/dismiss", dismiss_conflict, methods=["POST"]),
        Route("/dashboard/timeline", timeline, methods=["GET"]),
        Route("/dashboard/agents", agents_view, methods=["GET"]),
        Route("/dashboard/expiring", expiring_view, methods=["GET"]),
        Route("/dashboard/settings", settings_view, methods=["GET"]),
        Route("/dashboard/settings/rename", rename_workspace, methods=["POST"]),
        Route("/dashboard/settings/delete", delete_workspace_route, methods=["POST"]),
        Route("/", landing, methods=["GET"]),
    ]


# ── Landing page (mirrors api/index.py for local server) ────────────
# Imported by the local server; the Vercel deployment uses api/index.py directly.


def _render_landing() -> str:
    # Import the canonical version from api/index if available,
    # otherwise fall back to a minimal redirect.
    try:
        from api.index import _render_landing as _vercel_landing

        return _vercel_landing()
    except ImportError:
        pass

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=/dashboard">
<title>Engram</title></head>
<body style="background:#f0f9f0;color:#2d3b2d;font-family:sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh;">
<p>🌿 Redirecting to <a href="/dashboard" style="color:#16a34a;">dashboard</a>...</p>
</body></html>"""


# ── Dashboard HTML rendering ─────────────────────────────────────────

_HTMX_SCRIPT = '<script src="https://unpkg.com/htmx.org@2.0.4"></script>'

_DASH_STYLE = """
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f0f9f0; color: #2d3b2d; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    position: relative; min-height: 100vh;
  }
  /* Decorative leaves */
  body::before {
    content: '🌿'; position: fixed; top: 1.2rem; right: 1.5rem;
    font-size: 1.6rem; opacity: 0.35; pointer-events: none; z-index: 0;
  }
  body::after {
    content: '🍃 🌱 🍀';
    position: fixed; bottom: 1rem; left: 1.5rem;
    font-size: 1.1rem; opacity: 0.25; pointer-events: none; z-index: 0;
    letter-spacing: 0.4rem;
  }
  .container { max-width: 1200px; margin: 0 auto; padding: 1.5rem; position: relative; z-index: 1; }

  .dash-header { display: flex; align-items: center; justify-content: space-between;
                 margin-bottom: 1.5rem; flex-wrap: wrap; gap: 0.75rem; }
  .dash-title { display: flex; align-items: center; gap: 0.5rem; }
  .dash-title h1 { font-size: 1.25rem; font-weight: 600; color: #1a3a1a; }
  .dash-title h1::before { content: '🌿 '; }
  .dash-title .dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80;
                     box-shadow: 0 0 8px rgba(74,222,128,0.5); }
  .back-link { color: #5a8a5a; text-decoration: none; font-size: 0.8rem;
               transition: color 0.15s; }
  .back-link:hover { color: #2d6a2d; }

  nav { display: flex; gap: 0.25rem; margin-bottom: 1.5rem;
        background: rgba(74,222,128,0.08); border-radius: 10px;
        padding: 0.25rem; width: fit-content; flex-wrap: wrap; }
  nav a { color: #5a8a5a; text-decoration: none; padding: 0.45rem 0.9rem;
          border-radius: 8px; font-size: 0.8rem; font-weight: 500;
          transition: all 0.15s; }
  nav a:hover { color: #1a5a1a; background: rgba(74,222,128,0.1); }
  nav a.active { background: rgba(74,222,128,0.18); color: #15803d; }

  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
           gap: 0.75rem; margin-bottom: 1.5rem; }
  .stat { background: #fff; border: 1px solid #c6e9c6;
          border-radius: 12px; padding: 1.25rem;
          box-shadow: 0 1px 3px rgba(0,80,0,0.04); }
  .stat-value { font-size: 2rem; font-weight: 700; color: #1a3a1a;
                letter-spacing: -0.02em; }
  .stat-label { font-size: 0.8rem; color: #5a8a5a; margin-top: 0.15rem; }
  .stat-accent .stat-value { color: #16a34a; }
  .stat-warn .stat-value { color: #d97706; }
  .stat-ok .stat-value { color: #22c55e; }

  h2 { font-size: 1rem; font-weight: 600; color: #1a3a1a; margin-bottom: 0.75rem; }
  h2::before { content: '🍃 '; font-size: 0.9rem; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 0.6rem 0.75rem; font-size: 0.7rem; font-weight: 500;
       color: #5a8a5a; text-transform: uppercase; letter-spacing: 0.05em;
       border-bottom: 1px solid #c6e9c6; background: #f7fdf7; }
  td { padding: 0.6rem 0.75rem; font-size: 0.8rem; color: #3d5c3d;
       border-bottom: 1px solid #e2f2e2; }
  tr:hover td { background: #edf7ed; }
  .content-cell { max-width: 360px; overflow: hidden; text-overflow: ellipsis;
                  white-space: nowrap; }

  .badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 100px;
           font-size: 0.7rem; font-weight: 500; }
  .badge-high { background: #fee2e2; color: #dc2626; }
  .badge-medium { background: #fef3c7; color: #d97706; }
  .badge-low { background: #dcfce7; color: #16a34a; }
  .badge-open { background: #fee2e2; color: #dc2626; }
  .badge-resolved { background: #dcfce7; color: #16a34a; }
  .badge-dismissed { background: #f0f9f0; color: #5a8a5a; }
  .badge-verified { background: #dcfce7; color: #16a34a; }
  .badge-unverified { background: #fef3c7; color: #d97706; }

  .timeline-bar { height: 6px; border-radius: 3px; background: #4ade80; min-width: 4px; }
  .timeline-bar.superseded { background: #c6e9c6; }

  .filter-bar { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 1rem;
                flex-wrap: wrap; }
  input, select { background: #fff; color: #2d3b2d;
                  border: 1px solid #c6e9c6; border-radius: 8px;
                  padding: 0.45rem 0.75rem; font-size: 0.8rem;
                  font-family: 'DM Sans', sans-serif; transition: border-color 0.15s; }
  input:focus, select:focus { outline: none; border-color: #4ade80;
                              box-shadow: 0 0 0 3px rgba(74,222,128,0.15); }
  input::placeholder { color: #9ab89a; }
  button[type="submit"] { background: #dcfce7; color: #15803d;
                          border: 1px solid #86efac; border-radius: 8px;
                          padding: 0.45rem 1rem; font-size: 0.8rem; cursor: pointer;
                          font-family: 'DM Sans', sans-serif; font-weight: 500;
                          transition: all 0.15s; }
  button[type="submit"]:hover { background: #bbf7d0; }

  .table-wrap { background: #fff; border: 1px solid #c6e9c6;
                border-radius: 12px; overflow: hidden;
                box-shadow: 0 1px 3px rgba(0,80,0,0.04); }
  .table-wrap table { margin: 0; }
  .count-note { color: #5a8a5a; font-size: 0.75rem; margin-top: 0.75rem; }

  /* Conflict cards */
  .conflict-cards { display: flex; flex-direction: column; gap: 1rem; }
  .conflict-card { background: #fff; border: 1px solid #c6e9c6;
                   border-radius: 12px; padding: 1.25rem;
                   box-shadow: 0 1px 3px rgba(0,80,0,0.04); }
  .conflict-card.auto-resolved { border-color: #e2f2e2; opacity: 0.8; }
  .conflict-header { display: flex; align-items: center; gap: 0.5rem;
                     flex-wrap: wrap; margin-bottom: 0.9rem; }
  .conflict-id { font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
                 color: #9ab89a; }
  .tier-tag { font-family: 'JetBrains Mono', monospace; font-size: 0.68rem;
              background: #f0f9f0; color: #5a8a5a; padding: 0.1rem 0.4rem;
              border-radius: 4px; border: 1px solid #c6e9c6; }
  .escalation-note { font-size: 0.7rem; color: #d97706; margin-left: auto; }
  .badge-auto { background: #e0f2fe; color: #0369a1; }
  .badge-genuine { background: #fee2e2; color: #dc2626; }
  .badge-evolution { background: #e0f2fe; color: #0369a1; }
  .badge-ambiguous { background: #fef3c7; color: #d97706; }

  .conflict-facts { display: grid; grid-template-columns: 1fr auto 1fr;
                    gap: 0.75rem; align-items: start; margin-bottom: 0.75rem; }
  .fact-box { background: #f7fdf7; border: 1px solid #e2f2e2;
              border-radius: 8px; padding: 0.75rem; }
  .fact-content { font-size: 0.82rem; color: #1a3a1a; margin-bottom: 0.35rem;
                  line-height: 1.45; }
  .fact-meta { font-size: 0.7rem; color: #9ab89a; }
  .vs-divider { display: flex; align-items: center; padding-top: 1rem;
                font-size: 0.75rem; font-weight: 600; color: #d97706; }

  .conflict-explanation { font-size: 0.78rem; color: #5a8a5a;
                           font-style: italic; margin-bottom: 0.75rem; }

  .conflict-summary { font-size: 0.8rem; color: #1a3a1a; background: #fef3c7;
                      border: 1px solid #fcd34d; border-radius: 6px; padding: 0.5rem;
                      margin-bottom: 0.75rem; font-family: 'DM Sans', sans-serif; }

  .suggestion-box { background: #f0fdf4; border: 1px solid #86efac;
                    border-radius: 8px; padding: 0.9rem; margin-bottom: 0.75rem; }
  .suggestion-header { display: flex; align-items: center; gap: 0.5rem;
                       font-size: 0.75rem; font-weight: 600; color: #15803d;
                       margin-bottom: 0.5rem; }
  .suggestion-text { font-size: 0.82rem; color: #1a3a1a; margin-bottom: 0.4rem; }
  .suggestion-reasoning { font-size: 0.75rem; color: #5a8a5a; margin-bottom: 0.75rem; }
  .suggestion-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }

  .btn-approve { background: #dcfce7; color: #15803d; border: 1px solid #86efac;
                 border-radius: 8px; padding: 0.4rem 0.9rem; font-size: 0.78rem;
                 cursor: pointer; font-family: 'DM Sans', sans-serif; font-weight: 500;
                 transition: all 0.15s; }
  .btn-approve:hover { background: #bbf7d0; }
  .btn-dismiss { background: #f0f9f0; color: #5a8a5a; border: 1px solid #c6e9c6;
                 border-radius: 8px; padding: 0.4rem 0.9rem; font-size: 0.78rem;
                 cursor: pointer; font-family: 'DM Sans', sans-serif;
                 transition: all 0.15s; }
  .btn-dismiss:hover { background: #e2f2e2; }

  .resolution-note { font-size: 0.75rem; color: #5a8a5a; padding-top: 0.5rem;
                     border-top: 1px solid #e2f2e2; margin-top: 0.75rem; }

  /* Theme toggle */
  .theme-toggle { background: #fff; border: 1px solid #c6e9c6; border-radius: 8px;
                  padding: 0.4rem 0.6rem; cursor: pointer; font-size: 1rem; }

  /* Keyboard shortcuts */
  .keyboard-hints { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem;
                    padding: 0.75rem; background: #f0f9f0; border-radius: 8px;
                    font-size: 0.8rem; color: #5a8a5a; }
  .keyboard-hints kbd { background: #fff; border: 1px solid #c6e9c6; border-radius: 4px;
                        padding: 0.15rem 0.4rem; font-family: 'JetBrains Mono', monospace;
                        font-size: 0.75rem; }
  .conflict-card.focused { outline: 3px solid #4ade80; outline-offset: 2px; }

  @media (max-width: 640px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .content-cell { max-width: 180px; }
    .conflict-facts { grid-template-columns: 1fr; }
    .vs-divider { display: none; }
  }
</style>
"""


def _dash_layout(
    title: str, body: str, active: str = "", dark_mode: bool = False, workspace_name: str = ""
) -> str:
    def _nav_cls(name: str) -> str:
        return ' class="active"' if name == active else ""

    theme_class = "dark" if dark_mode else ""
    theme_script = """
    <script>
      (function() {
        const saved = localStorage.getItem('engram-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const isDark = saved === 'dark' || (!saved && prefersDark);
        if (isDark) document.documentElement.classList.add('dark');
      })();
    </script>"""

    display_name_html = (
        f'<span style="font-weight:400;opacity:0.7;">— {workspace_name}</span>'
        if workspace_name
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Engram Dashboard</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='28' font-size='28'%3E%F0%9F%8C%BF%3C/text%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  {_HTMX_SCRIPT}
  {theme_script}
  {_DASH_STYLE}
</head>
<body class="{theme_class}">
  <div class="container">
    <div class="dash-header">
      <div class="dash-title">
        <div class="dot"></div>
        <h1>Engram Dashboard{display_name_html}</h1>
      </div>
      <div style="display:flex;gap:1rem;align-items:center;">
        <button onclick="toggleTheme()" class="theme-toggle" title="Toggle dark mode">
          {"☀️" if dark_mode else "🌙"}
        </button>
        <a href="/" class="back-link">&larr; Back</a>
      </div>
    </div>
    <nav>
      <a href="/dashboard"{_nav_cls("overview")}>Overview</a>
      <a href="/dashboard/facts"{_nav_cls("facts")}>Knowledge Base</a>
      <a href="/dashboard/conflicts"{_nav_cls("conflicts")}>Conflicts</a>
      <a href="/dashboard/timeline"{_nav_cls("timeline")}>Timeline</a>
      <a href="/dashboard/agents"{_nav_cls("agents")}>Agents</a>
      <a href="/dashboard/expiring"{_nav_cls("expiring")}>Expiring</a>
      <a href="/dashboard/settings"{_nav_cls("settings")}>Settings</a>
      <a href="#" onclick="showShortcuts();return false;" style="margin-left:auto;font-size:0.75rem;color:#9ab89a;">⌨ Shortcuts</a>
    </nav>
    {body}
  </div>
  <script>
    function toggleTheme() {{
      const html = document.documentElement;
      const isDark = html.classList.contains('dark');
      html.classList.toggle('dark');
      localStorage.setItem('engram-theme', isDark ? 'light' : 'dark');
    }}
    function showShortcuts() {{
      alert('Keyboard Shortcuts:\n\n' +
        'j/k - Navigate conflicts up/down\n' +
        'a - Approve conflict fact A\n' +
        'b - Approve conflict fact B\n' +
        's - Dismiss/skip conflict\n' +
        '? - Show this help');
    }}
    // Keyboard navigation for conflict queue
    document.addEventListener('keydown', function(e) {{
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      const path = window.location.pathname;
      if (!path.includes('/dashboard/conflicts')) return;
      
      const cards = document.querySelectorAll('.conflict-card');
      if (!cards.length) return;
      
      let current = document.querySelector('.conflict-card.focused');
      let idx = current ? Array.from(cards).indexOf(current) : -1;
      
      if (e.key === 'j') {{
        e.preventDefault();
        if (current) current.classList.remove('focused');
        idx = Math.min(idx + 1, cards.length - 1);
        cards[idx].classList.add('focused');
        cards[idx].scrollIntoView({{behavior: 'smooth', block: 'center'}});
      }} else if (e.key === 'k') {{
        e.preventDefault();
        if (current) current.classList.remove('focused');
        idx = Math.max(idx - 1, 0);
        cards[idx].classList.add('focused');
        cards[idx].scrollIntoView({{behavior: 'smooth', block: 'center'}});
      }} else if (e.key === 'a' && current) {{
        const btn = current.querySelector('.btn-approve');
        if (btn) {{ e.preventDefault(); btn.click(); }}
      }} else if (e.key === 'b' && current) {{
        const btns = current.querySelectorAll('.btn-approve, .btn-dismiss');
        if (btns.length > 1) {{ e.preventDefault(); btns[1].click(); }}
      }} else if (e.key === 's' && current) {{
        const btn = current.querySelector('.btn-dismiss');
        if (btn) {{ e.preventDefault(); btn.click(); }}
      }}
    }});
  </script>
</body>
</html>"""


def _render_index(
    facts_count: int,
    total_facts: int,
    open_conflicts: int,
    resolved_conflicts: int,
    agents: list[dict],
    expiring_count: int,
    workspace_error: str | None = None,
    recent_activity: list[dict] | None = None,
) -> str:
    # Show workspace error if present
    error_html = ""
    if workspace_error:
        error_html = f"""
        <div style="background:#fee2e2;border:1px solid #ef4444;padding:12px;margin-bottom:16px;border-radius:6px;">
            <strong style="color:#dc2626;">⚐ Workspace Connection Error</strong>
            <p style="color:#991b1b;margin:8px 0 0 0;">{workspace_error}</p>
            <p style="color:#7f1d1d;margin:8px 0 0 0;font-size:13px;">
                Run <code>engram verify</code> to diagnose or <code>engram setup</code> to reconfigure.
            </p>
        </div>
        """

    # Onboarding checklist for new workspaces
    checklist_items = [
        ("First fact committed", facts_count > 0, "/dashboard/facts"),
        ("Teammate invited", len(agents) > 1, "/dashboard"),
        ("First conflict detected", open_conflicts > 0, "/dashboard/conflicts"),
        ("First conflict resolved", resolved_conflicts > 0, "/dashboard/conflicts"),
    ]

    all_complete = all(checked for _, checked, _ in checklist_items)
    checklist_html = ""
    if not all_complete:
        checklist_rows = ""
        for label, checked, link in checklist_items:
            status = "✓" if checked else "☐"
            style = "color:#16a34a;" if checked else "color:#6b7280;"
            checklist_rows += f"""
            <tr>
                <td style="padding:6px 12px;"><span style="{style}font-size:1.1rem;">{status}</span></td>
                <td style="padding:6px 12px;color:#374151;">{label}</td>
                <td style="padding:6px 12px;"><a href="{link}" style="color:#2563eb;font-size:0.85rem;">View</a></td>
            </tr>"""

        checklist_html = f"""
        <div style="background:#f0f9ff;border:1px solid #bae6fd;padding:16px;margin-bottom:20px;border-radius:8px;">
            <h3 style="margin:0 0 12px 0;font-size:1rem;color:#0369a1;">🚀 Getting Started</h3>
            <p style="margin:0 0 12px 0;font-size:0.85rem;color:#64748b;">Complete these steps to get the most out of Engram:</p>
            <table style="width:100%;border-collapse:collapse;">{checklist_rows}</table>
        </div>"""

    body = f"""
    {error_html}
    {checklist_html}
    <div class="stats">
      <div class="stat stat-accent">
        <div class="stat-value">{facts_count}</div>
        <div class="stat-label">Current Facts</div>
      </div>
      <div class="stat">
        <div class="stat-value">{total_facts}</div>
        <div class="stat-label">Total Facts</div>
      </div>
      <div class="stat stat-warn">
        <div class="stat-value">{open_conflicts}</div>
        <div class="stat-label">Open Conflicts</div>
      </div>
      <div class="stat stat-ok">
        <div class="stat-value">{resolved_conflicts}</div>
        <div class="stat-label">Resolved</div>
      </div>
      <div class="stat">
        <div class="stat-value">{len(agents)}</div>
        <div class="stat-label">Agents</div>
      </div>
      <div class="stat">
        <div class="stat-value">{expiring_count}</div>
        <div class="stat-label">Expiring (7d)</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:2fr 1fr;gap:1.5rem;">
      <div>
        <h2>Recent Activity</h2>
        <div class="table-wrap">
        <table>
          <tr><th>Fact</th><th>Scope</th><th>When</th></tr>
          {"".join(f"<tr><td class='content-cell'>{_esc(f.get('content', '')[:60])}</td><td>{_esc(f.get('scope', ''))}</td><td>{_esc(f.get('committed_at', '')[:16])}</td></tr>" for f in (recent_activity or [])[:10])}
        </table>
        </div>
      </div>
      <div>
        <h2>Recent Agents</h2>
        <div class="table-wrap">
        <table>
          <tr><th>Agent</th><th>Commits</th></tr>
          {"".join(f"<tr><td>{_esc(a.get('agent_id', ''))}</td><td>{a.get('total_commits', 0)}</td></tr>" for a in agents[:5])}
        </table>
        </div>
      </div>
    </div>"""
    return _dash_layout("Overview", body, active="overview", workspace_name=_get_workspace_name())


def _agent_row(a: dict) -> str:
    total = a.get("total_commits", 0)
    flagged = a.get("flagged_commits", 0)
    ratio = f"{flagged}/{total}" if total else "0/0"
    return (
        f"<tr><td>{_esc(a['agent_id'])}</td><td>{_esc(a.get('engineer', ''))}</td>"
        f"<td>{total}</td><td>{ratio}</td>"
        f"<td>{_esc(a.get('last_seen', '') or '')}</td></tr>"
    )


def _render_facts_table(
    facts: list[dict],
    conflict_ids: set[str],
    search_query: str = "",
    scope: str = "",
    fact_type: str = "",
    as_of: str = "",
    offset: int = 0,
    limit: int = 100,
    scopes: list[str] | None = None,
) -> str:
    import re

    rows = []
    for f in facts:
        has_conflict = f["id"] in conflict_ids
        verified = f.get("provenance") is not None
        conflict_badge = '<span class="badge badge-open">conflict</span>' if has_conflict else ""
        ver_badge = (
            '<span class="badge badge-verified">verified</span>'
            if verified
            else '<span class="badge badge-unverified">unverified</span>'
        )

        # Highlight search terms in content — escape first, then inject safe <mark> tags
        content_escaped = _esc(f["content"])
        if search_query:
            pattern = re.compile(re.escape(_esc(search_query)), re.IGNORECASE)
            content_escaped = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", content_escaped)

        rows.append(
            f"<tr><td class='content-cell'>{content_escaped}</td>"
            f"<td>{_esc(f['scope'])}</td><td>{f['confidence']:.2f}</td>"
            f"<td>{_esc(f['fact_type'])}</td><td>{_esc(f['agent_id'])}</td>"
            f"<td>{conflict_badge} {ver_badge}</td>"
            f"<td>{_esc(f.get('committed_at', '')[:19])}</td></tr>"
        )

    prev_offset = max(0, offset - limit)
    next_offset = offset + limit if len(facts) == limit else offset

    def _page_qs(new_offset: int) -> str:
        parts = []
        if search_query:
            parts.append(f"q={_esc(search_query)}")
        if scope:
            parts.append(f"scope={_esc(scope)}")
        if fact_type:
            parts.append(f"fact_type={_esc(fact_type)}")
        if as_of:
            parts.append(f"as_of={_esc(as_of)}")
        parts.append(f"offset={new_offset}&limit={limit}")
        return "?" + "&".join(parts)

    pagination = ""
    if offset > 0 or len(facts) == limit:
        prev_disabled = ' style="pointer-events:none;opacity:0.5;"' if offset == 0 else ""
        next_disabled = ' style="pointer-events:none;opacity:0.5;"' if len(facts) < limit else ""
        pagination = f"""
        <div class="pagination" style="display:flex;gap:0.5rem;margin-top:1rem;">
          <a href="{_page_qs(prev_offset)}" class="btn-dismiss"{prev_disabled}>&larr; Previous</a>
          <span style="padding:0.4rem 0.8rem;color:#5a8a5a;">Page {offset // limit + 1}</span>
          <a href="{_page_qs(next_offset)}" class="btn-dismiss"{next_disabled}>Next &rarr;</a>
        </div>"""

    scope_options = ""
    if scopes:
        scope_options = "".join(f'<option value="{_esc(s)}">{_esc(s)}</option>' for s in scopes)

    def _ft_option(val: str, label: str) -> str:
        sel = " selected" if fact_type == val else ""
        return f'<option value="{val}"{sel}>{label}</option>'

    body = f"""
    <h2>Knowledge Base</h2>
    <div class="filter-bar">
      <form method="get" action="/dashboard/facts" style="display:flex;gap:0.5rem;flex-wrap:wrap;">
        <input type="text" name="q" placeholder="Search facts..." value="{_esc(search_query)}" style="min-width:200px;">
        <input name="scope" placeholder="Scope filter" value="{_esc(scope)}" list="scopes-list">
        <datalist id="scopes-list">{scope_options}</datalist>
        <select name="fact_type">
          {_ft_option("", "All types")}
          {_ft_option("observation", "observation")}
          {_ft_option("inference", "inference")}
          {_ft_option("decision", "decision")}
        </select>
        <input name="as_of" placeholder="as_of (ISO 8601)" value="{_esc(as_of)}">
        <input type="hidden" name="offset" value="{offset}">
        <input type="hidden" name="limit" value="{limit}">
        <button type="submit">Search</button>
        <a href="?fact_type=observation" class="btn-dismiss">Observations</a>
        <a href="?fact_type=inference" class="btn-dismiss">Inferences</a>
        <a href="?fact_type=decision" class="btn-dismiss">Decisions</a>
      </form>
    </div>
    <div class="table-wrap">
    <table>
      <tr><th>Content</th><th>Scope</th><th>Confidence</th><th>Type</th>
          <th>Agent</th><th>Status</th><th>Committed</th></tr>
      {"".join(rows)}
    </table>
    </div>
    <p class="count-note">{len(facts)} fact(s)</p>
    {pagination}"""
    return _dash_layout(
        "Knowledge Base", body, active="facts", workspace_name=_get_workspace_name()
    )


def _render_conflicts_page(
    conflicts: list[dict],
    stats: dict | None = None,
    scope: str | None = None,
    status: str = "open",
) -> str:
    """Render the Conflicts tab."""
    open_count = (
        stats.get("open", 0) if stats else sum(1 for c in conflicts if c.get("status") == "open")
    )
    resolved_count = (
        stats.get("resolved", 0)
        if stats
        else sum(1 for c in conflicts if c.get("status") == "resolved")
    )

    if not conflicts:
        empty_html = (
            '<div style="text-align:center;padding:4rem 1rem;color:#5a8a5a;">'
            '<div style="font-size:2.5rem;margin-bottom:0.75rem;">✓</div>'
            '<div style="font-size:1rem;font-weight:600;color:#1a3a1a;">No conflicts detected</div>'
            '<div style="font-size:0.85rem;margin-top:0.4rem;">Your agents are aligned.</div>'
            "</div>"
        )
        cards_html = empty_html
    else:
        cards_html = (
            '<div class="conflict-cards">'
            + "".join(_render_conflict_card(c) for c in conflicts)
            + "</div>"
        )

    def _status_option(val: str, label: str) -> str:
        sel = " selected" if status == val else ""
        return f'<option value="{val}"{sel}>{label}</option>'

    filter_form = f"""
    <form method="get" action="/dashboard/conflicts" class="filter-bar">
      <input name="scope" placeholder="Filter by scope…" value="{_esc(scope or "")}">
      <select name="status">
        {_status_option("open", "Open")}
        {_status_option("resolved", "Resolved")}
        {_status_option("dismissed", "Dismissed")}
        {_status_option("all", "All")}
      </select>
      <button type="submit">Filter</button>
    </form>"""

    body = f"""
    <div class="dash-header">
      <div class="dash-title"><h2 style="margin:0;">Conflicts</h2></div>
      <div style="display:flex;gap:0.5rem;">
        <span class="badge badge-open">{open_count} open</span>
        <span class="badge badge-resolved">{resolved_count} resolved</span>
      </div>
    </div>
    {filter_form}
    {cards_html}"""

    return _dash_layout("Conflicts", body, active="conflicts", workspace_name=_get_workspace_name())


def _render_conflict_card(c: dict) -> str:
    """Render one conflict card. Handles both engine dicts and flat storage rows."""
    # Normalise nested vs flat shapes
    if "fact_a" in c:
        fact_a = c["fact_a"]
        fact_b = c["fact_b"]
        cid = c.get("conflict_id", "")
        explanation = c.get("explanation", "")
        status = c.get("status", "open")
        severity = c.get("severity", "high")
        conflict_type = c.get("conflict_type", "genuine")
        detected = (c.get("detected_at") or "")[:16]
        resolution = c.get("resolution") or ""
        resolution_type = c.get("resolution_type") or ""
        suggested_text = c.get("suggested_resolution") or ""
        suggested_type = c.get("suggested_resolution_type") or ""
        winning_id = c.get("suggested_winning_fact_id") or ""
        reasoning = c.get("suggestion_reasoning") or ""
        fact_a_id = fact_a.get("fact_id", "")
        fact_b_id = fact_b.get("fact_id", "")
    else:
        fact_a = {
            "content": c.get("fact_a_content", ""),
            "scope": c.get("fact_a_scope", ""),
            "agent_id": c.get("fact_a_agent", ""),
            "confidence": c.get("fact_a_confidence", 0),
        }
        fact_b = {
            "content": c.get("fact_b_content", ""),
            "scope": c.get("fact_b_scope", ""),
            "agent_id": c.get("fact_b_agent", ""),
            "confidence": c.get("fact_b_confidence", 0),
        }
        cid = c.get("id", "")
        explanation = c.get("explanation", "")
        status = c.get("status", "open")
        severity = c.get("severity", "high")
        conflict_type = c.get("conflict_type", "genuine")
        detected = (c.get("detected_at") or "")[:16]
        resolution = c.get("resolution") or ""
        resolution_type = c.get("resolution_type") or ""
        suggested_text = c.get("suggested_resolution") or ""
        suggested_type = c.get("suggested_resolution_type") or ""
        winning_id = c.get("suggested_winning_fact_id") or ""
        reasoning = c.get("suggestion_reasoning") or ""
        fact_a_id = c.get("fact_a_id", "")
        fact_b_id = c.get("fact_b_id", "")

    sev_badge_cls = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}.get(
        severity, "badge-low"
    )
    status_badge_cls = {
        "open": "badge-open",
        "resolved": "badge-resolved",
        "dismissed": "badge-dismissed",
    }.get(status, "badge-dismissed")
    type_badge_cls = {
        "genuine": "badge-genuine",
        "evolution": "badge-evolution",
        "ambiguous": "badge-ambiguous",
    }.get(conflict_type, "badge-genuine")

    def _fact_box(f: dict, label: str) -> str:
        content = _esc(str(f.get("content") or ""))
        scope = _esc(str(f.get("scope") or ""))
        agent = _esc(str(f.get("agent_id") or ""))
        return (
            f'<div class="fact-box">'
            f'<div class="fact-meta" style="font-weight:600;margin-bottom:0.35rem;text-transform:uppercase;font-size:0.68rem;">{label}</div>'
            f'<div class="fact-content">{content}</div>'
            f'<div class="fact-meta">scope: {scope} · agent: {agent}</div>'
            f"</div>"
        )

    # Build action buttons for open conflicts
    actions_html = ""
    if status == "open":
        keep_a = (
            f'<button class="btn-approve" '
            f'hx-post="/dashboard/conflicts/{_esc(cid)}/approve" '
            f'hx-target="#conflict-{_esc(cid)}" hx-swap="outerHTML">Keep Fact A</button>'
        )
        keep_b = (
            f'<button class="btn-approve" '
            f'hx-post="/dashboard/conflicts/{_esc(cid)}/approve" '
            f'hx-target="#conflict-{_esc(cid)}" hx-swap="outerHTML">Keep Fact B</button>'
        )
        dismiss_btn = (
            f'<button class="btn-dismiss" '
            f'hx-post="/dashboard/conflicts/{_esc(cid)}/dismiss" '
            f'hx-target="#conflict-{_esc(cid)}" hx-swap="outerHTML">Dismiss</button>'
        )

        suggestion_html = ""
        if suggested_text:
            winning_label = ""
            if winning_id == fact_a_id:
                winning_label = " · keep Fact A"
            elif winning_id == fact_b_id:
                winning_label = " · keep Fact B"
            suggestion_html = (
                f'<div class="suggestion-box">'
                f'<div class="suggestion-header">🤖 Suggested: {_esc(suggested_type)}{_esc(winning_label)}</div>'
                f'<div class="suggestion-text">{_esc(suggested_text)}</div>'
                f'<div class="suggestion-reasoning">{_esc(reasoning)}</div>'
                f'<div class="suggestion-actions">'
                f'<button class="btn-approve" '
                f'hx-post="/dashboard/conflicts/{_esc(cid)}/approve" '
                f'hx-target="#conflict-{_esc(cid)}" hx-swap="outerHTML">Approve suggestion</button>'
                f"{dismiss_btn}</div></div>"
            )

        actions_html = (
            f'<div class="suggestion-actions" style="margin-top:0.75rem;">'
            f"{keep_a}{keep_b}{dismiss_btn}</div>"
            f"{suggestion_html}"
        )
    elif resolution:
        actions_html = (
            f'<div class="resolution-note">'
            f"Resolved as <strong>{_esc(resolution_type)}</strong>: {_esc(resolution)}"
            f"</div>"
        )

    return (
        f'<div id="conflict-{_esc(cid)}" class="conflict-card">'
        f'<div class="conflict-header">'
        f'<span class="badge {sev_badge_cls}">{_esc(severity)}</span>'
        f'<span class="badge {type_badge_cls}">{_esc(conflict_type)}</span>'
        f'<span class="conflict-id">{_esc(cid[:12])}</span>'
        f'<span style="color:#9ab89a;font-size:0.72rem;">{_esc(detected)}</span>'
        f'<span class="badge {status_badge_cls}" style="margin-left:auto;">{_esc(status)}</span>'
        f"</div>"
        f'<div class="conflict-facts">'
        f"{_fact_box(fact_a, 'Fact A')}"
        f'<div class="vs-divider">vs</div>'
        f"{_fact_box(fact_b, 'Fact B')}"
        f"</div>"
        f'<div class="conflict-explanation">{_esc(explanation)}</div>'
        f"{actions_html}"
        f"</div>"
    )


def _render_timeline(facts: list[dict], scopes: list[str] | None = None, scope: str = "") -> str:
    rows = []
    for f in facts:
        is_superseded = f.get("valid_until") is not None
        bar_class = "timeline-bar superseded" if is_superseded else "timeline-bar"
        valid_range = f.get("valid_from", "")[:10]
        if is_superseded:
            valid_range += f" → {f['valid_until'][:10]}"
        else:
            valid_range += " → current"
        rows.append(
            f"<tr><td class='content-cell'>{_esc(f['content'][:80])}</td>"
            f"<td>{_esc(f['scope'])}</td><td>{_esc(f['agent_id'])}</td>"
            f"<td>{valid_range}</td>"
            f"<td><div class='{bar_class}' style='width:60px;'></div></td></tr>"
        )
    scope_options = ""
    if scopes:
        scope_options = "".join(f'<option value="{_esc(s)}">{_esc(s)}</option>' for s in scopes)
    body = f"""
    <h2>Timeline</h2>
    <div class="filter-bar">
      <form method="get" action="/dashboard/timeline" style="display:flex;gap:0.5rem;">
        <input name="scope" placeholder="Scope filter" value="{_esc(scope)}" list="scopes-list">
        <datalist id="scopes-list">{scope_options}</datalist>
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class="table-wrap">
    <table>
      <tr><th>Content</th><th>Scope</th><th>Agent</th><th>Validity</th><th>Window</th></tr>
      {"".join(rows)}
    </table>
    </div>"""
    return _dash_layout("Timeline", body, active="timeline", workspace_name=_get_workspace_name())


def _render_agents(agents: list[dict], feedback: dict[str, int], search_query: str = "") -> str:
    rows = []
    filtered_agents = agents
    if search_query:
        filtered_agents = [
            a
            for a in agents
            if search_query.lower() in a.get("agent_id", "").lower()
            or search_query.lower() in a.get("engineer", "").lower()
        ]
    for a in filtered_agents:
        total = a.get("total_commits", 0)
        flagged = a.get("flagged_commits", 0)
        reliability = f"{(1 - flagged / total) * 100:.0f}%" if total > 0 else "N/A"
        rel_score = (1 - flagged / total) * 100 if total > 0 else 0
        rel_badge = (
            '<span class="badge badge-high">🔥 Top</span>' if rel_score >= 90 and total >= 5 else ""
        )
        rows.append(
            f"<tr><td>{_esc(a['agent_id'])}</td>"
            f"<td>{_esc(a.get('engineer', ''))}</td>"
            f"<td>{total}</td><td>{flagged}</td>"
            f"<td>{reliability} {rel_badge}</td>"
            f"<td>{_esc(a.get('registered_at', '')[:19])}</td>"
            f"<td>{_esc(a.get('last_seen', '') or '')[:19]}</td></tr>"
        )
    tp = feedback.get("true_positive", 0)
    fp = feedback.get("false_positive", 0)
    body = f"""
    <h2>Agent Activity</h2>
    <div class="filter-bar">
      <form method="get" action="/dashboard/agents" style="display:flex;gap:0.5rem;flex-wrap:wrap;">
        <input type="text" name="q" placeholder="Search agents..." value="{_esc(search_query)}" style="min-width:180px;">
        <button type="submit">Search</button>
      </form>
    </div>
    <div class="stats">
      <div class="stat">
        <div class="stat-value">{len(agents)}</div>
        <div class="stat-label">Total Agents</div>
      </div>
      <div class="stat stat-ok">
        <div class="stat-value">{tp}</div>
        <div class="stat-label">True Positives</div>
      </div>
      <div class="stat stat-warn">
        <div class="stat-value">{fp}</div>
        <div class="stat-label">False Positives</div>
      </div>
    </div>
    <div class="table-wrap">
    <table>
      <tr><th>Agent</th><th>Engineer</th><th>Commits</th><th>Flagged</th>
          <th>Reliability</th><th>Registered</th><th>Last Seen</th></tr>
      {"".join(rows)}
    </table>
    </div>
    <p class="count-note">{len(filtered_agents)} agent(s)</p>"""
    return _dash_layout("Agents", body, active="agents", workspace_name=_get_workspace_name())


def _render_expiring(facts: list[dict], days: int) -> str:
    rows = []
    for f in facts:
        rows.append(
            f"<tr><td class='content-cell'>{_esc(f['content'])}</td>"
            f"<td>{_esc(f['scope'])}</td><td>{f.get('ttl_days', '')}</td>"
            f"<td>{_esc(f.get('valid_until', '')[:19])}</td>"
            f"<td>{_esc(f['agent_id'])}</td></tr>"
        )
    body = f"""
    <h2>Expiring Facts (next {days} days)</h2>
    <div class="filter-bar">
      <form method="get" action="/dashboard/expiring" style="display:flex;gap:0.5rem;">
        <input name="days" type="number" value="{days}" min="1" max="90" style="width:80px;">
        <button type="submit">Update</button>
      </form>
    </div>
    <div class="table-wrap">
    <table>
      <tr><th>Content</th><th>Scope</th><th>TTL (days)</th><th>Expires</th><th>Agent</th></tr>
      {"".join(rows)}
    </table>
    </div>
    <p class="count-note">{len(facts)} fact(s) expiring within {days} day(s)</p>"""
    return _dash_layout(
        "Expiring Facts", body, active="expiring", workspace_name=_get_workspace_name()
    )


def _render_settings(workspace_info: dict | None) -> str:
    """Render workspace settings page."""
    if not workspace_info:
        body = """
        <div style="text-align:center;padding:2rem;">
            <p>No workspace configured.</p>
            <p>Run <code>engram setup</code> or <code>engram init</code> to create a workspace.</p>
        </div>"""
        return _dash_layout(
            "Settings", body, active="settings", workspace_name=_get_workspace_name()
        )

    engram_id = workspace_info.get("engram_id", "Unknown")
    schema = workspace_info.get("schema", "engram")
    anonymous_mode = workspace_info.get("anonymous_mode", False)
    anon_agents = workspace_info.get("anon_agents", False)
    invite_keys = workspace_info.get("invite_keys", [])

    # Render invite keys
    invite_keys_html = ""
    if invite_keys:
        rows = ""
        for key in invite_keys:
            expires = key.get("expires_at", "N/A")[:10] if key.get("expires_at") else "Never"
            uses = f"{key.get('uses', 0)}/{key.get('max_uses', '∞')}"
            status = "active" if key.get("is_valid", True) else "revoked"
            rows += f"""
            <tr>
                <td style="font-family:monospace;">{_esc(key.get("key", "")[:20])}...</td>
                <td>{expires}</td>
                <td>{uses}</td>
                <td><span class="badge badge-{status}">{status}</span></td>
                <td>
                    <button class="btn-dismiss" disabled style="opacity:0.5;">Revoke</button>
                </td>
            </tr>"""
        invite_keys_html = f"""
        <table style="width:100%;">
            <tr><th>Key</th><th>Expires</th><th>Uses</th><th>Status</th><th>Action</th></tr>
            {rows}
        </table>"""
    else:
        invite_keys_html = "<p style='color:#6b7280;'>No invite keys found.</p>"

    display_name = workspace_info.get("display_name", "")
    rename_error = workspace_info.get("rename_error", "")
    rename_success = workspace_info.get("rename_success", False)

    rename_feedback = ""
    if rename_error:
        rename_feedback = (
            f'<p style="color:#dc2626;font-size:0.8rem;margin-top:0.5rem;">{_esc(rename_error)}</p>'
        )
    elif rename_success:
        rename_feedback = '<p style="color:#16a34a;font-size:0.8rem;margin-top:0.5rem;">Workspace name updated.</p>'

    name_section = f"""
    <div style="margin-bottom:2rem;">
        <h3 style="font-size:1rem;color:#374151;margin-bottom:0.5rem;">Display Name</h3>
        <form method="post" action="/dashboard/settings/rename" style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;">
            <input type="text" name="display_name" value="{_esc(display_name)}" placeholder="e.g. Engineering Team" style="min-width:220px;">
            <button type="submit">Save</button>
        </form>
        {rename_feedback}
    </div>"""

    is_creator = workspace_info.get("is_creator", False)
    if is_creator:
        delete_section = """
    <div style="margin-bottom:2rem;border:2px solid #fca5a5;border-radius:8px;overflow:hidden;">
        <div style="background:#fef2f2;padding:1rem 1.25rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
            <div>
                <h3 style="font-size:1rem;color:#dc2626;margin-bottom:0.25rem;">Delete Workspace</h3>
                <p style="font-size:0.85rem;color:#991b1b;margin:0;">Permanently removes all facts, conflicts, and history.</p>
            </div>
            <button type="button" onclick="document.getElementById('delete-confirm-panel').style.display='block';this.style.display='none';"
                    style="background:#dc2626;color:#fff;border:none;padding:0.45rem 1.1rem;
                           border-radius:4px;cursor:pointer;font-size:0.9rem;white-space:nowrap;">
                Delete Workspace
            </button>
        </div>
        <div id="delete-confirm-panel" style="display:none;background:#fff1f2;border-top:2px solid #fca5a5;padding:1.25rem;">
            <p style="font-size:0.95rem;font-weight:600;color:#b91c1c;margin-bottom:0.5rem;">
                &#9888; This action cannot be undone.
            </p>
            <p style="font-size:0.85rem;color:#7f1d1d;margin-bottom:1rem;">
                All facts, conflict history, invite keys, and agent records for this workspace
                will be permanently deleted. There is no recovery option.
            </p>
            <div style="display:flex;gap:0.75rem;align-items:center;">
                <form method="post" action="/dashboard/settings/delete">
                    <button type="submit"
                            style="background:#b91c1c;color:#fff;border:none;padding:0.45rem 1.1rem;
                                   border-radius:4px;cursor:pointer;font-size:0.9rem;">
                        Yes, permanently delete
                    </button>
                </form>
                <button type="button"
                        onclick="document.getElementById('delete-confirm-panel').style.display='none';
                                 document.querySelector('[onclick*=delete-confirm-panel]').style.display='';"
                        style="background:none;border:1px solid #9ca3af;color:#374151;padding:0.45rem 1rem;
                               border-radius:4px;cursor:pointer;font-size:0.9rem;">
                    Cancel
                </button>
            </div>
        </div>
    </div>"""
    else:
        delete_section = """
    <div style="margin-bottom:2rem;padding:1rem;background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;">
        <h3 style="font-size:1rem;color:#dc2626;margin-bottom:0.25rem;">Delete Workspace</h3>
        <p style="font-size:0.85rem;color:#991b1b;margin:0;">Only the workspace creator can delete this workspace.</p>
    </div>"""

    body = f"""
    <h2>Workspace Settings</h2>

    {name_section}

    <div style="margin-bottom:2rem;">
        <h3 style="font-size:1rem;color:#374151;margin-bottom:0.5rem;">Workspace ID</h3>
        <code style="background:#f3f4f6;padding:0.5rem;border-radius:4px;">{engram_id}</code>
    </div>

    <div style="margin-bottom:2rem;">
        <h3 style="font-size:1rem;color:#374151;margin-bottom:0.5rem;">Database Schema</h3>
        <code style="background:#f3f4f6;padding:0.5rem;border-radius:4px;">{schema}</code>
    </div>

    <div style="margin-bottom:2rem;padding:1rem;background:#f0fdf4;border:1px solid #86efac;border-radius:8px;">
        <h3 style="font-size:1rem;color:#374151;margin-bottom:0.75rem;">Privacy Settings</h3>
        <div style="display:flex;flex-direction:column;gap:0.5rem;">
            <label style="display:flex;align-items:center;gap:0.5rem;">
                <input type="checkbox" {"checked" if anonymous_mode else ""} disabled>
                <span>Anonymous mode (hide engineer names)</span>
            </label>
            <label style="display:flex;align-items:center;gap:0.5rem;">
                <input type="checkbox" {"checked" if anon_agents else ""} disabled>
                <span>Randomize agent IDs each session</span>
            </label>
        </div>
        <p style="font-size:0.85rem;color:#6b7280;margin-top:0.5rem;">Settings can only be changed via CLI.</p>
    </div>

    <div style="margin-bottom:2rem;">
        <h3 style="font-size:1rem;color:#374151;margin-bottom:0.75rem;">Invite Keys</h3>
        <p style="font-size:0.85rem;color:#6b7280;margin-bottom:1rem;">Share these keys with teammates to join your workspace.</p>
        <div class="table-wrap">{invite_keys_html}</div>
    </div>

    {delete_section}"""

    return _dash_layout("Settings", body, active="settings", workspace_name=_get_workspace_name())


def _get_workspace_name() -> str:
    """Get the workspace display name for header."""
    try:
        from engram.workspace import read_workspace

        ws = read_workspace()
        if ws and ws.display_name:
            return ws.display_name
    except Exception:
        pass
    return ""


def _esc(s: Any) -> str:
    """HTML-escape a string."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_fact_detail(fact: dict, lineage: list[dict]) -> str:
    """Render detailed view of a single fact with lineage and query log."""
    fact_id = fact.get("id", "")
    content = _esc(fact.get("content", ""))
    scope = _esc(fact.get("scope", ""))
    fact_type = _esc(fact.get("fact_type", ""))
    confidence = fact.get("confidence", 0.0)
    agent_id = _esc(fact.get("agent_id", ""))
    committed_at = fact.get("committed_at", "")[:19]
    provenance = fact.get("provenance")
    lineage_id = fact.get("lineage_id", "")
    query_hits = fact.get("query_hits", 0)
    durability = fact.get("durability", "durable")
    entities = fact.get("entities") or []

    verified = (
        '<span class="badge badge-verified">verified</span>'
        if provenance
        else '<span class="badge badge-unverified">unverified</span>'
    )
    durability_badge = (
        f'<span class="badge badge-low">{durability}</span>' if durability == "ephemeral" else ""
    )

    ticket_refs = []
    if isinstance(entities, str):
        try:
            import json

            entities = json.loads(entities)
        except Exception:
            entities = []
    if isinstance(entities, list):
        ticket_refs = [e for e in entities if isinstance(e, dict) and e.get("type") == "ticket_ref"]

    ticket_html = ""
    if ticket_refs:
        chips = []
        for ticket in ticket_refs:
            ref = _esc(ticket.get("name", ""))
            chips.append(
                f'<span style="display:inline-block;padding:0.25rem 0.6rem;'
                f"background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;"
                f'border-radius:999px;font-size:0.8rem;font-weight:500;">'
                f"{ref}"
                f"</span>"
            )
        ticket_html = f"""
            <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid #e5e7eb;">
                <h4 style="font-size:0.9rem;color:#6b7280;margin-bottom:0.5rem;">Linked Tickets</h4>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                    {"".join(chips)}
                </div>
            </div>
        """

    lineage_html = ""
    if lineage_id:
        lineage_html = f"""
        <div style="margin-top:1rem;">
            <h4 style="font-size:0.9rem;color:#6b7280;margin-bottom:0.5rem;">Version History</h4>
            <div hx-get="/dashboard/facts/{fact_id}/lineage" hx-trigger="load" hx-swap="innerHTML">
                <p style="color:#9ab89a;font-size:0.85rem;">Loading lineage...</p>
            </div>
        </div>
        """

    body = f"""
    <div style="max-width:800px;margin:0 auto;">
        <a href="/dashboard/facts" style="color:#6b7280;text-decoration:none;">&larr; Back to Knowledge Base</a>
        
        <div style="margin-top:1.5rem;padding:1.5rem;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb;">
            <h2 style="font-size:1.25rem;color:#111827;margin-bottom:1rem;">{content}</h2>
            
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1rem;">
                <div><span style="color:#6b7280;font-size:0.85rem;">Scope</span><div>{scope}</div></div>
                <div><span style="color:#6b7280;font-size:0.85rem;">Type</span><div>{fact_type}</div></div>
                <div><span style="color:#6b7280;font-size:0.85rem;">Confidence</span><div>{confidence:.2f}</div></div>
                <div><span style="color:#6b7280;font-size:0.85rem;">Agent</span><div>{agent_id}</div></div>
                <div><span style="color:#6b7280;font-size:0.85rem;">Committed</span><div>{committed_at}</div></div>
                <div><span style="color:#6b7280;font-size:0.85rem;">Status</span><div>{verified} {durability_badge}</div></div>
            </div>

            <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid #e5e7eb;">
                <h4 style="font-size:0.9rem;color:#6b7280;margin-bottom:0.5rem;">Query Log</h4>
                <div style="display:flex;gap:1rem;">
                    <div style="background:#fff;padding:0.5rem 1rem;border-radius:6px;border:1px solid #e5e7eb;">
                        <span style="color:#6b7280;font-size:0.8rem;">Times Queried</span>
                        <div style="font-size:1.5rem;font-weight:600;color:#111827;">{query_hits}</div>
                    </div>
                    <div style="background:#fff;padding:0.5rem 1rem;border-radius:6px;border:1px solid #e5e7eb;">
                        <span style="color:#6b7280;font-size:0.8rem;">Corroborating Agents</span>
                        <div style="font-size:1.5rem;font-weight:600;color:#111827;">{fact.get("corroborating_agents", 0)}</div>
                    </div>
                </div>
            </div>

            {ticket_html}
            
            {lineage_html}
        </div>
    </div>
    """
    return _dash_layout("Fact Detail", body, active="facts")


def _render_lineage_timeline(lineage: list[dict]) -> str:
    """Render lineage version history as a timeline."""
    if not lineage:
        return "<p style='color:#9ab89a;font-size:0.85rem;'>No version history</p>"

    items = []
    for i, f in enumerate(lineage):
        content = _esc(f.get("content", ""))[:100]
        if len(f.get("content", "")) > 100:
            content += "..."
        committed = f.get("committed_at", "")[:19]
        agent = _esc(f.get("agent_id", ""))
        confidence = f.get("confidence", 0.0)
        is_current = f.get("is_current", False)

        marker = (
            '<span class="badge badge-verified">current</span>'
            if is_current
            else f"v{len(lineage) - i}"
        )
        items.append(
            f"""<div style="padding:0.75rem;margin-left:1rem;border-left:2px solid #e5e7eb;{"" if i == len(lineage) - 1 else "border-bottom:1px solid #f3f4f6;"}">
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
                <span style="font-weight:600;color:#374151;">{marker}</span>
                <span style="color:#6b7280;font-size:0.8rem;">{committed}</span>
            </div>
            <div style="color:#111827;font-size:0.9rem;">{content}</div>
            <div style="color:#9ca3af;font-size:0.8rem;">agent: {agent} &middot; conf: {confidence:.2f}</div>
        </div>"""
        )

    return f"<div style='margin-top:0.5rem;'>{''.join(items)}</div>"
