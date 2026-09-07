# BACKUP.md

Backup, retention, encryption, and disaster-recovery reference for CloudVault.

---

## 1. What Is Backed Up

| Item | Source | Method |
|------|--------|--------|
| Database | PostgreSQL | `pg_dumpall` (global roles + databases), atomic single file |
| Configuration | `/var/www/nextcloud/config` | tar.gz + `config.php` copy |
| User data | `/var/www/nextcloud/data` | rsync incremental mirror → tar.gz |

All four artifacts are bundled into one tar and **encrypted with AES-256-CBC**
(PBKDF2, 200k iterations) using the key at `/etc/cloudvault/backup.key`.

## 2. Where Backups Live

```
/opt/cloudvault/backup/
├── daily/     cloudvault-daily-YYYYMMDD-HHMMSS.tar.enc (+ .sha256)
├── weekly/
├── monthly/
├── mirror/    incremental rsync mirror of data (reused across runs)
└── tmp/
```

## 3. Scheduling

systemd timers (created by `install.sh features`):

| Timer | Schedule | Job |
|-------|----------|-----|
| `cloudvault-maintenance.timer` | 02:30 daily | `maintenance.sh` |
| `cloudvault-backup.timer` | 03:00 daily | `backup.sh` |

Label derivation when run by timer: **monthly** on the 1st, **weekly** on Mondays,
**daily** otherwise.

## 4. Retention

| Tier | Keep |
|------|------|
| daily | 7 |
| weekly | 4 (28 days) |
| monthly | 12 (1 year) |

Pruning happens automatically after every run (`prune_retention`).

## 5. Manual Operations

```bash
# run a backup now (label auto-derived)
sudo bash /opt/cloudvault/scripts/backup.sh

# force a specific tier
sudo bash /opt/cloudvault/scripts/backup.sh weekly

# integrity verification (SHA-256 + decrypt + tar test) of latest archive
sudo bash /opt/cloudvault/scripts/backup.sh verify

# verify a specific archive
sudo bash /opt/cloudvault/scripts/backup.sh verify /opt/cloudvault/backup/daily/cloudvault-daily-20260715-030000.tar.enc

# prune only
sudo bash /opt/cloudvault/scripts/backup.sh clean
```

## 6. The Encryption Key

- Stored at `/etc/cloudvault/backup.key` (600 perms), created by `install.sh backup`.
- Used as the passphrase for `openssl enc`; salt + IV are embedded in the archive
  header, so decryption is self-contained with the key alone.
- **Back up this key offsite** (password manager, separate host, printed copy).
  Without it, archives are unrecoverable.

## 7. Restore (Disaster Recovery)

`restore.sh` decrypts an archive, verifies integrity, and restores in order:

1. Puts Nextcloud in **maintenance mode** and stops `nginx`/`php-fpm`.
2. Restores `/var/www/nextcloud/config`.
3. Drops & recreates the PostgreSQL database, imports the `pg_dumpall` dump.
4. Extracts the data directory and fixes ownership/permissions.
5. Restarts services and exits maintenance mode.

```bash
# restore the most recent archive
sudo bash /opt/cloudvault/scripts/restore.sh

# restore a specific archive
sudo bash /opt/cloudvault/scripts/restore.sh /opt/cloudvault/backup/daily/cloudvault-daily-20260715-030000.tar.enc

# pull the archive from the USB offsite mirror first, then restore
sudo bash /opt/cloudvault/scripts/restore.sh --from-usb
```

> **Full bare-metal recovery** (server mati total) bukan rollback biasa — lihat
> [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) untuk `dr-recover.sh` /
> `dr-recover.yml` (Tier-2).

### Manual decrypt (emergency)

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -salt \
  -pass file:/etc/cloudvault/backup.key \
  -in archive.tar.enc -out plain.tar
tar -tvf plain.tar
```

## 8. Recovery Testing

1. Monthly: restore to a **staging** instance and run `occ maintenance:repair`.
2. Verify database tables load and admin login works.
3. Spot-check file integrity by hashing a file in the restore and comparing with the
   original (`sha256sum`).

## 9. Offsite Replication

Disaster recovery sejati membutuhkan backup yang **selamat walau server mati
total**. Backups lokal (`/opt/cloudvault/backup`) hilang kalau disk/server
hilang — jadi pastikan ada salinan di luar server.

### A. Self-hosted USB (disarankan untuk project ini)

`scripts/usb-backup.sh` memirror backup terenkripsi ke USB dengan label
`CLOUDVAULT-BACKUP` (mount by LABEL — sama-sama jalan di VM setelah USB di-attach
oleh hypervisor, maupun di fisik langsung):

```bash
sudo bash /opt/cloudvault/scripts/usb-backup.sh            # mirror lokal -> USB
sudo bash /opt/cloudvault/scripts/usb-backup.sh --umount   # mirror + unmount (aman dibawa)
```

- Dipanggil otomatis di akhir `backup.sh` (gagal mirror TIDAK membuat backup
  dianggap gagal — dilaporkan terpisah).
- Simpan **fisik USB di lokasi berbeda** dari server (ruang/gedung lain).
- Tarik saat recovery: `restore.sh --from-usb`, atau `dr-recover.sh --from-usb`.

### B. Object storage (opsional/level berikutnya)

Untuk offsite geografis murni (mis. Backblaze B2, S3-compatible), mirror via
`rclone` setelah tiap backup:

```bash
# in /etc/systemd/system/cloudvault-backup.service  (or a cron)
rclone copy /opt/cloudvault/backup/daily remote:cloudvault/daily
```

Arsip sudah terenkripsi AES-256, jadi aman meski disimpan di cloud publik.
Tambahkan salinan `backup.key` di lokasi yang sama dengan offsite storage.

### Aturan kunci

- **Back up `backup.key` offsite** (password manager, host terpisah, kopi fisik).
  Tanpa kunci, semua arsip tidak dapat dibaca.

## 10. What Is NOT Backed Up

- Temporary/`tmp` content inside data (excluded trashbin).
- The operating system itself — use `dpkg --get-selections` + config backups, or a
  separate OS image, for full disaster recovery.
