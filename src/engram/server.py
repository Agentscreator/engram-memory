"""Engram MCP Server -- four tools, that's the entire surface area.

Supports both stdio (local) and Streamable HTTP (team) transports.
Tool descriptions embed behavioral guidance for the LLM.
Integrates auth (Phase 5), rate limiting, and scope permissions.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from engram.engine import EngramEngine
from engram.storage import Storage

logger = logging.getLogger("engram")

mcp = FastMCP(
    "Engram",
    instructions=(
        "Engram is a shared knowledge consistency layer for engineering teams. "
        "It gives agents a persistent, shared memory that detects contradictions. "
        "Query before starting work. Commit verified discoveries. Check conflicts "
        "before architectural decisions."
    ),
)

# Engine and storage are initialized at startup via lifespan
_engine: EngramEngine | None = None
_storage: Storage | None = None
_auth_enabled: bool = False
_rate_limiter: Any = None


def get_engine() -> EngramEngine:
    if _engine is None:
        raise RuntimeError("Engram engine not initialized.")
    return _engine


def set_auth_enabled(enabled: bool) -> None:
    global _auth_enabled
    _auth_enabled = enabled


def set_rate_limiter(limiter: Any) -> None:
    global _rate_limiter
    _rate_limiter = limiter


# ── engram_commit ────────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
async def engram_commit(
    content: str,
    scope: str,
    confidence: float,
    agent_id: str | None = None,
    engineer: str | None = None,
    corrects_lineage: str | None = None,
    provenance: str | None = None,
    fact_type: str = "observation",
    ttl_days: int | None = None,
) -> dict[str, Any]:
    """Commit a claim about the codebase to shared team memory.

    Use this when your agent discovers something worth preserving:
    a hidden side effect, a failed approach, an undocumented constraint,
    an architectural decision, or a configuration detail.

    IMPORTANT: Do not commit speculative or uncertain claims. Only commit
    facts your agent has verified through code reading, testing, or
    direct observation. Set confidence below 0.5 for uncertain claims.

    IMPORTANT: Do not include secrets, API keys, passwords, or credentials
    in the content field. The server will reject commits containing
    detected secrets.

    IMPORTANT: Do not call this tool more than 5 times per task. Batch
    related discoveries into a single, well-structured claim.

    Parameters:
    - content: The claim in plain English. Be specific. Include service
      names, version numbers, config keys, and numeric values where
      relevant. BAD: "auth is broken". GOOD: "The auth service
      rate-limits to 1000 req/s per IP using a sliding window in Redis,
      configured via AUTH_RATE_LIMIT in .env".
    - scope: Hierarchical topic path. Examples: "auth", "payments/webhooks",
      "infra/docker". Use consistent scopes across your team.
    - confidence: 0.0-1.0. How certain is this claim? 1.0 = verified in
      code. 0.7 = observed behavior. 0.3 = inferred from context.
    - agent_id: Your agent identifier. Use your agent name for attribution
      (e.g. the name field from your AgentConfig when using open-multi-agent).
      Auto-generated if omitted.
    - engineer: Optional human identifier (email or username) of the engineer
      whose agent is making this commit. Used for team attribution and trust
      scoring. Example: "alice@example.com" or your GitHub username.
    - corrects_lineage: If this claim corrects a previous one, pass the
      lineage_id of the claim being corrected. The old claim will be
      marked as superseded.
    - provenance: Optional evidence trail. File path, line number, test
      output, or tool call ID that generated this evidence. Facts with
      provenance are marked as verified in query results.
    - fact_type: "observation" (directly observed in code/tests/logs),
      "inference" (concluded from observations), or "decision"
      (architectural decision by humans or agents). Default: observation.
    - ttl_days: Optional time-to-live in days. When set, the fact
      automatically expires after this period. Useful for facts about
      external dependencies, API contracts, or infrastructure that
      change frequently. Default: null (no expiry).

    Returns: {fact_id, committed_at, duplicate, conflicts_detected}
    """
    engine = get_engine()

    # Rate limiting (Phase 5)
    effective_agent = agent_id or "anonymous"
    if _rate_limiter is not None:
        if not _rate_limiter.check(effective_agent):
            raise ValueError(
                f"Rate limit exceeded for agent '{effective_agent}'. "
                f"Max {_rate_limiter.max_per_hour} commits per hour."
            )

    # Scope permission check (Phase 5)
    if _storage is not None and agent_id:
        from engram.auth import check_scope_permission
        allowed = await check_scope_permission(_storage, agent_id, scope, "write")
        if not allowed:
            raise ValueError(
                f"Agent '{agent_id}' does not have write permission for scope '{scope}'."
            )

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

    # Record rate limit usage after successful commit
    if _rate_limiter is not None:
        _rate_limiter.record(effective_agent)

    return result


# ── engram_query ─────────────────────────────────────────────────────


@mcp.tool(
    annotations={"readOnlyHint": True},
)
async def engram_query(
    topic: str,
    scope: str | None = None,
    limit: int = 10,
    as_of: str | None = None,
    fact_type: str | None = None,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Query what your team's agents collectively know about a topic.

    Call this BEFORE starting work on any area of the codebase. It returns
    claims from all agents across all engineers, ordered by relevance.

    IMPORTANT: Claims marked with has_open_conflict=true are disputed.
    Do not treat them as settled facts. Check the conflict details before
    relying on them.

    IMPORTANT: Claims marked with verified=false lack provenance. Treat
    them with appropriate skepticism.

    IMPORTANT: Do not call this tool more than 3 times per task. Refine
    your query to be specific rather than making multiple broad queries.

    Parameters:
    - topic: What you want to know about. Be specific. BAD: "auth".
      GOOD: "How does the auth service handle JWT token refresh?"
    - scope: Optional filter. "auth" returns claims in "auth" and all
      sub-scopes like "auth/jwt", "auth/oauth".
    - limit: Max results (default 10, max 50).
    - as_of: ISO 8601 timestamp for historical queries. Returns what
      the system knew at that point in time.
    - fact_type: Optional filter. "observation", "inference", or
      "decision". Omit to return all types.
    - agent_id: Your agent identifier. Used for read permission checks
      when the server runs in auth mode (--auth flag). Match the same
      agent_id you use when calling engram_commit.

    Returns: List of claims with content, scope, confidence, agent_id,
    committed_at, has_open_conflict, verified, fact_type, and provenance
    metadata.
    """
    engine = get_engine()

    # Scope read permission check when auth is enabled and scope is specified
    if _auth_enabled and _storage is not None and agent_id and scope:
        from engram.auth import check_scope_permission
        allowed = await check_scope_permission(_storage, agent_id, scope, "read")
        if not allowed:
            raise ValueError(
                f"Agent '{agent_id}' does not have read permission for scope '{scope}'."
            )

    return await engine.query(
        topic=topic,
        scope=scope,
        limit=limit,
        as_of=as_of,
        fact_type=fact_type,
    )


# ── engram_conflicts ─────────────────────────────────────────────────


@mcp.tool(
    annotations={"readOnlyHint": True},
)
async def engram_conflicts(
    scope: str | None = None,
    status: str = "open",
) -> list[dict[str, Any]]:
    """See where agents disagree about the codebase.

    Returns pairs of claims that contradict each other. Each conflict
    includes both claims, the detection method, severity, and an
    explanation (when available).

    Review these before making architectural decisions. A conflict means
    two agents (possibly from different engineers) believe incompatible
    things about the same system.

    Parameters:
    - scope: Optional filter by scope prefix.
    - status: "open" (default), "resolved", "dismissed", or "all".

    Returns: List of conflicts with claim pairs, severity, detection
    method, and resolution status.
    """
    engine = get_engine()
    return await engine.get_conflicts(scope=scope, status=status)


# ── engram_resolve ───────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
)
async def engram_resolve(
    conflict_id: str,
    resolution_type: str,
    resolution: str,
    winning_claim_id: str | None = None,
) -> dict[str, Any]:
    """Settle a disagreement between claims.

    Three resolution types:
    - "winner": One claim is correct. Pass winning_claim_id. The losing
      claim is marked superseded.
    - "merge": Both claims are partially correct. Commit a new merged
      claim first, then resolve with this tool.
    - "dismissed": The conflict is a false positive (claims don't actually
      contradict). This feedback improves future detection accuracy.

    Parameters:
    - conflict_id: The conflict to resolve.
    - resolution_type: "winner", "merge", or "dismissed".
    - resolution: Human-readable explanation of why this resolution
      is correct.
    - winning_claim_id: Required when resolution_type is "winner".

    Returns: {resolved: true, conflict_id, resolution_type}
    """
    engine = get_engine()
    return await engine.resolve(
        conflict_id=conflict_id,
        resolution_type=resolution_type,
        resolution=resolution,
        winning_claim_id=winning_claim_id,
    )
