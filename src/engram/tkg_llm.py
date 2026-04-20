"""LLM-powered extraction for the Temporal Knowledge Graph.

When OPENAI_API_KEY is set, this module replaces the regex pipeline with
LLM-based extraction that understands natural language — closing the gap
with Graphiti's approach.

Uses gpt-4o-mini via httpx (same pattern as api/mcp.py) — no SDK needed.
Falls back gracefully to the regex pipeline when no key is available.

Three LLM calls per fact (all gpt-4o-mini, ~$0.0003 total per fact):
  1. extract_triplets  — entities + relationships from free text
  2. extract_temporals — valid_at / invalid_at from temporal references
  3. resolve_edges     — semantic dedup + contradiction detection
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("engram.tkg")

_MODEL = "gpt-4o-mini"
_API_URL = "https://api.openai.com/v1/chat/completions"


def is_available() -> bool:
    """Check if LLM extraction is available (OPENAI_API_KEY set)."""
    return bool(os.getenv("OPENAI_API_KEY"))


async def _chat(system: str, user: str, max_tokens: int = 1024) -> str | None:
    """Make a single OpenAI chat completion call via httpx.

    Returns the raw response text, or None on failure.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import httpx
    except ImportError:
        logger.debug("httpx not installed — LLM extraction unavailable")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                },
            )
            if resp.status_code != 200:
                logger.debug("OpenAI API returned %d: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            raw = data["choices"][0]["message"]["content"].strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            return raw
    except Exception:
        logger.debug("OpenAI API call failed", exc_info=True)
        return None


# ── Triplet extraction ───────────────────────────────────────────────

_EXTRACT_SYSTEM = """\
You extract structured knowledge from engineering facts committed by AI agents.

Given a fact, extract ALL entity-relationship-entity triplets.
Also extract any temporal information (when things became true or stopped being true).

Respond with JSON only — no prose, no markdown fences:
{
  "triplets": [
    {
      "subject": "entity name (normalized, lowercase)",
      "relation": "relationship type (e.g. uses, depends_on, has_value, configured_as, runs_on, replaced_by, connects_to, deployed_to, version_is)",
      "object": "entity name or value (normalized, lowercase)",
      "fact_label": "one-sentence natural language description of this relationship"
    }
  ],
  "valid_at": "ISO datetime when this became true, or null if not mentioned",
  "invalid_at": "ISO datetime when this stopped being true, or null if not mentioned"
}

Rules:
- Extract implicit relationships too. "We went with Postgres" → subject: "database", relation: "uses", object: "postgres"
- Normalize entity names: "PostgreSQL" and "Postgres" → "postgres". "Auth Service" → "auth service"
- For numeric values, use has_value: "rate limit is 1000 req/s" → subject: "rate_limit", relation: "has_value", object: "1000 req/s"
- For transitions, extract replaced_by: "switched from X to Y" → subject: "x", relation: "replaced_by", object: "y"
- If the fact mentions a time ("last week", "in January", "yesterday"), extract valid_at relative to the reference time
- If the fact says something stopped being true, extract invalid_at
- Return empty triplets list if no relationships can be extracted
- Never invent information not present in the fact\
"""


async def extract_triplets(
    content: str,
    reference_time: str | None = None,
) -> dict[str, Any]:
    """Extract entity-relationship triplets and temporal info from fact content.

    Returns:
        {
            "triplets": [{"subject", "relation", "object", "fact_label"}, ...],
            "valid_at": str | None,
            "invalid_at": str | None,
        }
    """
    prompt = f"Fact content: {content}"
    if reference_time:
        prompt += f"\nReference time (when this fact was committed): {reference_time}"

    raw = await _chat(_EXTRACT_SYSTEM, prompt)
    if raw is None:
        return {"triplets": [], "valid_at": None, "invalid_at": None}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("LLM returned invalid JSON for triplet extraction")
        return {"triplets": [], "valid_at": None, "invalid_at": None}

    triplets = data.get("triplets", [])

    # Validate triplet structure
    valid_triplets = []
    for t in triplets:
        if all(k in t for k in ("subject", "relation", "object")):
            t["subject"] = str(t["subject"]).strip().lower()
            t["object"] = str(t["object"]).strip().lower()
            t["relation"] = str(t["relation"]).strip().lower().replace(" ", "_")
            if not t.get("fact_label"):
                t["fact_label"] = f"{t['subject']} {t['relation']} {t['object']}"
            if len(t["subject"]) >= 2 and len(t["object"]) >= 1:
                valid_triplets.append(t)

    return {
        "triplets": valid_triplets,
        "valid_at": data.get("valid_at"),
        "invalid_at": data.get("invalid_at"),
    }


# ── Node dedup via embeddings ────────────────────────────────────────

# Common aliases that should resolve to the same node
_KNOWN_ALIASES: dict[str, str] = {
    "postgresql": "postgres",
    "k8s": "kubernetes",
    "mongo": "mongodb",
    "rabbit": "rabbitmq",
    "es": "elasticsearch",
    "elastic": "elasticsearch",
    "gql": "graphql",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "aws lambda": "lambda",
    "amazon s3": "s3",
    "amazon sqs": "sqs",
    "amazon sns": "sns",
}


def resolve_node_name(name: str) -> str:
    """Normalize a node name, resolving known aliases."""
    normalized = name.strip().lower()
    return _KNOWN_ALIASES.get(normalized, normalized)


async def find_similar_node(
    name: str,
    existing_nodes: list[dict[str, Any]],
    threshold: float = 0.85,
) -> dict[str, Any] | None:
    """Find an existing node that is semantically similar to the given name.

    Uses embedding cosine similarity to catch cases like
    "auth service" vs "authentication service" or "DB" vs "database".

    Returns the matching node dict, or None if no match above threshold.
    """
    if not existing_nodes:
        return None

    try:
        from engram import embeddings

        query_emb = embeddings.encode(name)
        best_score = 0.0
        best_node = None

        for node in existing_nodes:
            node_emb = embeddings.encode(node["name"])
            score = embeddings.cosine_similarity(query_emb, node_emb)
            if score > best_score:
                best_score = score
                best_node = node

        if best_score >= threshold and best_node is not None:
            logger.debug(
                "TKG node dedup: '%s' → '%s' (sim=%.3f)",
                name,
                best_node["name"],
                best_score,
            )
            return best_node

    except Exception:
        logger.debug("Embedding-based node dedup failed for '%s'", name)

    return None


# ── Edge dedup via LLM ───────────────────────────────────────────────

_DEDUP_SYSTEM = """\
You are a fact deduplication assistant for a knowledge graph.
Given a NEW FACT and a list of EXISTING FACTS between the same entities,
determine if the new fact is a duplicate or contradicts any existing fact.

Respond with JSON only:
{
  "is_duplicate_of": null or index of the duplicate existing fact (0-based),
  "contradicts": [] (list of indices of contradicted existing facts)
}

Rules:
- A duplicate means the same factual information, even if worded differently
- A contradiction means the facts cannot both be true at the same time
- Different numeric values for the same metric = contradiction
- Same information with minor wording differences = duplicate
- Different subjects or different aspects = neither\
"""


async def check_edge_duplicate(
    new_fact_label: str,
    existing_fact_labels: list[str],
) -> dict[str, Any]:
    """Ask LLM whether a new edge duplicates or contradicts existing edges.

    Returns:
        {"is_duplicate_of": int | None, "contradicts": list[int]}
    """
    if not existing_fact_labels:
        return {"is_duplicate_of": None, "contradicts": []}

    existing_text = "\n".join(f"  [{i}] {label}" for i, label in enumerate(existing_fact_labels))
    prompt = f"EXISTING FACTS:\n{existing_text}\n\nNEW FACT: {new_fact_label}"

    raw = await _chat(_DEDUP_SYSTEM, prompt, max_tokens=256)
    if raw is None:
        return {"is_duplicate_of": None, "contradicts": []}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"is_duplicate_of": None, "contradicts": []}

    dup_idx = data.get("is_duplicate_of")
    contradicts = data.get("contradicts", [])

    # Validate indices
    max_idx = len(existing_fact_labels) - 1
    if dup_idx is not None and (not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx > max_idx):
        dup_idx = None
    contradicts = [i for i in contradicts if isinstance(i, int) and 0 <= i <= max_idx]

    return {"is_duplicate_of": dup_idx, "contradicts": contradicts}
