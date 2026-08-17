#!/usr/bin/env bash
#
# maintenance.sh - CloudVault automated Nextcloud maintenance tasks
#
# Executed daily by systemd timer (cloudvault-maintenance.timer) at 02:30.
# Runs the maintenance occ commands as the www-data user; safe to run
# repeatedly (each command is idempotent).
#
set -uo pipefail

NC_BASE="${NC_BASE:-/var/www/nextcloud}"
NC_DATA_DIR="${NC_DATA_DIR:-${NC_BASE}/data}"
NC_PHP_VER="${NC_PHP_VER:-8.4}"
OCC="sudo -u www-data php ${NC_BASE}/occ"

LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/maintenance.log"
mkdir -p "${LOG_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

run() {
  local cmd="$1"
  log ">>> occ ${cmd}"
  eval "${OCC} ${cmd}" >> "${LOG}" 2>&1 || log "   !!! occ ${cmd} failed"
}

main() {
  # ensure the Nextcloud instance is installed & not in maintenance mode
  grep -q "'installed' => true" "${NC_BASE}/config/config.php" 2>/dev/null \
    || { log "Nextcloud not installed; skipping maintenance."; exit 0; }

  run "maintenance:mode --on"
  {
    # database integrity
    run "db:convert-filecache-bigint --no-interaction"   # only needed once; idempotent
    run "db:add-missing-indices"
    run "db:add-missing-primary-keys"
    run "db:add-missing-columns"
    # housekeeping
    run "files:cleanup"
    run "trashbin:expire"
    run "versions:expire"
    run "preview:pre-generate"
    run "files:scan --all"
    run "maintenance:repair"
  }
  run "maintenance:mode --off"
}

main
log "maintenance finished"