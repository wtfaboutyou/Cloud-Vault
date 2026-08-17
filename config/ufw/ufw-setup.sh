#!/usr/bin/env bash
#
# ufw-setup.sh - CloudVault UFW firewall rules (idempotent)
#
# usage: sudo bash ufw-setup.sh
#   ADMIN_IP="203.0.113.10/32" bash ufw-setup.sh   # restrict SSH to admin IP
#
set -uo pipefail

ADMIN_IP="${ADMIN_IP:-}"

ufw default deny incoming
ufw default allow outgoing

ufw allow 22/tcp comment 'SSH'
[[ -n "${ADMIN_IP}" ]] && ufw allow from "${ADMIN_IP}" to any port 22/tcp comment 'SSH admin'
ufw allow 80/tcp  comment 'HTTP (redirect to HTTPS)'
ufw allow 443/tcp comment 'HTTPS'

# outbound SMTP blocked to reduce spam abuse
ufw deny out 25/tcp

ufw --force enable
ufw status verbose