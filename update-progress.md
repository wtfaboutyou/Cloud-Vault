# Cloud Vault
CloudVault is a self-hosted cloud storage platform powered by Nextcloud, Nginx, PostgreSQL, and Redis on Debian 13. The project focuses on native deployment, web server architecture, security hardening, performance optimization, and Linux server administration without using Docker.

## ✨ Key Features

- 🔒 **HTTPS with Let's Encrypt**
  Secure all client-server communication using SSL/TLS certificates.

- 🌐 **Nginx Reverse Proxy**
  Efficient request routing with optimized web server configuration.

- 🛡️ **Security Hardening**
  Security headers, UFW firewall, Fail2Ban, and secure PHP-FPM configuration.

- ⚡ **Performance Optimization**
  Gzip compression, browser caching, optimized PHP-FPM, PostgreSQL, and Redis.

- 🚦 **Rate Limiting**
  Protect login and upload endpoints from brute-force and abuse.

- 🗄️ **PostgreSQL Integration**
  Reliable metadata storage with optimized database configuration.

- 🚀 **Redis File Locking & Caching**
  Improve responsiveness and prevent file conflicts during concurrent access.

- 📊 **Server Monitoring**
  Real-time monitoring with Prometheus and Grafana dashboards.

- 💾 **Automated Backup & Recovery**
  Scheduled backups for database, application configuration, and uploaded files.

- 📁 **Self-Hosted Cloud Storage**
  Private cloud storage powered by Nextcloud with full control over infrastructure.

- 🖥️ **Native Debian Deployment**
  Deploy directly on Debian 13 without Docker, providing full control over system administration.


## Project Structure
```
cloudvault/
│
├── read.md                    # Project specification (source of truth)
├── update-progress.md         # Progress tracker & phase results
├── walkthrough.md             # Implementation walkthrough
│
├── apps/
│   └── otp-register/          # Custom Nextcloud OTP registration app
│
├── benchmark/
│   ├── benchmark.sh           # HTTP/TLS/compression smoke test
│   ├── upload-download.sh     # WebDAV throughput benchmark
│   └── results/               # Benchmark result files
│
├── config/
│   ├── fail2ban/              # jail.d/nextcloud.conf + filter.d/nextcloud.conf
│   ├── nginx/                 # nginx.conf + sites-available/cloudvault.conf
│   ├── php/                   # 8.4/fpm/pool.d/www.conf
│   ├── postgresql/            # 17/main/postgresql.conf
│   ├── prometheus/            # prometheus.yml + alert.rules.yml
│   ├── redis/                 # redis.conf
│   └── ufw/                   # ufw-setup.sh + certbot-renew-hook.sh
│
├── docs/
│   ├── README.md
│   ├── INSTALLATION.md
│   ├── DEPLOYMENT.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── SECURITY.md
│   ├── PERFORMANCE.md
│   ├── BACKUP.md
│   └── MONITORING.md
│
├── scripts/
│   ├── install.sh             # Idempotent staged installer (9 phases)
│   ├── backup.sh              # AES-256 encrypted backup + retention
│   ├── restore.sh             # Full restore with integrity check
│   ├── healthcheck.sh         # Service status + disk/mem/SSL
│   ├── healthcheck-prom.sh    # Prometheus textfile collector metrics
│   ├── maintenance.sh         # Daily OCC maintenance tasks
│   ├── gcs-storage.sh         # GCS/object-storage helper
│   └── otp-send.sh            # OTP notification helper
│
└── web/
    └── demo/                  # Demo landing page (index.html, assets/)
```

## Roadmap

### Phase 1 — Environment Preparation

- [x] Install Debian 13
- [x] Configure hostname
- [x] Configure DNS
- [x] Update repositories
- [x] Configure swap
- [x] Create deployment directory

---

### Phase 2 — Core Services

- [x] Install Nginx
- [x] Install PHP-FPM 8.4
- [x] Install PostgreSQL 17
- [x] Install Redis 7
- [x] Install Nextcloud

---

### Phase 3 — Web Server Configuration

- [x] Configure Nginx
- [x] Configure PHP-FPM
- [x] Enable HTTPS
- [x] Enable Brotli
- [x] Configure Rate Limiting
- [x] Configure Security Headers

---

### Phase 4 — Database & Storage

- [x] Configure PostgreSQL
- [x] Configure Redis
- [x] Configure Data Directory
- [x] Configure File Permissions

---

### Phase 5 — Security

- [x] Configure UFW
- [x] Configure Fail2ban
- [x] Configure ClamAV
- [x] Harden SSH
- [x] Enable OCSP Stapling

---

### Phase 6 — Monitoring

- [x] Install Prometheus
- [x] Install Grafana
- [x] Configure Exporters
- [x] Create Dashboard

---

### Phase 7 — Backup & Maintenance

- [x] Create Backup Script
- [x] Create Restore Script
- [x] Configure Cron Jobs
- [x] Configure Health Check

---

### Phase 8 — Documentation

- [x] Complete README
- [x] Write Installation Guide
- [x] Write Deployment Guide
- [x] Write Security Guide
- [x] Write Monitoring Guide

---

### Phase 9 — Testing & Optimization

- [x] Upload Benchmark
- [x] Download Benchmark
- [x] SSL Test
- [x] Security Validation
- [x] Final Production Review

---

## Phase 9 Results (2026-08-17)

### Fixed During Testing
- **ClamAV DB korup** (`daily.cld` malformed → daemon failed). DB di-download
  ulang via `freshclam`; daemon + scan EICAR diverifikasi OK.
- **`files_antivirus` terpasang tapi disabled**, dan `av_mode=daemon` salah —
  membuat semua upload gagal 415 ("No connection to anti virus"). Di-enable dan
  diset `av_mode=socket`. Sekarang upload EICAR diblokir, file normal lolos scan.
- **Fail2ban** hanya 2 jail + aksi default `nftables`. Diselaraskan ke
  `config/fail2ban/jail.d/nextcloud.conf` (4 jail: nextcloud, nginx-auth,
  nginx-botsearch, sshd) dengan `banaction=ufw`. Auto-ban via UFW diverifikasi.
- **Redis** `rename-command FLUSHALL/FLUSHDB/SHUTDOWN` diterapkan ke server.
- **SSH hardening** diterapkan (`PermitRootLogin prohibit-password`,
  `PasswordAuthentication no`, `MaxAuthTries 3`, `AllowTcpForwarding no`).
  ⚠️ Wajib install SSH public key sebelum me-restart ssh.
- **Eksporter monitoring**: node/postgres/redis exporter diaktifkan &
  dikonfigurasi (redis exporter + password). Semua 5 target Prometheus `up`.

### Benchmarks
Lihat `docs/PERFORMANCE.md` §8. Download ~40 MB/s; upload ~0.6–1.9 MB/s best
(dibatasi synchronous ClamAV scan + RAM VM 3.8 GB).

### Remaining Production Gaps
- Sertifikat masih **self-signed** (OCSP stapling off) — ganti Let's Encrypt
  saat domain publik tersedia.
- `/opt/cloudvault/scripts` kosong; timer systemd masih memanggil
  `/root/cloudvault/scripts/`. Sinkronkan script + sync config ke `/opt` untuk
  konsistensi produksi.
- Nilai tuning docs (pm.max_children 100 dst.) vs live VM lebih kecil (12) —
  sesuaikan dengan kapasitas server riil.
