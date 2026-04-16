"""Conflict Detection Benchmark Suite (Issue #14)

Measures precision/recall of conflict detection.

Run with:
    python -m benchmark.conflict_benchmark
"""

import asyncio
import uuid
from dataclasses import dataclass


@dataclass
class BenchmarkResult:
    scenario: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


class ConflictBenchmark:
    """Benchmark suite for conflict detection accuracy."""

    def __init__(self, engine):
        self.engine = engine

    async def run_numeric_conflict_test(self) -> BenchmarkResult:
        """Test: Numeric value conflicts (e.g., "timeout=30" vs "timeout=60")"""
        scope = f"bench:numeric:{uuid.uuid4().hex[:8]}"

        await self.engine.commit(
            {
                "content": "The API timeout is 30 seconds",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-a",
            }
        )
        await self.engine.commit(
            {
                "content": "The API timeout is 60 seconds",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-b",
            }
        )

        conflicts = await self.engine.get_conflicts(scope=scope)
        detected = len([c for c in conflicts if c.get("status") == "open"])

        return BenchmarkResult(
            scenario="numeric_conflict",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
        )

    async def run_false_positive_test(self) -> BenchmarkResult:
        """Test: Similar but non-conflicting facts."""
        scope = f"bench:falsepos:{uuid.uuid4().hex[:8]}"

        facts = [
            "The API returns JSON responses",
            "The API supports JSON and XML responses",
        ]

        for i, content in enumerate(facts):
            await self.engine.commit(
                {
                    "content": content,
                    "scope": scope,
                    "confidence": 0.9,
                    "fact_type": "observation",
                    "agent_id": f"bench-{i}",
                }
            )

        conflicts = await self.engine.get_conflicts(scope=scope)
        fp = len([c for c in conflicts if c.get("status") == "open"])

        return BenchmarkResult(
            scenario="false_positive",
            true_positives=0,
            false_positives=fp,
            false_negatives=0,
            precision=1.0 if fp == 0 else 0.0,
            recall=1.0,
            f1=1.0 if fp == 0 else 0.0,
        )

    async def run_all(self) -> list[BenchmarkResult]:
        """Run all benchmark scenarios."""
        results = []
        for name, test_fn in [
            ("Numeric Conflicts", self.run_numeric_conflict_test),
            ("False Positive Rate", self.run_false_positive_test),
        ]:
            try:
                result = await test_fn()
                results.append(result)
                print(
                    f"{name}: TP={result.true_positives}, FP={result.false_positives}, F1={result.f1:.2f}"
                )
            except Exception as e:
                print(f"{name}: ERROR - {e}")
        return results

    def print_summary(self, results: list[BenchmarkResult]) -> None:
        """Print benchmark summary."""
        if not results:
            return
        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"\n=== BENCHMARK SUMMARY ===")
        print(f"Precision: {precision:.2%}")
        print(f"Recall:    {recall:.2%}")
        print(f"F1 Score:  {f1:.2%}")


async def main():
    """Run benchmark suite."""
    from engram.storage import SQLiteStorage
    from engram.engine import EngramEngine

    storage = SQLiteStorage(None, workspace_id="benchmark")
    await storage.connect()
    engine = EngramEngine(storage)

    benchmark = ConflictBenchmark(engine)
    results = await benchmark.run_all()
    benchmark.print_summary(results)

    await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
