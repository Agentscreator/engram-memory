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

## Related Documentation

- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) - Security features
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical details
- [README.md](../README.md) - Quick start guide
