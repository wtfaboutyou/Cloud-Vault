#!/usr/bin/env bash
#
# certbot-renew-hook.sh - deploy hook registered with Let's Encrypt
# Location: /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
#
# Reloads Nginx after each certificate renewal so that OCSP stapling and
# the new certificate are served immediately.
#
set -uo pipefail

systemctl reload nginx
logger -t cloudvault-certbot "Nginx reloaded after certificate renewal"