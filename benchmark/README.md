# Conflict Detection Benchmark Suite

A public benchmark for comparing multi-agent memory systems on their core claim: catching when two agents develop contradictory beliefs.

## Overview

This benchmark measures:

- **Precision** - How accurate is conflict detection?
- **Recall** - How many conflicts are caught?
- **F1 Score** - Harmonic mean of precision and recall
- **Latency** - How fast is detection?

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run the benchmark
python -m benchmark.conflict_benchmark
```

## Test Scenarios

| Scenario | Description |
|----------|------------|
| `numeric_conflict` | Numeric value contradictions (e.g., timeout=30 vs timeout=60) |
| `entity_conflict` | Same entity, different values (e.g., max_connections=50 vs 200) |
| `boolean_conflict` | Boolean contradictions (enabled vs disabled) |
| `semantic_conflict` | Natural language inference contradictions |
| `temporal_conflict` | Temporal contradictions (facts that changed over time) |
| `evolution` | Same agent fact evolution (auto-resolved) |
| `false_positive` | Similar but non-conflicting facts |

## Usage

### Run Full Suite

```bash
python -m benchmark.conflict_benchmark
```

### Run Specific Scenario

```bash
python -m benchmark.conflict_benchmark --scenario numeric
```

### Verbose Output

```bash
python -m benchmark.conflict_benchmark --verbose
```

### Save Results

```bash
python -m benchmark.conflict_benchmark --output results.json
```

### Compare with Baseline

```bash
python -m benchmark.conflict_benchmark --compare-baseline
```

## Output Format

```json
{
  "name": "Engram Conflict Detection Benchmark",
  "version": "1.1.0",
  "timestamp": "2026-04-19T12:00:00Z",
  "results": [
    {
      "scenario": "numeric_conflict",
      "description": "Numeric value contradictions",
      "true_positives": 1,
      "false_positives": 0,
      "false_negatives": 0,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0,
      "latency_ms": 45.2
    }
  ],
  "summary": {
    "total_tests": 7,
    "total_true_positives": 7,
    "total_false_positives": 0,
    "total_false_negatives": 0,
    "precision": 1.0,
    "recall": 1.0,
    "f1": 1.0,
    "avg_latency_ms": 52.3
  }
}
```

## API Usage

```python
from benchmark.conflict_benchmark import ConflictBenchmark, BenchmarkSuite
from engram.storage import SQLiteStorage
from engram.engine import EngramEngine

async def run_suite():
    storage = SQLiteStorage(None, workspace_id="benchmark")
    await storage.connect()
    engine = EngramEngine(storage)
    
    benchmark = ConflictBenchmark(engine, verbose=True)
    results = await benchmark.run_all()
    
    suite = BenchmarkSuite(
        name="My Benchmark",
        version="1.0.0",
        results=results,
    )
    
    print(suite.to_dict())
    await storage.close()

asyncio.run(run_suite())
```

## Why This Benchmark Matters

No public benchmark exists comparing multi-agent memory systems on their core claim: catching when two agents develop contradictory beliefs.

This benchmark:
1. **Quantifies** detection accuracy across multiple dimensions
2. **Enables** fair comparison between systems
3. **Tracks** improvements over time
4. **Promotes** transparency in multi-agent memory research

## License

MIT License - Use freely for research and benchmarking.

## Citation

If you use this benchmark in research, please cite:

```
@software{engram_benchmark_2026,
  title = {Conflict Detection Benchmark Suite},
  author = {Engram Team},
  year = {2026},
  url = {https://github.com/Agentscreator/engram-memory}
}
```

## Contributing

To add new test scenarios:

1. Add a new method to `ConflictBenchmark` class
2. Return `BenchmarkResult` with TP/FP/FN counts
3. Update `run_all()` to include the new test
4. Submit PR to the repository

## Support

- GitHub Issues: https://github.com/Agentscreator/engram-memory/issues
- Discord: https://discord.gg/engram