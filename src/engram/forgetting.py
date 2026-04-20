"""Probabilistic forgetting curve for the narrative coherence detective.

Implements FiFA-inspired forgetting: the detective samples a subset of
facts before running coherence checks, biased toward signal over noise.

Forgetting rates by age:
- < 24 hours:  forget 60-80% (keep 20-40%, base_keep=0.30)
- 1-7 days:    forget 80-90% (keep 10-20%, base_keep=0.15)
- > 7 days:    forget 90-95% (keep  5-10%, base_keep=0.07)

Facts involved in conflicts survive at higher rates — each flag
multiplies the keep probability by 2 (capped at 1.0).  A fact flagged
3 times has 8× the base keep probability, making it almost certain to
survive the filter.

The newest fact (the trigger) is always retained so the detective can
compare it against the surviving context.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Protocol


class _HasTimestamp(Protocol):
    """Minimal row interface — anything with committed_at and id."""

    def __getitem__(self, key: str) -> Any: ...


def compute_keep_probability(
    age_hours: float,
    flag_count: int = 0,
) -> float:
    """Return the probability that a fact survives the forgetting filter.

    Parameters
    ----------
    age_hours:
        How old the fact is in hours.
    flag_count:
        Number of times this fact has been involved in a conflict.
        Each flag doubles the keep probability (capped at 1.0).
    """
    if age_hours < 24:
        base_keep = 0.30  # keep 20-40%, center at 30%
    elif age_hours < 168:  # 7 days
        base_keep = 0.15  # keep 10-20%, center at 15%
    else:
        base_keep = 0.07  # keep 5-10%, center at 7%

    return min(1.0, base_keep * (2.0**flag_count))


def apply_forgetting(
    facts: list[dict[str, Any]],
    conflict_counts: dict[str, int],
    now: datetime | None = None,
    rng: random.Random | None = None,
    always_keep_ids: set[str] | None = None,
    min_survivors: int = 2,
) -> list[dict[str, Any]]:
    """Filter facts through the probabilistic forgetting curve.

    Parameters
    ----------
    facts:
        Chronologically ordered list of fact rows (oldest first).
    conflict_counts:
        Mapping of fact_id → number of conflict involvements (flags).
    now:
        Reference time for age calculation.  Defaults to UTC now.
    rng:
        Random instance for deterministic testing.  Defaults to
        ``random.Random()`` (non-deterministic).
    always_keep_ids:
        Fact IDs that bypass the filter entirely (e.g. the trigger fact).
    min_survivors:
        If fewer than this many facts survive, fall back to the last
        ``min_survivors * 5`` facts to ensure the detective has context.

    Returns
    -------
    List of facts that survived the forgetting filter, in original order.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if rng is None:
        rng = random.Random()
    if always_keep_ids is None:
        always_keep_ids = set()

    survivors: list[dict[str, Any]] = []

    for row in facts:
        fid = row.get("id", "")

        # Always keep explicitly protected facts
        if fid in always_keep_ids:
            survivors.append(row)
            continue

        ts = row.get("committed_at")
        if ts is None:
            # No timestamp — keep it (can't compute age)
            survivors.append(row)
            continue

        # Parse timestamp if it's a string
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        age_hours = (now - ts).total_seconds() / 3600
        flags = conflict_counts.get(fid, 0)

        keep_prob = compute_keep_probability(age_hours, flags)

        if rng.random() < keep_prob:
            survivors.append(row)

    # Ensure minimum context for the detective
    if len(survivors) < min_survivors:
        fallback_count = min(len(facts), min_survivors * 5)
        survivors = list(facts[-fallback_count:])

    return survivors
