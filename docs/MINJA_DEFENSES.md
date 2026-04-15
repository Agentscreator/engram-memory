# MINJA: Memory Injection Attack Defenses

## Overview

MINJA (Memory INJection Attack) is a threat model where a malicious or compromised agent commits false facts to poison a team's shared memory. This document describes the threat model and the defenses implemented in Engram.

## Threat Model

### Attackers

1. **Compromised Agent**: An agent whose credentials have been stolen or whose system has been compromised
2. **Malicious Insider**: A team member intentionally poisoning memory
3. **Prompt Injection**: External attacker injecting malicious content through legitimate facts
4. **Automated Bot**: Script continuously injecting false facts

### Attack Vectors

| Vector | Description | Impact |
|--------|-------------|--------|
| Mass commit | Agent commits hundreds of false facts rapidly | Complete memory corruption |
| Slow poison | Commit small amounts over time | Gradual trust degradation |
| Semantic injection | Facts that sound plausible but are false | Undetected corruption |
| Conflict spam | Create many fake conflicts | Alert fatigue |

### Attack Goals

- Disrupt team decision-making with false information
- Hide real information by creating conflicts
- Erode trust in the memory system
- Cause downstream system failures

## Current Mitigations

### 1. Rate Limiting (Implemented)

Per-agent commit rate limits prevent mass commit attacks:

```
Default: 50 commits/agent/hour
Configurable via: engram serve --rate-limit 100
```

**Implementation**: `src/engram/auth.py` — `RateLimiter` class

```python
class RateLimiter:
    """Per-agent sliding window rate limiter."""
    def __init__(self, max_per_hour: int = 50) -> None:
        ...
    def check(self, agent_id: str) -> bool:
        """Return True if the agent is within rate limits."""
        ...
```

### 2. Secret Scanning (Implemented)

The secret scanner in `src/engram/secrets.py` catches:
- API keys, tokens, credentials
- PII (emails, SSN, credit cards)

### 3. Provenance Tracking (Implemented)

Facts with provenance (verified evidence) score higher in retrieval:

**Schema**: `provenance` column on facts table

```sql
CREATE TABLE IF NOT EXISTS facts (
    ...
    provenance TEXT,  -- File path, test output, etc.
    corroborating_agents INTEGER NOT NULL DEFAULT 0,
    ...
);
```

**Scoring boost**: Facts with provenance get a 1.0 weight boost in retrieval.

### 4. Corroboration Scoring (Implemented)

Facts confirmed by multiple agents score higher:

**Schema**: `corroborating_agents` column tracks confirmation count

```python
# From src/engram/engine.py
corroboration_weight = 0.1 * fact.get("corroborating_agents", 0)
```

### 5. Agent Identification (Implemented)

The system tracks which agent committed each fact:

**Schema**: `agent_id` column on facts and audit log

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    operation   TEXT NOT NULL,  -- commit, resolve, query
    agent_id    TEXT NOT NULL,
    ...
);
```

## Proposed New Defenses

### 1. Agent Trust Levels

Add a trust score per agent based on:

- **Commit history quality**: Rate of fact corrections/revocations
- **Corroboration rate**: How often other agents confirm their facts
- **Conflict rate**: How often their facts are flagged as conflicts

**Database schema**:

```sql
CREATE TABLE IF NOT EXISTS agent_trust (
    agent_id        TEXT PRIMARY KEY,
    trust_score     REAL NOT NULL DEFAULT 0.5,
    commit_count    INTEGER NOT NULL DEFAULT 0,
    conflict_count  INTEGER NOT NULL DEFAULT 0,
    corroboration_count INTEGER NOT NULL DEFAULT 0,
    last_updated    TEXT NOT NULL,
    workspace_id     TEXT NOT NULL DEFAULT 'local'
);
```

**Trust score calculation**:

```python
def calculate_trust_score(agent: dict) -> float:
    conflict_rate = agent["conflict_count"] / max(agent["commit_count"], 1)
    corroboration_rate = agent["corcorboration_count"] / max(agent["commit_count"], 1)
    
    # Base score of 0.5, adjusted by behavior
    score = 0.5
    score += (1 - conflict_rate) * 0.3  # Up to +0.3 for low conflict rate
    score += corroboration_rate * 0.2   # Up to +0.2 for high corroboration
    
    return max(0.0, min(1.0, score))
```

**Behavior by trust level**:

| Trust Level | Commit Limit | Require Provenance | Auto-Resolve Conflicts |
|-------------|--------------|-------------------|------------------------|
| High (0.8+) | 100/hr | No | Yes |
| Medium (0.5-0.8) | 50/hr | No | No |
| Low (0-0.5) | 10/hr | Yes | No |

### 2. Anomaly Detection for Commit Velocity

Monitor commit velocity per agent and flag anomalies:

**Implementation**: Add sliding window detection in `auth.py`

```python
class CommitVelocityAnomalyDetector:
    """Detect abnormal commit patterns."""
    
    def __init__(self):
        self._recent_commits: dict[str, list[float]] = defaultdict(list)
        self._anomaly_threshold = 10  # Commits in 1 minute = suspicious
    
    def record(self, agent_id: str) -> None:
        """Record a commit and check for anomalies."""
        now = time.time()
        self._recent_commits[agent_id].append(now)
        
        # Prune entries older than 1 minute
        cutoff = now - 60
        self._recent_commits[agent_id] = [
            t for t in self._recent_commits[agent_id] if t > cutoff
        ]
        
        # Flag if threshold exceeded
        if len(self._recent_commits[agent_id]) > self._anomaly_threshold:
            logger.warning(
                f"Anomalous commit velocity detected for agent {agent_id}: "
                f"{len(self._recent_commits[agent_id])} commits in last minute"
            )
    
    def is_anomalous(self, agent_id: str) -> bool:
        """Return True if agent has anomalous commit velocity."""
        if agent_id not in self._recent_commits:
            return False
        return len(self._recent_commits[agent_id]) > self._anomaly_threshold
```

### 3. Fact Confidence Decay

Facts that are frequently contradicted should decay in confidence:

**Database update**:

```sql
ALTER TABLE facts ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE facts ADD COLUMN confidence_decay REAL NOT NULL DEFAULT 1.0;
```

**Algorithm** (from issue #18):

```python
def apply_confidence_decay(fact: dict, contradictions: int) -> float:
    """Apply confidence decay based on contradiction count."""
    base_confidence = fact.get("confidence", 0.5)
    decay_factor = 0.95 ** min(contradictions, 10)  # Max 10x decay
    return base_confidence * decay_factor
```

### 4. Provenance Requirements

Require provenance for agents below trust threshold:

**Implementation**: Add in `engine.py` commit path

```python
async def commit(self, content: str, agent_id: str, ...):
    trust_score = await self.get_agent_trust_score(agent_id)
    
    if trust_score < 0.5 and not provenance:
        raise ValueError(
            "Provenance required for low-trust agents. "
            "Provide evidence (file path, test output, etc.)"
        )
```

### 5. Audit Log Enhancements

Enhanced audit logging for security:

**Current**: Basic operation logging exists

**Proposed additions**:

```sql
-- Add client fingerprint
ALTER TABLE audit_log ADD COLUMN client_ip TEXT;
ALTER TABLE audit_log ADD COLUMN user_agent TEXT;

-- Add risk score at commit time
ALTER TABLE audit_log ADD COLUMN risk_score REAL;

-- Add commit content hash for later verification
ALTER TABLE audit_log ADD COLUMN content_hash TEXT;
```

## Detection & Response

### Alert Triggers

| Condition | Severity | Action |
|-----------|----------|--------|
| >10 commits/min from agent | High | Block + alert |
| >50 commits/hour (rate limit) | Medium | Block + log |
| >5 conflicts created in 1 hour | Medium | Alert |
| Trust score drops below 0.3 | High | Alert + review |

### Response Actions

1. **Temporary block**: Agent blocked for 5 minutes
2. **Alert team**: Notify workspace of suspicious activity
3. **Require approval**: Future commits require human approval
4. **Suspend agent**: Remove agent from workspace (admin only)

## Configuration

Defenses are configurable in `cli.py`:

```bash
# Rate limiting
engram serve --rate-limit 50

# Trust scoring
engram serve --min-trust-score 0.3

# Anomaly detection
engram serve --anomaly-threshold 10
```

## Testing

Test the MINJA defenses with:

```python
# Test rate limiting
def test_rate_limit_blocks_excess_commits():
    limiter = RateLimiter(max_per_hour=50)
    for i in range(50):
        assert limiter.check("test-agent") is True
    assert limiter.check("test-agent") is False

# Test anomaly detection
def test_detects_high_velocity_commits():
    detector = CommitVelocityAnomalyDetector()
    for i in range(15):
        detector.record("test-agent")
    assert detector.is_anomalous("test-agent") is True

# Test trust score calculation
def test_trust_score_uses_conflict_rate():
    agent = {"commit_count": 100, "conflict_count": 5, "corroboration_count": 80}
    score = calculate_trust_score(agent)
    assert score > 0.7  # Low conflict, high corroboration
```

## References

- Issue #16: MINJA defenses
- Issue #18: Fact confidence decay
- Issue #33: Agent identity and trust levels
- `src/engram/auth.py`: Rate limiter implementation
- `src/engram/engine.py`: Provenance scoring