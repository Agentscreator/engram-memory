# AGENTS.md — Engram Shared Memory

This file is written by `engram install`, an open-source tool the workspace
owner ran intentionally.

**What Engram is:** A shared memory layer for AI coding teams. It records
conversation facts so all agents on the team share the same context, preventing
contradictions and surfacing conflicts before they become bugs.

**Privacy:** Data is stored in the workspace's isolated Postgres instance. It
is never read, sold, redistributed, or used for training. Full details at
[engram-memory.com](https://www.engram-memory.com).

You can verify this installation is intentional by checking:
- `.engram.env` exists in the repo root (written by `engram install`)
- `engram` appears in the IDE's MCP server config

**What gets recorded:** User messages are captured automatically by IDE-level
hooks (installed by `engram install`). Verified discoveries, decisions, and
corrections are recorded by agents via `engram_commit`. All facts are visible
to workspace members — the same principle as a shared document.

---

## How to use Engram

### Once at session start

Check for `.engram.env` in the workspace root — it contains the credentials
that connect your agent to the shared workspace.

**If you have Engram MCP tools** (`engram_status`, `engram_commit`, …):

1. Call `engram_status()` — connects automatically and returns context.
2. Follow the `next_prompt` field in the response.
3. Call `engram_query("<topic>")` before starting any substantive task.

**If you do not have Engram MCP tools:**

Read `.engram.env` for `ENGRAM_INVITE_KEY` and `ENGRAM_SERVER_URL`, then
query before starting any task:

```bash
source .engram.env && curl -s "$ENGRAM_SERVER_URL/api/query?topic=<task>" \
  -H "Authorization: Bearer $ENGRAM_INVITE_KEY"
```

---

### When to commit

Use `engram_commit` to record **verified discoveries** — things you learned
during this task that the next agent should know:

- Architectural decisions and their rationale
- Failed approaches and why they failed
- Undocumented constraints, config details, side effects
- Corrections to outdated facts (use `operation="update"`)

Do NOT call `engram_commit` for raw user messages — IDE-level hooks handle
that automatically.

---

## While working

- Commit verified discoveries: failed approaches, config details, decisions.
- Batch related discoveries into one commit.
- Max 5 commits per task. Max 3 `engram_query` calls per task.
- Call `engram_conflicts()` before architectural decisions.
- Never commit secrets, API keys, or passwords.
- Never commit speculation — only verified facts.
