#!/usr/bin/env python3
"""
CloudVault Watchtower - Phase 8: Redis-backed Notification Queue

Asynchronous notification processing with:
  - Redis-backed persistent queue
  - Status tracking: QUEUED, PROCESSING, SENT, FAILED, RETRYING
  - Exponential backoff with jitter for retries
  - Maximum retry count with failure tracking
  - Non-blocking enqueue operations
  - Background worker for processing
  - Queue depth observability
  - Graceful degradation when Redis unavailable

Queue Architecture:
  CloudVault Event
        |
        v
  Notification Queue (Redis)
        |
        v
  Watchtower Worker
        |
        v
  Telegram API

Redis Key Structure:
  watchtower:notif:pending     - List of pending notification IDs (LPUSH/BRPOP)
  watchtower:notif:{id}        - Hash with notification data and metadata
  watchtower:notif:retry       - Sorted set for retry scheduling (score = next_retry_time)
  watchtower:notif:stats       - Hash with queue statistics (depth, sent, failed)

Design Principles:
  - Notifications must never block CloudVault operations
  - Redis unavailability degrades gracefully (log warning, continue)
  - Failed notifications are observable, not silently lost
  - Exponential backoff prevents Telegram API overload
  - Maximum retries prevent infinite retry loops
"""

import json
import time
import uuid
import random
import logging
import asyncio
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field, asdict

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    try:
        import aioredis
        HAS_REDIS = True
    except ImportError:
        HAS_REDIS = False

# Phase 9: Metrics import (soft dependency)
try:
    from watchtower_metrics import metrics as wt_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False


class NotificationStatus(str, Enum):
    """Notification lifecycle states."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


@dataclass
class Notification:
    """A single notification in the queue."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "UNKNOWN"
    status: str = NotificationStatus.QUEUED.value
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0
    max_retries: int = 3
    next_retry_at: float = 0.0
    last_error: str = ""
    sent_to: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for Redis storage."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "status": self.status,
            "payload": json.dumps(self.payload),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "attempts": str(self.attempts),
            "max_retries": str(self.max_retries),
            "next_retry_at": str(self.next_retry_at),
            "last_error": self.last_error,
            "sent_to": json.dumps(self.sent_to),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Notification":
        """Deserialize from Redis hash."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            event_type=data.get("event_type", "UNKNOWN"),
            status=data.get("status", NotificationStatus.QUEUED.value),
            payload=json.loads(data.get("payload", "{}")),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            attempts=int(data.get("attempts", 0)),
            max_retries=int(data.get("max_retries", 3)),
            next_retry_at=float(data.get("next_retry_at", 0.0)),
            last_error=data.get("last_error", ""),
            sent_to=json.loads(data.get("sent_to", "[]")),
        )


class NotificationQueue:
    """Redis-backed notification queue for Watchtower.

    Provides non-blocking enqueue with persistent retry tracking.
    Gracefully degrades when Redis is unavailable.
    """

    # Redis key prefixes
    KEY_PENDING = "watchtower:notif:pending"
    KEY_RETRY = "watchtower:notif:retry"
    KEY_STATS = "watchtower:notif:stats"
    KEY_NOTIF_PREFIX = "watchtower:notif:"
    KEY_SENT_PREFIX = "watchtower:notif:sent:"

    # Default configuration
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BASE_DELAY = 1.0  # seconds
    DEFAULT_MAX_DELAY = 60.0  # seconds
    DEFAULT_WORKER_INTERVAL = 1.0  # seconds
    DEFAULT_QUEUE_TTL = 86400  # 24 hours

    def __init__(
        self,
        redis_url: str = "redis://127.0.0.1:6379/1",
        logger: Optional[logging.Logger] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        worker_interval: float = DEFAULT_WORKER_INTERVAL,
        queue_ttl: int = DEFAULT_QUEUE_TTL,
    ):
        self.redis_url = redis_url
        self.logger = logger or logging.getLogger("watchtower")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.worker_interval = worker_interval
        self.queue_ttl = queue_ttl
        self._redis: Optional[Any] = None
        self._connected = False
        self._worker_task: Optional[asyncio.Task] = None
        self._send_callback: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None
        self._stats = {
            "enqueued": 0,
            "sent": 0,
            "failed": 0,
            "retried": 0,
            "redis_errors": 0,
        }

    async def connect(self) -> bool:
        """Connect to Redis. Returns True if successful."""
        if not HAS_REDIS:
            self.logger.warning(
                "Redis client not available, queue disabled",
                extra={"event": "queue_redis_unavailable"},
            )
            return False

        try:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            await self._redis.ping()
            self._connected = True
            self.logger.info(
                "Notification queue connected to Redis",
                extra={"event": "queue_connected", "redis_url": self._redact_url(self.redis_url)},
            )
            return True
        except Exception as e:
            self._connected = False
            self.logger.warning(
                "Failed to connect to Redis, queue degraded",
                extra={"event": "queue_connect_failed", "error": str(e)},
            )
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
        self._connected = False

    def set_send_callback(
        self, callback: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ) -> None:
        """Set the callback function to send notifications to Telegram.

        The callback receives the notification payload and should return:
        {"success": True/False, "error": "..."}
        """
        self._send_callback = callback

    async def enqueue(
        self,
        event_type: str,
        payload: Dict[str, Any],
        max_retries: Optional[int] = None,
    ) -> Optional[str]:
        """Enqueue a notification for async processing.

        This is non-blocking - returns immediately after Redis write.
        Returns notification ID or None if Redis unavailable.
        """
        if not self._connected or not self._redis:
            self._stats["redis_errors"] += 1
            self.logger.warning(
                "Cannot enqueue notification, Redis unavailable",
                extra={"event": "queue_enqueue_failed", "event_type": event_type},
            )
            return None

        notification = Notification(
            event_type=event_type,
            payload=payload,
            max_retries=max_retries if max_retries is not None else self.max_retries,
        )

        try:
            pipe = self._redis.pipeline()

            # Store notification data
            notif_key = f"{self.KEY_NOTIF_PREFIX}{notification.id}"
            pipe.hset(notif_key, mapping=notification.to_dict())
            pipe.expire(notif_key, self.queue_ttl)

            # Add to pending queue
            pipe.lpush(self.KEY_PENDING, notification.id)

            # Update stats
            pipe.hincrby(self.KEY_STATS, "enqueued", 1)
            pipe.hincrby(self.KEY_STATS, "depth", 1)

            await pipe.execute()
            self._stats["enqueued"] += 1

            self.logger.debug(
                "Notification enqueued",
                extra={
                    "event": "queue_enqueued",
                    "notification_id": notification.id,
                    "event_type": event_type,
                },
            )
            return notification.id

        except Exception as e:
            self._stats["redis_errors"] += 1
            self.logger.error(
                "Failed to enqueue notification",
                extra={
                    "event": "queue_enqueue_error",
                    "event_type": event_type,
                    "error": str(e),
                },
            )
            return None

    async def _dequeue(self) -> Optional[Notification]:
        """Dequeue the next notification from Redis.

        Uses BRPOP with timeout for efficient waiting.
        """
        if not self._connected or not self._redis:
            return None

        try:
            # BRPOP with 1-second timeout
            result = await self._redis.brpop(self.KEY_PENDING, timeout=1)
            if result is None:
                return None

            _, notif_id = result

            # Get notification data
            notif_key = f"{self.KEY_NOTIF_PREFIX}{notif_id}"
            data = await self._redis.hgetall(notif_key)

            if not data:
                # Notification expired or was deleted
                return None

            notification = Notification.from_dict(data)
            return notification

        except Exception as e:
            self._stats["redis_errors"] += 1
            self.logger.error(
                "Failed to dequeue notification",
                extra={"event": "queue_dequeue_error", "error": str(e)},
            )
            return None

    async def _process_notification(self, notification: Notification) -> bool:
        """Process a single notification.

        Returns True if successfully sent, False otherwise.
        """
        if not self._send_callback:
            self.logger.error(
                "No send callback configured",
                extra={"event": "queue_no_callback"},
            )
            return False

        notification.status = NotificationStatus.PROCESSING.value
        notification.attempts += 1
        notification.updated_at = time.time()

        # Phase 9: Track processing time
        _start_time = time.time()

        try:
            # Update status in Redis
            if self._connected and self._redis:
                notif_key = f"{self.KEY_NOTIF_PREFIX}{notification.id}"
                await self._redis.hset(notif_key, mapping={
                    "status": notification.status,
                    "attempts": str(notification.attempts),
                    "updated_at": str(notification.updated_at),
                })

            # Execute send callback
            result = await self._send_callback(notification.payload)

            if result.get("success"):
                notification.status = NotificationStatus.SENT.value
                notification.updated_at = time.time()

                # Record sent status
                if self._connected and self._redis:
                    notif_key = f"{self.KEY_NOTIF_PREFIX}{notification.id}"
                    sent_key = f"{self.KEY_SENT_PREFIX}{notification.id}"
                    pipe = self._redis.pipeline()
                    pipe.hset(notif_key, mapping={
                        "status": notification.status,
                        "updated_at": str(notification.updated_at),
                    })
                    pipe.setex(sent_key, self.queue_ttl, "1")
                    pipe.hincrby(self.KEY_STATS, "sent", 1)
                    pipe.hincrbyby(self.KEY_STATS, "depth", -1)
                    await pipe.execute()

                self._stats["sent"] += 1
                # Phase 9: Track successful notification
                if HAS_METRICS:
                    _elapsed = time.time() - _start_time
                    wt_metrics.notifications_total.inc(labels={"status": "sent"})
                    wt_metrics.notification_processing_seconds.observe(_elapsed)
                return True
            else:
                error = result.get("error", "unknown_error")
                return await self._handle_send_failure(notification, error, _start_time)

        except Exception as e:
            return await self._handle_send_failure(notification, str(e), _start_time)

    async def _handle_send_failure(
        self, notification: Notification, error: str, start_time: float = 0.0
    ) -> bool:
        """Handle a failed send attempt.

        Schedules retry if under max attempts, otherwise marks as FAILED.
        """
        notification.last_error = error
        notification.updated_at = time.time()

        if notification.attempts >= notification.max_retries:
            # Permanent failure
            notification.status = NotificationStatus.FAILED.value

            if self._connected and self._redis:
                notif_key = f"{self.KEY_NOTIF_PREFIX}{notification.id}"
                pipe = self._redis.pipeline()
                pipe.hset(notif_key, mapping={
                    "status": notification.status,
                    "last_error": notification.last_error,
                    "updated_at": str(notification.updated_at),
                })
                pipe.hincrby(self.KEY_STATS, "failed", 1)
                pipe.hincrbyby(self.KEY_STATS, "depth", -1)
                await pipe.execute()

            self._stats["failed"] += 1
            # Phase 9: Track permanent failure
            if HAS_METRICS:
                _elapsed = time.time() - start_time if start_time else 0.0
                wt_metrics.notifications_total.inc(labels={"status": "failed"})
                wt_metrics.notification_failures_total.inc(labels={"event_type": notification.event_type})
                wt_metrics.notification_processing_seconds.observe(_elapsed)
            self.logger.warning(
                "Notification permanently failed",
                extra={
                    "event": "queue_notification_failed",
                    "notification_id": notification.id,
                    "event_type": notification.event_type,
                    "attempts": notification.attempts,
                    "error": error,
                },
            )
            return False

        # Schedule retry with exponential backoff + jitter
        delay = self._calculate_retry_delay(notification.attempts)
        notification.next_retry_at = time.time() + delay
        notification.status = NotificationStatus.RETRYING.value

        if self._connected and self._redis:
            notif_key = f"{self.KEY_NOTIF_PREFIX}{notification.id}"
            pipe = self._redis.pipeline()
            pipe.hset(notif_key, mapping={
                "status": notification.status,
                "last_error": notification.last_error,
                "next_retry_at": str(notification.next_retry_at),
                "updated_at": str(notification.updated_at),
            })
            # Add to retry sorted set with score = next_retry_time
            pipe.zadd(self.KEY_RETRY, {notification.id: notification.next_retry_at})
            pipe.hincrby(self.KEY_STATS, "retried", 1)
            await pipe.execute()

        self._stats["retried"] += 1
        # Phase 9: Track retry
        if HAS_METRICS:
            wt_metrics.notifications_total.inc(labels={"status": "retried"})
        self.logger.info(
            "Notification scheduled for retry",
            extra={
                "event": "queue_notification_retry",
                "notification_id": notification.id,
                "event_type": notification.event_type,
                "attempt": notification.attempts,
                "delay_seconds": delay,
                "next_retry_at": notification.next_retry_at,
            },
        )
        return False

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        delay = min(base_delay * 2^attempt, max_delay) + jitter
        """
        delay = min(
            self.base_delay * (2 ** attempt),
            self.max_delay,
        )
        # Add jitter (0-25% of delay)
        jitter = delay * random.uniform(0, 0.25)
        return delay + jitter

    async def _process_retries(self) -> None:
        """Move notifications from retry set back to pending queue when due."""
        if not self._connected or not self._redis:
            return

        try:
            now = time.time()
            # Get notifications ready for retry (score <= now)
            ready = await self._redis.zrangebyscore(
                self.KEY_RETRY, "-inf", now, withscores=True
            )

            if not ready:
                return

            pipe = self._redis.pipeline()
            count = 0
            for notif_id, score in ready:
                # Remove from retry set
                pipe.zrem(self.KEY_RETRY, notif_id)
                # Add back to pending queue
                pipe.lpush(self.KEY_PENDING, notif_id)
                count += 1

            await pipe.execute()

            if count > 0:
                self.logger.debug(
                    "Notifications moved from retry to pending",
                    extra={"event": "queue_retry_move", "count": count},
                )

        except Exception as e:
            self._stats["redis_errors"] += 1
            self.logger.error(
                "Failed to process retries",
                extra={"event": "queue_retry_error", "error": str(e)},
            )

    async def worker_loop(self) -> None:
        """Main worker loop - processes notifications from queue."""
        self.logger.info(
            "Notification worker started",
            extra={"event": "queue_worker_start"},
        )

        while True:
            try:
                # Process pending retries first
                await self._process_retries()

                # Dequeue next notification
                notification = await self._dequeue()

                if notification is None:
                    # No notifications ready, wait briefly
                    await asyncio.sleep(self.worker_interval)
                    continue

                # Process the notification
                await self._process_notification(notification)

                # Brief pause between notifications to avoid rate limiting
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                self.logger.info(
                    "Notification worker shutting down",
                    extra={"event": "queue_worker_stop"},
                )
                break
            except Exception as e:
                self.logger.error(
                    "Notification worker error",
                    extra={"event": "queue_worker_error", "error": str(e)},
                )
                await asyncio.sleep(self.worker_interval)

    async def start_worker(self) -> None:
        """Start the background worker task."""
        if self._worker_task is not None:
            return

        self._worker_task = asyncio.create_task(self.worker_loop())
        self.logger.info(
            "Queue worker task created",
            extra={"event": "queue_worker_task_created"},
        )

    async def stop_worker(self) -> None:
        """Stop the background worker task."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics for observability."""
        stats = {
            "connected": self._connected,
            "worker_running": self._worker_task is not None and not self._worker_task.done(),
            "stats": dict(self._stats),
        }

        if self._connected and self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.llen(self.KEY_PENDING)
                pipe.zcard(self.KEY_RETRY)
                pipe.hgetall(self.KEY_STATS)
                results = await pipe.execute()

                stats["pending_count"] = results[0] if results[0] else 0
                stats["retry_count"] = results[1] if results[1] else 0
                stats["persistent_stats"] = results[2] if results[2] else {}
            except Exception as e:
                stats["error"] = str(e)

        return stats

    async def get_pending_notifications(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending notifications for observability."""
        if not self._connected or not self._redis:
            return []

        try:
            # Get IDs from pending queue
            notif_ids = await self._redis.lrange(self.KEY_PENDING, 0, limit - 1)

            notifications = []
            for notif_id in notif_ids:
                notif_key = f"{self.KEY_NOTIF_PREFIX}{notif_id}"
                data = await self._redis.hgetall(notif_key)
                if data:
                    notification = Notification.from_dict(data)
                    notifications.append({
                        "id": notification.id,
                        "event_type": notification.event_type,
                        "status": notification.status,
                        "created_at": notification.created_at,
                        "attempts": notification.attempts,
                    })

            return notifications

        except Exception as e:
            self.logger.error(
                "Failed to get pending notifications",
                extra={"event": "queue_get_pending_error", "error": str(e)},
            )
            return []

    async def get_retry_notifications(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get notifications in retry state for observability."""
        if not self._connected or not self._redis:
            return []

        try:
            # Get IDs from retry sorted set (upcoming retries)
            now = time.time()
            result = await self._redis.zrangebyscore(
                self.KEY_RETRY, now, "+inf", withscores=True, limit=(0, limit)
            )

            notifications = []
            for notif_id, score in result:
                notif_key = f"{self.KEY_NOTIF_PREFIX}{notif_id}"
                data = await self._redis.hgetall(notif_key)
                if data:
                    notification = Notification.from_dict(data)
                    notifications.append({
                        "id": notification.id,
                        "event_type": notification.event_type,
                        "status": notification.status,
                        "attempts": notification.attempts,
                        "next_retry_at": notification.next_retry_at,
                        "last_error": notification.last_error,
                    })

            return notifications

        except Exception as e:
            self.logger.error(
                "Failed to get retry notifications",
                extra={"event": "queue_get_retry_error", "error": str(e)},
            )
            return []

    async def get_failed_notifications(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get permanently failed notifications for observability."""
        if not self._connected or not self._redis:
            return []

        try:
            # Scan for failed notifications (check recent ones)
            pattern = f"{self.KEY_NOTIF_PREFIX}*"
            notifications = []
            count = 0

            async for key in self._redis.scan_iter(match=pattern, count=100):
                if count >= limit:
                    break

                data = await self._redis.hgetall(key)
                if data and data.get("status") == NotificationStatus.FAILED.value:
                    notification = Notification.from_dict(data)
                    notifications.append({
                        "id": notification.id,
                        "event_type": notification.event_type,
                        "status": notification.status,
                        "attempts": notification.attempts,
                        "last_error": notification.last_error,
                        "created_at": notification.created_at,
                        "updated_at": notification.updated_at,
                    })
                    count += 1

            return notifications

        except Exception as e:
            self.logger.error(
                "Failed to get failed notifications",
                extra={"event": "queue_get_failed_error", "error": str(e)},
            )
            return []

    async def health_check(self) -> Dict[str, Any]:
        """Check queue health for service health endpoint."""
        if not self._connected or not self._redis:
            return {
                "status": "unavailable",
                "detail": "Redis not connected",
            }

        try:
            await self._redis.ping()
            stats = await self.get_stats()
            return {
                "status": "healthy",
                "detail": "Connected to Redis",
                "pending": stats.get("pending_count", 0),
                "retry": stats.get("retry_count", 0),
                "worker_running": stats.get("worker_running", False),
            }
        except Exception as e:
            return {
                "status": "degraded",
                "detail": f"Redis check failed: {str(e)}",
            }

    @staticmethod
    def _redact_url(url: str) -> str:
        """Redact sensitive parts of Redis URL for logging."""
        if "@" in url:
            # redact password
            parts = url.split("@", 1)
            return f"***@{parts[1]}"
        return url
