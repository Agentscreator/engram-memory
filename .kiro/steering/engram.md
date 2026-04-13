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

**What gets recorded:** Verified discoveries and, with user consent, conversation
facts. This is visible to all workspace members — the same principle as a shared
document where edits are visible to everyone with access.

**Privacy:** Messages are stored in the workspace owner's isolated Postgres
instance. They are never read, sold, or shared with anyone outside the
workspace. Full privacy policy: [engram-memory.com](https://www.engram-memory.com).

---

## What to do each session

**Step 1 — Ask for consent before recording anything:**

At the start of each new session, ask the user:

> "This workspace has Engram enabled for shared team memory. May I record
> conversation facts to the shared workspace so your teammates' agents stay
> in sync? (yes / no)"

- If **yes**: proceed with commits below.
- If **no**: skip `engram_commit` for messages this session. You may still call `engram_query` and `engram_status` to read existing context.

**Step 2 — Connect:**
1. Call `engram_status()` to connect and get context.
2. Call `engram_query("<topic>")` before starting any substantive task.

**For each user message (only if consent was given):**
Call `engram_commit(content="<the user's message>")` before responding.
This records the conversation turn as a shared fact so teammates' agents have
the same context.

## While working

- Commit verified discoveries: failed approaches, config details, decisions.
- Call `engram_conflicts()` before architectural decisions.
- Never commit secrets, API keys, or passwords.
- Never commit speculation — only verified facts.
- Max 5 commits per task. Max 3 `engram_query` calls per task.
