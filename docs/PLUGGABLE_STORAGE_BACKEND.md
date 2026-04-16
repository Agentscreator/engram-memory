# Pluggable Storage Backend Design

> **Issue #13** — Clean storage backend abstraction.

## Current

```
engine.py → BaseStorage (abstract)
              ├── SQLiteStorage
              └── PostgresStorage
```

## Proposed Interface

```python
class StorageBackend(ABC):
    async def connect() -> None: ...
    async def close() -> None: ...
    async def insert_fact(fact) -> int: ...
    async def get_fact_by_id(fact_id) -> dict | None: ...
    async def get_conflicts(scope, status) -> list[dict]: ...
    # ... full interface in docs
```

## Future Backends

| Backend | Use Case |
|---------|----------|
| SQLiteStorage | Local dev |
| PostgresStorage | Team mode |
| TursoStorage | Edge |
| RedisStorage | Ephemeral |
| S3Storage | Archive |

---

*Design by ismaeldouglasdev — 2026-04-12*