# Agent Identity and Trust Levels (Issue #33)

## Overview

Engram tracks agent identity and assigns trust scores based on behavior, enabling smarter conflict resolution and fact validation.

## Agent Identity

### Identity Fields

Each agent has:
```python
Agent {
    id: str                    # Unique identifier
    name: str                 # Display name
    first_seen: datetime     # First appearance
    commit_count: int         # Total commits
    conflict_count: int       # Conflicts resolved
    trust_score: float       # 0.0 - 1.0
    is_anonymous: bool       # Anonymous mode
}
```

### Identity Storage

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT,
    first_seen TIMESTAMP DEFAULT NOW(),
    commit_count INT DEFAULT 0,
    conflict_count INT DEFAULT 0,
    trust_score FLOAT DEFAULT 0.5,
    is_anonymous BOOLEAN DEFAULT FALSE,
    workspace_id TEXT REFERENCES workspaces(id)
);
```

## Trust Score Calculation

### Factors (weight)

| Factor | Weight | Description |
|--------|--------|------------|
| Historical accuracy | 0.30 | Past facts proven correct |
| Commit count | 0.20 | Number of commits |
| Conflict resolution | 0.25 | Conflicts resolved positively |
| Recency | 0.15 | Recent activity |
| Corroboration | 0.10 | Multiple agents agree |

### Formula

```
trust_score = 
    0.30 * accuracy 
  + 0.20 * (commits / max_commits)
  + 0.25 * (resolved / conflicts)
  + 0.15 * recency_factor
  + 0.10 * corroboration_count
```

Where:
- `accuracy` = correct_facts / total_facts
- `recency_factor` = time_since_last_commit / max_window
- Values normalized to 0.0-1.0

## Trust Levels

| Level | Score Range | Behavior |
|-------|-----------|---------|
| **High** | 0.8-1.0 | Auto-approve commits |
| **Medium** | 0.5-0.79 | Normal processing |
| **Low** | 0.2-0.49 | Require review |
| **Untrusted** | 0.0-0.19 | Quarantine facts |

## Usage Examples

### Query Agent Trust

```python
# Via MCP tool
engram_agent_info(agent_id="agent-123")
# Returns: {trust_score: 0.85, level: "high", commit_count: 50}
```

### Filter by Trust

```python
# Only accept high-trust facts
facts = query(trust_threshold=0.8)

# Exclude untrusted
facts = exclude(trust_level="untrusted")
```

## Implementation

### Database Migration

```sql
ALTER TABLE agents ADD COLUMN trust_score FLOAT DEFAULT 0.5;
ALTER TABLE agents ADD COLUMN trust_updated_at TIMESTAMP;
ALTER TABLE facts ADD COLUMN agent_trust_score FLOAT;
```

### API Endpoints

```
GET /api/agents/<id>/trust     # Get agent trust
POST /api/agents/<id>/trust   # Update trust (system only)
GET /api/agents/trust        # List all with trust
```

## Security

- Trust updates are **system-only** (not exposed to agents)
- Anonymous agents get random IDs but track history
- Trust scores never decrease abruptly (smoothing)

## Migration Path

1. Add columns to agents table
2. Compute initial scores from history
3. Update scores on each commit/resolution
4. Add trust filtering to queries