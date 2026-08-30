#!/usr/bin/env bash
#
# notify.sh - shared CloudVault Watchtower event notification helper.
#
# Sourced by operational scripts (backup.sh, maintenance.sh, restore.sh,
# healthcheck.sh, ...) so every script emits events in exactly the same way.
#
# Provides:
#   notify_watchtower <event_type> <status> <detail> [key=value ...]
#
# Supported named parameters: label=, size=, duration=, exit_code=
#
# Notifications are fire-and-forget: a failure here MUST never break the
# caller (curl is wrapped with timeout + `|| true`). If WATCHTOWER_API_KEY is
# not provided in the environment it is auto-loaded from the watchtower env
# file, so scripts do not need to depend on a systemd EnvironmentFile.
#
set -u

WATCHTOWER_URL="${WATCHTOWER_URL:-http://127.0.0.1:9191}"
WATCHTOWER_ENV_FILE="${WATCHTOWER_ENV_FILE:-/opt/cloudvault/.secrets/watchtower.env}"

# Auto-load the API key from the watchtower environment file if the caller
# did not export it (e.g. manual runs from the shell).
if [[ -z "${WATCHTOWER_API_KEY:-}" && -f "${WATCHTOWER_ENV_FILE}" ]]; then
  WATCHTOWER_API_KEY="$(sed -n 's/^WATCHTOWER_API_KEY=//p' "${WATCHTOWER_ENV_FILE}" | tail -n1)"
fi

notify_watchtower() {
  local event_type="$1" status="$2" detail="$3"
  shift 3
  # Optional named parameters: label, size, duration, exit_code
  local label="" size="" duration="" exit_code=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      label=*)      label="${1#label=}";;
      size=*)       size="${1#size=}";;
      duration=*)   duration="${1#duration=}";;
      exit_code=*)  exit_code="${1#exit_code=}";;
    esac
    shift
  done

  [[ -n "${WATCHTOWER_API_KEY:-}" ]] || return 0

  local timestamp
  timestamp="$(date '+%F %T %Z')"

  # Build JSON payload using printf (safe, no jq dependency)
  local payload
  payload=$(printf '{"event_type":"%s","status":"%s","detail":"%s","timestamp":"%s"' \
    "${event_type}" "${status}" "${detail}" "${timestamp}")
  [[ -n "${label}" ]] && payload="${payload},\"label\":\"${label}\""
  [[ -n "${size}" ]] && payload="${payload},\"size\":\"${size}\""
  [[ -n "${duration}" ]] && payload="${payload},\"duration\":\"${duration}\""
  [[ -n "${exit_code}" ]] && payload="${payload},\"exit_code\":${exit_code}"
  payload="${payload}}"

  # Fire-and-forget: use timeout + no output check
  # curl failure is logged, but never causes the caller to fail
  timeout 5 curl -s -o /dev/null \
    -X POST "${WATCHTOWER_URL}/api/events" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${WATCHTOWER_API_KEY}" \
    -d "${payload}" 2>/dev/null || true
}