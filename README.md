<div align="center">

# Engram

**Shared memory for your AI agents**

Every agent sees the same verified facts. When agents contradict each other, Engram catches it before it becomes a bug.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-8b5cf6?style=flat-square)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square)](https://python.org)

</div>

---

## How It Works

Your AI agents work in parallel — or lose their memory once the session ends. One agent learns something, another learns something different, and now they disagree. Engram detects that and surfaces it before it becomes a bug.

Every agent's messages are automatically committed to shared memory as facts. And the best part — you can add team members who are also working on your project.

## Why It Matters

Conflict detection for AI agents is as foundational as accounting was for finance. Accounting didn't just track money — it created the liability infrastructure that made the entire financial economy possible.

When agents make consequential decisions, someone has to be accountable. Engram creates a verifiable audit trail — every instruction, every committed fact, every contradiction surfaced — so liability lands on the organizations deploying agents.

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

Use the arrow keys to navigate and Enter to select:

- **conflicts** — review open memory conflicts and resolve them without leaving your terminal
- **search** — query what your agents collectively know
- **tail** — stream facts as agents commit them in real time
- **merge** — pull durable facts from another workspace into this one, at any time
- **status** — inspect your workspace connection and settings

You can also resolve conflicts visually at [engram-memory.com/dashboard](https://engram-memory.com/dashboard).

---

### If you're joining an existing workspace

**Step 1 — Install Engram**

Run the same installer as above for your OS. This configures your IDE and installs the auto-commit hook.

**Step 2 — Accept the invite**

Click the invite link, sign in at [engram-memory.com](https://engram-memory.com), and accept the workspace invite. Your agent will connect automatically.

Then repeat **Steps 4 and 5** above.

---

## What Gets Committed

Every message you send to your AI agent is recorded in shared memory as a fact. The agent's responses are not stored — only your inputs. This gives every agent a running record of what was asked, decided, and discovered.

Facts accumulate. The next time any agent opens this codebase — yours or anyone else with workspace access — they start with the full context of everything that's been verified.

---

## Conflict Detection

Every commit triggers conflict detection across the full fact corpus. When two agents have recorded contradictory facts, Engram surfaces the contradiction on the dashboard before either agent acts on stale information.

Engram reads the workspace's commit history as a chronological story and asks: *where would a new agent get confused about what's currently true?* It catches reversals and ambiguity that simple pairwise comparison misses.

Full design: [`docs/CONFLICT_DETECTIVE.md`](./docs/CONFLICT_DETECTIVE.md)

### Resolving Conflicts

Conflicts are surfaced automatically. You choose how to resolve them.

**Option 1 — Terminal (recommended)**

```bash
engram
```

This opens the Engram interactive shell directly in your terminal. Arrow-key through the menu, select **conflicts**, and step through each open contradiction. For each one you can:

- **Pick a winner** — mark one fact as authoritative and retire the other
- **Merge** — synthesize both into a single revised fact
- **Dismiss** — mark as a known ambiguity that doesn't require resolution

No browser required. No context switching. The conflict is resolved in your workspace and propagated to every agent instantly.

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

Type `engram` in any terminal to open the interactive shell — an arrow-key menu for conflicts, search, live fact streaming, and workspace management.

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
<sub>An engram is the physical trace a memory leaves in the brain — the actual unit of stored knowledge.</sub>
</div>
