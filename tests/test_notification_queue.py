#!/usr/bin/env python3
"""
Comprehensive tests for CloudVault Watchtower Phase 8 — Notification Queue.

Tests cover:
  - Queue lifecycle (connect, enqueue, dequeue, process)
  - Status tracking (QUEUED, PROCESSING, SENT, FAILED, RETRYING)
  - Retry logic with exponential backoff
  - Worker loop behavior
  - Graceful degradation when Redis unavailable
  - Queue observability endpoints
  - Integration with Watchtower event system
  - CloudVault independence (failures don't affect core operations)

Run:  python3 tests/test_notification_queue.py
"""

import json
import os
import sys
import time
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "watchtower"))

from notification_queue import (
    NotificationQueue,
    NotificationStatus,
    Notification,
)


# ======================================================================
# Helpers
# ======================================================================

def run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_mock_redis():
    """Create a mock Redis client.

    In redis.asyncio, methods like get/set/lpush/hset are async.
    pipeline() is sync and returns a pipeline object.
    Pipeline command methods (hset, lpush, etc.) are sync (buffer commands).
    Only pipeline.execute() is async.
    """
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.lrange = AsyncMock(return_value=[])
    redis.brpop = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    redis.hgetall = AsyncMock(return_value={})
    redis.hincrby = AsyncMock(return_value=1)
    redis.hincrbyby = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.llen = AsyncMock(return_value=0)
    redis.zcard = AsyncMock(return_value=0)
    redis.zadd = AsyncMock(return_value=1)
    redis.zrem = AsyncMock(return_value=1)
    redis.zrangebyscore = AsyncMock(return_value=[])
    redis.scan_iter = MagicMock(return_value=async_list_iter([]))
    redis.setex = AsyncMock(return_value=True)
    redis.set = AsyncMock(return_value=True)
    redis.pipeline.return_value = make_mock_pipeline()
    return redis


async def async_list_iter(items):
    """Async generator that yields items from a list."""
    for item in items:
        yield item


def make_queue(redis=None):
    """Create a NotificationQueue with optional mock Redis."""
    q = NotificationQueue(
        redis_url="redis://127.0.0.1:6379/1",
        logger=MagicMock(),
        max_retries=3,
        base_delay=0.1,
        max_delay=1.0,
        worker_interval=0.01,
        queue_ttl=3600,
    )
    if redis:
        q._redis = redis
        q._connected = True
    return q


def make_mock_pipeline(results=None):
    """Create a mock pipeline with optional execute results.

    In redis.asyncio, pipeline command methods (hset, lpush, zadd, etc.) are
    sync — they buffer commands. Only execute() is async.
    """
    if results is None:
        results = [1, 1, 1, 1]
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=results)
    return pipe


def make_sample_event():
    """Create a sample event payload."""
    return {
        "event_type": "BACKUP_COMPLETED",
        "status": "success",
        "detail": "Daily backup completed",
        "timestamp": "2026-08-27 03:15:00 UTC",
        "label": "daily",
        "size": "1.2G",
        "duration": "2m 30s",
        "exit_code": 0,
    }


# ======================================================================
# 1. Notification Dataclass Tests
# ======================================================================

class TestNotification(unittest.TestCase):
    """Test the Notification dataclass."""

    def test_notification_creation_defaults(self):
        """Notification can be created with defaults."""
        n = Notification()
        self.assertTrue(n.id)
        self.assertEqual(n.event_type, "UNKNOWN")
        self.assertEqual(n.status, NotificationStatus.QUEUED.value)
        self.assertEqual(n.payload, {})
        self.assertEqual(n.attempts, 0)
        self.assertEqual(n.max_retries, 3)
        self.assertEqual(n.sent_to, [])

    def test_notification_serialization(self):
        """Notification can be serialized to dict."""
        n = Notification(
            event_type="BACKUP_COMPLETED",
            payload={"key": "value"},
        )
        d = n.to_dict()
        self.assertEqual(d["event_type"], "BACKUP_COMPLETED")
        self.assertEqual(d["payload"], json.dumps({"key": "value"}))
        self.assertEqual(d["status"], "QUEUED")
        self.assertIn("id", d)

    def test_notification_deserialization(self):
        """Notification can be deserialized from dict."""
        data = {
            "id": "test-123",
            "event_type": "BACKUP_FAILED",
            "status": "FAILED",
            "payload": '{"error": "timeout"}',
            "created_at": "1234567890.0",
            "updated_at": "1234567891.0",
            "attempts": "3",
            "max_retries": "3",
            "next_retry_at": "1234567892.0",
            "last_error": "timeout",
            "sent_to": '["user1"]',
        }
        n = Notification.from_dict(data)
        self.assertEqual(n.id, "test-123")
        self.assertEqual(n.event_type, "BACKUP_FAILED")
        self.assertEqual(n.status, "FAILED")
        self.assertEqual(n.payload, {"error": "timeout"})
        self.assertEqual(n.attempts, 3)
        self.assertEqual(n.last_error, "timeout")
        self.assertEqual(n.sent_to, ["user1"])

    def test_notification_status_enum(self):
        """NotificationStatus enum has all required states."""
        self.assertEqual(NotificationStatus.QUEUED.value, "QUEUED")
        self.assertEqual(NotificationStatus.PROCESSING.value, "PROCESSING")
        self.assertEqual(NotificationStatus.SENT.value, "SENT")
        self.assertEqual(NotificationStatus.FAILED.value, "FAILED")
        self.assertEqual(NotificationStatus.RETRYING.value, "RETRYING")


# ======================================================================
# 2. Queue Connection Tests
# ======================================================================

class TestQueueConnection(unittest.TestCase):
    """Test queue connection to Redis."""

    def test_connect_success(self):
        """Queue connects to Redis successfully."""
        mock_redis = make_mock_redis()
        q = NotificationQueue(redis_url="redis://127.0.0.1:6379/1")
        q._redis = mock_redis
        q._connected = True
        result = run_async(q.connect())
        # If already connected, connect returns True after ping
        self.assertTrue(q._connected)

    def test_connect_failure(self):
        """Queue handles Redis connection failure gracefully."""
        mock_redis = make_mock_redis()
        mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))
        q = NotificationQueue(redis_url="redis://127.0.0.1:6379/1")
        q._redis = mock_redis
        q._connected = False
        result = run_async(q.connect())
        self.assertFalse(result)
        self.assertFalse(q._connected)

    def test_disconnect(self):
        """Queue disconnects from Redis."""
        mock_redis = make_mock_redis()
        q = make_queue(mock_redis)
        run_async(q.disconnect())
        self.assertFalse(q._connected)
        self.assertIsNone(q._redis)

    def test_connect_without_redis_module(self):
        """Queue handles missing Redis module."""
        with patch('notification_queue.HAS_REDIS', False):
            q = NotificationQueue(redis_url="redis://127.0.0.1:6379/1")
            result = run_async(q.connect())
            self.assertFalse(result)


# ======================================================================
# 3. Enqueue Tests
# ======================================================================

class TestEnqueue(unittest.TestCase):
    """Test enqueue operations."""

    def test_enqueue_success(self):
        """Notification can be enqueued successfully."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline()

        q = make_queue(mock_redis)
        notif_id = run_async(q.enqueue(
            event_type="BACKUP_COMPLETED",
            payload={"key": "value"},
        ))
        self.assertIsNotNone(notif_id)
        self.assertEqual(q._stats["enqueued"], 1)

    def test_enqueue_redis_unavailable(self):
        """Enqueue returns None when Redis is unavailable."""
        q = make_queue()
        q._connected = False

        notif_id = run_async(q.enqueue(
            event_type="BACKUP_COMPLETED",
            payload={"key": "value"},
        ))
        self.assertIsNone(notif_id)
        self.assertEqual(q._stats["redis_errors"], 1)

    def test_enqueue_redis_error(self):
        """Enqueue handles Redis errors gracefully."""
        mock_redis = make_mock_redis()
        pipe = make_mock_pipeline()
        pipe.execute = AsyncMock(side_effect=Exception("Redis error"))
        mock_redis.pipeline.return_value = pipe

        q = make_queue(mock_redis)
        notif_id = run_async(q.enqueue(
            event_type="BACKUP_COMPLETED",
            payload={"key": "value"},
        ))
        self.assertIsNone(notif_id)
        self.assertEqual(q._stats["redis_errors"], 1)

    def test_enqueue_unique_ids(self):
        """Each enqueue produces a unique notification ID."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline()

        q = make_queue(mock_redis)
        id1 = run_async(q.enqueue("BACKUP_COMPLETED", {}))
        id2 = run_async(q.enqueue("BACKUP_FAILED", {}))
        self.assertNotEqual(id1, id2)


# ======================================================================
# 4. Dequeue Tests
# ======================================================================

class TestDequeue(unittest.TestCase):
    """Test dequeue operations."""

    def test_dequeue_empty(self):
        """Dequeue returns None when queue is empty."""
        mock_redis = make_mock_redis()
        mock_redis.brpop.return_value = None
        q = make_queue(mock_redis)

        notification = run_async(q._dequeue())
        self.assertIsNone(notification)

    def test_dequeue_success(self):
        """Dequeue returns a notification from the queue."""
        mock_redis = make_mock_redis()
        notif_id = "test-notif-123"
        mock_redis.brpop.return_value = (NotificationQueue.KEY_PENDING, notif_id)
        mock_redis.hgetall.return_value = {
            "id": notif_id,
            "event_type": "BACKUP_COMPLETED",
            "status": "QUEUED",
            "payload": '{"key": "value"}',
            "created_at": str(time.time()),
            "updated_at": str(time.time()),
            "attempts": "0",
            "max_retries": "3",
            "next_retry_at": "0.0",
            "last_error": "",
            "sent_to": "[]",
        }
        q = make_queue(mock_redis)

        notification = run_async(q._dequeue())
        self.assertIsNotNone(notification)
        self.assertEqual(notification.id, notif_id)
        self.assertEqual(notification.event_type, "BACKUP_COMPLETED")

    def test_dequeue_expired_notification(self):
        """Dequeue handles expired notifications gracefully."""
        mock_redis = make_mock_redis()
        notif_id = "test-notif-expired"
        mock_redis.brpop.return_value = (NotificationQueue.KEY_PENDING, notif_id)
        mock_redis.hgetall.return_value = {}
        q = make_queue(mock_redis)

        notification = run_async(q._dequeue())
        self.assertIsNone(notification)

    def test_dequeue_redis_unavailable(self):
        """Dequeue returns None when Redis is unavailable."""
        q = make_queue()
        q._connected = False

        notification = run_async(q._dequeue())
        self.assertIsNone(notification)


# ======================================================================
# 5. Notification Processing Tests
# ======================================================================

class TestProcessing(unittest.TestCase):
    """Test notification processing."""

    def test_process_notification_success(self):
        """Notification is processed successfully."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline()

        q = make_queue(mock_redis)
        mock_callback = AsyncMock(return_value={"success": True, "sent_to": ["user1"], "errors": []})
        q.set_send_callback(mock_callback)

        notification = Notification(
            id="test-123",
            event_type="BACKUP_COMPLETED",
            payload={"key": "value"},
        )
        result = run_async(q._process_notification(notification))

        self.assertTrue(result)
        self.assertEqual(notification.status, NotificationStatus.SENT.value)
        self.assertEqual(notification.attempts, 1)
        self.assertEqual(q._stats["sent"], 1)

    def test_process_notification_send_failure_triggers_retry(self):
        """Notification send failure triggers retry."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        mock_callback = AsyncMock(return_value={"success": False, "error": "telegram_error"})
        q.set_send_callback(mock_callback)

        notification = Notification(
            id="test-123",
            event_type="BACKUP_FAILED",
            payload={"error": "timeout"},
            max_retries=3,
        )
        result = run_async(q._process_notification(notification))

        self.assertFalse(result)
        self.assertEqual(notification.attempts, 1)
        self.assertEqual(notification.status, NotificationStatus.RETRYING.value)
        self.assertEqual(notification.last_error, "telegram_error")

    def test_process_notification_permanent_failure(self):
        """Notification fails permanently after max retries."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        mock_callback = AsyncMock(return_value={"success": False, "error": "permanent_error"})
        q.set_send_callback(mock_callback)

        notification = Notification(
            id="test-123",
            event_type="BACKUP_FAILED",
            payload={"error": "timeout"},
            max_retries=3,
            attempts=3,
        )
        result = run_async(q._process_notification(notification))

        self.assertFalse(result)
        self.assertEqual(notification.status, NotificationStatus.FAILED.value)
        self.assertEqual(q._stats["failed"], 1)

    def test_process_notification_no_callback(self):
        """Notification processing fails without callback."""
        q = make_queue(make_mock_redis())
        notification = Notification(
            id="test-123",
            event_type="BACKUP_COMPLETED",
            payload={},
        )
        result = run_async(q._process_notification(notification))
        self.assertFalse(result)

    def test_process_notification_callback_exception(self):
        """Notification processing handles callback exceptions."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        mock_callback = AsyncMock(side_effect=Exception("callback error"))
        q.set_send_callback(mock_callback)

        notification = Notification(
            id="test-123",
            event_type="BACKUP_COMPLETED",
            payload={},
            max_retries=3,
        )
        result = run_async(q._process_notification(notification))

        self.assertFalse(result)
        self.assertEqual(notification.last_error, "callback error")


# ======================================================================
# 6. Retry Logic Tests
# ======================================================================

class TestRetryLogic(unittest.TestCase):
    """Test retry logic and exponential backoff."""

    def test_calculate_retry_delay_exponential(self):
        """Retry delay follows exponential backoff."""
        q = make_queue()
        delay_0 = q._calculate_retry_delay(0)
        delay_1 = q._calculate_retry_delay(1)
        delay_2 = q._calculate_retry_delay(2)

        # Base delay is 0.1, so delays should be roughly 0.1, 0.2, 0.4
        self.assertGreaterEqual(delay_0, 0.1)
        self.assertGreaterEqual(delay_1, 0.2)
        self.assertGreaterEqual(delay_2, 0.4)

    def test_calculate_retry_delay_max(self):
        """Retry delay respects max delay."""
        q = make_queue()
        delay = q._calculate_retry_delay(100)
        # Max delay is 1.0, plus up to 25% jitter
        self.assertLessEqual(delay, 1.0 + 1.0 * 0.25)

    def test_handle_send_failure_retry(self):
        """Send failure schedules retry when under max attempts."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        notification = Notification(
            id="test-123",
            event_type="BACKUP_FAILED",
            payload={},
            max_retries=3,
            attempts=0,
        )
        result = run_async(q._handle_send_failure(notification, "timeout"))

        self.assertFalse(result)
        self.assertEqual(notification.status, NotificationStatus.RETRYING.value)
        self.assertGreater(notification.next_retry_at, time.time())
        self.assertEqual(q._stats["retried"], 1)

    def test_handle_send_failure_permanent(self):
        """Send failure marks as permanently failed after max attempts."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        notification = Notification(
            id="test-123",
            event_type="BACKUP_FAILED",
            payload={},
            max_retries=3,
            attempts=3,
        )
        result = run_async(q._handle_send_failure(notification, "timeout"))

        self.assertFalse(result)
        self.assertEqual(notification.status, NotificationStatus.FAILED.value)
        self.assertEqual(q._stats["failed"], 1)

    def test_process_retries_moves_to_pending(self):
        """Notifications are moved from retry set to pending when due."""
        mock_redis = make_mock_redis()
        mock_redis.zrangebyscore.return_value = [("notif-1", 1234567890.0)]
        pipe = make_mock_pipeline([1, 1])
        mock_redis.pipeline.return_value = pipe

        q = make_queue(mock_redis)
        run_async(q._process_retries())
        # zrem and lpush are called on the pipeline (sync buffer commands)
        pipe.zrem.assert_called_once()
        pipe.lpush.assert_called_once()


# ======================================================================
# 7. Queue Statistics Tests
# ======================================================================

class TestQueueStats(unittest.TestCase):
    """Test queue statistics and observability."""

    def test_get_stats(self):
        """Queue returns statistics."""
        mock_redis = make_mock_redis()
        pipe = make_mock_pipeline([5, 2, {"enqueued": "10", "sent": "8", "failed": "1", "depth": "3"}])
        mock_redis.pipeline.return_value = pipe
        q = make_queue(mock_redis)

        stats = run_async(q.get_stats())
        self.assertTrue(stats["connected"])
        self.assertEqual(stats["pending_count"], 5)
        self.assertEqual(stats["retry_count"], 2)
        self.assertEqual(stats["persistent_stats"]["enqueued"], "10")

    def test_get_pending_notifications(self):
        """Queue returns pending notifications."""
        mock_redis = make_mock_redis()
        mock_redis.lrange.return_value = ["notif-1", "notif-2"]
        mock_redis.hgetall.return_value = {
            "id": "notif-1",
            "event_type": "BACKUP_COMPLETED",
            "status": "QUEUED",
            "payload": "{}",
            "created_at": str(time.time()),
            "updated_at": str(time.time()),
            "attempts": "0",
            "max_retries": "3",
            "next_retry_at": "0.0",
            "last_error": "",
            "sent_to": "[]",
        }
        q = make_queue(mock_redis)

        pending = run_async(q.get_pending_notifications())
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["id"], "notif-1")

    def test_get_retry_notifications(self):
        """Queue returns retry notifications."""
        mock_redis = make_mock_redis()
        mock_redis.zrangebyscore.return_value = [("notif-1", time.time() + 60)]
        mock_redis.hgetall.return_value = {
            "id": "notif-1",
            "event_type": "BACKUP_FAILED",
            "status": "RETRYING",
            "payload": "{}",
            "created_at": str(time.time()),
            "updated_at": str(time.time()),
            "attempts": "1",
            "max_retries": "3",
            "next_retry_at": str(time.time() + 60),
            "last_error": "timeout",
            "sent_to": "[]",
        }
        q = make_queue(mock_redis)

        retry = run_async(q.get_retry_notifications())
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0]["status"], "RETRYING")

    def test_get_failed_notifications(self):
        """Queue returns failed notifications."""
        mock_redis = make_mock_redis()
        mock_redis.scan_iter = MagicMock(return_value=async_list_iter(["watchtower:notif:notif-1"]))
        mock_redis.hgetall.return_value = {
            "id": "notif-1",
            "event_type": "BACKUP_FAILED",
            "status": "FAILED",
            "payload": "{}",
            "created_at": str(time.time()),
            "updated_at": str(time.time()),
            "attempts": "3",
            "max_retries": "3",
            "next_retry_at": "0.0",
            "last_error": "permanent_error",
            "sent_to": "[]",
        }
        q = make_queue(mock_redis)

        failed = run_async(q.get_failed_notifications())
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["status"], "FAILED")

    def test_health_check_healthy(self):
        """Queue returns healthy status when connected."""
        mock_redis = make_mock_redis()
        q = make_queue(mock_redis)

        health = run_async(q.health_check())
        self.assertEqual(health["status"], "healthy")

    def test_health_check_disconnected(self):
        """Queue returns unavailable status when disconnected."""
        q = make_queue()
        q._connected = False

        health = run_async(q.health_check())
        self.assertEqual(health["status"], "unavailable")

    def test_health_check_redis_error(self):
        """Queue returns degraded status when Redis ping fails."""
        mock_redis = make_mock_redis()
        mock_redis.ping = AsyncMock(side_effect=Exception("Connection lost"))
        q = make_queue(mock_redis)

        health = run_async(q.health_check())
        self.assertEqual(health["status"], "degraded")


# ======================================================================
# 8. Graceful Degradation Tests
# ======================================================================

class TestGracefulDegradation(unittest.TestCase):
    """Test queue behavior when Redis is unavailable."""

    def test_enqueue_redis_unavailable(self):
        """Enqueue gracefully handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        result = run_async(q.enqueue("BACKUP_COMPLETED", {"key": "value"}))
        self.assertIsNone(result)
        self.assertEqual(q._stats["redis_errors"], 1)

    def test_dequeue_redis_unavailable(self):
        """Dequeue gracefully handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        result = run_async(q._dequeue())
        self.assertIsNone(result)

    def test_get_stats_redis_unavailable(self):
        """Get stats gracefully handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        stats = run_async(q.get_stats())
        self.assertFalse(stats["connected"])
        self.assertNotIn("pending_count", stats)

    def test_get_pending_notifications_redis_unavailable(self):
        """Get pending notifications handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        pending = run_async(q.get_pending_notifications())
        self.assertEqual(pending, [])

    def test_get_retry_notifications_redis_unavailable(self):
        """Get retry notifications handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        retry = run_async(q.get_retry_notifications())
        self.assertEqual(retry, [])

    def test_get_failed_notifications_redis_unavailable(self):
        """Get failed notifications handles Redis unavailability."""
        q = make_queue()
        q._connected = False

        failed = run_async(q.get_failed_notifications())
        self.assertEqual(failed, [])


# ======================================================================
# 9. CloudVault Independence Tests
# ======================================================================

class TestCloudVaultIndependence(unittest.TestCase):
    """Test that queue failures don't affect CloudVault operations."""

    def test_redis_failure_no_impact(self):
        """Redis failure doesn't block the caller."""
        q = make_queue()
        q._connected = False

        # Enqueue should return None but not raise
        result = run_async(q.enqueue("BACKUP_COMPLETED", {}))
        self.assertIsNone(result)

    def test_send_failure_no_impact(self):
        """Send failure doesn't affect queue operation."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline([1, 1, 1])

        q = make_queue(mock_redis)
        mock_callback = AsyncMock(return_value={"success": False, "error": "telegram_error"})
        q.set_send_callback(mock_callback)

        notification = Notification(
            id="test-123",
            event_type="BACKUP_FAILED",
            payload={},
            max_retries=3,
        )

        # Process should fail but not raise
        result = run_async(q._process_notification(notification))
        self.assertFalse(result)

    def test_queue_independent_of_nextcloud(self):
        """Queue operates independently of Nextcloud."""
        mock_redis = make_mock_redis()
        mock_redis.pipeline.return_value = make_mock_pipeline()
        q = make_queue(mock_redis)

        # Queue should work without Nextcloud being available
        mock_callback = AsyncMock(return_value={"success": True})
        q.set_send_callback(mock_callback)

        notif_id = run_async(q.enqueue("BACKUP_COMPLETED", {}))
        self.assertIsNotNone(notif_id)


# ======================================================================
# 10. URL Redaction Tests
# ======================================================================

class TestURLRedaction(unittest.TestCase):
    """Test URL redaction for logging."""

    def test_redact_url_with_password(self):
        """URL with password is redacted."""
        url = "redis://:secret123@127.0.0.1:6379/1"
        redacted = NotificationQueue._redact_url(url)
        self.assertNotIn("secret123", redacted)
        self.assertIn("127.0.0.1:6379/1", redacted)

    def test_redact_url_without_password(self):
        """URL without password is unchanged."""
        url = "redis://127.0.0.1:6379/1"
        redacted = NotificationQueue._redact_url(url)
        self.assertEqual(redacted, url)


# ======================================================================
# 11. Watchtower Config Integration Tests
# ======================================================================

class TestConfigIntegration(unittest.TestCase):
    """Test Config class queue settings."""

    def test_config_queue_defaults(self):
        """Config has correct queue defaults."""
        from watchtower import Config
        config = Config()
        self.assertTrue(config.queue_enabled)
        self.assertEqual(config.queue_max_retries, 3)
        self.assertEqual(config.queue_base_delay, 1.0)
        self.assertEqual(config.queue_max_delay, 60.0)
        self.assertEqual(config.queue_worker_interval, 1.0)
        self.assertEqual(config.queue_ttl, 86400)

    def test_config_queue_from_env(self):
        """Config reads queue settings from environment."""
        from watchtower import Config
        with patch.dict(os.environ, {
            "WATCHTOWER_QUEUE_ENABLED": "false",
            "WATCHTOWER_QUEUE_MAX_RETRIES": "5",
            "WATCHTOWER_QUEUE_BASE_DELAY": "2.0",
            "WATCHTOWER_QUEUE_MAX_DELAY": "120.0",
            "WATCHTOWER_QUEUE_WORKER_INTERVAL": "0.5",
            "WATCHTOWER_QUEUE_TTL": "43200",
        }):
            config = Config.from_env()
            self.assertFalse(config.queue_enabled)
            self.assertEqual(config.queue_max_retries, 5)
            self.assertEqual(config.queue_base_delay, 2.0)
            self.assertEqual(config.queue_max_delay, 120.0)
            self.assertEqual(config.queue_worker_interval, 0.5)
            self.assertEqual(config.queue_ttl, 43200)


if __name__ == "__main__":
    unittest.main()
