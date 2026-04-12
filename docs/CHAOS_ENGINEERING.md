# Survey: Chaos Engineering and Fault Injection for Engram

## Executive Summary

This survey evaluates chaos engineering practices for testing Engram's resilience to failures. We analyze tools, strategies, and implementation approaches.

## Chaos Engineering Principles Applied to Engram

### 1. Steady State Hypothesis
Engram's steady state includes:
- Facts can be committed and retrieved
- Conflicts are detected within 5 minutes
- Queries return results in <1 second
- Agents can join/leave workspace

### 2. Controlled Experiments
We inject failures in development/staging to observe behavior before production issues occur.

## Fault Categories to Test

### A. Storage Failures
| Fault | Description | Test Approach |
|-------|-------------|----------------|
| Database disconnect | PostgreSQL/SQLite unavailable | Kill connections, network partition |
| Write failure | Disk full or permission denied | Fill disk, revoke permissions |
| Read timeout | Slow queries or lock contention | Slow queries, long transactions |

### B. Network Failures
| Fault | Description | Test Approach |
|-------|-------------|----------------|
| MCP client disconnect | Agent loses connection | Network partition, timeout |
| Webhook delivery failure | HTTP endpoint unreachable | Mock HTTP errors |

### C. Agent Failures
| Fault | Description | Test Approach |
|-------|-------------|----------------|
| Agent crash mid-commit | Fact left in inconsistent state | SIGKILL during commit |
| Duplicate commits | Same fact committed twice | Retry logic failure |

## Testing Tools & Approaches

### 1. Python Chaos Monkey
```python
# Example: randomly kill connections during tests
import random
import subprocess

def chaos_kill_connections():
    pids = subprocess.run(
        ["pgrep", "-f", "postgres: engram"],
        capture_output=True
    ).stdout.split()
    if random.random() < 0.1:  # 10% chance
        subprocess.run(["kill", random.choice(pids)])
```

### 2. pytest-chaos Plugin
```python
import pytest

@pytest.mark.chaos
async def test_commit_during_db_disconnect():
    """Test that commits fail gracefully when DB disconnects"""
    with mock_db_disconnect():
        with pytest.raises(ConnectionError):
            await engine.commit(fact)
```

### 3. Tox + Failure Scenarios
```ini
[tox]
envlist = py3{unit,integration,chaos}

[testenv:chaos]
commands = pytest tests/ -m chaos
```

## Proposed Test Suite

### 1. Database Resilience Tests
```python
async def test_graceful_degradation_on_db_timeout():
    """DB timeout should return cached results or error cleanly"""
    # Start with cached facts
    facts = await engine.query("project context")
    
    # Simulate DB timeout
    with mock_timeout():
        result = await engine.query("project context")
        # Should either use cache or return clear error
        assert result is not None or "timeout" in str(error)
```

### 2. Conflict Detection Under Load
```python
async def test_conflict_detection_during_high_commit_rate():
    """Conflicts detected even with 100+ commits/minute"""
    # Commit 100 facts rapidly
    for i in range(100):
        await engine.commit(f"Fact {i}", scope="test")
    
    # Insert contradictory facts
    await engine.commit("The API is slow", scope="test/performance")
    await engine.commit("The API is fast", scope="test/performance")
    
    # Verify conflict detected
    conflicts = await engine.get_conflicts()
    assert len(conflicts) > 0
```

### 3. Agent Reconnection
```python
async def test_agent_rejoin_workspace():
    """Agent can rejoin after network interruption"""
    # Agent joins workspace
    agent_id = await engine.register_agent("test-agent")
    
    # Network interruption - agent "leaves"
    await engine.unregister_agent(agent_id)
    
    # Agent rejoins
    new_agent_id = await engine.register_agent("test-agent")
    
    # Should get new session but same engineer identity
    assert new_agent_id != agent_id
```

## Implementation Roadmap

### Phase 1: Basic Failure Tests
- Database disconnect handling
- Timeout behavior verification
- Error message clarity

### Phase 2: Advanced Chaos
- Random failure injection
- Performance degradation testing
- Multi-agent failure scenarios

### Phase 3: Production Simulation
- Staging environment chaos
- On-call response time tracking
- Automated recovery verification

## Tool Recommendations

| Tool | Use Case | Priority |
|------|----------|----------|
| pytest-timeout | Query timeout tests | High |
| unittest.mock | Network failure simulation | High |
| chaos Monkey | Random failure injection | Medium |
| Locust | Load testing | Medium |

## References

- Principles of Chaos Engineering: https://principlesofchaos.org/
- Chaos Monkey: https://github.com/Netflix/chaosmonkey
- Gremlin: https://www.gremlin.com/