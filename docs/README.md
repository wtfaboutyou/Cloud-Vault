# CloudVault

Enterprise-grade, self-hosted cloud storage platform built natively on **Debian 13 (Trixie)**.

CloudVault uses **Nextcloud** as the cloud storage application and **Nginx** as the
primary gateway responsible for traffic handling, SSL termination, security headers,
rate limiting, and performance tuning. All components are installed directly on the OS
via APT — **no Docker, no containers**.

---

## Technology Stack

| Layer          | Component                                        |
|----------------|--------------------------------------------------|
| Web server     | Nginx (HTTP/2, TLS 1.3, Brotli + Gzip, rate limit) |
| Application    | Nextcloud (latest stable)                        |
| Runtime        | PHP 8.4 FPM                                      |
| Database       | PostgreSQL 17                                    |
| Cache & locks  | Redis 7 (memcache.local / distributed / locking) |
| TLS            | Let's Encrypt (Certbot) + OCSP Stapling          |
| Security       | UFW + Fail2ban + ClamAV + AppArmor               |
| Monitoring     | Prometheus + Grafana + exporters                 |

## Advanced Production Features (6)

1. **Intrusion Prevention** — Fail2ban integrates with Nginx logs and Nextcloud
   `nextcloud.log` to ban brute-force / credential-stuffing IPs via UFW.
2. **Brotli + TLS 1.3 Hardening with OCSP Stapling** — A+ SSL Labs rating, HSTS
   preload, PFS, strict ciphers.
3. **ClamAV Antivirus Auto-Scanning** — every upload (Web, WebDAV, Desktop/Mobile)
   is scanned in real-time by `clamd`.
4. **Automated OCC Maintenance** — systemd timers run cron.php every 5 minutes and
   daily maintenance (`db:*`, `preview:pre-generate`, `files:scan --all`, cleanup).
5. **Encrypted Backup with Retention & Integrity** — AES-256 archives, SHA-256
   verification, rotation (7 daily / 4 weekly / 12 monthly).
6. **Centralized Health Checks & Grafana Alerting** — `healthcheck.sh` + Prometheus
   Alertmanager notifications.

## Repository Layout

```
cloudvault/
├── read.md                    # full project specification
├── walkthrough.md             # change log of spec revisions
├── scripts/                   # deployment & operations scripts
│   ├── install.sh             # phased installer (prep → backup)
│   ├── backup.sh              # encrypted backup + retention
│   ├── restore.sh             # disaster recovery
│   ├── healthcheck.sh         # service/disk/memory/SSL status
│   └── maintenance.sh         # daily occ maintenance tasks
├── config/                    # production configuration files
│   ├── nginx/sites-available/cloudvault.conf
│   ├── php/8.4/fpm/pool.d/www.conf
│   ├── postgresql/17/main/postgresql.conf
│   ├── redis/redis.conf
│   ├── fail2ban/ (jail.d + filter.d)
│   ├── ufw/ (ufw-setup.sh, certbot-renew-hook.sh)
│   └── prometheus/ (prometheus.yml, alert.rules.yml)
├── docs/                      # documentation
│   ├── INSTALLATION.md
│   ├── DEPLOYMENT.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── SECURITY.md
│   ├── PERFORMANCE.md
│   ├── BACKUP.md
│   └── MONITORING.md
├── backup/                    # backup staging (production: /opt/cloudvault/backup)
├── benchmark/                 # benchmark.sh + results
├── web/demo/                  # static demo login page (portfolio showcase)
└── apps/                      # custom Nextcloud apps
    └── otp-register/           # OTP email verification + admin approval
```

## Quick Start

```bash
# 1. Deploy the repository to the server
scp -r cloudvault root@<server>:/opt/

# 2. Set required variables and run the full installer
cd /opt/cloudvault
NC_DOMAIN=cloud.example.com ADMIN_EMAIL=admin@example.com \
  sudo bash scripts/install.sh all

# 3. Verify
sudo bash scripts/healthcheck.sh
curl -sI https://cloud.example.com | grep -i strict-transport-security
```

> Read **[INSTALLATION.md](INSTALLATION.md)** for prerequisites and step-by-step
> phases, and **[DEPLOYMENT.md](DEPLOYMENT.md)** for post-install verification.

## Operations Cheat-Sheet

```bash
sudo bash /opt/cloudvault/scripts/backup.sh            # run a backup now
sudo bash /opt/cloudvault/scripts/backup.sh verify     # verify latest archive
sudo bash /opt/cloudvault/scripts/restore.sh           # restore latest archive
sudo bash /opt/cloudvault/scripts/healthcheck.sh       # full health report
sudo bash /opt/cloudvault/scripts/maintenance.sh       # run maintenance manually
GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
  sudo bash /opt/cloudvault/scripts/install.sh gcs     # mount GCS bucket
systemctl list-timers cloudvault-*                    # scheduled tasks
```

## Documentation Index

| Document | Purpose |
|----------|---------|
| [INSTALLATION.md](INSTALLATION.md) | Prerequisites + phased installation |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Post-install verification & go-live |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Architecture, flow, diagrams |
| [SECURITY.md](SECURITY.md) | Hardening, firewall, Fail2ban, AV |
| [PERFORMANCE.md](PERFORMANCE.md) | Tuning, compression, benchmarking |
| [BACKUP.md](BACKUP.md) | Backup/restore strategy & recovery |
| [MONITORING.md](MONITORING.md) | Prometheus, Grafana, alerting |

---

## Requirements

- Debian 13 (Trixie) fresh minimal install, root + non-root sudo user
- FQDN with A/AAAA record pointing to the server
- 2 vCPU / 4 GB RAM minimum (8 GB recommended with ClamAV)
- 50 GB root storage + dedicated data volume for `/var/www/nextcloud/data`
- Ports 80, 443 reachable from the internet; 22 from admin networks
