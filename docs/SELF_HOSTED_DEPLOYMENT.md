# Self-Hosted Deployment Design

> **Issue #11** — Docker + SQLite/Postgres self-hosted option.

## Architecture

```
Engram Docker Image
  ├── FastMCP Server
  ├── Engram Engine
  └── SQLite/Postgres Storage
```

## Deployment

### SQLite (Simple)
```yaml
services:
  engram:
    image: engram-team/engram:latest
    volumes:
      - ./data:/data
    environment:
      - ENGRAM_STORAGE=sqlite
```

### Postgres (Production)
```yaml
services:
  engram:
    image: engram-team/engram:latest
    environment:
      - ENGRAM_DB_URL=postgres://...
    depends_on:
      - postgres
```

## Migration

1. Export: `engram export --workspace <id> --output backup.tar`
2. Import: `engram import --input backup.tar`
3. Update client config

---

*Design by ismaeldouglasdev — 2026-04-12*