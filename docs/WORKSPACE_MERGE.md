# Workspace Merge

Engram supports merging durable facts from one workspace into another.

## Use Cases

- Consolidating teams after a reorganization
- Migrating knowledge from a deprecated workspace
- Combining knowledge bases from acquired teams

## How It Works

The merge process copies all **durable** facts from a source workspace to a target workspace, preserving:
- Fact content and scope
- Confidence scores
- Agent attribution
- Commit timestamps

Ephemeral facts are NOT merged (they're temporary by design).

## CLI Command

```bash
engram merge --source SOURCE_WORKSPACE_ID --target TARGET_WORKSPACE_ID
```

Options:
- `--dry-run` - Preview what would be merged without making changes
- `--scope-prefix` - Only merge facts matching a specific scope prefix

## API Reference

```python
# Via MCP tool (future)
await engram_merge(source_workspace_id, target_workspace_id, dry_run=False)
```

## Conflict Resolution

If a fact with the same content_hash already exists in the target workspace:
- The existing fact is kept
- The incoming fact is skipped (no duplicates)

## Permissions

- Only workspace creators can initiate a merge
- Both workspaces must use the same storage backend (SQLite or PostgreSQL)

## Implementation Notes

```python
# Merge logic pseudocode
source_facts = await storage.get_current_facts_in_scope(
    durability='durable',
    limit=100000
)

for fact in source_facts:
    # Check for duplicates by content_hash
    existing = await storage.find_duplicate(fact['content_hash'], fact['scope'])
    if not existing:
        await storage.insert_fact(fact)  # Copy to target
```

## Rate Limits

- Maximum 10,000 facts per merge operation
- Use scope filtering for larger workspaces