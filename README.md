# CloudVault

**Enterprise-grade, self-hosted cloud storage platform built natively on Debian 13 (Trixie).**

CloudVault menggunakan **Nextcloud** sebagai aplikasi cloud storage dan **Nginx** sebagai gateway utama yang menangani traffic, SSL termination, security headers, rate limiting, dan performance tuning. Semua komponen diinstall langsung di OS via APT — **tanpa Docker, tanpa container**.

Project ini fokus pada **arsitektur web server, administrasi server Linux, deployment, security hardening, dan performance optimization**, bukan mengembangkan aplikasi cloud storage baru.

---

## 1. Tech Stack

| Layer          | Component / Teknologi                                              |
|----------------|--------------------------------------------------------------------|
| Web Server     | Nginx (HTTP/2, TLS 1.3, Brotli + Gzip, Rate Limiting)            |
| Application    | Nextcloud (latest stable)                                          |
| Runtime        | PHP 8.4 FPM                                                        |
| Database       | PostgreSQL 17 (tuned untuk SSD/NVMe)                              |
| Cache & Locks  | Redis 7 (memcache.local / distributed / locking)                  |
| TLS            | Let's Encrypt (Certbot) + OCSP Stapling                           |
| Security       | UFW + Fail2ban + ClamAV + AppArmor                                |
| Monitoring     | Prometheus + Grafana + Exporters                                  |
| Backup         | AES-256 Encrypted Archives + SHA-256 Verification + Retention     |

**Custom Components:**
- **Custom Nextcloud App `otp-register`** — OTP email verification via Resend API dengan manual admin approval (`occ otp-register:approve`)
- **Google Cloud Storage** — Optional S3-compatible external storage mount
- **Demo Page** — Static login page di `/demo/` untuk showcase portfolio

---

## 2. Screenshot / Demo

> **Placeholder** — Screenshot/GIF/video demo akan ditambahkan manual sebelum push ke GitHub.

| Tampilan | Deskripsi |
|----------|-----------|
| ![Dashboard Nextcloud](docs/assets/screenshots/dashboard.png) | Dashboard Nextcloud setelah login |
| ![OTP Registration](docs/assets/screenshots/otp-register.png) | Halaman registrasi OTP custom |
| ![Grafana Dashboard](docs/assets/screenshots/grafana.png) | Monitoring dashboard Grafana |
| ![Demo Page](docs/assets/screenshots/demo-page.png) | Static demo page di `/demo/` |

**Video Demo:** `[Link video demo akan ditambahkan di sini]`

---

## 3. Cara Install & Menjalankan

### Prasyarat

- **OS:** Debian 13 (Trixie) fresh minimal install, root + non-root sudo user
- **Domain:** FQDN dengan A/AAAA record menunjuk ke server
- **Spec Minimum:** 2 vCPU / 4 GB RAM (8 GB recommended dengan ClamAV)
- **Storage:** 50 GB root + dedicated data volume untuk `/var/www/nextcloud/data`
- **Network:** Port 80, 443 reachable dari internet; Port 22 dari admin networks

### Langkah-langkah Deployment

```bash
# 1. Clone repository ke server
scp -r cloudvault root@<server>:/opt/cloudvault

# 2. Masuk ke direktori project
cd /opt/cloudvault

# 3. Set environment variables & jalankan installer lengkap
NC_DOMAIN=cloud.example.com ADMIN_EMAIL=admin@example.com \
  sudo bash scripts/install.sh all

# 4. Verifikasi instalasi
sudo bash scripts/healthcheck.sh
curl -sI https://cloud.example.com | grep -i strict-transport-security
```

### Install Bertahap (Optional)

```bash
# Phase 1: System preparation
sudo bash scripts/install.sh prep

# Phase 2: Core packages (PHP, Nginx, PostgreSQL, Redis, dll)
sudo bash scripts/install.sh packages

# Phase 3a: Database & Redis
sudo bash scripts/install.sh database

# Phase 3b: Nextcloud core
sudo bash scripts/install.sh nextcloud

# Phase 3c: OTP Registration (butuh RESEND_API_KEY)
RESEND_API_KEY=re_xxxx RESEND_FROM="CloudVault <verify@example.com>" \
  sudo bash scripts/install.sh register

# Phase 3d: Google Cloud Storage (optional)
GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
  sudo bash scripts/install.sh gcs

# Phase 4: Nginx, TLS, Brotli, PHP tuning
sudo bash scripts/install.sh web

# Phase 5: Security hardening (UFW, Fail2ban, SSH)
sudo bash scripts/install.sh security

# Phase 6: ClamAV & Maintenance timers
sudo bash scripts/install.sh features

# Phase 7: Backup infrastructure
sudo bash scripts/install.sh backup

# Phase 8: Monitoring (optional)
ENABLE_MONITORING=yes sudo bash scripts/install.sh monitoring
```

### Post-Install Verification

```bash
# Cek status services
systemctl status nginx php8.4-fpm postgresql redis-server fail2ban clamav-daemon

# Health check lengkap
sudo bash /opt/cloudvault/scripts/healthcheck.sh

# Cek Nextcloud status
php /var/www/nextcloud/occ status

# Cek antivirus app aktif
sudo -u www-data php /var/www/nextcloud/occ app:list | grep -i antivirus

# Cek security headers
curl -sI https://cloud.example.com | grep -iE 'strict-transport|content-security'
```

Buka `https://cloud.example.com` dan login dengan kredensial admin.

> Dokumentasi lengkap: [INSTALLATION.md](docs/INSTALLATION.md) | [DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## 4. Link Demo Live

> **Placeholder** — Link demo live akan ditambahkan setelah project di-deploy.

- **Production:** `https://cloud.example.com` (ganti dengan domain actual)
- **Demo Page:** `https://cloud.example.com/demo/`
- **Grafana:** `https://cloud.example.com/grafana/` (jika monitoring enabled)
- **OTP Registration:** `https://cloud.example.com/apps/otp-register/`

---

## 5. Link Edusoft Portfolio

> **Placeholder** — Link ke halaman project di Edusoft Portfolio akan ditambahkan manual.

- **Portfolio Page:** `[URL Edusoft Portfolio Project Page]`

---

## Repository Structure

```
cloudvault/
├── README.md                    # Project overview (this file)
├── scripts/                     # Deployment & operations scripts
│   ├── install.sh              # Phased installer (prep → backup)
│   ├── backup.sh               # Encrypted backup + retention
│   ├── restore.sh              # Disaster recovery
│   ├── healthcheck.sh          # Service/disk/memory/SSL status
│   ├── healthcheck-prom.sh     # Prometheus-formatted healthcheck
│   ├── maintenance.sh          # Daily OCC maintenance tasks
│   ├── otp-send.sh             # CLI helper untuk send OTP
│   ├── gcs-storage.sh          # GCS mount helper
│   └── benchmark/              # Benchmark scripts
├── config/                      # Production configuration files
│   ├── nginx/
│   ├── php/8.4/fpm/pool.d/
│   ├── postgresql/17/main/
│   ├── redis/
│   ├── fail2ban/
│   ├── ufw/
│   └── prometheus/
├── docs/                        # Full documentation
│   ├── INSTALLATION.md
│   ├── DEPLOYMENT.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── SECURITY.md
│   ├── PERFORMANCE.md
│   ├── BACKUP.md
│   ├── MONITORING.md
│   ├── DEMO_VIDEO.md
│   └── assets/                  # Screenshots, diagrams (to be added)
├── apps/                        # Custom Nextcloud apps
│   └── otp-register/            # OTP email verification + admin approval
│       ├── appinfo/
│       ├── lib/
│       ├── templates/
│       └── js/
├── web/                         # Static web assets
│   └── demo/                    # Demo login page (portfolio showcase)
│       ├── index.html
│       └── assets/
└── benchmark/results/           # Benchmark output files
```

---

## Operations Cheat-Sheet

```bash
# Backup & Restore
sudo bash /opt/cloudvault/scripts/backup.sh            # Run backup now
sudo bash /opt/cloudvault/scripts/backup.sh verify     # Verify latest archive
sudo bash /opt/cloudvault/scripts/restore.sh           # Restore latest archive

# Health & Maintenance
sudo bash /opt/cloudvault/scripts/healthcheck.sh       # Full health report
sudo bash /opt/cloudvault/scripts/maintenance.sh       # Run maintenance manually

# GCS Mount
GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
  sudo bash /opt/cloudvault/scripts/install.sh gcs

# Scheduled Tasks
systemctl list-timers cloudvault-*

# OTP Registration CLI
sudo bash /opt/cloudvault/scripts/otp-send.sh user@example.com
```

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [INSTALLATION.md](docs/INSTALLATION.md) | Prerequisites + phased installation |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Post-install verification & go-live |
| [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Architecture, flow, diagrams |
| [SECURITY.md](docs/SECURITY.md) | Hardening, firewall, Fail2ban, AV |
| [PERFORMANCE.md](docs/PERFORMANCE.md) | Tuning, compression, benchmarking |
| [BACKUP.md](docs/BACKUP.md) | Backup/restore strategy & recovery |
| [MONITORING.md](docs/MONITORING.md) | Prometheus, Grafana, alerting |
| [DEMO_VIDEO.md](docs/DEMO_VIDEO.md) | Demo video documentation |

---

## Advanced Production Features (6)

1. **Intrusion Prevention** — Fail2ban integrate dengan Nginx logs dan Nextcloud `nextcloud.log` untuk auto-ban brute-force/credential-stuffing IPs via UFW.
2. **Brotli Compression + TLS 1.3 Hardening** — Strict cipher suites, HSTS preload, Perfect Forward Secrecy (target: A+ di SSL Labs).
3. **ClamAV Antivirus Auto-Scanning** — Setiap upload (Web, WebDAV, Desktop/Mobile clients) di-scan real-time oleh `clamd` sebelum disimpan.
4. **Automated OCC Maintenance** — Systemd timers jalan `cron.php` tiap 5 menit plus daily maintenance (`db:*`, `preview:pre-generate`, `files:scan --all`, orphan cleanup).
5. **Encrypted Backup dengan Retention & Integrity** — AES-256 encrypted archives, SHA-256 verification, rotation (7 daily / 4 weekly / 12 monthly).
6. **Centralized Health Checks & Grafana Alerting** — Automated health checks + Prometheus Alertmanager notifikasi saat service degradation atau storage >85%.

---

## License

MIT License — bebas digunakan, dimodifikasi, dan didistribusikan.

---

**Dibangun untuk showcase keahlian:** Linux Server Administration, Web Server Architecture, Security Hardening, Performance Tuning, Infrastructure as Code.