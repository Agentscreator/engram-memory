<div align="center">

# Engram

**Shared memory for your team's agents**

Persistent memory that survives across sessions and detects when agents contradict each other.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-8b5cf6?style=flat-square)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square)](https://python.org)

</div>

---

## What It Does

When one agent discovers something important — a hidden side effect, a failed approach, an undocumented constraint — it commits that fact. Every other agent on your team can query it instantly.

When two agents develop incompatible beliefs, Engram detects the contradiction and surfaces it for review.

**Your data is private.** Facts live in our database, isolated by workspace. We don't read, analyze, or redistribute your team's memory. Ever.

---

## Quick Start

**macOS / Linux:**
```bash
curl -fsSL https://engram.app/install | sh
```

**Windows PowerShell:**
```powershell
irm https://engram.app/install.ps1 | iex
```

**Windows CMD:**
```cmd
curl -fsSL https://engram.app/install.cmd -o install.cmd && install.cmd && del install.cmd
```

Restart your editor, then ask your agent:
```
"Set up Engram for my team"
```

Your agent handles the rest — no database setup, no configuration files, no environment variables. Works with Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, and any MCP-compatible IDE.

---

## Setup Flow

### Creating a Workspace

> 🤖 **Agent**
>
> Do you have an Invite Key to join an existing workspace, or are you setting up a new one?

> 👤 **You**
>
> New

> 🤖 **Agent**
>
> ✅ Your team workspace is ready.
>
> Share this Invite Key with teammates:
> ```
> ek_live_abc123...
> ```
>
> That's all they need — one key, nothing else to configure.
>
> Should commits show who made them, or stay anonymous?

---

### Joining a Workspace

> 🤖 **Agent**
>
> Do you have an Invite Key to join an existing workspace, or are you setting up a new one?

> 👤 **You**
>
> Join — here's my key: `ek_live_abc123...`

> 🤖 **Agent**
>
> You're in. I'll query team memory before starting work on anything.

**That's it.** Teammates only need the Invite Key. No database URL, no Team ID, no configuration.

---

## How It Works

```
┌──────────────────────────────────────────┐
│            MCP Tools                     │
│  engram_commit  — Write a fact           │
│  engram_query   — Read team knowledge    │
│  engram_conflicts — See disagreements    │
│  engram_resolve — Settle conflicts       │
├──────────────────────────────────────────┤
│        Conflict Detection                │
│  Tier 0: Entity exact-match              │
│  Tier 1: NLI cross-encoder (local)       │
│  Tier 2: Numeric/temporal rules          │
│  Tier 3: LLM escalation (rare)           │
├──────────────────────────────────────────┤
│          Hosted Storage                  │
│  Managed Postgres — zero setup           │
│  Isolated per workspace                  │
└──────────────────────────────────────────┘
```

No database to provision, no servers to run, no ports to open. Install and go.

---

## Privacy & Security

- Facts are isolated per workspace — no cross-workspace access
- Invite keys use encrypted payloads — teammates never see raw credentials
- **Anonymous mode** — Strip engineer names from all commits
- **Anonymous agents** — Randomize agent IDs each session
- We don't read, analyze, or redistribute your data

---

## Tools

| Tool | Purpose |
|---|---|
| `engram_commit` | Persist a verified discovery |
| `engram_query` | Pull what your team's agents know |
| `engram_conflicts` | Surface contradictions |
| `engram_resolve` | Settle disagreements |
| `engram_promote` | Graduate ephemeral memory to durable |

---

## Conflict Detection

Runs asynchronously in the background:

| Tier | Method | Catches |
|---|---|---|
| 0 | Entity matching | "rate limit is 1000" vs "rate limit is 2000" |
| 1 | NLI cross-encoder | Semantic contradictions |
| 2 | Numeric rules | Different values for same entity |
| 3 | LLM escalation | Ambiguous cases (rare, optional) |

Commits return instantly. Detection completes in the background (~2-10s on CPU).

---

## Memory That Forgets on Purpose

Engram doesn't just accumulate — it actively forgets what doesn't earn its place.

- **Ephemeral memory** — Scratchpad facts auto-expire in 24h unless queried twice ("proved useful more than once")
- **Importance decay** — Unverified inferences expire after 30 days. Unverified observations expire after 90 days.
- **Protected facts** — Decisions, verified facts, and corroborated claims are never auto-retired.
- **Steeper recency curve** — A 90-day-old fact scores 0.001 in retrieval. Old context stops crowding out what matters now.

Grounded in the [FiFA/MaRS research](https://arxiv.org/abs/2512.12856) on forgetting-by-design for cognitive agents.

---

## Research Foundation

Engram is grounded in peer-reviewed research on multi-agent memory systems:

- **[Yu et al. (2026)](https://arxiv.org/abs/2603.10062)** — Multi-agent memory as a computer architecture problem
- **[Xu et al. (2025)](https://arxiv.org/abs/2502.12110)** — A-Mem's Zettelkasten structure for fact enrichment
- **[Rasmussen et al. (2025)](https://arxiv.org/abs/2501.13956)** — Graphiti's bitemporal modeling for temporal validity
- **[Hu et al. (2026)](https://arxiv.org/abs/2512.13564)** — Survey confirming shared memory as an open frontier
- **[Alqithami (2025)](https://arxiv.org/abs/2512.12856)** — FiFA: forgetting-by-design improves agent coherence

Full literature review: [`LITERATURE.md`](./LITERATURE.md)  
Implementation details: [`docs/IMPLEMENTATION.md`](./docs/IMPLEMENTATION.md)

---

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

---

## License

[Apache 2.0](./LICENSE)

---

<div align="center">
<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge.</sub>
</div>
