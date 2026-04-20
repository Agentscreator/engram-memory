# Survey: Benchmarks for Evaluating Persistent Agent Memory Systems

## Executive Summary

This survey evaluates existing benchmarks and methodologies for evaluating persistent agent memory systems like Engram. We analyze their applicability and identify gaps.

## Existing Benchmarks

### 1. MemGPT Benchmarks
- **Focus**: Hierarchical memory management in LLMs
- **Metrics**: Conversation retention, task completion
- **Applicability**: Partially relevant - handles memory tiering

### 2. SWE-Bench
- **Focus**: Software engineering problem solving
- **Metrics**: Code correctness, bug fixes
- **Applicability**: Indirect - measures if memory helps solve complex tasks

### 3. AgentBench
- **Focus**: Multi-domain agent evaluation
- **Metrics**: Success rate, efficiency
- **Applicability**: Good - tests agents across environments

### 4. Memory Bank Benchmark
- **Focus**: Long-horizon dialogue memory
- **Metrics**: Recall accuracy, coherence
- **Applicability**: Highly relevant for fact retrieval

## Proposed Evaluation Framework for Engram

### Metric Categories

#### 1. Fact Retrieval Quality
- **Precision@K**: Of top K retrieved facts, how many are relevant?
- **Recall@K**: Of all relevant facts, how many are in top K?
- **MRR**: Mean Reciprocal Rank of first relevant fact

#### 2. Conflict Detection
- **Detection Rate**: % of actual conflicts detected
- **False Positive Rate**: % of flagged conflicts that are false
- **Latency**: Time from conflict creation to detection

#### 3. Memory Consistency
- **Contradiction Rate**: Facts that contradict each other over time
- **Staleness Detection**: % of outdated facts identified
- **Corroboration Accuracy**: Multi-agent agreement measurement

#### 4. System Performance
- **Query Latency**: P50, P95, P99 for fact retrieval
- **Commit Throughput**: Facts committed per second
- **Storage Efficiency**: Facts per GB

## Benchmark Suite for Engram

```python
# Example benchmark scenarios

SCENARIOS = {
    "fact_retrieval": {
        "description": "Query for specific facts across scopes",
        "metrics": ["precision@10", "recall@10", "mrr"],
        "data_size": "1K, 10K, 100K facts"
    },
    "conflict_detection": {
        "description": "Insert contradictory facts and measure detection",
        "metrics": ["detection_rate", "false_positive_rate", "latency"],
        "data_size": "100 conflict pairs"
    },
    "memory_consistency": {
        "description": "Long-running agent sessions with memory",
        "metrics": ["contradiction_rate", "staleness_detection"],
        "duration": "1 hour, 8 hours, 1 week"
    },
    "throughput": {
        "description": "High-volume fact commits",
        "metrics": ["throughput", "latency_p50", "latency_p99"],
        "load": "10, 100, 1000 commits/min"
    }
}
```

## Gap Analysis

| Gap | Description | Priority |
|-----|-------------|----------|
| Multi-agent memory benchmark | No standard for testing memory across multiple agents | High |
| Conflict resolution benchmark | No benchmark specifically for conflict detection | High |
| Long-horizon retention | Most benchmarks are short (<1 hour) | Medium |
| Cross-scope reasoning | Testing facts across scope hierarchies | Low |

## Recommendations

1. **Adopt AgentBench** as base for multi-agent evaluation
2. **Create Engram-specific conflict detection benchmark** 
3. **Implement internal benchmarks** for fact retrieval quality
4. **Track latency metrics** in production for performance monitoring

## References

- MemGPT: https://arxiv.org/abs/2310.08560
- SWE-Bench: https://arxiv.org/abs/2311.12971
- AgentBench: https://arxiv.org/abs/2308.02490