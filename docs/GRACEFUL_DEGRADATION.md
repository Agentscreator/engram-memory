# Graceful Degradation: Local Read Cache When Backend Unreachable

## Overview

Engram implements graceful degradation to maintain functionality when the database backend becomes temporarily unreachable.

## Architecture

```
┌─────────────────┐
│   Agent/MCP    │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  Cache Layer   │──┬──> HIT: Return cached facts
└────────┬────────┘  │
         │          │
         v          │ MISS or Error
┌─────────────────┐  │
│ Backend Storage │<─┘
│ (PostgreSQL/    │
│  SQLite)        │
└─────────────────┘
```

## Cache Behavior

### Read Path (engram_query)
1. Check local cache for requested facts
2. If cache miss → attempt backend query
3. If backend error → return stale cache if available
4. If no cache → return empty results with warning

### Write Path (engram_commit)
1. Write to backend first
2. If backend fails → reject commit with clear error
3. Do NOT write to local cache on failure (avoid inconsistency)

## Cache Implementation

### Local Cache Storage
```python
# In-memory cache with TTL
_cache: dict[str, tuple[list[dict], float]] = {}  # key -> (facts, expiry)

async def get_cached_facts(scope: str) -> list[dict] | None:
    if scope in _cache:
        facts, expiry = _cache[scope]
        if time.time() < expiry:
            return facts
    return None

def set_cached_facts(scope: str, facts: list[dict], ttl: int = 300):
    expiry = time.time() + ttl
    _cache[scope] = (facts, expiry)
```

### Cache Invalidation
- TTL-based expiration (5 minutes default)
- On successful write to backend → invalidate relevant scope cache
- On conflict detected → invalidate conflicting facts

## Fallback Modes

### 1. Stale Cache Mode
When backend is unreachable:
- Return last cached facts (up to 1 hour old)
- Show warning: "Using cached data - may be stale"

### 2. Offline Mode
When no cache available:
- Return empty results
- Queue commits for later retry
- Clear error message: "Backend unreachable - commits queued"

### 3. Degraded Query Mode
When only some scopes are available:
- Return available scope results
- Indicate missing scopes in response

## API Responses

```python
# Normal response
{"facts": [...], "cache_hit": False, "stale": False}

# Stale cache response  
{"facts": [...], "cache_hit": True, "stale": True, "warning": "Using cached data from 5 minutes ago"}

# Offline response
{"facts": [], "error": "Backend unreachable", "commits_queued": 3}
```

## Configuration

```bash
# Enable local cache
engram serve --enable-cache --cache-ttl 300

# Cache size limit
engram serve --max-cache-size 1000  # max facts in memory

# Stale data tolerance
engram serve --max-stale-age 3600  # 1 hour
```

## Testing

```python
async def test_query_fallback_to_cache():
    """Query returns cached facts when backend unreachable"""
    # Pre-populate cache
    await set_cached_facts("test", [fact1, fact2])
    
    # Simulate backend failure
    with mock_backend_error():
        result = await engine.query("test")
        
    assert len(result) == 2
    assert result["cache_hit"] is True
```

## Best Practices

1. **Never cache commits** - only cache query results
2. **Set appropriate TTL** - 5 min default, 1 hour max for stale
3. **Monitor cache hit rate** - track degradation usage
4. **Clear stale cache on recovery** - don't serve stale data after backend recovers

## Metrics to Track

| Metric | Description |
|--------|-------------|
| cache_hit_rate | % of queries served from cache |
| stale_data_served | % of cached responses that are stale |
| backend_errors | Count of backend unavailability events |
| queue_depth | Commits waiting to be retried |