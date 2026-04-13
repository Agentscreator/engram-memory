# Migration Guide: Schema Isolation

This guide helps you migrate existing Engram installations to use PostgreSQL schema isolation.

## Why Migrate?

Schema isolation provides:
- **Security**: Database credentials in environment variables, not chat
- **Isolation**: Share your app database without table conflicts
- **Organization**: Clear separation between app and Engram data
- **Backup**: Easy to backup/restore just Engram data

## Do I Need to Migrate?

**No migration required if:**
- You're a new user (schema isolation is automatic)
- You're using SQLite local mode
- You're happy with tables in the public schema

**Consider migrating if:**
- You want to use your existing app database
- You want better organization of database objects
- You want easier backup/restore of Engram data

## Migration Steps

### Step 1: Backup Your Data

```bash
# Full database backup
pg_dump -h host -U user -d database > backup_full.sql

# Or just Engram tables (if in public schema)
pg_dump -h host -U user -d database \
  -t facts -t conflicts -t agents -t workspaces \
  -t invite_keys -t scope_permissions -t detection_feedback \
  > backup_engram.sql
```

### Step 2: Create the Engram Schema

```sql
-- Connect to your database
psql -h host -U user -d database

-- Create schema
CREATE SCHEMA IF NOT EXISTS engram;

-- Grant permissions
GRANT ALL ON SCHEMA engram TO your_user;
```

### Step 3: Move Tables to New Schema

```sql
-- Move all Engram tables
ALTER TABLE facts SET SCHEMA engram;
ALTER TABLE conflicts SET SCHEMA engram;
ALTER TABLE agents SET SCHEMA engram;
ALTER TABLE workspaces SET SCHEMA engram;
ALTER TABLE invite_keys SET SCHEMA engram;
ALTER TABLE scope_permissions SET SCHEMA engram;
ALTER TABLE detection_feedback SET SCHEMA engram;

-- If you have FTS table (SQLite migration)
-- ALTER TABLE facts_fts SET SCHEMA engram;
```

### Step 4: Update Workspace Configuration

Edit `~/.engram/workspace.json`:

```json
{
  "engram_id": "ENG-X7K2-P9M4",
  "db_url": "postgres://user:pass@host:5432/database",
  "schema": "engram",  // ADD THIS LINE
  "anonymous_mode": false,
  "anon_agents": false
}
```

Or set environment variable:

```bash
# Add to .env or shell config
export ENGRAM_SCHEMA='engram'
```

### Step 5: Restart Engram

```bash
# Restart your editor/IDE
# Or if running standalone:
engram serve
```

### Step 6: Verify Migration

```sql
-- Check tables are in engram schema
SELECT schemaname, tablename 
FROM pg_tables 
WHERE schemaname = 'engram';

-- Should show:
-- engram | facts
-- engram | conflicts
-- engram | agents
-- etc.
```

## Alternative: Fresh Start with Schema

If you prefer a clean slate:

### Step 1: Export Important Data

```sql
-- Export facts you want to keep
COPY (
  SELECT content, scope, confidence, fact_type, committed_at
  FROM facts
  WHERE valid_until IS NULL
) TO '/tmp/facts_export.csv' CSV HEADER;
```

### Step 2: Remove Old Configuration

```bash
rm ~/.engram/workspace.json
```

### Step 3: Set Up Fresh with Schema

```bash
# Set environment variables
export ENGRAM_DB_URL='postgres://user:pass@host:5432/database'
export ENGRAM_SCHEMA='engram'

# Restart editor and run setup
# Agent will create tables in engram schema automatically
```

### Step 4: Re-import Data (Optional)

```python
# Use engram_commit to re-add important facts
# Or write a migration script
```

## Rollback Plan

If something goes wrong:

### Option 1: Move Tables Back

```sql
-- Move tables back to public schema
ALTER TABLE engram.facts SET SCHEMA public;
ALTER TABLE engram.conflicts SET SCHEMA public;
-- ... etc

-- Remove schema field from workspace.json
```

### Option 2: Restore from Backup

```bash
# Drop engram schema
psql -h host -U user -d database -c "DROP SCHEMA engram CASCADE;"

# Restore from backup
psql -h host -U user -d database < backup_full.sql

# Remove schema field from workspace.json
```

## Team Migration

If you have a team using Engram:

### Step 1: Coordinate Downtime

```
1. Announce migration window to team
2. Ask everyone to stop using Engram
3. Perform migration (Steps 1-3 above)
4. Generate new invite key with schema
```

### Step 2: Generate New Invite Key

```bash
# After migration, generate new invite key
# The new key will include schema='engram'
```

### Step 3: Share New Key

```
Share the new invite key with team members.
Old keys will still work but won't use the new schema.
```

### Step 4: Team Members Update

Each team member:

```bash
# Option 1: Join with new invite key
rm ~/.engram/workspace.json
# Paste new invite key in chat

# Option 2: Manually update workspace.json
# Add "schema": "engram" to workspace.json
```

## Troubleshooting

### "relation does not exist"

Tables are still in public schema. Run:

```sql
-- Check where tables are
SELECT schemaname, tablename 
FROM pg_tables 
WHERE tablename IN ('facts', 'conflicts', 'agents');

-- If in public, move them:
ALTER TABLE facts SET SCHEMA engram;
-- etc.
```

### "permission denied for schema"

Grant permissions:

```sql
GRANT ALL ON SCHEMA engram TO your_user;
GRANT ALL ON ALL TABLES IN SCHEMA engram TO your_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA engram TO your_user;
```

### "schema already exists"

This is fine. Engram uses `CREATE SCHEMA IF NOT EXISTS`.

### Tables in Wrong Schema

```sql
-- Check current schema
SELECT current_schema();

-- Check search_path
SHOW search_path;

-- Should be: engram, public
```

## Best Practices After Migration

### 1. Update .gitignore

```bash
# .gitignore
.env
.env.*
!.env.example
```

### 2. Document for Team

Create `.env.example`:

```bash
# .env.example
ENGRAM_DB_URL='postgres://user:password@host:port/database'
ENGRAM_SCHEMA='engram'
```

### 3. Backup Strategy

```bash
# Daily backup of engram schema only
pg_dump -h host -U user -d database -n engram > engram_$(date +%Y%m%d).sql

# Retention: keep last 7 days
find . -name "engram_*.sql" -mtime +7 -delete
```

### 4. Monitor Schema Size

```sql
-- Check schema size
SELECT 
  schemaname,
  pg_size_pretty(sum(pg_total_relation_size(schemaname||'.'||tablename))::bigint) as size
FROM pg_tables
WHERE schemaname = 'engram'
GROUP BY schemaname;
```

## FAQ

**Q: Will old invite keys still work?**  
A: Yes, they default to schema='engram' for backward compatibility.

**Q: Can I use a different schema name?**  
A: Yes, set `ENGRAM_SCHEMA='your_schema'` or pass `schema='your_schema'` to `engram_init()`.

**Q: Can I have multiple schemas for different environments?**  
A: Yes! Use `engram_dev`, `engram_staging`, `engram_prod`, etc.

**Q: Do I need to migrate if I'm using SQLite?**  
A: No, SQLite doesn't support schemas. This is PostgreSQL-only.

**Q: Will this break my existing setup?**  
A: No, it's backward compatible. Tables in public schema continue to work.

**Q: How do I verify the migration worked?**  
A: Check the logs when starting Engram. You should see:
```
Team mode: PostgreSQL (workspace: ENG-X7K2-P9M4, schema: engram)
```

## Support

If you encounter issues:

1. Check logs: `engram serve --log-level DEBUG`
2. Verify schema: `\dn` in psql
3. Check tables: `\dt engram.*` in psql
4. Open an issue with logs and error messages

## Schema Version History

| Version | What changed |
|---------|-------------|
| v2 | Conflict suggestion columns |
| v3 | `memory_op`, `supersedes_fact_id` on facts |
| v4 | Multi-tenancy (`workspace_id`), `workspaces` and `invite_keys` tables |
| v5 | `corroborating_agents` on facts |
| v6 | `durability`, `query_hits` on facts |
| v7 | `key_generation` on workspaces |
| v8 | `webhooks`, `webhook_deliveries`, `resolution_rules`, `scopes`, `audit_log` |
| v9 | `display_name`, `description` on workspaces |
| v10 | SQLite `facts_au` AFTER UPDATE trigger (FTS5 consistency for GDPR hard-erase) |
| v11 | `revoked_at`, `grace_until`, `rotation_reason` on `invite_keys`; grace index |

## Schema v10 — GDPR FTS Update Trigger

**New installs:** the `facts_au` trigger is included in `SCHEMA_SQL` automatically.

**Existing SQLite installs:** the trigger is created during the v10 migration that
runs automatically on next `connect()`.

**PostgreSQL installs:** no migration needed.  The `search_vector` column is a
`GENERATED ALWAYS AS ... STORED` tsvector, so any `UPDATE` to `content` or
`keywords` automatically refreshes the GIN index.

The trigger is required by the **GDPR hard-erase path** (`engram gdpr erase --mode hard`)
which replaces fact `content` and clears `keywords` in a bulk `UPDATE`.  Without
the trigger, FTS5 shadow tables would retain old content and erased facts would
still appear in full-text search results.

```sql
-- Added by v10 migration (SQLite only)
CREATE TRIGGER IF NOT EXISTS facts_au
    AFTER UPDATE OF content, scope, keywords ON facts BEGIN
        INSERT INTO facts_fts(facts_fts, rowid, content, scope, keywords)
        VALUES ('delete', old.rowid, old.content, old.scope, old.keywords);
        INSERT INTO facts_fts(rowid, content, scope, keywords)
        VALUES (new.rowid, new.content, new.scope, new.keywords);
    END;
```

## Schema v11 — Invite Key Lifecycle

**Purpose:** Support soft-revocation with a configurable grace period for
invite key rotation, plus an audit trail and structured rotation metadata.

**New columns on `invite_keys`:**

| Column | Type (SQLite / Postgres) | Meaning |
|--------|--------------------------|---------|
| `revoked_at` | `TEXT` / `TIMESTAMPTZ` | When the key was soft-revoked; `NULL` = still active |
| `grace_until` | `TEXT` / `TIMESTAMPTZ` | Existing sessions may continue until this timestamp |
| `rotation_reason` | `TEXT` | Optional operator note stored at revocation time |

**New index:** `invite_keys_grace ON invite_keys(engram_id, grace_until)` —
enables efficient `get_active_grace_until` queries.

**SQLite migration SQL (runs automatically on next `connect()`):**

```sql
ALTER TABLE invite_keys ADD COLUMN revoked_at TEXT;
ALTER TABLE invite_keys ADD COLUMN grace_until TEXT;
ALTER TABLE invite_keys ADD COLUMN rotation_reason TEXT;
CREATE INDEX IF NOT EXISTS invite_keys_grace ON invite_keys(engram_id, grace_until);
```

**PostgreSQL migration SQL (runs automatically on next `connect()`):**

```sql
ALTER TABLE invite_keys ADD COLUMN revoked_at TIMESTAMPTZ;
ALTER TABLE invite_keys ADD COLUMN grace_until TIMESTAMPTZ;
ALTER TABLE invite_keys ADD COLUMN rotation_reason TEXT;
CREATE INDEX IF NOT EXISTS invite_keys_grace ON invite_keys(engram_id, grace_until);
```

**Behaviour change:** `consume_invite_key` and `validate_invite_key` now
add `AND revoked_at IS NULL` to their `WHERE` clause.  Revoked keys cannot
be used for new joins even when still within their grace window.

See [PRIVACY_ARCHITECTURE.md — Invite Key Lifecycle](./PRIVACY_ARCHITECTURE.md)
for the full rotation workflow and grace period semantics.

## Related Documentation

- [PRIVACY_ARCHITECTURE.md](./PRIVACY_ARCHITECTURE.md) - GDPR erasure and invite key lifecycle
- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) - Security features
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical details
- [README.md](../README.md) - Quick start guide
