# INSTALLATION.md

Complete step-by-step guide to deploy CloudVault natively on **Debian 13 (Trixie)**.

The deployment is orchestrated by `scripts/install.sh` in **9 phases**. Each phase is
also callable independently, which lets you pause, verify, and resume.

---

## 1. Prerequisites

- **Hardware**: 2 vCPU / 4 GB RAM minimum (8 GB recommended; 16 GB with heavy ClamAV).
- **Storage**: 50 GB free on root, plus a data volume for `/var/www/nextcloud/data`.
- **Swap**: ≥ 2 GB (`fallocate -l 2G /swapfile && mkswap /swapfile && swapon /swapfile`).
- **Domain**: FQDN with `A`/`AAAA` record → server public IP.
- **Network**: inbound `80/tcp` and `443/tcp`; `22/tcp` from admin networks only.
- **Fresh Debian 13** minimal install with `root` and a non-root sudo user.
- **Time**: `timedatectl set-timezone <Region/City>` and `systemctl enable --now chrony`.

Verify OS:

```bash
cat /etc/debian_version     # 13.x (Trixie)
lsb_release -a
nproc && free -h && df -h / /var 2>/dev/null
```

---

## 2. Repository Deployment

```bash
# from your workstation
scp -r cloudvault root@<server>:/opt/cloudvault

# on the server
cd /opt/cloudvault
```

> On first run `install.sh` copies itself to `/opt/cloudvault/scripts/` so systemd
> timers reference a stable path.

---

## 3. Environment Variables

Set overrides before running (defaults are generated automatically if omitted):

| Variable               | Default                        | Purpose                          |
|------------------------|--------------------------------|----------------------------------|
| `NC_DOMAIN`            | `cloud.example.com`            | Nextcloud FQDN                   |
| `ADMIN_EMAIL`          | `webmaster@$NC_DOMAIN`         | Let's Encrypt contact            |
| `NC_ADMIN_USER`        | `admin`                        | Initial admin login              |
| `NC_ADMIN_PASS`        | random                         | Initial admin password           |
| `NC_DB_NAME/USER`      | `nextcloud`                    | PostgreSQL database              |
| `NC_DB_PASS`           | random                         | PostgreSQL password              |
| `REDIS_PASS`           | random                         | Redis `requirepass`              |
| `ADMIN_IP_WHITELIST`   | empty                          | Restrict SSH to admin IP         |
| `ENABLE_MONITORING`    | `no`                           | Install Prometheus/Grafana       |
| `TZ`                   | `Etc/UTC`                      | System timezone                  |
| `GCS_BUCKET`           | empty                          | GCS bucket (enables Phase 3d)    |
| `GCS_ACCESS_KEY`       | empty                          | GCS HMAC access key              |
| `GCS_SECRET`           | empty                          | GCS HMAC secret key              |
| `GCS_REGION`           | `auto`                         | GCS region (leave `auto`)        |
| `GCS_MOUNTPOINT`       | `/gcs`                         | Nextcloud mountpoint for bucket  |

Generated secrets are written to `/opt/cloudvault/.secrets/cloudvault.env`.

---

## 4. Phased Installation

### Phase 1 — System preparation

```bash
sudo bash scripts/install.sh prep
```

Installs base packages, creates the 2 GB swapfile, sets timezone and enables `chrony`.

### Phase 2 — Core packages

```bash
sudo bash scripts/install.sh packages
```

Installs:

- PHP 8.4 FPM + all Nextcloud extensions (gd, intl, imagick, redis, apcu, pgsql, ...)
- Nginx + `libnginx-mod-http-brotli-filter`
- PostgreSQL 17, Redis 7
- UFW, Fail2ban, ClamAV daemon, AppArmor utils
- (optional) Prometheus, exporters, Grafana — only when `ENABLE_MONITORING=yes`

### Phase 3a — PostgreSQL & Redis

```bash
sudo bash scripts/install.sh database
```

- Appends the CloudVault tuning block to `postgresql.conf` and restarts.
- Creates role `nextcloud` and database `nextcloud`.
- Hardens Redis: loopback bind, `protected-mode`, `requirepass`, disabled
  `FLUSHALL`/`FLUSHDB`/`SHUTDOWN`, `maxmemory 1gb` with `allkeys-lru`.

### Phase 3b — Nextcloud core

```bash
sudo bash scripts/install.sh nextcloud
```

- Downloads and unpacks the latest Nextcloud into `/var/www/nextcloud`.
- Writes `config/config.php` (PostgreSQL + Redis memcache/locking, trusted domains).
- Runs `occ maintenance:install` with the admin account.
- Installs the 5-minute cron entry for background jobs.
- Saves generated credentials to `.secrets/cloudvault.env`.

### Phase 3c — OTP registration via Resend (manual approval)

```bash
RESEND_API_KEY=re_xxxx RESEND_FROM="CloudVault <verify@example.com>" \
  sudo bash scripts/install.sh register
```

- Installs and enables the `otp-register` app into `/var/www/nextcloud/apps`.
- Wires the Resend API key / sender address via `occ config:app:set`.
- Registration is **manual**: a 6-digit verification code is emailed to confirm
  the address, but the account is **not** enabled automatically. The request is
  queued and an administrator must approve it before the user can log in:
  - List pending requests: `occ otp-register:pending`
  - Approve / enable:     `occ otp-register:approve <username>`
  - Reject / remove:      `occ otp-register:reject <username>`
- Public registration page: `https://<domain>/apps/otp-register/`.
- Standalone CLI helper: `sudo bash scripts/otp-send.sh user@example.com`.

See [PERFORMANCE.md](PERFORMANCE.md) and the app under `apps/otp-register/`.

### Phase 3d — Google Cloud Storage external storage (S3-compatible)

Mount a Google Cloud Storage bucket into Nextcloud using GCS's S3-compatible
endpoint and the stock `AmazonS3` backend (no extra package needed).

Prerequisites in the GCP console:
1. Create a bucket: `gsutil mb gs://<bucket>`
2. Create an HMAC access/secret key for a Service Account:
   `gcloud storage hmac create <service-account-email>`

Then run the phase through the installer (optional — skipped when `GCS_BUCKET`
is empty):

```bash
GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
  sudo bash scripts/install.sh gcs
```

Or deploy everything including GCS in one go:

```bash
GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
  sudo bash scripts/install.sh all
```

- Enables `files_external`, creates a system-wide mount `/gcs` → `gs://<bucket>`
  pointing at `https://storage.googleapis.com` (TLS, path-style requests).
  Override the mountpoint with `GCS_MOUNTPOINT`, e.g. `/archive`.
- Verify in admin UI: **Settings → External storages**.

### Phase 4 — Nginx, TLS, Brotli, PHP tuning

```bash
sudo bash scripts/install.sh web
```

- Deploys `cloudvault.conf` (see [config/nginx](../config/nginx/)).
- Deploys the tuned `www.conf` PHP-FPM pool.
- Issues a Let's Encrypt certificate with `certbot --nginx` and registers a
  renew hook that reloads Nginx (keeps OCSP stapling valid).

### Phase 5 — Security hardening

```bash
sudo bash scripts/install.sh security
```

- **UFW**: default deny incoming; allow 22/80/443; block outbound SMTP.
- **Fail2ban**: installs `nextcloud.conf` jail + filter (Nextcloud auth log and
  Nginx error/access logs) banning via `ufw` action.
- **SSH**: `PermitRootLogin prohibit-password`, `PasswordAuthentication no`,
  `MaxAuthTries 3`, `AllowTcpForwarding no`.

> **Verify your SSH key works before closing the session.**

### Phase 6 — ClamAV & maintenance timers

```bash
sudo bash scripts/install.sh features
```

- Extends the AppArmor clamd profile to read `/var/www/nextcloud/data/**`.
- Installs Nextcloud **files_antivirus** app and points it at the clamd socket.
- Creates `cloudvault-maintenance.timer` (02:30 daily) and
  `cloudvault-backup.timer` (03:00 daily).

### Phase 8 — Backup infrastructure

```bash
sudo bash scripts/install.sh backup
```

- Creates `/opt/cloudvault/backup` and the AES-256 key at
  `/etc/cloudvault/backup.key`.

> **Back up this key offsite — archives cannot be restored without it.**

### Phase 7 — Monitoring (optional)

```bash
ENABLE_MONITORING=yes sudo bash scripts/install.sh monitoring
```

- Installs Prometheus, node/postgres/redis exporters, and Grafana.
- Binds exporters to loopback; Grafana is intended to be published behind Nginx TLS.

### Full deployment

```bash
NC_DOMAIN=cloud.example.com ADMIN_EMAIL=admin@example.com \
  sudo bash scripts/install.sh all
```

---

## 5. Post-Installation Checklist

```bash
systemctl status nginx php8.4-fpm postgresql redis-server fail2ban clamav-daemon
sudo bash /opt/cloudvault/scripts/healthcheck.sh
php /var/www/nextcloud/occ status
sudo -u www-data php /var/www/nextcloud/occ app:list | grep -i antivirus
curl -sI https://cloud.example.com | grep -iE 'strict-transport|content-security'
```

Open `https://cloud.example.com` and complete the initial admin login.

---

## 6. Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `502 Bad Gateway` | PHP-FPM socket down: `systemctl restart php8.4-fpm`; check `/run/php/php8.4-fpm.sock` |
| Certbot fails | DNS not resolving / port 80 blocked |
| ClamAV not scanning | AppArmor profile; `apparmor_parser -r /etc/apparmor.d/usr.sbin.clamd` |
| Redis connection error | `requirepass` mismatch between `redis.conf` and `config.php` |
| Uploads failing | `client_max_body_size 10G` set but PHP `post_max_size` too small |

See [DEPLOYMENT.md](DEPLOYMENT.md) and [PERFORMANCE.md](PERFORMANCE.md) for more.
