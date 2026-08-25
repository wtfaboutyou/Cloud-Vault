# CloudVault — Alur Video Demonstrasi

Dokumen ini berisi storyboard lengkap untuk video demonstrasi CloudVault,
platform cloud storage self-hosted enterprise-grade di atas Debian 13 (Trixie).

- **Target durasi:** ± 8–10 menit
- **Tema:** Deploy → Fitur → Keamanan → Operasional
- **Format:** Penjelasan + live demo di layar

---

## Segmen 0 — Intro (0:00–0:30)

| Visual | Narasi (Bahasa Indonesia) |
|---|---|
| Logo CloudVault, fade in judul | "CloudVault adalah platform cloud storage enterprise-grade, self-hosted sepenuhnya di atas Debian 13 Trixie." |
| Overlay stack teknologi | "Dibangun dengan Nginx, PHP 8.4, PostgreSQL 17, dan Redis 7 — tanpa Docker, semuanya terpasang native di sistem operasi." |

**On-screen text:** *Nginx + PHP 8.4 + PostgreSQL 17 + Redis 7 — No Docker.*

---

## Segmen 1 — Arsitektur Sistem (0:30–1:30)

**Visual:** Diagram arsitektur (dari `docs/SYSTEM_ARCHITECTURE.md`), zoom ke tiap layer.

| Lapisan | Narasi |
|---|---|
| Gateway | "Nginx menjadi gerbang utama: TLS 1.3, HTTP/2, Brotli + Gzip, dan rate limiting." |
| Aplikasi | "Nextcloud versi stabil terbaru berjalan di atas PHP 8.4 FPM." |
| Data | "PostgreSQL 17 yang sudah di-tuning untuk SSD, plus Redis untuk cache dan lock." |
| Keamanan | "UFW, Fail2ban, ClamAV, dan AppArmor melindungi seluruh stack." |
| Monitoring | "Prometheus, Grafana, dan exporter memantau kesehatan layanan." |

---

## Segmen 2 — Live Demo: Login & Aplikasi (1:30–3:00)

**Visual:** Rekam layar browser.

1. Buka halaman demo `https://<domain>/demo/`.
   - Narasi: "Sebagai showcase, CloudVault menyediakan halaman login statis di `/demo/`."
   - Demo login: username `demo` / password `cloudvault` → muncul pesan sukses.
2. Buka URL utama CloudVault, login sebagai admin.
3. Tampilkan **Dashboard**: cuplikan file, storage, dan aktivitas.
4. Tampilkan **halaman Files**: unggah 1 file (misal PDF/5 MB), tunjukkan status upload.

> **Tips:** Persiapkan file contoh (dokumen + gambar) sebelum rekam agar alur lancar.

---

## Segmen 3 — Live Demo: Fitur Unggulan (3:00–5:00)

Berikut fitur yang paling kuat untuk ditunjukkan di video:

| Waktu | Fitur | Yang Ditampilkan |
|---|---|---|
| 3:00 | **ClamAV Auto-Scan** | Unggah file → cek log `clamdscan` / `nextcloud.log` bahwa file di-scan real-time sebelum tersimpan |
| 3:40 | **WebDAV / Client** | Konek aplikasi desktop/mobile ke endpoint WebDAV, upload file dari client |

---

## Segmen 4 — Keamanan (5:00–6:30)

**Visual:** Terminal (tmux) + split screen.

1. **UFW** — `sudo ufw status verbose` → tampilkan hanya port 22, 80, 443.
   - Narasi: "Firewall hanya membuka SSH dan web, semua port lain tertutup."
2. **Fail2ban** — `sudo fail2ban-client status nextcloud`.
   - Narasi: "Fail2ban memindai log Nginx dan Nextcloud, dan mem-banned IP percobaan brute-force secara otomatis."
   - **Opsional demo:** jalankan beberapa login gagal → tunjukkan IP masuk daftar banned.
3. **TLS Hardening** — `curl -sI https://<domain> | grep -i strict-transport-security` → tunjukkan header HSTS.
   - Narasi: "TLS 1.3 dengan OCSP Stapling dan HSTS preload, target skor A+ di SSL Labs."

---

## Segmen 5 — Operasional: Health, Backup, Maintenance (6:30–8:00)

**Visual:** Terminal.

1. **Health Check**
   ```bash
   sudo bash /opt/cloudvault/scripts/healthcheck.sh
   ```
   - Tampilkan semua layanan `OK` (nginx, php-fpm, postgresql, redis, fail2ban, clamav), status disk, memori, dan masa berlaku sertifikat SSL.

2. **Backup Terenkripsi**
   ```bash
   sudo bash /opt/cloudvault/scripts/backup.sh
   sudo bash /opt/cloudvault/scripts/backup.sh verify
   ```
   - Narasi: "Backup dienkripsi AES-256, diverifikasi SHA-256, dengan rotasi 7 harian / 4 mingguan / 12 bulanan."

3. **Maintenance Otomatis**
   - `systemctl list-timers cloudvault-*`
   - Narasi: "Timer systemd menjalankan cron Nextcloud tiap 5 menit plus maintenance harian: scan file, pre-generate preview, dan pembersihan orphan."

---

## Segmen 6 — Monitoring (8:00–9:00)

**Visual:** Grafana dashboard.

1. Buka Grafana → pilih dashboard CloudVault.
2. Tampilkan grafik: CPU, memori, disk, koneksi Nginx, dan metrik exporter.
3. Tampilkan **alert rules** (`config/prometheus/alert.rules.yml`).
   - Narasi: "Alertmanager memberi notifikasi otomatis saat layanan turun atau penggunaan storage melebihi 85%."

---

## Segmen 7 — Performa (9:00–9:30)

**Visual:** Terminal benchmark + hasil.

```bash
bash /root/cloudvault/benchmark/benchmark.sh
```

- Tampilkan hasil upload/download dari `benchmark/results/`.
- Narasi singkat: "Benchmark WebDAV menunjukkan throughput download stabil, berkat tuning Nginx, Brotli/Gzip, dan PHP-FPM."

---

## Segmen 8 — Penutup (9:30–10:00)

| Visual | Narasi |
|---|---|
| Ringkasan 6 fitur unggulan (animasi) | "Ringkasan: intrusion prevention, Brotli + TLS 1.3, ClamAV auto-scan, OCC automation, backup terenkripsi dengan retention, dan health check terpusat." |
| Repo + dokumentasi | "Seluruh kode, skrip, dan dokumentasi tersedia di repository — mulai dari install, deployment, security, hingga monitoring." |
| Layar akhir: logo + kontak | "Terima kasih." |

---

## Checklist Persiapan

- [ ] Pastikan semua layanan sehat: `sudo bash scripts/healthcheck.sh`
- [ ] Siapkan file contoh untuk upload (PDF, gambar, file 25 MB untuk benchmark)
- [ ] Test login demo di `/demo/` dan login admin Nextcloud
- [ ] Jika menampilkan OTP: pastikan kunci Resend aktif dan akun test siap
- [ ] Jika menampilkan GCS: pastikan bucket ter-mount
- [ ] Siapkan akun Grafana dengan dashboard CloudVault yang sudah di-import
- [ ] Latihan alur terminal sebelum rekam (hindari kesalahan ketik di depan kamera)
- [ ] Rekam dengan resolusi layar tinggi (≥ 1080p), terminal dengan font besar
- [ ] Matikan notifikasi OS selama perekaman
