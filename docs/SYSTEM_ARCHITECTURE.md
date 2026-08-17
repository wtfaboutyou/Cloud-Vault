# SYSTEM_ARCHITECTURE.md

Architecture, request flow, and data flow of the CloudVault platform.

---

## Overview

CloudVault is a reverse-proxy-first architecture. Nginx is the single entry point
for all HTTPS traffic. It terminates TLS 1.3, applies security headers, compression,
and rate limits, then hands PHP requests to PHP-FPM over a Unix socket. PHP runs
Nextcloud, which persists metadata to PostgreSQL, uses Redis for caching and file
locking, stores file blobs on the local filesystem, and asks ClamAV to scan uploads.

## Architecture Diagram

```mermaid
graph TD
    Client[Internet Clients / Mobile / Desktop] -->|HTTPS 443 / TLS 1.3| Nginx[Nginx Reverse Proxy & Gateway]

    subgraph Security & Hardening Layer
        UFW[UFW Firewall]
        Fail2ban[Fail2ban Intrusion Prevention]
        ClamAV[ClamAV Antivirus Daemon]
    end

    Fail2ban -. Monitor & Ban IPs .-> UFW
    Nginx -->|Unix Socket| PHP[PHP-FPM 8.4 Runtime]

    subgraph Application Layer
        PHP --> Nextcloud[Nextcloud Application Core]
        Nextcloud -. Scan Uploads .-> ClamAV
    end

    subgraph Storage & Cache Layer
        Nextcloud -->|SQL Metadata| Postgres[(PostgreSQL 17 Database)]
        Nextcloud -->|In-Memory Cache & File Lock| Redis[(Redis 7 Cache)]
        Nextcloud -->|Direct File Storage| Storage[/var/www/nextcloud/data]
    end

    subgraph Maintenance & Monitoring Layer
        Cron[Cron / Systemd Timers] -->|Run daily maintenance & backups| BackupScript[/opt/cloudvault/scripts/]
        Prometheus[Prometheus] -->|Collect Metrics| Grafana[Grafana Dashboard & Alerts]
    end
```

## Component Responsibilities

| Component | Role in the stack |
|-----------|-------------------|
| **Nginx** | TLS 1.3 termination, HTTP/2, Brotli/Gzip, security headers, rate limiting, large-upload buffering, static caching, reverse proxy to PHP-FPM. |
| **PHP-FPM 8.4** | Executes Nextcloud; tuned pool settings, APC cascade (APCu + Redis). |
| **Nextcloud** | Storage application: Web UI, WebDAV, Sync clients, sharing, apps. |
| **PostgreSQL 17** | All SQL metadata (users, shares, filecache). **Never stores binary file bytes.** |
| **Redis 7** | `memcache.local/d.s/global` + `memcaches locking` for sessions, query cache, and file locking. |
| **ClamAV** | Real-time AV scanning of uploads via `files_antivirus`. |
| **Fail2ban** | Watches Nginx + Nextcloud auth logs, bans offenders via UFW. |
| **Prometheus/Grafana** | Metric scraping, alerting, dashboards (loopback-bound). |

## Request Flow

```
Browser ──HTTPS──▶ Nginx
  │  (TLS 1.3, HSTS, rate limit, brotli/gzip)
  ├── static asset ──▶ disk (cached, immutable headers)
  └── PHP request ──▶ PHP-FPM socket ──▶ Nextcloud
                              │
                              ├──▶ Redis (session, query cache, locks)
                              ├──▶ PostgreSQL (metadata)
                              └──▶ /var/www/nextcloud/data (blobs, after ClamAV scan)
```

## Logging & Observability

| Log | Path |
|-----|------|
| Nginx access | `/var/log/nginx/access.log` |
| Nginx error | `/var/log/nginx/error.log` |
| PHP-FPM | `/var/log/php8.4-fpm.log`, slow log `/var/log/php8.4-fpm-slow.log` |
| Nextcloud | `/var/www/nextcloud/data/nextcloud.log` |
| PostgreSQL | `/var/log/postgresql/postgresql-17-main.log` |
| Fail2ban | `/var/log/fail2ban.log` |
| CloudVault scripts | `/var/log/cloudvault/*.log` |

## Service Readiness

Status of every critical service is reported by `/opt/cloudvault/scripts/healthcheck.sh`
(nginx, php-fpm, postgres, redis, fail2ban, clamav, ufw, disk, memory, SSL expiry).

## Directory Map

```
/etc/nginx/...                      web server config
/etc/php/8.4/fpm/...                PHP runtime + pool
/etc/postgresql/17/main/...         DB tuning + pg_hba
/etc/redis/redis.conf               cache/lock hardening
/etc/fail2ban/                      jails + filters
/var/www/nextcloud/                 the application
/var/www/nextcloud/data/            user files (blobs + nextcloud.log)
/opt/cloudvault/scripts/            operations scripts
/opt/cloudvault/backup/             encrypted archives
/var/log/cloudvault/                script logs
```

## Networking

| Port | Service | Bound to |
|------|---------|----------|
| 22 | SSH | public (restrict to admin IPs) |
| 80 | HTTP → HTTPS redirect | public |
| 443 | HTTPS (Nextcloud) | public |
| 6379 | Redis | 127.0.0.1 only |
| 9100 | node exporter | 127.0.0.1 only |
| 9113 | nginx stub_status | 127.0.0.1 only |
| 9121/9187 | redis/postgres exporters | 127.0.0.1 only |
| 9090/9093 | Prometheus / Alertmanager | 127.0.0.1 only |
| 3000 | Grafana | 127.0.0.1 (behind Nginx TLS) |