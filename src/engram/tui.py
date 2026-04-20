"""Claude Code-style full-screen interactive TUI for Engram."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import urllib.parse
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.styles import Style

_VERSION = "0.1.1"

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_CATEGORIES = ["About you", "About the codebase", "Goals"]

_STYLE = Style.from_dict(
    {
        "header.title": "bold noinherit #ffffff",
        "header.version": "noinherit #555555",
        "header.mode": "bold noinherit #00dd55",
        "header.id": "noinherit #555555",
        "header.cwd": "noinherit #555555",
        "header.tagline": "noinherit #ff8800",
        "header.logo": "bold noinherit #00dd55",
        "separator": "noinherit #333333",
        "prompt": "bold noinherit #00dd55",
        "output": "noinherit #cccccc",
        "output.cmd": "bold noinherit #00dd55",
        "output.error": "noinherit #ff5555",
        "output.dim": "noinherit #555555",
        "output.warn": "noinherit #ffaa00",
        "output.label": "bold noinherit #00dd55",
        "output.ai": "noinherit #88ddff",
        "toolbar": "noinherit bg:#111111 #444444",
        "toolbar.key": "noinherit bg:#111111 #00dd55",
        "toolbar.sep": "noinherit bg:#111111 #333333",
    }
)

_VALID_COMMANDS = {
    "conflicts",
    "resolve",
    "search",
    "status",
    "whoami",
    "export",
    "info",
    "stats",
    "verify",
    "doctor",
    "merge",
}

_HELP_LINES: list[tuple[str, str]] = [
    ("class:output.dim", "\n"),
    ("class:output", "  Commands:\n"),
    ("class:output", "    conflicts                           — refresh conflict list\n"),
    (
        "class:output",
        "    merge                               — merge with another person's memory\n",
    ),
    ("class:output", "    clear                               — clear output  (Ctrl+L)\n"),
    ("class:output", "    quit / q                            — exit          (Ctrl+C)\n"),
    ("class:output.dim", "\n"),
    (
        "class:output.dim",
        "  Any other text is sent to the AI with your full fact corpus as context.\n",
    ),
    ("class:output.dim", "  Every message you send is also saved as an Engram memory.\n"),
    ("class:output.dim", "\n"),
]

# Default local server address — matches `engram serve --http`
_LOCAL_SERVER = "http://localhost:7474"


# ── server API helpers ────────────────────────────────────────────────


def _http_get(url: str, timeout: int = 5, headers: dict[str, str] | None = None) -> Any | None:
    """GET url, return parsed JSON or None on any error."""
    try:
        parsed = urllib.parse.urlparse(url)
        use_https = parsed.scheme == "https"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if use_https else 80)
        conn: http.client.HTTPConnection
        if use_https:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request(
            "GET",
            parsed.path + (f"?{parsed.query}" if parsed.query else ""),
            headers=headers or {},
        )
        resp = conn.getresponse()
        if resp.status == 200:
            return json.loads(resp.read())
    except Exception:
        pass
    return None


def _http_post(
    url: str,
    body: dict[str, Any],
    timeout: int = 5,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """POST JSON body to url, return (status_code, parsed_json)."""
    try:
        parsed = urllib.parse.urlparse(url)
        raw = json.dumps(body).encode()
        use_https = parsed.scheme == "https"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if use_https else 80)
        conn: http.client.HTTPConnection
        if use_https:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        req_headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        if headers:
            req_headers.update(headers)
        conn.request("POST", parsed.path, raw, req_headers)
        resp = conn.getresponse()
        raw_body = resp.read()
        try:
            data = json.loads(raw_body) if raw_body.strip() else {}
        except Exception:
            data = {"error": raw_body.decode(errors="replace")[:200]}
        return resp.status, data
    except Exception as exc:
        return 0, {"error": str(exc)}


def _server_url(ws: Any) -> str:
    """Return the server base URL to use for API calls."""
    if ws and ws.server_url:
        return ws.server_url.rstrip("/")
    return _LOCAL_SERVER


def _is_hosted(ws: Any) -> bool:
    """Return True when connected to a remote hosted server (not localhost)."""
    base = _server_url(ws)
    return not base.startswith("http://localhost") and not base.startswith("http://127.")


def _parse_mcp_response(data: Any) -> Any | None:
    """Extract the tool result from a parsed MCP JSON-RPC response dict."""
    try:
        content = (data.get("result") or {}).get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except Exception:
                return {"reply": text} if text else None
    except Exception:
        pass
    return data.get("result")


def _mcp_call(ws: Any, tool: str, arguments: dict[str, Any]) -> Any | None:
    """Call an MCP tool via JSON-RPC POST to <server>/mcp.  Returns the result or None."""
    base = _server_url(ws)
    auth: dict[str, str] = {}
    if getattr(ws, "invite_key", ""):
        auth["Authorization"] = f"Bearer {ws.invite_key}"
    auth["Accept"] = "application/json, text/event-stream"
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    status, data = _http_post(f"{base}/mcp", body, timeout=15, headers=auth)
    if status != 200:
        return None

    # When the server returns text/event-stream (SSE), _http_post can't JSON-parse
    # the raw body and stashes it in {"error": "<raw text>"}. Extract data: lines.
    if isinstance(data, dict) and "error" in data and "result" not in data:
        raw_text = data["error"]
        if not isinstance(raw_text, str):
            return None
        for line in raw_text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                    break
                except Exception:
                    continue

    return _parse_mcp_response(data)


# ── OpenAI chat proxied through Engram server ─────────────────────────


def _commit_user_message(ws: Any, message: str) -> None:
    """Commit the user's typed message as an Engram fact."""
    args = {
        "content": message,
        "agent_id": "tui-user",
        "scope": "global",
        "confidence": 0.9,
        "fact_type": "observation",
    }
    if _is_hosted(ws):
        _mcp_call(ws, "engram_commit", args)
        return
    base = _server_url(ws)
    auth: dict[str, str] = {}
    if getattr(ws, "invite_key", ""):
        auth["Authorization"] = f"Bearer {ws.invite_key}"
    _http_post(f"{base}/api/commit", args, timeout=8, headers=auth)


def _openai_chat(
    ws: Any,
    message: str,
    output_lines: list[tuple[str, str]],
    history: list[dict[str, str]] | None = None,
) -> str | None:
    """Send message to the server chat endpoint. Returns assistant reply or None."""
    if _is_hosted(ws):
        result = _mcp_call(
            ws,
            "engram_chat",
            {"message": message, "history": history or []},
        )
        if isinstance(result, dict) and result.get("error"):
            output_lines.append(("class:output.dim", "\n"))
            output_lines.append(("class:output.warn", f"  ⚠ {result['error']}\n"))
            output_lines.append(("class:output.dim", "\n"))
            return None

        reply = (result or {}).get("reply") if isinstance(result, dict) else None

        if reply:
            output_lines.append(("class:output.dim", "\n"))
            for line in reply.splitlines():
                output_lines.append(("class:output.ai", f"  {line}\n"))
            output_lines.append(("class:output.dim", "\n"))
            return reply

        # engram_chat not yet deployed — query memory for context then respond locally
        qresult = _mcp_call(ws, "engram_query", {"topic": message, "limit": 6})
        facts = (qresult or {}).get("facts", []) if isinstance(qresult, dict) else []

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            try:
                import anthropic

                memory_ctx = "\n".join(
                    f"- {(f.get('content') or '').strip()[:200]}" for f in facts if f.get("content")
                )
                sys_prompt = (
                    "You are Engram, a shared team memory assistant. "
                    "Respond conversationally and concisely. "
                    "Use the memory context below if relevant, but don't just recite it — "
                    "synthesise and respond naturally to the user's message. "
                    "If the user's input is ambiguous (e.g. a single letter), "
                    "ask a clarifying question.\n\n"
                    f"Memory context:\n{memory_ctx or '(empty)'}"
                )
                msgs: list[dict[str, str]] = list(history or [])
                msgs.append({"role": "user", "content": message})
                client = anthropic.Anthropic(api_key=api_key)
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    system=sys_prompt,
                    messages=msgs,
                )
                reply = resp.content[0].text if resp.content else None
                if reply:
                    output_lines.append(("class:output.dim", "\n"))
                    for line in reply.splitlines():
                        output_lines.append(("class:output.ai", f"  {line}\n"))
                    output_lines.append(("class:output.dim", "\n"))
                    return reply
            except Exception:
                pass

        # No API key — show a brief memory summary instead of raw facts
        output_lines.append(("class:output.dim", "\n"))
        if facts:
            output_lines.append(("class:output.dim", "  Relevant memory:\n"))
            for f in facts[:3]:
                content = (f.get("content") or "").strip()[:120]
                output_lines.append(("class:output.dim", f"  · {content}\n"))
        else:
            output_lines.append(("class:output.dim", "  Nothing in memory on that topic yet.\n"))
        output_lines.append(("class:output.dim", "\n"))
        return None

    base = _server_url(ws)
    output_lines.append(("class:output.dim", "  Thinking...\n"))

    status, data = _http_post(
        f"{base}/api/chat",
        {"message": message},
        timeout=35,
    )

    if status == 0:
        output_lines.append(("class:output.error", f"  Server unreachable: {data.get('error')}\n"))
        return

    if status == 503:
        output_lines.append(("class:output.error", "  AI chat is not configured on this server.\n"))
        return

    if status != 200:
        err = data.get("error", f"HTTP {status}")
        output_lines.append(("class:output.error", f"  Error: {err}\n"))
        return

    reply = data.get("reply", "")
    output_lines.append(("class:output.dim", "\n"))
    for line in reply.splitlines():
        output_lines.append(("class:output.ai", f"  {line}\n"))
    output_lines.append(("class:output.dim", "\n"))


# ── conflict display helpers ──────────────────────────────────────────

_SEV_COLOURS = {"high": "class:output.error", "medium": "class:output.warn", "low": "class:output"}


def _format_conflicts(conflicts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Render a numbered conflict list for the TUI output area."""
    lines: list[tuple[str, str]] = []
    if not conflicts:
        lines.append(("class:output.dim", "  ✓ No conflicts found.\n"))
        return lines

    lines.append(
        ("class:output", f"  {len(conflicts)} open conflict(s) — shared with dashboard:\n\n")
    )
    for i, c in enumerate(conflicts, 1):
        cid = (c.get("conflict_id") or c.get("id") or "")[:16]
        short = cid[:8]
        explanation = c.get("explanation") or "Conflicting information detected"
        severity = c.get("severity", "medium")
        sev_style = _SEV_COLOURS.get(severity, "class:output")

        fa = c.get("fact_a") or {}
        fb = c.get("fact_b") or {}
        fa_content = (fa.get("content") or c.get("fact_a_content") or "")[:90]
        fb_content = (fb.get("content") or c.get("fact_b_content") or "")[:90]
        fa_scope = fa.get("scope") or c.get("fact_a_scope") or ""
        fb_scope = fb.get("scope") or c.get("fact_b_scope") or ""

        lines.append(("class:output.label", f"  [{i}] "))
        lines.append((sev_style, f"[{severity}] "))
        lines.append(("class:output.dim", f"id:{short}\n"))
        lines.append(("class:output", f"      {explanation}\n"))
        if fa_content:
            scope_tag = f" ({fa_scope})" if fa_scope else ""
            lines.append(("class:output.dim", f"      A{scope_tag}: {fa_content}\n"))
        if fb_content:
            scope_tag = f" ({fb_scope})" if fb_scope else ""
            lines.append(("class:output.dim", f"      B{scope_tag}: {fb_content}\n"))
        lines.append(("class:output.dim", "\n"))

    return lines


# ── conflict fetch / resolve via server ───────────────────────────────


def _load_conflicts(ws: Any, output_lines: list[tuple[str, str]]) -> None:
    """Fetch open conflicts from the server and append formatted output."""
    base = _server_url(ws)

    if _is_hosted(ws):
        result = _mcp_call(ws, "engram_conflicts", {"status": "open"})
        if result is None:
            output_lines.append(("class:output.error", f"  Could not reach server at {base}\n"))
            output_lines.append(
                ("class:output.dim", "  Check your invite key or internet connection.\n")
            )
            return
        conflicts = result.get("conflicts", result) if isinstance(result, dict) else result
        output_lines.extend(_format_conflicts(conflicts if isinstance(conflicts, list) else []))
        return

    auth_headers: dict[str, str] = {}
    if ws and getattr(ws, "invite_key", ""):
        auth_headers["Authorization"] = f"Bearer {ws.invite_key}"
    data = _http_get(f"{base}/api/conflicts?status=open", timeout=8, headers=auth_headers)

    if data is None:
        output_lines.append(("class:output.error", f"  Could not reach server at {base}\n"))
        output_lines.append(
            ("class:output.dim", "  Run `engram serve --http` locally or check your connection.\n")
        )
        return

    output_lines.extend(_format_conflicts(data if isinstance(data, list) else []))


def _resolve_conflict(
    ws: Any,
    conflict_id: str,
    resolution_type: str,
    output_lines: list[tuple[str, str]],
) -> None:
    """Resolve a conflict via the server API and report the result."""
    base = _server_url(ws)

    _aliases = {
        "keep_a": "winner",
        "keep_b": "winner",
        "dismiss": "dismissed",
        "dismissed": "dismissed",
        "winner": "winner",
        "merge": "merge",
    }
    resolution_type_norm = _aliases.get(resolution_type.lower(), resolution_type.lower())
    if resolution_type_norm not in ("winner", "merge", "dismissed"):
        output_lines.append(
            (
                "class:output.error",
                f"  Unknown resolution '{resolution_type}'. Use keep_a, keep_b, or dismiss.\n",
            )
        )
        return

    winning_claim_id: str | None = None
    if resolution_type.lower() in ("keep_a", "keep_b"):
        data = _http_get(f"{base}/api/conflicts?status=open")
        if isinstance(data, list):
            for c in data:
                cid = c.get("conflict_id") or c.get("id") or ""
                if cid.startswith(conflict_id):
                    if resolution_type.lower() == "keep_a":
                        fa = c.get("fact_a") or {}
                        winning_claim_id = fa.get("fact_id") or fa.get("id") or c.get("fact_a_id")
                    else:
                        fb = c.get("fact_b") or {}
                        winning_claim_id = fb.get("fact_id") or fb.get("id") or c.get("fact_b_id")
                    conflict_id = cid
                    break

    note = f"Resolved via TUI ({resolution_type})"
    payload: dict[str, Any] = {
        "conflict_id": conflict_id,
        "resolution_type": resolution_type_norm,
        "resolution": note,
    }
    if winning_claim_id:
        payload["winning_claim_id"] = winning_claim_id

    status, result = _http_post(f"{base}/api/resolve", payload)

    if status == 0:
        output_lines.append(("class:output.dim", "  (server offline — using local engine)\n"))
        _run_engram_command("resolve", f"{conflict_id} {resolution_type_norm} {note}", output_lines)
        return

    if status != 200:
        err = result.get("error") or result.get("detail") or f"HTTP {status}"
        output_lines.append(("class:output.error", f"  Resolve failed: {err}\n"))
        return

    output_lines.append(
        ("class:output.label", f"  ✓ Conflict {conflict_id[:8]} resolved ({resolution_type}).\n")
    )
    output_lines.append(("class:output.dim", "  Dashboard will reflect this immediately.\n"))


# ── merge (join another workspace) ────────────────────────────────────


def _handle_merge_invite_key(invite_key: str, output_lines: list[tuple[str, str]]) -> None:
    """Run `engram join <invite_key>` to merge with another person's memory space."""
    if not invite_key.strip():
        output_lines.append(("class:output.error", "  No invite key provided. Merge cancelled.\n"))
        return

    output_lines.append(("class:output.dim", "  Joining workspace...\n"))
    _run_engram_command("join", invite_key.strip(), output_lines)


def run_tui(ws: Any, ctx: Any) -> None:
    """Launch the Claude Code-style interactive shell."""
    if ws.server_url and not ws.db_url:
        mode_label = "hosted"
    elif ws.db_url:
        mode_label = "team · PostgreSQL"
    else:
        mode_label = "local · SQLite"

    workspace_id = ws.engram_id or "-"
    try:
        rel = os.path.relpath(os.getcwd(), os.path.expanduser("~"))
        cwd = "~/" + rel if not rel.startswith("..") else os.getcwd()
    except ValueError:
        cwd = os.getcwd()

    # Mutable state
    state: dict[str, Any] = {
        "selected_category": 0,
        "scanning": False,
        "scan_paused": False,
        "scan_frame": 0,
    }
    output_lines: list[tuple[str, str]] = []
    conversation_history: list[dict[str, str]] = []

    # ── formatted text producers ──────────────────────────────────────────

    _LOGO_OPEN = [
        "  ▄████▄  ",
        " ██▄██▄██ ",
        " ███▀▀███ ",
        " ▀ ▀  ▀ ▀ ",
    ]
    _LOGO_CLOSED = [
        "  ▄████▄  ",
        " ████████ ",
        " ███▀▀███ ",
        " ▀ ▀  ▀ ▀ ",
    ]

    def header_text() -> AnyFormattedText:
        logo = _LOGO_OPEN if state.get("eyes", "open") == "open" else _LOGO_CLOSED
        lines = [
            [
                ("class:header.logo", logo[0]),
                ("class:header.title", "   Engram "),
                ("class:header.version", f"v{_VERSION}"),
            ],
            [
                ("class:header.logo", logo[1]),
                ("class:header.mode", f"   {mode_label} "),
                ("class:header.id", f"· {workspace_id}"),
            ],
            [("class:header.logo", logo[2]), ("class:header.cwd", f"   {cwd}")],
            [
                ("class:header.logo", logo[3]),
                ("class:header.tagline", "   Active memory that never sleeps"),
            ],
        ]

        result: list[tuple[str, str]] = []
        for line in lines:
            result.extend(line)
            result.append(("", "\n"))
        return result

    def separator_text() -> AnyFormattedText:
        return [("class:separator", "─" * 200)]

    def output_text() -> AnyFormattedText:
        result = list(output_lines)
        if state["scanning"]:
            frame = _SPINNER[state["scan_frame"] % len(_SPINNER)]
            result.append(("class:output.dim", f"\n  {frame} Scanning codebase...\n"))
        return result

    def output_cursor_pos() -> Point:
        total = sum(t.count("\n") for _, t in output_lines)
        return Point(x=0, y=max(0, total - 1))

    def question_text() -> AnyFormattedText:
        return [("class:prompt", "  Tell me something your agents should always remember")]

    def tabs_text() -> AnyFormattedText:
        return [
            (
                "class:output.dim",
                "  Resolve conflicts, or tell me something your agents should always remember",
            ),
        ]

    def toolbar_text() -> AnyFormattedText:
        if state.get("waiting_for_invite_key"):
            return [
                ("class:toolbar", "  "),
                ("class:toolbar.key", "Paste invite key and press Enter"),
                ("class:toolbar.sep", "   ·   "),
                ("class:toolbar.key", "Ctrl+C"),
                ("class:toolbar", " cancel"),
                ("class:toolbar", "  "),
            ]
        return [
            ("class:toolbar", "  "),
            ("class:toolbar.key", "conflicts"),
            ("class:toolbar", " refresh"),
            ("class:toolbar.sep", "   ·   "),
            ("class:toolbar.key", "merge"),
            ("class:toolbar", " join another memory space"),
            ("class:toolbar.sep", "   ·   "),
            ("class:toolbar.key", "?"),
            ("class:toolbar", " help"),
            ("class:toolbar.sep", "   ·   "),
            ("class:toolbar.key", "Ctrl+C"),
            ("class:toolbar", " quit"),
            ("class:toolbar", "  "),
        ]

    # ── input & key handling ──────────────────────────────────────────────

    input_buf = Buffer(name="main_input", multiline=False)

    def run_cmd(cmd: str, arg: str, app: Application) -> None:
        output_lines.append(("class:output.cmd", f"\n  > {cmd}{' ' + arg if arg else ''}\n"))
        _run_engram_command(cmd, arg, output_lines)
        app.invalidate()

    def handle_command(text: str, app: Application) -> None:
        text = text.strip()
        if not text:
            return

        # Handle invite key input for merge flow
        if state.get("waiting_for_invite_key"):
            state.pop("waiting_for_invite_key")
            output_lines.append(("class:output.cmd", "\n  > [invite key entered]\n"))
            _handle_merge_invite_key(text, output_lines)
            app.invalidate()
            return

        output_lines.append(("class:output.cmd", f"\n  > {text}\n"))
        parts = text.split(None, 2)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        extra = parts[2] if len(parts) > 2 else ""

        if cmd in ("quit", "exit", "q"):
            app.exit()
            return
        if cmd in ("?", "help"):
            output_lines.extend(_HELP_LINES)
            return
        if cmd == "clear":
            output_lines.clear()
            return

        import threading
        import time

        # For local mode, commit in background via REST API
        if not _is_hosted(ws):
            threading.Thread(target=_commit_user_message, args=(ws, text), daemon=True).start()

        def _trigger_scan(a: Application) -> None:
            if state["scanning"] or state["scan_paused"]:
                return
            base = _server_url(ws)
            billing = _http_get(f"{base}/billing/status?engram_id={ws.engram_id or ''}", timeout=3)
            if billing and billing.get("paused"):
                state["scan_paused"] = True
                # Queue deferred scan so work runs at midnight instead of being dropped
                try:
                    from engram.overnight import build_deferred_scan
                    from engram.storage import SQLiteStorage

                    _scan_record = build_deferred_scan({"context": text[:500]})

                    async def _enqueue() -> None:
                        _st = SQLiteStorage(workspace_id=getattr(ws, "engram_id", None) or "local")
                        await _st.connect()
                        try:
                            await _st.enqueue_deferred_scan(_scan_record)
                        finally:
                            await _st.close()

                    import asyncio as _asyncio

                    try:
                        _asyncio.get_event_loop().run_until_complete(_enqueue())
                        output_lines.append(
                            (
                                "class:output.dim",
                                "  ↷ Queued for tonight's analysis (runs at midnight).\n",
                            )
                        )
                    except RuntimeError:
                        pass
                except Exception:
                    pass

                output_lines.append(
                    (
                        "class:output.warn",
                        "  ⏸ Active scanning paused — upgrade for more active hours.\n",
                    )
                )
                a.invalidate()
                return

            state["scanning"] = True
            facts_committed = 0
            scan_auth: dict[str, str] = {}
            if getattr(ws, "invite_key", ""):
                scan_auth["Authorization"] = f"Bearer {ws.invite_key}"

            def _spin(n: int) -> None:
                for _ in range(n):
                    time.sleep(0.08)
                    state["scan_frame"] += 1
                    a.invalidate()

            def _commit_fact(content: str) -> bool:
                nonlocal facts_committed
                s, _ = _http_post(
                    f"{base}/api/commit",
                    {
                        "content": content,
                        "agent_id": "tui-scanner",
                        "scope": "codebase",
                        "confidence": 0.8,
                        "fact_type": "observation",
                    },
                    headers=scan_auth,
                    timeout=5,
                )
                if s == 200:
                    facts_committed += 1
                    return True
                return False

            # Commit recent git activity
            _spin(5)
            try:
                r = subprocess.run(
                    ["git", "log", "--oneline", "-8"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if r.stdout.strip():
                    _commit_fact(f"Recent git commits:\n{r.stdout.strip()}")
            except Exception:
                pass

            # Scan recently modified files
            _spin(4)
            changed: list[str] = []
            try:
                r = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                changed = [f.strip() for f in r.stdout.splitlines() if f.strip()][:6]
            except Exception:
                pass

            for filepath in changed:
                _spin(4)
                full_path = os.path.join(os.getcwd(), filepath)
                if not os.path.isfile(full_path):
                    continue
                try:
                    with open(full_path, errors="replace") as fh:
                        preview = fh.read(400).strip()
                    first_lines = " · ".join(
                        ln.strip() for ln in preview.splitlines()[:4] if ln.strip()
                    )[:200]
                    if _commit_fact(f"{filepath}: {first_lines}"):
                        output_lines.append(("class:output.dim", f"  ↳ {filepath}\n"))
                        a.invalidate()
                except Exception:
                    pass

            _spin(5)
            state["scanning"] = False
            if facts_committed > 0:
                noun = "fact" if facts_committed == 1 else "facts"
                output_lines.append(
                    ("class:output.dim", f"  ✓ {facts_committed} {noun} saved to memory.\n")
                )
                a.invalidate()

        threading.Thread(target=_trigger_scan, args=(app,), daemon=True).start()

        if cmd == "merge":
            output_lines.append(
                ("class:output.label", "  engram merge — join another memory space\n\n")
            )
            output_lines.append(
                ("class:output", "  Enter the invite key from the other workspace:\n")
            )
            state["waiting_for_invite_key"] = True
            app.invalidate()
            return

        if cmd == "conflicts":
            _load_conflicts(ws, output_lines)
        elif cmd == "resolve":
            if not arg:
                output_lines.append(
                    ("class:output.error", "  Usage: resolve <id> keep_a|keep_b|dismiss\n")
                )
            else:
                resolution = extra or "dismissed"
                _resolve_conflict(ws, arg, resolution, output_lines)
                output_lines.append(("class:output.dim", "\n"))
                _load_conflicts(ws, output_lines)
        elif cmd == "search" and not arg:
            output_lines.append(("class:output.error", "  Usage: search <query>\n"))
        elif cmd in _VALID_COMMANDS:
            _run_engram_command(cmd, arg + (" " + extra if extra else ""), output_lines)
        else:
            # Unknown command → conversational chat with memory context
            reply = _openai_chat(ws, text, output_lines, history=conversation_history)
            if reply is not None:
                conversation_history.append({"role": "user", "content": text})
                conversation_history.append({"role": "assistant", "content": reply})
                # Keep history bounded to last 10 turns
                if len(conversation_history) > 20:
                    del conversation_history[:2]

        app.invalidate()

    kb = KeyBindings()

    @kb.add("enter")
    def _enter(event: Any) -> None:
        text = input_buf.text
        input_buf.reset()
        handle_command(text, event.app)

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event: Any) -> None:
        if state.get("waiting_for_invite_key"):
            state.pop("waiting_for_invite_key")
            output_lines.append(("class:output.dim", "  Merge cancelled.\n"))
            event.app.invalidate()
        else:
            event.app.exit()

    @kb.add("c-l")
    def _clear(event: Any) -> None:
        output_lines.clear()
        event.app.invalidate()

    @kb.add("tab")
    def _next_cat(event: Any) -> None:
        state["selected_category"] = (state["selected_category"] + 1) % len(_CATEGORIES)
        event.app.invalidate()

    @kb.add("s-tab")
    def _prev_cat(event: Any) -> None:
        state["selected_category"] = (state["selected_category"] - 1) % len(_CATEGORIES)
        event.app.invalidate()

    @kb.add("c-r")
    def _refresh(event: Any) -> None:
        output_lines.append(("class:output.cmd", "\n  > conflicts\n"))
        _load_conflicts(ws, output_lines)
        event.app.invalidate()

    # ── layout ────────────────────────────────────────────────────────────

    layout = Layout(
        HSplit(
            [
                Window(
                    FormattedTextControl(header_text, focusable=False),
                    height=D.exact(4),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(separator_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(
                        output_text,
                        get_cursor_position=output_cursor_pos,
                        focusable=False,
                    ),
                    wrap_lines=True,
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(separator_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    BufferControl(
                        buffer=input_buf,
                        input_processors=[BeforeInput("> ", style="class:prompt")],
                    ),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(separator_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(tabs_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(),  # pushes output and input to top, toolbar to bottom
                Window(
                    FormattedTextControl(toolbar_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                    style="class:toolbar",
                ),
            ]
        ),
        focused_element=input_buf,
    )

    app = Application(
        layout=layout,
        style=_STYLE,
        key_bindings=kb,
        full_screen=True,
        cursor=CursorShape.BLINKING_BLOCK,
        mouse_support=False,
    )

    import threading
    import time

    def _blink() -> None:
        while True:
            time.sleep(3)
            state["eyes"] = "closed"
            app.invalidate()
            time.sleep(0.15)
            state["eyes"] = "open"
            app.invalidate()

    threading.Thread(target=_blink, daemon=True).start()

    # Load conflicts immediately on startup
    _load_conflicts(ws, output_lines)

    app.run()


# ── command runner ─────────────────────────────────────────────────────


def _run_engram_command(cmd: str, arg: str, output_lines: list[tuple[str, str]]) -> None:
    engram_bin = _find_engram_bin()
    cli_args = [engram_bin, cmd]
    if arg:
        cli_args.extend(arg.split())

    try:
        result = subprocess.run(cli_args, capture_output=True, text=True, timeout=30)
        combined = (result.stdout + result.stderr).strip()
        if combined in ("[]", "{}", ""):
            output_lines.append(("class:output.dim", f"  No {cmd} found.\n"))
        elif combined:
            err = result.returncode != 0
            for line in combined.splitlines():
                style = "class:output.error" if err else "class:output"
                output_lines.append((style, f"  {line}\n"))
        else:
            output_lines.append(("class:output.dim", f"  No output from {cmd}.\n"))
    except subprocess.TimeoutExpired:
        output_lines.append(("class:output.error", "  Command timed out after 30s\n"))
    except FileNotFoundError:
        output_lines.append(("class:output.error", f"  Could not find: {engram_bin}\n"))
    except Exception as e:
        output_lines.append(("class:output.error", f"  Error: {e}\n"))


def _find_engram_bin() -> str:
    argv0 = sys.argv[0]
    if os.path.isfile(argv0) and os.access(argv0, os.X_OK):
        return argv0
    return "engram"
