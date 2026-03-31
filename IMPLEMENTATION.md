# Engram Implementation Plan

This plan is grounded in the papers in [`./papers/`](./papers/), the adversarial literature
review in [`LITERATURE.md`](./LITERATURE.md), and a study of the MCP servers that have
achieved real production adoption (Context7 at 44k stars, GitHub MCP at 20k, Playwright
MCP at 15k, plus Block's playbook from building 60+ MCP servers internally).

Four rounds of adversarial research shaped the architecture:

- **Round 1** exposed embedding retrieval failures and LLM-as-judge agreeableness bias.
- **Round 2** replaced the LLM-only pipeline with a tiered NLI approach, cutting latency 200×.
- **Round 3** found seven structural failure modes and collapsed four versioning mechanisms
  into one invariant: *temporal validity intervals*. BFT, graph database, and quorum commits
  removed as premature complexity.
- **Round 4** studied the live MCP ecosystem: Anthropic's MCP donated to the Linux Foundation
  (Agentic AI Foundation, Dec 2025), Block's 60+ internal server playbook, Context7's
  sub-agent filtering architecture, Google's managed remote MCP design, Microsoft's
  Windows ODR security proxy, and the OWASP/Invariant Labs MCP attack surface research.
  Four new failure modes added; transport upgraded to Streamable HTTP; AGENTS.md
  integration added; entity resolution improved with MinHash/Jaccard heuristics.

The unifying pattern across every successful MCP server: minimal tool count, rich tool
descriptions that guide LLM behavior, server-side intelligence, zero-setup deployment,
and privacy by design.

---

## Unifying Insight: Every Fact Has a Validity Window

The simplest possible correct model for a changing knowledge base is:

```
fact(id, content, valid_from, valid_until, ...)
```

A fact is **current** when `NOW() ∈ [valid_from, valid_until)`.  
A fact is **superseded** when `valid_until IS NOT NULL`.  
A fact is **archived** when `valid_until` is old enough.  
A fact is **a version** because all versions share a `lineage_id`.

This collapses *four separate Round 2 mechanisms* into one:
- `superseded_by` pointer → closed `valid_until`
- `utility_score` decay → query on `valid_from` age
- `facts_archive` table → filtered by `valid_until < ARCHIVE_CUTOFF`
- version chain → all rows with same `lineage_id`, ordered by `valid_from`

This is the **Graphiti insight** — bitemporal modeling — applied to a flat fact store. It
makes the schema smaller, the queries simpler, and the invariants obvious. Time is the
only versioning primitive needed.

---

## Architecture Overview

Engram is a **consistency layer** — not a memory system, not a knowledge graph, not a
graph database. It answers one question: *are the facts agents are working from coherent
with each other?*

```
┌──────────────────────────────────────────┐
│            I/O Layer (MCP)               │  ← agents connect here
│  engram_commit / engram_query /          │
│  engram_conflicts / engram_resolve       │
├──────────────────────────────────────────┤
│          Detection Layer                 │  ← runs asynchronously
│  Tier 0: hash dedup + entity exact-match │
│  Tier 1: NLI cross-encoder (local)       │
│  Tier 2: numeric/temporal rules          │
│  Tier 3: LLM escalation (rare)           │
├──────────────────────────────────────────┤
│          Storage Layer (SQLite)          │  ← durable append-only log
│  facts (temporal), conflicts, agents,    │
│  scope_permissions, detection_feedback   │
└──────────────────────────────────────────┘
```

Conflict detection runs **outside the write path**. Every `engram_commit` returns
immediately; detection happens in a background thread, completing within ~500ms for
typical loads. This eliminates the SQLite write-lock contention that the Round 3
analysis identified as an existential bottleneck.

---

## MCP Tool Design — Lessons from the Ecosystem

The most successful MCP servers share a pattern: minimal tool count, rich descriptions,
server-side intelligence. Context7 (44k GitHub stars, 240k weekly npm downloads) exposes
exactly two tools. GitHub MCP (20k stars) wraps entire workflows into single tools rather
than exposing raw API endpoints. Block's internal playbook from 60+ MCP servers says:
*"Design top-down from workflows, not bottom-up from API endpoints."*

Engram applies these lessons:

### Tool Surface: Four Tools, Not Seven

```
engram_commit   — Write a claim to shared memory
engram_query    — Read what the team's agents know about a topic
engram_conflicts — See where agents disagree
engram_resolve  — Settle a disagreement
```

That's it. `engram_dismiss` is folded into `engram_resolve` (with `resolution_type =
"dismissed"`). No separate archive query tool — `engram_query` accepts an `as_of`
parameter for historical lookups. Every tool removed is one fewer thing the LLM has to
reason about when deciding which tool to call.

### Tool Descriptions as LLM Behavioral Guidance

Context7's key insight: tool descriptions are not documentation for humans — they are
**prompts for the LLM**. Context7 embeds privacy guardrails, call frequency limits,
selection criteria, and query quality guidance directly in tool descriptions. The LLM
reads these at tool discovery time and follows them.

Engram's tool descriptions follow this pattern:

```python
@mcp.tool
def engram_commit(
    content: str,
    scope: str,
    confidence: float,
    agent_id: str | None = None,
    corrects_lineage: str | None = None,
) -> dict:
    """Commit a claim about the codebase to shared team memory.

    Use this when your agent discovers something worth preserving:
    a hidden side effect, a failed approach, an undocumented constraint,
    an architectural decision, or a configuration detail.

    IMPORTANT: Do not commit speculative or uncertain claims. Only commit
    facts your agent has verified through code reading, testing, or
    direct observation. Set confidence below 0.5 for uncertain claims.

    IMPORTANT: Do not include secrets, API keys, passwords, or credentials
    in the content field. These will be permanently stored.

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
    - agent_id: Your agent identifier. Auto-generated if omitted.
    - corrects_lineage: If this claim corrects a previous one, pass the
      lineage_id of the claim being corrected. The old claim will be
      marked as superseded.

    Returns: {claim_id, committed_at, duplicate, conflicts_detected}
    """
```

```python
@mcp.tool
def engram_query(
    topic: str,
    scope: str | None = None,
    limit: int = 10,
    as_of: str | None = None,
) -> list[dict]:
    """Query what your team's agents collectively know about a topic.

    Call this BEFORE starting work on any area of the codebase. It returns
    claims from all agents across all engineers, ordered by relevance.

    IMPORTANT: Claims marked with has_open_conflict=true are disputed.
    Do not treat them as settled facts. Check the conflict details before
    relying on them.

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

    Returns: List of claims with content, scope, confidence, agent_id,
    committed_at, has_open_conflict, and provenance metadata.
    """
```

```python
@mcp.tool
def engram_conflicts(
    scope: str | None = None,
    status: str = "open",
) -> list[dict]:
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
```

```python
@mcp.tool
def engram_resolve(
    conflict_id: str,
    resolution_type: str,
    resolution: str,
    winning_claim_id: str | None = None,
) -> dict:
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
```

### Tool Annotations

Following the MCP 2025-11-25 spec, all tools carry annotations:

```python
# engram_commit
annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}

# engram_query
annotations={"readOnlyHint": True}

# engram_conflicts
annotations={"readOnlyHint": True}

# engram_resolve
annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
```

### Server-Side Intelligence

Context7's biggest performance win was moving filtering and ranking from the LLM to the
server — reducing token consumption by 65% and latency by 38%. Engram applies the same
principle:

- `engram_query` returns pre-ranked, pre-scored results. The LLM does not need to
  re-rank or filter. Each result includes a relevance score and conflict flag.
- `engram_conflicts` returns conflicts pre-grouped by scope and pre-sorted by severity.
  The LLM gets an actionable queue, not raw data.
- `engram_commit` performs dedup, entity extraction, and conflict detection server-side.
  The LLM just provides the raw claim text.

Token budget: `engram_query` responses are capped at ~4000 tokens (10 claims × ~400
tokens each). If a claim is too long, it is truncated server-side with a note. This
follows Block's guidance: *"Check byte size or estimate token count before returning
text."*

### Transport and Deployment

**Transport:** Engram supports both stdio (for local use with Claude Desktop, Cursor,
Kiro) and Streamable HTTP (for team/remote deployment). Streamable HTTP replaced SSE
in the MCP 2025-03-26 spec and is the recommended transport for remote servers.

**Zero-setup local deployment:**
```json
{
  "mcpServers": {
    "engram": {
      "command": "uvx",
      "args": ["engram-mcp@latest"]
    }
  }
}
```

One line of config. No Docker, no separate server process, no database setup. The
server creates `~/.engram/knowledge.db` on first run. This follows Context7's lesson:
*"Every additional setup step is a point where potential users drop off."*

**Team deployment:**
```json
{
  "mcpServers": {
    "engram": {
      "url": "http://engram.internal:7474/mcp"
    }
  }
}
```

Or Docker:
```
docker run -p 7474:7474 -v engram-data:/data engram/server
```

**Auth for remote deployment:** OAuth 2.1 per the MCP 2025-06-18 spec. Bearer tokens
as the MVP, with the server acting as an OAuth 2.0 Resource Server. Tokens are bound
to the server instance (audience claim) to prevent token confusion attacks.

### Privacy by Design

Following Context7's model: agent code never leaves the local machine. `engram_commit`
receives only the claim text the agent explicitly provides. `engram_query` receives
only the topic string. The NLI model and embedding model run locally. The only external
call is Tier 3 LLM escalation (optional, for ambiguous cases), and even that sends
only the two claim texts being compared — never the agent's code or conversation.

---

## Phase 1 — Foundation: Data Model and Storage

**Goal:** Define the schema. Everything else depends on getting this right.

### Fact Schema

```sql
CREATE TABLE facts (
    id               TEXT PRIMARY KEY,   -- uuid4
    lineage_id       TEXT NOT NULL,      -- groups all versions of "the same fact"
    content          TEXT NOT NULL,      -- raw text committed by the agent
    content_hash     TEXT NOT NULL,      -- SHA-256(normalize(content)), for dedup
    scope            TEXT NOT NULL,      -- e.g. "auth", "payments/webhooks"
    confidence       REAL NOT NULL,      -- 0.0–1.0, agent-reported
    agent_id         TEXT NOT NULL,
    engineer         TEXT,
    keywords         TEXT,               -- JSON array
    entities         TEXT,               -- JSON array: {name, type, value}
    embedding        BLOB,               -- float32, serialized numpy
    embedding_model  TEXT NOT NULL,      -- "all-MiniLM-L6-v2"
    embedding_ver    TEXT NOT NULL,      -- semver of sentence-transformers
    committed_at     TEXT NOT NULL,      -- ISO 8601
    valid_from       TEXT NOT NULL,      -- ISO 8601 (= committed_at for new facts)
    valid_until      TEXT               -- NULL = currently valid; set when superseded
);

-- Validity window is the primary query filter
CREATE INDEX idx_facts_validity   ON facts(scope, valid_until);
CREATE INDEX idx_facts_content_hash ON facts(content_hash);
CREATE INDEX idx_facts_lineage    ON facts(lineage_id);
CREATE INDEX idx_facts_agent      ON facts(agent_id);
```

**Why `valid_until` replaces all Round 2 versioning machinery:**

| Round 2 mechanism | Round 3 equivalent |
|---|---|
| `superseded_by TEXT` pointer | `valid_until = now()` on the old fact |
| `facts_archive` table | `WHERE valid_until < ARCHIVE_CUTOFF` |
| `utility_score REAL` decay field | `DATEDIFF(now(), valid_from) > THRESHOLD` |
| Version chain via `superseded_by` | `WHERE lineage_id = X ORDER BY valid_from` |

Four separate mechanisms → one temporal predicate.

**Why `lineage_id` is new:** When a fact is corrected, the new version shares the old
fact's `lineage_id`. This enables point-in-time queries ("what did the system believe
about auth rate limits on day T?") and audit trails without any complex pointer chasing.

**Entity extraction format:**
```json
[
  {"name": "rate_limit", "type": "numeric", "value": 1000, "unit": "req/s"},
  {"name": "auth_service", "type": "service"},
  {"name": "JWT_SECRET", "type": "config_key"}
]
```
Structured entities are the foundation for Tier 0 and Tier 2 detection — they provide
O(1) exact-match lookup that is immune to embedding anisotropy and NLI domain shift.

### Conflict Schema

```sql
CREATE TABLE conflicts (
    id               TEXT PRIMARY KEY,
    fact_a_id        TEXT NOT NULL REFERENCES facts(id),
    fact_b_id        TEXT NOT NULL REFERENCES facts(id),
    detected_at      TEXT NOT NULL,
    detection_tier   TEXT NOT NULL,  -- "tier0_entity" | "tier1_nli" | "tier2_numeric" | "tier3_llm"
    nli_score        REAL,           -- contradiction score from NLI model, if applicable
    explanation      TEXT,           -- LLM-generated only for Tier 3
    severity         TEXT NOT NULL,  -- "high" | "medium" | "low"
    status           TEXT NOT NULL DEFAULT 'open',  -- "open" | "resolved" | "dismissed"
    resolved_by      TEXT,
    resolved_at      TEXT,
    resolution       TEXT
);
```

### Agent Registry

```sql
CREATE TABLE agents (
    agent_id         TEXT PRIMARY KEY,
    engineer         TEXT NOT NULL,
    label            TEXT,
    registered_at    TEXT NOT NULL,
    last_seen        TEXT,
    total_commits    INTEGER DEFAULT 0,
    flagged_commits  INTEGER DEFAULT 0   -- commits later involved in a conflict
);
```

`flagged_commits / total_commits` = **agent reliability ratio**. Used only as a
*downweight* signal in query scoring, not as an access control gate. An agent
with high conflict rate gets its facts surfaced lower, not blocked.

### NLI Feedback Table

```sql
CREATE TABLE detection_feedback (
    conflict_id    TEXT NOT NULL REFERENCES conflicts(id),
    feedback       TEXT NOT NULL,   -- "true_positive" | "false_positive"
    recorded_at    TEXT NOT NULL
);
```

False-positive feedback from `engram_dismiss` feeds a local calibration file
that adjusts the NLI threshold over time. This addresses the calibration failure
mode identified in Round 3.

### Scope Permissions

```sql
CREATE TABLE scope_permissions (
    agent_id   TEXT NOT NULL,
    scope      TEXT NOT NULL,
    can_read   BOOLEAN NOT NULL DEFAULT TRUE,
    can_write  BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (agent_id, scope)
);
```

Hierarchical scope matching: `payments/webhooks` inherits from `payments`. Default
(no row): full access. This is the MVP — role-based extensions and temporal policy
windows are future work.

---

## Phase 2 — Core MCP Server

**Goal:** A working MCP server that commits and queries facts. No conflict detection yet.

### Stack

| Dependency | Purpose | Why this and not X |
|---|---|---|
| `fastmcp` or `mcp` SDK | MCP server | Standard; supports Streamable HTTP transport |
| `aiosqlite` | Async SQLite I/O | WAL mode + async = correct |
| `sentence-transformers` | Embeddings + NLI | Local, no API key |
| `rank_bm25` | Lexical retrieval | Negation blindness fix |
| `numpy` | Cosine similarity | No extra dep |
| `datasketch` | MinHash for entity dedup | Round 4: replaces LLM-only entity resolution |

**Transport:** Streamable HTTP (MCP spec v2025-03-26+) is the default for remote
deployment. Local/CLI use is `stdio`. The legacy `HTTP+SSE` transport (2024-11-05 spec)
is deprecated by the MCP spec; Engram will not implement it. Streamable HTTP uses a
single `/mcp` endpoint supporting POST and GET, is stateless, and deploys behind any
standard reverse proxy (nginx, Cloudflare) — identical to how Google's managed remote
MCP endpoints and Microsoft's Azure-hosted MCP services work in production.

FastMCP is now integrated into the official `mcp` Python SDK. Engram uses the `@mcp.tool`
decorator pattern for tool registration, following the same pattern as Context7 and other
production MCP servers. Tool descriptions follow the behavioral guidance pattern described
in §MCP Tool Design.

**No graph database.** SQLite + the `entities` JSON column provides all the structured
lookup needed. Graph databases add operational burden for no capability advantage within
Engram's scope. See §MCP Tool Design for the rationale: Engram is a consistency layer,
not a knowledge graph.

**No BFT.** Engram serves a permissioned team. Crash fault tolerance via SQLite WAL is
sufficient.

**SQLite concurrency strategy:**
- WAL mode: `PRAGMA journal_mode=WAL` (readers never block writers)
- Busy timeout: `PRAGMA busy_timeout=5000`
- Conflict detection runs in a **background thread**, holding no write lock during
  NLI inference. The inference result is written in a single short transaction.
- Write lock is held only for the duration of the `INSERT INTO facts` statement
  (~1ms), not for the 300ms NLI scan. This is the structural fix for the Round 3
  bottleneck: decouple inference from the write path.

### `engram_commit(fact, scope, confidence, agent_id?, source_lineage_id?)`

1. Validate inputs
2. Compute `content_hash` (SHA-256 of lowercased, whitespace-normalized content)
3. **Dedup check:** `SELECT id FROM facts WHERE content_hash = ? AND valid_until IS NULL AND scope = ?`.
   If found, return `{fact_id: existing_id, duplicate: true}`. O(1) — no model inference.
4. Generate embedding for `content`
5. Extract `keywords` and `entities` via a lightweight local model or rule-based extractor.
   Entity extraction is mandatory even without LLM — a regex/rule engine can extract
   numerics, version numbers, and capitalized service names from codebase facts reliably.
6. Determine `lineage_id`: if `source_lineage_id` is provided, inherit it (this is a
   correction of an existing fact). Otherwise, generate a new UUID.
7. If correcting an existing fact: `UPDATE facts SET valid_until = NOW() WHERE lineage_id = source_lineage_id AND valid_until IS NULL`
8. `INSERT INTO facts (..., valid_from = NOW(), valid_until = NULL)`
9. Post the new `fact_id` to the **detection queue** (in-memory `asyncio.Queue`).
   Return immediately: `{fact_id, committed_at, duplicate: false}`

**Write lock is released at step 8.** Detection runs without holding any lock.

### `engram_query(topic, scope?, limit?, as_of?)`

1. Generate embedding for `topic`
2. Retrieve **currently valid** facts: `WHERE valid_until IS NULL [AND scope = ?]`
   If `as_of` timestamp provided: `WHERE valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)`
   This enables historical point-in-time queries without any additional machinery.
3. **Dual retrieval:** Score via embedding cosine + BM25 rank, fuse with RRF.
4. **Scoring:**
   ```
   score = relevance              (RRF rank, 0-1 normalized)
         + 0.2 * recency          (exp(-0.05 * days_since_commit))
         + 0.15 * agent_trust     (1 - flagged_commits/total_commits)
   ```
   **Change from Round 2:** Confidence is REMOVED from the scoring formula.
   Agent-reported confidence is uncalibrated (Round 3 finding: LLMs systematically
   over-report confidence). Including it as a scoring signal pollutes retrieval with
   noise. Confidence is still stored and returned as metadata; agents can weight it
   themselves.
5. Return top-`limit` facts (default 10) with `has_open_conflict` flag joined from
   `conflicts` table. Agents must see contested facts.

**Why the `as_of` parameter matters:** A debugging agent can query "what did Engram
know about the auth service on December 3rd?" without any special archive mechanism.
The validity window makes this a free predicate.

### `engram_conflicts(scope?, status?)`

Returns rows from `conflicts` table filtered by scope and status. Scope filtering uses
prefix matching: `WHERE fact_a_scope LIKE scope || '%'`.

### `engram_resolve(conflict_id, resolution_type, resolution, winning_claim_id?)`

Handles all conflict resolution, including dismissals (folded from the former
`engram_dismiss` — fewer tools = better LLM tool selection):

- `resolution_type = "winner"`: Closes the losing fact's validity window.
- `resolution_type = "merge"`: Expects a new synthesizing fact already committed.
  Closes both originals' windows.
- `resolution_type = "dismissed"`: Sets status to dismissed. Inserts a row into
  `detection_feedback` with `feedback = 'false_positive'`. This feeds the NLI
  threshold calibration loop (Phase 3).

---

## Phase 3 — Conflict Detection

**Goal:** Implement the consistency mechanism. This runs entirely outside the write path.

The detection worker is a background `asyncio` coroutine that consumes from the
detection queue posted by `engram_commit`. It processes one commit at a time to avoid
database lock contention.

### Critical Domain-Shift Finding (Round 3)

The 92% accuracy claim for `cross-encoder/nli-deberta-v3-base` is from SNLI/MNLI
benchmarks on general English. Codebase facts like *"The auth service rate-limits to
1,000 requests per second per IP"* are **not** general English. Domain shift will
degrade NLI accuracy on technical facts, potentially severely.

**Mitigation:** NLI is demoted from *judge* to *signal*. The tiered pipeline is
restructured so that:
1. Deterministic rules (Tier 0 + Tier 2) handle the majority of **high-confidence
   technical contradictions** (numeric values, entity attribute conflicts) — these are
   immune to domain shift.
2. NLI (Tier 1) handles **semantic contradictions** that rules cannot catch — its score
   is used as a screen, not a verdict at high-confidence thresholds.
3. LLM (Tier 3) generates explanations and handles ambiguous cases with domain
   understanding.

The NLI threshold is **locally calibrated** using the `detection_feedback` table.
After 100 conflict feedback events, the threshold is adjusted:
`threshold = threshold - 0.05 * (false_positive_rate - 0.1)`.
This creates a feedback loop that adapts the NLI to the team's codebase vocabulary.

### Detection Pipeline

**Tier 0 — Deterministic Pre-Checks (<1ms)**

Runs first, before any model inference:

1. **Content hash dedup** (already done in commit): `content_hash = f_existing.content_hash`
2. **Entity exact-match conflict:**
   For each entity in `f_new.entities` where `type in ("numeric", "config_key", "version")`,
   find all current facts with:
   - Same `scope`
   - Same entity `name`
   - Different entity `value`
   
   ```sql
   SELECT f.id FROM facts f, json_each(f.entities) e
   WHERE f.valid_until IS NULL
     AND f.scope = ?
     AND e.value->>'name' = ?
     AND e.value->>'value' != ?
   ```
   
   If found: **flag as conflict immediately** with `detection_tier = 'tier0_entity'`,
   `severity = 'high'` (numeric/config conflicts in code are rarely ambiguous).

This tier catches "rate limit is 1000" vs "rate limit is 2000" with zero ML.

**Tier 1 — NLI Cross-Encoder (<500ms total)**

For `f_new`, retrieve candidates via three parallel paths:
- *Path A:* Top-20 embedding-similar current facts in scope
- *Path B:* Top-10 BM25 lexical matches in scope
- *Path C:* All facts with overlapping entity names (regardless of value)

Union, dedup, skip any already flagged by Tier 0. Cap at 30 candidates.

For each candidate:
```python
nli_model = CrossEncoder('cross-encoder/nli-deberta-v3-base')
scores = nli_model.predict([(f_new.content, f_cand.content)])
# scores[0] = contradiction, scores[1] = entailment, scores[2] = neutral
```

Classification:
- `contradiction_score > THRESHOLD_HIGH` (default 0.85, locally calibrated): **flag conflict**
  with `detection_tier = 'tier1_nli'`, `nli_score = contradiction_score`
- `contradiction_score > THRESHOLD_LOW` (default 0.5): **escalate to Tier 3**
- `entailment_score > 0.85`, different agents: **corroboration link** (metadata only, not a conflict)

Tier 1 completes in ~300ms for 30 candidates. This is acceptable for an async background
worker — it does not block the write path.

**Tier 2 — Numeric and Temporal Rules (<5ms, parallel with Tier 1)**

For each candidate pair already in the candidate set:
- **Numeric:** Same scope + same entity name + different numeric value → conflict
  (catches what Tier 0 missed if entity extraction was partial)
- **Temporal:** Conflicting temporal claims about the same entity:
  "X was deprecated in Q1" vs "X is current" → flag with `detection_tier = 'tier2_temporal'`

**Tier 3 — LLM Escalation (~2000ms, rare)**

Invoked only when:
- Tier 1 NLI score is ambiguous (0.5–0.85)
- An explanation is needed for a confirmed conflict (on-demand, for the dashboard)
- A scope is configured as `high_stakes = true`

```
System: You are an adversarial fact-checker. Your job is to find contradictions
        between two facts about a codebase. You should be skeptical and look for
        ANY way these facts could be incompatible.

        The NLI model flagged these facts (score: {nli_score}).
        List all ways they COULD contradict. Then assess each. Give your verdict.

        Respond with JSON:
        {
          "verdict": {"contradicts": bool, "explanation": str, "severity": "high|medium|low"}
        }

Fact A (agent: {agent_a}, scope: {scope}, committed: {date_a}):
{content_a}

Fact B (agent: {agent_b}, scope: {scope}, committed: {date_b}):
{content_b}
```

Adversarial framing counteracts agreeableness bias. The NLI score anchors the LLM.
Use a cheap, fast model (e.g., `claude-haiku-4-5`). LLM is NOT required for the core
detection path — Tiers 0+2 handle all numeric/structural contradictions deterministically.

### Stale Supersession (Same-Lineage Update)

When `f_new` and `f_candidate` share the same `lineage_id` and NLI entailment > 0.85:
`f_candidate` is an older version of `f_new`. Close its window:
`UPDATE facts SET valid_until = NOW() WHERE id = f_candidate.id AND valid_until IS NULL`

### Severity Heuristic

| Condition | Severity |
|---|---|
| Tier 0 entity conflict (numeric/config key) | high |
| Tier 2 numeric conflict | high |
| Tier 1 NLI > 0.85, different engineers | high |
| Tier 1 NLI > 0.85, same engineer | medium |
| Tier 3 LLM confirmed, any | medium |
| Tier 1 NLI 0.5–0.85, escalated but not confirmed | low |

### Performance vs. Round 2

| Metric | Round 2 (NLI in write path) | Round 3 (NLI in background) |
|---|---|---|
| Commit latency | ~500ms (NLI blocking) | <10ms (async queue post) |
| Detection latency | ~500ms | ~500ms (background) |
| Write lock held | ~500ms | ~1ms |
| SQLite throughput at 10 concurrent agents | Serialized, ~2 commits/s | ~100 commits/s |
| NLI on technical facts | 92% (benchmark) | Calibrated via feedback loop |

The structural change: **detection is decoupled from the write path**. This is the
only architectural change that prevents SQLite write serialization from being fatal
under concurrent agent use.

---

## Phase 4 — Conflict Resolution Workflow

*Same as Round 2, except `engram_resolve` now closes validity windows instead of setting
`superseded_by` pointers.*

**Resolution strategies:**
1. **Last-writer-wins:** Close older fact's `valid_until`. New fact's `valid_from`
   becomes the resolution timestamp.
2. **Higher-confidence-wins:** Close lower-confidence fact's `valid_until`.
3. **Merge:** Commit a new synthesizing fact (possibly with a shared `lineage_id`),
   close both originals' windows.

---

## Phase 5 — Agent Identity and Access Control

**No quorum commits.** Quorum requires ≥2 agents to commit a fact before it's trusted.
For a single-developer workflow (the majority use case), quorum makes Engram
non-functional. Source corroboration in query scoring is sufficient.

**Auth model follows the MCP 2025-06-18 spec:**

The MCP spec now classifies MCP servers as OAuth 2.0 Resource Servers. Engram implements
this in two tiers:

1. **Local mode (default):** No auth. The server runs on localhost, accessed via stdio
   transport. This is the zero-setup path — identical to how Context7, GitHub MCP, and
   every other popular local MCP server works.

2. **Team mode (`--auth`):** Bearer token auth as the MVP. Tokens are JWTs bound to the
   server instance (audience claim) to prevent token confusion attacks per the MCP spec's
   security considerations. HTTPS required for non-localhost.

```
engram serve --auth
engram token create --engineer [email]
```

Future: full OAuth 2.1 with PKCE, Protected Resource Metadata (RFC 9728), and the
`resource` parameter (RFC 8707) for token binding. This aligns with the MCP spec's
direction and enables integration with enterprise identity providers.

**Input validation:** Following Aptori's and Block's MCP security guidance, all tool
inputs are validated via Pydantic models. LLM output is treated as untrusted input.
Parameterized queries only — no string interpolation in SQL. Entity extraction uses
allowlisted patterns, not arbitrary LLM output.

---

## Phase 6 — Cross-Team Federation

The append-only `facts` table (with `valid_from`/`valid_until`) is already a
**replicated journal** — every row is immutable once `valid_from` is set. This makes
federation trivially correct: pull-based sync of rows since a watermark timestamp.

```
GET /facts/since?after=2025-12-01T00:00:00Z&scope=shared/*
```

Remote facts arrive with their original `agent_id`, `committed_at`, and `valid_from`.
Local conflict detection runs on ingested remote facts using the same pipeline as local
commits. No cross-node RPC needed for detection — the NLI cross-encoder runs locally.

Federation is an **eventually consistent** distributed append-only log. Row-level
immutability guarantees convergence: the same row committed to two nodes will always
produce the same state (same `id`, same `content_hash`). The only conflict is semantic,
not structural, and semantic conflicts are the detection layer's job.

---

## Phase 7 — Dashboard

**Goal:** Make the knowledge base inspectable by humans.

**Stack:** FastAPI (same process, separate router) + server-rendered HTML with HTMX.
No separate frontend build step. Endpoint: `http://HOST:PORT/dashboard`.

This follows the MCP ecosystem pattern: the MCP server handles the protocol layer,
and a co-located HTTP endpoint serves the human interface. Agent-MCP uses the same
pattern (MCP + web dashboard in one process).

**Views:**
- **Knowledge base** — current facts (`valid_until IS NULL`), filterable by scope/agent/date
- **Conflict queue** — open conflicts, grouped by scope, severity-sorted. Each shows both
  facts side-by-side with detection tier and NLI score.
- **Timeline** — fact commits and validity windows as a Gantt-like chart. Makes it visible
  when different agents were active in the same scope.
- **Agent activity** — per-engineer commit rate, conflict rate, resolution rate
- **Point-in-time view** — query the knowledge base as of any past timestamp (enabled
  free by the `valid_from`/`valid_until` schema)

Human review is **structurally necessary**, not optional. CLAIRE [25] demonstrated that
automated consistency detection has a hard ceiling at ~75% AUROC. The conflict queue
is the human-in-the-loop interface that lifts the system above this ceiling.

---

## Delivery Sequence

| Phase | Deliverable | Unlocks |
|---|---|---|
| 1 | Schema + migrations | All subsequent phases |
| 2 | MCP server: commit + query | Usable by agents today |
| 3 | Conflict detection (background, tiered) | Core differentiator |
| 4 | Resolution workflow | Conflicts become actionable |
| 5 | Auth + access control | Team deployment |
| 6 | Federation (replicated journal) | Multi-team / org-wide |
| 7 | Dashboard | Human oversight (critical for >75% precision) |

Phases 1–3 are the minimum viable Engram. The background worker in Phase 3 is the
structural prerequisite for Phase 2 being usable under any real load.

---

## Failure Modes & Mitigations (Round 3 Findings)

### 1. NLI Domain Collapse (CRITICAL — Addressed)
- **Failure:** `cross-encoder/nli-deberta-v3-base` trained on SNLI/MNLI (general English).
  Technical codebase facts have different vocabulary, phrasing, and logical structure.
  The 92% benchmark accuracy does not transfer to "rate limit is 1000 req/s" vs "rate
  limit is 2000 req/s" — an NLI model trained on everyday language may classify these
  as "neutral" (both describe a rate limit) rather than "contradiction."
- **Mitigation:**
  - Dominance inversion: Tier 0 entity exact-match and Tier 2 numeric rules handle all
    numeric/config contradictions deterministically, eliminating the NLI's blind spot.
  - NLI handles only *natural language semantic* contradictions — its genuine strength.
  - Local threshold calibration via `detection_feedback` table adapts to team vocabulary.
  - Future: fine-tune on domain-specific pairs using LoRA (low cost, high impact).

### 2. SQLite Write Serialization Under Concurrent Load (CRITICAL — Addressed)
- **Failure:** Round 2 ran NLI inference (~300ms) inside the write path, holding the
  exclusive SQLite write lock for the duration. With 10 concurrent agents: ~3 commits/s
  maximum throughput. The system collapses under any real team workload.
- **Mitigation:** Detection is fully decoupled from the write path. The write lock is
  held for <1ms (a single `INSERT`). Detection runs in a background asyncio worker.
  Throughput ceiling is now SQLite's actual insert rate (~10,000/s in WAL mode).

### 3. BFT Over-Engineering (REMOVED)
- **Failure:** Byzantine Fault Tolerance requires O(n²) communication overhead and is
  designed for open adversarial networks. A permissioned team knowledge base with trusted
  agents has no Byzantine adversaries. Adding BFT would increase implementation complexity
  by an order of magnitude while providing zero benefit for the target use case.
- **Resolution:** Removed entirely. Rate limiting, agent reliability scoring, and
  source corroboration provide sufficient defense against accidental or low-sophistication
  poisoning. Full adversarial attack resistance is explicitly out of scope.

### 4. Graph Database Scope Creep (REMOVED)
- **Failure:** Round 2's §5 proposed replacing SQLite with a graph database, contradicting
  the explicit "What Engram Is Not" section. Graph databases require external services
  (Neo4j, Memgraph), new query languages, and operational burden. They provide graph
  traversal — a capability Engram's use case (consistency checking) does not require.
- **Resolution:** Removed entirely. `entities` JSON column provides structured entity
  lookup without any graph infrastructure.

### 5. Uncalibrated Confidence Scoring (ADDRESSED)
- **Failure:** Four-signal scoring (`0.5 * relevance + 0.2 * recency + 0.15 * reliability
  + 0.15 * confidence`) includes agent-reported confidence as a ranking signal. LLMs
  systematically over-report confidence regardless of epistemic state. The weights are
  ad-hoc and will not be retuned. Including confidence pollutes retrieval with noise.
- **Mitigation:** Confidence removed from the scoring formula. It is stored as metadata
  for human inspection, but does not affect retrieval ranking. Scoring uses three signals:
  relevance (RRF), recency, and agent trust (derived from conflict history — calibrated
  by actual outcomes, not self-reported).

### 6. Quorum Commits Breaking Single-Developer Use (REMOVED)
- **Failure:** Round 2 proposed quorum-based commits for "sensitive scopes," requiring
  multiple agents to ratify a fact before it's trusted. For solo developers (the primary
  initial user), this makes Engram unusable: no quorum is ever achievable.
- **Resolution:** Removed. Source corroboration (the number of independent agents whose
  facts align) is tracked as metadata and used as a downweight signal in query scoring.
  This achieves the semantic goal (single-source facts are lower-confidence) without
  the mechanism that would gate solo usage.

### 7. Missing Point-in-Time Queryability (ADDRESSED)
- **Failure:** Round 2 had no mechanism to query the knowledge base as it was on a
  specific past date. The `facts_archive` table actively destroyed this capability by
  moving old facts out of the main query path.
- **Mitigation:** The `valid_from`/`valid_until` temporal model makes this a free
  predicate on the main `facts` table. `engram_query(topic, as_of="2025-12-01")` works
  without any additional infrastructure.

### 8. Silent Retrieval Corruption on Embedding Upgrade (UNCHANGED — Already Addressed)
- Embedding model + version stored with each fact.
- Re-indexing tool provided.
- At startup, validate configured model against newest rows.

---

## Key Design Constraints (Refined)

**1. Temporal Validity is the Only Versioning Primitive**  
Every state change — supersession, correction, archival, expiry — is expressed as
setting `valid_until`. No other versioning mechanism exists. This is the invariant
that makes the schema simple and the logic predictable.

**2. Hybrid Retrieval is Non-Negotiable**  
Embedding retrieval alone is blind to negation. BM25 retrieval alone misses paraphrases.
Entity-based lookup handles exact structured matches. All three are required for
comprehensive conflict candidate generation.

**3. Detection is Decoupled from the Write Path**  
Conflict detection is always async. The committing agent never waits for detection.
This is the only design choice that keeps SQLite viable as the storage backend.

**4. NLI is a Signal, Not a Verdict**  
For technical codebase facts, domain-specific rules (entity exact-match, numeric
comparison) produce higher-confidence determinations than a general-domain NLI model.
NLI fills the gap for natural language semantic contradictions. Its threshold is
calibrated, not fixed.

**5. Complexity Budget: Prefer Deletion**  
Every component added to Engram must either remove another component (generalization)
or address a documented failure mode. The Round 3 rewrite removed 4 components
(BFT, graph DB, quorum commits, `facts_archive` table) and replaced 4 mechanisms
with 1 temporal invariant.

---

## What Engram Is Not Building

- **Parametric memory:** No weight updates to the LLMs it interacts with.
- **Cache-level protocols:** No sharing of LLM KV caches.
- **Graph traversal:** Entity relationships are tracked in JSON, not a graph database.
- **Full adversarial security:** BFT and quorum commits are not implemented.
  Engram protects against accidental inconsistency; a determined attacker with write
  access can still poison the store.
- **RL-driven memory management:** Out of scope.
- **Multimodal memory:** Text facts only in v1.
- **General agent orchestration:** Letta, Agent-MCP handle this. Engram is the
  consistency layer only.

### Strategic Positioning

Engram is a **consistency layer** that sits on top of existing shared memory systems.
Long-term: other systems store and retrieve; Engram asks "are these facts coherent?"
This complementary positioning keeps the implementation focused on the one thing no
other system does, and makes Engram composable with the existing ecosystem.

### What the MCP Ecosystem Taught Us (Round 4)

The successful MCP servers (Context7, GitHub MCP, Playwright MCP) and the broader AAIF
ecosystem (MCP + AGENTS.md + Goose, all now under the Linux Foundation) share patterns
that Engram adopts:

**1. Solve one problem exceptionally well.**
Context7 does documentation freshness. GitHub MCP does repo management. Engram does
consistency. No feature creep. The AAIF's standardization of MCP, AGENTS.md, and Goose
as three separate, complementary projects — not one monolith — validates this positioning.

**2. Minimal tool surface (empirically enforced).**
Context7 has 2 tools. Engram has 4. Research and production experience shows LLM
tool-selection accuracy degrades significantly when exposed to >30-40 tools. Block's
principle: "connecting too many servers causes agents to send every tool description
with every prompt, consuming the context window." Engram's 4-tool surface is the
correct answer — not a limitation.

**3. Tool descriptions are executable LLM prompts.**
The LLM selects tools based *solely* on names, descriptions, and schemas. Every
Engram tool description embeds: (a) what state the agent should be in before calling
it, (b) what it returns and how to interpret it, (c) rate-limit and error-handling
guidance. This is behavioral guidance, not documentation. Round 4 security finding:
tool descriptions can also be the attack vector (see Failure Mode 9).

**4. Block's "Discovery → Planning → Execution" pattern.**
Block learned (from 60+ internal MCP servers) not to expose granular API calls directly.
Instead: a discovery tool reveals what's available, a planning tool determines the
necessary steps, and execution tools perform the operations. Engram's tool surface maps
naturally: `engram_query` = Discovery, `engram_commit` = Execution, `engram_conflicts`
+ `engram_resolve` = Planning and execution of fixes. This pattern was validated at scale.

**5. Context7's sub-agent filtering as a model for `engram_query`.**
Context7's late-2025 architectural shift: add a filtering sub-layer that selects and
injects only the most relevant, high-precision snippets rather than dumping raw data.
This reduced token usage while improving accuracy. Engram's `engram_query` already does
this: RRF scoring + server-side filtering returns 10 scored facts, not all 10,000.
The lesson: never return raw data when pre-ranked answers will do.

**6. Server-side intelligence, not client-side computation.**
NLI scoring, BM25 ranking, entity extraction, embedding generation — all happen on the
Engram server. The agent receives `[fact_text, has_conflict: bool, conflict_severity: str]`
tuples, not raw embeddings or scores to interpret. The LLM does reasoning; Engram does
data pipeline work.

**7. AGENTS.md as a first-class integration target.**
OpenAI's AGENTS.md standard, now under the Linux Foundation, is a markdown-based
convention that acts as a "README for AI agents" — project-specific guidance that coding
agents consume at session start. Engram should provide a reference AGENTS.md template
that tells coding agents: what Engram is, when to call `engram_commit` (after discovering
a codebase fact, not after every thought), what constitutes a well-formed fact, and how
to interpret `has_open_conflict` in query results. This is zero-cost distribution: a
template in the docs that users drop into their repos.

**8. Zero-setup deployment.**
One line of JSON config for local use. `uvx engram-mcp` downloads and runs. No Docker,
no database setup, no API keys for core features. Google's managed remote MCP model
(fully-hosted endpoints for BigQuery, Google Maps) shows the aspirational end state:
team deployment without any server management. Engram's path: `stdio` → `uvx` →
Streamable HTTP remote → (future) managed cloud endpoint. Each step removes friction.

---

## AGENTS.md Reference Template

The following is a reference AGENTS.md template that teams should add to their repos
when running Engram:

```markdown
# Engram — Shared Knowledge Consistency

Engram is a consistency layer for agent-shared facts. It detects contradictions between
facts committed by different agents working on this codebase.

## When to commit a fact
Call `engram_commit` when you discover or verify something concrete about this codebase:
- A service's rate limit, throughput, or SLA
- A configuration value, secret name, or environment variable
- A dependency version or compatibility constraint
- An architectural decision that other agents need to know

Do NOT commit every thought, conclusion, or inference. Commit facts that other agents
would need to do their work correctly.

## Interpreting query results
If `has_open_conflict: true` is returned for a fact, two agents have committed
contradictory information. Do not act on a contested fact without calling
`engram_conflicts` to understand the disagreement.

## Scope convention for this repo
- `auth/*` — authentication service, JWT, sessions
- `payments/*` — payment processing, webhooks, billing
- `infra/*` — database, cache, queue configuration
- `api/*` — public API contracts, rate limits, versioning
```

This template ships as `docs/AGENTS.md.template` in the Engram repository. Teams
customize it for their scope hierarchy.
