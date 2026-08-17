#!/usr/bin/env bash
#
# gcs-storage.sh - Mount Google Cloud Storage into Nextcloud (S3-compatible)
#
# Google Cloud Storage exposes an S3-compatible interoperability endpoint, so
# the stock Nextcloud "AmazonS3" backend works without extra packages.
#
# Prerequisites (GCP console):
#   1. Create a bucket:  gsutil mb gs://<BUCKET>
#   2. Create HMAC access/secret keys for a Service Account:
#        gcloud storage hmac create <service-account-email>
#   3. Run this script with the generated keys.
#
# Usage:
#   GCS_BUCKET=<bucket> GCS_ACCESS_KEY=<key> GCS_SECRET=<secret> \
#     sudo bash scripts/gcs-storage.sh [MOUNTPOINT]
#
#   MOUNTPOINT defaults to "/gcs". The mount is created as a *system-wide*
#   external storage so every user can use it.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NC_BASE="${NC_BASE:-/var/www/nextcloud}"
occ() { sudo -u www-data php "${NC_BASE}/occ" "$@"; }

GCS_BUCKET="${GCS_BUCKET:-}"
GCS_ACCESS_KEY="${GCS_ACCESS_KEY:-}"
GCS_SECRET="${GCS_SECRET:-}"
GCS_REGION="${GCS_REGION:-auto}"
GCS_HOST="${GCS_HOST:-storage.googleapis.com}"
MOUNTPOINT="${1:-/gcs}"

fail() { echo "[ERROR] $1" >&2; exit 1; }

[[ -n "${GCS_BUCKET}" ]]      || fail "GCS_BUCKET is required."
[[ -n "${GCS_ACCESS_KEY}" ]] || fail "GCS_ACCESS_KEY (HMAC) is required."
[[ -n "${GCS_SECRET}" ]]     || fail "GCS_SECRET (HMAC) is required."

command -v gcloud >/dev/null 2>&1 || echo "[WARN] gcloud not found (not needed on the server itself)."

echo "==> Enabling files_external app"
occ app:enable files_external || occ app:install files_external || true

echo "==> Creating external storage mount ${MOUNTPOINT} -> gs://${GCS_BUCKET}"
occ files_external:create "${MOUNTPOINT}" AmazonS3 AccessKey \
  --config bucket="${GCS_BUCKET}" \
  --config key="${GCS_ACCESS_KEY}" \
  --config secret="${GCS_SECRET}" \
  --config hostname="${GCS_HOST}" \
  --config port=443 \
  --config use_ssl=true \
  --config use_path_style=true \
  --config legacy_auth=false \
  --config region="${GCS_REGION}"

echo "==> Listing configured mounts"
occ files_external:list

echo
echo "Mount ${MOUNTPOINT} -> gs://${GCS_BUCKET} configured."
echo "Verify in the admin UI: Settings > External storages."
echo "To share the bucket for a single user use Settings > External storages and set visibility."
