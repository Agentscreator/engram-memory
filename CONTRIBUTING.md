<div align="center">

# Contributing to Engram

*This is built in the open. Early contributors shape what it becomes — and become part of it.*

</div>

---

## Five-Minute Quick Start

```bash
# 1. Fork the repo on GitHub, then:
git clone https://github.com/YOUR-USERNAME/Engram.git
cd Engram

# 2. Install
./install.sh          # macOS / Linux
# or: pip install -e ".[dev]"

# 3. Run the MCP server locally
python -m engram.cli serve --http

# 4. Open the local dashboard
# http://127.0.0.1:7474/dashboard

# 5. Ask your agent (Claude Code, Cursor, etc.) to set up Engram
# Your agent will call engram_init and you'll see it working.

# 6. Make a change → open a PR
git checkout -b your-feature-or-fix
```

That's it. If any step fails, open an issue — a broken setup path is itself a valid first contribution.

---

## Shared Agent Memory (Engram Workspace)

All contributors' AI agents share the same Engram workspace so your agent has the same context and memory as the rest of the team. Before starting work, have your agent join with this invite key:

```
ek_live_TXeVIk5ENmmWFHMR_-wq_XgwN6f5So8nIR8CVGAmhi5bzxZQQP13t7gOhGgGIhVWFmJTYuKn3kn_R22kwzxHEcH-BD2KIKS8EhXN4dxiry6HT1-g9CQ6g_S1JLnLJM4PKBeSahokEdHG9evVKSSQlaqe-oJnnBHiSpXXRkaXCcy8maGo2RPPFw
```

Your agent will call `engram_join` with this key and automatically connect to the shared workspace. This means every agent working on Engram sees the same verified facts, architectural decisions, and known issues.

---

## Good First Contributions

Not sure where to start? These are always useful:
- **Improve error messages** — vague errors are bugs
- **Add test coverage** for an edge case you noticed
- **Document a non-obvious behavior** in a code comment or the README
- **Pick a roadmap item** from [README.md#roadmap](./README.md#roadmap) — comment on the issue before starting so we can align
- **Add a quickstart guide** for your favorite IDE in `docs/quickstart/` — we already have Claude Code, Cursor, and VS Code, but need more

---

## Before You Start

Read the [README](./README.md). Understand the problem Engram is solving. The best contributions come from people who've felt the pain — agents re-discovering things that were already known, knowledge evaporating at session end.

If something is unclear or the design raises questions, **open a discussion before writing code.** Early-stage projects benefit more from alignment than from PRs that go in a different direction.

<br />

## Ways to Contribute

### Open a Discussion
The design is still being shaped. If you have thoughts on the API surface, the storage model, the conflict detection approach, or anything else — open a GitHub Discussion and share them. That is a real contribution.

### File an Issue
Found a bug, a gap in the design, or something that doesn't make sense? Open an issue. Be specific. Include what you expected, what happened, and what context matters.

### Submit a Pull Request
Code contributions are welcome. See the workflow below.

<br />

## Development Workflow

**1. Fork and clone**
```bash
git clone https://github.com/your-username/Engram.git
cd Engram
```

**2. Create a branch**
```bash
git checkout -b your-feature-or-fix
```

Use a descriptive branch name. `fix/conflict-detection-threshold` is better than `fix`.

**3. Make your changes**

Keep changes focused. One concern per PR. If you find yourself touching unrelated things, split them out.

**4. Test your work**

Don't submit a PR you haven't run yourself. If tests don't exist yet for what you're changing, add them or note it clearly in the PR description.

**5. Open a PR**

Write a clear description:
- What does this change?
- Why is it the right change?
- Is there anything the reviewer should pay particular attention to?

<br />

## What Good PRs Look Like

- **Focused.** One change, one reason.
- **Explained.** The description covers the why, not just the what.
- **Clean.** No dead code, no commented-out experiments, no unrelated formatting changes.
- **Tested.** Ideally with new tests. At minimum, not breaking existing ones.

<br />

## What to Avoid

- PRs without context or explanation
- Large refactors without prior discussion
- Changes to core API surface without an issue or discussion first
- Dependency additions without a clear reason

If you're unsure whether something is in scope, ask first. The cost of a quick discussion is much lower than a PR that can't be merged.

<br />

## Code Style

Consistency matters more than any particular style. Match what's already there. If you're introducing something new, be deliberate about it and note it in the PR.

<br />

## Roadmap Items

The [README roadmap](./README.md#roadmap) lists what's being built. These are good starting points if you want to contribute but aren't sure where. Comment on an issue or open a discussion before picking one up — some items have design decisions that need to happen first.

<br />

## Ground Rules

- Be direct and specific in issues and reviews. Be respectful.
- Disagreement on approach is fine. Resolve it through discussion, not pressure.
- If you commit to something, follow through. If you can't, say so early.

<br />

## Questions

Not sure where to start? Open a discussion. Describe what you're thinking, what interests you, or what problem you've run into. That's enough to start a conversation.


<br />

---

<div align="center">

*Every great project was once just a problem someone cared about enough to fix.*
*Glad you're here.*

</div>
