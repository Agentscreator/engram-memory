# Memory Compression: Squashing Lineage Chains

This document describes the memory compression feature for squashing long lineage chains.

## Problem

A fact that has been superseded 15 times has a lineage chain that is:
- Noisy to retrieve (many rows returned)
- Expensive to store (redundant data)
- Slow to query (multiple joins)

## Solution

Implement a compression step that fires when lineage_id has N+ entries. The chain is collapsed into a single compressed fact that retains the most important historical context.

## Compression Trigger

Compression triggers when a fact has >10 versions:

```sql
-- Check if compression needed
SELECT COUNT(*) FROM facts WHERE lineage_id = ? AND valid_until IS NOT NULL;
-- If count > 10, trigger compression
```

## Compressed Fact Structure

```sql
-- Original facts (archived)
id: "fact-001-v1"
lineage_id: "lineage-001"
content: "Initial value: v1"
valid_until: "2024-01-01T00:00:00Z"
compressed: 1
archive_ref: "archive-facts-001"  -- Points to archive table

-- Compressed fact (current)
id: "fact-001-v11"
lineage_id: "lineage-001"
content: "[COMPRESSED] See archive_ref for full history"
valid_until: NULL
compressed: 1
first_commit: "2024-01-01T00:00:00Z"
last_commit: "2024-01-15T00:00:00Z"
version_count: 11
archive_ref: "archive-facts-001"
```

## Archive Table

```sql
CREATE TABLE fact_archives (
    id              TEXT PRIMARY KEY,
    lineage_id      TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    content         TEXT NOT NULL,  -- Full compressed content
    first_commit    TEXT NOT NULL,
    last_commit     TEXT NOT NULL,
    version_count   INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_fact_archives_lineage ON fact_archives(lineage_id, workspace_id);
```

## Compression Algorithm

1. **Identify**: Find facts with >10 versions in lineage
2. **Extract**: Get first commit, key inflection points, current value
3. **Compress**: Create archive entry with full history
4. **Replace**: Update current fact to point to archive
5. **Cleanup**: Mark original facts as archived (not deleted)

## Key Inflection Points

Keep commits where:
- Content changed significantly (>50% diff)
- A conflict was detected
- Agent changed

## Safety Guarantees

- Bitemporal schema ensures archived rows never surface in normal queries
- `valid_until` already marks superseded facts as invalid
- Archive table provides full audit trail
- Compression is reversible (can restore from archive)

## API Changes

```python
# New engine methods
async def compress_lineage(lineage_id: str) -> dict:
    """Compress a lineage chain if it exceeds threshold."""
    
async def get_archive(lineage_id: str) -> list[dict]:
    """Retrieve full history from archive."""
    
async def restore_from_archive(lineage_id: str) -> str:
    """Restore compressed fact to full history."""
```

## Trigger Schedule

- Background job runs daily at 3 AM UTC
- Compresses lineages with >10 versions
- Rate-limited to 100 compressions per hour

## Monitoring

- Track compression ratio: `archive_size / original_size`
- Alert if ratio < 0.5 (compression not effective)
- Log compression time per lineage
