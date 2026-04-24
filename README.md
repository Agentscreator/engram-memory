<div align="center">

# Engram

**Active memory for your AI agents — outlasting sessions, never sleeping**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-8b5cf6?style=flat-square)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square)](https://python.org)

</div>

---

## How It Works

Your brain never turns off — even when you're asleep, it's consolidating memory, surfacing patterns, preparing for what comes next. Your agents don't work that way. They lose everything the moment a session ends.

Engram changes that. Every agent's messages are committed to active memory as verified facts — and Engram keeps working while you sleep, reading through your codebase, learning what changed, and surfacing contradictions before any agent acts on stale information. The longer it runs, the more it knows. From the moment you install it, Engram is already studying your codebase.

You can add team members and every agent on the workspace shares the same memory. Active hours are tiered by plan — see the [pricing page](https://engram-memory.com/dashboard) in your dashboard.

## Why It Matters

Conflict detection for AI agents is as foundational as accounting was for finance. Accounting didn't just track money — it created the liability infrastructure that made the entire financial economy possible.

When agents make consequential decisions, someone has to be accountable. Engram creates a verifiable audit trail — every instruction, every committed fact, every contradiction surfaced — so liability lands on the organizations deploying agents.

## North Star

Zero bugs in AI-assisted development. Every agent shares the same verified truth — contradictions between what agents believe and what the code says are caught before they become bugs.

---

## Getting Started

### If you're setting up Engram for your team

**Step 1 — Create a workspace**

Go to [engram-memory.com/dashboard](https://engram-memory.com/dashboard), sign in, and create a new workspace. You'll get an invite link to share with others working on your project.

**Step 2 — Run the installer**

**macOS / Linux:**
```bash
curl -fsSL https://engram-memory.com/install | sh
```

**Windows (PowerShell):**
```powershell
irm https://engram-memory.com/install.ps1 | iex
```

**Windows (CMD):**
```cmd
curl -fsSL https://engram-memory.com/install.cmd -o install.cmd && install.cmd && del install.cmd
```

This configures your IDE and installs the auto-commit hook. Restart your editor when it's done.

**Step 3 — Ask your agent to connect**

```
"Set up Engram for my agents"
```

**Step 4 — Manage memory from your terminal**

Once Engram is installed, type `engram` in any terminal to open the interactive shell:

```bash
engram
```

From here you can ask questions, search memory, and inspect what Engram knows about your workspace.

You can also ask your agent to merge memory spaces — it will pull durable facts from another workspace into this one automatically.

---

### If you're joining an existing workspace

**Step 1 — Install Engram**

Run the same installer as above for your OS. This configures your IDE and installs the auto-commit hook.

**Step 2 — Accept the invite**

Click the invite link, sign in at [engram-memory.com](https://engram-memory.com), and accept the workspace invite. Your agent will connect automatically.

Then repeat **Steps 3 and 4** above.

---

## What Gets Committed

Every message you send to your AI agent — and every agent response — is recorded in shared memory as a fact. This gives every agent a running record of what was asked, what was decided, and what was discovered.

Facts accumulate. The next time any agent opens this codebase — yours or anyone else with workspace access — they start with the full context of everything that's been verified.

---

## Conflict Resolution

Engram detects and resolves conflicts on your behalf — no manual review required.

**Agent vs. agent** — Every commit triggers detection across the full fact corpus. When two agents record contradictory facts, Engram resolves the conflict automatically: it uses Claude to evaluate both facts and pick the winner, falling back to a confidence-and-recency heuristic when no API key is configured. The losing fact's validity window is closed so it no longer surfaces in queries.

**Agent vs. codebase** — On startup and every 10 minutes, Engram scans your codebase — config files, dependency manifests, Dockerfiles — and compares what it finds against what agents have committed to memory. When an agent claims the rate limit is 1000 but the config says 500, the stale agent memory is resolved against the ground truth automatically.

Conflicts appear in your dashboard's **Conflicts** tab with the resolution reasoning attached. Nothing sits open waiting for you.

Full design: [`docs/CONFLICT_DETECTIVE.md`](./docs/CONFLICT_DETECTIVE.md)

---

## Privacy & Data

- **Isolated per workspace.** Your data is never mixed with other workspaces.
- **Encrypted in transit and at rest.**
- **Never used for training.** Your facts are never read, analyzed, or shared with anyone outside your workspace.
- **Right to erasure.** Delete your workspace and every fact is gone. GDPR-compliant erasure is built into the core engine.

---

## IDE Support

Engram works with any AI coding environment. First-class support for:

- [Claude Code](./docs/quickstart/claude-code.md)
- [Cursor](./docs/quickstart/cursor.md)
- [Windsurf / Kiro](./docs/quickstart/windsurf.md)
- [VS Code (Copilot)](./docs/quickstart/vscode-copilot.md)
- [Zed](./docs/quickstart/zed.md)

Agents without MCP support connect via the REST API using the credentials in `.engram.env`. Instructions are in `AGENTS.md` at the root of every Engram-enabled repo.

Framework integrations:

- [LangChain / LangGraph](./docs/integrations/langchain.md)
- [OpenAI Agents SDK](./docs/integrations/openai-agents.md)
- [open-multi-agent](https://github.com/JackChen-me/open-multi-agent) — TypeScript multi-agent orchestration engine.

> **Try open-multi-agent** — If you're building multi-agent teams in TypeScript, [open-multi-agent](https://github.com/JackChen-me/open-multi-agent) is the easiest way to get started. One `runTeam()` call, three runtime dependencies, multi-model support. Pairs naturally with Engram for shared memory across your agent team.

---

## CLI Reference

Type `engram` in any terminal to open the interactive shell — search memory, inspect facts, and query what your agents know.

```bash
engram                  # Open the interactive shell (conflicts, search, status, and more)
```


---

## Self-Hosting

Engram runs on any Postgres database. Point it at your own instance and your facts never leave your infrastructure.

```bash
export ENGRAM_DB_URL='postgres://user:password@host:port/database'
engram serve --http
```

Full setup: [`docs/DEVELOPER_SETUP.md`](./docs/DEVELOPER_SETUP.md)

---

## Research Foundation

Engram is built on a body of research that reframes multi-agent memory as a computer architecture problem — coherence, consistency, and shared state across concurrent agents.

- **[Yu et al. (2026)](https://arxiv.org/abs/2603.10062)** — Primary intellectual foundation. Multi-agent memory from a computer architecture perspective.
- **[Xu et al. (2025)](https://arxiv.org/abs/2502.12110)** — A-Mem's Zettelkasten structure for fact enrichment
- **[Rasmussen et al. (2025)](https://arxiv.org/abs/2501.13956)** — Graphiti's bitemporal modeling for temporal validity
- **[Hu et al. (2026)](https://arxiv.org/abs/2512.13564)** — Survey confirming shared memory as an open frontier

Full literature review: [`docs/LITERATURE.md`](./docs/LITERATURE.md)

---

## Contributing

PRs welcome. Run `make help` for common development commands, then see [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`HIRING.md`](./HIRING.md) for paid contract work ($125–185/hour).

---

## License

[Apache 2.0](./LICENSE)

---

<div align="center">
<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge. Active memory that never sleeps.</sub>
</div>
