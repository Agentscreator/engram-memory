"""Conflict Detection Benchmark Suite (Issue #14, #34)

Measures precision/recall of conflict detection in multi-agent memory systems.
This benchmark quantifies how well a system catches contradictory beliefs between agents.

Run with:
    python -m benchmark.conflict_benchmark
    python -m benchmark.conflict_benchmark --verbose
    python -m benchmark.conflict_benchmark --output results.json
    python -m benchmark.conflict_benchmark --compare-baseline

Public benchmark for comparing multi-agent memory systems on their core claim:
catching when two agents develop contradictory beliefs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from engram.storage import SQLiteStorage
from engram.engine import EngramEngine


@dataclass
class BenchmarkResult:
    scenario: str
    description: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    latency_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "description": self.description,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "latency_ms": round(self.latency_ms, 2),
            **self.metadata,
        }


@dataclass
class BenchmarkSuite:
    name: str
    version: str = "1.0.0"
    description: str = "Engram Conflict Detection Benchmark"
    results: list[BenchmarkResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": [r.to_dict() for r in self.results],
            "summary": self.compute_summary(),
            "metadata": self.metadata,
        }

    def compute_summary(self) -> dict:
        if not self.results:
            return {}
        total_tp = sum(r.true_positives for r in self.results)
        total_fp = sum(r.false_positives for r in self.results)
        total_fn = sum(r.false_negatives for r in self.results)
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        avg_latency = (
            sum(r.latency_ms for r in self.results) / len(self.results) if self.results else 0.0
        )
        return {
            "total_tests": len(self.results),
            "total_true_positives": total_tp,
            "total_false_positives": total_fp,
            "total_false_negatives": total_fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "avg_latency_ms": round(avg_latency, 2),
        }

    def print_summary(self) -> None:
        summary = self.compute_summary()
        if not summary:
            print("No results to display.")
            return

        print("\n" + "=" * 60)
        print(f"  {self.name} v{self.version}")
        print(f"  {self.description}")
        print("=" * 60)
        print(f"\nTimestamp: {self.to_dict()['timestamp']}")
        print(f"Tests Run:  {summary['total_tests']}")
        print("\n--- AGGREGATE SCORES ---")
        print(f"  Precision:  {summary['precision']:>6.1%}")
        print(f"  Recall:    {summary['recall']:>6.1%}")
        print(f"  F1 Score:  {summary['f1']:>6.1%}")
        print(f"  Avg Latency: {summary['avg_latency_ms']:>5.2f}ms")
        print("\n--- DETAILED RESULTS ---")
        print(f"{'Scenario':<30} {'TP':>4} {'FP':>4} {'FN':>4} {'F1':>6}")
        print("-" * 52)
        for r in self.results:
            print(
                f"{r.scenario:<30} {r.true_positives:>4} {r.false_positives:>4} {r.false_negatives:>4} {r.f1:>6.1%}"
            )
        print("=" * 60)


class ConflictBenchmark:
    """Comprehensive benchmark suite for conflict detection accuracy.

    Tests multiple dimensions of conflict detection:
    - Numeric value contradictions
    - Semantic contradictions (natural language inference)
    - Temporal contradictions (changes over time)
    - Entity-level contradictions
    - Boolean contradictions
    - False positive rate
    """

    def __init__(self, engine: EngramEngine, verbose: bool = False):
        self.engine = engine
        self.verbose = verbose

    async def run_numeric_conflict_test(self) -> BenchmarkResult:
        """Test: Numeric value conflicts (e.g., "timeout=30" vs "timeout=60")"""
        scope = f"bench:numeric:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "The API timeout is 30 seconds",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-a",
            }
        )
        await self.engine.commit(
            {
                "content": "The API timeout is 60 seconds",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-b",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope)
        detected = len([c for c in conflicts if c.get("status") == "open"])

        if self.verbose:
            print(f"  Numeric conflict: detected={detected}")

        return BenchmarkResult(
            scenario="numeric_conflict",
            description="Numeric value contradictions (e.g., timeout=30 vs timeout=60)",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
            latency_ms=latency_ms,
            metadata={"agents": ["bench-agent-a", "bench-agent-b"]},
        )

    async def run_semantic_conflict_test(self) -> BenchmarkResult:
        """Test: Semantic contradictions using NLI (natural language inference)."""
        scope = f"bench:semantic:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "The API returns JSON responses only",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-c",
            }
        )
        await self.engine.commit(
            {
                "content": "The API returns both JSON and XML responses",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-d",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        detected = len(conflicts)

        if self.verbose:
            print(f"  Semantic conflict: detected={detected}")

        return BenchmarkResult(
            scenario="semantic_conflict",
            description="Semantic contradictions detected via NLI",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
            latency_ms=latency_ms,
            metadata={"type": "nli_based"},
        )

    async def run_entity_conflict_test(self) -> BenchmarkResult:
        """Test: Same entity, different values."""
        scope = f"bench:entity:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "Max database connections is 50",
                "scope": scope,
                "confidence": 0.85,
                "fact_type": "observation",
                "agent_id": "bench-agent-e",
            }
        )
        await self.engine.commit(
            {
                "content": "Max database connections is 200",
                "scope": scope,
                "confidence": 0.85,
                "fact_type": "observation",
                "agent_id": "bench-agent-f",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        detected = len(conflicts)

        if self.verbose:
            print(f"  Entity conflict: detected={detected}")

        return BenchmarkResult(
            scenario="entity_conflict",
            description="Same entity with different values (e.g., max_connections=50 vs 200)",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
            latency_ms=latency_ms,
            metadata={"entity": "max_database_connections"},
        )

    async def run_false_positive_test(self) -> BenchmarkResult:
        """Test: Similar but non-conflicting facts (should NOT trigger)."""
        scope = f"bench:falsepos:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
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
                    "agent_id": f"bench-agent-{i}",
                }
            )

        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        fp = len(conflicts)

        if self.verbose:
            print(f"  False positive: fp={fp}")

        return BenchmarkResult(
            scenario="false_positive_rate",
            description="Similar but non-conflicting facts (low FP rate = high precision)",
            true_positives=0,
            false_positives=fp,
            false_negatives=0,
            precision=1.0 if fp == 0 else 0.0,
            recall=1.0,
            f1=1.0 if fp == 0 else 0.0,
            latency_ms=latency_ms,
            metadata={"total_facts": len(facts)},
        )

    async def run_boolean_conflict_test(self) -> BenchmarkResult:
        """Test: Boolean/boolean contradictions."""
        scope = f"bench:boolean:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "Debug mode is enabled",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-g",
            }
        )
        await self.engine.commit(
            {
                "content": "Debug mode is disabled",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-h",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        detected = len(conflicts)

        if self.verbose:
            print(f"  Boolean conflict: detected={detected}")

        return BenchmarkResult(
            scenario="boolean_conflict",
            description="Boolean value contradictions (enabled vs disabled)",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
            latency_ms=latency_ms,
        )

    async def run_temporal_conflict_test(self) -> BenchmarkResult:
        """Test: Temporal contradictions (facts that changed over time)."""
        scope = f"bench:temporal:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "Service version is 1.0.0",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-i",
            }
        )
        await self.engine.commit(
            {
                "content": "Service version is 2.0.0",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-j",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        detected = len(conflicts)

        if self.verbose:
            print(f"  Temporal conflict: detected={detected}")

        return BenchmarkResult(
            scenario="temporal_conflict",
            description="Facts that changed over time (version 1.0 vs 2.0)",
            true_positives=1 if detected > 0 else 0,
            false_positives=0,
            false_negatives=1 if detected == 0 else 0,
            precision=1.0 if detected > 0 else 0.0,
            recall=1.0 if detected > 0 else 0.0,
            f1=1.0 if detected > 0 else 0.0,
            latency_ms=latency_ms,
        )

    async def run_cross_agent_evolution_test(self) -> BenchmarkResult:
        """Test: Same agent evolving facts (should be auto-resolved as evolution)."""
        scope = f"bench:evolution:{uuid.uuid4().hex[:8]}"

        start = time.perf_counter()
        await self.engine.commit(
            {
                "content": "Worker pool size is 4 threads",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-k",
            }
        )
        await self.engine.commit(
            {
                "content": "Worker pool size is 8 threads",
                "scope": scope,
                "confidence": 0.9,
                "fact_type": "observation",
                "agent_id": "bench-agent-k",
            }
        )
        await self.engine._detection_queue.join()
        latency_ms = (time.perf_counter() - start) * 1000

        open_conflicts = await self.engine.get_conflicts(scope=scope, status="open")
        resolved = await self.engine.get_conflicts(scope=scope, status="resolved")

        if self.verbose:
            print(f"  Evolution: open={len(open_conflicts)}, resolved={len(resolved)}")

        return BenchmarkResult(
            scenario="evolution_auto_resolve",
            description="Same agent fact evolution (should auto-resolve)",
            true_positives=1 if len(resolved) > 0 and len(open_conflicts) == 0 else 0,
            false_positives=len(open_conflicts),
            false_negatives=1 if len(resolved) == 0 else 0,
            precision=1.0 if len(open_conflicts) == 0 else 0.0,
            recall=1.0 if len(resolved) > 0 else 0.0,
            f1=1.0 if len(open_conflicts) == 0 and len(resolved) > 0 else 0.0,
            latency_ms=latency_ms,
            metadata={"auto_resolved": len(resolved) > 0},
        )

    async def run_all(self) -> list[BenchmarkResult]:
        """Run all benchmark scenarios."""
        results = []
        tests = [
            ("Numeric Conflict", self.run_numeric_conflict_test),
            ("Entity Conflict", self.run_entity_conflict_test),
            ("Boolean Conflict", self.run_boolean_conflict_test),
            ("Semantic Conflict", self.run_semantic_conflict_test),
            ("Temporal Conflict", self.run_temporal_conflict_test),
            ("False Positive Rate", self.run_false_positive_test),
            ("Evolution Auto-Resolve", self.run_cross_agent_evolution_test),
        ]

        print("\nRunning benchmark suite...")
        for name, test_fn in tests:
            try:
                print(f"  [{len(results) + 1}/{len(tests)}] {name}...", end=" ")
                result = await test_fn()
                results.append(result)
                status = "✓" if result.f1 >= 1.0 else "✗"
                print(
                    f"{status} TP={result.true_positives}, FP={result.false_positives}, F1={result.f1:.0%}"
                )
            except Exception as e:
                print(f"ERROR - {e}")
                results.append(
                    BenchmarkResult(
                        scenario=name.lower().replace(" ", "_"),
                        description=name,
                        metadata={"error": str(e)},
                    )
                )

        return results

    def print_summary(self, results: list[BenchmarkResult]) -> None:
        suite = BenchmarkSuite(
            name="Engram Conflict Detection Benchmark",
            version="1.1.0",
            results=results,
        )
        suite.print_summary()


async def run_benchmark(args: argparse.Namespace) -> BenchmarkSuite:
    """Execute the benchmark suite."""
    storage = SQLiteStorage(None, workspace_id="benchmark")
    await storage.connect()
    engine = EngramEngine(storage)

    benchmark = ConflictBenchmark(engine, verbose=args.verbose)

    if args.scenario:
        test_map = {
            "numeric": benchmark.run_numeric_conflict_test,
            "entity": benchmark.run_entity_conflict_test,
            "boolean": benchmark.run_boolean_conflict_test,
            "semantic": benchmark.run_semantic_conflict_test,
            "temporal": benchmark.run_temporal_conflict_test,
            "falsepos": benchmark.run_false_positive_test,
            "evolution": benchmark.run_cross_agent_evolution_test,
        }
        test_fn = test_map.get(args.scenario)
        if test_fn:
            results = [await test_fn()]
        else:
            print(f"Unknown scenario: {args.scenario}")
            results = []
    else:
        results = await benchmark.run_all()

    suite = BenchmarkSuite(
        name="Engram Conflict Detection Benchmark",
        version="1.1.0",
        results=results,
    )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(suite.to_dict(), f, indent=2)
        print(f"\nResults written to: {args.output}")

    await storage.close()
    return suite


def main():
    parser = argparse.ArgumentParser(
        description="Conflict Detection Benchmark Suite for multi-agent memory systems.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m benchmark.conflict_benchmark
  python -m benchmark.conflict_benchmark --verbose
  python -m benchmark.conflict_benchmark --output results.json
  python -m benchmark.conflict_benchmark --scenario numeric

Run with --compare-baseline to compare against known good systems.
        """,
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output results to JSON file",
    )
    parser.add_argument(
        "--scenario",
        "-s",
        help="Run a specific test scenario (numeric, entity, boolean, semantic, temporal, falsepos, evolution)",
    )
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare results against baseline systems",
    )

    args = parser.parse_args()

    suite = asyncio.run(run_benchmark(args))
    suite.print_summary()

    if args.compare_baseline:
        print("\n--- BASELINE COMPARISON ---")
        print("Note: Public benchmark comparison data available at:")
        print("  https://github.com/Agentscreator/engram-memory/wiki/Benchmarks")


if __name__ == "__main__":
    main()
