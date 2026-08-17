#!/usr/bin/env bash
#
# healthcheck-prom.sh - expose CloudVault healthcheck as Prometheus metrics
#
# Runs healthcheck.sh --json and converts each line into a Prometheus textfile
# metric consumed by prometheus-node-exporter via --collector.textfile.directory.
#
# Metric: cloudvault_health_status{service=...,status=...}  (0=ok 1=warn 2=crit)
#   plus cloudvault_health_detail{service=...,status=...,detail=...} 1
#
# usage:
#   healthcheck-prom.sh            # write metrics to the textfile directory
#   healthcheck-prom.sh --stdout   # print metrics to stdout instead
#
set -uo pipefail

TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/prometheus/textfiles}"
OUT="${TEXTFILE_DIR}/cloudvault_health.prom"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HEALTHCHECK="${SCRIPT_DIR}/healthcheck.sh"

metric_value() {
  case "$1" in
    ok)   echo 0 ;;
    warn) echo 1 ;;
    crit) echo 2 ;;
    *)    echo 3 ;;
  esac
}

main() {
  local out_file="$1" i
  local lines tmp
  lines="$("${HEALTHCHECK}" --json 2>/dev/null)"
  tmp="$(mktemp)"

  {
    echo '# HELP cloudvault_health_status CloudVault service health (0=ok 1=warn 2=crit)'
    echo '# TYPE cloudvault_health_status gauge'
    echo '# HELP cloudvault_health_detail CloudVault service health detail'
    echo '# TYPE cloudvault_health_detail gauge'

    while IFS= read -r line; do
      [[ -n "${line}" ]] || continue
      st="$(echo "${line}" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
      svc="$(echo "${line}" | sed -n 's/.*"service":"\([^"]*\)".*/\1/p')"
      det="$(echo "${line}" | sed -n 's/.*"detail":"\([^"]*\)".*/\1/p')"
      [[ -n "${svc}" ]] || continue
      i="$(metric_value "${st}")"
      printf 'cloudvault_health_status{service="%s"} %s\n' "${svc}" "${i}"
      printf 'cloudvault_health_detail{service="%s",status="%s",detail="%s"} 1\n' \
        "${svc}" "${st}" "${det}"
    done <<< "${lines}"
  } > "${tmp}"

  if [[ "${out_file}" == "-" ]]; then
    cat "${tmp}"
  else
    install -m 0644 -o root -g prometheus "${tmp}" "${out_file}"
  fi
  rm -f "${tmp}"
}

case "${1:-write}" in
  --stdout) main "-" ;;
  write)    main "${OUT}" ;;
  *)        echo "usage: $0 [--stdout]" >&2; exit 1 ;;
esac