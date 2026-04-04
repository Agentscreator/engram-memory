# Database Security & Schema Isolation

## Overview

Engram now supports secure database configuration and schema isolation, addressing two key concerns:

1. **Security**: Database credentials are never exposed in chat
2. **Isolation**: Engram can share your existing app database using a separate schema

## Key Features

### 1. Environment Variable Configuration

Database URLs are configured via environment variables or `.env` files, never pasted in chat.

**Setup options:**

```bash
# Option 1: .env file in project root
echo "ENGRAM_DB_URL='postgres://user:pass@host:port/database'" >> .env
echo "ENGRAM_SCHEMA='engram'" >> .env  # optional, defaults to 'engram'

# Option 2: Shell configuration
export ENGRAM_DB_URL='postgres://user:pass@host:port/database'
export ENGRAM_SCHEMA='engram'  # optional
```

**Security benefits:**
- Credentials never appear in chat history
- `.env` files can be gitignored
- Environment variables are process-isolated
- `~/.engram/workspace.json` has mode 600 (owner-only access)

### 2. Schema Isolation

Engram creates all tables in a dedicated PostgreSQL schema (default: `engram`), allowing you to use your existing application database without conflicts.

**How it works:**

```sql
-- Engram automatically runs on connect:
CREATE SCHEMA IF NOT EXISTS engram;
SET search_path TO engram, public;

-- All Engram tables are created in the engram schema:
-- engram.facts
-- engram.conflicts
-- engram.agents
-- engram.workspaces
-- etc.
```

**Benefits:**
- Single database connection for your app and Engram
- No table name conflicts
- Easy to backup/restore just Engram data: `pg_dump -n engram`
- Can use same connection pooling
- Clear separation of concerns

### 3. Improved Setup Flow

**Before (security risk):**
```
User: "Set up Engram"
Agent: "Paste your database URL"
User: "postgres://user:secret@host/db"  ← visible in chat!
```

**After (secure):**
```
User: "Set up Engram"
Agent: "Add ENGRAM_DB_URL to your .env file or shell config.
        Don't paste it in this chat for security reasons."
User: [sets environment variable]
Agent: [auto-detects on restart] "Your workspace is ready!"
```

## Configuration Reference

### WorkspaceConfig

```python
@dataclass
class WorkspaceConfig:
    engram_id: str              # Team ID (e.g., "ENG-X7K2-P9M4")
    db_url: str                 # PostgreSQL connection string
    schema: str = "engram"      # Schema name for Engram tables
    anonymous_mode: bool = False
    anon_agents: bool = False
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENGRAM_DB_URL` | Yes* | None | PostgreSQL connection string |
| `ENGRAM_SCHEMA` | No | `engram` | Schema name for Engram tables |

*Required for team mode. Local SQLite mode works without it.

### Invite Keys

Invite keys now include the schema name in their encrypted payload:

```python
# Encrypted payload structure:
{
    "db_url": "postgres://...",
    "engram_id": "ENG-X7K2-P9M4",
    "schema": "engram",          # NEW
    "expires_at": 1234567890,
    "uses_remaining": 10,
    "created_at": 1234567890
}
```

**Backward compatibility:** Old invite keys without `schema` default to `"engram"`.

## Migration Guide

### Existing Installations

If you're already using Engram, no migration is needed. The code is backward compatible:

1. Existing `workspace.json` files without `schema` will default to `"engram"`
2. Existing invite keys without `schema` will default to `"engram"`
3. Existing databases will continue to work (tables are in the public schema)

### Moving to Schema Isolation

To move existing Engram tables to a dedicated schema:

```sql
-- 1. Create the engram schema
CREATE SCHEMA IF NOT EXISTS engram;

-- 2. Move tables (example for facts table)
ALTER TABLE facts SET SCHEMA engram;
ALTER TABLE conflicts SET SCHEMA engram;
ALTER TABLE agents SET SCHEMA engram;
-- ... repeat for all Engram tables

-- 3. Update workspace.json
{
  "engram_id": "ENG-X7K2-P9M4",
  "db_url": "postgres://...",
  "schema": "engram",  // ADD THIS
  "anonymous_mode": false,
  "anon_agents": false
}
```

## Best Practices

### 1. Use .env Files for Local Development

```bash
# .env
ENGRAM_DB_URL='postgres://localhost:5432/myapp_dev'
ENGRAM_SCHEMA='engram'
```

```bash
# .gitignore
.env
.env.*
!.env.example
```

### 2. Use Environment Variables in Production

```bash
# In your deployment config (Heroku, Railway, etc.)
ENGRAM_DB_URL='postgres://prod-host:5432/myapp'
ENGRAM_SCHEMA='engram'
```

### 3. Use Separate Schemas for Different Environments

```bash
# Development
ENGRAM_SCHEMA='engram_dev'

# Staging
ENGRAM_SCHEMA='engram_staging'

# Production
ENGRAM_SCHEMA='engram'
```

### 4. Backup Engram Data Separately

```bash
# Backup only Engram schema
pg_dump -h host -U user -n engram myapp_db > engram_backup.sql

# Restore
psql -h host -U user myapp_db < engram_backup.sql
```

## Security Considerations

### What's Protected

✅ Database credentials never appear in chat  
✅ Credentials stored in mode 600 files or environment variables  
✅ Invite keys encrypt database URLs  
✅ Schema isolation prevents table conflicts  

### What's Not Protected

⚠️ Database credentials visible to anyone with shell access  
⚠️ Invite keys contain encrypted credentials (share securely)  
⚠️ No encryption at rest (use PostgreSQL encryption if needed)  

### Recommendations

1. **Never commit credentials to git**
   - Use `.env` files and add them to `.gitignore`
   - Use environment variables in CI/CD

2. **Rotate invite keys regularly**
   - Set reasonable expiry times (default: 90 days)
   - Limit uses (default: 10)
   - Revoke keys when team members leave

3. **Use connection pooling**
   - PostgresStorage uses asyncpg connection pooling (2-10 connections)
   - Share the same database with your app

4. **Monitor access**
   - Check `agents` table for unexpected agent IDs
   - Review `facts` table for suspicious commits
   - Use anonymous mode if attribution isn't needed

## Troubleshooting

### "Database URL not found"

```bash
# Check if environment variable is set
echo $ENGRAM_DB_URL

# Check if .env file exists and is readable
cat .env | grep ENGRAM_DB_URL

# Restart your editor after setting environment variables
```

### "Schema does not exist"

Engram creates the schema automatically on first connect. If you see this error:

```sql
-- Manually create the schema
CREATE SCHEMA IF NOT EXISTS engram;

-- Grant permissions
GRANT ALL ON SCHEMA engram TO your_user;
```

### "Permission denied for schema"

```sql
-- Grant schema permissions
GRANT ALL ON SCHEMA engram TO your_user;

-- Grant table permissions
GRANT ALL ON ALL TABLES IN SCHEMA engram TO your_user;
```

## Implementation Details

### PostgresStorage Changes

```python
class PostgresStorage(BaseStorage):
    def __init__(self, db_url: str, workspace_id: str = "local", schema: str = "engram"):
        self.schema = schema  # NEW
        # ...

    async def connect(self):
        # Create schema if it doesn't exist
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
        
        # Set search_path to use our schema first
        await conn.execute(f"SET search_path TO {self.schema}, public")
        
        # Tables are created in the engram schema
        await conn.execute(POSTGRES_SCHEMA_SQL)
```

### Workspace Config Changes

```python
@dataclass
class WorkspaceConfig:
    schema: str = "engram"  # NEW field with default

def read_workspace() -> WorkspaceConfig | None:
    # Backward compatibility
    if "schema" not in data:
        data["schema"] = "engram"
    return WorkspaceConfig(**data)
```

### Invite Key Changes

```python
def generate_invite_key(..., schema: str = "engram"):
    payload = {
        "schema": schema,  # NEW field
        # ...
    }

def decode_invite_key(invite_key: str):
    payload = json.loads(...)
    # Backward compatibility
    if "schema" not in payload:
        payload["schema"] = "engram"
    return payload
```

## Related Documentation

- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical architecture
- [README.md](../README.md) - Quick start guide
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development setup
