# AUTOMATION.md

How the CloudVault deployment is automated, from `git clone` to a running,
Telegram-notified build. Describes the ways to drive `scripts/install.sh`
(wizard or direct stage) and the exact deployment flow.

---

## Overview

Deployment is **wizard-driven**. After the repo is on the server (clone or
`scp` to `/opt/cloudvault`), the client runs `install.sh`: the wizard asks ~5
interactive questions, then the rest is fully automated and idempotent (a failed
step stops the run and is resumed on the next invocation).

```
CLIENT (target server: Debian / Ubuntu)
  1. git clone https://github.com/wtfaboutyou/Cloud-Vault.git /opt/cloudvault
  2. cd /opt/cloudvault && sudo bash scripts/install.sh   ← entry point
       └─ wizard: ~5 questions, then fully automated phases 1-10
```

Ways to invoke it:

| Invocation                                          | Behaviour |
|-----------------------------------------------------|-----------|
| `sudo bash scripts/install.sh`                      | Interactive wizard → full automated deploy |
| `sudo bash scripts/install.sh <stage>`              | Run a single phase directly (power users / resume) |
| `sudo bash scripts/install.sh update`               | Idempotent update/maintenance (re-apply config + `occ upgrade`, safe re-run) |

Running it is now literally two lines (clone + wizard); everything inside is
orchestrated by `install.sh`, whose stages can each be run directly.

---

## Deployment Flow

```mermaid
graph TD
    A[Client: clone repo ke /opt/cloudvault] --> B[install.sh tanpa argumen]
    B --> D{Argumen stage?}
    D -->|tanpa argumen (wizard)| E[detect_os: /etc/os-release]
    D -->|stage: prep, packages, ...| F[Jalankan phase spesifik]
    E --> G[Wizard: 5 input interaktif]
    G --> H[run_wizard: set environment variables]
    H --> I[Full deploy: Phase 1-10 otomatis]
    F --> I
    I --> J{Sukses semua phase?}
    J -->|ya| K[telegram_final_ping: CloudVault connected]
    K --> L[Cetak laporan audit & credential]
    J -->|tidak| M[Stop di step yang gagal + report step mana]
    M -->|jalanin lagi, idempoten lanjut| I
```

---

## Components of `install.sh`

### 1. OS detection — `detect_os()` (automatic, not asked)

Reads `/etc/os-release` and picks the correct native PHP version. No wizard
prompt is required — the client never has to think about the distro.

| OS                      | PHP version |
|-------------------------|-------------|
| Debian 13 (Trixie)      | 8.4         |
| Debian 12 (Bookworm)    | 8.2         |
| Ubuntu 24.04 (Noble)    | 8.3         |
| Ubuntu 22.04 (Jammy)    | 8.1         |
| Anything else           | fails with a clear message |

### 2. Interactive wizard — `run_wizard()`

Runs once at the start. Collects **5 answers in order**; the **last input is the
Telegram chat id**, after which there is no further client input.

```text
1. Domain (FQDN or server IP)
2. Admin email
3. Admin password            (blank = auto-generate)
4. Telegram bot token        (from @BotFather)
5. Telegram chat id          (e.g. -1001234567890)    ← LAST input
```

The wizard writes the answers into the same environment variables consumed by
the phases (`NC_DOMAIN`, `ADMIN_EMAIL`, `NC_ADMIN_PASS`), and — if both Telegram
values are supplied — enables `ENABLE_TELEGRAM=yes` + `ENABLE_WATCHTOWER=yes`
and stores the token/chat id for the final test ping.

> **Re-run aware** — if `telegram.env` already exists (from a previous run), a
> wizard re-run with new Telegram values **refreshes** the stored token/chat id
> instead of silently keeping the old ones.

### 3. Automated phases — `Phase 1-10`

Everything after the wizard is fully automatic (no input), and each phase is
idempotent:

| Phase | Stage name  | What it does |
|-------|-------------|--------------|
| 1 | `prep`      | timezone, NTP, swap, base packages |
| 2 | `packages`  | PHP-FPM, Nginx, PostgreSQL, Redis, Fail2ban, ClamAV |
| 3a| `database`  | PostgreSQL tuning + role, Redis hardening |
| 3b| `nextcloud` | download Nextcloud (~300 MB), config.php, `occ install` |
| 4 | `web`       | Nginx site, Brotli, PHP tuning, TLS (certbot) |
| 5 | `security`  | UFW, Fail2ban jails, SSH hardening |
| 6 | `features`  | ClamAV `files_antivirus`, systemd maintenance timers |
| 7 | `monitoring`| Prometheus, exporters, Grafana, Fail2ban security metrics, security alert rules (`ENABLE_MONITORING=yes`), Grafana security dashboard template |
| 8 | `backup`    | backup dir + AES-256 encryption key |
| 9 | `watchtower`| Watchtower foundation service |
| 10| `telegram`  | Telegram bot + linking (`ENABLE_TELEGRAM=yes`) |
| U | `update`    | Idempotent update/maintenance (re-apply config, `occ upgrade` + `repair`, refresh timers/cron, healthcheck) |

### 4. Finalisation — `telegram_final_ping()`

After a successful deploy, sends **"CloudVault connected"** to the admin's
Telegram as the observable sign that installation finished. Verified by checking
the Telegram API returns **HTTP 200** (not just "curl exited 0"), so a bad
token/chat id is honestly reported instead of falsely claiming success.

---

## Idempotency & Resume

- Every phase guards against re-doing work (e.g. only writes config files if
  absent, only creates users/keys if missing).
- Before dispatching, `install.sh` reloads persisted values from
  `.secrets/cloudvault.env`, `.secrets/telegram.env` and `.secrets/watchtower.env`
  (via a safe line-parser, never `source`, because the files contain unquoted
  libpq-style `VAR=value with spaces` DSNs). Resume and `update` therefore reuse
  the installed domain, DB/Redis passwords and Telegram creds instead of the
  script defaults; variables exported in the caller's environment still win.
- If a step fails (apt error, Nextcloud tarball download failure, ...), the
  script stops and reports **which step failed**.
- The client simply runs `sudo bash scripts/install.sh <gagal-stage>` again (or
  the wizard) — it resumes from the unfinished step.
- **Telegram config is re-run aware**: re-running the wizard with new
  token/chat id updates the stored `.secrets/telegram.env` values (refresh via
  `sed` only when a new value is supplied; otherwise existing values are kept).

---

## Update / maintenance (`install.sh update`)

Routine upgrades shouldn't need a re-install. The `update` stage is a safe,
idempotent maintenance run that **never touches user data**:

1. **Pulls** the latest repo (if `/opt/cloudvault` is a git checkout).
2. **Refreshes** Nginx config + reloads (only after `nginx -t` passes).
3. **Re-applies** site-level Nextcloud settings via `occ` (and falls back to the
   already-configured `server_name` if the domain wasn't persisted).
4. **Runs** `occ upgrade` and `occ maintenance:repair` (official NC update steps).
5. **Refreshes** cron and systemd timers (grep-guarded, overwrite-safe).
6. **Refreshes** security monitoring (fail2ban collector + `alert.rules.yml`,
   reloads Prometheus).
7. **Health check** at the end.

> Unlike `phase3_nextcloud` (which *writes* `config.php`), `update` deliberately
> does **not** rewrite `config.php` or regenerate instance secrets — so it is
> safe on a live install.

```bash
sudo bash scripts/install.sh update
```

---

## Attack detection & security monitoring

CloudVault ships a thin security observability layer on top of the existing
monitoring stack (Prometheus + Grafana + Alertmanager → Watchtower → Telegram).
It adds attack-detection signals without a separate IDS service:

| Piece | What it does |
|-------|--------------|
| `scripts/fail2ban-collector.sh` | Polls Fail2ban and writes low-cardinality Prometheus textfile metrics (bans per jail, active bans, failed attempts). Runs on a systemd timer. |
| `config/prometheus/alert.rules.yml` (`cloudvault-security`) | Alerts on banned-IP count, ban spikes, HTTP rate spikes, and TCP connection surges. |
| `config/grafana/dashboards/security.json` | "CloudVault Security" Grafana dashboard (banned IPs, per-jail bans, HTTP rate, TCP connections). Import manually. |

All attack signals route through the same Alertmanager → Watchtower path as
infra alerts, so they land in Telegram for the admin.

> Deployed together with `monitoring` (or refreshed by `update`). The collector
> deliberately avoids high-cardinality labels (no per-IP series), keeping
> Prometheus cheap even under heavy probing.

---

## Failure handling summary

```text
apt error / download error / TLS failure
        │
        ▼
install.sh stops  →  prints step name + hint
        │
        ▼
client re-runs ./install.sh  →  skips done steps, continues unfinished
```

---

## Secrets persisted

| Variable                      | Where written |
|-------------------------------|---------------|
| `NC_DOMAIN`, `ADMIN_EMAIL`    | `.secrets/cloudvault.env` |
| `NC_ADMIN_PASS`, `NC_DB_PASS` | `.secrets/cloudvault.env` |
| Telegram token / chat id      | `.secrets/telegram.env` (enables bot) |

> **Back up `/opt/cloudvault/.secrets/` and the AES-256 backup key offsite.**
