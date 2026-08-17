# PROJECT SPECIFICATION

## Project Name
**CloudVault**

---

# Project Overview

CloudVault is a self-hosted enterprise cloud storage platform built using Nextcloud natively on **Debian 13 (Trixie)**. The primary objective of this project is to demonstrate a production-ready, highly secure, and optimized web server architecture by implementing Nginx as the primary reverse proxy and web server with HTTPS (TLS 1.3), Brotli/Gzip Compression, Redis caching/locking, PostgreSQL database, PHP-FPM 8.4, Fail2ban intrusion protection, ClamAV antivirus scanning, and automated backup & monitoring.

This project focuses on server architecture, deployment, system administration, security, and performance optimization rather than developing a new cloud storage application. Nextcloud is used as the cloud storage application, while Nginx acts as the primary gateway responsible for traffic handling, SSL termination, security headers, rate limiting, and performance tuning.

---

# Scope

This project **MUST NOT** modify Nextcloud source code.

The implementation focuses on:
- Native Linux server administration on **Debian 13**
- Web server & reverse proxy configuration (Nginx)
- Database tuning and optimization (PostgreSQL 17)
- PHP runtime optimization (PHP-FPM 8.4)
- Cache & locking configuration (Redis 7)
- Security hardening (Fail2ban, UFW, TLS 1.3, Security Headers)
- Automated maintenance, health checking & antivirus protection
- System monitoring & metrics collection (Prometheus & Grafana)
- Production-ready deployment scripts and documentation

---

# Operating System

**Debian 13 (Trixie)**

---

# Technology Stack

- **Web Server & Reverse Proxy**: Nginx (with HTTP/2, TLS 1.3, Brotli & Gzip compression, Rate Limiting) using the native Debian module `libnginx-mod-http-brotli-filter`
- **Application**: Nextcloud Latest Stable
- **Runtime**: PHP 8.4 FPM
- **Database**: PostgreSQL 17
- **Cache & File Locking**: Redis 7
- **SSL / TLS Certificate**: Let's Encrypt (Certbot) with OCSP Stapling
- **Security & Firewall**: UFW + Fail2ban
- **Antivirus Engine**: ClamAV Daemon (Clamd)
- **Monitoring & Metrics**: Prometheus + Grafana (with Node Exporter, Postgres Exporter, Redis Exporter, Nginx Prometheus Exporter reading `ngx_http_stub_status_module`)

---

# Installation Method

**Native Installation Only**

- Docker **MUST NOT** be used.
- Containerization **MUST NOT** be used.
- Virtual Machine configuration is outside project scope.
- Every service **MUST** be installed directly on Debian 13 using APT package manager or native binaries.

---

# Prerequisites

- **Minimum Hardware**:
  - CPU: 2 vCPU (recommended 4 vCPU).
  - RAM: 4 GB (recommended 8 GB; 16 GB for heavy use with ClamAV).
  - Storage: 50 GB free on the root filesystem, plus dedicated storage for `/var/www/nextcloud/data` sized to expected user data.
- **Swap**: Configure at least 2 GB swap or a swapfile (`fallocate -l 2G`).
- **Domain & DNS**: A fully qualified domain name (FQDN) with an `A`/`AAAA` record pointing to the server public IP.
- **Network**: Inbound ports `80/tcp` and `443/tcp` reachable from the internet; SSH `22/tcp` reachable from admin networks.
- **System**: Fresh Debian 13 (Trixie) minimal installation with the root user, a non-root sudo user, and an up-to-date package index.
- **Time**: Timezone configured (e.g., `timedatectl set-timezone <Region/City>`) and time synchronized via NTP/`chrony` (`systemctl enable --now chrony`).

---

# Advanced Production Features (Minimum 5 Core Features)

CloudVault incorporates 6 enterprise-grade server architectural features:

1. **Intrusion Prevention System (Fail2ban Integration)**
   - Integrates Fail2ban with Nginx access logs and Nextcloud authentication logs (`/var/www/nextcloud/data/nextcloud.log`).
   - Automatically bans offending IP addresses attempting brute-force logins, credential stuffing, or abusing rate-limited endpoints via UFW firewall rules.

2. **Brotli Compression & High-Security TLS 1.3 Hardening with OCSP Stapling**
   - Implements Brotli compression alongside Gzip for maximum static asset and web response compression speed.
   - Configures TLS 1.3/1.2 strict cipher suites, HSTS (Preload), Perfect Forward Secrecy (PFS), and OCSP Stapling for optimal security (A+ rating on SSL Labs) and faster SSL handshake times.

3. **ClamAV Antivirus Auto-Scanning Integration**
   - Integrates native ClamAV daemon (`clamd`) with Nextcloud Antivirus App.
   - Every file uploaded via Web UI, WebDAV, or Desktop/Mobile clients is scanned in real-time before saving to storage, blocking malware and infected payloads.

4. **Automated OCC Maintenance & Background Task Optimization**
   - Replaces AJAX cron with systemd timer / Linux cron executing `php /var/www/nextcloud/occ cron.php` every 5 minutes.
   - Includes daily automated background maintenance scripts running `occ db:add-missing-indices`, `occ db:convert-filecache-bigint`, `occ preview:pre-generate`, and orphan file cleanup.

5. **Encrypted Backup System with Retention & Integrity Verification**
   - Automated offsite/local backup script located at `/opt/cloudvault/scripts/backup.sh`.
   - Performs atomic PostgreSQL database dumps (`pg_dumpall`), Nextcloud configuration backups, and incremental data sync.
   - Features AES-256 backup archive encryption, automated retention rotation (7 daily, 4 weekly, 12 monthly backups), and SHA-256 checksum integrity checks.

6. **Centralized Health Check Automation & Grafana Alerting**
   - Automated system health check script (`/opt/cloudvault/scripts/healthcheck.sh`) reporting real-time status of all services (Nginx, PHP-FPM, PostgreSQL, Redis, UFW, Fail2ban, Disk, RAM).
   - Prometheus Alertmanager integration with Grafana to dispatch notifications upon service degradation, storage exhaustion (>85%), or memory pressure.

---

# System Architecture

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
        Cron[Cron / Systemd Timers] -->|Run Daily Maintenance & Backups| BackupScript[/opt/cloudvault/scripts/backup.sh]
        Prometheus[Prometheus] -->|Collect Metrics| Grafana[Grafana Dashboard & Alerts]
    end
```

---

# Directory Structure

```
/etc
├── nginx/
│   ├── nginx.conf
│   ├── sites-available/cloudvault.conf
│   └── sites-enabled/cloudvault.conf
├── php/8.4/
│   ├── fpm/
│   │   ├── php.ini
│   │   └── pool.d/www.conf
│   └── cli/php.ini
├── redis/
│   └── redis.conf
├── postgresql/17/main/
│   ├── postgresql.conf
│   └── pg_hba.conf
├── fail2ban/
│   ├── jail.d/nextcloud.conf
│   └── filter.d/nextcloud.conf
├── ufw/
└── ssl/

/var/www/nextcloud/
├── config/
├── apps/
├── data/
├── themes/
└── core/

/var/log
├── nginx/
├── php8.4-fpm.log
├── redis/
├── postgresql/
├── fail2ban.log
└── cloudvault/

/opt/cloudvault/
├── backup/
├── scripts/
│   ├── install.sh
│   ├── backup.sh
│   ├── restore.sh
│   ├── healthcheck.sh
│   └── maintenance.sh
├── docs/
└── benchmark/
```

---

# Service Responsibilities & Configurations

## Nginx Responsibilities
- HTTPS / TLS 1.3 Termination with Let's Encrypt & OCSP Stapling
- Reverse Proxy to PHP-FPM via Unix Domain Socket (`/run/php/php8.4-fpm.sock`)
- Brotli & Gzip Compression for static assets (CSS, JS, SVG, WASM)
- Strict Security Headers (HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy)
- Static File Caching & Optimization (`Cache-Control` max-age headers for immutables)
- Rate Limiting (`limit_req_zone` for login & API endpoints)
- Large Upload Buffering & Body Size Limit (`client_max_body_size 10G`)

## PostgreSQL 17 Responsibilities
- Secure persistence of application state, user credentials, shares, metadata, file indexing, and permissions.
- Optimized shared buffers, work_mem, maintenance_work_mem, and WAL settings for SSD/NVMe throughput.
- **MUST NOT** store uploaded binary file content.

  Reference tuning values (adjust proportionally to server RAM) in `/etc/postgresql/17/main/postgresql.conf`:

  ```ini
  shared_buffers = 1GB                    # ~25% of total RAM
  effective_cache_size = 3GB              # ~75% of total RAM
  work_mem = 16MB                         # per-session sort/hash memory
  maintenance_work_mem = 256MB            # autovacuum / index maintenance
  max_connections = 200
  wal_buffers = 16MB
  synchronous_commit = off                # optional performance trade-off
  checkpoint_completion_target = 0.9
  random_page_cost = 1.1                  # SSD/NVMe
  effective_io_concurrency = 200
  ```

## Redis 7 Responsibilities
- Fast In-Memory Data Store for Nextcloud session caching (`memcache.local`).
- Distributed Memory Cache for query caching (`memcache.distributed`).
- Transactional File Locking (`memcache.locking`).

  ```php
  'memcache.local' => '\OC\Memcache\Redis',
  'memcache.distributed' => '\OC\Memcache\Redis',
  'memcache.locking' => '\OC\Memcache\Redis',
  'redis' => [
      'host' => '127.0.0.1',
      'port' => 6379,
      'password' => '<REDIS_PASSWORD>',
  ],
  ```

## File Storage
- Storage Directory: `/var/www/nextcloud/data`
- Strict directory permissions: `chown -R www-data:www-data /var/www/nextcloud/data`, `chmod 750 /var/www/nextcloud/data`.

---

# Security Hardening & Firewall

1. **UFW Firewall Rules**:
   - Port `22/tcp` (SSH)
   - Port `80/tcp` (HTTP - Redirect to HTTPS)
   - Port `443/tcp` (HTTPS)
   - Block all other incoming ports by default.

2. **Security Headers**:
   - `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
   - `X-Frame-Options: SAMEORIGIN`
   - `X-Content-Type-Options: nosniff`
   - `X-XSS-Protection: 1; mode=block`
   - `Referrer-Policy: no-referrer-when-downgrade`
   - `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'`

3. **System Hardening**:
   - Disable Server Tokens in Nginx (`server_tokens off;`).
   - Disable Directory Indexing (`autoindex off;`).
   - Restrict access to sensitive dotfiles (`.htaccess`, `.git`, `.env`).

4. **SSH Hardening** (`/etc/ssh/sshd_config`):
   - `PermitRootLogin prohibit-password`
   - `PasswordAuthentication no` (key-based authentication only)
   - `MaxAuthTries 3`
   - `AllowTcpForwarding no` (if not required)
   - Apply changes with `systemctl reload ssh`.

5. **Redis Hardening** (`/etc/redis/redis.conf`):
   - `bind 127.0.0.1 -::1` (loopback only)
   - `protected-mode yes`
   - `requirepass <REDIS_PASSWORD>` (store the password in Nextcloud `config.php`)
   - `rename-command FLUSHALL ""` and `rename-command FLUSHDB ""` (optional)
   - `maxmemory 1gb` and `maxmemory-policy allkeys-lru`
   - Restart with `systemctl restart redis-server`.

6. **AppArmor**: Debian ships AppArmor profiles for `clamd` that may block scanning of Nextcloud directories. Extend the profile (e.g., add `owner /var/www/nextcloud/data/** rk,`) in `/etc/apparmor.d/local/usr.sbin.clamd` then `apparmor_parser -r /etc/apparmor.d/usr.sbin.clamd`.

7. **Certbot Renewal**: Add `--deploy-hook "systemctl reload nginx"` to the renewal configuration so renewed certificates reload Nginx and keep OCSP stapling valid.

8. **Fail2ban Recovery**:
   - Inspect bans: `fail2ban-client status nextcloud`
   - Unban an IP: `fail2ban-client set nextcloud unbanip <IP_ADDRESS>`
   - Whitelist admin IPs in `ignoreip` within `/etc/fail2ban/jail.d/nextcloud.conf`.

9. **Monitoring Exposure**:
   - Bind Prometheus, Node Exporter, and the exporters to `localhost` only.
   - Do **not** expose Prometheus/Grafana ports (9090/3000) publicly; publish Grafana behind the Nginx TLS reverse proxy with authentication or restrict via UFW to admin IPs.

---

# Maintenance & Backup

- **Cron-based Automated Backup**:
  - Script: `/opt/cloudvault/scripts/backup.sh`
  - Location: `/opt/cloudvault/backup`
  - Backs up: PostgreSQL database (`pg_dumpall`), Nextcloud `/var/www/nextcloud/config`, and user data directory `/var/www/nextcloud/data`.
  - Retention: Rotates and removes backups older than retention policy.

- **System Healthcheck Script**:
  - Script: `/opt/cloudvault/scripts/healthcheck.sh`
  - Verifies statuses of `nginx`, `php8.4-fpm`, `postgresql`, `redis-server`, `fail2ban`, `clamav-daemon`, disk space, and UFW firewall.

- **Automated Maintenance Script**:
  - Script: `/opt/cloudvault/scripts/maintenance.sh`
  - Runs Nextcloud maintenance tasks on a daily schedule (systemd timer/cron): `occ db:add-missing-indices`, `occ db:convert-filecache-bigint`, `occ preview:pre-generate`, `occ files:scan --all`, and orphan file cleanup.
  - Must be executed as the `www-data` user: `sudo -u www-data php /var/www/nextcloud/occ <command>`.

- **Backup Restore**:
  - Script: `/opt/cloudvault/scripts/restore.sh`
  - Restores PostgreSQL dump, Nextcloud configuration, and user data from `/opt/cloudvault/backup`, followed by integrity verification and permission fixes.

---

# Development Phases

- **Phase 1**: Debian 13 Preparation & Repository Update
- **Phase 2**: Core Package Installation (PostgreSQL 17, Redis 7, PHP-FPM 8.4, Nginx, Fail2ban, ClamAV)
- **Phase 3**: Nextcloud Native Setup, Database & Redis Integration
- **Phase 4**: Nginx Configuration, SSL/TLS Setup, Brotli & PHP Optimization
- **Phase 5**: Security Hardening, Fail2ban Jail Rules, UFW Firewall Setup
- **Phase 6**: Advanced Features Setup (ClamAV Integration, Systemd Maintenance Timers)
- **Phase 7**: Monitoring & Alerting Setup (Prometheus & Grafana Dashboards)
- **Phase 8**: Backup Scripting & Disaster Recovery Testing
- **Phase 9**: Documentation & Verification

---

# Deliverables

## Documentation
- `README.md`
- `INSTALLATION.md`
- `DEPLOYMENT.md`
- `SYSTEM_ARCHITECTURE.md`
- `SECURITY.md`
- `PERFORMANCE.md`
- `BACKUP.md`
- `MONITORING.md`

## Configuration Files & Scripts
- Nginx Server Config (`/etc/nginx/sites-available/cloudvault.conf`) + Brotli module (`libnginx-mod-http-brotli-filter`)
- Nginx Monitoring Exporter Config (stub_status endpoint + `nginx-prometheus-exporter`)
- PHP-FPM Configuration & Pool Settings (`/etc/php/8.4/fpm/pool.d/www.conf`)
- PostgreSQL Tuning Settings (`postgresql.conf`, `pg_hba.conf`)
- Redis Tuning Configuration (`redis.conf`)
- Fail2ban Jail & Filter Files (`nextcloud.conf`)
- UFW Firewall & Certbot SSL renewal scripts
- System Management Scripts under `/opt/cloudvault/scripts/` (`install.sh`, `backup.sh`, `restore.sh`, `healthcheck.sh`, `maintenance.sh`)

---

# Final Objective

The final result must be a production-ready, enterprise-grade self-hosted cloud storage platform running natively on **Debian 13 (Trixie)** using Nextcloud, Nginx, PHP-FPM 8.4, PostgreSQL 17, Redis 7, Fail2ban, ClamAV, and Let's Encrypt without Docker or any container technology.

The project must demonstrate web server architecture, Linux server administration, deployment, security, and performance optimization following production best practices.
