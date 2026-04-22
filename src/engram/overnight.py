"""Overnight deferred thinking processor.

When active scanning hours are exhausted during the day, excess work is queued
as deferred_scans scheduled for midnight. This module processes the queue:
it reads existing facts, explores the codebase, synthesises findings with an
LLM, and commits them back to memory.

Run via: `engram overnight`  (typically from a cron job at 00:00 local time).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# Stable system prompt cached server-side; identical across every deferred scan.
_OVERNIGHT_SYSTEM: list[dict[str, Any]] = [
    {
        "type": "text",
        "text": (
            "You are Engram's overnight synthesis agent. "
            "Your job is to read the team's existing memory and recently changed code, "
            "then produce 3–5 concise, factual insights that would help future agents. "
            "Each insight should be a single sentence, starting with a capital letter. "
            "Focus on non-obvious architectural decisions, patterns, or risks. "
            "Output ONLY a JSON array of strings, e.g.: "
            '["Insight one.", "Insight two."]'
        ),
        "cache_control": {"type": "ephemeral"},
    }
]

# Lazy synchronous client reused across all overnight calls in a single process.
_overnight_client: Any = None


def _get_overnight_client(api_key: str) -> Any:
    global _overnight_client
    if _overnight_client is None:
        import anthropic

        _overnight_client = anthropic.Anthropic(api_key=api_key)
    return _overnight_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _midnight_tonight() -> str:
    """ISO timestamp for midnight (00:00) at the start of tomorrow UTC."""
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if tomorrow <= now:
        from datetime import timedelta

        tomorrow = tomorrow + timedelta(days=1)
    return tomorrow.isoformat()


def build_deferred_scan(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a deferred scan record to enqueue."""
    return {
        "id": str(uuid4()),
        "queued_at": _now_iso(),
        "scheduled_for": _midnight_tonight(),
        "payload": json.dumps(context or {}),
    }


def _read_codebase_snapshot(cwd: str, max_files: int = 12) -> list[dict[str, str]]:
    """Collect recently-changed source files for LLM analysis."""
    files: list[dict[str, str]] = []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~5", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
        paths = [p.strip() for p in r.stdout.splitlines() if p.strip()][:max_files]
    except Exception:
        paths = []

    for rel in paths:
        full = os.path.join(cwd, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, errors="replace") as fh:
                snippet = fh.read(800).strip()
            if snippet:
                files.append({"path": rel, "snippet": snippet})
        except Exception:
            continue
    return files


def _call_llm(
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
) -> str | None:
    """Call Anthropic API synchronously for overnight synthesis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        client = _get_overnight_client(api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return msg.content[0].text if msg.content else None
    except ImportError:
        return None
    except Exception:
        return None


async def run_overnight(storage: Any, cwd: str | None = None) -> int:
    """Process all pending deferred scans.

    Returns the total number of facts committed.
    """
    cwd = cwd or os.getcwd()
    now_iso = _now_iso()

    pending = await storage.get_pending_deferred_scans(before=now_iso)
    if not pending:
        return 0

    total_committed = 0

    # Gather shared context once
    codebase_files = _read_codebase_snapshot(cwd)
    git_log = ""
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-15"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
        git_log = r.stdout.strip()
    except Exception:
        pass

    # Load recent facts from storage to give the LLM context
    recent_facts: list[dict] = []
    try:
        rows = await storage.fts_search("codebase architecture decision", limit=10)
        if rows:
            recent_facts = await storage.get_facts_by_rowids(rows)
    except Exception:
        pass

    facts_summary = "\n".join(
        f"- {f.get('content', '')[:200]}" for f in recent_facts[:8] if f.get("content")
    )

    # Build stable codebase context once — reused (and cached) across all scans in this run.
    file_summaries = "\n\n".join(
        f"### {f['path']}\n```\n{f['snippet']}\n```" for f in codebase_files
    )
    stable_parts: list[str] = []
    if git_log:
        stable_parts.append(f"## Recent git history\n{git_log}")
    if file_summaries:
        stable_parts.append(f"## Recently changed files\n{file_summaries}")
    stable_context = "\n\n".join(stable_parts)

    for scan in pending:
        scan_id = scan["id"]
        await storage.update_deferred_scan_status(scan_id, "running")

        payload: dict[str, Any] = {}
        try:
            raw = scan.get("payload") or "{}"
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

        # Variable per-scan content follows the cached codebase block.
        variable_parts = ["## Existing team memory\n" + (facts_summary or "(none)")]
        if payload.get("context"):
            variable_parts.append(f"## Session context\n{payload['context']}")
        variable_parts.append(
            "\nProduce 3–5 synthesis insights as a JSON array of strings. Be specific, not generic."
        )
        variable_text = "\n\n".join(variable_parts)

        # Two-block user message: stable codebase context cached, per-scan content uncached.
        user_messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": stable_context or "(no codebase context)",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": variable_text},
                ],
            }
        ]

        insights: list[str] = []
        raw_reply = _call_llm(_OVERNIGHT_SYSTEM, user_messages)
        if raw_reply:
            try:
                start = raw_reply.find("[")
                end = raw_reply.rfind("]") + 1
                if start != -1 and end > start:
                    insights = json.loads(raw_reply[start:end])
            except Exception:
                pass

        committed = 0
        for insight in insights[:5]:
            if not isinstance(insight, str) or not insight.strip():
                continue
            fact: dict[str, Any] = {
                "id": str(uuid4()),
                "lineage_id": str(uuid4()),
                "content": insight.strip(),
                "content_hash": "",
                "scope": "overnight-synthesis",
                "confidence": 0.75,
                "fact_type": "synthesis",
                "agent_id": "overnight-processor",
                "engineer": "system",
                "provenance": f"deferred_scan:{scan_id}",
                "keywords": "synthesis overnight codebase",
                "entities": "[]",
                "artifact_hash": None,
                "embedding": None,
                "embedding_model": "none",
                "embedding_ver": "0",
                "committed_at": _now_iso(),
                "valid_from": _now_iso(),
                "valid_until": None,
                "ttl_days": None,
                "memory_op": "add",
                "supersedes_fact_id": None,
                "workspace_id": storage.workspace_id,
                "corroborating_agents": 0,
                "durability": "durable",
                "query_hits": 0,
            }
            # Compute content hash
            import hashlib

            fact["content_hash"] = hashlib.sha256(
                f"{fact['content']}:{fact['scope']}".encode()
            ).hexdigest()
            # Skip if duplicate
            dup = await storage.find_duplicate(fact["content_hash"], fact["scope"])
            if dup:
                continue
            try:
                await storage.insert_fact(fact)
                committed += 1
            except Exception:
                pass

        total_committed += committed
        await storage.update_deferred_scan_status(
            scan_id, "done", fact_count=committed, completed_at=_now_iso()
        )

    return total_committed
