# Cross-Session Temporal Conflict Detection Design

> **Issue #15** — Design document for distinguishing "update" from "contradiction" using temporal confidence.

## Problem Statement

Currently, if Agent A says "the rate limit is 1000" on Monday and Agent B says "the rate limit is 2000" on Friday, Engram detects a conflict. But what if B's fact is correct — the limit changed? The system has no way to distinguish "update" from "contradiction."

## Design Goals

1. **Reduce false positive conflicts** — Temporal signals should suppress conflicts when recency suggests an update.
2. **Improve resolution suggestions** — When conflicts are real, the temporal model should inform which fact to keep.
3. **Maintain backward compatibility** — Existing conflicts should not be invalidated.

## Proposed Solution

### 1. Temporal Confidence Signals

Add a `temporal_confidence` field to facts that combines:

- **Recency decay**: Facts become less authoritative over time
- **Supersedes chains**: If `supersedes_fact_id` is set, the newer fact inherits confidence boost
- **Agent agreement count**: Multiple agents confirming the same fact increases confidence
- **Query corroboration**: Facts frequently queried + re-committed gain confidence (already tracked via `corroborating_agents`)

```
temporal_confidence = base_confidence * recency_factor * agreement_factor * corroboration_factor
```

### 2. Conflict Scoring Update

When detecting conflicts, incorporate temporal signals:

```python
def calculate_conflict_score(fact_a, fact_b):
    base_score = nli_score or numeric_diff_score
    
    # If one fact is much more recent, suppress the conflict
    recency_diff = abs(fact_a.committed_at - fact_b.committed_at)
    if recency_diff > 30 days:
        score *= 0.5  # Likely an update, not a contradiction
    
    # If supersedes chain exists, trust the newer fact
    if fact_b.supersedes_fact_id == fact_a.id:
        score *= 0.3  # Explicit update signal
    
    # Boost score if both facts have been independently corroborated
    if fact_a.corroborating_agents > 0 and fact_b.corroborating_agents > 0:
        score *= 1.5  # True conflict, not just noise
    
    return score
```

### 3. Schema Changes

```python
# New migration (version 10)
ALTER TABLE facts ADD COLUMN temporal_confidence REAL
ALTER TABLE facts ADD COLUMN last_corroborated_at TEXT
ALTER TABLE conflicts ADD COLUMN temporal_evidence TEXT  -- JSON with recency signals
```

### 4. Implementation Phases

#### Phase 1: Recency Decay (Low effort, high impact)
- Add `recency_decay` parameter to conflict detection
- Configurable threshold (default: 30 days)
- Skip conflicts where one fact is > 30 days old

#### Phase 2: Supersedes Chain Detection (Medium effort)
- When conflict detected, check if either fact has `supersedes_fact_id`
- If yes, auto-resolve as "update" rather than "conflict"

#### Phase 3: Full Temporal Confidence Model (Higher effort)
- Implement `temporal_confidence` calculation
- Use in conflict scoring and resolution suggestions

## Risk Assessment

- **Backward compatibility**: Low risk — temporal signals are additive
- **Performance**: Minimal — recency check is a simple date comparison
- **False negatives**: Medium risk — overly aggressive recency suppression could miss real conflicts

## Testing Strategy

1. Create test facts with different timestamps
2. Verify conflicts are suppressed when recency > threshold
3. Verify supersedes chain correctly resolves conflicts
4. Benchmark: ensure no performance regression

## Related Issues

- #17 — Automatic fact deduplication on commit (related: should check temporal too)
- #18 — Fact confidence decay with corroboration boost (can reuse temporal model)

---

*Design by ismaeldouglasdev — 2026-04-12*