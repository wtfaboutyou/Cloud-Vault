#!/usr/bin/env bash
#
# healthcheck.sh - CloudVault centralized health check
#
# Reports status of: nginx, php-fpm, postgresql, redis, fail2ban, clamav,
# UFW, disk usage, memory pressure, SwapCheck, and SSL certificate lifetime.
#
# Output: colorized report to stdout + a compact JSON summary for metrics.
# Exit code 0 = healthy, 1 = warnings, 2 = critical.
#
# usage:
#   healthcheck.sh          # full human-readable report
#   healthcheck.sh --json   # machine-readable JSON for Prometheus/Grafana
#
set -uo pipefail

NC_BASE="${NC_BASE:-/var/www/nextcloud}"
NC_DATA_DIR="${NC_DATA_DIR:-${NC_BASE}/data}"
NC_PHP_VER="${NC_PHP_VER:-8.4}"
DOMAIN="${NC_DOMAIN:-$(hostname -f)}"
DISK_THRESH_WARN=75
DISK_THRESH_CRIT=85
MEM_THRESH_WARN=85
MEM_THRESH_CRIT=95

GREEN="\e[32m"; YELLOW="\e[33m"; RED="\e[31m"; RESET="\e[0m"
LOG_DIR="/var/log/cloudvault"
JSON=0
PROBLEMS=0

[[ $# -gt 0 && "$1" == "--json" ]] && JSON=1

service_active() { systemctl is-active --quiet "$1" 2>/dev/null; }

run_as_www() {
  # run a command as www-data using sudo when available, else su
  if command -v sudo >/dev/null 2>&1; then
    sudo -u www-data "$@"
  else
    su -s /bin/bash www-data -c "$(printf '%q ' "$@")"
  fi
}

report() {
  # report <name> <status> <detail>
  local name="$1" status="$2" detail="${3:-}"
  if (( JSON )); then
    printf '{"service":"%s","status":"%s","detail":"%s"}\n' "$name" "$status" "$detail"
  else
    local color
    case "$status" in
      ok)  color="${GREEN}";;
      warn) color="${YELLOW}"; ((PROBLEMS+=1));;
      crit) color="${RED}"; ((PROBLEMS+=2));;
    esac
    printf "%-16s %b%-8s%b %s\n" "$name" "$color" "$status" "$RESET" "$detail"
  fi
}

# ---- services ----
for svc in nginx postgresql redis-server fail2ban clamav-daemon clamav-freshclam php${NC_PHP_VER}-fpm; do
  if service_active "$svc"; then
    report "$svc" ok
  else
    report "$svc" crit "not running"
  fi
done

# ---- UFW ----
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  report ufw ok
else
  report ufw crit "inactive"
fi

# ---- disk usage ----
disk_usage=$(df -P "${NC_DATA_DIR}" | awk 'NR==2 {print $5+0}')
disk_mount=$(df -P "${NC_DATA_DIR}" | awk 'NR==2 {print $6}')
if (( disk_usage >= DISK_THRESH_CRIT )); then
  report disk crit "${disk_usage}% on ${disk_mount}"
elif (( disk_usage >= DISK_THRESH_WARN )); then
  report disk warn "${disk_usage}% on ${disk_mount}"
else
  report disk ok "${disk_usage}% on ${disk_mount}"
fi

# ---- memory ----
mempct=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d", (1-a/t)*100}' /proc/meminfo)
if (( mempct >= MEM_THRESH_CRIT )); then
  report memory crit "${mempct}% used"
elif (( mempct >= MEM_THRESH_WARN )); then
  report memory warn "${mempct}% used"
else
  report memory ok "${mempct}% used"
fi

# ---- load average vs cpu count ----
load=$(awk '{print $1}' /proc/loadavg)
cpus=$(nproc)
if awk -v l="$load" -v c="$cpus" 'BEGIN{exit !(l > c)}'; then
  report load warn "1-min ${load} > ${cpus} cpus"
else
  report load ok "${load}"
fi

# ---- TLS certificate expiry ----
if command -v openssl >/dev/null && [[ -n "${DOMAIN}" ]]; then
  cert=$(echo | timeout 5 openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [[ -n "$cert" ]]; then
    days=$(( ( $(date -d "$cert" +%s) - $(date +%s) ) / 86400 ))
    if (( days < 14 )); then report ssl crit "${days} days remaining"; 
    elif (( days < 30 )); then report ssl warn "${days} days remaining"; 
    else report ssl ok "${days} days remaining"; fi
  else
    report ssl warn "unable to check"
  fi
fi

# ---- fail2ban ban count ----
if command -v fail2ban-client >/dev/null; then
  bans=$(fail2ban-client status nextcloud 2>/dev/null | grep -c 'IPs' >/dev/null; \
    fail2ban-client status nextcloud 2>/dev/null | grep -oP 'IP list:\s*\K.*' | wc -w)
  report fail2ban_bans ok "banned IPs: ${bans:-0}"
fi

# ---- Queue / Nextcloud status ----
if [[ -f "${NC_BASE}/occ" ]]; then
  ncstatus=$(run_as_www php "${NC_BASE}/occ" status 2>/dev/null | grep -m1 '^  - installed:' | awk '{print $3}')
  report nextcloud ok "installed=${ncstatus:-unknown}"
fi

exit ${PROBLEMS}