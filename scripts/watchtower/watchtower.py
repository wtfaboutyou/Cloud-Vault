#!/usr/bin/env python3
"""
CloudVault Watchtower - Foundation Service + Telegram Linking API (Phase 4)
+ Event Notifications (Phase 7)

Minimal systemd-integrated service with:
  - Health / status / metrics / storage endpoints (Phases 1-2)
  - Telegram account linking API (Phase 4)
  - Static settings page serving
  - Periodic token cleanup
  - Event notification endpoint (Phase 7)
  - Backup completion/failure routing to Telegram (Phase 7)
"""

import os
import sys
import json
import signal
import asyncio
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

try:
    from aiohttp import web
except ImportError:
    print("ERROR: aiohttp not installed. Run: pip3 install aiohttp", file=sys.stderr)
    sys.exit(1)

try:
    import systemd.daemon
    HAS_SYSTEMD = True
except ImportError:
    HAS_SYSTEMD = False

# Telegram linking (Phase 4) — soft import so core still works without psycopg2
try:
    from telegram_linking import Database as TelegramDatabase, CLEANUP_INTERVAL_SECONDS
    HAS_LINKING = True
except ImportError:
    HAS_LINKING = False

# Notification queue (Phase 8) — soft import so core still works without redis
try:
    from notification_queue import NotificationQueue, NotificationStatus
    HAS_QUEUE = True
except ImportError:
    HAS_QUEUE = False

# Watchtower metrics (Phase 9) — soft import for observability
try:
    from watchtower_metrics import metrics as wt_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False

PROMETHEUS_URL = "http://127.0.0.1:9090"
ALERTMANAGER_URL = "http://127.0.0.1:9093"

# Alert deduplication: track recent alerts to prevent storms
_ALERT_DEDUP_WINDOW_SECONDS = 300  # 5 minutes
_recent_alerts: Dict[str, float] = {}  # fingerprint -> last_sent_timestamp

# Event deduplication: track recent operational events to prevent duplicate notifications
_EVENT_DEDUP_WINDOW_SECONDS = 60  # 1 minute for operational events (shorter than alerts)
_recent_events: Dict[str, float] = {}  # fingerprint -> last_sent_timestamp


@dataclass
class Config:
    """Watchtower configuration loaded from environment."""
    log_level: str = "INFO"
    health_port: int = 9191
    health_host: str = "127.0.0.1"
    redis_url: str = "redis://127.0.0.1:6379/1"
    watchdog_interval: int = 10
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    # Phase 4 — Telegram linking
    postgres_dsn: str = "dbname=nextcloud user=nextcloud host=localhost"
    api_key: str = ""
    settings_dir: str = "/opt/cloudvault/web/settings"
    bot_username: str = "cloudvaultfbot"
    # Phase 8 — Notification queue
    queue_enabled: bool = True
    queue_max_retries: int = 3
    queue_base_delay: float = 1.0
    queue_max_delay: float = 60.0
    queue_worker_interval: float = 1.0
    queue_ttl: int = 86400

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            log_level=os.getenv("WATCHTOWER_LOG_LEVEL", "INFO").upper(),
            health_port=int(os.getenv("WATCHTOWER_HEALTH_PORT", "9191")),
            health_host=os.getenv("WATCHTOWER_HEALTH_HOST", "127.0.0.1"),
            redis_url=os.getenv("WATCHTOWER_REDIS_URL", "redis://127.0.0.1:6379/1"),
            watchdog_interval=int(os.getenv("WATCHTOWER_WATCHDOG_INTERVAL", "10")),
            prometheus_enabled=os.getenv("WATCHTOWER_PROMETHEUS_ENABLED", "true").lower() != "false",
            prometheus_port=int(os.getenv("WATCHTOWER_PROMETHEUS_PORT", "9090")),
            postgres_dsn=os.getenv(
                "WATCHTOWER_POSTGRES_DSN",
                "dbname=nextcloud user=nextcloud host=localhost",
            ),
            api_key=os.getenv("WATCHTOWER_API_KEY", ""),
            settings_dir=os.getenv(
                "WATCHTOWER_SETTINGS_DIR", "/opt/cloudvault/web/settings"
            ),
            bot_username=os.getenv("WATCHTELEGRAM_BOT_USERNAME", "cloudvaultfbot"),
            queue_enabled=os.getenv("WATCHTOWER_QUEUE_ENABLED", "true").lower() != "false",
            queue_max_retries=int(os.getenv("WATCHTOWER_QUEUE_MAX_RETRIES", "3")),
            queue_base_delay=float(os.getenv("WATCHTOWER_QUEUE_BASE_DELAY", "1.0")),
            queue_max_delay=float(os.getenv("WATCHTOWER_QUEUE_MAX_DELAY", "60.0")),
            queue_worker_interval=float(os.getenv("WATCHTOWER_QUEUE_WORKER_INTERVAL", "1.0")),
            queue_ttl=int(os.getenv("WATCHTOWER_QUEUE_TTL", "86400")),
        )


class PrometheusQuery:
    """Safe predefined Prometheus metric queries.

    Only hardcoded queries are allowed — no user-controlled PromQL.
    All queries target 127.0.0.1 loopback Prometheus instance.
    """

    # CPU utilization (percentage)
    CPU_UTILIZATION = (
        '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    )

    # Memory utilization (percentage)
    MEMORY_UTILIZATION = (
        '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100'
    )

    # Disk utilization percentage (used)
    DISK_UTILIZATION = (
        '(1 - (node_filesystem_avail_bytes{fstype=~"ext4|xfs"} / node_filesystem_size_bytes{fstype=~"ext4|xfs"})) * 100'
    )

    # Disk availability percentage
    DISK_AVAILABILITY = (
        'node_filesystem_avail_bytes{fstype=~"ext4|xfs"} / node_filesystem_size_bytes{fstype=~"ext4|xfs"} * 100'
    )

    # Disk total size (bytes)
    DISK_TOTAL = 'node_filesystem_size_bytes{fstype=~"ext4|xfs"}'

    # Node availability (up metric = 1 if up, 0 if down)
    NODE_AVAILABILITY = 'up'

    # PostgreSQL connected backends
    POSTGRES_BACKENDS = 'pg_stat_database_numbackends'

    # Redis connected clients
    REDIS_CONNECTED_CLIENTS = 'redis_connected_clients'

    # Nginx active connections
    NGINX_CONNECTIONS = 'nginx_connections_active'

    # Query Prometheus HTTP API for a predefined safe query.
    @staticmethod
    def query(query: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Query Prometheus HTTP API with a predefined safe PromQL query.

        Returns dict with 'success', 'data', or 'error' keys.
        """
        import urllib.request

        url = f"{PROMETHEUS_URL}/api/v1/query"
        params = {"query": query}
        encoded_params = urllib.parse.urlencode(params)
        full_url = f"{url}?{encoded_params}"

        try:
            req = urllib.request.Request(full_url)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                result = json.loads(body)
                return {"success": True, "data": result}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            return {"success": False, "error": f"HTTP {e.code}: {body}"}
        except urllib.error.URLError as e:
            return {"success": False, "error": f"Connection failed: {str(e)}"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON response: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Query error: {str(e)}"}

    # Execute predefined safe query by name
    @staticmethod
    def execute(query_name: str) -> Dict[str, Any]:
        """Execute a predefined safe query by name.

        Raises ValueError if query_name is not a recognized predefined query.
        """
        queries = {
            "cpu_utilization": PrometheusQuery.CPU_UTILIZATION,
            "memory_utilization": PrometheusQuery.MEMORY_UTILIZATION,
            "disk_utilization": PrometheusQuery.DISK_UTILIZATION,
            "disk_availability": PrometheusQuery.DISK_AVAILABILITY,
            "disk_total": PrometheusQuery.DISK_TOTAL,
            "node_availability": PrometheusQuery.NODE_AVAILABILITY,
            "postgres_backends": PrometheusQuery.POSTGRES_BACKENDS,
            "redis_clients": PrometheusQuery.REDIS_CONNECTED_CLIENTS,
            "nginx_connections": PrometheusQuery.NGINX_CONNECTIONS,
        }
        if query_name not in queries:
            raise ValueError(f"Unknown predefined query: {query_name}")
        return PrometheusQuery.query(queries[query_name])


class JSONFormatter(logging.Formatter):
    """JSON log formatter with timestamp, level, component, message."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "component": "watchtower",
            "message": record.getMessage(),
        }
        # Handle extra fields passed via logging extra parameter
        for key, value in record.__dict__.items():
            if key not in {"name", "msg", "args", "created", "filename", "funcName",
                          "levelname", "levelno", "lineno", "module", "msecs",
                          "message", "msg", "pathname", "process", "processName",
                          "relativeCreated", "thread", "threadName", "exc_info",
                          "exc_text", "stack_info", "getMessage"}:
                log_data[key] = value
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(level: str) -> logging.Logger:
    """Configure structured JSON logging."""
    logger = logging.getLogger("watchtower")
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    return logger


class HealthServer:
    """HTTP server exposing health, status, metrics, and storage endpoints."""

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.app = web.Application(middlewares=[self._api_key_middleware])
        self.app.router.add_get("/healthz", self.handle_healthz)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/status", self.handle_status)
        self.app.router.add_get("/metrics", self.handle_metrics)
        self.app.router.add_get("/storage", self.handle_storage)
        # Phase 4 — Telegram linking API
        self.app.router.add_post("/api/telegram/link/generate", self.handle_link_generate)
        self.app.router.add_get("/api/telegram/status", self.handle_link_status)
        self.app.router.add_post("/api/telegram/disconnect", self.handle_link_disconnect)
        self.app.router.add_get("/api/telegram/prefs", self.handle_prefs_get)
        self.app.router.add_post("/api/telegram/prefs", self.handle_prefs_set)
        # Internal API (called by Telegram bot, not exposed to frontend)
        self.app.router.add_post("/api/internal/telegram/validate-token", self.handle_internal_validate)
        self.app.router.add_post("/api/internal/telegram/update-seen", self.handle_internal_update_seen)
        # Phase 5 — Status commands (internal API for Telegram bot)
        self.app.router.add_get("/api/internal/telegram/check-authorization/{user_id}", self.handle_internal_check_auth)
        self.app.router.add_get("/api/internal/telegram/status", self.handle_internal_status)
        self.app.router.add_get("/api/internal/telegram/health", self.handle_internal_health)
        self.app.router.add_get("/api/internal/telegram/metrics", self.handle_internal_metrics)
        self.app.router.add_get("/api/internal/telegram/storage", self.handle_internal_storage)
        self.app.router.add_get("/api/internal/telegram/jobs", self.handle_internal_jobs)
        self.app.router.add_get("/api/internal/telegram/alerts", self.handle_internal_alerts)
        # Phase 6 — Alertmanager webhook (receives alerts from Alertmanager)
        self.app.router.add_post("/api/alertmanager/webhook", self.handle_alertmanager_webhook)
        # Phase 7 — Event notifications (receives events from CloudVault scripts)
        self.app.router.add_post("/api/events", self.handle_event_webhook)
        # Phase 7 — Internal event API for Telegram bot
        self.app.router.add_get("/api/internal/telegram/events", self.handle_internal_events)
        # Phase 8 — Notification queue observability
        self.app.router.add_get("/api/internal/telegram/queue", self.handle_internal_queue)
        self.app.router.add_get("/api/internal/telegram/queue/pending", self.handle_internal_queue_pending)
        self.app.router.add_get("/api/internal/telegram/queue/retry", self.handle_internal_queue_retry)
        self.app.router.add_get("/api/internal/telegram/queue/failed", self.handle_internal_queue_failed)
        # Static settings page
        self.app.router.add_get("/settings/telegram", self.handle_settings_page)
        self.app.router.add_get("/settings/telegram/", self.handle_settings_page)
        self.app.router.add_get("/settings/telegram/assets/{path:.*}", self.handle_settings_asset)
        # Phase 9 — Prometheus metrics endpoint
        self.app.router.add_get("/metrics/prometheus", self.handle_metrics_prometheus)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._ready = False
        self._prometheus_unavailable = False
        # Telegram linking database (lazy init)
        self._tg_db: Any = None
        self._cleanup_task: Optional[asyncio.Task] = None
        # Notification queue (Phase 8 — set by WatchtowerService)
        self._notification_queue: Any = None

    # -- API key middleware ------------------------------------------------

    @web.middleware
    async def _api_key_middleware(self, request: web.Request, handler):
        """Validate API key for /api/* routes.  Internal routes use a separate key."""
        path = request.path
        # Skip non-API routes
        if not path.startswith("/api/"):
            return await handler(request)
        # Public API routes (settings page) — no API key required, user_id header is enough
        _PUBLIC_ROUTES = (
            "/api/telegram/status",
            "/api/telegram/link/generate",
            "/api/telegram/link/confirm",
            "/api/telegram/prefs",
            "/api/telegram/disconnect",
        )
        if path in _PUBLIC_ROUTES:
            return await handler(request)
        # Local webhook endpoints — Alertmanager (receiver) and event webhooks
        # POST from loopback only. Alertmanager's webhook http_config does not
        # support custom headers in this version, so skip the API key check for
        # loopback peers (the endpoints stay protected on non-loopback requests).
        if path in ("/api/alertmanager/webhook", "/api/events"):
            if self._is_loopback_request(request):
                return await handler(request)
        # Internal routes use INTERNAL_API_KEY or fall back to API_KEY
        if path.startswith("/api/internal/"):
            expected = (
                os.getenv("WATCHTOWER_INTERNAL_API_KEY")
                or self.config.api_key
            )
        else:
            expected = self.config.api_key
        if not expected:
            return web.json_response(
                {"error": "api_key_not_configured"}, status=503
            )
        provided = request.headers.get("X-API-Key", "")
        if not provided:
            return web.json_response(
                {"error": "missing_api_key"}, status=401
            )
        import hmac
        if not hmac.compare_digest(provided, expected):
            return web.json_response(
                {"error": "invalid_api_key"}, status=403
            )
        return await handler(request)

    def _is_loopback_request(self, request: web.Request) -> bool:
        """Return True if the request originated from a loopback interface."""
        transport = request.transport
        if transport is None:
            return False
        peername = transport.get_extra_info("peername")
        if peername is None:
            return False
        host = peername[0]
        return host in ("127.0.0.1", "::1")

    # -- Lazy DB init -----------------------------------------------------

    def _get_tg_db(self):
        """Lazily initialize the Telegram linking database."""
        if self._tg_db is None:
            if not HAS_LINKING:
                raise RuntimeError("telegram_linking module not available")
            self._tg_db = TelegramDatabase(self.config.postgres_dsn)
        return self._tg_db

    async def handle_healthz(self, request: web.Request) -> web.Response:
        """Liveness probe - service is running."""
        return web.json_response({"status": "ok", "service": "watchtower"})

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health status - overall system health.

        Returns HEALTHY, DEGRADED, UNHEALTHY, or UNKNOWN based on
        multiple components including Prometheus availability.
        """
        components = []

        # Check Prometheus availability
        prometheus_ok, prometheus_data = await self._check_prometheus_health()
        if prometheus_ok:
            self._prometheus_unavailable = False
            components.append({"component": "Prometheus", "status": "ok", "detail": "reachable"})
        else:
            self._prometheus_unavailable = True
            components.append({"component": "Prometheus", "status": "unavailable", "detail": prometheus_data or "unknown"})

        # Check system services based on healthcheck.sh logic
        for svc in ["nginx", "postgresql", "redis-server", "fail2ban", "clamav-daemon"]:
            try:
                import subprocess
                active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc], capture_output=True, timeout=3
                )
                if active.returncode == 0:
                    components.append({"component": svc, "status": "ok", "detail": "running"})
                else:
                    components.append({"component": svc, "status": "critical", "detail": "not running"})
            except Exception:
                components.append({"component": svc, "status": "unknown", "detail": "check failed"})

        # Determine overall health
        has_critical = any(c["status"] == "critical" for c in components)
        has_unavailable = any(c["status"] == "unavailable" for c in components)

        if has_critical:
            overall = "UNHEALTHY"
        elif has_unavailable:
            overall = "DEGRADED"
        elif len(components) == 0:
            overall = "UNKNOWN"
        else:
            overall = "HEALTHY"

        return web.json_response({
            "status": overall,
            "components": components,
        })

    async def _check_prometheus_health(self) -> tuple:
        """Check if Prometheus is reachable. Returns (ok, detail)."""
        import urllib.request
        try:
            req = urllib.request.Request(f"{PROMETHEUS_URL}/api/v1/query?query=up")
            with urllib.request.urlopen(req, timeout=3) as response:
                return True, None
        except Exception as e:
            return False, str(e)

    async def handle_status(self, request: web.Request) -> web.Response:
        """Operational summary - concise status overview."""

        # Prometheus metrics
        prometheus_metrics = {}
        if not self._prometheus_unavailable:
            try:
                cpu = PrometheusQuery.execute("cpu_utilization")
                mem = PrometheusQuery.execute("memory_utilization")
                disk = PrometheusQuery.execute("disk_utilization")
                node = PrometheusQuery.execute("node_availability")

                prometheus_metrics = {
                    "cpu_utilization": self._extract_value(cpu),
                    "memory_utilization": self._extract_value(mem),
                    "disk_utilization": self._extract_value(disk),
                    "node_availability": self._extract_value(node),
                }
                self._prometheus_unavailable = False
            except Exception:
                self._prometheus_unavailable = True
                prometheus_metrics = {"error": "monitoring_unavailable"}

        # System services status
        services = {}
        try:
            import subprocess
            for svc in ["nginx", "postgresql", "redis-server", "fail2ban", "clamav-daemon"]:
                active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc], capture_output=True, timeout=3
                )
                services[svc] = "running" if active.returncode == 0 else "stopped"
        except Exception:
            services = {"error": "check_failed"}

        # Storage information
        storage = await self._get_storage_info()

        return web.json_response({
            "status": "ok",
            "prometheus": prometheus_metrics,
            "services": services,
            "storage": storage,
        })

    async def _get_storage_info(self) -> Dict[str, Any]:
        """Get storage information from node_exporter metrics or fallback."""
        import subprocess

        # Always try df first as it's the most reliable fallback
        df_result = None
        try:
            result = subprocess.run(
                ["df", "-P", "/"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    parts = lines[1].split()
                    if len(parts) >= 6:
                        total_kb = int(parts[1])
                        used_kb = int(parts[2])
                        avail_kb = int(parts[3])
                        total_gb = total_kb / 1024 / 1024
                        used_gb = used_kb / 1024 / 1024
                        avail_gb = avail_kb / 1024 / 1024
                        usage_pct = int(parts[4].rstrip("%")) if "%" in parts[4] else int(parts[4])
                        df_result = {
                            "used_gb": round(used_gb, 1),
                            "available_gb": round(avail_gb, 1),
                            "total_gb": round(total_gb, 1),
                            "usage_pct": usage_pct,
                            "source": "df",
                        }
        except Exception:
            pass

        # Try Prometheus for additional/override data
        try:
            disk = PrometheusQuery.execute("disk_availability")
            data = disk.get("data", {})
            inner_data = data.get("data", data)
            result = inner_data.get("result", [])
            if result:
                item = result[0]
                value = float(item["value"][1] if isinstance(item, dict) and "value" in item else item[1])
                available_pct = round(value, 1)
                used_pct = round(100 - value, 1)
                # Try to get actual disk sizes from node_exporter
                try:
                    total = PrometheusQuery.execute("disk_total")
                    total_data = total.get("data", {})
                    total_inner = total_data.get("data", total_data)
                    total_result = total_inner.get("result", [])
                    if total_result:
                        t_item = total_result[0]
                        total_bytes = float(t_item["value"][1] if isinstance(t_item, dict) and "value" in t_item else t_item[1])
                        total_gb = total_bytes / 1024 / 1024 / 1024
                        used_gb = total_gb * (used_pct / 100)
                        available_gb = total_gb * (available_pct / 100)
                        return {
                            "used_gb": round(used_gb, 1),
                            "available_gb": round(available_gb, 1),
                            "total_gb": round(total_gb, 1),
                            "usage_pct": used_pct,
                            "source": "prometheus",
                        }
                except Exception:
                    pass
                # Prometheus has percentage but not total - supplement with df if available
                if df_result:
                    df_result["usage_pct"] = used_pct
                    df_result["source"] = "prometheus+df"
                return df_result or {
                    "used_gb": None,
                    "available_gb": None,
                    "total_gb": None,
                    "usage_pct": used_pct,
                    "source": "prometheus",
                }
        except Exception:
            pass

        # Fall back to df result
        if df_result:
            return df_result

        return {"error": "unavailable"}

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """Prometheus metrics - query predefined safe metrics from Prometheus API."""

        if not self.config.prometheus_enabled:
            return web.json_response({
                "error": "prometheus_disabled",
                "message": "Prometheus metrics collection is disabled in watchtower configuration.",
            }, status=503)

        metrics: List[Dict[str, Any]] = []

        # Predefined safe queries - no arbitrary PromQL allowed
        safe_queries = [
            ("cpu_utilization", "CPU utilization (%)"),
            ("memory_utilization", "Memory utilization (%)"),
            ("disk_utilization", "Disk utilization (%)"),
            ("disk_availability", "Disk availability (%)"),
            ("node_availability", "Node availability"),
            ("postgres_backends", "PostgreSQL connected backends"),
            ("redis_clients", "Redis connected clients"),
            ("nginx_connections", "Nginx active connections"),
        ]

        for query_name, description in safe_queries:
            try:
                result = PrometheusQuery.execute(query_name)
                if result.get("success"):
                    data = result.get("data", {})
                    # Handle double-nested structure
                    inner_data = data.get("data", data)
                    result_str = inner_data.get("result", "")
                    # HELP and TYPE lines for Prometheus text format
                    lines = ["# HELP watchtower_{} {}".format(query_name, description),
                             "# TYPE watchtower_{} gauge".format(query_name)]

                    # Parse the value from the Prometheus response
                    # Response format: {"data":{"data":{"result":[["<timestamp>", "<value>"]]}}}
                    result_array = inner_data.get("result", [])
                    if result_array and len(result_array) > 0:
                        item = result_array[0]
                        value_str = item["value"][1] if isinstance(item, dict) and "value" in item else item[1]
                        try:
                            value = float(value_str)
                            lines.append('watchtower_{} {} {}'.format(query_name, description, value))
                        except ValueError:
                            lines.append('watchtower_{} {} "unknown"'.format(query_name, description))
                    else:
                        lines.append('watchtower_{} {} "no_data"'.format(query_name, description))

                    metrics.append({"name": query_name, "description": description, "success": True, "value": result_array})
                else:
                    metrics.append({"name": query_name, "description": description, "success": False, "error": result.get("error", "unknown")})
            except ValueError:
                metrics.append({"name": query_name, "description": description, "success": False, "error": "unknown_query"})
            except Exception as e:
                metrics.append({"name": query_name, "description": description, "success": False, "error": str(e)})

        return web.json_response({
            "metrics": metrics,
            "prometheus_available": not self._prometheus_unavailable,
            "source": "prometheus_http_api",
        })

    async def handle_metrics_prometheus(self, request: web.Request) -> web.Response:
        """GET /metrics/prometheus — Watchtower metrics in Prometheus text exposition format.

        This endpoint is designed for Prometheus scraping. It exposes Watchtower's
        own operational metrics (counters, gauges, histograms) in the standard
        Prometheus text format.

        Metrics are low-cardinality by design. No filenames, user IDs, Telegram IDs,
        IP addresses, or message contents are exposed as labels.
        """
        if not HAS_METRICS:
            return web.Response(
                text="# Watchtower metrics module not available\n",
                content_type="text/plain; version=0.0.4; charset=utf-8",
                status=503,
            )

        # Update queue stats before rendering
        if self._notification_queue:
            wt_metrics.update_queue_stats(self._notification_queue)

        body = wt_metrics.render()
        return web.Response(
            text=body,
            content_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # ----------------------------------------------------------------
    # Phase 4 — Telegram Linking API Handlers
    # ----------------------------------------------------------------

    def _get_user_id(self, request: web.Request) -> Optional[str]:
        """Extract user_id from request header or query parameter.

        In production this would validate a Nextcloud session cookie.
        For Phase 4 we accept it from the X-User-Id header, which the
        frontend sends after reading it from a server-side rendered page.
        """
        return request.headers.get("X-User-Id") or request.query.get("user_id")

    async def handle_link_generate(self, request: web.Request) -> web.Response:
        """POST /api/telegram/link/generate — create a one-time linking token."""
        user_id = self._get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            db = self._get_tg_db()
            token, deep_link = await asyncio.get_event_loop().run_in_executor(
                None, db.create_link_token, user_id
            )
            self.logger.info(
                "Link token generated",
                extra={"event": "link_token_generated", "user_id": user_id},
            )
            return web.json_response({
                "deep_link": deep_link,
                "expires_in": 600,
            })
        except ValueError as e:
            if str(e) == "active_token_exists":
                return web.json_response(
                    {"error": "active_token_exists",
                     "message": "A linking token is already active. Wait for it to expire or disconnect first."},
                    status=409,
                )
            raise
        except Exception as e:
            self.logger.error(
                "Token generation failed",
                extra={"event": "link_token_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_link_status(self, request: web.Request) -> web.Response:
        """GET /api/telegram/status — check connection status."""
        user_id = self._get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            db = self._get_tg_db()
            conn = await asyncio.get_event_loop().run_in_executor(
                None, db.get_connection, user_id
            )
            if conn:
                # Serialize timestamps
                conn["connected_at"] = (
                    conn["connected_at"].isoformat() if conn["connected_at"] else None
                )
                conn["last_seen_at"] = (
                    conn["last_seen_at"].isoformat() if conn["last_seen_at"] else None
                )
                return web.json_response({"connected": True, "connection": conn})
            return web.json_response({"connected": False})
        except Exception as e:
            self.logger.error(
                "Status check failed",
                extra={"event": "link_status_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_link_disconnect(self, request: web.Request) -> web.Response:
        """POST /api/telegram/disconnect — remove Telegram connection."""
        user_id = self._get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            db = self._get_tg_db()
            removed = await asyncio.get_event_loop().run_in_executor(
                None, db.disconnect, user_id
            )
            self.logger.info(
                "Telegram disconnected",
                extra={"event": "telegram_disconnected", "user_id": user_id,
                        "had_connection": removed},
            )
            return web.json_response({"disconnected": True, "had_connection": removed})
        except Exception as e:
            self.logger.error(
                "Disconnect failed",
                extra={"event": "disconnect_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_prefs_get(self, request: web.Request) -> web.Response:
        """GET /api/telegram/prefs — get notification preferences."""
        user_id = self._get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            db = self._get_tg_db()
            prefs = await asyncio.get_event_loop().run_in_executor(
                None, db.get_notification_prefs, user_id
            )
            return web.json_response({"preferences": prefs})
        except Exception as e:
            self.logger.error(
                "Prefs get failed",
                extra={"event": "prefs_get_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_prefs_set(self, request: web.Request) -> web.Response:
        """POST /api/telegram/prefs — update notification preferences."""
        user_id = self._get_user_id(request)
        if not user_id:
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        key = body.get("key")
        value = body.get("value")
        if not key or value not in ("true", "false"):
            return web.json_response(
                {"error": "invalid_request", "message": "Provide key and value (true/false)"},
                status=400,
            )
        try:
            db = self._get_tg_db()
            await asyncio.get_event_loop().run_in_executor(
                None, db.set_notification_pref, user_id, key, value
            )
            return web.json_response({"ok": True})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            self.logger.error(
                "Prefs set failed",
                extra={"event": "prefs_set_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    # -- Internal API (Telegram bot -> Watchtower) ------------------------

    async def handle_internal_validate(self, request: web.Request) -> web.Response:
        """POST /api/internal/telegram/validate-token — bot calls this on /start <token>.

        Body: { "token": "...", "telegram_user_id": 123, "telegram_username": "..." }
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        token = body.get("token", "")
        telegram_user_id = body.get("telegram_user_id")
        telegram_username = body.get("telegram_username")
        if not token or not telegram_user_id:
            return web.json_response({"error": "missing_fields"}, status=400)
        try:
            telegram_user_id = int(telegram_user_id)
        except (ValueError, TypeError):
            return web.json_response({"error": "invalid_telegram_user_id"}, status=400)
        try:
            db = self._get_tg_db()
            user_id = await asyncio.get_event_loop().run_in_executor(
                None, db.validate_and_consume_token,
                token, telegram_user_id, telegram_username,
            )
            if user_id:
                self.logger.info(
                    "Telegram account linked",
                    extra={"event": "telegram_linked", "user_id": user_id},
                )
                return web.json_response({"linked": True, "user_id": user_id})
            return web.json_response({"linked": False, "error": "invalid_token"}, status=400)
        except ValueError as e:
            if str(e) == "telegram_already_linked":
                return web.json_response(
                    {"linked": False, "error": "telegram_already_linked"},
                    status=409,
                )
            raise
        except Exception as e:
            self.logger.error(
                "Token validation failed",
                extra={"event": "token_validate_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_internal_update_seen(self, request: web.Request) -> web.Response:
        """POST /api/internal/telegram/update-seen — bot calls this on each interaction."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        telegram_user_id = body.get("telegram_user_id")
        if not telegram_user_id:
            return web.json_response({"error": "missing_fields"}, status=400)
        try:
            db = self._get_tg_db()
            await asyncio.get_event_loop().run_in_executor(
                None, db.get_connection_by_telegram_id, int(telegram_user_id)
            )
            # Just touch the record (update last_seen_at)
            import psycopg2
            conn = db._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE oc_telegram_connections SET last_seen_at = now() "
                    "WHERE telegram_user_id = %s",
                    (int(telegram_user_id),),
                )
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()
            return web.json_response({"ok": True})
        except Exception:
            return web.json_response({"ok": True})  # Best-effort, don't fail bot

    # ----------------------------------------------------------------
    # Phase 5 — Internal API for Telegram bot status commands
    # ----------------------------------------------------------------

    async def handle_internal_check_auth(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/check-authorization/{user_id} — verify Telegram user is linked."""
        user_id_str = request.match_info.get("user_id")
        if not user_id_str:
            return web.json_response({"error": "missing_user_id"}, status=400)
        try:
            telegram_user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"error": "invalid_user_id"}, status=400)
        try:
            db = self._get_tg_db()
            conn = await asyncio.get_event_loop().run_in_executor(
                None, db.get_connection_by_telegram_id, telegram_user_id
            )
            if conn:
                return web.json_response({
                    "authorized": True,
                    "user_id": conn["user_id"],
                })
            return web.json_response({"authorized": False})
        except Exception as e:
            self.logger.error(
                "Authorization check failed",
                extra={"event": "auth_check_failed", "error": str(e)},
            )
            return web.json_response({"error": "internal_error"}, status=500)

    async def handle_internal_status(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/status — operational summary for Telegram bot."""
        # Reuse existing handle_status logic but return raw JSON
        prometheus_metrics = {}
        if not self._prometheus_unavailable:
            try:
                cpu = PrometheusQuery.execute("cpu_utilization")
                mem = PrometheusQuery.execute("memory_utilization")
                disk = PrometheusQuery.execute("disk_utilization")
                node = PrometheusQuery.execute("node_availability")
                prometheus_metrics = {
                    "cpu_utilization": self._extract_value(cpu),
                    "memory_utilization": self._extract_value(mem),
                    "disk_utilization": self._extract_value(disk),
                    "node_availability": self._extract_value(node),
                }
                self._prometheus_unavailable = False
            except Exception:
                self._prometheus_unavailable = True
                prometheus_metrics = {"error": "monitoring_unavailable"}

        services = {}
        try:
            import subprocess
            for svc in ["nginx", "postgresql", "redis-server", "fail2ban", "clamav-daemon"]:
                active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc], capture_output=True, timeout=3
                )
                services[svc] = "running" if active.returncode == 0 else "stopped"
        except Exception:
            services = {"error": "check_failed"}

        storage = await self._get_storage_info()

        # Phase 8: Add queue status
        queue_status = {}
        if self._notification_queue:
            try:
                queue_health = await self._notification_queue.health_check()
                queue_status = queue_health
            except Exception:
                queue_status = {"status": "error", "detail": "check_failed"}

        return web.json_response({
            "status": "ok",
            "prometheus": prometheus_metrics,
            "services": services,
            "storage": storage,
            "notification_queue": queue_status,
        })

    async def handle_internal_health(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/health — health status for Telegram bot."""
        components = []

        # Check Prometheus availability
        prometheus_ok, prometheus_data = await self._check_prometheus_health()
        if prometheus_ok:
            self._prometheus_unavailable = False
            components.append({"component": "Prometheus", "status": "ok", "detail": "reachable"})
        else:
            self._prometheus_unavailable = True
            components.append({"component": "Prometheus", "status": "unavailable", "detail": prometheus_data or "unknown"})

        # Check system services
        for svc in ["nginx", "postgresql", "redis-server", "fail2ban", "clamav-daemon"]:
            try:
                import subprocess
                active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc], capture_output=True, timeout=3
                )
                if active.returncode == 0:
                    components.append({"component": svc, "status": "ok", "detail": "running"})
                else:
                    components.append({"component": svc, "status": "critical", "detail": "not running"})
            except Exception:
                components.append({"component": svc, "status": "unknown", "detail": "check failed"})

        # Phase 8: Check notification queue
        if self._notification_queue:
            try:
                queue_health = await self._notification_queue.health_check()
                components.append({
                    "component": "notification_queue",
                    "status": queue_health.get("status", "unknown"),
                    "detail": queue_health.get("detail", ""),
                    "pending": queue_health.get("pending", 0),
                    "retry": queue_health.get("retry", 0),
                })
            except Exception:
                components.append({
                    "component": "notification_queue",
                    "status": "unknown",
                    "detail": "check failed",
                })

        # Determine overall health
        has_critical = any(c["status"] == "critical" for c in components)
        has_unavailable = any(c["status"] == "unavailable" for c in components)

        if has_critical:
            overall = "UNHEALTHY"
        elif has_unavailable:
            overall = "DEGRADED"
        elif len(components) == 0:
            overall = "UNKNOWN"
        else:
            overall = "HEALTHY"

        return web.json_response({
            "status": overall,
            "components": components,
        })

    async def handle_internal_metrics(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/metrics — predefined metrics for Telegram bot."""
        if not self.config.prometheus_enabled:
            return web.json_response({
                "error": "prometheus_disabled",
                "metrics": [],
            })

        metrics = []
        safe_queries = [
            ("cpu_utilization", "CPU utilization (%)"),
            ("memory_utilization", "Memory utilization (%)"),
            ("disk_utilization", "Disk utilization (%)"),
        ]

        for query_name, description in safe_queries:
            try:
                result = PrometheusQuery.execute(query_name)
                if result.get("success"):
                    value = self._extract_value(result)
                    metrics.append({"name": query_name, "value": value, "success": True})
                else:
                    metrics.append({"name": query_name, "value": None, "success": False, "error": result.get("error", "unknown")})
            except Exception as e:
                metrics.append({"name": query_name, "value": None, "success": False, "error": str(e)})

        return web.json_response({
            "metrics": metrics,
            "prometheus_available": not self._prometheus_unavailable,
        })

    async def handle_internal_storage(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/storage — storage info for Telegram bot."""
        storage = await self._get_storage_info()
        return web.json_response({"storage": storage})

    async def handle_internal_jobs(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/jobs — background job status for Telegram bot."""
        jobs = []

        # Check PostgreSQL cron jobs if available
        try:
            db = self._get_tg_db()
            conn = db._connect()
            try:
                cur = conn.cursor()
                # Check if pg_cron is available
                cur.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'"
                )
                if cur.fetchone():
                    cur.execute(
                        "SELECT jobname, schedule, active FROM cron.job LIMIT 10"
                    )
                    for row in cur.fetchall():
                        jobs.append({
                            "name": row[0],
                            "status": "ok" if row[2] else "disabled",
                            "last_run": None,
                        })
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()
        except Exception:
            pass

        # Check systemd timers
        try:
            import subprocess
            result = subprocess.run(
                ["systemctl", "list-timers", "--no-pager", "--plain", "--no-legend"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            timer_name = parts[1] if len(parts) > 1 else "unknown"
                            jobs.append({
                                "name": timer_name,
                                "status": "ok",
                                "last_run": parts[0] if parts[0] != "-" else None,
                            })
        except Exception:
            pass

        return web.json_response({"jobs": jobs})

    async def handle_internal_alerts(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/alerts — active alerts from Alertmanager."""
        alerts = []

        # Query Alertmanager for active alerts
        alertmanager_url = os.getenv("ALERTMANAGER_URL", "http://127.0.0.1:9093")
        try:
            import urllib.request
            import urllib.parse
            url = f"{alertmanager_url}/api/v2/alerts"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                for alert in data:
                    labels = alert.get("labels", {})
                    annotations = alert.get("annotations", {})
                    alerts.append({
                        "name": labels.get("alertname", "unknown"),
                        "severity": labels.get("severity", "unknown"),
                        "summary": annotations.get("summary", ""),
                    })
        except Exception:
            return web.json_response({
                "error": "alertmanager_unavailable",
                "alerts": [],
            })

        return web.json_response({"alerts": alerts})

    # ----------------------------------------------------------------
    # Phase 6 — Alertmanager Webhook Handler
    # ----------------------------------------------------------------

    def _compute_alert_fingerprint(self, alert: Dict[str, Any]) -> str:
        """Compute a fingerprint for deduplication.

        Uses alertname + severity + instance to create a unique key.
        """
        labels = alert.get("labels", {})
        alertname = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        instance = labels.get("instance", "unknown")
        return f"{alertname}:{severity}:{instance}"

    def _is_duplicate_alert(self, fingerprint: str) -> bool:
        """Check if this alert was recently sent (deduplication)."""
        import time
        now = time.time()
        last_sent = _recent_alerts.get(fingerprint)
        if last_sent and (now - last_sent) < _ALERT_DEDUP_WINDOW_SECONDS:
            return True
        return False

    def _mark_alert_sent(self, fingerprint: str) -> None:
        """Record that this alert was sent."""
        import time
        _recent_alerts[fingerprint] = time.time()
        # Cleanup old entries periodically
        if len(_recent_alerts) > 1000:
            cutoff = time.time() - _ALERT_DEDUP_WINDOW_SECONDS
            expired = [k for k, v in _recent_alerts.items() if v < cutoff]
            for k in expired:
                del _recent_alerts[k]

    def _format_alert_telegram(self, alert: Dict[str, Any]) -> str:
        """Format an Alertmanager alert for Telegram notification.

        Follows the spec format:
        🚨 CloudVault Alert

        Status: DEGRADED
        Disk usage: 92%
        Server: cloudvault
        Used: 920 GB / 1 TB
        Available: 80 GB
        [View Grafana]
        """
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        alertname = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        instance = labels.get("instance", "unknown")
        summary = annotations.get("summary", "")

        # Status mapping
        status_map = {
            "critical": "CRITICAL",
            "warning": "WARNING",
            "info": "INFO",
        }
        status_text = status_map.get(severity, severity.upper())

        lines = ["🚨 CloudVault Alert\n"]
        lines.append(f"Status: {status_text}")
        lines.append(f"Alert: {alertname}")
        lines.append(f"Server: {instance}")

        if summary:
            lines.append(f"\nDetails:")
            lines.append(summary)

        # Add storage info if available (for disk alerts)
        if "DiskSpace" in alertname or "storage" in alertname.lower():
            # Try to get current storage info
            pass

        # Add Grafana link if configured
        grafana_url = os.getenv("WATCHTOWER_GRAFANA_URL", "")
        if grafana_url:
            lines.append(f"\n[View Grafana]({grafana_url})")

        return "\n".join(lines)

    async def _send_alert_to_telegram(self, alert: Dict[str, Any]) -> None:
        """Send an alert to all authorized Telegram users.

        Respects notification preferences for SECURITY_ALERT and HEALTH_ALERT.
        """
        try:
            # Get all connected Telegram users
            db = self._get_tg_db()
            connections = await asyncio.get_event_loop().run_in_executor(
                None, db.get_all_connections
            )

            if not connections:
                self.logger.info(
                    "No Telegram connections for alert routing",
                    extra={"event": "alert_no_recipients"},
                )
                return

            # Format the alert message
            message = self._format_alert_telegram(alert)

            # Get Telegram bot token from environment
            bot_token = os.getenv("WATCHTELEGRAM_BOT_TOKEN")
            if not bot_token:
                self.logger.warning(
                    "Telegram bot token not configured for alert routing",
                    extra={"event": "alert_no_bot_token"},
                )
                return

            # Send to each connected user
            sent_count = 0
            for conn in connections:
                user_id = conn.get("user_id")
                telegram_user_id = conn.get("telegram_user_id")

                if not telegram_user_id:
                    continue

                # Check notification preferences
                try:
                    prefs = await asyncio.get_event_loop().run_in_executor(
                        None, db.get_notification_prefs, user_id
                    )
                    # Check SECURITY_ALERT and HEALTH_ALERT preferences
                    security_enabled = prefs.get("SECURITY_ALERT", "true") == "true"
                    health_enabled = prefs.get("HEALTH_ALERT", "true") == "true"

                    if not (security_enabled or health_enabled):
                        continue
                except Exception:
                    # If we can't check prefs, send anyway (fail-open for alerts)
                    pass

                # Send via Telegram Bot API
                try:
                    import urllib.request
                    import urllib.parse

                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    data = json.dumps({
                        "chat_id": telegram_user_id,
                        "text": message,
                        "parse_mode": "Markdown",
                    }).encode("utf-8")

                    req = urllib.request.Request(
                        url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as response:
                        result = json.loads(response.read().decode("utf-8"))
                        if result.get("ok"):
                            sent_count += 1
                            self.logger.info(
                                "Alert sent to Telegram user",
                                extra={
                                    "event": "alert_sent",
                                    "telegram_user_id": telegram_user_id,
                                    "alertname": alert.get("labels", {}).get("alertname"),
                                },
                            )
                        else:
                            self.logger.warning(
                                "Failed to send alert to Telegram user",
                                extra={
                                    "event": "alert_send_failed",
                                    "telegram_user_id": telegram_user_id,
                                    "error": result,
                                },
                            )
                except Exception as e:
                    self.logger.error(
                        "Error sending alert to Telegram",
                        extra={
                            "event": "alert_send_error",
                            "telegram_user_id": telegram_user_id,
                            "error": str(e),
                        },
                    )

            self.logger.info(
                "Alert routing complete",
                extra={
                    "event": "alert_routing_complete",
                    "alertname": alert.get("labels", {}).get("alertname"),
                    "sent_count": sent_count,
                    "total_recipients": len(connections),
                },
            )

        except Exception as e:
            self.logger.error(
                "Alert routing failed",
                extra={"event": "alert_routing_failed", "error": str(e)},
            )

    async def handle_alertmanager_webhook(self, request: web.Request) -> web.Response:
        """POST /api/alertmanager/webhook — receive alerts from Alertmanager.

        This endpoint is called by Alertmanager when alerts fire or resolve.
        Format: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config

        The endpoint:
        1. Validates the payload
        2. Deduplicates alerts to prevent storms
        3. Formats alerts for Telegram
        4. Routes to authorized users
        5. Returns 200 OK to Alertmanager (never fail Alertmanager)
        """
        try:
            body = await request.json()
        except Exception:
            # Always return 200 to Alertmanager
            return web.json_response({"status": "ok"})

        # Phase 9: Track webhook requests
        if HAS_METRICS:
            wt_metrics.webhook_requests_total.inc(labels={"endpoint": "alertmanager"})

        # Alertmanager sends {"alerts": [...], "status": "resolved"|"firing"}
        alerts = body.get("alerts", [])
        status = body.get("status", "unknown")

        self.logger.info(
            "Alertmanager webhook received",
            extra={
                "event": "alertmanager_webhook_received",
                "alert_count": len(alerts),
                "status": status,
            },
        )

        # Process each alert
        for alert in alerts:
            # Compute fingerprint for deduplication
            fingerprint = self._compute_alert_fingerprint(alert)

            # Skip if recently sent
            if self._is_duplicate_alert(fingerprint):
                self.logger.info(
                    "Alert deduplicated, skipping",
                    extra={
                        "event": "alert_deduplicated",
                        "fingerprint": fingerprint,
                    },
                )
                continue

            # Only send firing alerts, not resolved
            if alert.get("status") == "resolved":
                self.logger.info(
                    "Alert resolved, skipping notification",
                    extra={
                        "event": "alert_resolved",
                        "fingerprint": fingerprint,
                    },
                )
                continue

            # Mark as sent before sending (prevent race conditions)
            self._mark_alert_sent(fingerprint)

            # Send to Telegram users
            await self._send_alert_to_telegram(alert)

        return web.json_response({"status": "ok"})

    # ----------------------------------------------------------------
    # Phase 7 — Event Notifications
    # ----------------------------------------------------------------

    def _compute_event_fingerprint(self, event_type: str, detail: str) -> str:
        """Compute fingerprint for operational event deduplication."""
        return f"{event_type}:{detail}"

    def _is_duplicate_event(self, fingerprint: str) -> bool:
        """Check if this event was recently sent."""
        import time
        now = time.time()
        last_sent = _recent_events.get(fingerprint)
        if last_sent and (now - last_sent) < _EVENT_DEDUP_WINDOW_SECONDS:
            return True
        return False

    def _mark_event_sent(self, fingerprint: str) -> None:
        """Record that this event was sent."""
        import time
        _recent_events[fingerprint] = time.time()
        # Cleanup old entries periodically
        if len(_recent_events) > 500:
            cutoff = time.time() - _EVENT_DEDUP_WINDOW_SECONDS
            expired = [k for k, v in _recent_events.items() if v < cutoff]
            for k in expired:
                del _recent_events[k]

    def _format_event_telegram(self, event: Dict[str, Any]) -> str:
        """Format an operational event for Telegram notification.

        Supports event types: BACKUP_COMPLETED, BACKUP_FAILED, HEALTH_ALERT,
        UPLOAD_COMPLETED, UPLOAD_FAILED, and others from notification preferences.
        """
        event_type = event.get("event_type", "UNKNOWN")
        status = event.get("status", "unknown")
        detail = event.get("detail", "")
        timestamp = event.get("timestamp", "")
        label = event.get("label", "")
        size = event.get("size", "")
        duration = event.get("duration", "")
        exit_code = event.get("exit_code")

        # Map event type to notification category
        category_map = {
            "BACKUP_COMPLETED": "Backup",
            "BACKUP_FAILED": "Backup",
            "HEALTH_ALERT": "Health",
            "SECURITY_ALERT": "Security",
            "UPLOAD_COMPLETED": "Upload",
            "UPLOAD_FAILED": "Upload",
            "BACKGROUND_JOB_FAILED": "Background Job",
            "STORAGE_WARNING": "Storage",
            "STORAGE_CRITICAL": "Storage",
        }
        category = category_map.get(event_type, "Event")

        # Status icon and text
        if "FAILED" in event_type or "CRITICAL" in event_type or status == "error":
            icon = "!"
            status_text = "FAILED"
        elif "COMPLETED" in event_type or status == "success":
            icon = "+"
            status_text = "SUCCESS"
        elif "WARNING" in event_type or status == "warning":
            icon = "~"
            status_text = "WARNING"
        else:
            icon = "*"
            status_text = status.upper()

        lines = [f"{icon} CloudVault {category} Event\n"]
        lines.append(f"Status: {status_text}")

        if label:
            lines.append(f"Type: {label}")

        if detail:
            lines.append(f"Detail: {detail}")

        if size:
            lines.append(f"Size: {size}")

        if duration:
            lines.append(f"Duration: {duration}")

        if exit_code is not None and exit_code != 0:
            lines.append(f"Exit code: {exit_code}")

        if timestamp:
            lines.append(f"Time: {timestamp}")

        # Add Grafana link if configured
        grafana_url = os.getenv("WATCHTOWER_GRAFANA_URL", "")
        if grafana_url:
            lines.append(f"\n[View Grafana]({grafana_url})")

        return "\n".join(lines)

    async def _send_event_to_telegram(self, event: Dict[str, Any]) -> None:
        """Send an operational event to all authorized Telegram users.

        Respects notification preferences for the event type.
        """
        try:
            db = self._get_tg_db()
            connections = await asyncio.get_event_loop().run_in_executor(
                None, db.get_all_connections
            )

            if not connections:
                self.logger.info(
                    "No Telegram connections for event routing",
                    extra={"event": "event_no_recipients"},
                )
                return

            # Format the event message
            message = self._format_event_telegram(event)

            # Get Telegram bot token from environment
            bot_token = os.getenv("WATCHTELEGRAM_BOT_TOKEN")
            if not bot_token:
                self.logger.warning(
                    "Telegram bot token not configured for event routing",
                    extra={"event": "event_no_bot_token"},
                )
                return

            # Map event type to notification preference key
            event_type = event.get("event_type", "UNKNOWN")
            pref_key = event_type  # BACKUP_COMPLETED, BACKUP_FAILED, etc.

            sent_count = 0
            for conn in connections:
                user_id = conn.get("user_id")
                telegram_user_id = conn.get("telegram_user_id")

                if not telegram_user_id:
                    continue

                # Check notification preferences
                try:
                    prefs = await asyncio.get_event_loop().run_in_executor(
                        None, db.get_notification_prefs, user_id
                    )
                    if prefs.get(pref_key, "true") != "true":
                        continue
                except Exception:
                    # If we can't check prefs, send anyway (fail-open for events)
                    pass

                # Send via Telegram Bot API
                try:
                    import urllib.request
                    import urllib.parse

                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    data = json.dumps({
                        "chat_id": telegram_user_id,
                        "text": message,
                        "parse_mode": "Markdown",
                    }).encode("utf-8")

                    req = urllib.request.Request(
                        url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as response:
                        result = json.loads(response.read().decode("utf-8"))
                        if result.get("ok"):
                            sent_count += 1
                            self.logger.info(
                                "Event sent to Telegram user",
                                extra={
                                    "event": "event_sent",
                                    "telegram_user_id": telegram_user_id,
                                    "event_type": event_type,
                                },
                            )
                        else:
                            self.logger.warning(
                                "Failed to send event to Telegram user",
                                extra={
                                    "event": "event_send_failed",
                                    "telegram_user_id": telegram_user_id,
                                    "error": result,
                                },
                            )
                except Exception as e:
                    self.logger.error(
                        "Error sending event to Telegram",
                        extra={
                            "event": "event_send_error",
                            "telegram_user_id": telegram_user_id,
                            "error": str(e),
                        },
                    )

            self.logger.info(
                "Event routing complete",
                extra={
                    "event": "event_routing_complete",
                    "event_type": event_type,
                    "sent_count": sent_count,
                    "total_recipients": len(connections),
                },
            )

        except Exception as e:
            self.logger.error(
                "Event routing failed",
                extra={"event": "event_routing_failed", "error": str(e)},
            )

    async def handle_event_webhook(self, request: web.Request) -> web.Response:
        """POST /api/events — receive operational events from CloudVault scripts.

        This endpoint is called by backup.sh, maintenance.sh, and other
        operational scripts to report success/failure.

        Payload format:
        {
            "event_type": "BACKUP_COMPLETED" | "BACKUP_FAILED" | "HEALTH_ALERT" | ...,
            "status": "success" | "error" | "warning",
            "detail": "...",
            "timestamp": "2026-08-27 03:15:00 UTC",
            "label": "daily",
            "size": "1.2G",
            "duration": "2m 30s",
            "exit_code": 0
        }

        The endpoint:
        1. Validates the API key
        2. Deduplicates events to prevent storms
        3. Formats events for Telegram
        4. Routes to authorized users asynchronously
        5. Returns 200 OK immediately (never blocks the caller)
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"status": "ok"})

        # Phase 9: Track webhook requests
        if HAS_METRICS:
            wt_metrics.webhook_requests_total.inc(labels={"endpoint": "events"})

        event_type = body.get("event_type", "UNKNOWN")
        status = body.get("status", "unknown")
        detail = body.get("detail", "")

        self.logger.info(
            "Event received",
            extra={
                "event": "event_received",
                "event_type": event_type,
                "status": status,
                "detail": detail,
            },
        )

        # Compute fingerprint for deduplication
        fingerprint = self._compute_event_fingerprint(event_type, detail)

        # Skip if recently sent
        if self._is_duplicate_event(fingerprint):
            self.logger.info(
                "Event deduplicated, skipping",
                extra={
                    "event": "event_deduplicated",
                    "fingerprint": fingerprint,
                },
            )
            return web.json_response({"status": "ok"})

        # Mark as sent before sending (prevent race conditions)
        self._mark_event_sent(fingerprint)

        # Send to Telegram users asynchronously (non-blocking)
        # Phase 8: Use notification queue if available, otherwise fall back to direct send
        if self._notification_queue and self._notification_queue._connected:
            # Format message for Telegram
            formatted_message = self._format_event_telegram(body)
            payload = {
                "event_type": event_type,
                "message": formatted_message,
                "raw_event": body,
            }
            notification_id = await self._notification_queue.enqueue(
                event_type=event_type,
                payload=payload,
            )
            if notification_id:
                self.logger.debug(
                    "Event enqueued for Telegram delivery",
                    extra={
                        "event": "event_enqueued",
                        "notification_id": notification_id,
                        "event_type": event_type,
                    },
                )
            else:
                # Queue unavailable, fall back to direct send
                self.logger.warning(
                    "Queue unavailable, falling back to direct send",
                    extra={"event": "event_queue_fallback"},
                )
                asyncio.ensure_future(self._send_event_to_telegram(body))
        else:
            # No queue available, use direct send (legacy mode)
            asyncio.ensure_future(self._send_event_to_telegram(body))

        return web.json_response({"status": "ok"})

    # ----------------------------------------------------------------
    # Phase 7 — Internal Event API for Telegram bot
    # ----------------------------------------------------------------

    async def handle_internal_events(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/events — recent events for Telegram bot."""
        # Return recent events from dedup cache (informational only)
        import time
        now = time.time()
        recent = []
        for fp, ts in _recent_events.items():
            if (now - ts) < 3600:  # last hour
                parts = fp.split(":", 1)
                recent.append({
                    "event_type": parts[0] if parts else "unknown",
                    "detail": parts[1] if len(parts) > 1 else "",
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                })
        return web.json_response({"events": recent})

    # ----------------------------------------------------------------
    # Phase 8 — Notification Queue Observability
    # ----------------------------------------------------------------

    async def handle_internal_queue(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/queue — queue status and statistics."""
        if not self._notification_queue:
            return web.json_response({
                "status": "unavailable",
                "detail": "Notification queue not initialized",
            })

        stats = await self._notification_queue.get_stats()
        health = await self._notification_queue.health_check()

        return web.json_response({
            "queue": stats,
            "health": health,
        })

    async def handle_internal_queue_pending(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/queue/pending — pending notifications."""
        if not self._notification_queue:
            return web.json_response({
                "status": "unavailable",
                "detail": "Notification queue not initialized",
            })

        limit = int(request.query.get("limit", "10"))
        pending = await self._notification_queue.get_pending_notifications(limit=limit)

        return web.json_response({
            "notifications": pending,
            "count": len(pending),
        })

    async def handle_internal_queue_retry(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/queue/retry — notifications pending retry."""
        if not self._notification_queue:
            return web.json_response({
                "status": "unavailable",
                "detail": "Notification queue not initialized",
            })

        limit = int(request.query.get("limit", "10"))
        retry = await self._notification_queue.get_retry_notifications(limit=limit)

        return web.json_response({
            "notifications": retry,
            "count": len(retry),
        })

    async def handle_internal_queue_failed(self, request: web.Request) -> web.Response:
        """GET /api/internal/telegram/queue/failed — permanently failed notifications."""
        if not self._notification_queue:
            return web.json_response({
                "status": "unavailable",
                "detail": "Notification queue not initialized",
            })

        limit = int(request.query.get("limit", "10"))
        failed = await self._notification_queue.get_failed_notifications(limit=limit)

        return web.json_response({
            "notifications": failed,
            "count": len(failed),
        })

    # -- Settings page serving --------------------------------------------

    async def handle_settings_page(self, request: web.Request) -> web.Response:
        """Serve the Telegram settings page."""
        settings_dir = Path(self.config.settings_dir)
        page = settings_dir / "telegram" / "index.html"
        if not page.exists():
            return web.Response(status=404, text="Settings page not found")
        content = page.read_text(encoding="utf-8")
        return web.Response(
            text=content,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_settings_asset(self, request: web.Request) -> web.Response:
        """Serve static assets for the settings page."""
        asset_path = request.match_info.get("path", "")
        # Prevent directory traversal
        if ".." in asset_path or asset_path.startswith("/"):
            return web.Response(status=403, text="forbidden")
        asset = Path(self.config.settings_dir) / "telegram" / "assets" / asset_path
        if not asset.exists() or not asset.is_file():
            return web.Response(status=404, text="not found")
        content_type = "application/octet-stream"
        if asset.suffix == ".css":
            content_type = "text/css"
        elif asset.suffix == ".js":
            content_type = "application/javascript"
        elif asset.suffix == ".html":
            content_type = "text/html"
        elif asset.suffix == ".svg":
            content_type = "image/svg+xml"
        content = asset.read_bytes()
        return web.Response(
            body=content,
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )

    # -- Token cleanup task -----------------------------------------------

    async def _token_cleanup_loop(self) -> None:
        """Periodically remove expired/used linking tokens."""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                db = self._get_tg_db()
                deleted = await asyncio.get_event_loop().run_in_executor(
                    None, db.cleanup_expired_tokens
                )
                if deleted > 0:
                    self.logger.info(
                        "Token cleanup",
                        extra={"event": "token_cleanup", "deleted": deleted},
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(
                    "Token cleanup error",
                    extra={"event": "token_cleanup_error", "error": str(e)},
                )

    # ----------------------------------------------------------------
    # Existing endpoints (Phases 1-2)
    # ----------------------------------------------------------------

    async def handle_storage(self, request: web.Request) -> web.Response:
        """Storage information based on existing CloudVault/system metrics."""

        storage = await self._get_storage_info()

        # Build response based on what's available
        if "error" in storage:
            return web.json_response({
                "storage": {
                    "used_gb": "unavailable",
                    "available_gb": "unavailable",
                    "total_gb": "unavailable",
                    "usage_pct": "unavailable",
                    "source": "unavailable",
                    "error": storage["error"],
                }
            })

        return web.json_response({
            "storage": {
                "used_gb": storage.get("used_gb"),
                "available_gb": storage.get("available_gb"),
                "total_gb": storage.get("total_gb"),
                "usage_pct": storage.get("usage_pct"),
                "source": storage.get("source", "unknown"),
            }
        })

    def _extract_value(self, result: Dict[str, Any]) -> Any:
        """Extract the value from a Prometheus query result."""
        data = result.get("data", {})
        # Handle double-nested structure: {"data": {"data": {"result": [...]}}}
        inner_data = data.get("data", data)
        result_array = inner_data.get("result", [])
        if result_array and len(result_array) > 0:
            item = result_array[0]
            # Vector format: {"metric": {...}, "value": [timestamp, "value"]}
            if isinstance(item, dict) and "value" in item:
                return float(item["value"][1])
            # Legacy flat format: [timestamp, "value"]
            if isinstance(item, list) and len(item) > 1:
                return float(item[1])
        return None

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config.health_host, self.config.health_port)
        await self.site.start()
        self.logger.info(
            "Health server started",
            extra={"event": "health_server_start", "host": self.config.health_host, "port": self.config.health_port}
        )

    async def stop(self) -> None:
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self.logger.info("Health server stopped", extra={"event": "health_server_stop"})

    def set_ready(self, ready: bool) -> None:
        self._ready = ready


class WatchtowerService:
    """Main Watchtower service."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config.log_level)
        self.health_server = HealthServer(config, self.logger)
        self._shutdown_event = asyncio.Event()
        self._watchdog_task: Optional[asyncio.Task] = None
        self._notification_queue: Optional[Any] = None

    async def start(self) -> None:
        """Start the service."""
        self.logger.info(
            "Starting CloudVault Watchtower",
            extra={"event": "service_start", "version": "1.0.0"}
        )

        # Start health server (provides /health, /status, /metrics, /storage,
        # plus Phase 4 linking API and settings page)
        await self.health_server.start()
        self.health_server.set_ready(True)

        # Start notification queue (Phase 8)
        if self.config.queue_enabled and HAS_QUEUE:
            try:
                self._notification_queue = NotificationQueue(
                    redis_url=self.config.redis_url,
                    logger=self.logger,
                    max_retries=self.config.queue_max_retries,
                    base_delay=self.config.queue_base_delay,
                    max_delay=self.config.queue_max_delay,
                    worker_interval=self.config.queue_worker_interval,
                    queue_ttl=self.config.queue_ttl,
                )
                connected = await self._notification_queue.connect()
                if connected:
                    # Set the send callback (existing _send_event_to_telegram logic)
                    self._notification_queue.set_send_callback(self._queue_send_callback)
                    await self._notification_queue.start_worker()
                    self.health_server._notification_queue = self._notification_queue
                    self.logger.info(
                        "Notification queue started",
                        extra={"event": "queue_start"},
                    )
                else:
                    self._notification_queue = None
                    self.logger.warning(
                        "Notification queue Redis unavailable, degraded mode",
                        extra={"event": "queue_start_degraded"},
                    )
            except Exception as e:
                self._notification_queue = None
                self.logger.error(
                    "Failed to start notification queue",
                    extra={"event": "queue_start_error", "error": str(e)},
                )

        # Start token cleanup task (Phase 4)
        if HAS_LINKING:
            try:
                self.health_server._get_tg_db()  # verify DB connectivity
                self.health_server._cleanup_task = asyncio.create_task(
                    self.health_server._token_cleanup_loop()
                )
                self.logger.info(
                    "Token cleanup task started",
                    extra={"event": "token_cleanup_start"},
                )
            except Exception as e:
                self.logger.warning(
                    "Telegram linking DB unavailable, skipping cleanup",
                    extra={"event": "token_cleanup_skip", "error": str(e)},
                )

        # Start systemd watchdog
        if HAS_SYSTEMD:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            self.logger.info("Systemd watchdog enabled", extra={"event": "watchdog_start"})

        # Notify systemd ready
        if HAS_SYSTEMD:
            systemd.daemon.notify("READY=1")
            self.logger.info("Notified systemd ready", extra={"event": "systemd_ready"})

    async def stop(self) -> None:
        """Graceful shutdown."""
        self.logger.info("Shutting down CloudVault Watchtower", extra={"event": "service_stop"})

        # Notify systemd stopping
        if HAS_SYSTEMD:
            systemd.daemon.notify("STOPPING=1")

        # Stop notification queue (Phase 8)
        if self._notification_queue:
            try:
                await self._notification_queue.stop_worker()
                await self._notification_queue.disconnect()
                self.logger.info(
                    "Notification queue stopped",
                    extra={"event": "queue_stop"},
                )
            except Exception as e:
                self.logger.error(
                    "Error stopping notification queue",
                    extra={"event": "queue_stop_error", "error": str(e)},
                )

        # Cancel token cleanup
        if self.health_server._cleanup_task:
            self.health_server._cleanup_task.cancel()
            try:
                await self.health_server._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel watchdog
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

        # Stop health server
        self.health_server.set_ready(False)
        await self.health_server.stop()

        self.logger.info("CloudVault Watchtower stopped", extra={"event": "service_stopped"})

    async def _queue_send_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send callback for notification queue — routes to Telegram.

        This callback is invoked by the notification queue worker to send
        notifications to Telegram. It handles user resolution and message
        formatting.
        """
        try:
            event_type = payload.get("event_type", "UNKNOWN")
            message = payload.get("message", "")

            # Get all Telegram connections
            db = self.health_server._get_tg_db()
            connections = await asyncio.get_event_loop().run_in_executor(
                None, db.get_all_connections
            )

            if not connections:
                self.logger.debug(
                    "No Telegram connections for notification",
                    extra={"event": "queue_no_connections", "event_type": event_type},
                )
                return {"success": False, "error": "no_connections"}

            sent_to = []
            errors = []

            for conn in connections:
                user_id = conn.get("user_id", "")
                telegram_id = conn.get("telegram_user_id")

                if not telegram_id:
                    continue

                # Check notification preferences
                prefs = await asyncio.get_event_loop().run_in_executor(
                    None, db.get_notification_prefs, user_id
                )
                if prefs and not prefs.get("backup_notifications", True):
                    # User has disabled notifications
                    continue

                # Send message via Telegram bot
                try:
                    bot_token = os.getenv("WATCHTELEGRAM_BOT_TOKEN", "")
                    if not bot_token:
                        errors.append("no_bot_token")
                        continue

                    import aiohttp as http_session
                    async with http_session.ClientSession() as session:
                        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                        data = {
                            "chat_id": telegram_id,
                            "text": message,
                            "parse_mode": "HTML",
                        }
                        async with session.post(url, json=data, timeout=10) as resp:
                            if resp.status == 200:
                                sent_to.append(user_id)
                            else:
                                error_text = await resp.text()
                                errors.append(f"{user_id}:{resp.status}")
                                self.logger.warning(
                                    "Telegram send failed",
                                    extra={
                                        "event": "queue_send_failed",
                                        "user_id": user_id,
                                        "status": resp.status,
                                        "error": error_text[:200],
                                    },
                                )
                except Exception as e:
                    errors.append(f"{user_id}:{str(e)[:50]}")

            if sent_to:
                self.logger.info(
                    "Notification sent to Telegram",
                    extra={
                        "event": "queue_notification_sent",
                        "event_type": event_type,
                        "sent_count": len(sent_to),
                        "error_count": len(errors),
                    },
                )
                return {"success": True, "sent_to": sent_to, "errors": errors}
            else:
                return {"success": False, "error": "no_sends_successful", "errors": errors}

        except Exception as e:
            self.logger.error(
                "Queue send callback error",
                extra={"event": "queue_callback_error", "error": str(e)},
            )
            return {"success": False, "error": str(e)}

    async def _watchdog_loop(self) -> None:
        """Send watchdog keep-alive to systemd."""
        while True:
            try:
                await asyncio.sleep(self.config.watchdog_interval)
                if HAS_SYSTEMD:
                    systemd.daemon.notify("WATCHDOG=1")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Watchdog error", extra={"event": "watchdog_error", "error": str(e)})

    def signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        self.logger.info("Received shutdown signal", extra={"event": "signal_received", "signal": signum})
        self._shutdown_event.set()

    async def run(self) -> None:
        """Main run loop."""
        await self.start()
        await self._shutdown_event.wait()
        await self.stop()


def load_env_file(path: Path) -> None:
    """Load environment variables from file."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    """Entry point."""
    # Load environment from secrets file
    secrets_path = Path("/opt/cloudvault/.secrets/watchtower.env")
    load_env_file(secrets_path)

    config = Config.from_env()
    service = WatchtowerService(config)

    # Setup signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, service.signal_handler, sig, None)

    try:
        loop.run_until_complete(service.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger("watchtower").error(
            "Service crashed",
            extra={"event": "service_crash", "error": str(e)}
        )
        return 1
    finally:
        loop.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())