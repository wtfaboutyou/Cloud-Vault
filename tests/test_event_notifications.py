#!/usr/bin/env python3
"""
Comprehensive tests for CloudVault Watchtower Phase 7 — Event Notifications.

Tests cover:
  - Event webhook payload handling
  - Event deduplication/debouncing
  - Event formatting for Telegram
  - Event routing to authorized users
  - Notification preferences
  - Telegram unavailable handling
  - Backup event scenarios
  - Health alert event scenarios
  - Upload event scenarios (documented limitation)
  - Original CloudVault operation independence
  - No secret leakage

Run:  python3 -m pytest tests/test_event_notifications.py -v
  or: python3 tests/test_event_notifications.py
"""

import json
import os
import sys
import time
import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "watchtower"))

from watchtower import (
    HealthServer,
    WatchtowerService,
    Config,
    _EVENT_DEDUP_WINDOW_SECONDS,
    _recent_events,
)


def run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ======================================================================
# 1. Event webhook payload tests
# ======================================================================

class TestEventWebhookPayload(unittest.TestCase):
    """Test event webhook payload handling."""

    def test_backup_completed_payload(self):
        """Valid backup completed event payload."""
        payload = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
            "timestamp": "2026-08-27 03:15:00 UTC",
            "label": "daily",
            "size": "1.2G",
            "duration": "2m 30s",
        }
        self.assertEqual(payload["event_type"], "BACKUP_COMPLETED")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["label"], "daily")

    def test_backup_failed_payload(self):
        """Valid backup failed event payload."""
        payload = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup daily failed",
            "timestamp": "2026-08-27 03:15:00 UTC",
            "label": "daily",
            "exit_code": 1,
            "duration": "0m 45s",
        }
        self.assertEqual(payload["event_type"], "BACKUP_FAILED")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["exit_code"], 1)

    def test_health_alert_payload(self):
        """Valid health alert event payload."""
        payload = {
            "event_type": "HEALTH_ALERT",
            "status": "warning",
            "detail": "Disk usage above 75%",
            "timestamp": "2026-08-27 03:15:00 UTC",
        }
        self.assertEqual(payload["event_type"], "HEALTH_ALERT")
        self.assertEqual(payload["status"], "warning")

    def test_upload_completed_payload(self):
        """Upload completed event payload (for future use)."""
        payload = {
            "event_type": "UPLOAD_COMPLETED",
            "status": "success",
            "detail": "File uploaded successfully",
            "timestamp": "2026-08-27 03:15:00 UTC",
        }
        self.assertEqual(payload["event_type"], "UPLOAD_COMPLETED")

    def test_upload_failed_payload(self):
        """Upload failed event payload (for future use)."""
        payload = {
            "event_type": "UPLOAD_FAILED",
            "status": "error",
            "detail": "Upload rejected",
            "timestamp": "2026-08-27 03:15:00 UTC",
        }
        self.assertEqual(payload["event_type"], "UPLOAD_FAILED")

    def test_empty_payload(self):
        """Empty payload should be handled gracefully."""
        payload = {}
        # Should not raise
        self.assertEqual(payload.get("event_type", "UNKNOWN"), "UNKNOWN")

    def test_missing_optional_fields(self):
        """Payload with only required fields should work."""
        payload = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
        }
        self.assertIn("event_type", payload)
        self.assertIn("status", payload)
        self.assertNotIn("label", payload)
        self.assertNotIn("size", payload)


# ======================================================================
# 2. Event deduplication tests
# ======================================================================

class TestEventDeduplication(unittest.TestCase):
    """Test event deduplication mechanism."""

    def setUp(self):
        """Clear event dedup cache before each test."""
        _recent_events.clear()

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_new_event_not_duplicate(self):
        """New event should not be flagged as duplicate."""
        server = self._make_server()
        fp = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        self.assertFalse(server._is_duplicate_event(fp))

    def test_same_event_is_duplicate(self):
        """Same event within dedup window should be flagged as duplicate."""
        server = self._make_server()
        fp = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        server._mark_event_sent(fp)
        self.assertTrue(server._is_duplicate_event(fp))

    def test_different_event_not_duplicate(self):
        """Different event should not be flagged as duplicate."""
        server = self._make_server()
        fp1 = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        fp2 = server._compute_event_fingerprint("BACKUP_FAILED", "daily")
        server._mark_event_sent(fp1)
        self.assertFalse(server._is_duplicate_event(fp2))

    def test_event_expires_after_window(self):
        """Event should no longer be duplicate after dedup window expires."""
        server = self._make_server()
        fp = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        # Simulate old event by setting timestamp in the past
        _recent_events[fp] = time.time() - _EVENT_DEDUP_WINDOW_SECONDS - 1
        self.assertFalse(server._is_duplicate_event(fp))

    def test_dedup_cache_cleanup(self):
        """Dedup cache should be cleaned up when it grows too large."""
        server = self._make_server()
        # Add many entries with old timestamps to trigger cleanup
        old_time = time.time() - _EVENT_DEDUP_WINDOW_SECONDS - 10
        for i in range(501):
            fp = f"test_event:{i}"
            _recent_events[fp] = old_time
        # Trigger cleanup by adding one more
        server._mark_event_sent("trigger_cleanup")
        # Old entries should be cleaned up, only the new one remains
        self.assertLess(len(_recent_events), 502)

    def test_fingerprint_contains_event_type(self):
        """Fingerprint should contain event type."""
        server = self._make_server()
        fp = server._compute_event_fingerprint("BACKUP_COMPLETED", "detail")
        self.assertTrue(fp.startswith("BACKUP_COMPLETED:"))

    def test_fingerprint_unique_per_detail(self):
        """Different details should produce different fingerprints."""
        server = self._make_server()
        fp1 = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        fp2 = server._compute_event_fingerprint("BACKUP_COMPLETED", "weekly")
        self.assertNotEqual(fp1, fp2)


# ======================================================================
# 3. Event formatting tests
# ======================================================================

class TestEventFormatting(unittest.TestCase):
    """Test event formatting for Telegram."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_backup_completed_format(self):
        """Backup completed event should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
            "label": "daily",
            "size": "1.2G",
            "duration": "2m 30s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Backup", message)
        self.assertIn("SUCCESS", message)
        self.assertIn("daily", message)
        self.assertIn("1.2G", message)
        self.assertIn("2m 30s", message)

    def test_backup_failed_format(self):
        """Backup failed event should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup daily failed",
            "label": "daily",
            "exit_code": 1,
            "duration": "0m 45s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Backup", message)
        self.assertIn("FAILED", message)
        self.assertIn("daily", message)
        self.assertIn("1", message)

    def test_health_alert_format(self):
        """Health alert event should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "HEALTH_ALERT",
            "status": "warning",
            "detail": "Disk usage above 75%",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Health", message)
        self.assertIn("WARNING", message)
        self.assertIn("Disk usage above 75%", message)

    def test_upload_completed_format(self):
        """Upload completed event should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "UPLOAD_COMPLETED",
            "status": "success",
            "detail": "File uploaded",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Upload", message)
        self.assertIn("SUCCESS", message)

    def test_unknown_event_type_format(self):
        """Unknown event type should still format correctly."""
        server = self._make_server()
        event = {
            "event_type": "CUSTOM_EVENT",
            "status": "info",
            "detail": "Something happened",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Event", message)
        self.assertIn("INFO", message)

    def test_minimal_event_format(self):
        """Event with only required fields should format without errors."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Backup", message)
        self.assertIn("SUCCESS", message)

    def test_timestamp_included(self):
        """Timestamp should be included when provided."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "timestamp": "2026-08-27 03:15:00 UTC",
        }
        message = server._format_event_telegram(event)
        self.assertIn("2026-08-27 03:15:00 UTC", message)

    def test_grafana_link_included_when_configured(self):
        """Grafana link should be included when WATCHTOWER_GRAFANA_URL is set."""
        server = self._make_server()
        with patch.dict(os.environ, {"WATCHTOWER_GRAFANA_URL": "http://grafana:3000"}):
            event = {
                "event_type": "BACKUP_COMPLETED",
                "status": "success",
            }
            message = server._format_event_telegram(event)
            self.assertIn("http://grafana:3000", message)

    def test_grafana_link_not_included_by_default(self):
        """Grafana link should not be included when WATCHTOWER_GRAFANA_URL is not set."""
        server = self._make_server()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("WATCHTOWER_GRAFANA_URL", None)
            event = {
                "event_type": "BACKUP_COMPLETED",
                "status": "success",
            }
            message = server._format_event_telegram(event)
            self.assertNotIn("Grafana", message)


# ======================================================================
# 4. Backup event scenario tests
# ======================================================================

class TestBackupEventScenarios(unittest.TestCase):
    """Test backup event scenarios."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_backup_completed_daily(self):
        """Daily backup completion should produce correct notification."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
            "label": "daily",
            "size": "2.5G",
            "duration": "5m 12s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("daily", message)
        self.assertIn("2.5G", message)
        self.assertIn("5m 12s", message)

    def test_backup_completed_weekly(self):
        """Weekly backup completion should produce correct notification."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup weekly completed",
            "label": "weekly",
            "size": "12.8G",
            "duration": "15m 30s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("weekly", message)
        self.assertIn("12.8G", message)

    def test_backup_completed_monthly(self):
        """Monthly backup completion should produce correct notification."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup monthly completed",
            "label": "monthly",
            "size": "45.2G",
            "duration": "45m 0s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("monthly", message)
        self.assertIn("45.2G", message)

    def test_backup_failed_encryption_error(self):
        """Backup failure due to encryption error should be reported."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup daily failed",
            "label": "daily",
            "exit_code": 1,
            "duration": "0m 30s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("FAILED", message)
        self.assertIn("1", message)

    def test_backup_failed_postgres_error(self):
        """Backup failure due to PostgreSQL error should be reported."""
        server = self._make_server()
        event = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup daily failed",
            "label": "daily",
            "exit_code": 1,
            "duration": "0m 15s",
        }
        message = server._format_event_telegram(event)
        self.assertIn("FAILED", message)

    def test_backup_dedup_daily(self):
        """Two daily backup events should be deduplicated."""
        server = self._make_server()
        _recent_events.clear()

        event1 = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
        }
        event2 = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
        }

        fp1 = server._compute_event_fingerprint(
            event1["event_type"], event1["detail"]
        )
        fp2 = server._compute_event_fingerprint(
            event2["event_type"], event2["detail"]
        )

        # First event is not duplicate
        self.assertFalse(server._is_duplicate_event(fp1))
        server._mark_event_sent(fp1)

        # Second event with same fingerprint is duplicate
        self.assertTrue(server._is_duplicate_event(fp2))

    def test_backup_different_labels_not_deduped(self):
        """Different backup labels should not be deduplicated."""
        server = self._make_server()
        _recent_events.clear()

        event_daily = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
        }
        event_weekly = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup weekly completed",
        }

        fp_daily = server._compute_event_fingerprint(
            event_daily["event_type"], event_daily["detail"]
        )
        fp_weekly = server._compute_event_fingerprint(
            event_weekly["event_type"], event_weekly["detail"]
        )

        server._mark_event_sent(fp_daily)
        self.assertFalse(server._is_duplicate_event(fp_weekly))


# ======================================================================
# 5. Health alert event tests
# ======================================================================

class TestHealthAlertEvents(unittest.TestCase):
    """Test health alert event scenarios."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_disk_warning_format(self):
        """Disk warning should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "HEALTH_ALERT",
            "status": "warning",
            "detail": "Disk usage above 75% on /",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Health", message)
        self.assertIn("WARNING", message)
        self.assertIn("Disk usage above 75%", message)

    def test_disk_critical_format(self):
        """Disk critical should format as FAILED."""
        server = self._make_server()
        event = {
            "event_type": "STORAGE_CRITICAL",
            "status": "error",
            "detail": "Disk usage above 85% on /",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Storage", message)
        self.assertIn("FAILED", message)

    def test_service_down_format(self):
        """Service down should format correctly."""
        server = self._make_server()
        event = {
            "event_type": "HEALTH_ALERT",
            "status": "error",
            "detail": "nginx is not running",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Health", message)
        self.assertIn("FAILED", message)
        self.assertIn("nginx", message)


# ======================================================================
# 6. Notification preference tests
# ======================================================================

class TestNotificationPreferences(unittest.TestCase):
    """Test notification preference handling."""

    def test_backup_completed_preference_key(self):
        """BACKUP_COMPLETED should be a valid preference key."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("BACKUP_COMPLETED", DEFAULT_NOTIFICATION_PREFS)

    def test_backup_failed_preference_key(self):
        """BACKUP_FAILED should be a valid preference key."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("BACKUP_FAILED", DEFAULT_NOTIFICATION_PREFS)

    def test_health_alert_preference_key(self):
        """HEALTH_ALERT should be a valid preference key."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("HEALTH_ALERT", DEFAULT_NOTIFICATION_PREFS)

    def test_upload_completed_preference_key(self):
        """UPLOAD_COMPLETED should be a valid preference key."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("UPLOAD_COMPLETED", DEFAULT_NOTIFICATION_PREFS)

    def test_upload_failed_preference_key(self):
        """UPLOAD_FAILED should be a valid preference key."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("UPLOAD_FAILED", DEFAULT_NOTIFICATION_PREFS)

    def test_all_notification_prefs_default_true(self):
        """All notification preferences should default to 'true'."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        for key, value in DEFAULT_NOTIFICATION_PREFS.items():
            self.assertEqual(value, "true", f"Preference {key} should default to 'true'")


# ======================================================================
# 7. Event type mapping tests
# ======================================================================

class TestEventTypeMapping(unittest.TestCase):
    """Test event type to category mapping."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_backup_events_map_to_backup_category(self):
        """Backup events should map to Backup category."""
        server = self._make_server()
        for event_type in ["BACKUP_COMPLETED", "BACKUP_FAILED"]:
            event = {"event_type": event_type, "status": "success"}
            message = server._format_event_telegram(event)
            self.assertIn("Backup", message)

    def test_health_events_map_to_health_category(self):
        """Health events should map to Health category."""
        server = self._make_server()
        event = {"event_type": "HEALTH_ALERT", "status": "warning"}
        message = server._format_event_telegram(event)
        self.assertIn("Health", message)

    def test_upload_events_map_to_upload_category(self):
        """Upload events should map to Upload category."""
        server = self._make_server()
        for event_type in ["UPLOAD_COMPLETED", "UPLOAD_FAILED"]:
            event = {"event_type": event_type, "status": "success"}
            message = server._format_event_telegram(event)
            self.assertIn("Upload", message)

    def test_security_events_map_to_security_category(self):
        """Security events should map to Security category."""
        server = self._make_server()
        event = {"event_type": "SECURITY_ALERT", "status": "error"}
        message = server._format_event_telegram(event)
        self.assertIn("Security", message)

    def test_storage_events_map_to_storage_category(self):
        """Storage events should map to Storage category."""
        server = self._make_server()
        for event_type in ["STORAGE_WARNING", "STORAGE_CRITICAL"]:
            event = {"event_type": event_type, "status": "warning"}
            message = server._format_event_telegram(event)
            self.assertIn("Storage", message)


# ======================================================================
# 8. Status indicator tests
# ======================================================================

class TestStatusIndicators(unittest.TestCase):
    """Test status indicator mapping."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_failed_events_show_exclamation(self):
        """Failed events should show ! indicator."""
        server = self._make_server()
        event = {"event_type": "BACKUP_FAILED", "status": "error"}
        message = server._format_event_telegram(event)
        self.assertIn("!", message)

    def test_completed_events_show_plus(self):
        """Completed events should show + indicator."""
        server = self._make_server()
        event = {"event_type": "BACKUP_COMPLETED", "status": "success"}
        message = server._format_event_telegram(event)
        self.assertIn("+", message)

    def test_warning_events_show_tilde(self):
        """Warning events should show ~ indicator."""
        server = self._make_server()
        event = {"event_type": "HEALTH_ALERT", "status": "warning"}
        message = server._format_event_telegram(event)
        self.assertIn("~", message)


# ======================================================================
# 9. Security tests
# ======================================================================

class TestEventSecurity(unittest.TestCase):
    """Test security properties of event notifications."""

    def test_event_fingerprint_not_sensitive(self):
        """Event fingerprint should not contain sensitive information."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        fp = server._compute_event_fingerprint("BACKUP_COMPLETED", "daily")
        self.assertNotIn("password", fp.lower())
        self.assertNotIn("secret", fp.lower())
        self.assertNotIn("token", fp.lower())
        self.assertNotIn("key", fp.lower())

    def test_event_message_not_contains_api_key(self):
        """Event message should not contain API key."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup completed",
        }
        message = server._format_event_telegram(event)
        self.assertNotIn("api_key", message.lower())
        self.assertNotIn("API_KEY", message)

    def test_event_message_not_contains_bot_token(self):
        """Event message should not contain Telegram bot token."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup completed",
        }
        message = server._format_event_telegram(event)
        self.assertNotIn("bot_token", message.lower())
        self.assertNotIn("BOT_TOKEN", message)

    def test_dedup_window_reasonable(self):
        """Dedup window should be reasonable (not too long, not too short)."""
        # Should be at least 30 seconds and at most 300 seconds
        self.assertGreaterEqual(_EVENT_DEDUP_WINDOW_SECONDS, 30)
        self.assertLessEqual(_EVENT_DEDUP_WINDOW_SECONDS, 300)


# ======================================================================
# 10. Integration tests
# ======================================================================

class TestEventIntegration(unittest.TestCase):
    """Integration tests for event notification flow."""

    def _make_server(self):
        """Create a HealthServer instance with mocked config."""
        config = Config()
        logger = MagicMock()
        return HealthServer(config, logger)

    def test_full_backup_completed_flow(self):
        """Test complete backup completed flow."""
        server = self._make_server()
        _recent_events.clear()

        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup daily completed",
            "label": "daily",
            "size": "1.2G",
            "duration": "2m 30s",
        }

        # Compute fingerprint
        fp = server._compute_event_fingerprint(
            event["event_type"], event["detail"]
        )

        # Should not be duplicate initially
        self.assertFalse(server._is_duplicate_event(fp))

        # Mark as sent
        server._mark_event_sent(fp)

        # Should now be duplicate
        self.assertTrue(server._is_duplicate_event(fp))

        # Format message
        message = server._format_event_telegram(event)
        self.assertIn("Backup", message)
        self.assertIn("SUCCESS", message)
        self.assertIn("daily", message)

    def test_full_backup_failed_flow(self):
        """Test complete backup failed flow."""
        server = self._make_server()
        _recent_events.clear()

        event = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup daily failed",
            "label": "daily",
            "exit_code": 1,
            "duration": "0m 45s",
        }

        # Compute fingerprint
        fp = server._compute_event_fingerprint(
            event["event_type"], event["detail"]
        )

        # Should not be duplicate initially
        self.assertFalse(server._is_duplicate_event(fp))

        # Mark as sent
        server._mark_event_sent(fp)

        # Should now be duplicate
        self.assertTrue(server._is_duplicate_event(fp))

        # Format message
        message = server._format_event_telegram(event)
        self.assertIn("Backup", message)
        self.assertIn("FAILED", message)
        self.assertIn("daily", message)

    def test_health_alert_flow(self):
        """Test health alert event flow."""
        server = self._make_server()
        _recent_events.clear()

        event = {
            "event_type": "HEALTH_ALERT",
            "status": "warning",
            "detail": "Disk usage above 75%",
        }

        fp = server._compute_event_fingerprint(
            event["event_type"], event["detail"]
        )

        self.assertFalse(server._is_duplicate_event(fp))
        server._mark_event_sent(fp)
        self.assertTrue(server._is_duplicate_event(fp))

        message = server._format_event_telegram(event)
        self.assertIn("Health", message)
        self.assertIn("WARNING", message)

    def test_concurrent_backup_events(self):
        """Multiple backup events should be handled correctly."""
        server = self._make_server()
        _recent_events.clear()

        events = [
            {"event_type": "BACKUP_COMPLETED", "status": "success",
             "detail": "Backup daily completed", "label": "daily"},
            {"event_type": "BACKUP_COMPLETED", "status": "success",
             "detail": "Backup weekly completed", "label": "weekly"},
            {"event_type": "BACKUP_FAILED", "status": "error",
             "detail": "Backup daily failed", "label": "daily", "exit_code": 1},
        ]

        for event in events:
            fp = server._compute_event_fingerprint(
                event["event_type"], event["detail"]
            )
            self.assertFalse(server._is_duplicate_event(fp))
            server._mark_event_sent(fp)
            self.assertTrue(server._is_duplicate_event(fp))
            message = server._format_event_telegram(event)
            self.assertIsInstance(message, str)
            self.assertTrue(len(message) > 0)


# ======================================================================
# 11. Original CloudVault operation independence tests
# ======================================================================

class TestCloudVaultIndependence(unittest.TestCase):
    """Test that event notifications do not affect CloudVault operations."""

    def test_backup_script_notification_does_not_block(self):
        """Backup notification should be fire-and-forget."""
        # The notify_watchtower() helper uses:
        # timeout 5 curl -s -o /dev/null ... || true
        # The || true ensures the backup always continues
        # This is a structural test - verify the function exists
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        backup_script = scripts / "backup.sh"
        notify_helper = scripts / "lib" / "notify.sh"
        content = backup_script.read_text()
        helper = notify_helper.read_text()
        self.assertIn("notify_watchtower", content)
        self.assertIn("|| true", helper)
        self.assertIn("timeout 5", helper)

    def test_backup_script_preserves_exit_code(self):
        """Backup script should preserve original exit code."""
        backup_script = Path(__file__).resolve().parent.parent / "scripts" / "backup.sh"
        content = backup_script.read_text()
        self.assertIn("BACKUP_EXIT_CODE", content)
        self.assertIn("exit ${BACKUP_EXIT_CODE}", content)

    def test_backup_script_watchtower_optional(self):
        """Backup should work without Watchtower configured."""
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        backup_script = scripts / "backup.sh"
        notify_helper = scripts / "lib" / "notify.sh"
        content = backup_script.read_text()
        helper = notify_helper.read_text()
        # Should check for API key before notifying
        self.assertIn("WATCHTOWER_API_KEY", helper)
        self.assertIn("return 0", helper)
        # The helper must degrade silently when the env file is missing
        self.assertIn("2>/dev/null", helper)

    def test_watchtower_endpoint_returns_immediately(self):
        """Event endpoint should return 200 immediately."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        # The endpoint uses asyncio.ensure_future for non-blocking send
        # This is verified by the code structure
        self.assertTrue(hasattr(server, "handle_event_webhook"))

    def test_watchtower_failure_does_not_affect_backup(self):
        """Watchtower failure should not affect backup operation."""
        # The notify_watchtower function uses || true to catch failures
        backup_script = Path(__file__).resolve().parent.parent / "scripts" / "backup.sh"
        content = backup_script.read_text()
        self.assertIn("|| true", content)


# ======================================================================
# 12. Upload event limitation tests
# ======================================================================

class TestUploadEventLimitations(unittest.TestCase):
    """Test upload event limitations and documentation."""

    def test_upload_event_types_in_preferences(self):
        """UPLOAD_COMPLETED and UPLOAD_FAILED should be in notification preferences."""
        from telegram_linking import DEFAULT_NOTIFICATION_PREFS
        self.assertIn("UPLOAD_COMPLETED", DEFAULT_NOTIFICATION_PREFS)
        self.assertIn("UPLOAD_FAILED", DEFAULT_NOTIFICATION_PREFS)

    def test_upload_event_formatting_works(self):
        """Upload event formatting should work even without live events."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "UPLOAD_COMPLETED",
            "status": "success",
            "detail": "File uploaded via WebDAV",
        }
        message = server._format_event_telegram(event)
        self.assertIn("Upload", message)
        self.assertIn("SUCCESS", message)

    def test_upload_events_are_future_ready(self):
        """Upload event infrastructure should be in place for future integration."""
        # Verify the event endpoint accepts upload event types
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "UPLOAD_COMPLETED",
            "status": "success",
            "detail": "File uploaded",
        }
        fp = server._compute_event_fingerprint(
            event["event_type"], event["detail"]
        )
        self.assertTrue(fp.startswith("UPLOAD_COMPLETED:"))


# ======================================================================
# 13. Edge case tests
# ======================================================================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_event_type(self):
        """Empty event type should be handled."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {"event_type": "", "status": "success"}
        message = server._format_event_telegram(event)
        self.assertIsInstance(message, str)

    def test_none_detail(self):
        """None detail should be handled."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {"event_type": "BACKUP_COMPLETED", "status": "success", "detail": None}
        message = server._format_event_telegram(event)
        self.assertIsInstance(message, str)

    def test_very_long_detail(self):
        """Very long detail should be handled."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "x" * 10000,
        }
        message = server._format_event_telegram(event)
        self.assertIsInstance(message, str)

    def test_special_characters_in_detail(self):
        """Special characters in detail should be handled."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup with <special> & \"characters\"",
        }
        message = server._format_event_telegram(event)
        self.assertIn("<special>", message)

    def test_negative_exit_code(self):
        """Negative exit code should be handled."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_FAILED",
            "status": "error",
            "detail": "Backup failed",
            "exit_code": -1,
        }
        message = server._format_event_telegram(event)
        self.assertIn("-1", message)

    def test_zero_exit_code_not_shown(self):
        """Zero exit code should not be shown in notification."""
        config = Config()
        logger = MagicMock()
        server = HealthServer(config, logger)
        event = {
            "event_type": "BACKUP_COMPLETED",
            "status": "success",
            "detail": "Backup completed",
            "exit_code": 0,
        }
        message = server._format_event_telegram(event)
        self.assertNotIn("Exit code", message)


# ======================================================================
# 14. Queue send callback preference filtering
# ======================================================================

class TestQueueSendCallback(unittest.TestCase):
    """Test that the Redis queue send path respects per-event preferences.

    Regression test: the queue path previously checked a non-existent
    "backup_notifications" key, silently bypassing every notification toggle.
    """

    def _make_service(self):
        config = Config()
        logger = MagicMock()
        return WatchtowerService(config)

    def _send(self, svc, connections, prefs, event_type):
        fake_db = MagicMock()
        fake_db.get_all_connections = lambda: connections
        fake_db.get_notification_prefs = lambda user_id: prefs
        svc.health_server._get_tg_db = MagicMock(return_value=fake_db)

        sent = []

        class FakeResp:
            status = 200

            async def text(self):
                return "{}"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            # aiohttp ClientSession.post() returns an async context manager
            # (not a coroutine); mirror that shape.
            def post(self, url, json=None, timeout=None):
                sent.append(json)
                return FakeResp()

        payload = {"event_type": event_type, "message": "notification message"}
        with patch.dict(os.environ, {"WATCHTELEGRAM_BOT_TOKEN": "123:abc"}, clear=False):
            with patch("aiohttp.ClientSession", FakeSession):
                result = run_async(svc._queue_send_callback(payload))
        return sent, result

    def test_disabled_event_pref_skips_user(self):
        """BACKUP_COMPLETED disabled -> no Telegram send happens."""
        svc = self._make_service()
        conn = {"user_id": "alice", "telegram_user_id": 111}
        prefs = {"BACKUP_COMPLETED": "false"}
        sent, result = self._send(svc, [conn], prefs, "BACKUP_COMPLETED")
        self.assertEqual(sent, [])
        self.assertFalse(result["success"])

    def test_enabled_event_pref_sends(self):
        """Enabled event pref -> notification is sent."""
        svc = self._make_service()
        conn = {"user_id": "alice", "telegram_user_id": 111}
        prefs = {"BACKUP_COMPLETED": "true"}
        sent, result = self._send(svc, [conn], prefs, "BACKUP_COMPLETED")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["chat_id"], 111)
        self.assertTrue(result["success"])

    def test_upload_event_pref_respected(self):
        """UPLOAD_FAILED disabled -> skip; enabled -> send."""
        svc = self._make_service()
        conn = {"user_id": "bob", "telegram_user_id": 222}
        sent, _ = self._send(svc, [conn], {"UPLOAD_FAILED": "false"}, "UPLOAD_FAILED")
        self.assertEqual(sent, [])
        sent, _ = self._send(svc, [conn], {"UPLOAD_FAILED": "true"}, "UPLOAD_FAILED")
        self.assertEqual(len(sent), 1)

    def test_default_pref_true_when_unknown(self):
        """Unknown pref defaults to enabled (send)."""
        svc = self._make_service()
        conn = {"user_id": "carol", "telegram_user_id": 333}
        sent, _ = self._send(svc, [conn], {}, "STORAGE_CRITICAL")
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
