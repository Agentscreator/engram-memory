<div align="center">

<br />

<img src="./assets/banner.svg" alt="Engram" width="860"/>

<br />

**Multi-agent memory consistency for engineering teams.**

<br />

[![Status](https://img.shields.io/badge/status-early%20development-orange?style=flat-square)](https://github.com/Agentscreator/Engram)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-8b5cf6?style=flat-square)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](./CONTRIBUTING.md)

</div>

<br />

Engram is an MCP server that gives your agents a shared, persistent knowledge base — one that survives across sessions, syncs across engineers, and detects when two agents develop contradictory beliefs about the same codebase.

> Individual agent memory is solved. Engram solves what happens when multiple agents need to agree on what's true.

<br />

## The Problem

Every agent session starts from zero. Your agent re-discovers why that architectural decision was made, re-learns which approaches already failed, re-figures out which constraints are non-negotiable. Another engineer's agent did the same thing last week.

Existing memory tools fix this for a single engineer and a single agent. They don't address what happens when Agent A and Agent B — running in separate sessions, for different engineers — develop incompatible beliefs about the same system.

That's a consistency problem. Engram solves it.

<br />

## How It Works

Engram exposes four MCP tools. That's the entire surface area.

| Tool | Purpose |
|---|---|
| `engram_query` | Pull what your team's agents collectively know about a topic. Structured facts, ranked by relevance and recency. |
| `engram_commit` | Persist a verified discovery — a hidden side effect, a failed approach, an undocumented constraint. Append-only, timestamped, traceable. |
| `engram_conflicts` | Surface pairs of facts that semantically contradict each other. Not an error — a structured artifact. Reviewable, resolvable, auditable. |
| `engram_resolve` | Settle a disagreement. Pick a winner, merge both sides, or dismiss a false positive. |

Conflict detection runs asynchronously in the background using a tiered pipeline: deterministic entity matching, NLI cross-encoder scoring, and optional LLM escalation for ambiguous cases. Commits return instantly; detection completes within seconds.

<br />

## Quick Start

### Requirements

- Python 3.11+
- Any MCP-compatible client — Claude Code, Cursor, Windsurf, Kiro, VS Code

### Install and run

```bash
pip install engram-mcp
engram serve
```

Engram runs at `localhost:7474` and stores facts in `~/.engram/knowledge.db`. No Docker, no database setup, no API keys.

### Connect

Add to your MCP client config:

```json
{
  "mcpServers": {
    "engram": {
      "url": "http://localhost:7474/mcp"
    }
  }
}
```

Or use stdio for local-only mode:

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

<br />

## Team Setup

Engram is local-first by default. To share knowledge across your team, point everyone at the same server:

```bash
engram serve --host 0.0.0.0 --port 7474
```

Or deploy with Docker:

```bash
docker run -p 7474:7474 -v engram-data:/data engram/server
```

Every commit is immediately available to every agent on the team.

<br />

## Architecture

```
┌──────────────────────────────────────────┐
│            I/O Layer (MCP)               │  ← agents connect here
│  engram_commit / engram_query /          │
│  engram_conflicts / engram_resolve       │
├──────────────────────────────────────────┤
│          Detection Layer                 │  ← runs asynchronously
│  Tier 0: hash dedup + entity match       │
│  Tier 1: NLI cross-encoder (local)       │
│  Tier 2: numeric / temporal rules        │
│  Tier 3: LLM escalation (rare)           │
├──────────────────────────────────────────┤
│          Storage Layer (SQLite)          │  ← append-only, bitemporal
│  facts · conflicts · agents · scopes     │
└──────────────────────────────────────────┘
```

Every fact carries a temporal validity window (`valid_from`, `valid_until`). Supersession, correction, archival, and versioning are all expressed through this single primitive — no pointer chasing, no separate archive tables, no decay scores.

Detection is fully decoupled from the write path. The write lock is held for ~1ms (a single `INSERT`). NLI inference runs in a background worker. This keeps SQLite viable under concurrent agent load.

<br />

## What Engram Is Not

There are 400+ MCP servers that give an individual agent persistent memory across sessions. Engram is not that.

Engram is a **consistency layer**. Other systems store and retrieve. Engram asks: *are these facts coherent with each other?* It is designed to be composable with existing memory tools, not to replace them.

<br />

## Research Foundation

Engram is grounded in peer-reviewed research on multi-agent memory systems:

- [Yu et al. (2026)](https://arxiv.org/abs/2603.10062) — frames multi-agent memory as a computer architecture problem and names consistency as the most pressing open challenge
- [Xu et al. (2025)](https://arxiv.org/abs/2502.12110) — A-Mem's Zettelkasten-inspired note structure informs fact enrichment
- [Rasmussen et al. (2025)](https://arxiv.org/abs/2501.13956) — Graphiti's bitemporal modeling directly inspired the temporal validity design
- [Hu et al. (2026)](https://arxiv.org/abs/2512.13564) — comprehensive survey confirming shared multi-agent memory as an open frontier

Full literature review: [`LITERATURE.md`](./LITERATURE.md) · Implementation plan: [`IMPLEMENTATION.md`](./IMPLEMENTATION.md)

<br />

## Roadmap

| Phase | What | Status |
|:---:|---|---|
| 1 | Schema and storage (bitemporal facts, conflict tables) | 🟡 In progress |
| 2 | Core MCP server (commit, query) | ⬜ Next |
| 3 | Conflict detection (tiered async pipeline) | ⬜ Planned |
| 4 | Resolution workflow | ⬜ Planned |
| 5 | Auth and access control (local → team → enterprise) | ⬜ Planned |
| 6 | Cross-team federation | ⬜ Future |
| 7 | Dashboard UI | ⬜ Future |

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
