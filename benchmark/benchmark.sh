#!/usr/bin/env bash
#
# benchmark.sh - basic CloudVault performance smoke test
# Location: /opt/cloudvault/benchmark/
#
# Measures: Nginx response time, Brotli/Gzip compression savings,
# TLS handshake time, and PHP-FPM processing time.
#
# usage: bash benchmark.sh [URL]
#
set -uo pipefail

URL="${1:-https://localhost/}"
RESULT_DIR="$(dirname "$0")/results"
mkdir -p "${RESULT_DIR}"
OUT="${RESULT_DIR}/benchmark-$(date +%Y%m%d-%H%M%S).txt"

{
echo "CloudVault benchmark at $(date)"
echo "=================================="
echo

echo "[1] HTTP response time (10 requests, curl)"
for i in $(seq 1 10); do
  curl -sk -o /dev/null -w "  %{http_code} %{time_total}s %{size_download}B\n" "$URL"
done
echo

echo "[2] TLS handshake time"
curl -sk -o /dev/null -w "  TLS handshake: %{time_appconnect}s\n" "$URL"
echo

echo "[3] Compression: Brotli vs Gzip vs plain"
curl -sk -H 'Accept-Encoding: br' -o /dev/null -w "  brotli: %{size_download}B (%{speed_download} B/s)\n" "$URL"
curl -sk -H 'Accept-Encoding: gzip' -o /dev/null -w "  gzip  : %{size_download}B (%{speed_download} B/s)\n" "$URL"
curl -sk -o /dev/null -w "  plain : %{size_download}B (%{speed_download} B/s)\n" "$URL"
echo

echo "[4] PHP-FPM processing (via /status.json if enabled)"
curl -sk -o /dev/null -w "  PHP page time: %{time_starttransfer}s\n" "$URL"
echo

echo "[5] PHP-FPM pool status"
if curl -sk --max-time 3 "http://127.0.0.1/status" -o /dev/null; then
  curl -sk --max-time 3 "http://127.0.0.1/status" | head -20
else
  echo "  status page not exposed; skipping"
fi
} | tee "$OUT"

echo
echo "Results written to $OUT"