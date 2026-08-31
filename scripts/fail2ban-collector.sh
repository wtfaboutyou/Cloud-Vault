#!/usr/bin/env bash
#
# fail2ban-collector.sh - CloudVault security metrics collector
#
# Polls Fail2ban and writes Prometheus textfile metrics for the node exporter
# (textfile collector directory). This gives Prometheus real, low-cardinality
# security data to visualize on the Security dashboard and alert on:
#
#   cloudvault_fail2ban_active_bans   (gauge)  total currently-banned IPs
#   cloudvault_fail2ban_jail_banned   (gauge)  currently-banned IPs per jail
#   cloudvault_fail2ban_jail_failed   (gauge)  cumulative failed attempts per jail
#   cloudvault_fail2ban_total_bans    (counter) cumulative bans issued per jail
#
# Idempotent & safe to run on any interval. If Fail2ban is unavailable at write
# time it emits zeros (guarded) rather than failing the run.
#
# Install: symlink into cron / a systemd timer; MUST run as root to read
#          `fail2ban-client status`.
#   */5 * * * *  /opt/cloudvault/scripts/fail2ban-collector.sh >/dev/null 2>&1
#
set -uo pipefail

OUT_DIR="${OUT_DIR:-/var/lib/node_exporter/textfile_collector}"
OUT_FILE="${OUT_FILE:-${OUT_DIR}/cloudvault_fail2ban.prom}"

mkdir -p "${OUT_DIR}"
chmod 0755 "${OUT_DIR}"

jails=""
if command -v fail2ban-client >/dev/null 2>&1; then
  jails="$(fail2ban-client status 2>/dev/null | sed -n 's/^.*Jail list:[[:space:]]*//p')"
fi

: > "${OUT_FILE}.tmp"

if [[ -z "${jails}" ]]; then
  # Fail2ban absent or no jails -> emit zero so the metric still exists
  cat >> "${OUT_FILE}.tmp" <<'PROM'
# HELP cloudvault_fail2ban_active_bans Total IPs currently banned by Fail2ban.
# TYPE cloudvault_fail2ban_active_bans gauge
cloudvault_fail2ban_active_bans 0
PROM
else
  active_total=0
  total_bans=0
  if [[ "${jails}" != "0" ]]; then
    for jail in ${jails//,/ }; do
      banned="$(fail2ban-client status "${jail}" 2>/dev/null | sed -n 's/^.*Currently banned:[[:space:]]*//p')"
      failed="$(fail2ban-client status "${jail}" 2>/dev/null | sed -n 's/^.*Currently failed:[[:space:]]*//p')"
      total="$(fail2ban-client status "${jail}" 2>/dev/null | sed -n 's/^.*Total banned:[[:space:]]*//p')"
      banned="${banned:-0}"; failed="${failed:-0}"; total="${total:-0}"
      active_total=$((active_total + banned))
      total_bans=$((total_bans + total))
      cat >> "${OUT_FILE}.tmp" <<PROM
cloudvault_fail2ban_jail_banned{jail="${jail}"} ${banned}
cloudvault_fail2ban_jail_failed{jail="${jail}"} ${failed}
cloudvault_fail2ban_total_bans{jail="${jail}"} ${total}
PROM
    done
  fi
  cat >> "${OUT_FILE}.tmp" <<PROM
# HELP cloudvault_fail2ban_active_bans Total IPs currently banned by Fail2ban.
# TYPE cloudvault_fail2ban_active_bans gauge
cloudvault_fail2ban_active_bans ${active_total}
# HELP cloudvault_fail2ban_total_bans Cumulative bans issued by Fail2ban.
# TYPE cloudvault_fail2ban_total_bans counter
cloudvault_fail2ban_total_bans ${total_bans}
PROM
fi

mkdir -p "${OUT_DIR}"
chmod 0755 "${OUT_DIR}"
mv "${OUT_FILE}.tmp" "${OUT_FILE}" 2>/dev/null || true
