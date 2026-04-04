<div align="center">

**Shared memory for your team's agents. Works with any MCP-compatible IDE. You own your data.**

<br />

[![Core](https://img.shields.io/badge/core-shipped-brightgreen?style=flat-square)](#) 
[![Dashboard](https://img.shields.io/badge/dashboard-shipped-brightgreen?style=flat-square)](#) 
[![Federation](https://img.shields.io/badge/federation-shipped-brightgreen?style=flat-square)](#)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-8b5cf6?style=flat-square)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](./CONTRIBUTING.md)

</div>

<br />

Engram gives your team's agents a shared, persistent memory that survives across sessions and detects when two agents develop contradictory beliefs about the same codebase.

You bring your own database. Engram never owns your data.

> Individual agent memory is solved. Engram solves what happens when multiple agents need to agree on what's true.

<br />

## How it works

Every agent on your team connects to the same knowledge base. When one agent discovers something — a hidden side effect, a failed approach, an undocumented constraint — it commits that fact. Every other agent on the team can query it instantly.

When two agents develop incompatible beliefs about the same system, Engram detects the contradiction and surfaces it for review. No silent divergence.

<br />

## Quick Start

1. Install Engram:
   ```bash
   pip install engram-team
   engram install
   ```
   
   Supports: Claude Code, Claude Desktop, Cursor, Windsurf, VS Code (Cline/Roo/Copilot), Codex, and any MCP-compatible IDE.

2. Restart your MCP-compatible editor or IDE

3. Open a new chat and ask your agent:
   ```
   "Set up Engram for my team"
   ```

4. Your agent will ask if you're:
   - **Creating a new workspace** → You'll need a PostgreSQL database URL
     - Use your existing app database (Engram creates a separate `engram` schema)
     - Or get a free dedicated database at [Neon](https://neon.tech), [Supabase](https://supabase.com), or [Railway](https://railway.app)
   - **Joining an existing workspace** → You'll need the Invite Key from your workspace founder

5. Done! Your agent now has persistent memory. Share your Invite Key with teammates anytime to enable team collaboration.

**Important:** For security, set your database URL in a `.env` file or environment variable — never paste it in chat.

<br />

## What happens after install

Your agent calls `engram_status()` on its first tool use and walks you through setup. No docs to read. No JSON to edit.

**Setting up a new workspace (team founder):**

```
Agent: "Do you have an Invite Key to join an existing workspace,
        or are you setting up a new one?"

You:   "New"

Agent: "Add your database connection string to your environment.
        
        Create a .env file in your project root with:
        
          ENGRAM_DB_URL='postgres://...'
        
        Or set it in your shell config (.bashrc, .zshrc):
        
          export ENGRAM_DB_URL='postgres://...'
        
        IMPORTANT: Don't paste your database URL in this chat.
        
        You can:
          • Use your existing app database (Engram creates a separate 'engram' schema)
          • Get a free dedicated database at neon.tech, supabase.com, or railway.app
        
        Once set, restart this chat and I'll detect it automatically."

[You set ENGRAM_DB_URL in .env or shell config]

Agent: "Your team workspace is ready.
        
        Engram tables are in the 'engram' schema in your database —
        completely isolated from your application tables.

        Share with teammates:
          Invite Key: ek_live_abc123...

        That's all they need.
        Should commits show who made them, or stay anonymous?"
```

**Joining a workspace (teammate):**

```
Agent: "Do you have an Invite Key to join an existing workspace,
        or are you setting up a new one?"

You:   "Join"

Agent: "What's your Invite Key?"
You:   "ek_live_abc123..."

Agent: "You're in. I'll query team memory before starting any task."
```

Teammates only need one thing — the Invite Key. The workspace ID and database connection are encrypted inside it and extracted automatically. No one except the workspace founder ever sees or handles a database URL.

**Every session after that:** the agent connects silently, queries before every task, commits after every discovery. Engram is invisible infrastructure.

<br />

## You own your data

Engram connects to a PostgreSQL database you provide. Your facts, conflicts, and agent history live in your database — not ours.

- Use [Neon](https://neon.tech), [Supabase](https://supabase.com), [Railway](https://railway.app), or any PostgreSQL instance
- Use your existing app database — Engram creates all tables in a separate `engram` schema
- Self-host if you want zero third-party involvement
- The database URL is stored securely in `~/.engram/workspace.json` (mode 600) or environment variables
- The invite key carries the database URL encrypted inside it — teammates never see it in plaintext

**Privacy settings** (asked once during setup, enforced server-side):
- **Anonymous mode** — strip engineer names from all commits
- **Anonymous agents** — randomize agent IDs each session

<br />

## Tools

Engram exposes seven MCP tools. The first three handle setup; the last four are the knowledge layer.

| Tool | Purpose |
|---|---|
| `engram_status` | Check setup state. Returns `next_prompt` — the agent says it to you. |
| `engram_init` | Create a new workspace (founder). Generates Team ID + Invite Key. |
| `engram_join` | Join a workspace with just an Invite Key. Extracts workspace ID + db URL automatically. |
| `engram_query` | Pull what your team's agents collectively know about a topic. |
| `engram_commit` | Persist a verified discovery — fact, constraint, decision, failed approach. |
| `engram_conflicts` | Surface pairs of facts that semantically contradict each other. |
| `engram_resolve` | Settle a disagreement: pick a winner, merge both sides, or dismiss. |

<br />

## Conflict detection

Contradiction detection runs asynchronously in the background using a tiered pipeline:

| Tier | Method | Catches |
|---|---|---|
| 0 | Deterministic entity matching | "rate limit is 1000" vs "rate limit is 2000" |
| 1 | NLI cross-encoder (local, CPU) | Semantic contradictions in natural language |
| 2 | Numeric + temporal rules | Different values for the same named entity |
| 2b | Cross-scope entity detection | Contradictions spanning different scopes |
| 3 | LLM escalation (rare, optional) | Ambiguous cases needing domain understanding |

Commits return instantly. Detection completes in the background. The write lock is held for ~1ms.

<br />

## Architecture

```
┌──────────────────────────────────────────┐
│            I/O Layer (MCP)               │  ← agents connect here (stdio)
│  engram_status / engram_init /           │
│  engram_join / engram_commit /           │
│  engram_query / engram_conflicts /       │
│  engram_resolve                          │
├──────────────────────────────────────────┤
│          Detection Layer                 │  ← runs asynchronously
│  Tier 0: entity exact-match             │
│  Tier 1: NLI cross-encoder (local)      │
│  Tier 2: numeric / temporal rules       │
│  Tier 2b: cross-scope entity detection  │
│  Tier 3: LLM escalation (rare)          │
├──────────────────────────────────────────┤
│          Storage Layer                   │
│  PostgreSQL (your ENGRAM_DB_URL)         │
│  Personal or team workspace              │
└──────────────────────────────────────────┘
```

Team sharing works through the shared database — no HTTP server, no port forwarding, no firewall rules. Every team member runs their own local Engram process connected to the same PostgreSQL instance.

<br />

## Solo use (personal workspace)

Start with your own personal workspace — you can share with teammates later.

**Recommended: PostgreSQL**
- Get a free database at [Neon](https://neon.tech), [Supabase](https://supabase.com), or [Railway](https://railway.app)
- Or use your existing app database — Engram creates a separate `engram` schema
- Set `ENGRAM_DB_URL` in a `.env` file or environment variable (never paste in chat)
- During setup, choose "new" and your agent will detect the database URL automatically
- Share your Invite Key with teammates anytime to enable collaboration

**For local development only: SQLite**
- Engram will use `~/.engram/knowledge.db` if no database URL is provided
- Good for testing, but limited to single-machine use
- No team sharing or federation support

<br />

## Research foundation

Engram is grounded in peer-reviewed research on multi-agent memory systems:

- [Yu et al. (2026)](https://arxiv.org/abs/2603.10062) — frames multi-agent memory as a computer architecture problem; names consistency as the most pressing open challenge
- [Xu et al. (2025)](https://arxiv.org/abs/2502.12110) — A-Mem's Zettelkasten note structure informs fact enrichment
- [Rasmussen et al. (2025)](https://arxiv.org/abs/2501.13956) — Graphiti's bitemporal modeling directly inspired the temporal validity design
- [Hu et al. (2026)](https://arxiv.org/abs/2512.13564) — survey confirming shared multi-agent memory as an open frontier

Full literature review: [`LITERATURE.md`](./LITERATURE.md) · Implementation details: [`docs/IMPLEMENTATION.md`](./docs/IMPLEMENTATION.md)

<br />

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for guidelines.

<br />

## License

[Apache 2.0](./LICENSE)

---

<div align="center">

<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge.</sub>

</div>
