# Agent Identity and Trust Levels Design

> **Issue #33** — Design for agent trust scoring system.

## Problem

All agents are treated equally. A senior engineer's fact should carry more weight than a junior agent's.

## Solution

### Trust Score Calculation

```python
trust_score = accuracy_rate * 0.4 + corroboration_rate * 0.3 + (1 - conflict_rate) * 0.3
```

### Trust Tiers

| Tier | Score | Behavior |
|------|-------|----------|
| `trusted` | 0.8-1.0 | +20% relevance boost |
| `standard` | 0.4-0.79 | Default |
| `flagged` | 0.0-0.39 | -20% relevance |

### Query Integration

```python
def rank_fact(fact, agent_trust_scores):
    score = fact.relevance_score
    agent_score = agent_trust_scores.get(fact.agent_id, 0.5)
    if agent_score >= 0.8:
        score *= 1.2
    elif agent_score < 0.4:
        score *= 0.8
    return score
```

---

*Design by ismaeldouglasdev — 2026-04-12*