# Pluggable Storage Backend Interface (Issue #13)

## Overview

Engram supports multiple storage backends, allowing teams to choose the best storage solution for their needs.

## Supported Backends

| Backend | Use Case | Status |
|---------|---------|-------|
| **SQLite** | Local development | ✅ Default |
| **PostgreSQL** | Production | ✅ Supported |
| **MySQL** | Alternative SQL | 🔜 Planned |
| **DynamoDB** | AWS Serverless | 🔜 Planned |
| **Redis** | Caching layer | 🔜 Planned |

## Interface Definition

```python
from abc import ABC, abstractmethod
from typing import Any

class StorageBackend(ABC):
    """Abstract storage backend for Engram."""
    
    workspace_id: str
    
    async def connect(self) -> None:
        """Initialize connection."""
        pass
    
    async def close(self) -> None:
        """Close connection."""
        pass
    
    # ── Fact Operations ─────────────────────────────────────
    
    @abstractmethod
    async def insert_fact(self, fact: dict[str, Any]) -> str:
        """Insert a fact. Returns fact_id."""
        ...
    
    @abstractmethod
    async def get_fact(self, fact_id: str) -> dict | None:
        """Get fact by ID."""
        ...
    
    @abstractmethod
    async def query_facts(
        self,
        topic: str | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        durability: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query facts with filters."""
        ...
    
    @abstractmethod
    async def update_fact(self, fact_id: str, updates: dict) -> bool:
        """Update fact. Returns success."""
        ...
    
    @abstractmethod
    async def delete_fact(self, fact_id: str) -> bool:
        """Soft delete fact. Returns success."""
        ...
    
    # ── Conflict Operations ─────────────────────────────────
    
    @abstractmethod
    async def insert_conflict(self, conflict: dict) -> None:
        """Insert conflict."""
        ...
    
    @abstractmethod
    async def get_conflicts(
        self,
        scope: str | None = None,
        status: str = "open"
    ) -> list[dict]:
        """Get conflicts."""
        ...
    
    @abstractmethod
    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution_type: str,
        resolution: str,
    ) -> bool:
        """Resolve conflict. Returns success."""
        ...
    
    # ── Agent Operations ─────────────────────────────────────
    
    @abstractmethod
    async def upsert_agent(self, agent: dict) -> None:
        """Insert or update agent."""
        ...
    
    @abstractmethod
    async def get_agent(self, agent_id: str) -> dict | None:
        """Get agent."""
        ...
    
    @abstractmethod
    async def list_agents(self) -> list[dict]:
        """List all agents."""
        ...
    
    # ── Analytics ───────────────────────────────────────
    
    @abstractmethod
    async def get_stats(self) -> dict:
        """Get workspace statistics."""
        ...
```

## Storage Factory

```python
class StorageFactory:
    """Create storage backend from connection string."""
    
    @staticmethod
    def create(connection_string: str, workspace_id: str) -> StorageBackend:
        """Create appropriate storage backend.
        
        Examples:
            sqlite:///engram.db
            postgres://user:pass@localhost:5432/engram
            mysql://user:pass@localhost:3306/engram
            dynamodb://table:engram us-east-1
        """
        if connection_string.startswith("postgres"):
            return PostgresStorage(connection_string, workspace_id)
        elif connection_string.startswith("mysql"):
            return MySQLStorage(connection_string, workspace_id)
        elif connection_string.startswith("dynamodb"):
            return DynamoDBStorage(connection_string, workspace_id)
        else:
            return SQLiteStorage(connection_string, workspace_id)
```

## Implementation Checklist

For each new backend:

- [ ] Create `backend_<name>.py`
- [ ] Implement `StorageBackend` interface
- [ ] Add to `StorageFactory`
- [ ] Write tests
- [ ] Update documentation
- [ ] Add connection string parser

## Configuration

### Via Environment

```bash
# SQLite (default)
ENGRAM_DB_URL="sqlite:///path/to/engram.db"

# PostgreSQL
ENGRAM_DB_URL="postgres://user:pass@host:port/dbname"

# MySQL  
ENGRAM_DB_URL="mysql://user:pass@host:port/dbname"

# DynamoDB
ENGRAM_DB_URL="dynamodb://table:engram region:us-east-1"
```

### Via CLI

```bash
engram init --db-url postgres://user:pass@localhost:5432/engram
```

## Performance Notes

| Backend | Read Speed | Write Speed | Scalability |
|---------|-----------|-----------|-----------|
| SQLite | Fast | Fast | Single user |
| PostgreSQL | Fast | Fast | Unlimited |
| MySQL | Fast | Fast | Unlimited |
| DynamoDB | Very Fast | Medium | Serverless |

## Migration

```bash
# Export from current backend
engram export --format json > backup.json

# Import to new backend
NEW_DB_URL="mysql://..." engram import --format json backup.json
```

## Future Backends

To request a new backend, open an issue with:
- Use case
- Expected scale
- Preferred cloud provider