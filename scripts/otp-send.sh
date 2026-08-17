#!/usr/bin/env bash
#
# otp-send.sh - send a 6-digit OTP via Resend (standalone admin/CLI helper).
#
# The Nextcloud app `otp-register` handles this in-app; this script is a handy
# CLI alternative and doubles as a manual sender for admin/user verification.
#
# Usage:
#   RESEND_API_KEY=re_xxx ./otp-send.sh <to@example.com> [code]
#   If [code] is omitted a random 6-digit code is generated and printed.
#
set -uo pipefail

API_URL="https://api.resend.com/emails"
API_KEY="${RESEND_API_KEY:-}"
FROM="${RESEND_FROM:-CloudVault <verify@cloud.example.com>}"

TO="${1:-}"
if [[ -z "${TO}" || -z "${API_KEY}" ]]; then
  echo "Usage: RESEND_API_KEY=re_xxx $0 <to@example.com> [code]" >&2
  exit 1
fi

if [[ -z "${2:-}" ]]; then
  CODE="$(( ( RANDOM % 9 + 1 ) * 100000 + RANDOM % 100000 ))"
else
  CODE="${2}"
fi

payload=$(cat <<EOF
{
  "from": "$FROM",
  "to": ["$TO"],
  "subject": "Your CloudVault verification code",
  "html": "<p>Your verification code is:</p><h2 style=\"letter-spacing:6px;font-size:28px\">$CODE</h2><p>This code expires in a few minutes.</p>",
  "text": "Your CloudVault verification code is: $CODE"
}
EOF
)

resp=$(curl -sS -w "\n%{http_code}" -X POST "$API_URL" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "$payload")

http_code=$(printf '%s\n' "$resp" | tail -n1)
body=$(printf '%s\n' "$resp" | head -n -1)

if [[ "$http_code" != "2"* ]]; then
  echo "Send failed (HTTP $http_code): $body" >&2
  exit 1
fi

echo "OK sent to $TO (code: $CODE)"
exit 0