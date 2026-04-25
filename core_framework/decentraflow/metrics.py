"""
DecentraFlow — Lightweight Prometheus Metrics Collector

Zero-dependency metrics exposed at GET /metrics in Prometheus
exposition format.  Prometheus scrapes this endpoint — the node
never pushes.  Fully decentralized: each node owns its own metrics.

Thread-safe via threading.Lock (safe for concurrent asyncio workers
on the same event loop AND background threads).
"""

import threading
from typing import Dict, List


class MetricsCollector:
    """
    Collects counters, gauges, and histogram observations.
    Renders them in Prometheus exposition text format.
    """

    def __init__(self, node_name: str):
        self.node_name = node_name
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}

        # Metric metadata (HELP / TYPE lines for Prometheus)
        self._meta = {
            # Counters
            "tasks_ingested_total": ("counter", "Total tasks ingested via /ingest"),
            "tasks_completed_total": ("counter", "Total tasks successfully completed"),
            "tasks_failed_total": ("counter", "Total task processing failures"),
            "tasks_dead_letter_total": ("counter", "Total tasks moved to dead letter queue"),
            "tasks_timeout_total": ("counter", "Total tasks that timed out"),
            "tasks_forwarded_total": ("counter", "Total successful task forwards"),
            "forwarding_errors_total": ("counter", "Total forwarding failures"),
            "tasks_retried_total": ("counter", "Total task retries scheduled"),
            # Gauges
            "queue_pending": ("gauge", "Current number of PENDING tasks"),
            "queue_processing": ("gauge", "Current number of PROCESSING tasks"),
            "queue_dead_letter": ("gauge", "Current number of DEAD_LETTER tasks"),
            # Histograms
            "processing_duration_seconds": ("histogram", "Task processing duration in seconds"),
        }

    def inc(self, name: str, value: int = 1):
        """Increment a counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float):
        """Set a gauge to a specific value."""
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float):
        """Record a histogram observation."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)

    def get_counter(self, name: str) -> int:
        """Read a counter value (for testing)."""
        with self._lock:
            return self._counters.get(name, 0)

    def render(self) -> str:
        """Render all metrics in Prometheus exposition text format."""
        lines: List[str] = []
        prefix = "decentraflow"
        labels = f'node="{self.node_name}"'

        with self._lock:
            # ── Counters ─────────────────────────────────────────
            for name, value in sorted(self._counters.items()):
                meta = self._meta.get(name)
                if meta:
                    lines.append(f"# HELP {prefix}_{name} {meta[1]}")
                    lines.append(f"# TYPE {prefix}_{name} {meta[0]}")
                lines.append(f"{prefix}_{name}{{{labels}}} {value}")
                lines.append("")

            # ── Gauges ───────────────────────────────────────────
            for name, value in sorted(self._gauges.items()):
                meta = self._meta.get(name)
                if meta:
                    lines.append(f"# HELP {prefix}_{name} {meta[1]}")
                    lines.append(f"# TYPE {prefix}_{name} {meta[0]}")
                lines.append(f"{prefix}_{name}{{{labels}}} {value}")
                lines.append("")

            # ── Histograms ───────────────────────────────────────
            for name, observations in sorted(self._histograms.items()):
                meta = self._meta.get(name)
                if meta:
                    lines.append(f"# HELP {prefix}_{name} {meta[1]}")
                    lines.append(f"# TYPE {prefix}_{name} {meta[0]}")

                if observations:
                    total = sum(observations)
                    count = len(observations)
                    buckets = [
                        0.01, 0.05, 0.1, 0.25, 0.5,
                        1.0, 2.5, 5.0, 10.0, 30.0,
                        60.0, 120.0, 300.0,
                    ]
                    for b in buckets:
                        bucket_count = sum(1 for o in observations if o <= b)
                        lines.append(
                            f'{prefix}_{name}_bucket{{{labels},le="{b}"}} {bucket_count}'
                        )
                    lines.append(
                        f'{prefix}_{name}_bucket{{{labels},le="+Inf"}} {count}'
                    )
                    lines.append(f"{prefix}_{name}_sum{{{labels}}} {total:.6f}")
                    lines.append(f"{prefix}_{name}_count{{{labels}}} {count}")
                    lines.append("")

        return "\n".join(lines) + "\n" if lines else ""

