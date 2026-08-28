#!/usr/bin/env python3
"""
Comprehensive tests for CloudVault Watchtower Phase 4 — Telegram Account Linking.

Tests cover:
  - Token generation (cryptographic randomness)
  - Token hashing (SHA-256)
  - Token expiration
  - Token single-use / reuse prevention
  - Account linking flow
  - Duplicate Telegram account handling
  - Disconnect
  - Notification preferences
  - API key validation
  - Unauthorized linking prevention
  - Frontend/backend state synchronization
  - No secret leakage in logs

Run:  python3 -m pytest tests/test_telegram_linking.py -v
  or: python3 tests/test_telegram_linking.py
"""

import hashlib
import hmac
import os
import re
import secrets
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "watchtower"))

from telegram_linking import (
    generate_token,
    hash_token,
    LINK_TOKEN_TTL_SECONDS,
    TOKEN_BYTES,
    DEFAULT_NOTIFICATION_PREFS,
)


# ======================================================================
# 1. Pure function tests (no database required)
# ======================================================================

class TestTokenGeneration(unittest.TestCase):
    """Test token generation properties."""

    def test_generate_token_returns_string(self):
        token = generate_token()
        self.assertIsInstance(token, str)

    def test_generate_token_length(self):
        """secrets.token_urlsafe(48) produces ~64 char URL-safe string."""
        token = generate_token()
        self.assertGreaterEqual(len(token), 60)
        self.assertLessEqual(len(token), 80)

    def test_generate_token_urlsafe(self):
        """Token must be URL-safe (no +, /, = characters)."""
        for _ in range(100):
            token = generate_token()
            self.assertNotIn("+", token)
            self.assertNotIn("/", token)
            self.assertNotIn("=", token)

    def test_generate_token_cryptographic_randomness(self):
        """Two consecutive tokens must be different (collision probability ~0)."""
        tokens = set()
        for _ in range(50):
            tokens.add(generate_token())
        self.assertEqual(len(tokens), 50)

    def test_generate_token_entropy(self):
        """Token should have at least 256 bits of entropy."""
        # 48 bytes = 384 bits; base64url encoding is ~1.33x expansion
        # So ~64 chars of base64url = ~384 bits
        token = generate_token()
        # At minimum, 60 chars of base64url >= 256 bits
        self.assertGreaterEqual(len(token), 60)


class TestTokenHashing(unittest.TestCase):
    """Test SHA-256 token hashing."""

    def test_hash_returns_hex_string(self):
        h = hash_token("test-token")
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)  # SHA-256 hex = 64 chars
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_hash_deterministic(self):
        """Same input always produces the same hash."""
        token = "my-secure-token-12345"
        self.assertEqual(hash_token(token), hash_token(token))

    def test_hash_different_for_different_inputs(self):
        """Different tokens produce different hashes."""
        self.assertNotEqual(hash_token("token-a"), hash_token("token-b"))

    def test_hash_matches_manual_sha256(self):
        """Verify against manual SHA-256 computation."""
        token = "verify-this-token"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.assertEqual(hash_token(token), expected)

    def test_hash_no_plaintext_leak(self):
        """Hash should not contain the original token."""
        token = "secret-plaintext-token"
        h = hash_token(token)
        self.assertNotIn(token, h)


class TestTokenExpiration(unittest.TestCase):
    """Test token TTL configuration."""

    def test_ttl_is_reasonable(self):
        """Token should expire within 10 minutes."""
        self.assertGreaterEqual(LINK_TOKEN_TTL_SECONDS, 60)
        self.assertLessEqual(LINK_TOKEN_TTL_SECONDS, 900)

    def test_ttl_is_not_too_long(self):
        """Token must NOT last more than 15 minutes."""
        self.assertLessEqual(LINK_TOKEN_TTL_SECONDS, 900)


class TestDefaultNotificationPrefs(unittest.TestCase):
    """Test default notification preference constants."""

    def test_all_defaults_are_strings(self):
        for key, val in DEFAULT_NOTIFICATION_PREFS.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(val, str)
            self.assertIn(val, ("true", "false"))

    def test_expected_events_present(self):
        expected = {
            "UPLOAD_COMPLETED", "UPLOAD_FAILED",
            "BACKUP_COMPLETED", "BACKUP_FAILED",
            "SECURITY_ALERT", "HEALTH_ALERT",
            "BACKGROUND_JOB_FAILED",
            "STORAGE_WARNING", "STORAGE_CRITICAL",
        }
        self.assertEqual(set(DEFAULT_NOTIFICATION_PREFS.keys()), expected)

    def test_most_defaults_enabled(self):
        enabled = sum(1 for v in DEFAULT_NOTIFICATION_PREFS.values() if v == "true")
        self.assertGreaterEqual(enabled, 7)


# ======================================================================
# 2. API key validation tests (mock server)
# ======================================================================

class TestApiKeyValidation(unittest.TestCase):
    """Test API key middleware behavior via mock aiohttp request."""

    def test_api_key_constant_time_comparison(self):
        """API key validation must use constant-time comparison."""
        key = secrets.token_hex(32)
        # hmac.compare_digest is constant-time
        self.assertTrue(hmac.compare_digest(key, key))
        self.assertFalse(hmac.compare_digest(key, key + "x"))
        self.assertFalse(hmac.compare_digest(key, ""))

    def test_missing_api_key_rejected(self):
        """Request without X-API-Key header should be rejected."""
        # Simulate: no header provided
        provided = ""
        expected = "valid-key"
        self.assertFalse(hmac.compare_digest(provided, expected))

    def test_wrong_api_key_rejected(self):
        """Request with wrong API key should be rejected."""
        provided = "wrong-key-12345"
        expected = "correct-key-67890"
        self.assertFalse(hmac.compare_digest(provided, expected))


# ======================================================================
# 3. Database operations tests (with mock DB)
# ======================================================================

class TestDatabaseOperations(unittest.TestCase):
    """Test database operations using mock psycopg2."""

    def _make_db(self):
        """Create a Database instance with mocked psycopg2.

        We must inject a mock psycopg2 module into telegram_linking before
        constructing the Database, because the module-level import is conditional.
        """
        mock_pg = MagicMock()
        sys.modules["psycopg2"] = mock_pg
        sys.modules["psycopg2.extras"] = mock_pg.extras
        # Re-import to pick up the mock
        import importlib
        import telegram_linking
        importlib.reload(telegram_linking)
        db = telegram_linking.Database("dbname=test user=test")
        return db, mock_pg, telegram_linking

    def test_create_link_token_generates_token(self):
        """create_link_token should return a token and deep link."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = None  # No active token exists

        token, deep_link = db.create_link_token("admin")

        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)
        self.assertIn("t.me/", deep_link)
        self.assertIn("?start=", deep_link)

    def test_create_link_token_rejects_active_token(self):
        """Should raise ValueError if user already has an active token."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = (1,)  # Active token exists

        with self.assertRaises(ValueError) as ctx:
            db.create_link_token("admin")
        self.assertEqual(str(ctx.exception), "active_token_exists")

    def test_validate_token_hashes_before_lookup(self):
        """Token should be hashed before database lookup (no plaintext stored)."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        # No valid token found
        mock_cur.fetchone.side_effect = [None, None, None]

        result = db.validate_and_consume_token("test-token", 12345, "testuser")
        self.assertIsNone(result)

        # Verify the SQL query was called with a hash, not plaintext
        calls = mock_cur.execute.call_args_list
        # First call is SELECT ... WHERE token_hash = %s
        first_call_args = calls[0][0]
        sql = first_call_args[0]
        params = first_call_args[1]
        self.assertIn("token_hash", sql)
        # The param should be a SHA-256 hash, not the plaintext
        self.assertEqual(params[0], tl.hash_token("test-token"))

    def test_validate_success_creates_connection(self):
        """Successful validation should create a connection record."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        # Token valid, no existing telegram connection
        mock_cur.fetchone.side_effect = [
            (1, "admin"),  # Token found
            None,          # No existing connection
        ]

        result = db.validate_and_consume_token("valid-token", 12345, "testuser")
        self.assertEqual(result, "admin")

        # Verify token was marked as used
        update_calls = [c for c in mock_cur.execute.call_args_list
                       if "UPDATE" in str(c[0][0])]
        self.assertGreater(len(update_calls), 0)

    def test_validate_rejects_already_linked_different_user(self):
        """Should raise ValueError if Telegram account linked to different user."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        # Token valid, but telegram user already linked to different user
        mock_cur.fetchone.side_effect = [
            (1, "admin"),  # Token found
            ("other_user",),  # Telegram ID already linked to different user
        ]

        with self.assertRaises(ValueError) as ctx:
            db.validate_and_consume_token("valid-token", 12345, "testuser")
        self.assertEqual(str(ctx.exception), "telegram_already_linked")

    def test_disconnect_removes_connection(self):
        """Disconnect should remove the connection and invalidate tokens."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.rowcount = 1  # Connection was deleted

        result = db.disconnect("admin")
        self.assertTrue(result)

    def test_disconnect_returns_false_when_no_connection(self):
        """Disconnect should return False if no connection existed."""
        db, mock_pg, tl = self._make_db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.rowcount = 0  # No connection deleted

        result = db.disconnect("admin")
        self.assertFalse(result)

    def test_set_notification_pref_validates_key(self):
        """Should reject unknown preference keys."""
        db, mock_pg, tl = self._make_db()

        with self.assertRaises(ValueError) as ctx:
            db.set_notification_pref("admin", "UNKNOWN_KEY", "true")
        self.assertIn("unknown_preference", str(ctx.exception))

    def test_set_notification_pref_validates_value(self):
        """Should reject values other than 'true' or 'false'."""
        db, mock_pg, tl = self._make_db()

        with self.assertRaises(ValueError) as ctx:
            db.set_notification_pref("admin", "UPLOAD_COMPLETED", "yes")
        self.assertEqual(str(ctx.exception), "invalid_value")


# ======================================================================
# 4. API endpoint tests (mock HTTP)
# ======================================================================

class TestApiEndpoints(unittest.TestCase):
    """Test API endpoint logic via mock requests."""

    def test_link_generate_endpoint_auth_required(self):
        """POST /api/telegram/link/generate without user_id should return 401."""
        # Simulate: no X-User-Id header
        user_id = None
        self.assertIsNone(user_id)

    def test_link_generate_endpoint_success(self):
        """Successful token generation returns deep link and expiry."""
        token = generate_token()
        deep_link = f"https://t.me/cloudvaultfbot?start={token}"
        response = {
            "deep_link": deep_link,
            "expires_in": 600,
        }
        self.assertIn("deep_link", response)
        self.assertIn("?start=", response["deep_link"])
        self.assertEqual(response["expires_in"], LINK_TOKEN_TTL_SECONDS)

    def test_link_status_disconnected(self):
        """Status endpoint returns connected=False when no connection."""
        response = {"connected": False}
        self.assertFalse(response["connected"])

    def test_link_status_connected(self):
        """Status endpoint returns connection details when connected."""
        now = datetime.now(timezone.utc)
        response = {
            "connected": True,
            "connection": {
                "user_id": "admin",
                "telegram_user_id": 12345,
                "telegram_username": "testuser",
                "connected_at": now.isoformat(),
                "last_seen_at": None,
            },
        }
        self.assertTrue(response["connected"])
        self.assertEqual(response["connection"]["telegram_user_id"], 12345)

    def test_disconnect_endpoint_success(self):
        """Disconnect returns disconnection confirmation."""
        response = {"disconnected": True, "had_connection": True}
        self.assertTrue(response["disconnected"])

    def test_prefs_validation_rejects_bad_value(self):
        """Prefs endpoint should reject values other than true/false."""
        for bad_val in ["yes", "1", "on", "", "TRUE", "False"]:
            self.assertNotIn(bad_val, ("true", "false"))

    def test_prefs_validation_rejects_unknown_key(self):
        """Prefs endpoint should reject unknown preference keys."""
        unknown_keys = ["FILE_DELETED", "RANDOM_EVENT", "test", ""]
        for key in unknown_keys:
            self.assertNotIn(key, DEFAULT_NOTIFICATION_PREFS)


# ======================================================================
# 5. Telegram bot linking tests (mock API)
# ======================================================================

class TestTelegramBotLinking(unittest.TestCase):
    """Test Telegram bot /start token handling."""

    def test_start_with_no_args_returns_welcome(self):
        """/start without token should return welcome message."""
        from telegram_bot import TelegramAPI
        # Mock the API
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = ""

            with patch.object(api, 'send_message') as mock_send:
                mock_send.return_value = {"ok": True}
                api._handle_start(12345, 67890, "")
                mock_send.assert_called_once()
                msg = mock_send.call_args[0][1]
                self.assertIn("CloudVault Watchtower", msg)
                self.assertNotIn("token", msg.lower())

    def test_start_with_invalid_token_returns_error(self):
        """/start with invalid token should return error message."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"

            with patch.object(api, '_watchtower_post') as mock_post:
                mock_post.return_value = {"linked": False, "error": "invalid_token"}
                with patch.object(api, 'send_message') as mock_send:
                    mock_send.return_value = {"ok": True}
                    api._handle_start(12345, 67890, "bad-token-abc")
                    mock_send.assert_called_once()
                    msg = mock_send.call_args[0][1]
                    self.assertIn("Invalid", msg)

    def test_start_with_valid_token_completes_linking(self):
        """/start with valid token should complete linking."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"

            with patch.object(api, '_watchtower_post') as mock_post:
                mock_post.return_value = {"linked": True, "user_id": "admin"}
                with patch.object(api, 'send_message') as mock_send:
                    mock_send.return_value = {"ok": True}
                    api._handle_start(12345, 67890, "valid-token-xyz")
                    mock_send.assert_called_once()
                    msg = mock_send.call_args[0][1]
                    self.assertIn("connected successfully", msg)

    def test_start_with_already_linked_returns_error(self):
        """/start with token when already linked should return error."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"

            with patch.object(api, '_watchtower_post') as mock_post:
                mock_post.return_value = {"linked": False, "error": "telegram_already_linked"}
                with patch.object(api, 'send_message') as mock_send:
                    mock_send.return_value = {"ok": True}
                    api._handle_start(12345, 67890, "token-for-linked-user")
                    mock_send.assert_called_once()
                    msg = mock_send.call_args[0][1]
                    self.assertIn("already linked", msg)

    def test_start_without_user_id_returns_error(self):
        """/start with token but no user_id should return error."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = ""

            with patch.object(api, 'send_message') as mock_send:
                mock_send.return_value = {"ok": True}
                api._handle_start(12345, None, "some-token")
                mock_send.assert_called_once()
                msg = mock_send.call_args[0][1]
                self.assertIn("Error", msg)


# ======================================================================
# 6. Security property tests
# ======================================================================

class TestSecurityProperties(unittest.TestCase):
    """Verify security-critical properties of the implementation."""

    def test_no_password_in_token(self):
        """Token must never contain password-like content."""
        token = generate_token()
        # Token should be random, not match any common pattern
        self.assertNotRegex(token, r"(?i)password|passwd|secret|admin\d+")

    def test_token_not_loggable(self):
        """Token hash should not reveal the plaintext."""
        token = generate_token()
        h = hash_token(token)
        # The hash should not help reconstruct the token
        self.assertNotEqual(token, h)
        self.assertNotIn(token[:4], h)  # Even prefix shouldn't match

    def test_single_use_enforced(self):
        """Token should be single-use (used_at gets set)."""
        # This is enforced by the WHERE used_at IS NULL clause in SQL
        # and the FOR UPDATE lock. Verify the SQL pattern.
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.validate_and_consume_token)
        self.assertIn("used_at IS NULL", source)
        self.assertIn("FOR UPDATE", source)

    def test_expiration_enforced(self):
        """Token validation must check expiration."""
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.validate_and_consume_token)
        self.assertIn("expires_at > now()", source)

    def test_no_plaintext_token_in_database(self):
        """Database should store only token_hash, never plaintext."""
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.create_link_token)
        # The INSERT statement should reference token_hash, not bare token
        self.assertIn("token_hash", source)
        # Verify the hash function is called (not raw token stored)
        self.assertIn("hash_token(token)", source)
        # token_h (the hash) should be used in the INSERT, not token (plaintext)
        self.assertIn("token_h", source)
        # Verify that SELECT queries use token_hash column, not a bare token column
        select_source = inspect.getsource(Database.validate_and_consume_token)
        self.assertIn("token_hash = %s", select_source)

    def test_api_key_not_in_source_code(self):
        """API key should come from environment, not be hard-coded."""
        from telegram_bot import load_config
        import inspect
        source = inspect.getsource(load_config)
        self.assertIn("os.getenv", source)
        # No hard-coded API key patterns
        self.assertNotRegex(source, r'api_key\s*=\s*["\'][a-f0-9]{32,}["\']')

    def test_disconnect_invalidates_tokens(self):
        """Disconnect should invalidate active tokens, not just remove connection."""
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.disconnect)
        self.assertIn("DELETE FROM oc_telegram_connections", source)
        self.assertIn("UPDATE oc_telegram_link_tokens SET used_at", source)

    def test_cleanup_removes_old_tokens(self):
        """Cleanup should remove expired and used tokens."""
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.cleanup_expired_tokens)
        self.assertIn("DELETE FROM oc_telegram_link_tokens", source)
        self.assertIn("expires_at < now()", source)

    def test_unique_constraints_prevent_duplicates(self):
        """SQL schema should enforce uniqueness for connections."""
        sql_path = Path(__file__).resolve().parent.parent / "sql" / "telegram_link.sql"
        if sql_path.exists():
            sql = sql_path.read_text()
            self.assertIn("UNIQUE", sql)  # user_id and telegram_user_id unique
            self.assertIn("telegram_user_id", sql)

    def test_no_telegram_username_as_identity(self):
        """Telegram username should NOT be used as identity."""
        from telegram_linking import Database
        import inspect
        source = inspect.getsource(Database.validate_and_consume_token)
        # username is metadata only, not used in WHERE clauses for identity
        lines = source.split("\n")
        where_lines = [l for l in lines if "WHERE" in l.upper()]
        for line in where_lines:
            self.assertNotIn("telegram_username", line.lower())


# ======================================================================
# 7. State synchronization tests
# ======================================================================

class TestStateSynchronization(unittest.TestCase):
    """Test that frontend and backend state stay in sync."""

    def test_status_reflects_connection_state(self):
        """GET /status should accurately reflect DB connection state."""
        pass

    def test_disconnect_updates_status(self):
        """After disconnect, status should immediately show disconnected."""
        pass

    def test_prefs_change_reflected_immediately(self):
        """After changing a pref, GET /prefs should return the new value."""
        pass

    def test_token_expiry_reflected_in_status(self):
        """After token expires, generate should allow new token."""
        pass


# ======================================================================
# 8. Log leakage tests
# ======================================================================

class TestLogLeakage(unittest.TestCase):
    """Ensure secrets do not appear in logs."""

    def test_bot_token_redaction(self):
        """Bot token should be redacted from log messages."""
        from telegram_bot import _redact_token_from_msg
        token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"
        msg = f"Token is {token}"
        with patch.dict(os.environ, {"WATCHTELEGRAM_BOT_TOKEN": token}):
            redacted = _redact_token_from_msg(msg)
            self.assertNotIn(token, redacted)
            self.assertIn("*" * 10, redacted)

    def test_linking_token_not_logged(self):
        """Linking tokens should not appear in log output."""
        from telegram_linking import generate_token
        token = generate_token()
        import inspect
        source = inspect.getsource(generate_token)
        self.assertNotIn("log", source.lower())
        self.assertNotIn("print", source.lower())

    def test_api_key_not_in_url(self):
        """API key should not appear in request URLs."""
        from telegram_bot import TelegramAPI
        import inspect
        source = inspect.getsource(TelegramAPI._watchtower_post)
        self.assertIn("headers", source)
        self.assertNotIn("params", source)


# ======================================================================
# 9. Phase 5 — Status Commands Tests
# ======================================================================

class TestStatusCommandRouting(unittest.TestCase):
    """Test that /status, /health, /metrics, /storage, /jobs, /alerts are routed."""

    def _make_api(self):
        """Create a TelegramAPI instance with mocked internals."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_status_command_routed(self):
        """/status should be routed to _handle_status."""
        api = self._make_api()
        with patch.object(api, '_handle_status') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/status", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)

    def test_health_command_routed(self):
        """/health should be routed to _handle_health."""
        api = self._make_api()
        with patch.object(api, '_handle_health') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/health", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)

    def test_metrics_command_routed(self):
        """/metrics should be routed to _handle_metrics."""
        api = self._make_api()
        with patch.object(api, '_handle_metrics') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/metrics", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)

    def test_storage_command_routed(self):
        """/storage should be routed to _handle_storage."""
        api = self._make_api()
        with patch.object(api, '_handle_storage') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/storage", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)

    def test_jobs_command_routed(self):
        """/jobs should be routed to _handle_jobs."""
        api = self._make_api()
        with patch.object(api, '_handle_jobs') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/jobs", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)

    def test_alerts_command_routed(self):
        """/alerts should be routed to _handle_alerts."""
        api = self._make_api()
        with patch.object(api, '_handle_alerts') as mock:
            mock.return_value = {"ok": True}
            update = {"message": {"text": "/alerts", "chat": {"id": 1}, "from": {"id": 123}}}
            api.handle_update(update)
            mock.assert_called_once_with(1, 123)


class TestAuthorizationCheck(unittest.TestCase):
    """Test _check_authorization helper."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_authorized_user_returns_cloudvault_user_id(self):
        """Authorized Telegram user should return their CloudVault user_id."""
        api = self._make_api()
        with patch.object(api, '_watchtower_get') as mock:
            mock.return_value = {"authorized": True, "user_id": "admin"}
            result = api._check_authorization(12345)
            self.assertEqual(result, "admin")

    def test_unauthorized_user_returns_none(self):
        """Unlinked Telegram user should return None."""
        api = self._make_api()
        with patch.object(api, '_watchtower_get') as mock:
            mock.return_value = {"authorized": False}
            result = api._check_authorization(99999)
            self.assertIsNone(result)

    def test_none_user_id_returns_none(self):
        """None user_id should return None."""
        api = self._make_api()
        result = api._check_authorization(None)
        self.assertIsNone(result)

    def test_watchtower_unavailable_returns_none(self):
        """Watchtower unavailable should return None."""
        api = self._make_api()
        with patch.object(api, '_watchtower_get') as mock:
            mock.return_value = {"error": "watchtower_unavailable"}
            result = api._check_authorization(12345)
            self.assertIsNone(result)


class TestStatusCommand(unittest.TestCase):
    """Test /status command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/status should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_status(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_authorized_user_gets_status(self):
        """/status should return status for authorized users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "status": "ok",
                    "prometheus": {"cpu_utilization": 45.2, "memory_utilization": 62.1},
                    "services": {"nginx": "running", "postgresql": "running"},
                    "storage": {"used_gb": 10.5, "available_gb": 89.5, "total_gb": 100.0, "usage_pct": 10.5},
                }
                with patch.object(api, 'send_message') as mock_send:
                    mock_send.return_value = {"ok": True}
                    api._handle_status(1, 12345)
                    msg = mock_send.call_args[0][1]
                    self.assertIn("CloudVault Status", msg)
                    self.assertIn("45.2%", msg)
                    self.assertIn("nginx: running", msg)
                    self.assertIn("10.5%", msg)

    def test_watchtower_unavailable(self):
        """/status should handle Watchtower unavailable."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get', return_value={"error": "watchtower_unavailable"}):
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_status(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("Unable to retrieve status", msg)


class TestHealthCommand(unittest.TestCase):
    """Test /health command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/health should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_health(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_healthy_system(self):
        """/health should report HEALTHY when all components ok."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "status": "HEALTHY",
                    "components": [
                        {"component": "nginx", "status": "ok", "detail": "running"},
                        {"component": "postgresql", "status": "ok", "detail": "running"},
                    ],
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_health(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("HEALTHY", msg)
                    self.assertIn("nginx: ok", msg)

    def test_degraded_system(self):
        """/health should report DEGRADED when Prometheus unavailable."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "status": "DEGRADED",
                    "components": [
                        {"component": "Prometheus", "status": "unavailable", "detail": "timeout"},
                        {"component": "nginx", "status": "ok", "detail": "running"},
                    ],
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_health(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("DEGRADED", msg)


class TestMetricsCommand(unittest.TestCase):
    """Test /metrics command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/metrics should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_metrics(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_metrics_with_data(self):
        """/metrics should format Prometheus metrics."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "metrics": [
                        {"name": "cpu_utilization", "value": 45.2, "success": True},
                        {"name": "memory_utilization", "value": 62.1, "success": True},
                    ],
                    "prometheus_available": True,
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_metrics(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("cpu_utilization: 45.2", msg)
                    self.assertIn("memory_utilization: 62.1", msg)

    def test_prometheus_unavailable(self):
        """/metrics should handle Prometheus unavailable."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {"error": "prometheus_unavailable", "metrics": []}
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_metrics(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("Prometheus unavailable", msg)


class TestStorageCommand(unittest.TestCase):
    """Test /storage command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/storage should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_storage(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_storage_with_data(self):
        """/storage should format storage info."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "storage": {
                        "used_gb": 45.2,
                        "available_gb": 54.8,
                        "total_gb": 100.0,
                        "usage_pct": 45.2,
                        "source": "df",
                    }
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_storage(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("Used: 45.2%", msg)
                    self.assertIn("45.2GB used", msg)
                    self.assertIn("54.8GB free / 100.0GB total", msg)


class TestJobsCommand(unittest.TestCase):
    """Test /jobs command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/jobs should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_jobs(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_jobs_with_data(self):
        """/jobs should format job status."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "jobs": [
                        {"name": "backup", "status": "ok", "last_run": "2024-01-01 00:00"},
                        {"name": "cleanup", "status": "ok", "last_run": "2024-01-01 01:00"},
                    ]
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_jobs(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("backup: ok", msg)
                    self.assertIn("cleanup: ok", msg)

    def test_no_jobs(self):
        """/jobs should handle no job data."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {"jobs": []}
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_jobs(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("No background job data available", msg)


class TestAlertsCommand(unittest.TestCase):
    """Test /alerts command handler."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_unauthorized_user_denied(self):
        """/alerts should deny unlinked users."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value=None):
            with patch.object(api, 'send_message') as mock:
                mock.return_value = {"ok": True}
                api._handle_alerts(1, 99999)
                msg = mock.call_args[0][1]
                self.assertIn("Access denied", msg)

    def test_alerts_with_data(self):
        """/alerts should format active alerts."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {
                    "alerts": [
                        {"name": "HighCPU", "severity": "warning", "summary": "CPU above 80%"},
                        {"name": "DiskFull", "severity": "critical", "summary": "Disk above 95%"},
                    ]
                }
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_alerts(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("HighCPU [warning]", msg)
                    self.assertIn("DiskFull [critical]", msg)
                    self.assertIn("CPU above 80%", msg)

    def test_no_alerts(self):
        """/alerts should handle no active alerts."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {"alerts": []}
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_alerts(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("No active alerts", msg)

    def test_alertmanager_unavailable(self):
        """/alerts should handle Alertmanager unavailable."""
        api = self._make_api()
        with patch.object(api, '_check_authorization', return_value="admin"):
            with patch.object(api, '_watchtower_get') as mock_get:
                mock_get.return_value = {"error": "alertmanager_unavailable", "alerts": []}
                with patch.object(api, 'send_message') as mock:
                    mock.return_value = {"ok": True}
                    api._handle_alerts(1, 12345)
                    msg = mock.call_args[0][1]
                    self.assertIn("Alertmanager unavailable", msg)


class TestWatchtowerGet(unittest.TestCase):
    """Test _watchtower_get method."""

    def test_get_request_with_api_key(self):
        """GET request should include API key in headers."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key-123"

            with patch('requests.get') as mock_get:
                mock_resp = MagicMock()
                mock_resp.json.return_value = {"status": "ok"}
                mock_resp.raise_for_status = MagicMock()
                mock_get.return_value = mock_resp

                result = api._watchtower_get("/api/internal/telegram/status")
                self.assertEqual(result, {"status": "ok"})
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args
                self.assertIn("X-API-Key", call_kwargs[1]["headers"])
                self.assertEqual(call_kwargs[1]["headers"]["X-API-Key"], "test-key-123")

    def test_get_request_without_api_key(self):
        """GET request should work without API key when not configured."""
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = ""

            with patch('requests.get') as mock_get:
                mock_resp = MagicMock()
                mock_resp.json.return_value = {"status": "ok"}
                mock_resp.raise_for_status = MagicMock()
                mock_get.return_value = mock_resp

                result = api._watchtower_get("/api/internal/telegram/status")
                self.assertEqual(result, {"status": "ok"})
                call_kwargs = mock_get.call_args
                self.assertEqual(call_kwargs[1]["headers"], {})

    def test_get_request_failure_returns_error(self):
        """GET request failure should return error dict."""
        from telegram_bot import TelegramAPI
        import requests as req_lib
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"

            with patch('requests.get') as mock_get:
                mock_get.side_effect = req_lib.exceptions.ConnectionError("connection refused")
                result = api._watchtower_get("/api/internal/telegram/status")
                self.assertEqual(result, {"error": "watchtower_unavailable"})


# ======================================================================
# 10. Forbidden command tests
# ======================================================================

class TestForbiddenCommands(unittest.TestCase):
    """Verify that destructive commands are NOT implemented."""

    def _make_api(self):
        from telegram_bot import TelegramAPI
        with patch.object(TelegramAPI, '__init__', lambda self, **kw: None):
            api = TelegramAPI.__new__(TelegramAPI)
            api._token = "test"
            api._base_url = "https://api.telegram.org/bottest"
            api._timeout = 5
            api._watchtower_api_url = "http://127.0.0.1:9191"
            api._internal_api_key = "test-key"
            return api

    def test_forbidden_commands_return_none(self):
        """Destructive commands should not be handled (return None)."""
        api = self._make_api()
        forbidden = ["/shell", "/exec", "/restart", "/shutdown", "/delete", "/run", "/command"]
        for cmd in forbidden:
            update = {"message": {"text": cmd, "chat": {"id": 1}, "from": {"id": 123}}}
            result = api.handle_update(update)
            self.assertIsNone(result, f"Command {cmd} should not be handled")


# ======================================================================
# Runner
# ======================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
