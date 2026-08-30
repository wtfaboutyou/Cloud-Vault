#!/usr/bin/env bash
#
# backup.sh - CloudVault encrypted backup with retention & integrity checks
#
# Features:
#   * atomic pg_dumpall for PostgreSQL (single backup file)
#   * Nextcloud config/ directory backup
#   * data directory sync (rsync incremental mirror, then archive)
#   * AES-256 encrypt-encrypted tar archive via openssl (backup.key)
#   * SHA-256 checksum verification file per archive
#   * retention rotation: 7 daily, 4 weekly, 12 monthly
#
# usage:
#   backup.sh              # run respecting the label derived from day of month
#   backup.sh daily        # force daily label
#   backup.sh weekly
#   backup.sh monthly
#   backup.sh clean        # retention pruning only
#   backup.sh verify       # verify integrity of latest archive
#
set -uo pipefail

BACKUP_KEY="/etc/cloudvault/backup.key"          # AES-256 key (hex, 64 chars)
BACKUP_DIR="/opt/cloudvault/backup"
DATA_DIR="/var/www/nextcloud/data"
CONFIG_DIR="/var/www/nextcloud/config"
NC_PHP_VER="${NC_PHP_VER:-8.4}"

RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=12

KEEP_MIRROR="yes"                                # keep incremental rsync mirror between runs
MIRROR_DIR="${BACKUP_DIR}/mirror/data"

LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/backup.log"
mkdir -p "${LOG_DIR}"

# Phase 7 — Event notification configuration (shared helper)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/notify.sh
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/notify.sh" 2>/dev/null || true

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

require_root() { [[ ${EUID} -eq 0 ]] || { echo "Please run as root." >&2; exit 1; }; }

openssl_encrypt() {
  # usage: openssl_encrypt <input-file> <output-file>
  # The backup key file acts as the passphrase; openssl embeds salt + IV in
  # the output header ("Salted__" prefix), making decryption self-contained.
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
    -pass file:"${BACKUP_KEY}" \
    -in "$1" -out "$2"
}

openssl_decrypt() {
  # usage: openssl_decrypt <input-file> <output-file>
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -pass file:"${BACKUP_KEY}" \
    -in "$1" -out "$2"
}

create_backup() {
  local label="${1:-daily}"
  local stamp
  stamp="$(date +%Y%m%d-%H%M%S)"
  local work="${BACKUP_DIR}/tmp/${stamp}"
  local archive="${BACKUP_DIR}/${label}"

  [[ -f "${BACKUP_KEY}" ]] || { log "ERROR missing ${BACKUP_KEY}"; exit 1; }
  [[ -d "${BACKUP_DIR}" ]] || mkdir -p "${BACKUP_DIR}"
  mkdir -p "${BACKUP_DIR}/tmp" "${BACKUP_DIR}/${label}" "${work}"

  # 1) PostgreSQL dump
  log "Dumping PostgreSQL (pg_dumpall)..."
  su - postgres -c "pg_dumpall --clean --if-exists" > "${work}/postgres.sql" 2>>"${LOG}"
  [[ -s "${work}/postgres.sql" ]] || { log "ERROR postgres dump empty"; exit 1; }

  # 2) Nextcloud config backup
  log "Backing up Nextcloud config..."
  tar -czf "${work}/nextcloud-config.tar.gz" -C "${CONFIG_DIR}" . 2>>"${LOG}" || true
  cp "${CONFIG_DIR}/config.php" "${work}/nextcloud-config.php" 2>/dev/null || true

  # 3) Incremental data sync (mirror first, archive later)
  if [[ "${KEEP_MIRROR}" == "yes" ]] && command -v rsync >/dev/null; then
    log "Syncing data via rsync mirror..."
    mkdir -p "${MIRROR_DIR}"
    rsync -a --delete --exclude 'files_trashbin' \
      "${DATA_DIR}/" "${MIRROR_DIR}/" >> "${LOG}" 2>&1
    DATA_SRC="${MIRROR_DIR}"
  else
    DATA_SRC="${DATA_DIR}"
  fi
  log "Archiving data from ${DATA_SRC}..."
  tar -czf "${work}/nextcloud-data.tar.gz" -C "$(dirname "${DATA_SRC}")" "$(basename "${DATA_SRC}")"

  # 4) Plaintext aggregate
  tar -cf "${work}/cloudvault-${label}-plain.tar" -C "${work}" \
    postgres.sql nextcloud-config.tar.gz nextcloud-config.php nextcloud-data.tar.gz

  # 5) Encrypt
  local final="${archive}/cloudvault-${label}-${stamp}.tar.enc"
  log "Encrypting -> ${final}"
  openssl_encrypt "${work}/cloudvault-${label}-plain.tar" "${final}" || { log "encryption failed"; exit 1; }

  # 6) SHA-256 integrity file
  sha256sum "${final}" > "${final}.sha256"

  # clean workspace
  rm -rf "${work}"
  log "Backup created: ${final} (size $(du -h "${final}" | cut -f1))"
}

# derive label: monthly on 01, weekly on Mondays, otherwise daily
derive_label() {
  local dom dow
  dom="$(date +%d)"
  dow="$(date +%u)"
  if [[ "${dom}" == "01" ]]; then echo monthly
  elif [[ "${dow}" == "1" ]]; then echo weekly
  else echo daily; fi
}

prune_retention() {
  log "Pruning old backups (keep=${RETENTION_DAILY}d/${RETENTION_WEEKLY}w/${RETENTION_MONTHLY}m)..."
  local keep keep_ts now label file ts
  now="$(date +%s)"
  for label in daily weekly monthly; do
    case "${label}" in
      daily)   keep="${RETENTION_DAILY}";;
      weekly)  keep="${RETENTION_WEEKLY}";;
      monthly) keep="${RETENTION_MONTHLY}";;
    esac
    keep=$(( keep * 86400 ))
    [[ "$label" == "weekly" ]] && keep=$(( keep * 7 ))
    [[ "$label"  == "monthly" ]] && keep=$(( keep * 30 ))
    for file in "${BACKUP_DIR}/${label}"/cloudvault-${label}-*.tar.enc; do
      [[ -e "${file}" ]] || continue
      ts="$(stat -c %Y "${file}")"
      if (( now - ts > keep )); then
        log "pruning ${file}"
        rm -f "${file}" "${file}.sha256"
      fi
    done
  done
}

verify_latest() {
  local label="${1:-latest}"
  local pattern="cloudvault-[a-z]+-*.tar.enc"
  if [[ "${label}" != "latest" ]]; then pattern="${label}"/cloudvault-${label}-*.tar.enc; else pattern="*/cloudvault-*.tar.enc"; fi

  local latest
  latest="$(ls -1t "${BACKUP_DIR}"/${pattern} 2>/dev/null | head -1)"
  [[ -n "${latest}" ]] || { log "no backups found"; exit 1; }

  log "Integrity check of ${latest}"
  # 1) verify stored SHA-256 checksum matches the actual file
  ( cd "$(dirname "${latest}")" && sha256sum -c "$(basename "${latest}").sha256" ) >/dev/null 2>&1 \
    || { log "FAIL sha256 mismatch for ${latest}"; return 1; }

  # 2) test the archive can be decrypted and read
  local tmp
  tmp="$(mktemp -d)"
  if ! openssl_decrypt "${latest}" "${tmp}/test.tar" 2>>"${LOG}"; then
    log "FAIL decryption failed for ${latest}"
    rm -rf "${tmp}"
    return 1
  fi
  tar -tf "${tmp}/test.tar" >/dev/null 2>&1 || { log "FAIL archive invalid"; rm -rf "${tmp}"; return 1; }
  rm -rf "${tmp}"
  log "OK  ${latest} verified"
}

# ---------------------------------------------------------------------------
require_root
BACKUP_EXIT_CODE=0
BACKUP_START=$(date +%s)
BACKUP_LABEL="${1:-$(derive_label)}"
case "${BACKUP_LABEL}" in
  daily)   create_backup daily ;;
  weekly)  create_backup weekly ;;
  monthly) create_backup monthly ;;
  clean)   prune_retention; log "backup.sh finished"; exit 0 ;;
  verify)  verify_latest "${2:-latest}"; log "backup.sh finished"; exit $? ;;
  *) create_backup "$1";;
esac
BACKUP_EXIT_CODE=$?
BACKUP_END=$(date +%s)
BACKUP_DURATION=$(( BACKUP_END - BACKUP_START ))

# Phase 7 — Send event notification to Watchtower (fire-and-forget)
if (( BACKUP_EXIT_CODE == 0 )); then
  # Determine backup size (last created .enc file)
  LATEST_ENC=$(ls -1t "${BACKUP_DIR}/${BACKUP_LABEL}"/cloudvault-${BACKUP_LABEL}-*.tar.enc 2>/dev/null | head -1)
  BACKUP_SIZE=""
  if [[ -n "${LATEST_ENC}" ]] && [[ -f "${LATEST_ENC}" ]]; then
    BACKUP_SIZE=$(du -h "${LATEST_ENC}" | cut -f1)
  fi

  # Format duration
  DURATION_FMT="$(( BACKUP_DURATION / 60 ))m $(( BACKUP_DURATION % 60 ))s"

  notify_watchtower "BACKUP_COMPLETED" "success" "Backup ${BACKUP_LABEL} completed" \
    "label=${BACKUP_LABEL}" "size=${BACKUP_SIZE}" "duration=${DURATION_FMT}"
  log "backup.sh finished"
else
  DURATION_FMT="$(( BACKUP_DURATION / 60 ))m $(( BACKUP_DURATION % 60 ))s"
  notify_watchtower "BACKUP_FAILED" "error" "Backup ${BACKUP_LABEL} failed" \
    "label=${BACKUP_LABEL}" "exit_code=${BACKUP_EXIT_CODE}" "duration=${DURATION_FMT}"
  log "backup.sh finished with errors"
fi
exit ${BACKUP_EXIT_CODE}