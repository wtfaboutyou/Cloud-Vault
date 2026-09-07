#!/usr/bin/env bash
#
# dr-recover.sh - CloudVault FULL bare-metal disaster recovery (fallback path).
#
# Rebuilds a COMPLETELY fresh host (fresh OS install, no Ansible required)
# into a working CloudVault, pulling data from an encrypted backup.
#
# This is the operational fallback of the `dr-recover.yml` Ansible playbook:
#   * Playbook  → used when a control node is available.
#   * This script → used when you only have shell access to the fresh host.
#
# Flow:
#   1. preflight (root, repo present, OS supported)
#   2. build the full stack with `install.sh all`  (non-interactive via env vars)
#   3. fetch the encrypted backup (local disk or USB offsite via --from-usb)
#   4. run restore.sh  → decrypt, verify, restore config+DB+data
#   5. verify (healthcheck + occ maintenance:repair)
#   6. notify Watchtower (RECOVERY_COMPLETED / RECOVERY_FAILED)
#
# usage:
#   dr-recover.sh                                  # rebuild + restore from local backup
#   dr-recover.sh --from-usb                       # pull backup from USB offsite first
#   dr-recover.sh --archive /path/file.tar.enc     # explicit archive
#
# config (override via env, mirror install.sh):
#   NC_DOMAIN, ADMIN_EMAIL, NC_ADMIN_USER, NC_ADMIN_PASS, NC_DB_PASS,
#   REDIS_PASS, ENABLE_MONITORING, ENABLE_TELEGRAM,
#   WATCHTELEGRAM_BOT_TOKEN, WATCHTELEGRAM_ADMIN_USER_ID
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/notify.sh
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/notify.sh" 2>/dev/null || true

DEPLOY_DIR="${DEPLOY_DIR:-/opt/cloudvault}"
NC_BASE="/var/www/nextcloud"
LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/dr-recover.log"
mkdir -p "${LOG_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

fail() {
  local msg="$*"
  echo "[$(date '+%F %T')] ERROR: ${msg}" | tee -a "${LOG}"
  notify_watchtower "BACKGROUND_JOB_FAILED" "error" "DR recovery failed: ${msg}" "exit_code=1"
  exit 1
}

require_root() { [[ ${EUID} -eq 0 ]] || fail "Please run as root."; }

parse_args() {
  FROM_USB="no"
  ARCHIVE=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --from-usb) FROM_USB="yes"; shift;;
      --archive) ARCHIVE="${2:-}"; shift 2;;
      *) fail "unknown argument: $1";;
    esac
  done
}

preflight() {
  [[ -f "${DEPLOY_DIR}/scripts/install.sh" ]] || fail "repo not found at ${DEPLOY_DIR} (git clone https://github.com/wtfaboutyou/Cloud-Vault.git ${DEPLOY_DIR})"
  [[ -f "${DEPLOY_DIR}/scripts/restore.sh" ]] || fail "restore.sh missing in repo"
  [[ -f /etc/cloudvault/backup.key ]] || fail "missing /etc/cloudvault/backup.key — DR requires the ORIGINAL key; copy it here before recovering!"
  command -v openssl >/dev/null 2>&1 || fail "openssl missing"
}

build_stack() {
  log "==> Building full CloudVault stack (install.sh all)"
  # Ensures packages/config/DB exist on a fresh host so restore.sh has a target.
  # Attention: `all` will bootstrap an EMPTY Nextcloud instance; restore.sh then
  # replaces it (config/DB/data) from the encrypted archive.
  # Env overrides (NC_DOMAIN, NC_ADMIN_PASS, ...) are read from the caller's
  # environment — export them before running for non-default values.
  bash "${DEPLOY_DIR}/scripts/install.sh" all >> "${LOG}" 2>&1 || fail "install.sh all failed (see ${LOG})"
}

fetch_backup() {
  if [[ "${FROM_USB}" == "yes" ]]; then
    log "==> Pulling archive(s) from USB offsite"
    bash "${DEPLOY_DIR}/scripts/usb-backup.sh" --umount >> "${LOG}" 2>&1 \
      || bash "${DEPLOY_DIR}/scripts/usb-backup.sh" >> "${LOG}" 2>&1
  fi
  log "Backup source ready."
}

run_restore() {
  log "==> Restoring from ${ARCHIVE:-latest archive}"
  if [[ -n "${ARCHIVE}" ]]; then
    bash "${DEPLOY_DIR}/scripts/restore.sh" "${ARCHIVE}" >> "${LOG}" 2>&1 \
      || fail "restore of ${ARCHIVE} failed (see ${LOG})"
  else
    bash "${DEPLOY_DIR}/scripts/restore.sh" >> "${LOG}" 2>&1 \
      || fail "restore of latest archive failed (see ${LOG})"
  fi
}

verify_recovery() {
  log "==> Verifying recovery"
  bash "${DEPLOY_DIR}/scripts/healthcheck.sh" 2>&1 | tee -a "${LOG}"
  if [[ -x "${NC_BASE}/occ" ]]; then
    sudo -u www-data php "${NC_BASE}/occ" maintenance:repair 2>&1 | tee -a "${LOG}" || true
  fi
}

# ---------------------------------------------------------------------------
require_root
parse_args "$@"
preflight
log "===== CloudVault DISASTER RECOVERY started ($(date -Is)) ====="
build_stack
fetch_backup
run_restore
verify_recovery
notify_watchtower "RECOVERY_COMPLETED" "success" "DR recovery completed for ${NC_DOMAIN:-unknown domain}" "exit_code=0"
log "===== DR recovery COMPLETE ====="