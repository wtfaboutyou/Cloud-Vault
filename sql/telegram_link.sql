-- CloudVault Watchtower — Telegram account linking (PostgreSQL 17)
--
-- Links Telegram accounts to existing CloudVault users.
-- Uses numeric Telegram user ID as the stable identity (never username).
--
-- Tables:
--   oc_telegram_link_tokens     — short-lived one-time linking tokens
--   oc_telegram_connections     — active CloudVault <-> Telegram associations
--   oc_telegram_notification_preferences — per-user notification toggles
--
-- Migration idempotency: every statement uses IF NOT EXISTS / ON CONFLICT.

BEGIN;

-- -------------------------------------------------------
-- 1. Linking tokens (short-lived, single-use, hashed)
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_telegram_link_tokens (
    id              bigserial    PRIMARY KEY,
    token_hash      varchar(128) NOT NULL UNIQUE,
    user_id         varchar(64)  NOT NULL,
    expires_at      timestamptz  NOT NULL,
    used_at         timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lttoken_hash      ON oc_telegram_link_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_lttoken_user      ON oc_telegram_link_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_lttoken_expires   ON oc_telegram_link_tokens (expires_at);

-- -------------------------------------------------------
-- 2. Active connections (one Telegram account per user)
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_telegram_connections (
    id                 bigserial    PRIMARY KEY,
    user_id            varchar(64)  NOT NULL UNIQUE,
    telegram_user_id   bigint       NOT NULL UNIQUE,
    telegram_username  varchar(64),
    connected_at       timestamptz  NOT NULL DEFAULT now(),
    last_seen_at       timestamptz
);

CREATE INDEX IF NOT EXISTS idx_tgconn_tgid ON oc_telegram_connections (telegram_user_id);

-- -------------------------------------------------------
-- 3. Notification preferences (follows oc_preferences pattern)
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_telegram_notification_preferences (
    userid      varchar(64)  NOT NULL,
    appid       varchar(32)  NOT NULL DEFAULT 'telegram',
    configkey   varchar(64)  NOT NULL,
    configvalue text         NOT NULL DEFAULT 'true',
    lazy        smallint     NOT NULL DEFAULT 0,
    type        smallint     NOT NULL DEFAULT 0,
    flags       integer      NOT NULL DEFAULT 0,
    indexed     varchar(64)  NOT NULL DEFAULT '',
    PRIMARY KEY (userid, appid, configkey)
);

CREATE INDEX IF NOT EXISTS idx_tgnotif_user ON oc_telegram_notification_preferences (userid);

COMMIT;
