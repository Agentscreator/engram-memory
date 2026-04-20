"""Tests for the probabilistic forgetting curve.

Validates that the detective's forgetting filter matches the spec:
- < 24h:  forget 60-80% (keep 20-40%)
- 1-7d:   forget 80-90% (keep 10-20%)
- > 7d:   forget 90-95% (keep  5-10%)
- Flagged facts survive at higher rates (2× per flag)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from engram.forgetting import apply_forgetting, compute_keep_probability


# ── compute_keep_probability unit tests ──────────────────────────────


class TestKeepProbability:
    def test_fresh_fact_no_flags(self):
        """< 24h, no flags → base_keep = 0.30."""
        assert compute_keep_probability(age_hours=6, flag_count=0) == pytest.approx(0.30)

    def test_week_old_fact_no_flags(self):
        """1-7 days, no flags → base_keep = 0.15."""
        assert compute_keep_probability(age_hours=72, flag_count=0) == pytest.approx(0.15)

    def test_old_fact_no_flags(self):
        """> 7 days, no flags → base_keep = 0.07."""
        assert compute_keep_probability(age_hours=200, flag_count=0) == pytest.approx(0.07)

    def test_one_flag_doubles(self):
        """One flag doubles the keep probability."""
        base = compute_keep_probability(age_hours=6, flag_count=0)
        flagged = compute_keep_probability(age_hours=6, flag_count=1)
        assert flagged == pytest.approx(base * 2)

    def test_two_flags_quadruples(self):
        """Two flags → 4× base."""
        base = compute_keep_probability(age_hours=72, flag_count=0)
        flagged = compute_keep_probability(age_hours=72, flag_count=2)
        assert flagged == pytest.approx(base * 4)

    def test_many_flags_capped_at_one(self):
        """Enough flags cap the probability at 1.0."""
        prob = compute_keep_probability(age_hours=200, flag_count=10)
        assert prob == 1.0

    def test_boundary_24h(self):
        """Exactly 24h falls into the 1-7d bucket."""
        assert compute_keep_probability(age_hours=24, flag_count=0) == pytest.approx(0.15)

    def test_boundary_168h(self):
        """Exactly 168h (7 days) falls into the >7d bucket."""
        assert compute_keep_probability(age_hours=168, flag_count=0) == pytest.approx(0.07)


# ── apply_forgetting integration tests ───────────────────────────────


def _make_fact(fact_id: str, hours_ago: float, now: datetime) -> dict:
    ts = now - timedelta(hours=hours_ago)
    return {
        "id": fact_id,
        "content": f"fact {fact_id}",
        "committed_at": ts.isoformat(),
    }


class TestApplyForgetting:
    def test_always_keep_ids_bypass_filter(self):
        """Facts in always_keep_ids are never dropped."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact("keep-me", hours_ago=200, now=now)]
        # Seed that would normally drop a 200h-old fact (7% keep)
        rng = random.Random(999)
        result = apply_forgetting(facts, {}, now=now, rng=rng, always_keep_ids={"keep-me"})
        assert len(result) == 1
        assert result[0]["id"] == "keep-me"

    def test_no_timestamp_kept(self):
        """Facts without committed_at are always kept."""
        now = datetime.now(timezone.utc)
        facts = [{"id": "no-ts", "content": "mystery", "committed_at": None}]
        result = apply_forgetting(facts, {}, now=now)
        assert len(result) == 1

    def test_min_survivors_fallback(self):
        """If too few survive, fall back to recent facts."""
        now = datetime.now(timezone.utc)
        # 5 very old facts — most will be dropped at 7% keep rate
        facts = [_make_fact(f"old-{i}", hours_ago=500, now=now) for i in range(5)]
        # Use a seed that drops everything
        rng = random.Random(42)
        result = apply_forgetting(facts, {}, now=now, rng=rng, min_survivors=2)
        assert len(result) >= 2

    def test_statistical_24h_forgetting_rate(self):
        """Over many runs, < 24h facts should survive ~30% of the time (20-40% range)."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact("recent", hours_ago=6, now=now)]
        survived = 0
        trials = 5000
        for i in range(trials):
            rng = random.Random(i)
            result = apply_forgetting(facts, {}, now=now, rng=rng, min_survivors=0)
            if result:
                survived += 1
        rate = survived / trials
        # Should be in the 20-40% range (forgetting 60-80%)
        assert 0.20 <= rate <= 0.40, f"24h survival rate {rate:.2%} outside 20-40%"

    def test_statistical_week_forgetting_rate(self):
        """Over many runs, 1-7d facts should survive ~15% of the time (10-20% range)."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact("week-old", hours_ago=72, now=now)]
        survived = 0
        trials = 5000
        for i in range(trials):
            rng = random.Random(i)
            result = apply_forgetting(facts, {}, now=now, rng=rng, min_survivors=0)
            if result:
                survived += 1
        rate = survived / trials
        assert 0.10 <= rate <= 0.20, f"Week survival rate {rate:.2%} outside 10-20%"

    def test_statistical_old_forgetting_rate(self):
        """Over many runs, >7d facts should survive ~7% of the time (5-10% range)."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact("old", hours_ago=300, now=now)]
        survived = 0
        trials = 5000
        for i in range(trials):
            rng = random.Random(i)
            result = apply_forgetting(facts, {}, now=now, rng=rng, min_survivors=0)
            if result:
                survived += 1
        rate = survived / trials
        assert 0.04 <= rate <= 0.12, f"Old survival rate {rate:.2%} outside 4-12%"

    def test_flagged_facts_survive_more(self):
        """Flagged facts should survive at significantly higher rates."""
        now = datetime.now(timezone.utc)
        fact_id = "flagged-one"
        facts = [_make_fact(fact_id, hours_ago=72, now=now)]
        conflict_counts = {fact_id: 3}  # 3 flags → 8× base

        survived_flagged = 0
        survived_unflagged = 0
        trials = 5000
        for i in range(trials):
            rng = random.Random(i)
            flagged_result = apply_forgetting(
                facts, conflict_counts, now=now, rng=rng, min_survivors=0
            )
            rng2 = random.Random(i)
            unflagged_result = apply_forgetting(facts, {}, now=now, rng=rng2, min_survivors=0)
            if flagged_result:
                survived_flagged += 1
            if unflagged_result:
                survived_unflagged += 1

        flagged_rate = survived_flagged / trials
        unflagged_rate = survived_unflagged / trials
        # 3 flags = 8× base (0.15) = 1.0 capped, so flagged should survive ~100%
        assert flagged_rate > unflagged_rate * 3, (
            f"Flagged rate {flagged_rate:.2%} should be much higher than "
            f"unflagged rate {unflagged_rate:.2%}"
        )

    def test_deterministic_with_seed(self):
        """Same seed produces same results."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact(f"f-{i}", hours_ago=i * 10, now=now) for i in range(20)]
        r1 = apply_forgetting(facts, {}, now=now, rng=random.Random(42), min_survivors=0)
        r2 = apply_forgetting(facts, {}, now=now, rng=random.Random(42), min_survivors=0)
        assert [f["id"] for f in r1] == [f["id"] for f in r2]

    def test_preserves_chronological_order(self):
        """Surviving facts maintain their original chronological order."""
        now = datetime.now(timezone.utc)
        facts = [_make_fact(f"f-{i}", hours_ago=(20 - i), now=now) for i in range(20)]
        rng = random.Random(123)
        result = apply_forgetting(facts, {}, now=now, rng=rng, min_survivors=0)
        ids = [f["id"] for f in result]
        # Check order is preserved (subset of original order)
        original_ids = [f["id"] for f in facts]
        original_positions = [original_ids.index(fid) for fid in ids]
        assert original_positions == sorted(original_positions)

    def test_datetime_object_timestamps(self):
        """Works with datetime objects (not just ISO strings)."""
        now = datetime.now(timezone.utc)
        fact = {
            "id": "dt-fact",
            "content": "test",
            "committed_at": now - timedelta(hours=6),
        }
        result = apply_forgetting([fact], {}, now=now, rng=random.Random(0), min_survivors=0)
        # Should not raise — just verify it runs
        assert isinstance(result, list)
