# Structured Audit Log for Memory Operations

This document specifies the audit log infrastructure for SOC 2 compliance.

## Overview

Every engram_commit, engram_resolve, and engram_query should produce a structured audit event:
- **who** (agent ID)
- **what** (fact ID, operation)
- **when** (timestamp)
- **why** (optional reason field)

## Current Schema

The infrastructure already exists in the schema:

```sql
-- audit_events table (already in schema)
CREATE TABLE audit_events (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    event_type      TEXT NOT NULL,  -- 'commit', 'resolve', 'query'
    agent_id       TEXT NOT NULL,
    target_id     TEXT,            -- fact_id for commits/resolves
    scope          TEXT,
    details       JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Event Types

### engram_commit Event

```json
{
    "event_type": "commit",
    "agent_id": "claude-code",
    "target_id": "fact-abc123",
    "scope": "auth",
    "details": {
        "content_hash": "sha256:...",
        "confidence": 0.95,
        "fact_type": "observation",
        "lineage_id": "lineage-001",
        "valid_from": "2026-04-14T10:00:00Z",
        "ttl_days": 30
    }
}
```

### engram_resolve Event

```json
{
    "event_type": "resolve",
    "agent_id": "claude-code",
    "target_id": "conflict-xyz",
    "scope": "config",
    "details": {
        "fact_a_id": "fact-001",
        "fact_b_id": "fact-002",
        "resolution": "keep_a",
        "reason": "fact_a has higher confidence"
    }
}
```

### engram_query Event

```json
{
    "event_type": "query",
    "agent_id": "claude-code",
    "target_id": null,
    "scope": "auth",
    "details": {
        "query_text": "rate limit config",
        "results_count": 5,
        "as_of": "2026-04-14T10:00:00Z"
    }
}
```

## Implementation

### Storage Layer

```python
async def insert_audit_entry(
    self,
    event_type: str,
    agent_id: str,
    target_id: str | None = None,
    scope: str | None = None,
    details: dict | None = None,
) -> None:
    """Insert an audit event."""
    await self.db.execute("""
        INSERT INTO audit_events (id, workspace_id, event_type, agent_id, target_id, scope, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        self.workspace_id,
        event_type,
        agent_id,
        target_id,
        scope,
        json.dumps(details) if details else None,
    ))
```

### MCP Tool: engram_audit_log

```python
@mcp.tool()
async def engram_audit_log(
    event_type: str | None = None,
    agent_id: str | None = None,
    scope: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query the audit log.
    
    Parameters:
    - event_type: Filter by 'commit', 'resolve', 'query'.
    - agent_id: Filter by agent.
    - scope: Filter by scope.
    - from_date: ISO 8601 start date.
    - to_date: ISO 8601 end date.
    - limit: Max results (default 100).
    
    Returns: {events: [...], total_count}
    """
```

## Retention Policy

| Data Type | Retention |
|-----------|-----------|
| Commits | 2 years |
| Resolves | 2 years |
| Queries | 90 days |
| Aggregations | Permanent |

## Compliance Use Cases

### SOC 2 Audit Trail

```sql
-- Who accessed what and when
SELECT agent_id, event_type, target_id, scope, created_at
FROM audit_events
WHERE workspace_id = 'ws-001'
AND created_at BETWEEN '2026-01-01' AND '2026-03-31'
ORDER BY created_at DESC;
```

### Incident Investigation

```sql
-- What happened before a security incident
SELECT *
FROM audit_events
WHERE workspace_id = 'ws-001'
AND created_at < '2026-04-10T14:00:00Z'
AND created_at > '2026-04-10T13:00:00Z'
ORDER BY created_at DESC;
```

## Dashboard View

```
┌─────────────────────────────────────────────┐
│ Audit Log                                   │
├─────────────────────────────────────────────┤
│ Filters: [Event ▼] [Agent ▼] [Scope ▼]      │
│                                             │
│ 2026-04-14T10:30:00Z                       │
│ claude-code → commit → fact-abc123 (auth)   │
│                                            │
│ 2026-04-14T10:25:00Z                     │
│ gpt-4o → resolve → conflict-xyz (config)  │
│                                            │
│ 2026-04-14T10:20:00Z                     │
│ claude-code → query → (results: 5)         │
└─────────────────────────────────────────────┘
```

## Related Documentation

- [MIGRATION_SCHEMA.md](./MIGRATION_SCHEMA.md)
- [IMPLEMENTATION.md](./IMPLEMENTATION.md)