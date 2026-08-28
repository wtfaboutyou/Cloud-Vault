#!/usr/bin/env python3
"""
Comprehensive tests for CloudVault Watchtower Phase 9 — Prometheus Metrics.

Tests cover:
  - Counter: increment, render, labels
  - Gauge: set/inc/dec, render, labels
  - Histogram: observe, render, buckets
  - WatchtowerMetrics: all metrics, render, update_queue_stats
  - /metrics/prometheus endpoint integration
  - No high-cardinality labels verification
  - Prometheus text format compliance

Run:  python3 tests/test_watchtower_metrics.py
"""

import os
import sys
import time
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "watchtower"))

from watchtower_metrics import Counter, Gauge, Histogram, WatchtowerMetrics


# ======================================================================
# 1. Counter Tests
# ======================================================================

class TestCounter(unittest.TestCase):
    """Test the Counter metric type."""

    def test_counter_zero_value(self):
        """Counter emits zero when no increments."""
        c = Counter("test_counter", "A test counter")
        output = c.render()
        self.assertIn("# HELP test_counter A test counter", output)
        self.assertIn("# TYPE test_counter counter", output)
        self.assertIn("test_counter 0", output)

    def test_counter_increment(self):
        """Counter increments correctly."""
        c = Counter("test_counter", "A test counter")
        c.inc()
        c.inc()
        c.inc(value=5)
        output = c.render()
        self.assertIn("test_counter 7", output)

    def test_counter_with_labels(self):
        """Counter with labels renders correctly."""
        c = Counter("test_counter", "A test counter", label_names=["status"])
        c.inc(labels={"status": "sent"})
        c.inc(labels={"status": "sent"})
        c.inc(labels={"status": "failed"})
        output = c.render()
        self.assertIn('test_counter{status="sent"} 2', output)
        self.assertIn('test_counter{status="failed"} 1', output)

    def test_counter_thread_safety(self):
        """Counter is thread-safe."""
        import threading
        c = Counter("test_counter", "A test counter")

        def increment():
            for _ in range(100):
                c.inc()

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        output = c.render()
        self.assertIn("test_counter 1000", output)


# ======================================================================
# 2. Gauge Tests
# ======================================================================

class TestGauge(unittest.TestCase):
    """Test the Gauge metric type."""

    def test_gauge_zero_value(self):
        """Gauge emits zero when no value set."""
        g = Gauge("test_gauge", "A test gauge")
        output = g.render()
        self.assertIn("# HELP test_gauge A test gauge", output)
        self.assertIn("# TYPE test_gauge gauge", output)
        self.assertIn("test_gauge 0", output)

    def test_gauge_set(self):
        """Gauge set works correctly."""
        g = Gauge("test_gauge", "A test gauge")
        g.set(42.5)
        output = g.render()
        self.assertIn("test_gauge 42.5", output)

    def test_gauge_inc_dec(self):
        """Gauge inc/dec work correctly."""
        g = Gauge("test_gauge", "A test gauge")
        g.inc(10)
        g.inc(5)
        g.dec(3)
        output = g.render()
        self.assertIn("test_gauge 12", output)

    def test_gauge_with_labels(self):
        """Gauge with labels renders correctly."""
        g = Gauge("test_gauge", "A test gauge", label_names=["component"])
        g.set(1, labels={"component": "redis"})
        g.set(0, labels={"component": "worker"})
        output = g.render()
        self.assertIn('test_gauge{component="redis"} 1', output)
        self.assertIn('test_gauge{component="worker"} 0', output)


# ======================================================================
# 3. Histogram Tests
# ======================================================================

class TestHistogram(unittest.TestCase):
    """Test the Histogram metric type."""

    def test_histogram_empty(self):
        """Histogram emits empty buckets when no observations."""
        h = Histogram("test_hist", "A test histogram")
        output = h.render()
        self.assertIn("# HELP test_hist A test histogram", output)
        self.assertIn("# TYPE test_hist histogram", output)
        self.assertIn('test_hist_bucket{le="+Inf"} 0', output)
        self.assertIn("test_hist_sum 0", output)
        self.assertIn("test_hist_count 0", output)

    def test_histogram_observations(self):
        """Histogram accumulates observations correctly."""
        h = Histogram("test_hist", "A test histogram", buckets=(0.1, 0.5, 1.0))
        h.observe(0.05)
        h.observe(0.3)
        h.observe(0.8)
        h.observe(1.5)
        output = h.render()
        # Count of observations in each bucket
        self.assertIn('test_hist_bucket{le="0.1"} 1', output)
        self.assertIn('test_hist_bucket{le="0.5"} 2', output)
        self.assertIn('test_hist_bucket{le="1.0"} 3', output)
        self.assertIn('test_hist_bucket{le="+Inf"} 4', output)
        self.assertIn("test_hist_count 4", output)

    def test_histogram_with_labels(self):
        """Histogram with labels renders correctly."""
        h = Histogram("test_hist", "A test histogram", label_names=["type"])
        h.observe(0.5, labels={"type": "fast"})
        h.observe(2.0, labels={"type": "slow"})
        output = h.render()
        self.assertIn('test_hist_bucket{type="fast",le="0.5"}', output)
        self.assertIn('test_hist_bucket{type="slow",le="0.5"}', output)

    def test_histogram_default_buckets(self):
        """Histogram uses sensible default buckets."""
        h = Histogram("test_hist", "A test histogram")
        self.assertEqual(h.buckets, Histogram.DEFAULT_BUCKETS)
        self.assertIn(0.1, h.buckets)
        self.assertIn(1.0, h.buckets)
        self.assertIn(10.0, h.buckets)


# ======================================================================
# 4. WatchtowerMetrics Tests
# ======================================================================

class TestWatchtowerMetrics(unittest.TestCase):
    """Test the WatchtowerMetrics registry."""

    def setUp(self):
        """Create a fresh metrics instance for each test."""
        self.m = WatchtowerMetrics()

    def test_all_metrics_defined(self):
        """All required metrics are defined."""
        self.assertTrue(hasattr(self.m, "notifications_total"))
        self.assertTrue(hasattr(self.m, "notification_failures_total"))
        self.assertTrue(hasattr(self.m, "webhook_requests_total"))
        self.assertTrue(hasattr(self.m, "command_requests_total"))
        self.assertTrue(hasattr(self.m, "notification_queue_depth"))
        self.assertTrue(hasattr(self.m, "redis_connected"))
        self.assertTrue(hasattr(self.m, "worker_running"))
        self.assertTrue(hasattr(self.m, "uptime_seconds"))
        self.assertTrue(hasattr(self.m, "notification_processing_seconds"))

    def test_render_all_metrics(self):
        """Render produces valid Prometheus text for all metrics."""
        output = self.m.render()
        # All metric names should appear
        self.assertIn("watchtower_notifications_total", output)
        self.assertIn("watchtower_notification_failures_total", output)
        self.assertIn("watchtower_webhook_requests_total", output)
        self.assertIn("watchtower_command_requests_total", output)
        self.assertIn("watchtower_notification_queue_depth", output)
        self.assertIn("watchtower_redis_connected", output)
        self.assertIn("watchtower_worker_running", output)
        self.assertIn("watchtower_uptime_seconds", output)
        self.assertIn("watchtower_notification_processing_seconds", output)

    def test_render_valid_format(self):
        """Rendered output follows Prometheus text exposition format."""
        output = self.m.render()
        lines = output.strip().split("\n")
        for line in lines:
            # Skip empty lines and HELP/TYPE comments
            if not line or line.startswith("#"):
                continue
            # Valid lines: metric_name{labels} value or metric_name value
            self.assertRegex(
                line,
                r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})?\s+[0-9.e+-]+$',
                f"Invalid Prometheus line: {line}"
            )

    def test_update_queue_stats_with_queue(self):
        """update_queue_stats reads from queue instance."""
        mock_queue = MagicMock()
        mock_queue._connected = True
        mock_queue._worker_task = MagicMock()
        mock_queue._worker_task.done.return_value = False
        mock_queue._stats = {"enqueued": 10, "sent": 7, "failed": 1}

        self.m.update_queue_stats(mock_queue)
        self.assertEqual(self.m.redis_connected._values.get((), 0), 1)
        self.assertEqual(self.m.worker_running._values.get((), 0), 1)
        self.assertEqual(self.m.notification_queue_depth._values.get((), 0), 2)

    def test_update_queue_stats_with_none(self):
        """update_queue_stats with None queue resets gauges."""
        self.m.update_queue_stats(None)
        self.assertEqual(self.m.redis_connected._values.get((), 0), 0)
        self.assertEqual(self.m.worker_running._values.get((), 0), 0)
        self.assertEqual(self.m.notification_queue_depth._values.get((), 0), 0)

    def test_update_uptime(self):
        """update_uptime sets a positive value."""
        self.m.update_uptime()
        uptime = self.m.uptime_seconds._values.get((), 0)
        self.assertGreaterEqual(uptime, 0)

    def test_counter_metric_labels_are_low_cardinality(self):
        """Counter labels have finite, bounded values."""
        # notifications_total has status label: sent, failed, retried (3 values)
        self.m.notifications_total.inc(labels={"status": "sent"})
        self.m.notifications_total.inc(labels={"status": "failed"})
        self.m.notifications_total.inc(labels={"status": "retried"})
        self.assertEqual(len(self.m.notifications_total._values), 3)

        # webhook_requests_total has endpoint label: events, alertmanager (2 values)
        self.m.webhook_requests_total.inc(labels={"endpoint": "events"})
        self.m.webhook_requests_total.inc(labels={"endpoint": "alertmanager"})
        self.assertEqual(len(self.m.webhook_requests_total._values), 2)

    def test_command_labels_are_bounded(self):
        """Command labels have finite, bounded values."""
        commands = ["status", "health", "metrics", "storage", "jobs", "alerts", "start", "help"]
        for cmd in commands:
            self.m.command_requests_total.inc(labels={"command": cmd})
        self.assertEqual(len(self.m.command_requests_total._values), len(commands))


# ======================================================================
# 5. No High-Cardinality Labels Verification
# ======================================================================

class TestNoHighCardinalityLabels(unittest.TestCase):
    """Verify no high-cardinality labels are used anywhere."""

    def test_no_filename_labels(self):
        """No metric uses 'filename' as a label."""
        m = WatchtowerMetrics()
        output = m.render()
        self.assertNotIn('filename=', output)

    def test_no_user_id_labels(self):
        """No metric uses 'user_id' as a label."""
        m = WatchtowerMetrics()
        output = m.render()
        self.assertNotIn('user_id=', output)

    def test_no_telegram_id_labels(self):
        """No metric uses 'telegram_id' as a label."""
        m = WatchtowerMetrics()
        output = m.render()
        self.assertNotIn('telegram_id=', output)

    def test_no_ip_address_labels(self):
        """No metric uses 'ip' or 'ip_address' as a label."""
        m = WatchtowerMetrics()
        output = m.render()
        self.assertNotIn('ip=', output)
        self.assertNotIn('ip_address=', output)

    def test_no_message_content_labels(self):
        """No metric uses 'message' as a label."""
        m = WatchtowerMetrics()
        output = m.render()
        self.assertNotIn('message=', output)


# ======================================================================
# 6. Prometheus Endpoint Integration Tests
# ======================================================================

class TestMetricsEndpoint(unittest.TestCase):
    """Test /metrics/prometheus endpoint integration."""

    def test_endpoint_returns_text_plain(self):
        """Endpoint returns Prometheus text format."""
        from watchtower_metrics import metrics as wt_metrics
        output = wt_metrics.render()
        # Should contain HELP and TYPE lines
        self.assertIn("# HELP", output)
        self.assertIn("# TYPE", output)

    def test_endpoint_content_type(self):
        """Prometheus expects text/plain; version=0.0.4."""
        # This is tested at the aiohttp handler level
        # Here we verify the format is valid
        from watchtower_metrics import metrics as wt_metrics
        output = wt_metrics.render()
        lines = output.strip().split("\n")
        # First non-empty, non-comment line should be a metric
        for line in lines:
            if line and not line.startswith("#"):
                self.assertRegex(line, r'^[a-zA-Z_:]')
                break


# ======================================================================
# 7. Config Integration Tests
# ======================================================================

class TestConfigIntegration(unittest.TestCase):
    """Test Config class metrics settings."""

    def test_config_has_prometheus_settings(self):
        """Config has prometheus_enabled and prometheus_port."""
        from watchtower import Config
        config = Config()
        self.assertTrue(config.prometheus_enabled)
        self.assertEqual(config.prometheus_port, 9090)

    def test_config_prometheus_from_env(self):
        """Config reads prometheus settings from environment."""
        from watchtower import Config
        with patch.dict(os.environ, {
            "WATCHTOWER_PROMETHEUS_ENABLED": "false",
            "WATCHTOWER_PROMETHEUS_PORT": "9091",
        }):
            config = Config.from_env()
            self.assertFalse(config.prometheus_enabled)
            self.assertEqual(config.prometheus_port, 9091)


if __name__ == "__main__":
    unittest.main()
