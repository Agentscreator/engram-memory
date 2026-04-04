# Engram Implementation Plan

This plan is grounded in the papers in [`./papers/`](./papers/), the adversarial literature
review in [`LITERATURE.md`](./LITERATURE.md), and a deep study of the protocols and MCP
servers that have achieved real production adoption across every major platform.

Five rounds of research shaped the architecture:

- **Round 1** exposed embedding retrieval failures and LLM-as-judge agreeableness bias.
- **Round 2** replaced the LLM-only pipeline with a tiered NLI approach, cutting latency 200×.
- **Round 3** found seven structural failure modes and collapsed four versioning mechanisms
  into one invariant: *temporal validity intervals*. BFT, graph database, and quorum commits
  removed as premature complexity.
- **Round 5** addressed regex entity extraction recall failure and cross-scope detection
  blind spots.
- **Round 6** — an adversarial external review — falsified latency claims, identified the
  MINJA memory injection threat model, replaced `rank_bm25` with SQLite FTS5, corrected
  NLI model sizing for CPU deployment, added fact expiry (TTL), secret detection, provenance
  tracking, and fact typing. It also identified Turso/libSQL as the v2 storage upgrade path
  and recalibrated the competitive landscape against Mem0, Cipher, SAMEP, and Agent KB.
- **Round 7** — MemFactory (arXiv 2603.29493, Guo et al., 2026) — introduced explicit CRUD
  memory operations (ADD/UPDATE/DEL/NONE) and a semantic auto-updater. This replaced implicit
  "agents track lineage IDs manually" with a first-class `operation` parameter on `engram_commit`,
  and added a schema-level audit trail (`memory_op`, `supersedes_fact_id`) for every lifecycle
  operation. Schema advanced to version 3.

A fourth input — the live MCP ecosystem — shaped the tool surface, transport, security,
and deployment model. This includes:

- **Linux Foundation / AAIF:** MCP donated to the Agentic AI Foundation (Dec 2025).
  Platinum members: AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft,
  OpenAI. Gold: Cisco, Datadog, IBM, Oracle, Salesforce, SAP, Shopify, Snowflake.
  Three founding projects: MCP (connectivity), goose (execution runtime), AGENTS.md
  (repository-level agent guidance). 97M cumulative SDK downloads. 13k+ servers on GitHub.
- **Microsoft:** Azure MCP Server (Cosmos DB, Storage, Monitor, App Config, Resource Groups,
  Azure CLI, azd). Playwright MCP (15k stars, accessibility-snapshot-based browser
  automation). OWASP MCP Top 10 security guide. Enterprise deployment architecture:
  remote HTTP servers behind Azure API Management gateway with Entra ID auth, centralized
  policy enforcement, and comprehensive monitoring. Key lesson: *stdio for prototyping,
  HTTP for production*.
- **Google:** Managed remote MCP servers for AlloyDB, Spanner, Cloud SQL, Firestore,
  Bigtable, BigQuery, Google Maps. Zero infrastructure deployment — configure endpoint,
  get enterprise-grade auditing/observability/governance. IAM-based auth (no shared keys).
  Every query logged in Cloud Audit Logs. MCP Toolbox for Databases (open-source).
  Key lesson: *identity-first security, full observability, managed infrastructure*.
- **Apple:** MCP support coming to macOS Tahoe 26.1, iOS 26.1, iPadOS 26.1 via App Intents
  framework integration. System-level MCP lets developers expose app actions to any
  MCP-compatible AI agent. Key lesson: *MCP is becoming an OS-level primitive, not just
  a developer tool*.
- **Block:** goose agent framework (open-source, AAIF founding project). 60+ internal MCP
  servers. Published playbook: design top-down from workflows, tool descriptions are LLM
  prompts, token budget management, actionable error messages. Key lesson: *fewer tools,
  richer descriptions, server-side intelligence*.
- **OpenAI:** AGENTS.md standard (AAIF founding project). A README for AI agents — project
  build instructions, coding conventions, testing policies, security rules in Markdown.
  20k+ repos adopted. Supported by Codex, Cursor, Google Jules, Amp, Factory. Key lesson:
  *agents need repository-level context alongside tool access*.
- **Context7 (Upstash):** 44k stars, 240k weekly npm downloads. Two tools only. Server-side
  reranking cut tokens 65%, latency 38%. Behavioral guidance embedded in tool descriptions.
  Zero-setup deployment. Privacy by design. Key lesson: *solve one problem exceptionally
  well with minimal surface area*.

The pattern is consistent across every platform: minimal tool count, rich descriptions
that guide LLM behavior, server-side intelligence, zero-setup local deployment, remote
HTTP for production, identity-first security, full observability, and privacy by design.

---

## Unifying Insight: Every Fact Has a Validity Window

The simplest possible correct model for a changing knowledge base is:

```
fact(id, content, valid_from, valid_until, ...)
```

A fact is **current** when `NOW() ∈ [valid_from, valid_until)`.  
A fact is **superseded** when `valid_until IS NOT NULL`.  
A fact is **archived** when `valid_until` is old enough.  
A fact is **expired** when `valid_until` was set by TTL, not by supersession.  
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
│            I/O Layer (MCP)               │  ← agents connect here (stdio)
│  engram_status / engram_init /           │
│  engram_join / engram_commit /           │
│  engram_query / engram_conflicts /       │
│  engram_resolve                          │
├──────────────────────────────────────────┤
│        Commit Pipeline                   │  ← inline, <10ms
│  Secret scan → dedup → entity extract →  │
│  provenance check → insert → queue       │
├──────────────────────────────────────────┤
│          Detection Layer                 │  ← runs asynchronously
│  Tier 0: hash dedup + entity exact-match │
│  Tier 1: NLI cross-encoder (local)       │
│  Tier 2: numeric/temporal rules          │
│  Tier 2b: cross-scope entity detection   │
│  Tier 3: LLM escalation (rare)           │
├──────────────────────────────────────────┤
│          Storage Layer                   │  ← durable append-only log
│  Local mode: SQLite (~/.engram/)         │
│  Team mode:  PostgreSQL (ENGRAM_DB_URL)  │
│  facts, conflicts, agents, workspaces,   │
│  scope_permissions, detection_feedback   │
│  Full-text: FTS5 (local) / tsvector (pg) │
│  Vectors:   numpy BLOB / pgvector        │
└──────────────────────────────────────────┘

Workspace config: ~/.engram/workspace.json
  {engram_id, db_url, anonymous_mode, anon_agents}
  Written once by engram_init or engram_join.
  All subsequent sessions connect silently.
```

Conflict detection runs **outside the write path**. Every `engram_commit` returns
immediately; detection happens in a background worker. On CPU (the default deployment),
detection completes in 2–10 seconds depending on candidate set size and NLI model
choice. On GPU, detection completes in <500ms. This is acceptable because detection
is fully async — it does not block the committing agent.

This eliminates the SQLite write-lock contention that the Round 3 analysis identified
as an existential bottleneck.

---

## Competitive Landscape and Strategic Positioning

The window for "only system doing consistency" is narrowing. The plan must be explicit
about where Engram sits relative to converging competitors:

- **Mem0** (38k+ GitHub stars) now addresses multi-agent memory with four scoping
  dimensions (user, session, agent, application). Their March 2026 blog post directly
  discusses "agents duplicating and contradicting each other's work." They don't have
  conflict *detection*, but they're framing the same problem.
- **Cipher (Byterover)** ships team-level memory sharing across IDEs with real-time
  sync. No conflict detection, but the shared memory layer is production-ready.
- **SAMEP** ([arxiv 2507.10562](https://arxiv.org/abs/2507.10562)) proposes a formal
  protocol for secure agent memory exchange with cryptographic access controls
  (AES-256-GCM) and MCP/A2A compatibility.
- **Agent KB** (ICML 2025) provides cross-domain experience sharing with hybrid
  retrieval — structurally similar to `engram_query`.

**Engram's moat is the conflict detection pipeline (Tiers 0–3), not the shared memory
layer itself.** If Engram ships Phases 1–2 without Phase 3, it is just another shared
memory MCP server in a crowded field. Phase 3 must be prioritized as the defensible
differentiator. The delivery sequence reflects this: Phases 1–3 are the minimum viable
product, and Phase 3 is the reason Engram exists.

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
    provenance: str | None = None,
    fact_type: str = "observation",
    ttl_days: int | None = None,
    operation: str = "add",  # "add" | "update" | "delete" | "none"
) -> dict:
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
    - agent_id: Your agent identifier. Auto-generated if omitted.
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
    - operation: Memory CRUD intent (MemFactory pattern). One of:
        "add"    (default) — new independent fact.
        "update" — supersede an outdated fact. If corrects_lineage is
                   omitted, the engine automatically finds the most
                   semantically similar active fact in scope (cosine
                   similarity ≥ 0.75) and supersedes it.
        "delete" — retire an existing lineage without replacement.
                   Requires corrects_lineage.
        "none"   — no-op; signals the agent has nothing new to add.

    Returns: {fact_id, committed_at, duplicate, conflicts_detected,
              memory_op, supersedes_fact_id}
    """
```

```python
@mcp.tool
def engram_query(
    topic: str,
    scope: str | None = None,
    limit: int = 10,
    as_of: str | None = None,
    fact_type: str | None = None,
) -> list[dict]:
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

    Returns: List of claims with content, scope, confidence, agent_id,
    committed_at, has_open_conflict, verified, fact_type, and provenance
    metadata.
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
  re-rank or filter. Each result includes a relevance score, conflict flag, verification
  status, and fact type.
- `engram_conflicts` returns conflicts pre-grouped by scope and pre-sorted by severity.
  The LLM gets an actionable queue, not raw data.
- `engram_commit` performs secret scanning, dedup, entity extraction, and conflict
  detection server-side. The LLM just provides the raw claim text.

Token budget: `engram_query` responses are capped at ~4000 tokens (10 claims × ~400
tokens each). If a claim is too long, it is truncated server-side with a note. This
follows Block's guidance: *"Check byte size or estimate token count before returning
text."*

### Transport and Deployment

**Transport:** Engram supports both stdio (for local use with Claude Desktop, Cursor,
Kiro) and Streamable HTTP (for team/remote deployment). Streamable HTTP replaced SSE
in the MCP 2025-03-26 spec and is the recommended transport for remote servers.

**Local deployment (solo developer):**
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

No database setup. No Docker. The server creates `~/.engram/knowledge.db` on first run.
This follows Context7's lesson: *"Every additional setup step is a point where potential
users drop off."*

**Team deployment (shared database):**
```json
{
  "mcpServers": {
    "engram": {
      "command": "uvx",
      "args": ["engram-mcp@latest"],
      "env": { "ENGRAM_DB_URL": "postgres://..." }
    }
  }
}
```

Same MCP config structure. No HTTP server. No Docker. No firewall rules. The agent runs
`engram_status()` on first use and walks the user through `engram_init` or `engram_join`.
The database connection string is the only thing that needs to be distributed — and
the agent tells the user exactly where to put it.

Every team member brings their own database URL pointing at the same PostgreSQL instance.
The invite key proves workspace membership; the connection string provides database access.
These are two separate concerns: *what workspace* vs *how to reach the data*.

### Privacy by Design

Following Context7's model: agent code never leaves the local machine. `engram_commit`
receives only the claim text the agent explicitly provides. `engram_query` receives
only the topic string. The NLI model and embedding model run locally. The only external
call is Tier 3 LLM escalation (optional, for ambiguous cases), and even that sends
only the two claim texts being compared — never the agent's code or conversation.

**Deterministic secret detection (Round 6):** The tool description says "do not include
secrets," but relying on the LLM to follow this instruction is insufficient.
[AMP (ICML 2026)](https://proceedings.mlr.press/v317/wu26a.html) demonstrates that
privacy guarantees require deterministic enforcement, not advisory prompts. Engram runs
a lightweight regex scanner on `content` at commit time to detect common secret patterns
(API keys, JWT tokens, connection strings, AWS credentials). If detected, the commit is
rejected with an actionable error message identifying the pattern. This is a ~1ms check
that prevents the most common accidental secret leakage.

---

## Phase 0 — Agent-Native Onboarding

**Goal:** Every interaction with Engram goes through the agent. No CLI wizards, no docs
to read, no JSON to edit. The agent asks the questions and handles the setup.

### The Core Principle

Engram never owns your data. You bring a PostgreSQL database connection string. Engram
provides the schema, the conflict detection logic, and the MCP tools. The database lives
wherever you want it — any PostgreSQL-compatible provider, or self-hosted.

Local mode (no `ENGRAM_DB_URL`) continues to work with SQLite for solo developers who
don't need team sharing.

### Workspace Config

On first run, Engram looks for `~/.engram/workspace.json`:

```json
{
  "engram_id": "ENG-X7K2-P9M4",
  "db_url": "postgres://...",
  "anonymous_mode": false,
  "anon_agents": false
}
```

If this file does not exist and `ENGRAM_DB_URL` is not set, Engram is in **local mode**
(SQLite). If `ENGRAM_DB_URL` is set but no workspace.json exists, `engram_status` guides
the agent through `engram_init`. If workspace.json exists, the agent connects silently.

### Three New MCP Tools

**`engram_status()`** — the entry point. Called by the agent on first use (or any time
the agent needs to know the current state). Returns the current setup state and the exact
string the agent should say to the user next.

```python
# Example responses:
{
  "status": "unconfigured",
  "next_prompt": "Do you have a Team ID to join an existing workspace, or are you setting up a new one?"
}

{
  "status": "awaiting_db",
  "next_prompt": "Add your database connection string to your environment before we continue:\n\n  export ENGRAM_DB_URL='postgres://...'\n\nYou can get a free PostgreSQL database at neon.tech, supabase.com, railway.app, or use any self-hosted instance. Tell me when it's set."
}

{
  "status": "ready",
  "engram_id": "ENG-X7K2-P9M4",
  "workspace": "~/.engram/workspace.json"
}
```

**`engram_init()`** — called by the agent when the user is setting up a new workspace.
Requires `ENGRAM_DB_URL` to be set. Runs schema setup, generates a Team ID and invite
key, writes workspace.json, and asks the user their privacy preferences.

The invite key is a signed, encrypted token with the database URL embedded inside it.
Teammates never see or handle the raw connection string — it is extracted and written
to their workspace.json automatically when they call `engram_join`.

```python
# Invite key payload (encrypted + HMAC-signed, never shown in plaintext):
{
  "engram_id": "ENG-X7K2-P9M4",
  "db_url": "postgres://...",   # extracted silently by engram_join
  "expires_at": "2026-07-01",
  "uses_remaining": 10          # None = unlimited
}

# Response to agent:
{
  "status": "initialized",
  "engram_id": "ENG-X7K2-P9M4",
  "invite_key": "ek_live_abc123...",
  "next_prompt": "Your team workspace is ready.\n\nShare with teammates:\n  Team ID:    ENG-X7K2-P9M4\n  Invite Key: ek_live_abc123\n\nThat's all they need. Should commits show who made them, or stay anonymous?"
}
```

**`engram_join(invite_key)`** — called by the agent when a teammate is joining an
existing workspace. The invite key is the only input — no Team ID required. Decrypts
the invite key, extracts both the workspace ID and the database URL, validates
workspace membership, and writes workspace.json. The teammate never provides or sees
the database connection string or Team ID — everything is contained within the invite key.

```python
# Response:
{
  "status": "joined",
  "engram_id": "ENG-X7K2-P9M4",
  "next_prompt": "You're in. I'll query team memory before starting work on anything."
}
```

### The Agent-Driven Conversation

The MCP server `instructions` field tells the agent its behavioral contract:

```
On first use, call engram_status(). Read the 'next_prompt' field in every response
and say it to the user. This is how Engram guides setup — follow each prompt in
sequence. Once status is 'ready', query before every task and commit discoveries after.
```

The agent IS the UX. No dashboard, no setup wizard, no documentation required.

### Privacy: Two Decisions, Made Once

Both are asked by the agent during `engram_init`, stored in the workspace, and never
asked again. Both are **enforced server-side** — stripping happens on INSERT, not on
the client.

**Attribution (anonymous_mode):**
> "Should commits show who made them? Yes = your identifier appears on discoveries.
> No = all commits are anonymous. The server enforces this — your name is stripped
> before storage even if the agent sends it."

**Agent identity (anon_agents):**
> "Should agent identifiers be stored? Yes = tracks which agent made each commit
> (useful for debugging conflicts). No = agent IDs are randomized each session."

These become `anonymous_mode` and `anon_agents` booleans in the `workspaces` table.

### Complete Flow

```
Install:  pip install engram-mcp
Config:   Add to MCP client (stdio, uvx engram-mcp@latest)

┌─ First session (founder — one time only) ──────────────────────┐
│  Agent calls engram_status()                                    │
│  → "Do you have an Invite Key or are you setting up new?"      │
│  User: "New"                                                    │
│  → "Add ENGRAM_DB_URL to your environment. Tell me when set."  │
│  [Only person who ever touches a database string]              │
│  User sets env var, restarts agent                             │
│  Agent calls engram_init()                                      │
│  → db_url + workspace_id encrypted into invite key             │
│  → "Anonymous commits or named?"                               │
│  User answers. workspace.json written.                          │
│  → "Share with teammates via iMessage, WhatsApp, etc:           │
│     Invite Key: ek_live_abc123"                                 │
└─────────────────────────────────────────────────────────────────┘

┌─ First session (teammate — one string) ────────────────────────┐
│  Agent calls engram_status()                                    │
│  → "Do you have an Invite Key or are you setting up new?"      │
│  User: "Join"                                                   │
│  → "What's your Invite Key?"                                    │
│  Agent calls engram_join(invite_key)                            │
│  → workspace_id + db_url decrypted silently                     │
│  → workspace.json written                                       │
│  → "You're in."                                                 │
│  [One string. No Team ID. No database URL. No configuration.]  │
└─────────────────────────────────────────────────────────────────┘

┌─ Every session thereafter ─────────────────────────────────────┐
│  workspace.json exists → agent connects silently                │
│  engram_query before every task                                 │
│  engram_commit after every discovery                            │
│  No prompts. No setup. Invisible.                               │
└─────────────────────────────────────────────────────────────────┘
```

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
    fact_type        TEXT NOT NULL DEFAULT 'observation',  -- observation | inference | decision
    agent_id         TEXT NOT NULL,
    engineer         TEXT,
    provenance       TEXT,               -- optional evidence trail (file path, test output, etc.)
    keywords         TEXT,               -- JSON array
    entities         TEXT,               -- JSON array: {name, type, value}
    artifact_hash    TEXT,               -- optional SHA-256 of referenced file/config at commit time
    embedding        BLOB,               -- float32, serialized numpy
    embedding_model  TEXT NOT NULL,      -- "all-MiniLM-L6-v2"
    embedding_ver    TEXT NOT NULL,      -- semver of sentence-transformers
    committed_at     TEXT NOT NULL,      -- ISO 8601
    valid_from       TEXT NOT NULL,      -- ISO 8601 (= committed_at for new facts)
    valid_until      TEXT,              -- NULL = currently valid; set when superseded or expired
    ttl_days         INTEGER,           -- optional; when set, valid_until = valid_from + ttl_days
    memory_op        TEXT NOT NULL DEFAULT 'add',  -- CRUD intent: add | update | delete | none
    supersedes_fact_id TEXT             -- fact_id closed by this update/delete operation (audit trail)
);

-- Validity window is the primary query filter
CREATE INDEX idx_facts_validity     ON facts(scope, valid_until);
CREATE INDEX idx_facts_content_hash ON facts(content_hash);
CREATE INDEX idx_facts_lineage      ON facts(lineage_id);
CREATE INDEX idx_facts_agent        ON facts(agent_id);
CREATE INDEX idx_facts_type         ON facts(fact_type);

-- FTS5 virtual table for lexical retrieval (replaces rank_bm25 dependency)
CREATE VIRTUAL TABLE facts_fts USING fts5(
    content, scope, keywords,
    content=facts, content_rowid=rowid
);
```

**New columns from Round 6:**

| Column | Source | Purpose |
|---|---|---|
| `fact_type` | Cipher's System 1/2 model | Distinguishes observations, inferences, and decisions. Enables richer query filtering and differential conflict weighting. |
| `provenance` | MINJA threat model, SEDM | Evidence trail for auditability. Facts with provenance are marked `verified` in query results. |
| `artifact_hash` | SEDM's verifiable write admission | SHA-256 of the referenced file/config at commit time. Enables staleness detection on query. |
| `ttl_days` | Round 6 expiry analysis | Automatic fact expiry. When set, a background job sets `valid_until = valid_from + ttl_days`. |

**New columns from Round 7 (MemFactory):**

| Column | Source | Purpose |
|---|---|---|
| `memory_op` | MemFactory CRUD pattern (Memory-R1) | Stores the explicit intent of each commit: `add`, `update`, `delete`, or `none`. Enables lifecycle auditing and downstream analysis of memory update patterns. |
| `supersedes_fact_id` | MemFactory semantic Updater | Records which specific fact was closed by an `update` or `delete` operation. Provides a direct audit link between new and superseded facts, beyond the lineage chain alone. |

**Why `valid_until` replaces all Round 2 versioning machinery:**

| Round 2 mechanism | Round 3+ equivalent |
|---|---|
| `superseded_by TEXT` pointer | `valid_until = now()` on the old fact |
| `facts_archive` table | `WHERE valid_until < ARCHIVE_CUTOFF` |
| `utility_score REAL` decay field | `DATEDIFF(now(), valid_from) > THRESHOLD` |
| Version chain via `superseded_by` | `WHERE lineage_id = X ORDER BY valid_from` |
| *(none — Round 6)* | `valid_until = valid_from + ttl_days` for TTL expiry |

Five separate mechanisms → one temporal predicate.

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
    detection_tier   TEXT NOT NULL,  -- "tier0_entity" | "tier1_nli" | "tier2_numeric" | "tier2b_cross_scope" | "tier3_llm"
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

False-positive feedback from `engram_resolve(resolution_type="dismissed")` feeds a
local calibration file that adjusts the NLI threshold over time. This addresses the
calibration failure mode identified in Round 3.

### Workspace Table (Phase 0)

```sql
CREATE TABLE workspaces (
    engram_id        TEXT PRIMARY KEY,   -- e.g. "ENG-X7K2-P9M4"
    created_at       TEXT NOT NULL,
    anonymous_mode   INTEGER NOT NULL DEFAULT 0,  -- 1 = strip engineer on INSERT
    anon_agents      INTEGER NOT NULL DEFAULT 0   -- 1 = randomize agent_id per session
);

CREATE TABLE invite_keys (
    key_hash         TEXT PRIMARY KEY,   -- SHA-256 of the raw invite key
    engram_id        TEXT NOT NULL REFERENCES workspaces(engram_id),
    created_at       TEXT NOT NULL,
    expires_at       TEXT,               -- NULL = no expiry
    uses_remaining   INTEGER             -- NULL = unlimited
    -- db_url is NOT stored here — it is encrypted into the invite key token itself
    -- so the database never contains plaintext credentials in the invite_keys table
);
```

All other tables gain a `workspace_id TEXT NOT NULL` column (populated at init time,
defaults to `'local'` in SQLite mode). This is the namespace: one database can host
multiple teams.

### Scope Permissions

```sql
CREATE TABLE scope_permissions (
    agent_id    TEXT NOT NULL,
    scope       TEXT NOT NULL,
    can_read    BOOLEAN NOT NULL DEFAULT TRUE,
    can_write   BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from  TEXT,              -- NULL = always valid (Round 6: temporal permissions)
    valid_until TEXT,              -- NULL = no expiry
    PRIMARY KEY (agent_id, scope)
);
```

Hierarchical scope matching: `payments/webhooks` inherits from `payments`. Default
(no row): full access.

**Temporal permissions (Round 6):** Inspired by [Collaborative Memory
(OpenReview, 2025)](https://openreview.net/forum?id=pJUQ5YA98Z), scope permissions
carry the same `valid_from`/`valid_until` temporal primitive as facts. An agent might
have write access to `payments/*` only during a specific sprint or deployment window.
This reuses the existing temporal model — no new abstraction needed.

---

## Phase 2 — Core MCP Server

**Goal:** A working MCP server that commits and queries facts. No conflict detection yet.

### Stack

| Dependency | Purpose | Why this and not X |
|---|---|---|
| `mcp` SDK (includes FastMCP) | MCP server | Standard; supports stdio and Streamable HTTP |
| `aiosqlite` | Local mode (solo dev) | WAL mode + async = correct for single-machine use |
| `asyncpg` | Team mode (ENGRAM_DB_URL set) | Fast PostgreSQL async driver; replaces aiosqlite when DB URL present |
| `sentence-transformers` | Embeddings + NLI | Local, no API key |
| `numpy` | Cosine similarity (local mode) | No extra dep |
| `pgvector` | Vector similarity (team mode) | Native PostgreSQL vector index; replaces numpy cosine at scale |
| `datasketch` | MinHash for entity dedup | Replaces LLM-only entity resolution |
| small NER model (e.g. `dslim/bert-base-NER`) | Entity extraction fallback | Catches what regex misses; ~50ms, local |

**Dual storage backend:** `Storage` is an abstract interface. `SQLiteStorage` handles
local mode; `PostgresStorage` handles team mode. The engine, server, and MCP tools call
the interface — they have no knowledge of which backend is active. Backend selection
happens at startup by checking for `ENGRAM_DB_URL` (or reading workspace.json).

**PostgreSQL migration notes:**
- `?` placeholders → `$1, $2, ...` (asyncpg syntax)
- `json_each()` / `json_extract()` → `jsonb @>` operators and `->>`
- FTS5 virtual table → `tsvector` column + `GIN` index + `to_tsquery()`
- `BLOB` embeddings → `vector` type (pgvector extension)
- `PRAGMA journal_mode=WAL` → not needed (PostgreSQL MVCC handles this natively)

**Schema isolation (security & organization):**

Engram creates all tables in a dedicated PostgreSQL schema (default: `engram`), enabling
teams to use their existing application database without table name conflicts. This
addresses two critical concerns:

1. **Security:** Database credentials are configured via environment variables or `.env`
   files, never pasted in chat. The agent guides users to set `ENGRAM_DB_URL` outside
   of the conversation, eliminating credential exposure in chat history.

2. **Isolation:** All Engram tables live in a separate schema namespace. A team can
   point `ENGRAM_DB_URL` at their production database and Engram will create:
   ```sql
   CREATE SCHEMA IF NOT EXISTS engram;
   SET search_path TO engram, public;
   -- All tables created in engram schema
   ```
   This provides:
   - Zero table name conflicts with application tables
   - Easy backup/restore of just Engram data: `pg_dump -n engram`
   - Clear organizational separation
   - Single database connection for both app and Engram

The schema name is configurable via `ENGRAM_SCHEMA` environment variable or the `schema`
parameter in `engram_init()`. The workspace config stores the schema name:

```json
{
  "engram_id": "ENG-X7K2-P9M4",
  "db_url": "postgres://...",
  "schema": "engram",
  "anonymous_mode": false,
  "anon_agents": false
}
```

Invite keys include the schema name in their encrypted payload, so teammates joining
via `engram_join()` automatically use the correct schema without manual configuration.

**Backward compatibility:** Existing installations without schema isolation continue to
work (tables in public schema). Old invite keys without `schema` default to `"engram"`.

See [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) for security best practices and
[MIGRATION_SCHEMA.md](./MIGRATION_SCHEMA.md) for migration instructions.

**Round 6 change: `rank_bm25` removed.** SQLite FTS5 provides BM25 ranking natively
in C, requires zero additional dependencies, and integrates with the existing storage
layer. The `facts_fts` virtual table replaces the Python-level BM25 library entirely.
In PostgreSQL team mode, `tsvector` + `ts_rank` provides equivalent functionality.

**Transport:** `stdio` is the transport for both local and team mode. Team sharing is
achieved through the shared PostgreSQL database — not through an HTTP server that all
engineers must reach. This eliminates the need for port forwarding, firewall rules, or
"always-on" infrastructure. The MCP config is identical for solo and team use:

```json
{
  "mcpServers": {
    "engram": {
      "command": "uvx",
      "args": ["engram-mcp@latest"],
      "env": {
        "ENGRAM_DB_URL": "postgres://..."
      }
    }
  }
}
```

Or with the env var set at the shell level, the config stays exactly as it is for local
mode — the server detects the env var at startup and switches backends automatically.

Streamable HTTP remains available for dashboard access and federation endpoints, but
is no longer required for team collaboration. The legacy `HTTP+SSE` transport
(2024-11-05 spec) is deprecated by the MCP spec; Engram will not implement it.

FastMCP is now integrated into the official `mcp` Python SDK. Engram uses the `@mcp.tool`
decorator pattern for tool registration, following the same pattern as Context7 and other
production MCP servers. Tool descriptions follow the behavioral guidance pattern described
in §MCP Tool Design.

**No graph database.** SQLite + the `entities` JSON column provides all the structured
lookup needed. Graph databases add operational burden for no capability advantage within
Engram's v1 scope. See §MCP Tool Design for the rationale: Engram is a consistency layer,
not a knowledge graph. **Note (Round 6):** This stance is correct for v1 but not absolute.
If federation (Phase 6) scales beyond ~10 teams or ~100k facts, traversal queries
("which agents' facts influenced this decision?", "show the correction chain for this
lineage") become expensive in SQL. At that scale, a lightweight embedded graph layer
(e.g., [Kùzu](https://kuzudb.com/)) may become justified. This is a v2+ consideration.

**No BFT.** Engram serves a permissioned team. Crash fault tolerance via SQLite WAL is
sufficient.

**SQLite concurrency strategy:**
- WAL mode: `PRAGMA journal_mode=WAL` (readers never block writers)
- Busy timeout: `PRAGMA busy_timeout=5000`
- Conflict detection runs in a **background thread**, holding no write lock during
  NLI inference. The inference result is written in a single short transaction.
- Write lock is held only for the duration of the `INSERT INTO facts` statement
  (~1ms), not for the NLI scan. This is the structural fix for the Round 3
  bottleneck: decouple inference from the write path.

**v2 storage upgrade path (Round 6):** [Turso](https://turso.tech/) (Rust rewrite of
SQLite with MVCC) now supports concurrent writes, achieving 4x write throughput over
vanilla SQLite and eliminating `SQLITE_BUSY` errors entirely. It is wire-compatible
with SQLite, supports the same SQL dialect, and adds concurrent writes via MVCC,
built-in vector search, Change Data Capture (useful for federation), and edge
replication. For v1, SQLite WAL + async detection is safer and simpler. For team mode
in v2, Turso is the natural upgrade: `pip install engram-mcp[team]`. The schema is
identical; only the connection layer changes.

**Embedding model consistency (Round 6):** In team mode, the server is the single
source of all embeddings — both at commit time and query time. This eliminates the
risk of different engineers running different `sentence-transformers` versions and
producing incompatible embeddings. In local mode, embedding version mismatches are
detected at startup by comparing the configured model against the newest stored rows,
and flagged with a warning.

### `engram_commit` Pipeline

0. **Resolve `operation`** — one of `add`, `update`, `delete`, `none` (MemFactory CRUD pattern):
   - `none`: return immediately, no write.
   - `delete`: close the lineage specified by `corrects_lineage`, no new fact inserted.
   - `update` / `add`: continue with steps 1–13.
1. **Validate inputs** (Pydantic)
2. **Secret scan (<1ms):** Regex scanner checks `content` for common secret patterns
   (API keys, JWT tokens, AWS credentials, connection strings). If detected, reject
   with an actionable error: `"Commit rejected: content appears to contain an API key
   (pattern: sk-...). Remove secrets before committing."` This is deterministic
   enforcement, not advisory.
3. **Compute `content_hash`** (SHA-256 of lowercased, whitespace-normalized content)
4. **Dedup check:** `SELECT id FROM facts WHERE content_hash = ? AND valid_until IS NULL AND scope = ?`.
   If found, return `{fact_id: existing_id, duplicate: true}`. O(1) — no model inference.
5. **Generate embedding** for `content`
6. **Extract `keywords` and `entities`** via a hybrid extraction pipeline.
   Entity extraction is the foundation of Tier 0 detection and must have high recall.
   
   **Why regex alone is insufficient:** Natural language codebase facts use varied
   phrasing: "about a thousand requests per second," "1k/s," "bumped from 30 to 60
   seconds," "doesn't use rate limiting." Regex catches clean patterns like
   `\d+\s*req/s` but misses written-out numbers, abbreviations, multi-value sentences,
   and negation of entity existence. Low entity recall means Tier 0 fires rarely, and
   the system silently falls through to NLI for contradictions that should have been
   caught deterministically.
   
   **Hybrid extraction (ordered by cost):**
   
   a. **Regex pass (< 1ms):** Extract obvious patterns — bare numbers with units
      (`100 req/s`, `v3.2.1`, `port 5432`), ALL_CAPS identifiers (`AUTH_RATE_LIMIT`,
      `JWT_SECRET`), and known service name patterns. Regex is the fast first pass;
      the NER model is the primary extractor. No unsupported recall claims — actual
      regex recall depends on how well-structured the facts are, which the AGENTS.md
      template influences but cannot guarantee.
   
   b. **Lightweight NER model pass (< 50ms):** Run a small token-classification model
      (e.g., a fine-tuned distilbert or the `sentence-transformers` NER head) to catch
      entities the regex missed — written-out numbers ("a thousand"), abbreviations
      ("1k"), service names in natural phrasing ("the auth service"), and negation
      contexts ("does not use X"). This is the primary extraction path.
   
   c. **LLM extraction (optional, on commit if available):** For high-stakes scopes
      or when the lightweight model's confidence is low, use the Tier 3 LLM to extract
      structured entities. This is the same LLM already available for conflict
      escalation, reused for a different purpose.
   
   The extraction result is stored in the `entities` JSON column. If extraction fails
   or returns empty, the fact is still committed — it just won't benefit from Tier 0
   detection and will rely on Tier 1 NLI instead.

7. **Set provenance and verification status:** If `provenance` is provided, the fact
   is marked as `verified`. If not, it is accepted but marked `unverified` in query
   results. This is the lightweight version of [SEDM's verifiable write
   admission](https://arxiv.org/abs/2509.09498) — full replay verification is too
   heavy, but provenance tracking makes poisoned facts auditable and distinguishable
   from verified ones. See §Memory Injection Defense for the full threat model.
8. **Determine `lineage_id` and resolve supersession** (MemFactory Updater pattern):
   - If `operation = "update"` and `corrects_lineage` is **not** provided: run the
     **semantic auto-updater** — compare the new embedding against all active facts with
     embeddings in the same scope; if the best cosine similarity ≥ 0.75, automatically
     set `corrects_lineage` to that fact's lineage and `supersedes_fact_id` to its ID.
     If no match above threshold, fall back to `add` behavior.
   - If `corrects_lineage` is provided (either explicitly or via auto-updater): inherit
     it as `lineage_id` and record `supersedes_fact_id` from the most recent fact in
     that lineage.
   - Otherwise: generate a new UUID for `lineage_id`.
9. If superseding an existing fact: `UPDATE facts SET valid_until = NOW() WHERE lineage_id = corrects_lineage AND valid_until IS NULL`
10. **Handle TTL:** If `ttl_days` is provided, set `valid_until = valid_from + ttl_days`.
    A background job also periodically scans for facts where `ttl_days IS NOT NULL AND
    valid_until IS NULL AND valid_from + ttl_days < NOW()` and closes their windows.
11. `INSERT INTO facts (..., valid_from = NOW(), valid_until = NULL, memory_op = operation, supersedes_fact_id = ...)`
12. **Update FTS5 index:** `INSERT INTO facts_fts(rowid, content, scope, keywords) VALUES (...)`
13. Post the new `fact_id` to the **detection queue** (in-memory `asyncio.Queue`).
    Return immediately: `{fact_id, committed_at, duplicate: false, memory_op, supersedes_fact_id}`

**Write lock is released at step 11.** Detection runs without holding any lock.

### `engram_query(topic, scope?, limit?, as_of?, fact_type?)`

1. Generate embedding for `topic`
2. Retrieve **currently valid** facts: `WHERE valid_until IS NULL [AND scope = ?] [AND fact_type = ?]`
   If `as_of` timestamp provided: `WHERE valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)`
   This enables historical point-in-time queries without any additional machinery.
3. **Dual retrieval:** Score via embedding cosine + FTS5 BM25 rank, fuse with RRF.
   FTS5 query: `SELECT rowid, rank FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT 20`
4. **Scoring:**
   ```
   score = relevance              (RRF rank, 0-1 normalized)
         + 0.2 * recency          (exp(-0.05 * days_since_commit))
         + 0.15 * agent_trust     (1 - flagged_commits/total_commits)
   ```
   **Confidence handling (Round 6 revision):** Raw agent-reported confidence is excluded
   from the scoring formula because LLMs systematically over-report confidence (Round 3
   finding). However, confidence is not permanently discarded. Once sufficient calibration
   data exists (tracked via `flagged_commits` at confidence buckets per agent), calibrated
   confidence can be reintroduced as a scoring signal. Until then, confidence is stored
   and returned as metadata; agents can weight it themselves. "Confidence is deferred
   until calibration data exists" — not removed.
5. Return top-`limit` facts (default 10) with:
   - `has_open_conflict` flag joined from `conflicts` table
   - `verified` flag (true if `provenance IS NOT NULL`)
   - `fact_type` for filtering context
   - `artifact_hash` for staleness checking by the consuming agent

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

The 92% accuracy claim for NLI cross-encoders is from SNLI/MNLI benchmarks on general
English. Codebase facts like *"The auth service rate-limits to 1,000 requests per
second per IP"* are **not** general English. Domain shift will degrade NLI accuracy on
technical facts, potentially severely.

Research confirms this is worse than initially estimated. LLMs detect self-contradictions
at 0.6–45.6% accuracy; pairwise contradictions top out at ~89% with chain-of-thought
([httphangar.com synthesis, 2025](https://httphangar.com/blog/nlp-contradiction-deep-dive)).
CLAIRE's ~75% AUROC on Wikipedia is an **upper bound from a more favorable domain**.
Engram's actual automated precision on technical codebase facts will likely be 60–70%
without the deterministic tiers, and 80–85% with them. The deterministic tiers are not
just a performance optimization — they are a precision necessity.

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

### NLI Model Selection (Round 6 Correction)

The original plan specified `cross-encoder/nli-deberta-v3-base` (86M parameters) and
claimed "~300ms for 30 candidates" and "~500ms total detection." **This latency claim
is falsified on CPU.** DeBERTa-base takes ~200–400ms *per pair* on CPU. 30 pairs on
CPU = 6–12 seconds, not 300ms. The claim is only valid on GPU with batch inference.

Since the default deployment is CPU-first (`pip install`, no GPU required), the model
selection must match the deployment target:

| Model | Params | CPU per pair | 30 pairs (CPU) | MNLI accuracy | Default? |
|---|---|---|---|---|---|
| `cross-encoder/nli-MiniLM2-L6-H768` | ~60M | ~80ms | ~2.4s | ~85% of DeBERTa | **Yes (CPU)** |
| `cross-encoder/nli-deberta-v3-base` | 86M | ~300ms | ~9s | Baseline | GPU flag |
| DeBERTa + ONNX INT8 quantization | 86M | ~100ms | ~3s | ~98% of base | Optional |

**Default:** MiniLM2-L6 for CPU deployment. This covers the zero-setup local use case.
**`--high-accuracy` flag:** DeBERTa-base for GPU-equipped team servers.
**Optional:** ONNX Runtime as an optional dependency (`pip install engram-mcp[onnx]`)
for 2–4x CPU speedup with DeBERTa.

After Tier 0 catches obvious entity conflicts and Tier 2 catches numeric ones, the
NLI candidate set after dedup is typically 5–15 pairs, not 30. At 10 pairs × 80ms
(MiniLM2-L6 on CPU) = ~800ms. This is acceptable for a background worker.

**Honest latency table:**

| Metric | CPU (MiniLM2-L6, default) | GPU (DeBERTa-base) |
|---|---|---|
| Commit latency | <10ms (async queue post) | <10ms |
| Detection latency | 2–5 seconds (background) | <500ms (background) |
| Write lock held | ~1ms | ~1ms |
| SQLite throughput at 10 agents | ~100 commits/s | ~100 commits/s |

Detection is async in both cases. The committing agent never waits.

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

**Tier 1 — NLI Cross-Encoder**

For `f_new`, retrieve candidates via three parallel paths:
- *Path A:* Top-20 embedding-similar current facts in scope
- *Path B:* Top-10 FTS5 BM25 lexical matches in scope
- *Path C:* All facts with overlapping entity names (regardless of value)

Union, dedup, skip any already flagged by Tier 0. Cap at 30 candidates.

For each candidate:
```python
nli_model = CrossEncoder('cross-encoder/nli-MiniLM2-L6-H768')  # CPU default
scores = nli_model.predict([(f_new.content, f_cand.content)])
# scores[0] = contradiction, scores[1] = entailment, scores[2] = neutral
```

Classification:
- `contradiction_score > THRESHOLD_HIGH` (default 0.85, locally calibrated): **flag conflict**
  with `detection_tier = 'tier1_nli'`, `nli_score = contradiction_score`
- `contradiction_score > THRESHOLD_LOW` (default 0.5): **escalate to Tier 3**
- `entailment_score > 0.85`, different agents: **corroboration link** (metadata only, not a conflict)

**Tier 2 — Numeric and Temporal Rules (<5ms, parallel with Tier 1)**

For each candidate pair already in the candidate set:
- **Numeric:** Same scope + same entity name + different numeric value → conflict
  (catches what Tier 0 missed if entity extraction was partial)
- **Temporal:** Conflicting temporal claims about the same entity:
  "X was deprecated in Q1" vs "X is current" → flag with `detection_tier = 'tier2_temporal'`

**Tier 2b — Cross-Scope Entity Contradiction (<50ms, parallel with Tiers 1-2)**

This addresses the most dangerous blind spot in the original design: contradictions
that span scopes. The entire detection pipeline previously filtered by `scope`, meaning
"The payments service uses PostgreSQL" (scope: `payments`) would never be compared
against "All services use MySQL" (scope: `infra/database`). These cross-scope
contradictions are the hardest to catch and the most damaging when missed.

For `f_new`, query the `entities` column across ALL scopes (not just `f_new.scope`):

```sql
SELECT f.id, f.scope FROM facts f, json_each(f.entities) e
WHERE f.valid_until IS NULL
  AND f.id != ?
  AND e.value->>'name' = ?
  AND e.value->>'type' = ?
  AND (e.value->>'value' IS NULL OR e.value->>'value' != ?)
```

If a cross-scope entity match is found, add it to the Tier 1 NLI candidate set
regardless of embedding similarity or BM25 score. The NLI model then determines
whether the cross-scope pair actually contradicts.

This is cheap because it's a single indexed query on the `entities` JSON column,
and it catches the class of contradictions that scope-filtered detection misses
entirely. Cross-scope conflicts are flagged with `detection_tier = 'tier2b_cross_scope'`
and default to `severity = 'high'` (if two scopes disagree about the same entity,
that's almost always a real problem).

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
| Tier 2b cross-scope entity conflict | high |
| Tier 1 NLI > 0.85, different engineers | high |
| Tier 1 NLI > 0.85, same engineer | medium |
| Tier 3 LLM confirmed, any | medium |
| Tier 1 NLI 0.5–0.85, escalated but not confirmed | low |

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

### Auth model — three tiers, following the industry

The MCP ecosystem has converged on a clear deployment pattern. Microsoft's OWASP MCP
security guide says it plainly: *"stdio for prototyping, HTTP for production."* Google's
managed MCP servers use IAM-based auth with no shared keys. The MCP 2025-06-18 spec
classifies servers as OAuth 2.0 Resource Servers. Engram follows this progression:

**Tier 1 — Local mode (default):** No auth. Stdio transport. No `ENGRAM_DB_URL` set.
The server creates `~/.engram/knowledge.db` on first run. Zero setup. Single developer.

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

**Tier 2 — Team mode (BYOD database):** Stdio transport. `ENGRAM_DB_URL` set in env.
The connection string IS the credential — database-level auth is provided by the
PostgreSQL provider. No HTTP server required. No port forwarding. No firewall rules.
All engineers run their own local Engram process; all connect to the same database.

Workspace membership is controlled by invite keys (generated by `engram_init`, validated
by `engram_join`). The invite key is the only thing a teammate needs — it is a signed,
encrypted token that contains both the workspace ID and the database URL. The connection
string is never shared in plaintext; it is decrypted from the invite key and written
silently to workspace.json. After joining, workspace.json is the credential store.

```json
{
  "mcpServers": {
    "engram": {
      "command": "uvx",
      "args": ["engram-mcp@latest"],
      "env": { "ENGRAM_DB_URL": "postgres://user:pass@host/db" }
    }
  }
}
```

**Tier 3 — Enterprise mode (future):** Secrets manager integration (AWS Secrets Manager,
HashiCorp Vault, 1Password) so `ENGRAM_DB_URL` never appears in plaintext config. Full
audit logging of every workspace join/leave event. SSO-bound workspace membership:
workspace access is tied to an Okta/Entra group rather than a static invite key.

### Memory Injection Defense (Round 6)

[MINJA (Dong et al., 2025)](https://arxiv.org/abs/2503.03704) demonstrates that an
attacker can inject malicious records into an agent's memory bank through normal query
interactions alone — no direct memory access needed. The attack achieves >95% injection
success rate and 70% attack success rate. A follow-up paper ([Memory Poisoning Attack
and Defense, Jan 2026](https://arxiv.org/abs/2601.05504)) studies defenses.

**Why this matters for Engram:** `engram_commit` accepts facts from any authenticated
agent. A compromised or prompt-injected agent (not a malicious human — a legitimate
agent that was manipulated) could commit poisoned facts that propagate through
`engram_query` to other agents. Rate limiting and agent reliability scoring are
necessary but insufficient.

**Defense layers:**

1. **Provenance tracking:** Facts committed with a `provenance` field (file path, line
   number, test output, tool call ID) are marked `verified` in query results. Facts
   without provenance are accepted but marked `unverified`. This makes poisoned facts
   auditable and distinguishable from verified ones.

2. **Agent reliability scoring:** `flagged_commits / total_commits` downweights agents
   with high conflict rates. A poisoning agent that triggers many conflicts will see
   its facts ranked lower automatically.

3. **Rate limiting:** Per-agent commit rate limits (configurable, default 50/hour)
   prevent bulk poisoning.

4. **Fact type differentiation:** `observation` facts (directly observed in code) are
   harder to poison than `inference` facts (concluded from context). The conflict
   detection pipeline can weight observation-vs-observation conflicts as more serious
   than inference-vs-inference conflicts.

5. **AGENTS.md guidance:** The template instructs agents to always include provenance
   and to commit only verified facts. This is advisory, not deterministic, but it
   reduces the attack surface by making well-behaved agents the norm.

This is a "trust but verify" model. It does not prevent a determined attacker with
write access from poisoning the store — that remains explicitly out of scope. It does
make poisoning detectable, auditable, and self-correcting through the reliability
scoring feedback loop.

### Security — copying what works

Every major platform's MCP security guidance converges on the same principles. Engram
implements all of them:

| Principle | Source | Engram Implementation |
|---|---|---|
| Validate all inputs | Microsoft OWASP, Aptori, Block | Pydantic models on all tool inputs |
| Treat LLM output as untrusted | Microsoft OWASP, Aptori | Parameterized SQL only, no string interpolation |
| Enforce auth per tool | Microsoft OWASP, Google IAM | Scope permissions checked on every tool call |
| Full observability | Google Cloud Audit Logs, Microsoft | Every tool call logged with agent_id, args, duration |
| Bind tokens to server instance | MCP 2025-06-18 spec | JWT audience claim |
| No shared keys | Google managed MCP | Per-engineer tokens, never shared |
| HTTPS for non-localhost | MCP spec, all enterprise guides | Enforced in team/enterprise mode |
| Deterministic secret detection | AMP (ICML 2026) | Regex scanner rejects commits containing secrets |
| Provenance tracking | MINJA defense, SEDM | Facts without provenance marked unverified |

### AGENTS.md integration

OpenAI's AGENTS.md standard (AAIF founding project, 20k+ repos adopted) provides
repository-level context to AI agents. Engram should be referenced in a project's
AGENTS.md to guide agents on when and how to use shared memory:

```markdown
## Shared Memory (Engram)

Before starting work on any area of the codebase, query Engram for existing
team knowledge: `engram_query("topic")`. After discovering something worth
preserving, commit it: `engram_commit(content, scope, confidence)`.

Always include provenance (file path, line number, test output) when committing
facts. Facts without provenance are marked as unverified.

Check `engram_conflicts()` before making architectural decisions. Conflicts
mean two agents believe incompatible things about the same system.

Scopes: auth, payments, infra, api, frontend, database
```

This is how Engram becomes part of the standard agent workflow — not through
configuration, but through the same repository-level guidance that every major
AI coding tool now reads.

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

**v2 acceleration (Round 6):** If Turso/libSQL is adopted for team mode, its built-in
edge replication and Change Data Capture provide federation infrastructure for free.
The sync endpoint above becomes a thin wrapper around Turso's replication protocol
rather than a custom implementation.

---

## Phase 7 — Dashboard

**Goal:** Make the knowledge base inspectable by humans.

**Stack:** FastAPI (same process, separate router) + server-rendered HTML with HTMX.
No separate frontend build step. Endpoint: `http://HOST:PORT/dashboard`.

This follows the MCP ecosystem pattern: the MCP server handles the protocol layer,
and a co-located HTTP endpoint serves the human interface. Agent-MCP uses the same
pattern (MCP + web dashboard in one process).

**Views:**
- **Knowledge base** — current facts (`valid_until IS NULL`), filterable by scope/agent/date/fact_type
- **Conflict queue** — open conflicts, grouped by scope, severity-sorted. Each shows both
  facts side-by-side with detection tier and NLI score.
- **Timeline** — fact commits and validity windows as a Gantt-like chart. Makes it visible
  when different agents were active in the same scope.
- **Agent activity** — per-engineer commit rate, conflict rate, resolution rate,
  verification rate (% of commits with provenance)
- **Point-in-time view** — query the knowledge base as of any past timestamp (enabled
  free by the `valid_from`/`valid_until` schema)
- **Expiring facts** — facts with `ttl_days` approaching expiry, surfaced as
  "needs re-verification"

Human review is **structurally necessary**, not optional. CLAIRE demonstrated that
automated consistency detection has a hard ceiling at ~75% AUROC on general knowledge.
On technical codebase facts, the ceiling is likely lower (60–70% without deterministic
tiers). The conflict queue is the human-in-the-loop interface that lifts the system
above this ceiling. The deterministic tiers (0, 2, 2b) push automated precision to
an estimated 80–85%, but the remaining 15–20% requires human judgment.

---

## Delivery Sequence

| Phase | Deliverable | Unlocks |
|---|---|---|
| 0 | Agent-native onboarding: engram_status / engram_init / engram_join, workspace.json, privacy settings | Team sharing without any manual setup |
| 1 | Dual-backend schema: SQLite (local) + PostgreSQL (team), workspaces + invite_keys tables, pgvector + tsvector | All subsequent phases on both backends |
| 2 | MCP server: commit (secret scan, provenance, TTL) + query | Usable by agents today |
| 3 | Conflict detection (background, tiered, CPU-optimized) | **Core differentiator** |
| 4 | Resolution workflow | Conflicts become actionable |
| 5 | Access control + MINJA defense (scope permissions, rate limiting, agent reliability) | Production hardening |
| 6 | Federation (replicated journal) | Multi-team / org-wide |
| 7 | Dashboard (with expiry view) | Human oversight |

Phases 0–3 are the minimum viable Engram. **Phase 0 is what makes it distributable** —
without agent-native onboarding, team setup requires humans reading docs and running
CLI commands. **Phase 3 is the reason Engram exists** — without conflict detection,
Engram is just another shared memory MCP server in a field that includes Mem0 (38k
stars), Cipher, SAMEP, and Agent KB. The background worker in Phase 3 is the structural
prerequisite for Phase 2 being usable under any real load.

---

## Failure Modes & Mitigations

### 1. NLI Domain Collapse (CRITICAL — Addressed)
- **Failure:** NLI cross-encoders trained on SNLI/MNLI (general English) suffer
  significant accuracy degradation on technical codebase facts. The 92% benchmark
  accuracy does not transfer. LLMs detect pairwise contradictions at ~89% best case;
  self-contradictions at 0.6–45.6%.
- **Mitigation:**
  - Dominance inversion: Tier 0 entity exact-match and Tier 2 numeric rules handle all
    numeric/config contradictions deterministically, eliminating the NLI's blind spot.
  - NLI handles only *natural language semantic* contradictions — its genuine strength.
  - Default model is MiniLM2-L6 (CPU-optimized); DeBERTa-base available for GPU.
  - Local threshold calibration via `detection_feedback` table adapts to team vocabulary.
  - Future: fine-tune on domain-specific pairs using LoRA (low cost, high impact).

### 2. SQLite Write Serialization Under Concurrent Load (CRITICAL — Addressed)
- **Failure:** Running NLI inference inside the write path holds the exclusive SQLite
  write lock for ~300ms+. With 10 concurrent agents: ~3 commits/s maximum throughput.
- **Mitigation:** Detection is fully decoupled from the write path. The write lock is
  held for <1ms (a single `INSERT`). Detection runs in a background asyncio worker.
  Throughput ceiling is now SQLite's actual insert rate (~10,000/s in WAL mode).
  v2 upgrade path: Turso/libSQL with MVCC eliminates single-writer entirely.

### 3. BFT Over-Engineering (REMOVED)
- **Resolution:** Removed entirely. Rate limiting, agent reliability scoring, provenance
  tracking, and source corroboration provide sufficient defense against accidental or
  low-sophistication poisoning. Full adversarial attack resistance is explicitly out of
  scope.

### 4. Graph Database Scope Creep (REMOVED for v1)
- **Resolution:** Removed for v1. `entities` JSON column provides structured entity
  lookup without any graph infrastructure. Acknowledged as a potential v2+ consideration
  if federation scales beyond ~10 teams or ~100k facts (see Phase 2 notes).

### 5. Uncalibrated Confidence Scoring (DEFERRED)
- **Failure:** LLMs systematically over-report confidence. Raw confidence pollutes
  retrieval with noise.
- **Mitigation:** Confidence excluded from scoring formula until calibration data exists.
  Once sufficient `flagged_commits` data accumulates per agent per confidence bucket,
  calibrated confidence can be reintroduced. Confidence is stored and returned as
  metadata in the interim.

### 6. Quorum Commits Breaking Single-Developer Use (REMOVED)
- **Resolution:** Removed. Source corroboration tracked as metadata and used as a
  downweight signal in query scoring.

### 7. Missing Point-in-Time Queryability (ADDRESSED)
- **Mitigation:** The `valid_from`/`valid_until` temporal model makes this a free
  predicate. `engram_query(topic, as_of="2025-12-01")` works without additional
  infrastructure.

### 8. Silent Retrieval Corruption on Embedding Upgrade (ADDRESSED)
- Embedding model + version stored with each fact.
- Re-indexing tool provided.
- At startup, validate configured model against newest rows.
- In team mode, server is the single source of embeddings (Round 6).

### 9. Regex Entity Extraction Recall Failure (CRITICAL — Addressed)
- **Failure:** Regex alone misses the majority of entities in natural prose.
- **Mitigation:** Hybrid extraction pipeline: regex first (< 1ms), then lightweight
  NER model (< 50ms, primary extractor), with optional LLM extraction for high-stakes
  scopes. No unsupported recall percentage claims — actual recall depends on fact
  structure, which the AGENTS.md template influences but cannot guarantee.

### 10. Cross-Scope Contradictions Invisible to Detection (CRITICAL — Addressed)
- **Failure:** Scope-filtered detection misses contradictions spanning scopes.
- **Mitigation:** Tier 2b cross-scope entity detection queries across all scopes.
  Cross-scope conflicts default to `severity = 'high'`.

### 11. Memory Injection via Prompt-Injected Agents (NEW — Round 6)
- **Failure:** MINJA demonstrates >95% injection success rate through normal agent
  interactions. A prompt-injected agent could commit poisoned facts that propagate
  to other agents via `engram_query`.
- **Mitigation:** Provenance tracking (verified/unverified), agent reliability scoring,
  rate limiting, fact type differentiation, and AGENTS.md guidance. See §Memory
  Injection Defense for the full defense model.

### 12. Detection Latency Mismatch on CPU (NEW — Round 6)
- **Failure:** Original plan claimed ~500ms total detection. On CPU with DeBERTa-base,
  actual latency is 6–12 seconds for 30 candidates.
- **Mitigation:** Default to MiniLM2-L6 on CPU (~80ms/pair). After Tier 0/2 dedup,
  typical candidate set is 5–15 pairs → 400ms–1.2s. DeBERTa-base available via
  `--high-accuracy` flag for GPU servers. ONNX quantization as optional dependency.

### 13. Fact Staleness Without Expiry (NEW — Round 6)
- **Failure:** Facts committed months ago about rate limits or API contracts may no
  longer be true but are never superseded because nobody re-checks them.
- **Mitigation:** Optional `ttl_days` parameter on `engram_commit`. When set,
  `valid_until` is automatically set to `valid_from + ttl_days`. Dashboard surfaces
  expiring facts as "needs re-verification." The `recency` signal in query scoring
  also naturally downweights old facts.

### 14. Accidental Secret Leakage (NEW — Round 6)
- **Failure:** Agents may commit facts containing API keys, JWT tokens, or connection
  strings despite tool description warnings.
- **Mitigation:** Deterministic regex scanner at commit time rejects content matching
  common secret patterns. This is enforcement, not advisory.

### 15. Silent Fact Accumulation Without Update Intent (NEW — Round 7)
- **Failure:** When an agent learns that an existing fact is outdated, it must know and
  pass the specific `lineage_id` to supersede it. Without that, both the old and new
  facts coexist as "current," creating silent duplication and inflating the conflict
  detection candidate set. Agents often lack access to lineage IDs from prior sessions.
- **Mitigation (MemFactory CRUD pattern):** The `operation="update"` parameter triggers
  the semantic auto-updater: the engine embeds the new content, scores it against all
  active facts in scope, and automatically supersedes the best match above cosine
  similarity 0.75. The agent does not need to know or track the lineage ID. This reduces
  the cognitive burden on the agent and prevents silent duplication. The `memory_op` and
  `supersedes_fact_id` columns provide a complete audit trail of every lifecycle operation.

---

## Key Design Constraints (Refined)

**1. Temporal Validity is the Only Versioning Primitive**  
Every state change — supersession, correction, archival, expiry, TTL — is expressed as
setting `valid_until`. No other versioning mechanism exists. This is the invariant
that makes the schema simple and the logic predictable.

**2. Hybrid Retrieval is Non-Negotiable**  
Embedding retrieval alone is blind to negation. FTS5 BM25 retrieval alone misses
paraphrases. Entity-based lookup handles exact structured matches. All three are
required for comprehensive conflict candidate generation.

**3. Detection is Decoupled from the Write Path**  
Conflict detection is always async. The committing agent never waits for detection.
This is the only design choice that keeps SQLite viable as the storage backend.

**4. NLI is a Signal, Not a Verdict**  
For technical codebase facts, domain-specific rules (entity exact-match, numeric
comparison) produce higher-confidence determinations than a general-domain NLI model.
NLI fills the gap for natural language semantic contradictions. Its threshold is
calibrated, not fixed. Its model is sized for the deployment target (CPU vs GPU).

**5. Complexity Budget: Prefer Deletion**  
Every component added to Engram must either remove another component (generalization)
or address a documented failure mode. The Round 3 rewrite removed 4 components
(BFT, graph DB, quorum commits, `facts_archive` table) and replaced 4 mechanisms
with 1 temporal invariant. Round 6 added 4 features (provenance, TTL, secret scan,
fact typing) but removed 1 dependency (`rank_bm25` → FTS5) and corrected 2 false
claims (latency, regex recall). Round 7 added 1 parameter (`operation`) and 2 schema
columns (`memory_op`, `supersedes_fact_id`) in exchange for eliminating the agent-side
burden of lineage ID tracking for update operations.

**7. Explicit Memory Operation Intent**  
Every commit carries an explicit `memory_op` (`add`, `update`, `delete`, `none`).
This is the MemFactory CRUD invariant: the engine should never have to infer whether
an agent intends to add new information or correct old information — the agent declares
its intent, and the engine enforces it. The semantic auto-updater handles the common
case where the agent knows its intent (`update`) but not the specific lineage to supersede.

**6. Honest Performance Claims**  
All latency and throughput numbers are stated for the default deployment target (CPU,
MiniLM2-L6, SQLite WAL). GPU numbers are stated separately. No benchmark-only claims
are presented as production expectations.

---

## What Engram Is Not Building

- **Parametric memory:** No weight updates to the LLMs it interacts with.
- **Cache-level protocols:** No sharing of LLM KV caches.
- **Graph traversal (v1):** Entity relationships are tracked in JSON, not a graph
  database. Lightweight embedded graph (Kùzu) is a v2+ consideration if federation
  scales beyond ~100k facts.
- **Full adversarial security:** BFT and quorum commits are not implemented.
  Engram protects against accidental inconsistency and makes poisoning detectable
  via provenance tracking; a determined attacker with write access can still poison
  the store.
- **RL-driven memory policy optimization:** Fine-tuning LLMs with GRPO to learn better
  memory management policies (MemFactory's Trainer Layer) is out of scope for Engram's
  server-side backend. Engram adopts the *structural insights* from Memory-RL research
  (explicit CRUD operations, semantic auto-update) without the training infrastructure.
- **Multimodal memory:** Text facts only in v1.
- **General agent orchestration:** Letta, Agent-MCP handle this. Engram is the
  consistency layer only.

### Strategic Positioning

Engram is a **consistency layer** that sits on top of existing shared memory systems.
Long-term: other systems store and retrieve; Engram asks "are these facts coherent?"
This complementary positioning keeps the implementation focused on the one thing no
other system does, and makes Engram composable with the existing ecosystem.

The competitive landscape is converging. Mem0 (38k+ stars) now frames multi-agent
contradiction as a core problem. Cipher ships team-level memory sharing. SAMEP proposes
a formal exchange protocol. Agent KB provides cross-domain experience sharing. None of
them have conflict *detection*. That is Engram's moat, and Phase 3 is the phase that
builds it.

### What the MCP Ecosystem Taught Us (Rounds 4 + 6)

The successful MCP servers (Context7, GitHub MCP, Playwright MCP) and the broader AAIF
ecosystem (MCP + AGENTS.md + Goose, all now under the Linux Foundation) share patterns
that Engram adopts:

**1. Solve one problem exceptionally well.**
Context7 does documentation freshness. GitHub MCP does repo management. Engram does
consistency. No feature creep.

**2. Minimal tool surface (empirically enforced).**
Context7 has 2 tools. Engram has 4. LLM tool-selection accuracy degrades significantly
when exposed to >30-40 tools.

**3. Tool descriptions are executable LLM prompts.**
Every Engram tool description embeds: (a) what state the agent should be in before
calling it, (b) what it returns and how to interpret it, (c) rate-limit and
error-handling guidance.

**4. Block's "Discovery → Planning → Execution" pattern.**
`engram_query` = Discovery, `engram_commit` = Execution, `engram_conflicts` +
`engram_resolve` = Planning and execution of fixes.

**5. Server-side intelligence, not client-side computation.**
NLI scoring, FTS5 ranking, entity extraction, embedding generation — all happen on the
Engram server. The agent receives pre-ranked, pre-scored results.

**6. Zero-setup deployment.**
One line of JSON config for local use. `uvx engram-mcp` downloads and runs. No Docker,
no database setup, no API keys for core features.

**7. AGENTS.md as a first-class integration target.**
Engram ships a reference AGENTS.md template that tells coding agents when to query,
when to commit, and how to interpret conflicts.

**8. Honest about what runs where.**
CPU-first deployment means CPU-first model selection and CPU-first latency claims.
GPU is an upgrade, not the default.

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

Always include provenance (file path, line number, test output) so the fact is marked
as verified. Use fact_type to distinguish observations from inferences and decisions.
Set ttl_days for facts about external dependencies or API contracts that may change.

## Interpreting query results
- `has_open_conflict: true` — two agents disagree. Call `engram_conflicts` before acting.
- `verified: false` — no provenance provided. Treat with appropriate skepticism.
- `fact_type: inference` — concluded from context, not directly observed. Lower weight.

## Scope convention for this repo
- `auth/*` — authentication service, JWT, sessions
- `payments/*` — payment processing, webhooks, billing
- `infra/*` — database, cache, queue configuration
- `api/*` — public API contracts, rate limits, versioning
```

This template ships as `docs/AGENTS.md.template` in the Engram repository. Teams
customize it for their scope hierarchy.
