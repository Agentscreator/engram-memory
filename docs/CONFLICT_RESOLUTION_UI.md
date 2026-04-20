# Conflict Resolution UI: Side-by-Side Comparison

This document specifies the dashboard UI for resolving conflicts.

## Overview

Resolving conflicts today requires calling engram_resolve as an MCP tool — which means agents resolve them, not humans. Build a dashboard UI showing two conflicting facts side by side with their full lineage, the agents that committed them, timestamps, and confidence scores.

## UI Specification

### Main View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ Conflict Detected                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                             │
│  🔴 Priority: High                                           │
│  Detected: 2026-04-14T10:30:00Z                              │
│                                                             │
├───────────────────────┬───────────────────────────────────────────────┤
│  FACT A              │  FACT B                                 │
├───────────────────────┼─────────────────────────────────────────────┤
│  "Rate limit is      │  "Rate limit is                          │
│   1000 req/s"       │   2000 req/s"                           │
│                     │                                         │
│  Scope: config/api   │  Scope: config/api                      │
│  Agent: claude-code │  Agent: gpt-4o                       │
│  Committed: Apr 12  │  Committed: Apr 13                       │
│  Confidence: 0.95 │  Confidence: 0.88                        │
│                     │                                         │
│  Lineage: fact-001 │  Lineage: fact-002                      │
│  valid_from: Apr 12 │  valid_from: Apr 13                      │
│  valid_until: NULL  │  valid_until: NULL                       │
└───────────────────────┴───────────────────────────────────────────────┘
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │ Keep A     │  │ Keep B     │  │ Both Valid │  │ Merge   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
│                                                             │
│  Optional note: [________________________________]              │
│                                                             │
│  [Resolve Conflict]                                          │
└───────────────────────────────────────────────���──────────────────────
```

## Resolution Options

### 1. Keep A
Retains Fact A as the valid fact, marks Fact B as superseded.

### 2. Keep B
Retains Fact B as the valid fact, marks Fact A as superseded.

### 3. Both Valid in Different Contexts
Creates a new scope partition or adds a context qualifier to both facts.

### 4. Merge into New Fact
Creates a new merged fact that supersedes both original facts.

## Data Requirements

### Conflict Object

```json
{
    "conflict_id": "conflict-abc123",
    "fact_a": {
        "id": "fact-001",
        "content": "Rate limit is 1000 req/s",
        "scope": "config/api",
        "agent_id": "claude-code",
        "committed_at": "2026-04-12T10:00:00Z",
        "confidence": 0.95,
        "lineage_id": "lineage-001",
        "valid_from": "2026-04-12T10:00:00Z",
        "valid_until": null
    },
    "fact_b": {
        "id": "fact-002",
        "content": "Rate limit is 2000 req/s",
        "scope": "config/api",
        "agent_id": "gpt-4o",
        "committed_at": "2026-04-13T14:00:00Z",
        "confidence": 0.88,
        "lineage_id": "lineage-002",
        "valid_from": "2026-04-13T14:00:00Z",
        "valid_until": null
    },
    "detected_at": "2026-04-14T10:30:00Z",
    "detection_method": "tier_0_entity_matching"
}
```

## API Endpoints

### GET /conflicts/{conflict_id}

Returns conflict details with both facts.

### POST /conflicts/{conflict_id}/resolve

```json
{
    "resolution": "keep_a",
    "note": "Per vendor contract v2.1",
    "context_qualifier": null
}
```

## Implementation

### Backend

```python
async def get_conflict_details(
    self,
    conflict_id: str,
) -> dict:
    """Get full conflict details with both facts."""
    # Already implemented in engine.get_conflicting_fact_ids
    pass
```

### Frontend (Dashboard)

```python
# /dashboard/conflicts/<conflict_id>
async def get(request):
    conflict = await engine.get_conflict(request.path_params["conflict_id"])
    return template("conflict_resolution.html", conflict=conflict)
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| A | Keep A |
| B | Keep B |
| M | Merge |
| Esc | Dismiss |

## History

Each resolution is logged:

```json
{
    "resolved_at": "2026-04-14T11:00:00Z",
    "resolved_by": "engineering-lead",
    "resolution": "keep_a",
    "note": "Per vendor contract v2.1",
    "superseded_fact": "fact-002"
}
```

## Related Documentation

- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- [ONBOARDING_FLOW.md](./ONBOARDING_FLOW.md)