#!/usr/bin/env python3
"""
CloudVault Telegram Bot Foundation
Phase 3+4: Telegram foundation with /start, /help, and account linking.

Uses Telegram Bot API with webhook architecture integrated via
existing Nginx/TLS infrastructure.

Key security principles:
- Bot token from environment only, never hard-coded
- Token never logged or exposed to frontend
- Graceful failure if Telegram API unavailable
- Webhook via loopback-only HTTPS through existing Nginx
- Linking tokens validated server-side via Watchtower internal API
"""

import os
import sys
import json
import logging
import asyncio
import signal
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import requests

# Phase 9: Metrics import (soft dependency)
try:
    from watchtower_metrics import metrics as wt_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False

# ---------------------------------------------------------------------------
# Configuration loaded from environment (never hard-coded)
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN_ENV = "WATCHTELEGRAM_BOT_TOKEN"
TELEGRAM_WEBHOOK_URL_ENV = "WATCHTELEGRAM_WEBHOOK_URL"
TELEGRAM_ADMIN_USER_ID_ENV = "WATCHTELEGRAM_ADMIN_USER_ID"
WATCHTOWER_API_URL_ENV = "WATCHTOWER_API_URL"
WATCHTOWER_INTERNAL_API_KEY_ENV = "WATCHTOWER_INTERNAL_API_KEY"

DEFAULT_WEBHOOK_HOST = "127.0.0.1"
DEFAULT_WEBHOOK_PORT = 9192  # Separate from watchtower health endpoint (9191)


def load_config() -> Dict[str, Any]:
    """Load Telegram configuration from environment variables."""
    token = os.getenv(TELEGRAM_BOT_TOKEN_ENV)
    webhook_url = os.getenv(TELEGRAM_WEBHOOK_URL_ENV)
    admin_user_id_str = os.getenv(TELEGRAM_ADMIN_USER_ID_ENV)
    watchtower_api_url = os.getenv(WATCHTOWER_API_URL_ENV, "http://127.0.0.1:9191")
    internal_api_key = os.getenv(WATCHTOWER_INTERNAL_API_KEY_ENV, "")

    admin_user_id = None
    if admin_user_id_str is not None:
        try:
            admin_user_id = int(admin_user_id_str)
        except ValueError:
            admin_user_id = None

    config = {
        "bot_token": token,
        "webhook_url": webhook_url,
        "admin_user_id": admin_user_id,
        "webhook_host": DEFAULT_WEBHOOK_HOST,
        "webhook_port": DEFAULT_WEBHOOK_PORT,
        "watchtower_api_url": watchtower_api_url,
        "internal_api_key": internal_api_key,
    }

    return config


# ---------------------------------------------------------------------------
# Logging — never log the bot token
# ---------------------------------------------------------------------------

def _redact_token_from_msg(msg: str) -> str:
    """Redact bot token from a message string.

    Removes the bot token from log messages if present.
    Uses prefix/suffix masking to preserve partial visibility.
    """
    token = os.getenv(TELEGRAM_BOT_TOKEN_ENV, "")
    if not token:
        return msg
    # Mask: first 4 chars + asterisks + last 4 chars
    masked = token[:4] + "*" * (len(token) - 8) + token[-4:] if len(token) > 4 else "*" * len(token)
    if token in msg:
        # Replace only the first occurrence to avoid double-masking
        return msg.replace(token, masked, 1)
    return msg


def setup_logging() -> logging.Logger:
    """Configure watchtower Telegram logging (token never logged)."""

    class TokenSafeFormatter(logging.Formatter):
        """Formatter that redacts bot token from log output."""

        def format(self, record: logging.LogRecord) -> str:
            msg = super().format(record)
            return _redact_token_from_msg(msg)

    logger = logging.getLogger("cloudvault_telegram")
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = TokenSafeFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(handler)

    return logger


logger = setup_logging()

# ---------------------------------------------------------------------------
# Telegram Bot API helper
# ---------------------------------------------------------------------------

class TelegramAPI:
    """Thin wrapper around Telegram Bot API with error handling."""

    def __init__(self, token: str, timeout: int = 10,
                 watchtower_api_url: str = "http://127.0.0.1:9191",
                 internal_api_key: str = ""):
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout = timeout
        self._session: Optional[requests.Session] = None
        self._watchtower_api_url = watchtower_api_url.rstrip("/")
        self._internal_api_key = internal_api_key

    def _get(self, method: str, **params) -> Dict[str, Any]:
        """Make a GET request to Telegram API."""
        url = f"{self._base_url}/{method}"
        try:
            telegram_timeout = params.get("timeout", 0)
            http_timeout = max(self._timeout, int(telegram_timeout) + 5)
            resp = requests.get(url, params=params, timeout=http_timeout)
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                logger.warning(
                    "Telegram API error",
                    extra={"event": "telegram_api_error", "error": result},
                )
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Telegram API request failed",
                extra={"event": "telegram_api_request_failed", "error": str(e)},
            )
            return {"ok": False}

    def _post(self, method: str, json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request to Telegram API."""
        url = f"{self._base_url}/{method}"
        try:
            resp = requests.post(url, json=json_data, timeout=self._timeout)
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                logger.warning(
                    "Telegram API error",
                    extra={"event": "telegram_api_error", "error": result},
                )
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Telegram API request failed",
                extra={"event": "telegram_api_request_failed", "error": str(e)},
            )
            return {"ok": False}

    # ---- Bot commands ----

    def set_webhook(self, url: str) -> Dict[str, Any]:
        """Set the webhook URL for the bot."""
        return self._post("setWebhook", {"url": url})

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove the webhook and start polling."""
        return self._post("deleteWebhook")

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook configuration."""
        return self._get("getWebhookInfo")

    def send_message(
        self, chat_id: int, text: str, parse_mode: str = "Markdown"
    ) -> Dict[str, Any]:
        """Send a message to a chat."""
        return self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )

    # ---- Watchtower internal API ----------------------------------------

    def _watchtower_post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the Watchtower internal API with API key."""
        url = f"{self._watchtower_api_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self._internal_api_key:
            headers["X-API-Key"] = self._internal_api_key
        try:
            resp = requests.post(
                url, json=data, headers=headers, timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Watchtower API request failed",
                extra={"event": "watchtower_api_failed", "path": path, "error": str(e)},
            )
            return {"error": "watchtower_unavailable"}

    def _watchtower_get(self, path: str) -> Dict[str, Any]:
        """GET from the Watchtower internal API with API key."""
        url = f"{self._watchtower_api_url}{path}"
        headers = {}
        if self._internal_api_key:
            headers["X-API-Key"] = self._internal_api_key
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Watchtower API request failed",
                extra={"event": "watchtower_api_failed", "path": path, "error": str(e)},
            )
            return {"error": "watchtower_unavailable"}

    def _check_authorization(self, user_id: Optional[int]) -> Optional[str]:
        """Check if a Telegram user is authorized (linked to a CloudVault account).

        Returns the CloudVault user_id if authorized, None otherwise.
        """
        if not user_id:
            return None
        result = self._watchtower_get(
            f"/api/internal/telegram/check-authorization/{user_id}"
        )
        if result.get("authorized"):
            return result.get("user_id")
        return None

    # ---- Command handlers ----

    def handle_update(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single update from Telegram.

        Returns command result or None if not a recognized command.
        """
        if not update:
            return None

        message = update.get("message")
        if not message:
            return None

        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")

        if not chat_id or not text:
            return None

        # Handle /start
        if text.startswith("/start"):
            args = text[len("/start"):].strip()
            # Phase 9: Track command requests
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "start"})
            return self._handle_start(chat_id, user_id, args)

        # Handle /help
        if text.startswith("/help"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "help"})
            return self._handle_help(chat_id)

        # Handle /status
        if text.startswith("/status"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "status"})
            return self._handle_status(chat_id, user_id)

        # Handle /health
        if text.startswith("/health"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "health"})
            return self._handle_health(chat_id, user_id)

        # Handle /metrics
        if text.startswith("/metrics"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "metrics"})
            return self._handle_metrics(chat_id, user_id)

        # Handle /storage
        if text.startswith("/storage"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "storage"})
            return self._handle_storage(chat_id, user_id)

        # Handle /jobs
        if text.startswith("/jobs"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "jobs"})
            return self._handle_jobs(chat_id, user_id)

        # Handle /alerts
        if text.startswith("/alerts"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "alerts"})
            return self._handle_alerts(chat_id, user_id)

        # Handle /alert (alias for /alerts)
        if text.startswith("/alert"):
            if HAS_METRICS:
                wt_metrics.command_requests_total.inc(labels={"command": "alert"})
            return self._handle_alerts(chat_id, user_id)

        # Unknown command — ignore silently
        return None

    # ---- Command handlers implementation ----

    def _handle_start(self, chat_id: int, user_id: Optional[int], args: str) -> Dict[str, Any]:
        """Handle /start command — with Phase 4 token validation."""
        if args:
            # This is a linking token — validate through Watchtower API
            return self._handle_linking_token(chat_id, user_id, args.strip())

        # No token — regular welcome
        welcome = (
            "CloudVault Watchtower\n\n"
            "Bot is operational.\n\n"
            "Use /health to check system status,\n"
            "/status for operational summary,\n"
            "/metrics for resource metrics,\n"
            "or /help for the full command list.\n\n"
            "To link your CloudVault account, open the\n"
            "Telegram settings in CloudVault and click\n"
            "'Connect Telegram'."
        )
        return self.send_message(chat_id, welcome)

    def _handle_linking_token(
        self, chat_id: int, user_id: Optional[int], token: str
    ) -> Dict[str, Any]:
        """Validate a linking token and complete account association."""
        if not user_id:
            return self.send_message(
                chat_id,
                "Error: unable to identify your Telegram account.\n"
                "Please try again or contact your administrator."
            )

        # Call Watchtower internal API to validate token
        result = self._watchtower_post(
            "/api/internal/telegram/validate-token",
            {
                "token": token,
                "telegram_user_id": user_id,
                "telegram_username": None,  # Not used as identity
            },
        )

        if result.get("linked"):
            return self.send_message(
                chat_id,
                "CloudVault account connected successfully.\n\n"
                "You will now receive notifications for\n"
                "enabled events. Manage preferences in\n"
                "CloudVault Settings > Notifications > Telegram.\n\n"
                "Use /help to see available commands."
            )
        elif result.get("error") == "invalid_token":
            return self.send_message(
                chat_id,
                "Invalid or expired linking token.\n\n"
                "Please generate a new token from\n"
                "CloudVault Settings > Notifications > Telegram."
            )
        elif result.get("error") == "telegram_already_linked":
            return self.send_message(
                chat_id,
                "This Telegram account is already linked\n"
                "to a CloudVault account.\n\n"
                "To link to a different account, disconnect\n"
                "the current connection first in CloudVault\n"
                "Settings > Notifications > Telegram."
            )
        elif result.get("error") == "watchtower_unavailable":
            return self.send_message(
                chat_id,
                "Service temporarily unavailable.\n"
                "Please try again in a few moments."
            )
        else:
            return self.send_message(
                chat_id,
                "Linking failed. Please try again or\n"
                "contact your administrator."
            )

    def _handle_help(self, chat_id: int) -> Dict[str, Any]:
        """Handle /help command."""
        help_text = (
            "CloudVault Watchtower — Telegram Commands\n\n"
            "/start — Start or re-link Telegram bot\n"
            "/health — Check system health status\n"
            "/status — Operational summary\n"
            "/metrics — Resource metrics (CPU, memory, disk)\n"
            "/storage — Storage usage information\n"
            "/jobs — Background job status\n"
            "/alerts — Active alerts\n"
            "/alert — Alias for /alerts\n\n"
            "Note: This bot integrates with your existing Prometheus/Grafana\n"
            "infrastructure. No data is stored in Telegram."
        )

        return self.send_message(chat_id, help_text)

    # ----------------------------------------------------------------
    # Phase 5 — Status Commands
    # ----------------------------------------------------------------

    def _handle_status(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /status command — operational summary."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/status")
        if result.get("error"):
            return self.send_message(
                chat_id,
                "Unable to retrieve status. Try again later."
            )

        # Format status message
        status = result.get("status", "unknown")
        prometheus = result.get("prometheus", {})
        services = result.get("services", {})
        storage = result.get("storage", {})

        lines = ["CloudVault Status\n"]
        lines.append(f"Status: {status.upper()}\n")

        # CPU and Memory
        if prometheus:
            cpu = prometheus.get("cpu_utilization")
            mem = prometheus.get("memory_utilization")
            if cpu is not None:
                lines.append(f"CPU: {cpu:.1f}%")
            if mem is not None:
                lines.append(f"Memory: {mem:.1f}%")
            lines.append("")

        # Services
        if services and "error" not in services:
            lines.append("Services:")
            for svc, state in services.items():
                icon = "+" if state == "running" else "!"
                lines.append(f"  {icon} {svc}: {state}")
            lines.append("")

        # Storage
        if storage and "error" not in storage:
            usage_pct = storage.get("usage_pct")
            available_gb = storage.get("available_gb")
            total_gb = storage.get("total_gb")
            if usage_pct is not None:
                lines.append(f"Storage: {usage_pct}% used")
                if available_gb is not None and total_gb is not None:
                    lines.append(f"  {available_gb:.1f}GB free / {total_gb:.1f}GB total")

        return self.send_message(chat_id, "\n".join(lines))

    def _handle_health(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /health command — system health status."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/health")
        if result.get("error"):
            return self.send_message(
                chat_id,
                "Unable to retrieve health status. Try again later."
            )

        overall = result.get("status", "UNKNOWN")
        components = result.get("components", [])

        lines = ["System Health\n"]
        lines.append(f"Overall: {overall}\n")

        if components:
            lines.append("Components:")
            for comp in components:
                name = comp.get("component", "unknown")
                status = comp.get("status", "unknown")
                detail = comp.get("detail", "")
                icon = "+" if status == "ok" else ("~" if status == "unavailable" else "!")
                lines.append(f"  {icon} {name}: {status}")
                if detail:
                    lines.append(f"    {detail}")

        return self.send_message(chat_id, "\n".join(lines))

    def _handle_metrics(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /metrics command — resource metrics."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/metrics")
        if result.get("error"):
            if result.get("error") == "prometheus_unavailable":
                return self.send_message(
                    chat_id,
                    "Prometheus unavailable. Metrics cannot be retrieved."
                )
            return self.send_message(
                chat_id,
                "Unable to retrieve metrics. Try again later."
            )

        metrics = result.get("metrics", [])

        lines = ["Resource Metrics\n"]

        for metric in metrics:
            name = metric.get("name", "")
            value = metric.get("value")
            success = metric.get("success", False)

            if success and value is not None:
                if isinstance(value, (int, float)):
                    lines.append(f"{name}: {value:.1f}")
                else:
                    lines.append(f"{name}: {value}")
            else:
                error = metric.get("error", "unavailable")
                lines.append(f"{name}: {error}")

        if not metrics:
            lines.append("No metrics available")

        return self.send_message(chat_id, "\n".join(lines))

    def _handle_storage(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /storage command — storage usage."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/storage")
        if result.get("error"):
            return self.send_message(
                chat_id,
                "Unable to retrieve storage info. Try again later."
            )

        storage = result.get("storage", {})
        if storage.get("error"):
            return self.send_message(
                chat_id,
                f"Storage info unavailable: {storage['error']}"
            )

        used_gb = storage.get("used_gb")
        available_gb = storage.get("available_gb")
        total_gb = storage.get("total_gb")
        usage_pct = storage.get("usage_pct")

        lines = ["Storage Usage\n"]
        if usage_pct is not None:
            lines.append(f"Used: {usage_pct}%")
        if used_gb is not None:
            lines.append(f"  {used_gb:.1f}GB used")
        if available_gb is not None and total_gb is not None:
            lines.append(f"  {available_gb:.1f}GB free / {total_gb:.1f}GB total")

        source = storage.get("source")
        if source and source != "unknown":
            lines.append(f"\nSource: {source}")

        return self.send_message(chat_id, "\n".join(lines))

    def _handle_jobs(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /jobs command — background job status."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/jobs")
        if result.get("error"):
            return self.send_message(
                chat_id,
                "Unable to retrieve job status. Try again later."
            )

        jobs = result.get("jobs", [])

        lines = ["Background Jobs\n"]

        if jobs:
            for job in jobs:
                name = job.get("name", "unknown")
                status = job.get("status", "unknown")
                last_run = job.get("last_run")
                icon = "+" if status == "ok" else "!"
                lines.append(f"{icon} {name}: {status}")
                if last_run:
                    lines.append(f"  Last run: {last_run}")
        else:
            lines.append("No background job data available")

        return self.send_message(chat_id, "\n".join(lines))

    def _handle_alerts(self, chat_id: int, user_id: Optional[int]) -> Dict[str, Any]:
        """Handle /alerts command — active alerts."""
        # Check authorization
        cloudvault_user_id = self._check_authorization(user_id)
        if not cloudvault_user_id:
            return self.send_message(
                chat_id,
                "Access denied. Link your CloudVault account first.\n"
                "Use /start to begin linking."
            )

        result = self._watchtower_get("/api/internal/telegram/alerts")
        if result.get("error"):
            if result.get("error") == "alertmanager_unavailable":
                return self.send_message(
                    chat_id,
                    "Alertmanager unavailable. Alerts cannot be retrieved."
                )
            return self.send_message(
                chat_id,
                "Unable to retrieve alerts. Try again later."
            )

        alerts = result.get("alerts", [])

        lines = ["Active Alerts\n"]

        if alerts:
            for alert in alerts:
                name = alert.get("name", "unknown")
                severity = alert.get("severity", "unknown")
                summary = alert.get("summary", "")
                icon = "!" if severity == "critical" else "~"
                lines.append(f"{icon} {name} [{severity}]")
                if summary:
                    lines.append(f"  {summary}")
        else:
            lines.append("No active alerts")

        return self.send_message(chat_id, "\n".join(lines))


# ---------------------------------------------------------------------------
# Webhook server using aiohttp (integrated with existing watchtower)
# ---------------------------------------------------------------------------

async def handle_webhook_request(
    request_path: str, body: Dict[str, Any], api: TelegramAPI
) -> Optional[Dict[str, Any]]:
    """Handle an incoming webhook update from Telegram.

    Returns command result if a recognized command was processed.
    """
    if request_path == "/":
        # Telegram sends updates as JSON POST
        update = body
        return api.handle_update(update)
    return None


# ---------------------------------------------------------------------------
# Webhook server
# ---------------------------------------------------------------------------

async def run_polling(api: TelegramAPI) -> None:
    """Long-poll for Telegram updates (local network mode)."""
    import time

    offset = 0
    logger.info(
        "Telegram polling started",
        extra={"event": "telegram_polling_start"},
    )

    try:
        while True:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: api._get("getUpdates", offset=offset, timeout=30)
                )
                if result.get("ok") and result.get("result"):
                    for update in result["result"]:
                        offset = update["update_id"] + 1
                        await asyncio.get_event_loop().run_in_executor(
                            None, lambda u=update: api.handle_update(u)
                        )
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(
                    "Polling error: %s",
                    str(e),
                    extra={"event": "telegram_polling_error"},
                )
                await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info(
            "Telegram polling stopped",
            extra={"event": "telegram_polling_stop"},
        )


async def run_webhook_server(api: TelegramAPI, host: str, port: int) -> None:
    """Run a minimal HTTP server for Telegram webhooks.

    Binds to loopback only. Expected to be reverse-proxied by Nginx
    with TLS termination.
    """
    from aiohttp import web

    async def webhook_handler(request: web.Request) -> web.Response:
        """Handle incoming webhook POST from Telegram."""
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="invalid JSON")

        # Process the update
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: handle_webhook_request(request.path, body, api)
        )

        # Always return 200 OK to Telegram to prevent retries
        # The actual response content is informational
        if result:
            # Command was handled — still ACK
            pass

        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/", webhook_handler)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(
        "Telegram webhook server started",
        extra={"event": "telegram_webhook_start", "host": host, "port": port},
    )

    try:
        # Keep running — webhook server stays active
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        logger.info(
            "Telegram webhook server stopped",
            extra={"event": "telegram_webhook_stop"},
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point for Telegram bot foundation."""

    config = load_config()

    # Validate required configuration
    token = config["bot_token"]
    if not token:
        logger.error(
            "Telegram bot token not configured — set WATCHTELEGRAM_BOT_TOKEN environment variable",
            extra={"event": "telegram_missing_token"},
        )
        print(
            "ERROR: Telegram bot token not configured. "
            "Set WATCHTELEGRAM_BOT_TOKEN environment variable.",
            file=sys.stderr,
        )
        return 1

    # Validate admin user ID if configured
    admin_user_id = config["admin_user_id"]
    if admin_user_id is not None and admin_user_id <= 0:
        logger.warning(
            "Invalid admin user ID configured",
            extra={"event": "telegram_invalid_admin_id"},
        )

    # Initialize Telegram API client
    try:
        api = TelegramAPI(
            token=token,
            watchtower_api_url=config["watchtower_api_url"],
            internal_api_key=config["internal_api_key"],
        )
    except ValueError as e:
        logger.error(
            "Failed to initialize Telegram API: %s",
            str(e),
            extra={"event": "telegram_api_init_failed"},
        )
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Set up webhook if webhook URL is configured
    webhook_url = config["webhook_url"]
    if webhook_url:
        try:
            result = api.set_webhook(webhook_url)
            if result.get("ok"):
                logger.info(
                    "Telegram webhook set: %s",
                    webhook_url,
                    extra={"event": "telegram_webhook_set", "url": webhook_url},
                )
            else:
                logger.warning(
                    "Failed to set Telegram webhook: %s",
                    result,
                    extra={"event": "telegram_webhook_set_failed"},
                )
        except Exception as e:
            logger.warning(
                "Error setting Telegram webhook: %s",
                str(e),
                extra={"event": "telegram_webhook_set_error"},
            )

    # Log startup (token is NOT logged — only non-sensitive info)
    logger.info(
        "CloudVault Telegram Bot starting",
        extra={"event": "telegram_starting", "version": "1.0.0"},
    )

    # Determine mode: webhook or polling
    # Phase 3: webhook architecture integrated with existing Nginx/TLS
    use_webhook = os.getenv("WATCHTELEGRAM_USE_WEBHOOK", "true").lower() != "false"

    host = config["webhook_host"]
    port = config["webhook_port"]

    if use_webhook:
        # Webhook mode — server stays running, receives updates via Nginx
        try:
            asyncio.run(run_webhook_server(api, host, port))
        except KeyboardInterrupt:
            logger.info("Telegram bot shutting down via KeyboardInterrupt")
        except Exception as e:
            logger.error(
                "Telegram bot fatal error: %s",
                str(e),
                extra={"event": "telegram_fatal_error"},
            )
            return 1
    else:
        # Polling mode (fallback for testing / local network)
        logger.warning(
            "Webhook mode disabled, using short polling",
            extra={"event": "telegram_polling_mode"},
        )
        try:
            asyncio.run(run_polling(api))
        except KeyboardInterrupt:
            logger.info("Telegram bot shutting down via KeyboardInterrupt")
        except Exception as e:
            logger.error(
                "Telegram bot fatal error: %s",
                str(e),
                extra={"event": "telegram_fatal_error"},
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())