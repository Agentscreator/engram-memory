# Cross-Session Temporal Conflict Detection Design

> **Issue #15** — Design for distinguishing "update" from "contradiction" using temporal confidence.

## Problem

When Agent A says "the rate limit is 1000" on Monday and Agent B says "the rate limit is 2000" on Friday, Engram detects a conflict. But what if B's fact is correct — the limit changed? The system can't distinguish "update" from "contradiction."

## Proposed Solution

### Temporal Confidence Model

Add a `temporal_confidence` field combining:
- **Recency decay**: Facts become less authoritative over time
- **Supersedes chains**: If `supersedes_fact_id` is set, trust the newer fact
- **Agent agreement**: Multiple agents confirming increases confidence
- **Query corroboration**: Frequently queried facts gain confidence

### Conflict Scoring Update

```python
def calculate_conflict_score(fact_a, fact_b):
    base_score = nli_score or numeric_diff_score
    
    # Recency signal: if one fact is much more recent, suppress
    recency_diff = abs(fact_a.committed_at - fact_b.committed_at)
    if recency_diff > 30 days:
        score *= 0.5  # Likely an update
    
    # Supersedes chain
    if fact_b.supersedes_fact_id == fact_a.id:
        score *= 0.3  # Explicit update
    
    return score
```

## Implementation Phases

1. **Phase 1**: Recency decay (add threshold parameter)
2. **Phase 2**: Supersedes chain detection
3. **Phase 3**: Full temporal confidence model

---

*Design by ismaeldouglasdev — 2026-04-12*