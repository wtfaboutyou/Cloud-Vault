# IaC (Ansible) + Disaster Recovery — KONSEP FINAL (Handoff/Checkpoint)

> Dokumen pengaman. Kalau konteks hilang (VM mati, sesi baru), baca ini dulu —
> ini keputusan & arah final yang sudah disepakati, lalu baru eksekusi.

## TUJUAN UTAMA (sesuai masukan mentor)
1. **Automation satu-klik** untuk install/deploy memakai tool IaC standar industri.
2. **Recovery cepat saat bencana** (disaster). Backup sudah ada & terenkripsi,
   tinggal bikin cara recovery-nya.
3. Pelengkap backup offsite biar recovery tahan server mati total.

## KEPUTUSAN FINAL (sudah disepakati lewat diskusi)
| Poin | Keputusan |
|---|---|
| Tool IaC | **Ansible** (bukan Terraform) — cocok bare-metal/no-Docker |
| Peran Ansible | **Orchestrator `install.sh`** (push repo + set env + jalankan fase idempotent) — BUKAN refactor penuh per-role (hemat, minim risiko regression) |
| DR | **1-command bare-metal recovery**: server fresh OS → bangun stack utuh + pulihkan data → verifikasi → notif |
| Delivery DR | **Playbook Ansible + fallback bash script** (`dr-recover.sh`) — redundancy bila control node mati |
| Backup offsite | **USB sendiri (self-hosted, gratis)** — konsisten filosofi no-Docker/no-cloud |
| Catatan offsite lanjutan | Backblaze B2 (object storage via rclone) disebut sebagai opsi lanjutan bila mau offsite geografis; user sudah punya akun B2 tapi **belum dipilih** sebagai primary |
| Output | **Kode + docs** (bisa direview mentor) |

## ARAH TEKNIS
### Ansible
- Struktur: `ansible/` → `ansible.cfg`, `inventory/` (`hosts.yml`, `group_vars/all.yml`),
  `playbooks/` (`deploy.yml`, `update.yml`, `dr-recover.yml`, `site.yml`),
  `roles/` (`cloudvault_bootstrap`, `cloudvault_deploy`, `cloudvault_dr`),
  `vars/secret.example.yml` (rahasia anonymized).
- Model: control node (laptop/CI) via SSH → target (server CloudVault). Agentless.
- `deploy.yml` = bootstrap (base OS/ssh/swap) + deploy (push repo + jalankan
  `install.sh` non-interaktif via env vars → `all`) + healthcheck.
- `update.yml` = `install.sh update` (idempotent, tidak menyentuh data).

### Disaster Recovery (bare-metal)
- `dr-recover.yml` (Ansible) + `dr-recover.sh` (fallback bash) = SATU PERINTAH.
- Alur: preflight (ssh/sudo/akses backup) → `install.sh` bangun stack utuh →
  tarik backup terenkripsi (lokal/USB) → `restore.sh` (config+DB+data) →
  verifikasi (`healthcheck.sh` + `occ maintenance:repair` + login test) →
  notif Telegram `RECOVERY_COMPLETED/FAILED`.
- 2-tier DR: Tier1 = application restore (`restore.sh`, server hidup);
  Tier2 = full bare-metal (`dr-recover`, server mati total / pindah host).
- Kunci DR: `backup.key` & backup Wajib disimpan di luar server yang direcovery.

### Offsite USB (self-hosted)
- `scripts/usb-backup.sh` — mount USB (pakai LABEL, bukan hardcode `/dev/sdX`) →
  `rsync -a --delete` backup → cermin offsite.
- Netral VM & fisik: di VM perlu attach/passthrough USB dulu (hypervisor);
  di fisik langsung kebaca `/dev/sdX`. Auto-detect via LABEL=`CLOUDVAULT-BACKUP`,
  opsi tambah `/etc/fstab` (`noauto,users`).
- Sisipkan di `backup.sh` setelah backup sukses → push ke USB.
- `restore.sh`/`dr-recover` bisa tarik dari USB bila backup lokal hilang.
- Catatan jujur: USB bukan "offsite geografis" kalau satu ruangan; simpan di
  lokasi beda / dampai naik ke B2 utk geografis sejati.

### Docs (yang perlu dibuat/diupdate)
- Baru: `docs/DISASTER_RECOVERY.md` (runbook: RTO/RPO, prosedur, pengujian bulanan).
- Update: `BACKUP.md` (section offsite USB + B2 opsional), `README.md`, index docs.
- Rencana awal sudah ada di `docs/IAAS_AND_DR_PLAN.md` (bisa jadi basis).

### Pengujian (industri)
- Uji DR berkala (bulanan) → restore ke staging + `occ maintenance:repair` + login.
- `restore.sh verify` (decrypt+tar test) sebagai rutinitas.
- CI opsional: `.github/workflows/iac-validate.yml` → lint YAML + `ansible-playbook --syntax-check`.

## RISIKO & KOMPROMI
- Ansible panggil `install.sh`, bukan kelola tiap file declaratively → diterima
  (kurangi duplikasi/regression; install.sh sudah idempotent & version-controlled).
- Butuh control node + SSH key → satu laptop/runner cukup; secret di vault.
- DR gagal tanpa key & backup offsite → dokumentasi tegas: Wajib simpan di luar.
- USB 1-lokasi → bukan geografis murni; dicatat sebagai keterbatasan + opsi B2.

## STATUS
- **Tahap: DISKUSI/RENCANA — belum ada kode yang dieksekusi.**
- Yang sudah dibangun di repo (EXISTING, reuse, jangan dihancurkan):
  `scripts/install.sh` (wizard, fase idempotent 1-10), `backup.sh`, `restore.sh`,
  `healthcheck.sh`, `config/`, Watchtower/Telegram.
- Filosofi project: **tanpa Docker/container, native APT + systemd, self-hosted.**
