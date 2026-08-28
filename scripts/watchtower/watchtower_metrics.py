#!/usr/bin/env python3
"""
CloudVault Watchtower - Phase 9: Prometheus Metrics

Lightweight Prometheus-compatible metrics for Watchtower observability.

Implements the Prometheus text exposition format (OpenMetrics-compatible)
without requiring the prometheus_client library.

Metrics exposed:
  - watchtower_notifications_total (counter) — notifications sent, by status
  - watchtower_notification_failures_total (counter) — permanent failures, by event_type
  - watchtower_webhook_requests_total (counter) — webhook requests, by endpoint
  - watchtower_command_requests_total (counter) — Telegram commands, by command
  - watchtower_notification_queue_depth (gauge) — current queue depth
  - watchtower_notification_processing_seconds (histogram) — processing latency

Label cardinality is kept low by design:
  - event_type: BACKUP_COMPLETED, BACKUP_FAILED, HEALTH_ALERT, UNKNOWN (finite set)
  - command: status, health, metrics, storage, jobs, alerts, start, help (finite set)
  - endpoint: events, alertmanager, telegram (finite set)
  - status: sent, failed, retried (finite set)

Never used as labels:
  - filenames, user IDs, Telegram IDs, IP addresses, message contents
"""

import time
import threading
from typing import Dict, Any, Optional, List


class Counter:
    """Prometheus-compatible counter with optional label support."""

    def __init__(self, name: str, help_text: str, label_names: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, labels: Optional[Dict[str, str]] = None, value: float = 1.0):
        """Increment the counter."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def _make_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def render(self) -> str:
        """Render in Prometheus text exposition format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} counter")
        with self._lock:
            if not self._values:
                # Emit zero so Prometheus sees the metric exists
                if self.label_names:
                    # Emit with empty labels — Prometheus expects at least one sample
                    lines.append(f'{self.name}{{}} 0')
                else:
                    lines.append(f'{self.name} 0')
            else:
                for key, val in self._values.items():
                    if key:
                        label_str = ",".join(f'{k}="{v}"' for k, v in key)
                        lines.append(f'{self.name}{{{label_str}}} {val}')
                    else:
                        lines.append(f'{self.name} {val}')
        return "\n".join(lines)


class Gauge:
    """Prometheus-compatible gauge with optional label support."""

    def __init__(self, name: str, help_text: str, label_names: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Set the gauge value."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment the gauge."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def dec(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Decrement the gauge."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - value

    def _make_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def render(self) -> str:
        """Render in Prometheus text exposition format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} gauge")
        with self._lock:
            if not self._values:
                if self.label_names:
                    lines.append(f'{self.name}{{}} 0')
                else:
                    lines.append(f'{self.name} 0')
            else:
                for key, val in self._values.items():
                    if key:
                        label_str = ",".join(f'{k}="{v}"' for k, v in key)
                        lines.append(f'{self.name}{{{label_str}}} {val}')
                    else:
                        lines.append(f'{self.name} {val}')
        return "\n".join(lines)


class Histogram:
    """Prometheus-compatible histogram with fixed bucket boundaries."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Optional[List[str]] = None,
        buckets: Optional[tuple] = None,
    ):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._buckets: Dict[tuple, List[float]] = {}
        self._sums: Dict[tuple, float] = {}
        self._counts: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Record an observation."""
        key = self._make_key(labels)
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = [0.0] * len(self.buckets)
                self._sums[key] = 0.0
                self._counts[key] = 0.0

            self._sums[key] += value
            self._counts[key] += 1

            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    self._buckets[key][i] += 1

    def _make_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def render(self) -> str:
        """Render in Prometheus text exposition format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} histogram")

        with self._lock:
            if not self._values_exist():
                # Emit empty histogram so Prometheus sees it
                lines.append(f'{self.name}_bucket{{le="+Inf"}} 0')
                lines.append(f'{self.name}_sum 0')
                lines.append(f'{self.name}_count 0')
            else:
                for key in self._buckets:
                    bucket_counts = self._buckets[key]
                    label_prefix = ""
                    if key:
                        label_prefix = ",".join(f'{k}="{v}"' for k, v in key)

                    for i, bound in enumerate(self.buckets):
                        le_str = str(bound) if bound != float("inf") else "+Inf"
                        if label_prefix:
                            lines.append(
                                f'{self.name}_bucket{{{label_prefix},le="{le_str}"}} {int(bucket_counts[i])}'
                            )
                        else:
                            lines.append(
                                f'{self.name}_bucket{{le="{le_str}"}} {int(bucket_counts[i])}'
                            )

                    # +Inf bucket = total count
                    if label_prefix:
                        lines.append(
                            f'{self.name}_bucket{{{label_prefix},le="+Inf"}} {int(self._counts[key])}'
                        )
                        lines.append(f'{self.name}_sum{{{label_prefix}}} {self._sums[key]}')
                        lines.append(f'{self.name}_count{{{label_prefix}}} {int(self._counts[key])}')
                    else:
                        lines.append(f'{self.name}_bucket{{le="+Inf"}} {int(self._counts[key])}')
                        lines.append(f'{self.name}_sum {self._sums[key]}')
                        lines.append(f'{self.name}_count {int(self._counts[key])}')

        return "\n".join(lines)

    def _values_exist(self) -> bool:
        return bool(self._buckets)


# ======================================================================
# Singleton metrics registry
# ======================================================================

class WatchtowerMetrics:
    """Central metrics registry for Watchtower.

    All metrics are defined here to ensure consistency and prevent
    accidental high-cardinality label creation.
    """

    def __init__(self):
        # --- Counters ---
        self.notifications_total = Counter(
            "watchtower_notifications_total",
            "Total notifications processed by Watchtower",
            label_names=["status"],  # sent, failed, retried
        )

        self.notification_failures_total = Counter(
            "watchtower_notification_failures_total",
            "Total permanent notification failures by event type",
            label_names=["event_type"],
        )

        self.webhook_requests_total = Counter(
            "watchtower_webhook_requests_total",
            "Total webhook requests received by Watchtower",
            label_names=["endpoint"],  # events, alertmanager
        )

        self.command_requests_total = Counter(
            "watchtower_command_requests_total",
            "Total Telegram command requests processed",
            label_names=["command"],  # status, health, metrics, storage, jobs, alerts, start, help
        )

        # --- Gauges ---
        self.notification_queue_depth = Gauge(
            "watchtower_notification_queue_depth",
            "Current number of notifications in the queue (pending + retry)",
        )

        self.redis_connected = Gauge(
            "watchtower_redis_connected",
            "Whether Watchtower Redis connection is active (1=yes, 0=no)",
        )

        self.worker_running = Gauge(
            "watchtower_worker_running",
            "Whether the notification queue worker is running (1=yes, 0=no)",
        )

        self.uptime_seconds = Gauge(
            "watchtower_uptime_seconds",
            "Seconds since Watchtower service started",
        )

        # --- Histograms ---
        self.notification_processing_seconds = Histogram(
            "watchtower_notification_processing_seconds",
            "Time spent processing a single notification (seconds)",
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        )

        # Track service start time
        self._start_time = time.time()

    def update_queue_stats(self, queue) -> None:
        """Update queue-related gauges from NotificationQueue instance."""
        if queue is None:
            self.notification_queue_depth.set(0)
            self.redis_connected.set(0)
            self.worker_running.set(0)
            return

        # Redis connection status
        self.redis_connected.set(1 if queue._connected else 0)

        # Worker status
        self.worker_running.set(1 if queue._worker_task and not queue._worker_task.done() else 0)

        # Queue depth = pending count from stats
        if hasattr(queue, '_stats'):
            pending = queue._stats.get("enqueued", 0) - queue._stats.get("sent", 0) - queue._stats.get("failed", 0)
            self.notification_queue_depth.set(max(0, pending))

    def update_uptime(self) -> None:
        """Update the uptime gauge."""
        self.uptime_seconds.set(time.time() - self._start_time)

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        self.update_uptime()

        sections = [
            self.notifications_total.render(),
            self.notification_failures_total.render(),
            self.webhook_requests_total.render(),
            self.command_requests_total.render(),
            self.notification_queue_depth.render(),
            self.redis_connected.render(),
            self.worker_running.render(),
            self.uptime_seconds.render(),
            self.notification_processing_seconds.render(),
        ]
        return "\n\n".join(sections) + "\n"


# Global singleton
metrics = WatchtowerMetrics()
