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

There are a lot of tools that give agents memory. Engram works alongside any of them.

What makes Engram different: it catches when agents contradict each other. One agent learns something, another agent learns something else, and now they disagree. Engram detects that and surfaces it before it becomes a bug.

Your whole team shares the same memory. Your agents, your teammates' agents — everyone stays in sync. The same context, the same facts, no duplicated mistakes.

Right now it's your personal memory layer that survives across sessions. The bigger picture is a consistency layer for teams of hundreds of agents working on the same codebase at once.

---

## Quick Start

**Step 1 — Create an account**

Sign up at [engram-memory.com/dashboard](https://engram-memory.com/dashboard). Create a new workspace or join an existing one using an invite key from a teammate.

**Step 2 — Run the installer**

**macOS / Linux:**
```bash
curl -fsSL https://engram-memory.com/install | sh
```

**Windows PowerShell:**
```powershell
irm https://engram-memory.com/install.ps1 | iex
```

**Windows CMD:**
```cmd
curl -fsSL https://engram-memory.com/install.cmd -o install.cmd && install.cmd && del install.cmd
```

**Step 3 — Restart your editor, then ask your agent:**
```
"Set up Engram for my team"
```

Your agent handles the rest.

---

## First-Class IDE Targets

Engram is currently optimized for MCP-native workflows in:

- [Claude Code](./docs/quickstart/claude-code.md)
- [Cursor](./docs/quickstart/cursor.md)
- [VS Code (Copilot)](./docs/quickstart/vscode-copilot.md)
- [Windsurf](./docs/quickstart/windsurf.md)
- [Zed](./docs/quickstart/zed.md)

Each guide includes the expected MCP config path, restart step, verification flow, and common setup mistakes.


## Running Locally

If you want to run Engram from this repository during development:

```powershell
pip install -e ".[dev]"
python -m engram.cli serve --http
```

Then open:

```text
http://127.0.0.1:7474/dashboard
```

If `engram` is not on your `PATH`, `python -m engram.cli ...` works reliably.

---

## Setup Flow

Create an account at [engram-memory.com](https://engram-memory.com) to start a workspace. A demo video is coming soon that will walk through the full setup flow.

---

## Privacy & Security

Your data is encrypted in transit and at rest, fully isolated per workspace, and never read, analyzed, trained on, or shared with anyone. Delete your workspace and everything is gone.

---

## Tools

| Tool | Purpose |
|---|---|
| `engram_commit` | Persist a verified discovery |
| `engram_query` | Pull what your team's agents know |
| `engram_conflicts` | Surface contradictions |
| `engram_resolve` | Settle disagreements |
| `engram_promote` | Graduate ephemeral memory to durable |

### CLI Commands

```bash
engram install              # Auto-detect IDEs and configure MCP
engram serve               # Start MCP server (stdio mode)
engram serve --http        # Start MCP server (HTTP mode)
engram setup              # One-command workspace setup
engram status             # Show workspace status
engram info               # Display detailed workspace info
engram whoami             # Show current user identity
engram search <query>     # Query workspace from terminal
engram stats              # Show workspace statistics
engram config show        # Display configuration
engram config set <key>   # Update configuration
engram tail               # Live stream of workspace commits
engram verify             # Verify installation
engram doctor             # Diagnose setup issues
engram completion <shell> # Install shell tab completion
```

---

## Conflict Detection

Every commit triggers LLM-powered conflict detection. The entire fact corpus is scanned — no fact is skipped.

On each commit, all active facts are batched into 8k-token context windows and checked for semantic contradictions. Batches run concurrently. Commits return instantly; conflicts surface on the dashboard as they're found.

---

## The Detective

Pairwise contradiction detection misses the most common failure mode: not two facts that directly contradict, but a reversal across time. Engram reads the workspace's commit history as a **chronological story** and asks: *where would a new agent get confused about what's currently true?*

It catches reversals, ambiguity between active facts, and stale claims that pairwise detection can't see. A forgetting curve keeps the signal-to-noise ratio high.

This is Engram's moat — designed as a layer that works on top of Engram's memory or any other agent memory system.

Full design: [`docs/CONFLICT_DETECTIVE.md`](./docs/CONFLICT_DETECTIVE.md)

---

## Memory That Forgets on Purpose

Not everything deserves to stick around. Scratchpad facts expire in 24h, unverified observations after 90 days. Decisions and confirmed facts are kept forever. Old context stops crowding out what matters now.

---

## Research Foundation

Engram exists because of a paper.

**[Multi-Agent Memory from a Computer Architecture Perspective: Visions and Challenges Ahead](https://arxiv.org/abs/2603.10062)** — Yu et al. (2026), UCSD SysEvol — is the primary intellectual foundation of this project. It reframes multi-agent memory as a computer architecture problem: coherence, consistency, and shared state across concurrent agents. That framing is what Engram is built to implement in practice.

The rest of the literature informs specific subsystems:

- **[Xu et al. (2025)](https://arxiv.org/abs/2502.12110)** — A-Mem's Zettelkasten structure for fact enrichment
- **[Rasmussen et al. (2025)](https://arxiv.org/abs/2501.13956)** — Graphiti's bitemporal modeling for temporal validity
- **[Hu et al. (2026)](https://arxiv.org/abs/2512.13564)** — Survey confirming shared memory as an open frontier
- **[Alqithami (2025)](https://arxiv.org/abs/2512.12856)** — FiFA: forgetting-by-design improves agent coherence

Full literature review: [`docs/LITERATURE.md`](./docs/LITERATURE.md)  
Implementation details: [`docs/IMPLEMENTATION.md`](./docs/IMPLEMENTATION.md)

---

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

For a full description of the test suite — what each module covers and the per-test breakdown for lifecycle and conflict tests — see [`tests/TESTS.md`](./tests/TESTS.md).

---

## License

[Apache 2.0](./LICENSE)

---

<div align="center">
<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge.</sub>
</div>
