# Engram Pricing & Usage Tiers

All plans include LLM suggestions, conflict detection (forgetting-based), and the full MCP toolset. Plans differ only by monthly commit volume.

## Tiers

| Tier    | Price   | Commits/mo | Overage          |
|---------|---------|------------|------------------|
| Free    | $0      | 500        | Workspace paused |
| Builder | $12/mo  | 5,000      | $0.015/commit    |
| Team    | $39/mo  | 25,000     | $0.015/commit    |
| Scale   | $99/mo  | 100,000    | $0.015/commit    |

## What counts as a commit?

Every call to `engram_commit` (including duplicates that are deduplicated, and facts that are later forgotten by the detective's forgetting curve) counts toward the monthly limit. The `operation="none"` no-op does not count.

## Features included on all plans

- MCP server (stdio + HTTP)
- Conflict detection (entity, NLI, narrative coherence)
- LLM suggestions for conflict resolution
- Forgetting-based memory management
- Dashboard at engram-memory.com/dashboard
- Invite key-based team joining

## In-Product Upgrade Prompts

When users approach their limits, Engram displays contextual upgrade prompts:

### Commit Limit Warning
```
⚠ You've used 450/500 commits (90%)
Upgrade to Builder for 5,000 commits/mo → [Upgrade Now]
```

### Workspace Paused (free tier)
```
⚠ Workspace paused — 500 commits/month limit reached
Upgrade at https://www.engram-memory.com/dashboard to continue.
```

## Checking Your Usage

```bash
# Check current usage
engram stats --json
```

## Implementation Notes

- Usage is tracked per workspace per calendar month
- Free tier pauses the workspace when the limit is reached
- Paid tiers allow overage at $0.015/commit above the limit
- Stripe handles subscriptions and metered billing
- Legacy plan names (`hobby` → `free`, `pro` → `builder`) are aliased automatically
