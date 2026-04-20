# Controlled Study: Does Engram Improve Agent Task Completion?

This document outlines a controlled study methodology to measure whether Engram improves agent task completion rates.

## Hypothesis

**null**: Engram does not improve agent task completion rates
**alternative**: Engram improves agent task completion rates by at least 15%

## Methodology

### Setup

1. **Baseline**: Run N tasks without Engram memory
2. **Treatment**: Run same N tasks with Engram memory
3. **Control**: Randomize task order to avoid learning effects

### Tasks

Select tasks from a standardized set:
- Bug fixes with known root causes
- Feature implementations with clear requirements
- Refactoring with specific goals

### Metrics

| Metric | Description |
|--------|-------------|
| **Completion Rate** | % of tasks completed successfully |
| **Time to Complete** | Average minutes per task |
| **Revisions** | Agent corrections/retries |

### Sample Size

For 15% effect size with 80% power at α=0.05:
- ~50 tasks per condition required

## Implementation

```python
# study_runner.py
import random
import time

async def run_study(tasks: list, with_engram: bool) -> dict:
    results = []
    for task in tasks:
        start = time.time()
        if with_engram:
            context = await query_workspace(task["query"])
        result = await agent_execute(task)
        results.append({
            "task_id": task["id"],
            "completed": result["success"],
            "elapsed": time.time() - start,
        })
    return aggregate(results)

# Run study
baseline = await run_study(tasks, with_engram=False)
treatment = await run_study(tasks, with_engram=True)

# Analyze
from scipy import stats
t, p = stats.ttest_ind(baseline["rate"], treatment["rate"])
```

## Output

| Metric | Baseline | Treatment | Δ |
|--------|----------|------------|---|
| Completion Rate | X% | Y% | (Y-X)% |

Fixes #56