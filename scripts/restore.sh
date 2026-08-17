#!/usr/bin/env bash
#
# restore.sh - restore CloudVault from an encrypted backup archive
#
# Restores, in order: Nextcloud config, PostgreSQL database, Nextcloud data.
# Nextcloud is placed in maintenance mode around the restore window.
#
# usage:
#   restore.sh                          # most recent archive under $BACKUP_DIR
#   restore.sh /path/to/archive.tar.enc # restore a specific archive
#
# Archive layout (produced by backup.sh):
#   postgres.sql  nextcloud-config.tar.gz  nextcloud-config.php  nextcloud-data.tar.gz
#   -> tar -> aes-256-cbc -> .tar.enc
#
set -uo pipefail

BACKUP_KEY="/etc/cloudvault/backup.key"
BACKUP_DIR="/opt/cloudvault/backup"
NC_BASE="/var/www/nextcloud"
NC_CONFIG_DIR="${NC_BASE}/config"
NC_DATA_DIR="${NC_BASE}/data"
PG_USER="postgres"
PG_DB="nextcloud"
NC_USER="www-data"
NC_PHP_VER="${NC_PHP_VER:-8.4}"

LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/restore.log"
mkdir -p "${LOG_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
fail() { echo "[$(date '+%F %T')] ERROR: $*" | tee -a "${LOG}"; exit 1; }

require_root() { [[ ${EUID} -eq 0 ]] || fail "Please run as root."; }

openssl_decrypt() {
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -pass file:"${BACKUP_KEY}" \
    -in "$1" -out "$2"
}

choose_archive() {
  if [[ $# -gt 0 ]]; then
    echo "$1"
  else
    ls -1t "${BACKUP_DIR}"/*/cloudvault-*.tar.enc 2>/dev/null | head -1
  fi
}

restore_archive() {
  local ar="${1:?no archive specified}"
  [[ -f "${ar}" ]] || fail "archive not found: ${ar}"
  [[ -f "${BACKUP_KEY}" ]] || fail "missing ${BACKUP_KEY}"

  local work
  work="$(mktemp -d)"
  log "Decrypting ${ar} ..."
  openssl_decrypt "${ar}" "${work}/plain.tar" || fail "decryption failed"

  log "Verifying archive integrity..."
  tar -tf "${work}/plain.tar" >/dev/null || fail "invalid archive"
  tar -xf "${work}/plain.tar" -C "${work}"

  # 1. Enter maintenance mode & stop web stack
  if [[ -f "${NC_BASE}/occ" ]]; then
    sudo -u "${NC_USER}" php "${NC_BASE}/occ" maintenance:mode --on || true
  fi
  systemctl stop nginx php${NC_PHP_VER}-fpm 2>/dev/null || true

  # 2. Restore Nextcloud config
  if [[ -f "${work}/nextcloud-config.tar.gz" ]]; then
    cp -a "${NC_CONFIG_DIR}" "${NC_CONFIG_DIR}.pre-restore" 2>/dev/null || true
    rm -rf "${NC_CONFIG_DIR}"
    mkdir -p "${NC_CONFIG_DIR}"
    tar -xzf "${work}/nextcloud-config.tar.gz" -C "${NC_CONFIG_DIR}"
    chown -R "${NC_USER}:${NC_USER}" "${NC_CONFIG_DIR}"
    chmod 640 "${NC_CONFIG_DIR}/config.php"
    log "config restored"
  fi

  # 3. Restore PostgreSQL (drop & recreate, then load global dump)
  if [[ -s "${work}/postgres.sql" ]]; then
    log "Recreating PostgreSQL database ${PG_DB}..."
    su - "${PG_USER}" -c "psql -v ON_ERROR_STOP=0 -c \"DROP DATABASE IF EXISTS ${PG_DB}\"" >> "${LOG}" 2>&1 || true
    su - "${PG_USER}" -c "createuser ${PG_DB}" 2>>"${LOG}" || true
    su - "${PG_USER}" -c "createdb -O ${PG_DB} ${PG_DB}" >> "${LOG}" 2>&1 || true
    log "Importing pg_dumpall ..."
    su - "${PG_USER}" -c "psql -v ON_ERROR_STOP=0" < "${work}/postgres.sql" >> "${LOG}" 2>&1 \
      || fail "postgres restore reported errors (see ${LOG})"
    log "database restored"
  fi

  # 4. Restore data directory
  if [[ -f "${work}/nextcloud-data.tar.gz" ]]; then
    log "Restoring data directory..."
    tar -xzf "${work}/nextcloud-data.tar.gz" -C "${NC_BASE}"
    chown -R "${NC_USER}:${NC_USER}" "${NC_BASE}"
    chmod 750 "${NC_DATA_DIR}"
    log "data restored"
  fi

  # 5. Restart services & exit maintenance mode
  systemctl start nginx php${NC_PHP_VER}-fpm 2>/dev/null || true
  if [[ -f "${NC_BASE}/occ" ]]; then
    sudo -u "${NC_USER}" php "${NC_BASE}/occ" maintenance:mode --off || true
    sudo -u "${NC_USER}" php "${NC_BASE}/occ" maintenance:repair || true
  fi

  rm -rf "${work}"
  log "Restore complete for ${ar}"
}

# ---------------------------------------------------------------------------
require_root
CHOICE="$(choose_archive "${@}")"
[[ -n "${CHOICE}" ]] || fail "no backups found under ${BACKUP_DIR}"
log "Starting restore from: ${CHOICE}"
restore_archive "${CHOICE}"