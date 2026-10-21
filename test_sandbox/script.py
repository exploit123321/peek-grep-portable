"""High-performance directory crawler and search metric analyzer."""

import os
import sys
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class SearchBenchmark:
    query: str
    hits: int
    duration_ms: float
    mode: str = "content"

class MetricsCollector:
    """Collects and aggregates latency and throughput metrics for Peek & Grep."""

    def __init__(self, system_name: str = "Peek & Grep Workstation"):
        self.system_name = system_name
        self.benchmarks: List[SearchBenchmark] = []

    def record_query(self, query: str, hits: int, duration_ms: float) -> None:
        """Record an individual query execution event."""
        benchmark = SearchBenchmark(query=query, hits=hits, duration_ms=duration_ms)
        self.benchmarks.append(benchmark)
        print(f"[{self.system_name}] Query '{query}' yielded {hits} hits in {duration_ms:.2f}ms")

    def compute_summary(self) -> Dict[str, float]:
        """Calculates p50, p95, and average latency across all queries."""
        if not self.benchmarks:
            return {"count": 0, "avg_ms": 0.0, "p95_ms": 0.0}

        latencies = sorted([b.duration_ms for b in self.benchmarks])
        n = len(latencies)
        p95_idx = int(0.95 * n) if n > 1 else 0

        return {
            "count": float(n),
            "avg_ms": sum(latencies) / n,
            "p95_ms": latencies[p95_idx],
            "min_ms": latencies[0],
            "max_ms": latencies[-1],
        }

def run_sample_pipeline() -> None:
    collector = MetricsCollector()
    collector.record_query("architecture review", 14, 12.4)
    collector.record_query("SQLite FTS5", 28, 8.1)
    collector.record_query("Spacebar Quick Look", 6, 4.3)
    summary = collector.compute_summary()
    print("Performance Summary:", summary)

if __name__ == "__main__":
    run_sample_pipeline()
