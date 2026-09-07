#!/usr/bin/env bash
#
# usb-backup.sh - mirror CloudVault encrypted backups to a self-hosted USB.
#
# Offsite ("2-3-1") layer for disaster recovery. Because the server itself is
# the USB host, the USB is a SECOND copy that survives a total server failure
# if it is physically stored away from the server (another room / building).
#
# Design:
#   * LABEL-based mounting (never a hardcoded /dev/sdX) so the SAME script
#     works on a physical bare-metal host (USB auto-detected) and inside a VM
#     (USB attached/passed-through by the hypervisor first).
#   * rsync with --delete keeps USB a true mirror of the backup directory.
#   * Notifies Watchtower on success/failure (fire-and-forget).
#
# usage:
#   usb-backup.sh            # mount (if not mounted) + sync
#   usb-backup.sh --umount   # sync then unmount (safe for moving the USB)
#   usb-backup.sh --help
#
# config (override via env):
#   USB_LABEL   default: CLOUDVAULT-BACKUP
#   USB_MOUNT   default: /mnt/usbbackup
#   BACKUP_DIR  default: /opt/cloudvault/backup
#
set -uo pipefail

USB_LABEL="${USB_LABEL:-CLOUDVAULT-BACKUP}"
USB_MOUNT="${USB_MOUNT:-/mnt/usbbackup}"
BACKUP_DIR="${BACKUP_DIR:-/opt/cloudvault/backup}"

LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/usb-backup.log"
mkdir -p "${LOG_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/notify.sh
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/notify.sh" 2>/dev/null || true

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

require_root() { [[ ${EUID} -eq 0 ]] || { echo "Please run as root." >&2; exit 1; }; }

usb_is_mounted() { mountpoint -q "${USB_MOUNT}"; }

usb_mount() {
  if usb_is_mounted; then
    log "Already mounted at ${USB_MOUNT}"
    return 0
  fi
  mkdir -p "${USB_MOUNT}"

  # Prefer a filesystem LABEL (stable across reboots / VM vs physical).
  # Fall back to any USB-ish device currently present if no label match.
  if findfs "LABEL=${USB_LABEL}" >/dev/null 2>&1; then
    log "Mounting LABEL=${USB_LABEL} -> ${USB_MOUNT}"
    mount -L "${USB_LABEL}" "${USB_MOUNT}" || return 1
  else
    # Any removable device currently present and unmounted (best-effort).
    local dev
    dev="$(lsblk -nrpo NAME,TRAN 2>/dev/null | awk '$2=="usb"{print $1}' | head -1)"
    [[ -n "${dev}" ]] || { warn_no_usb; return 1; }
    log "No label match; mounting ${dev} (USB transport found)"
    mount "${dev}" "${USB_MOUNT}" || return 1
  fi
}

warn_no_usb() {
  echo "[$(date '+%F %T')] ERROR: No USB with LABEL=${USB_LABEL} found. \
(For VM servers: attach/passthrough the USB to the VM first.)" | tee -a "${LOG}"
}

# Use --delete but never delete out of a sync error (rsync --delete with nonzero
# exit still copies; guard so a failed incremental does not nuke the mirror).
sync_backup() {
  log "Syncing ${BACKUP_DIR} -> ${USB_MOUNT} ..."
  local timeout_sync
  timeout_sync="${USB_SYNC_TIMEOUT:-3600}"
  if ! timeout "${timeout_sync}" rsync -a --delete \
      "${BACKUP_DIR}/" "${USB_MOUNT}/" >> "${LOG}" 2>&1; then
    log "ERROR rsync failed (exit ${?}) — USB mirror NOT updated"
    return 1
  fi
  log "USB mirror updated"
  df -h "${USB_MOUNT}" 2>/dev/null | tee -a "${LOG}"
}

main() {
  require_root
  case "${1:-}" in
    --help|-h)
      sed -n '1,20p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    --umount)
      usb_mount || { notify_watchtower "BACKUP_FAILED" "error" "USB backup: mount failed" "exit_code=2"; exit 2; }
      sync_backup || { notify_watchtower "BACKUP_FAILED" "error" "USB backup: sync failed" "exit_code=3"; exit 3; }
      umount "${USB_MOUNT}" && log "USB unmounted — safe to carry away."
      notify_watchtower "BACKUP_COMPLETED" "success" "USB backup synced & unmounted"
      ;;
    *)
      usb_mount || { notify_watchtower "BACKUP_FAILED" "error" "USB backup: mount failed" "exit_code=2"; exit 2; }
      sync_backup || { notify_watchtower "BACKUP_FAILED" "error" "USB backup: sync failed" "exit_code=3"; exit 3; }
      notify_watchtower "BACKUP_COMPLETED" "success" "USB backup mirrored to ${USB_MOUNT}"
      ;;
  esac
}

main "$@"