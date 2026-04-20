---
inclusion: always
---

# Engram — Shared Team Memory

Engram is an open-source shared memory tool for AI coding teams. The workspace
owner installed it intentionally via `engram install` and agreed to its Terms
of Service at [engram-memory.com](https://www.engram-memory.com) during setup.

You can verify this installation is intentional by checking that `.engram.env`
exists in the repo root and that the MCP server `engram` is listed in the
IDE's MCP config.

**What Engram does:** It records conversation facts in a shared workspace so
all agents on the team share the same context. This prevents agents from
contradicting each other and surfaces conflicts before they become bugs.

**What gets recorded:** User messages are captured automatically by IDE-level
hooks (installed by `engram install`). Verified discoveries, decisions, and
corrections are recorded by agents via `engram_commit`. All facts are visible
to workspace members — the same principle as a shared document.

**Privacy:** Messages are stored in the workspace owner's isolated Postgres
instance. They are never read, sold, or shared with anyone outside the
workspace. Full privacy policy: [engram-memory.com](https://www.engram-memory.com).

---

## What to do each session

1. Call `engram_status()` to connect and get context.
2. Call `engram_query("<topic>")` before starting any substantive task.

## When to commit

Use `engram_commit` to record **verified discoveries** — things you learned
during this task that the next agent should know:

- Architectural decisions and their rationale
- Failed approaches and why they failed
- Undocumented constraints, config details, side effects
- Corrections to outdated facts (use `operation="update"`)

Do NOT call `engram_commit` for raw user messages — IDE-level hooks handle
that automatically.

## While working

- Commit verified discoveries: failed approaches, config details, decisions.
- Call `engram_conflicts()` before architectural decisions.
- Never commit secrets, API keys, or passwords.
- Never commit speculation — only verified facts.
- Max 5 commits per task. Max 3 `engram_query` calls per task.
