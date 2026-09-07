# DISASTER_RECOVERY.md

Runbook untuk pemulihan CloudVault dari bencana, termasuk **bare-metal
recovery** (Tier-2) dan prosedur, target RTO/RPO, serta pengujian berkala.

---

## 1. Konsep — Dua Tier Recovery

| Tier | Skenario | Tool | Kanan |
|---|---|---|---|
| **Tier 1 — Application restore** | Server MASIH hidup; stack rusak / data korup / mau rollback | `scripts/restore.sh` (sudah ada) | Server hidup |
| **Tier 2 — Full bare-metal restore** | Server MATI total / disk rusak / pindah ke hardware baru | `scripts/dr-recover.sh` ATAU `ansible-playbook dr-recover.yml` | Server fresh OS |

Tier-2 adalah jawaban atas skenario "industri": **server baru (fresh OS) →
satu perintah → CloudVault hidup kembali** dengan data utuh dari backup
terenkripsi.

---

## 2. Target RTO / RPO

| Metrik | Target | Catatan |
|---|---|---|
| **RTO** (Recovery Time Objective) | **< 1 jam** | Fresh OS + playbook `dr-recover.yml` |
| **RPO** (Recovery Point Objective) | **24 jam** (konsisten dengan backup harian) | Backup otomatis tiap 03:00 |
| **Cadangan (backup)** | max data loss = 1x backup harian | Plus USB offsite bila aktif |

> RTO/RPO ini adalah **target desain**, harus diverifikasi dengan uji DR
> berkala (lihat §6) dan dicatat hasilnya.

---

## 3. Prasyarat DR (wajib dijaga SEBELUM bencana)

1. **Backup aktif** — timer `cloudvault-backup.timer` (03:00) jalan; verifikasi
   rutin `backup.sh verify`.
2. **Backup key** (`/etc/cloudvault/backup.key`) **disimpan di tempat aman di
   luar server**: password manager, host lain, atau kopi fisik. Tanpa kunci ini
   arsip terenkripsi TIDAK bisa dibuka.
3. **Backup offsite** (opsional, disarankan) — USB dengan label
   `CLOUDVAULT-BACKUP` di-mirror via `scripts/usb-backup.sh`; fisiknya **dipindah
   ke lokasi berbeda** secara berkala. Ini satu-satunya lapis yang selamat kalau
   server (dan backup lokalnya) hancur total.
4. **Ansible Vault** berisi kredensial admin/DB/Redis/Telegram (untuk membangun
   ulang stack dari control node).
5. **Catatan domain/DNS** — pastikan `A`/`AAAA` record dan port 80/443 sudah
   diarahkan ke server pengganti.

---

## 4. Prosedur DR — Opsi A: Ansible Playbook (control node tersedia)

Prasyarat: fresh OS Debian 13/12 atau Ubuntu 24.04/22.04, SSH reachable dari
control node, `backup.key` ada di control node.

```bash
# 1. Siapkan inventory (copy dari template & isi host target)
cp ansible/inventory/hosts.example.yml ansible/inventory/hosts.yml

# 2. Siapkan Vault dengan kredensial (sekali saja)
ansible-vault create ansible/inventory/group_vars/vault.yml

# 3. Jalankan recovery — SATU PERINTAH
ansible-playbook playbooks/dr-recover.yml \
    -e cloudvault_backup_key_local=$HOME/vault/cloudvault/backup.key \
    --ask-vault-pass
```

Alur yang dijalankan playbook:

```
preflight (key + reachability)
   → bootstrap (base OS + swap)
   → mount USB (kalau cloudvault_usb_enabled=yes, by LABEL)
   → install.sh all   (bangun stack utuh di fresh OS)
   → tarik arsip terenkripsi (lokal / USB)
   → restore.sh       (config + PostgreSQL + data)
   → healthcheck + occ maintenance:repair
   → ringkasan + URL akses
```

Jika ingin restore toreh-arsip tertentu:

```bash
ansible-playbook playbooks/dr-recover.yml \
    -e cloudvault_backup_key_local=$HOME/vault/cloudvault/backup.key \
    -e cloudvault_restore_archive=/opt/cloudvault/backup/daily/cloudvault-daily-20260315-030000.tar.enc \
    --ask-vault-pass
```

---

## 5. Prosedur DR — Opsi B: `dr-recover.sh` fallback (hanya shell ke server)

Gunakan ketika **control node/Ansible tidak tersedia** — kamu hanya punya akses
shell (root) ke server fresh OS.

```bash
# 0. (kalau repo belum ada)
git clone https://github.com/wtfaboutyou/Cloud-Vault.git /opt/cloudvault

# 1. Letakkan ORIGINAL backup.key
sudo install -m 600 $HOME/backup.key /etc/cloudvault/backup.key

# 2. (opsional) colok USB offsite, lalu:
sudo bash /opt/cloudvault/scripts/dr-recover.sh --from-usb

#    atau pakai backup lokal:
sudo bash /opt/cloudvault/scripts/dr-recover.sh
```

Alur sama dengan playbook: `install.sh all` → tarik backup → `restore.sh` →
healthcheck + repair → notif `RECOVERY_COMPLETED` ke Telegram.

---

## 6. Verifikasi Hasil Recovery

```bash
sudo bash /opt/cloudvault/scripts/healthcheck.sh       # semua hijau
sudo -u www-data php /var/www/nextcloud/occ status     # version skr
sudo -u www-data php /var/www/nextcloud/occ maintenance:repair
# Login admin + cek tautan file pernah ada, compare sha256 jk perlu.
```

---

## 7. Pengujian DR Berkala (wajib, monthly)

Tujuan: pastikan backup & prosedur benar-benar bekerja sebelum benar-benar
diperlukan. Kerugian uji: hanya waktu + CPU staging.

1. Spawn **staging** server (VM) fresh OS.
2. Jalankan prosedur DR (Opsi A atau B) terhadap staging.
3. Verifikasi: admin login, daftar user/file ada, `occ maintenance:repair` OK,
   sampel file hash cocok dengan yang asli.
4. Catat hasil (tanggal, RTO aktual, catatan) di `docs/assets/` atau
   `LOG_DIR` — bukti bagi auditor/kepatuhan.
5. (Opsional) `restore.sh verify` rutin tiap minggu sebagai smoke test ringan.

---

## 8. Skenario Bencana & Respons

| Skenario | Layer yang selamat | Respons |
|---|---|---|
| File terhapus / korup | Backup lokal (server hidup) | `restore.sh` (Tier-1) |
| DB korup, server hidup | Backup lokal | `restore.sh` (Tier-1) |
| Disk server rusak | Backup lokal mungkin hilang | **Tier-2** + USB offsite |
| Server kehilangan seluruh data/OS | Backup lokal hilang | **Tier-2** + USB offsite |
| Seluruh ruangan server musnah | Hanya USB/penggandaan luar | **Tier-2** + USB (fisik terpisah) |

---

## 9. Mitigasi / catatan kejujuran

- **Backup key = pintu menuju semua arsip.** Hilang = data tak terbaca.
  Simpan minimal 2 salinan di lokasi berbeda.
- **USB bukan offsite geografis murni** kalau masih satu bangunan. Untuk
  kepatuhan ketat / geo-redundancy, tambahkan object storage offsite
  (Backblaze B2 / S3 via `rclone`) sebagai lapis tambahan.
- `install.sh all` pada fresh host akan membuat instance kosong dulu, lalu
  `restore.sh` menimpa config/DB/data dari arsip — aman karena runbook ini
  menjalankan keduanya berurutan dalam satu proses.

---

## 10. Ringkasan Perintah (Cheat-Sheet)

```bash
# Backup & verifikasi
sudo bash /opt/cloudvault/scripts/backup.sh
sudo bash /opt/cloudvault/scripts/backup.sh verify

# Offsite USB
sudo bash /opt/cloudvault/scripts/usb-backup.sh          # mirror lokal -> USB
sudo bash /opt/cloudvault/scripts/usb-backup.sh --umount # mirror + unmount (amankan USB)

# Tier-1 (server hidup)
sudo bash /opt/cloudvault/scripts/restore.sh
sudo bash /opt/cloudvault/scripts/restore.sh --from-usb  # tarik dari USB dulu

# Tier-2 (fresh OS) — DUA pilihan, pilih satu
sudo bash /opt/cloudvault/scripts/dr-recover.sh --from-usb
ansible-playbook ansible/playbooks/dr-recover.yml -e cloudvault_backup_key_local=$HOME/backup.key --ask-vault-pass
```