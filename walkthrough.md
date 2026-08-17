# Walkthrough - CloudVault Specification Restructuring & Feature Expansion

## Overview

File [`read.md`](file:///root/cloudvault/read.md) telah berhasil diperbaiki, dirapikan strukturnya, dan ditingkatkan dengan spesifikasi produksi yang konsisten menggunakan **Debian 13 (Trixie)** serta penambahan 6 fitur canggih (*advanced enterprise features*).

---

## Ringkasan Perubahan

### 1. Merapikan Struktur & Formatting [`read.md`](file:///root/cloudvault/read.md)
- **Konsistensi OS**: Menyelaraskan seluruh penyebutan OS yang tadinya tidak konsisten (Debian 12 vs 13) menjadi **Debian 13 (Trixie)**.
- **Formatting Markdown**: Menghapus baris kosong/spasi berlebih antar paragraf agar tampilan dokumen profesional dan mudah dibaca.
- **Visual Diagram**: Menambahkan Mermaid diagram interaktif untuk arsitektur sistem (`graph TD`).

### 2. Penambahan 6 Fitur Canggih Server Web CloudVault
Telah ditambahkan seksi khusus `Advanced Production Features` yang mencakup 6 fitur enterprise:
1. **Intrusion Prevention System (Fail2ban Integration)**: Automasi deteksi dan pemblokiran IP penyerang/brute-force login via log Nginx & Nextcloud.
2. **Brotli Compression & High-Security TLS 1.3 with OCSP Stapling**: Pengoptimuman kecepatan transfer aset web dan keamanan SSL tingkat tinggi (skor A+).
3. **ClamAV Antivirus Auto-Scanning Integration**: Pemindaian otomatis secara real-time (*daemon scan*) terhadap semua file yang diunggah ke Nextcloud.
4. **Automated OCC Maintenance & Background Task Optimization**: Systemd/Cron task harian untuk indeks database, prapembuatan preview, dan pembersihan sampah.
5. **Encrypted Backup System with Retention & Integrity Verification**: Script backup terenkripsi AES-256 dengan rotasi retensi (harian/mingguan/bulanan) dan verifikasi checksum SHA-256.
6. **Centralized Health Check Automation & Grafana Alerting**: Script monitoring real-time (`healthcheck.sh`) dan Alertmanager Grafana saat ada indikasi penurunan performa server.

---

## Verifikasi Dokumen

Dokumen [`read.md`](file:///root/cloudvault/read.md) telah diverifikasi secara penuh:
- Spasi berlebih telah dibersihkan.
- Semua seksi (Project Overview, Scope, Tech Stack, Architecture, Advanced Features, Responsibilities, Security, Maintenance, Development Phases, Deliverables) tersusun secara hierarkis dan jelas.

---

## Update: Perbaikan Konsistensi & Kelengkapan (Round 2)

Dokumen [`read.md`](file:///root/cloudvault/read.md) diperbarui kembali untuk menutup celah konsistensi teknis dan melengkapi seksi yang kurang, berdasarkan verifikasi terhadap rilis Debian 13 (Trixie) dan dokumentasi resmi Nextcloud.

### 1. Konsistensi Versi PHP: 8.3 → 8.4
- **Akar masalah**: Debian 13 (Trixie) mengirim PHP **8.4** secara native. PHP 8.3 hanya tersedia lewat repositori pihak ketiga (packages.sury.org), bertentangan dengan mandat *"Every service MUST be installed directly on Debian 13 using APT"*.
- **Keputusan**: Seluruh penyebutan PHP 8.3 diganti menjadi **PHP 8.4** (termasuk `php8.4-fpm`, `/etc/php/8.4/`, `/run/php/php8.4-fpm.sock`, `php8.4-fpm.log`, diagram Mermaid, dan deliverables).

### 2. Perbaikan Header HSTS (Preload Compliance)
- Nilai `max-age=15768000` (6 bulan) **tidak memenuhi syarat preload** yang mewajibkan minimal 1 tahun (31536000 detik).
- Diubah menjadi `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` (2 tahun, nilai rekomendasi hstspreload.org).

### 3. Koreksi Konfigurasi Redis Nextcloud
- `redis.remember_without_overwritten` **bukan** parameter resmi Nextcloud.
- Diganti dengan blok konfigurasi standar yang valid: `memcache.local`, `memcache.distributed`, `memcache.locking` → `\OC\Memcache\Redis` beserta array `redis` (`host`, `port`, `password`).

### 4. Perbaikan Pemantauan Nginx
- `Nginx VTS Exporter` membutuhkan modul pihak ketiga yang harus dikompilasi sendiri (melanggar prinsip native).
- Diganti dengan **`nginx-prometheus-exporter`** yang membaca `ngx_http_stub_status_module` (tersedia native di paket Nginx Debian).

### 5. Penambahan Paket Modul Brotli
- Kompresi Brotli membutuhkan modul `libnginx-mod-http-brotli-filter` yang tersedia native di Debian Trixie.
- Ditambahkan ke Technology Stack dan Deliverables agar instalasi eksplisit.

### 6. Penyempurnaan Nilai CSP
- Placeholder `Content-Security-Policy: default-src 'self' ...` dilengkapi menjadi nilai produksi lengkap (script-src, style-src, img-src, font-src, connect-src, frame-ancestors).

### 7. Penambahan Seksi yang Kurang
- **Prerequisites**: hardware minimum, swap, FQDN/DNS, port jaringan, timezone & NTP/chrony.
- **PostgreSQL Tuning**: contoh nilai konkret `postgresql.conf` (shared_buffers, effective_cache_size, work_mem, maintenance_work_mem, WAL, SSD tuning).
- **SSH Hardening**: `PermitRootLogin`, `PasswordAuthentication no`, `MaxAuthTries`, `AllowTcpForwarding`.
- **Redis Hardening**: `bind 127.0.0.1`, `protected-mode`, `requirepass`, `rename-command`, `maxmemory`/`maxmemory-policy`.
- **AppArmor ClamAV**: penyesuaian profil agar clamd dapat memindai direktori Nextcloud.
- **Certbot Renewal**: `--deploy-hook "systemctl reload nginx"` untuk OCSP stapling.
- **Fail2ban Recovery**: perintah `fail2ban-client status`/`unbanip` dan `ignoreip`.
- **Monitoring Exposure**: Prometheus/eksporter di-bind ke localhost; Grafana hanya via reverse proxy TLS.
- **`maintenance.sh` & `restore.sh`**: deskripsi tugas pemeliharaan harian (`occ` commands sebagai `www-data`) dan prosedur restore.

---

## Status Akhir

- [x] Versi OS konsisten: Debian 13 (Trixie).
- [x] Versi paket sesuai repositori native Debian (PHP 8.4, PostgreSQL 17, Redis 7, Nginx 1.26, Brotli module).
- [x] Konfigurasi Nextcloud mengacu parameter resmi (`config.sample.php`).
- [x] Seksi Prerequisites, Security, Maintenance, dan Monitoring lengkap.
- [x] 6 Advanced Production Features tetap dipertahankan.

---

## Update: Implementasi Deliverable (Round 3)

Spesifikasi [`read.md`](file:///root/cloudvault/read.md) telah diimplementasikan menjadi
kumpulan script operasional, file konfigurasi produksi, dan dokumentasi lengkap.

### 1. Script Operasional (`scripts/`)
- **`install.sh`** — installer bertahap (9 phase) dengan CLI stage:
  `prep`, `packages`, `database`, `nextcloud`, `web`, `security`, `features`,
  `monitoring`, `backup`, dan `all`. Idempotent, menghasilkan password acak yang
  disimpan di `/opt/cloudvault/.secrets/cloudvault.env`.
- **`backup.sh`** — backup terenkripsi **AES-256-CBC (PBKDF2)**: `pg_dumpall` atomik,
  arsip config, rsync mirror incremental untuk data, verifikasi **SHA-256**, rotasi
  retensi (7 daily / 4 weekly / 12 monthly), mode `verify` & `clean`.
- **`restore.sh`** — restore penuh (config → DB → data) dengan maintenance mode,
  perbaikan permission, dan verifikasi integritas arsip.
- **`healthcheck.sh`** — status 7 service + UFW, disk %, memori %, load, masa berlaku
  sertifikat TLS, dan Nextcloud `occ status`; output human-readable & `--json`.
- **`maintenance.sh`** — `occ db:convert-filecache-bigint`, `db:add-missing-indices`,
  `db:add-missing-primary-keys`, `db:add-missing-columns`, `files:cleanup`,
  `trashbin:expire`, `versions:expire`, `preview:pre-generate`, `files:scan --all`,
  `maintenance:repair` — dijalankan sebagai `www-data`.

Semua script lolos `bash -n` (syntax check); konfigurasi Nginx lolos `nginx -t`.

### 2. Konfigurasi Produksi (`config/`)
- **Nginx** (`nginx.conf` + `sites-available/cloudvault.conf`): TLS 1.3/1.2 + OCSP
  stapling, HSTS preload, CSP, rate limiting (login/api/generic),
  `client_max_body_size 10G`, Brotli + Gzip, `stub_status` loopback untuk
  `nginx-prometheus-exporter`, deny path sensitif. **Teruji `nginx -t` sukses**
  (hanya peringatan OCSP pada sertifikat dummy test). Catatan: direktif
  `brotli_static` dihapus karena paket Debian `libnginx-mod-http-brotli-filter`
  hanya menyediakan modul filter (kompresi dinamis).
- **PHP-FPM** (`www.conf`): pool dynamic, OPcache+JIT, `memory_limit 1G`,
  `upload_max_filesize 10G`.
- **PostgreSQL 17**: blok tuning (shared_buffers, effective_cache_size, WAL, SSD).
- **Redis 7**: hardening (bind loopback, requirepass, rename-command, maxmemory).
- **Fail2ban**: jail `nextcloud`, `nginx-auth`, `nginx-botsearch`, `sshd` + filter
  regex Nextcloud auth log; aksi ban via UFW.
- **UFW** (`ufw-setup.sh`) & deploy-hook renew certbot (`certbot-renew-hook.sh`).
- **Prometheus** (`prometheus.yml`, `alert.rules.yml`) + eksporter loopback.

### 3. Dokumentasi (`docs/`)
`README.md`, `INSTALLATION.md`, `DEPLOYMENT.md`, `SYSTEM_ARCHITECTURE.md`,
`SECURITY.md`, `PERFORMANCE.md`, `BACKUP.md`, `MONITORING.md` — sesuai daftar
Deliverables di `read.md`.

### 4. Benchmark (`benchmark/`)
`benchmark.sh` untuk mengukur response time, TLS handshake, rasio kompresi
Brotli/Gzip, dan hasil disimpan ke `benchmark/results/`.

## Status Implementasi

- [x] 5 script operasional lengkap & lolos validasi syntax.
- [x] Konfigurasi 8 komponen produksi tersedia di `config/`.
- [x] 8 dokumen deliverable dibuat.
- [x] Script benchmark tersedia.
- [ ] (Verifikasi lintas-perangkat) Uji deploy di server Debian 13 riil.
