# Workspace Federation (Issue #12)

## Overview

Workspace federation allows two workspaces to connect and share knowledge **without merging** their data, enabling cross-team collaboration while maintaining isolation.

## Use Cases

1. **Security teams** sharing IOCs without exposing infrastructure
2. **Platform teams** sharing patterns without exposing code
3. **Multiple subteams** in large organizations
4. **Contractors** getting read-only access to specific knowledge

## Architecture

```
┌─────────────────────────────────────────────────────┐
│           Federation Network                        │
│                                              │
│  Workspace A ─────► Proxy ─────► Workspace B   │
│  (team-a)           ↕          (team-b)         │
│  - facts: open     query     - facts: open      │
│  - agents: own    respond  - agents: own       │
└─────────────────────────────────────────────────────┘
```

## Key Concepts

| Concept | Description |
|---------|-----------|
| **Federation link** | Connection between two workspaces |
| **Proxy** | Forwards queries between workspaces |
| **Read-through** | Query local, then federated |
| **Remote facts** | Facts from linked workspace |

## Data Sharing Modes

| Mode | Local Write | Local Read | Federated Read | Federated Write |
|------|-----------|----------|------------|-------------|
| **Full** | ✅ | ✅ | ✅ | ❌ |
| **Read-only** | ✅ | ✅ | ✅ | ❌ |
| **Facts only** | ❌ | ✅ | ❌ | ❌ |

### Detailed Permissions

```
Full:
  - Can read all local facts
  - Can read federated facts  
  - Can write local facts
  - Cannot write to remote

Read-only:
  - Can read all local facts
  - Can read federated facts
  - Cannot write local facts
  - Cannot write to remote
```

## Implementation

### Database Schema

```sql
-- Federation connections
CREATE TABLE federation_links (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id),
    remote_workspace_id TEXT,
    mode TEXT CHECK (mode IN ('full', 'read-only', 'facts-only')),
    secret_hash TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(workspace_id, remote_workspace_id)
);

-- Cached remote facts (for performance)
CREATE TABLE federated_facts_cache (
    id TEXT,
    workspace_id TEXT,
    remote_fact_id TEXT,
    remote_workspace_id TEXT,
    content TEXT,
    scope TEXT,
    fetched_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workspace_id, remote_fact_id)
);
```

### API Endpoints

```python
# Create federation link
POST /api/federation/link
{
    "remote_workspace_id": "ws-123",
    "mode": "read-only",
    "secret": "optional-secret"
}

# List federated facts
GET /api/federation/facts?remote=ws-123

# Query through federation
GET /api/federation/query?topic=...

# Accept link request
POST /api/federation/link/accept

# Revoke link
DELETE /api/federation/link/{id}
```

### Query Flow

```
1. Agent queries local workspace
2. If no results, check federated links
3. For each linked workspace:
   a. Authenticate with secret
   b. Forward query
   c. Merge results
4. Return combined results
```

## Security

### Secrets

- Federation uses **shared secrets**
- Each link has unique secret
- Secrets hashed in database
- Can be rotated independently

### Isolation Guarantees

- **No cross-workspace DELETE** - Can only read
- **Local writes stay local** - Facts written locally only
- **Audit logging** - All federation queries logged
- **Revoke at any time** - Instant disconnection

### Rate Limiting

```python
# Default limits
FEDERATION_QUERY_RATE_LIMIT = 100  # per minute
FEDERATION_RESULT_LIMIT = 50   # per query
```

## Usage Examples

### CLI Commands

```bash
# Create federation link
engram federation create --to team-b-workspace

# List federated workspaces
engram federation list

# Query federated knowledge
engram query --federated "API timeout"

# Revoke link
engram federation revoke team-b
```

### MCP Tool

```
engram_federate(
    action="create",
    workspace_id="ws-123",
    mode="read-only"
)

engram_federate(
    action="query",
    query="API config",
    federate=True
)
```

## UI Integration

### Dashboard

- Show federated workspaces in sidebar
- Badge for read-only vs full
- Click to query federated knowledge

### Conflict Detection

- Conflicts can span workspaces
- Local facts only shown
- Cross-workspace conflicts flagged separately

## Migration Path

1. Add federation_links table
2. Add federated_facts_cache table
3. Implement proxy queries
4. Add CLI commands
5. Add dashboard UI
6. Add rate limiting

## Limitations

- **Cross-workspace conflicts** - Not fully supported
- **Write to remote** - Not allowed (by design)
- **Nested federation** - Single hop only initially

## Future Enhancements

- Multi-hop federation (A→B→C)
- Selective fact sharing (by scope)
- Real-time sync via webhooks