# Self-Hosted Deployment Mode Design

> **Issue #11** — Design for self-hosted Engram with Docker + SQLite/Postgres.

## Problem Statement

Currently, Engram requires the hosted backend. Enterprise sales, security-conscious teams, and regulated industries need a self-hosted option. This requires:
- Single Docker container deployment
- SQLite or Postgres storage
- Migration path between local and hosted
- Same CLI tool surface
- Documentation

## Architecture

```
┌─────────────────────────────────────────┐
│         Engram Docker Image             │
│  ┌─────────────────────────────────┐   │
│  │     FastMCP Server (stdio)      │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │      Engram Engine              │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │    SQLiteStorage / Postgres     │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│        Client (IDE with MCP)           │
└─────────────────────────────────────────┘
```

## Deployment Options

### Option 1: SQLite (Single File)
```yaml
# docker-compose.yml
services:
  engram:
    image: engram-team/engram:latest
    volumes:
      - ./data:/data
    environment:
      - ENGRAM_STORAGE=sqlite
      - ENGRAM_DATA_PATH=/data/engram.db
    ports:
      - "7474:7474"
```

### Option 2: Postgres (Production)
```yaml
services:
  engram:
    image: engram-team/engram:latest
    environment:
      - ENGRAM_STORAGE=postgres
      - ENGRAM_DB_URL=postgres://user:pass@postgres:5432/engram
    depends_on:
      - postgres

  postgres:
    image: postgres:16
    volumes:
      - ./pgdata:/var/lib/postgresql/data
```

## CLI Surface (Unchanged)

```bash
# Local mode (existing)
engram init
engram serve

# Self-hosted (new)
engram init --storage postgres
engram serve --host 0.0.0.0

# Migration
engram migrate --from hosted --to local
engram export --backup ./backup.tar
```

## Migration Path

1. **Export from hosted**: `engram export --workspace <id> --output backup.tar`
2. **Import to self-hosted**: `engram import --input backup.tar`
3. **Update client config**: Point MCP URL to self-hosted instance

## Security Considerations

- TLS termination (nginx sidecar)
- Secrets management (Docker secrets or env vars)
- Backup encryption
- Audit log export

## Implementation Phases

### Phase 1: Docker Image
- Multi-stage build
- SQLite + Postgres support
- Health checks

### Phase 2: Migration Tools
- Export/import commands
- Data validation
- Progress tracking

### Phase 3: Documentation
- Quickstart guide
- Security hardening guide
- Enterprise FAQ

---

*Design by ismaeldouglasdev — 2026-04-12*