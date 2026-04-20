# Data Residency: EU and APAC Regions

This document outlines the architecture for supporting data residency in EU and APAC regions.

## Overview

| Region | Code | Status | Expected Latency |
|--------|------|--------|---------------|
| US (default) | us-east-1 | ✅ Available | 20-50ms |
| EU | eu-west-1 | Planned | 80-120ms |
| APAC | ap-southeast-1 | Planned | 150-200ms |

## Motivation

Enterprise customers, particularly in regulated industries, require data residency guarantees:
- GDPR compliance (EU)
- Data sovereignty requirements (APAC)
- Industry regulations (banking, healthcare)

## Architecture

### Multi-Region Model

```
┌─────────────────────────────────────────────────────────────┐
│                      Engram Platform                        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   US VPC    │    │   EU VPC    │    │  APAC VPC   │     │
│  │  (default)  │◀──▶│  (planned) │◀──▶│  (planned)  │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │              │
│    PostgreSQL        PostgreSQL        PostgreSQL          │
│    (us-east-1)      (eu-west-1)       (ap-southeast-1)    │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate VPCs per region | Isolation, compliance |
| Regional invite keys | Customer selects region at signup |
| No cross-region replication | Data sovereignty |
| Same feature set | Consistent UX |

## Implementation

### Invite Key Format

```python
# Invite key now includes region
{
    "db_url": "postgres://...",
    "region": "eu-west-1",  # New field
    "engram_id": "ENG-XXX",
    "schema": "engram",
    "expires_at": 1715404800,
    "uses_remaining": 10
}
```

### Region Selection Flow

```
User signs up
       │
       ▼
Select region (US/EU/APAC)
       │
       ▼
┌──────────────────────────────────┐
│  Region Selection UI               │
│  - Where is your organization?   │
│  - US (default)                  │
│  - European Union               │
│  - Asia Pacific                │
└──────────────────────────────────┘
       │
       ▼
Provision workspace in region
       │
       ▼
Generate invite key with region
```

### API Changes

```python
# New endpoint for region availability
async def get_available_regions() -> list[dict]:
    """List available regions with latency estimates."""
    return [
        {"code": "us-east-1", "name": "US East", "latency_ms": 35},
        {"code": "eu-west-1", "name": "EU Ireland", "latency_ms": 95},
        {"code": "ap-southeast-1", "name": "APAC Singapore", "latency_ms": 180},
    ]

# Modified workspace creation
async def create_workspace(
    name: str,
    region: str = "us-east-1"  # New parameter
) -> Workspace:
    """Create workspace in specified region."""
```

## Database Schema

### Regional Workspaces

```sql
-- workspaces table now includes region
CREATE TABLE engram.workspaces (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    region          TEXT NOT NULL DEFAULT 'us-east-1',
    created_at      TIMESTAMPTZ NOT NULL,
    is_active       BOOL DEFAULT true,
    ...
);

CREATE INDEX idx_workspaces_region ON engram.workspaces(region);
```

### Regional Routing

```python
# Database connection per region
REGIONAL_DB_URLS = {
    "us-east-1": "postgres://engram-us-east-1.db.engram.app",
    "eu-west-1": "postgres://engram-eu-west-1.db.engram.app",
    "ap-southeast-1": "postgres://engram-ap-southeast-1.db.engram.app",
}

def get_db_url(region: str) -> str:
    """Get database URL for region."""
    return REGIONAL_DB_URLS.get(region, REGIONAL_DB_URLS["us-east-1"])
```

## Compliance

### EU (GDPR)

| Requirement | Implementation |
|-------------|----------------|
| Data processing agreement | DPA available |
| Right to erasure | Per-workspace delete |
| Data portability | Export all workspace data |
| Transfer mechanisms | Standard Contractual Clauses |
| Local processing | EU VPC |

### APAC

| Requirement | Implementation |
|-------------|----------------|
| PDPA (Singapore) | Local VPC |
| APP (Australia) | Local VPC |
| Data Localization | APAC VPC |

## Migration Strategy

### Existing Customers

```python
# Migration tool for existing workspaces
async def migrate_workspace(
    workspace_id: str,
    target_region: str
) -> dict:
    """
    Migrate workspace to new region.
    1. Export all data
    2. Transfer to new region
    3. Update invite keys
    4. Verify integrity
    """
```

Migration requires:
- Customer approval
- Downtime window (15-30 min)
- Data integrity verification

## Pricing

| Region | Storage | Query |
|--------|---------|-------|
| US | Included | Included |
| EU | +10% | Included |
| APAC | +15% | Included |

Regional deployment is an enterprise feature.

## Monitoring

### Per-Region Metrics

```python
# Track region-specific metrics
METRICS = {
    "storage_gb": "per-region",
    "query_count": "per-region", 
    "workspace_count": "per-region",
    "avg_latency_ms": "per-region",
}
```

## Roadmap

| Phase | Region | Timeline |
|-------|--------|----------|
| 1 | EU | Q3 2026 |
| 2 | APAC | Q4 2026 |
| 3 | Latency routing | Q1 2027 |

## Related Documentation

- [PRIVACY_ARCHITECTURE.md](./PRIVACY_ARCHITECTURE.md)
- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md)
- [IMPLEMENTATION.md](./IMPLEMENTATION.md)
