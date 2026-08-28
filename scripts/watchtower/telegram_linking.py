#!/usr/bin/env python3
"""
CloudVault Watchtower — Telegram Account Linking (Phase 4)

Secure token-based linking between CloudVault users and Telegram accounts.

Security properties:
  - Tokens are 48-byte cryptographically random (secrets.token_urlsafe)
  - Only SHA-256 hashes are stored in the database
  - Tokens expire after LINK_TOKEN_TTL_SECONDS (default 10 minutes)
  - Tokens are single-use; consumed atomically via UPDATE ... WHERE used_at IS NULL
  - Expired/used tokens are cleaned up periodically
  - No passwords transit through Telegram
  - Numeric Telegram user ID is the stable identity (never username)
"""

import os
import secrets
import hashlib
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

logger = logging.getLogger("watchtower")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LINK_TOKEN_TTL_SECONDS = 600  # 10 minutes
TOKEN_BYTES = 48             # 384 bits of entropy (URL-safe base64 = 64 chars)
CLEANUP_INTERVAL_SECONDS = 300  # run cleanup every 5 minutes

DEFAULT_NOTIFICATION_PREFS = {
    "UPLOAD_COMPLETED":  "true",
    "UPLOAD_FAILED":     "true",
    "BACKUP_COMPLETED":  "true",
    "BACKUP_FAILED":     "true",
    "SECURITY_ALERT":    "true",
    "HEALTH_ALERT":      "true",
    "BACKGROUND_JOB_FAILED": "true",
    "STORAGE_WARNING":   "true",
    "STORAGE_CRITICAL":  "true",
}


# ---------------------------------------------------------------------------
# Token helpers (pure functions, no I/O)
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """Generate a cryptographically secure linking token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hash of the plaintext token.  Stored in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------

class Database:
    """Synchronous PostgreSQL connection wrapper.

    Operations are fast (single-row reads/writes) so blocking calls are
    acceptable.  Callers in async contexts should use asyncio.to_thread().
    """

    def __init__(self, dsn: str):
        if not HAS_PSYCOPG2:
            raise RuntimeError("psycopg2 is required for Telegram linking")
        self._dsn = dsn

    def _connect(self):
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = False
        return conn

    # -- Tokens -----------------------------------------------------------

    def create_link_token(self, user_id: str) -> Tuple[str, str]:
        """Create a short-lived one-time linking token.

        Returns (plaintext_token, deep_link).
        Raises ValueError if user already has an active (unused, unexpired) token.
        """
        conn = self._connect()
        try:
            cur = conn.cursor()
            # Reject if user already has an active token
            cur.execute(
                "SELECT 1 FROM oc_telegram_link_tokens "
                "WHERE user_id = %s AND used_at IS NULL AND expires_at > now()",
                (user_id,),
            )
            if cur.fetchone():
                raise ValueError("active_token_exists")

            token = generate_token()
            token_h = hash_token(token)
            expires_at = _now() + timedelta(seconds=LINK_TOKEN_TTL_SECONDS)

            cur.execute(
                "INSERT INTO oc_telegram_link_tokens "
                "(token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)",
                (token_h, user_id, expires_at),
            )
            conn.commit()
            return token, f"https://t.me/{self._get_bot_username()}?start={token}"
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_bot_username(self) -> str:
        """Fetch bot username from environment.  Fallback to placeholder."""
        return os.getenv("WATCHTELEGRAM_BOT_USERNAME", "cloudvaultfbot")

    def validate_and_consume_token(
        self, token: str, telegram_user_id: int, telegram_username: Optional[str]
    ) -> Optional[str]:
        """Validate a linking token and create the connection.

        Returns the CloudVault user_id on success, None on failure.
        Atomically marks the token as used to prevent reuse.
        """
        token_h = hash_token(token)
        conn = self._connect()
        try:
            cur = conn.cursor()
            # Find valid token
            cur.execute(
                "SELECT id, user_id FROM oc_telegram_link_tokens "
                "WHERE token_hash = %s AND used_at IS NULL AND expires_at > now() "
                "FOR UPDATE",
                (token_h,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None

            token_id, user_id = row

            # Check if this Telegram user is already linked to ANY account
            cur.execute(
                "SELECT user_id FROM oc_telegram_connections "
                "WHERE telegram_user_id = %s",
                (telegram_user_id,),
            )
            existing = cur.fetchone()
            if existing:
                # Telegram account already linked to a (possibly different) user
                if existing[0] != user_id:
                    conn.rollback()
                    raise ValueError("telegram_already_linked")
                # Same user re-linking — allowed (update metadata)

            # Mark token as used
            cur.execute(
                "UPDATE oc_telegram_link_tokens SET used_at = now() WHERE id = %s",
                (token_id,),
            )

            # Upsert connection
            cur.execute(
                "INSERT INTO oc_telegram_connections "
                "(user_id, telegram_user_id, telegram_username, connected_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "  telegram_user_id = EXCLUDED.telegram_user_id, "
                "  telegram_username = EXCLUDED.telegram_username, "
                "  connected_at = now()",
                (user_id, telegram_user_id, telegram_username),
            )

            # Seed notification preferences if not present
            for key, default_val in DEFAULT_NOTIFICATION_PREFS.items():
                cur.execute(
                    "INSERT INTO oc_telegram_notification_preferences "
                    "(userid, appid, configkey, configvalue) "
                    "VALUES (%s, 'telegram', %s, %s) "
                    "ON CONFLICT (userid, appid, configkey) DO NOTHING",
                    (user_id, key, default_val),
                )

            conn.commit()
            return user_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Connection -------------------------------------------------------

    def get_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Return the active Telegram connection for a CloudVault user, or None."""
        conn = self._connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT user_id, telegram_user_id, telegram_username, "
                "       connected_at, last_seen_at "
                "FROM oc_telegram_connections WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_connection_by_telegram_id(
        self, telegram_user_id: int
    ) -> Optional[Dict[str, Any]]:
        """Return the active connection for a Telegram user ID, or None."""
        conn = self._connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT user_id, telegram_user_id, telegram_username, "
                "       connected_at, last_seen_at "
                "FROM oc_telegram_connections WHERE telegram_user_id = %s",
                (telegram_user_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_connections(self) -> List[Dict[str, Any]]:
        """Return all active Telegram connections for alert routing."""
        conn = self._connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT user_id, telegram_user_id, telegram_username, "
                "       connected_at, last_seen_at "
                "FROM oc_telegram_connections"
            )
            rows = cur.fetchall()
            conn.commit()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def disconnect(self, user_id: str) -> bool:
        """Remove Telegram connection and invalidate active tokens.

        Returns True if a connection was removed.
        """
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM oc_telegram_connections WHERE user_id = %s", (user_id,)
            )
            removed = cur.rowcount > 0
            # Invalidate any active linking tokens for this user
            cur.execute(
                "UPDATE oc_telegram_link_tokens SET used_at = now() "
                "WHERE user_id = %s AND used_at IS NULL",
                (user_id,),
            )
            conn.commit()
            return removed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Notification preferences -----------------------------------------

    def get_notification_prefs(self, user_id: str) -> Dict[str, str]:
        """Return all notification preferences for a user."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT configkey, configvalue "
                "FROM oc_telegram_notification_preferences "
                "WHERE userid = %s AND appid = 'telegram'",
                (user_id,),
            )
            prefs = {row[0]: row[1] for row in cur.fetchall()}
            conn.commit()
            # Merge with defaults so new event types appear automatically
            merged = dict(DEFAULT_NOTIFICATION_PREFS)
            merged.update(prefs)
            return merged
        finally:
            conn.close()

    def set_notification_pref(self, user_id: str, key: str, value: str) -> None:
        """Set a single notification preference."""
        if key not in DEFAULT_NOTIFICATION_PREFS:
            raise ValueError(f"unknown_preference:{key}")
        if value not in ("true", "false"):
            raise ValueError("invalid_value")
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO oc_telegram_notification_preferences "
                "(userid, appid, configkey, configvalue) "
                "VALUES (%s, 'telegram', %s, %s) "
                "ON CONFLICT (userid, appid, configkey) "
                "DO UPDATE SET configvalue = EXCLUDED.configvalue",
                (user_id, key, value),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Token cleanup ----------------------------------------------------

    def cleanup_expired_tokens(self) -> int:
        """Delete expired and used tokens.  Returns count deleted."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM oc_telegram_link_tokens "
                "WHERE expires_at < now() - interval '1 hour' "
                "OR (used_at IS NOT NULL AND used_at < now() - interval '1 hour')"
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Health -----------------------------------------------------------

    def check_health(self) -> bool:
        """Simple connectivity check."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()
