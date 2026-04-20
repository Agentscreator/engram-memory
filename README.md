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

Most agent errors aren't disagreements between agents. They're disagreements between the agent and code. Engram verifies what agents believe exist and what the code actually says.

### Demo Video

[![Watch the demo](https://img.youtube.com/vi/KFIjxyTO2q4/maxresdefault.jpg)](https://youtu.be/KFIjxyTO2q4)

<video src="docs/demo-video-1.mp4" controls width="100%"></video>

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

From here you can ask questions or talk to Engram about your workspace and resolve conflicts.

You can also ask your agent to merge memory spaces — it will pull durable facts from another workspace into this one automatically.

You can also resolve conflicts visually at [engram-memory.com/dashboard](https://engram-memory.com/dashboard).

---

### If you're joining an existing workspace

**Step 1 — Install Engram**

Run the same installer as above for your OS. This configures your IDE and installs the auto-commit hook.

**Step 2 — Accept the invite**

Click the invite link, sign in at [engram-memory.com](https://engram-memory.com), and accept the workspace invite. Your agent will connect automatically.

Then repeat **Steps 3 and 4** above.

---

## What Gets Committed

Every message you send to your AI agent is recorded in shared memory as a fact. The agent's responses are not stored — only your inputs. This gives every agent a running record of what was asked, decided, and discovered.

Facts accumulate. The next time any agent opens this codebase — yours or anyone else with workspace access — they start with the full context of everything that's been verified.

---

## Conflict Detection

Engram runs conflict detection at two levels:

**Agent vs. agent** — Every commit triggers detection across the full fact corpus. When two agents have recorded contradictory facts, Engram surfaces the contradiction before either agent acts on stale information. It reads the workspace's commit history as a chronological story and asks: *where would a new agent get confused about what's currently true?*

**Codebase vs. agent** — On startup and every 10 minutes, Engram scans your codebase — config files, dependency manifests, Dockerfiles — and compares what it finds against what agents have committed to memory. When an agent claims the rate limit is 1000 but the config says 500, that conflict is surfaced immediately.

Full design: [`docs/CONFLICT_DETECTIVE.md`](./docs/CONFLICT_DETECTIVE.md)

### Resolving Conflicts

Conflicts are surfaced automatically. You choose how to resolve them.

**Option 1 — Terminal (recommended)**

```bash
engram
```


**Option 2 — Web dashboard**

Visit [engram-memory.com/dashboard](https://engram-memory.com/dashboard) to review and resolve conflicts in a visual interface — useful when you want to inspect the full fact lineage or manage multiple workspaces at once.

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

---

## CLI Reference

Type `engram` in any terminal to open the interactive shell — it opens straight to your open conflicts with a command prompt to resolve them.

```bash
engram                  # Open the interactive shell (conflicts, search, status, and more)
```

Individual commands are also available directly:

```bash
engram conflicts        # List open memory conflicts
engram search <query>   # Query workspace memory
engram tail             # Live stream of commits as they happen
engram merge --source-key <key>  # Merge durable facts from another workspace into this one
engram status           # Inspect workspace connection and settings
engram install          # Configure your IDE and install the auto-commit hook
engram verify           # Check that everything is connected
engram stats            # Privacy-preserving workspace analytics
engram import <path>    # Bulk-ingest Markdown/text docs
engram serve --http     # Run the MCP server locally (port 7474)
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

PRs welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`HIRING.md`](./HIRING.md) for paid contract work ($125–185/hour).

---

## License

[Apache 2.0](./LICENSE)

---

<div align="center">
<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge. Active memory that never sleeps.</sub>
</div>
