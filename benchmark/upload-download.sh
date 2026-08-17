#!/usr/bin/env bash
#
# upload-download.sh - CloudVault WebDAV throughput benchmark
# Location: /opt/cloudvault/benchmark/
#
# Measures real upload/download speed through the full stack:
# nginx -> php-fpm -> files_antivirus (ClamAV) -> Nextcloud -> PostgreSQL/Redis.
#
# Sizes tested: 1 MB, 5 MB, 25 MB. Each round run N times (default 3).
#
# usage: bash upload-download.sh [RPI] [URL]
#   RPI  repetitions per size (default 3)
#   URL  Nextcloud base URL, e.g. https://localhost (default https://localhost)
#
set -uo pipefail

source /opt/cloudvault/.env
URL="${2:-https://localhost}"
RPI="${1:-3}"
USER="${ADMIN_USER:?ADMIN_USER missing in /opt/cloudvault/.env}"
PASS="${ADMIN_PASS:?ADMIN_PASS missing in /opt/cloudvault/.env}"
DAV="${URL}/remote.php/dav/files/${USER}"
RESULT_DIR="$(dirname "$0")/results"
mkdir -p "${RESULT_DIR}"
OUT="${RESULT_DIR}/upload-download-$(date +%Y%m%d-%H%M%S).txt"

mkfile() { head -c "$1" /dev/urandom > "$2"; }

human() { numfmt --to=iec "$1" 2>/dev/null || echo "$1 B"; }

bench_upload() {
  local file="$1" size="$2" best=999999999 avg=0 t
  for i in $(seq 1 "$RPI"); do
    t=$(curl -sk -o /dev/null -w '%{time_total}' -u "${USER}:${PASS}" \
      -T "$file" "${DAV}/$(basename "$file")")
    avg=$(awk -v a="$avg" -v t="$t" 'BEGIN{print a+t}')
    best=$(awk -v b="$best" -v t="$t" 'BEGIN{print (t<b)?t:b}')
  done
  avg=$(awk -v a="$avg" -v n="$RPI" 'BEGIN{printf "%.3f", a/n}')
  best=$(awk -v b="$best" 'BEGIN{printf "%.3f", b}')
  local mbs_best mbs_avg
  mbs_best=$(awk -v s="$size" -v t="$best" 'BEGIN{printf "%.1f", s/t/1048576}')
  mbs_avg=$(awk -v s="$size" -v t="$avg" 'BEGIN{printf "%.1f", s/t/1048576}')
  printf "  %-8s upload  best=%-7s avg=%-7s  best=%-6sMB/s avg=%-6sMB/s\n" \
    "$(human "$size")" "${best}s" "${avg}s" "$mbs_best" "$mbs_avg"
}

bench_download() {
  local name="$1" size="$2" best=999999999 avg=0 t
  for i in $(seq 1 "$RPI"); do
    t=$(curl -sk -o /dev/null -w '%{time_total}' -u "${USER}:${PASS}" \
      "${DAV}/${name}")
    avg=$(awk -v a="$avg" -v t="$t" 'BEGIN{print a+t}')
    best=$(awk -v b="$best" -v t="$t" 'BEGIN{print (t<b)?t:b}')
  done
  avg=$(awk -v a="$avg" -v n="$RPI" 'BEGIN{printf "%.3f", a/n}')
  best=$(awk -v b="$best" 'BEGIN{printf "%.3f", b}')
  local mbs_best mbs_avg
  mbs_best=$(awk -v s="$size" -v t="$best" 'BEGIN{printf "%.1f", s/t/1048576}')
  mbs_avg=$(awk -v s="$size" -v t="$avg" 'BEGIN{printf "%.1f", s/t/1048576}')
  printf "  %-8s download best=%-7s avg=%-7s  best=%-6sMB/s avg=%-6sMB/s\n" \
    "$(human "$size")" "${best}s" "${avg}s" "$mbs_best" "$mbs_avg"
}

WORK=$(mktemp -d)
SIZES=(1048576 5242880 26214400)
NAMES=(bench-1m.bin bench-5m.bin bench-25m.bin)

{
  echo "CloudVault WebDAV benchmark at $(date)"
  echo "URL=$URL  user=$USER  rounds=$RPI"
  echo "============================================================"
  echo "Warmup (1 MB upload + download) to avoid cold-start outliers"
  head -c 1048576 /dev/urandom > "${WORK}/warmup.bin"
  curl -sk -o /dev/null -u "${USER}:${PASS}" -T "${WORK}/warmup.bin" "${DAV}/warmup.bin"
  curl -sk -o /dev/null -u "${USER}:${PASS}" "${DAV}/warmup.bin"
  curl -sk -o /dev/null -X DELETE -u "${USER}:${PASS}" "${DAV}/warmup.bin"
  echo "Warmup done"
  echo
  for idx in 0 1 2; do
    mkfile "${SIZES[$idx]}" "${WORK}/${NAMES[$idx]}"
    bench_upload "${WORK}/${NAMES[$idx]}" "${SIZES[$idx]}"
  done
  echo
  for idx in 0 1 2; do
    bench_download "${NAMES[$idx]}" "${SIZES[$idx]}"
  done
  echo "============================================================"
  echo "Cleanup: removing benchmark files"
  curl -sk -o /dev/null -X DELETE -u "${USER}:${PASS}" "${DAV}/bench-1m.bin"
  curl -sk -o /dev/null -X DELETE -u "${USER}:${PASS}" "${DAV}/bench-5m.bin"
  curl -sk -o /dev/null -X DELETE -u "${USER}:${PASS}" "${DAV}/bench-25m.bin"
} | tee "$OUT"

rm -rf "$WORK"
echo "Results written to $OUT"