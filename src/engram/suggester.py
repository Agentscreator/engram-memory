"""LLM-powered conflict resolution grounded in codebase and TKG evidence.

Requires ANTHROPIC_API_KEY. Gracefully no-ops if the `anthropic` package is
not installed or no key is configured — the heuristic resolver handles it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("engram")

# Lazy client reused across all suggestion calls in a single process.
_suggester_client: Any = None


def _get_suggester_client(api_key: str) -> Any:
    global _suggester_client
    if _suggester_client is None:
        import anthropic

        _suggester_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _suggester_client


_SYSTEM_TEXT = """\
You are Engram's conflict resolver for a multi-agent engineering team.
Two AI agents have committed facts that contradict each other.
Resolve the conflict using ALL evidence provided — codebase ground truth
and the temporal knowledge graph (TKG) belief history carry the most weight.

Priority order for evidence:
1. CODEBASE GROUND TRUTH — what config files, env vars, and dependency manifests
   actually say. This is the authoritative source. If one fact matches the code
   and the other doesn't, the matching fact wins unconditionally.
2. TKG BELIEF HISTORY — how beliefs about the disputed entity evolved over time.
   A reversal pattern (A→B→A) or a clear drift toward one value indicates which
   belief is more current. Use this to understand context and trajectory.
3. FACT METADATA — confidence score, provenance, commit time, and agent identity.
   Higher confidence and verified provenance favor a fact when codebase and TKG
   evidence is absent or inconclusive.

Respond with JSON only — no prose, no markdown fences:
{
  "resolution_type": "winner" | "merge" | "dismissed",
  "winning_fact_id": "<id of the winning fact, or null if merge or dismissed>",
  "suggested_resolution": "<1-2 sentence human-readable summary of the resolution>",
  "reasoning": "<cite the specific evidence — codebase value, TKG trajectory, or metadata — that drove this decision>"
}

Resolution type guidelines:
- "winner": One fact is correct. MUST be used when codebase ground truth
  confirms one side, or when TKG shows a clear settled trajectory.
- "merge": Both facts are true in different contexts (e.g. different environments,
  different time periods). Use sparingly — only when evidence shows both are valid.
- "dismissed": The conflict is a false positive — the facts describe different
  things entirely (different scopes, units, or system components).
- Never invent facts or values not present in the input.\
"""

# Cached system prompt — stable across all conflict resolution calls.
_SYSTEM: list[dict[str, Any]] = [
    {"type": "text", "text": _SYSTEM_TEXT, "cache_control": {"type": "ephemeral"}}
]


async def generate_suggestion(
    fact_a: dict[str, Any],
    fact_b: dict[str, Any],
    conflict: dict[str, Any],
    codebase_context: list[dict[str, str]] | None = None,
    tkg_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Ask Claude to resolve a conflict using codebase and TKG evidence.

    Returns a dict with keys:
      suggested_resolution, suggested_resolution_type,
      suggested_winning_fact_id, suggestion_reasoning, suggestion_generated_at

    Returns None if no API key is set or the `anthropic` package is missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        client = _get_suggester_client(api_key)
    except ImportError:
        logger.debug("anthropic package not installed — skipping LLM suggestions")
        return None

    prompt = _build_prompt(fact_a, fact_b, conflict, codebase_context, tkg_context)

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if the model adds them despite instructions
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        resolution_type = data.get("resolution_type", "winner")
        winning_fact_id = data.get("winning_fact_id")

        # Validate winning_fact_id is one of the two known fact IDs
        if resolution_type == "winner":
            if winning_fact_id not in (fact_a["id"], fact_b["id"]):
                winning_fact_id = (
                    fact_a["id"]
                    if (fact_a.get("confidence") or 0) >= (fact_b.get("confidence") or 0)
                    else fact_b["id"]
                )

        return {
            "suggested_resolution": data.get("suggested_resolution", ""),
            "suggested_resolution_type": resolution_type,
            "suggested_winning_fact_id": winning_fact_id,
            "suggestion_reasoning": data.get("reasoning", ""),
            "suggestion_generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        logger.exception("LLM suggestion failed for conflict %s", conflict.get("id", "unknown"))
        return None


def _build_prompt(
    fact_a: dict[str, Any],
    fact_b: dict[str, Any],
    conflict: dict[str, Any],
    codebase_context: list[dict[str, str]] | None,
    tkg_context: list[dict[str, Any]] | None,
) -> str:
    sections: list[str] = []

    # ── Conflict metadata ──────────────────────────────────────────────
    tier = conflict.get("detection_tier", "unknown")
    tier_label = _tier_label(tier)
    sections.append(
        f"CONFLICT DETECTED\n"
        f"  method:      {tier_label}\n"
        f"  severity:    {conflict.get('severity', 'unknown')}\n"
        f"  explanation: {conflict.get('explanation', 'none')}"
    )

    # ── Facts ──────────────────────────────────────────────────────────
    sections.append(f"FACT A:\n{_fact_lines(fact_a)}")
    sections.append(f"FACT B:\n{_fact_lines(fact_b)}")

    # ── Codebase ground truth ──────────────────────────────────────────
    if codebase_context:
        lines = ["CODEBASE GROUND TRUTH (authoritative — what the code actually says):"]
        for entry in codebase_context:
            entity = entry["entity"]
            code_val = entry["code_value"]
            source = entry["source"]
            # Annotate which fact (if any) matches the code value
            content_a = (fact_a.get("content") or "").lower()
            content_b = (fact_b.get("content") or "").lower()
            match_a = str(code_val).lower() in content_a
            match_b = str(code_val).lower() in content_b
            annotation = ""
            if match_a and not match_b:
                annotation = " → Fact A matches code, Fact B contradicts it"
            elif match_b and not match_a:
                annotation = " → Fact B matches code, Fact A contradicts it"
            elif match_a and match_b:
                annotation = " → Both facts consistent with code"
            lines.append(f"  {entity} = {code_val}  (source: {source}){annotation}")
        sections.append("\n".join(lines))

    # ── TKG belief history ─────────────────────────────────────────────
    if tkg_context:
        lines = ["TKG BELIEF HISTORY (how beliefs about these entities evolved):"]
        for entry in tkg_context:
            entity = entry["entity"]
            timeline = entry["timeline"]
            lines.append(f"  Entity: {entity}")
            for edge in timeline[-6:]:  # last 6 entries to keep it concise
                status = "active" if edge.get("is_active") else "expired"
                lines.append(
                    f"    {edge.get('created_at', '')[:19]}  "
                    f"agent={edge.get('agent_id', '?')}  "
                    f"{edge.get('source', '?')} {edge.get('relation', '?')} "
                    f"{edge.get('target', '?')}  [{status}]"
                )
        sections.append("\n".join(lines))

    sections.append("Resolve this conflict. Cite the specific evidence that drives your decision.")
    return "\n\n".join(sections)


def _fact_lines(f: dict[str, Any]) -> str:
    lines = [
        f"  id:         {f['id']}",
        f"  content:    {f['content']}",
        f"  scope:      {f.get('scope', 'unknown')}",
        f"  confidence: {f.get('confidence', 0):.2f}",
        f"  type:       {f.get('fact_type', 'observation')}",
        f"  committed:  {f.get('committed_at', 'unknown')}",
        f"  agent:      {f.get('agent_id', 'unknown')}",
    ]
    if f.get("provenance"):
        lines.append(f"  provenance: {f['provenance']}")
    return "\n".join(lines)


def _tier_label(tier: str) -> str:
    return {
        "tier0_entity": "entity extraction (config/version/port mismatch)",
        "tier1_nli": "semantic NLI (natural language contradiction)",
        "tier2_numeric": "numeric entity conflict (same entity, different values)",
        "tier2b_cross_scope": "cross-scope numeric conflict",
        "tier3_tkg_reversal": "TKG reversal (A→B→A belief flip detected)",
        "tier4_codebase": "codebase verification (fact contradicts code)",
    }.get(tier, tier)
