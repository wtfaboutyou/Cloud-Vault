#!/usr/bin/env bash
#
# install.sh - CloudVault deployment orchestrator
#
# Target : Debian 13 (Trixie), native install (NO Docker / containers).
# Usage  : sudo bash install.sh [stage]
#
#   all          Phase 1-9 full deployment
#   prep         Phase 1 : timezone, NTP, swap, base packages
#   packages     Phase 2 : PHP 8.4, Nginx, PostgreSQL, Redis, Fail2ban, ClamAV
#   database     Phase 3a: PostgreSQL tuning + role, Redis hardening
#   nextcloud    Phase 3b: Nextcloud code, config.php, occ install
#   web          Phase 4 : Nginx site, Brotli, PHP tuning, TLS (certbot)
#   security     Phase 5 : UFW, Fail2ban jails, SSH hardening
#   features     Phase 6 : ClamAV integration + systemd maintenance timers
#   monitoring   Phase 7 : Prometheus, exporters, Grafana (ENABLE_MONITORING=yes)
#   backup       Phase 8 : backup dir + AES-256 encryption key
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config"
DEPLOY_DIR="/opt/cloudvault"

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
NC_DOMAIN="${NC_DOMAIN:-localhost}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"
NC_PHP_VER="${NC_PHP_VER:-8.4}"
NC_BASE="${NC_BASE:-/var/www/nextcloud}"
NC_DATA_DIR="${NC_DATA_DIR:-${NC_BASE}/data}"
NC_DB_NAME="${NC_DB_NAME:-nextcloud}"
NC_DB_USER="${NC_DB_USER:-nextcloud}"
NC_ADMIN_USER="${NC_ADMIN_USER:-admin}"
NC_ADMIN_PASS="${NC_ADMIN_PASS:-$(openssl rand -base64 18)}"
NC_DB_PASS="${NC_DB_PASS:-$(openssl rand -base64 24)}"
REDIS_PASS="${REDIS_PASS:-$(openssl rand -base64 24)}"
GRAFANA_DB_PASS="${GRAFANA_DB_PASS:-$(openssl rand -base64 24)}"
PROM_SCRAPE_SECRET="${PROM_SCRAPE_SECRET:-$(openssl rand -base64 32)}"



ADMIN_IP_WHITELIST="${ADMIN_IP_WHITELIST:-}"   # e.g. "203.0.113.10/32"
ENABLE_MONITORING="${ENABLE_MONITORING:-no}"   # Phase 7 is heavy-weight

LOG_DIR="/var/log/cloudvault"
LOG="${LOG_DIR}/install.log"
mkdir -p "${LOG_DIR}"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "[$(date '+%F %T')] ${GREEN}${1}${NC}"; echo "[$(date '+%F %T')] $1" >> "${LOG}"; }
warn() { echo -e "[$(date '+%F %T')] ${YELLOW}${1}${NC}"; echo "[$(date '+%F %T')] WARN $1" >> "${LOG}"; }
fail() { echo -e "[$(date '+%F %T')] ${RED}${1}${NC}" >&2; exit 1; }

require_root() { [[ ${EUID} -eq 0 ]] || fail "Please run as root."; }

deploy_scripts() {
  # First run: mirror the scripts/ directory into /opt/cloudvault/scripts
  if [[ ! -f "${DEPLOY_DIR}/scripts/install.sh" ]]; then
    mkdir -p "${DEPLOY_DIR}/scripts"
    cp -r "${SCRIPT_DIR}/." "${DEPLOY_DIR}/scripts/"
    chmod +x "${DEPLOY_DIR}"/scripts/*.sh
  fi
  if [[ ! -f "${DEPLOY_DIR}/config/nginx/sites-available/cloudvault.conf" && -d "${CONFIG_DIR}" ]]; then
    cp -r "${CONFIG_DIR}" "${DEPLOY_DIR}/config"
  fi
}

apt_quiet() {
  apt-get -q -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" "$@"
}

occ() {
  sudo -u www-data php "${NC_BASE}/occ" "$@"
}

# ---------------------------------------------------------------------------
# Phase 1 - system preparation
# ---------------------------------------------------------------------------
phase1_prep() {
  require_root
  log "Phase 1: Debian 13 (Trixie) preparation"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt_quiet upgrade
  apt_quiet install -y \
    ca-certificates curl gnupg lsb-release software-properties-common \
    tzdata chrony htop sysstat openssl rsync jq unzip \
    unattended-upgrades

  # Swap (>= 2 GB)
  if ! swapon --show | grep -q '/swapfile'; then
    log "Creating 2G swapfile"
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile && swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi

  # Timezone + NTP (set your Region/City)
  timedatectl set-timezone "${TZ:-Etc/UTC}" 2>/dev/null || true
  systemctl enable --now chrony >/dev/null 2>&1
  log "Phase 1 complete."
}

# ---------------------------------------------------------------------------
# Phase 2 - core packages
# ---------------------------------------------------------------------------
phase2_packages() {
  require_root
  log "Phase 2: core package installation"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update

  # PHP 8.4 (native in Trixie) + Nextcloud extensions
  apt_quiet install -y \
    php${NC_PHP_VER}-fpm \
    php${NC_PHP_VER}-cli \
    php${NC_PHP_VER}-gd \
    php${NC_PHP_VER}-intl \
    php${NC_PHP_VER}-bz2 \
    php${NC_PHP_VER}-curl \
    php${NC_PHP_VER}-imagick \
    php${NC_PHP_VER}-mbstring \
    php${NC_PHP_VER}-zip \
    php${NC_PHP_VER}-xml \
    php${NC_PHP_VER}-json \
    php${NC_PHP_VER}-pgsql \
    php${NC_PHP_VER}-redis \
    php${NC_PHP_VER}-apcu \
    php${NC_PHP_VER}-bcmath \
    php${NC_PHP_VER}-gmp \
    php${NC_PHP_VER}-sysvshm \
    php${NC_PHP_VER}-sysvsem \
    php${NC_PHP_VER}-sysvmsg \
    php${NC_PHP_VER}-smbclient

  # Web server + Brotli module + certbot
  apt_quiet install -y \
    nginx libnginx-mod-http-brotli-filter \
    certbot python3-certbot-nginx

  # Data stores
  apt_quiet install -y postgresql postgresql-contrib redis-server

  # Security / AV
  apt_quiet install -y ufw fail2ban apparmor-utils \
    clamav clamav-daemon clamav-freshclam

  # Monitoring (Phase 7)
  if [[ "${ENABLE_MONITORING}" == "yes" ]]; then
    apt_quiet install -y \
      prometheus prometheus-node-exporter \
      prometheus-postgres-exporter prometheus-redis-exporter grafana
  fi

  systemctl enable --now php${NC_PHP_VER}-fpm nginx redis-server postgresql
  systemctl enable --now fail2ban clamav-daemon clamav-freshclam
  log "Phase 2 complete."
}

# ---------------------------------------------------------------------------
# Phase 3a - PostgreSQL + Redis
# ---------------------------------------------------------------------------
phase3_database() {
  require_root
  log "Phase 3a: PostgreSQL tuning and roles"

  local pgver pg_conf
  pgver="$(ls /etc/postgresql/ | sort -V | tail -1)"
  pg_conf="/etc/postgresql/${pgver}/main/postgresql.conf"

  # Tuning block (values proportional to server RAM; adjust as needed)
  if ! grep -q 'CloudVault tuning' "${pg_conf}"; then
    cat >> "${pg_conf}" <<'EOF'

# ---- CloudVault tuning (SSD/NVMe) ----
shared_buffers = 1GB                # ~25% of total RAM
effective_cache_size = 3GB          # ~75% of total RAM
work_mem = 16MB
maintenance_work_mem = 256MB
max_connections = 200
wal_buffers = 16MB
synchronous_commit = off
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
EOF
    systemctl restart postgresql
  fi

  # Role + database (idempotent)
  su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${NC_DB_USER}'\"" | grep -q 1 \
    || su - postgres -c "psql -c \"CREATE ROLE ${NC_DB_USER} LOGIN PASSWORD '${NC_DB_PASS}'\""
  su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${NC_DB_NAME}'\"" | grep -q 1 \
    || su - postgres -c "psql -c \"CREATE DATABASE ${NC_DB_NAME} OWNER ${NC_DB_USER} ENCODING 'UTF8' TEMPLATE template0\""

  log "PostgreSQL ready (db=${NC_DB_NAME}, user=${NC_DB_USER})."

  # Redis hardening
  log "Phase 3a: Redis hardening"
  sed -i -E "s/^(requirepass .*)/requirepass ${REDIS_PASS}/" /etc/redis/redis.conf \
    || echo "requirepass ${REDIS_PASS}" >> /etc/redis/redis.conf
  sed -i -E 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
  sed -i -E 's/^#? *protected-mode .*/protected-mode yes/' /etc/redis/redis.conf
  grep -q '^maxmemory ' /etc/redis/redis.conf || echo 'maxmemory 1gb' >> /etc/redis/redis.conf
  grep -q '^maxmemory-policy' /etc/redis/redis.conf || echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf
  grep -q '^rename-command FLUSHALL' /etc/redis/redis.conf || echo 'rename-command FLUSHALL ""' >> /etc/redis/redis.conf
  grep -q '^rename-command FLUSHDB' /etc/redis/redis.conf || echo 'rename-command FLUSHDB ""' >> /etc/redis/redis.conf
  systemctl restart redis-server
  log "Redis ready."
}

# ---------------------------------------------------------------------------
# Phase 3b - Nextcloud
# ---------------------------------------------------------------------------
phase3_nextcloud() {
  require_root
  log "Phase 3b: Nextcloud installation"

  if [[ ! -d "${NC_BASE}" ]]; then
    mkdir -p /var/www
    curl -fsSL "https://download.nextcloud.com/server/releases/latest.zip" -o /tmp/nextcloud-latest.zip
    unzip -q /tmp/nextcloud-latest.zip -d /var/www
  else
    warn "${NC_BASE} already exists, skipping download."
  fi

  install -d -o www-data -g www-data -m 750 "${NC_DATA_DIR}"
  chown -R www-data:www-data "${NC_BASE}"

  # config.php
  local conf="${NC_BASE}/config/config.php"
  mkdir -p "$(dirname "${conf}")"
  cat > "${conf}" <<EOF
<?php
\$CONFIG = [
  'instanceid' => '$(cat /proc/sys/kernel/random/uuid | tr -d '-')',
  'passwordsalt' => '$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9')',
  'secret' => '$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9')',
  'trusted_domains' => [
    0 => '${NC_DOMAIN}',
    1 => 'localhost',
  ],
  'overwrite.cli.url' => 'https://${NC_DOMAIN}',
  'overwritehost' => '${NC_DOMAIN}',
  'overwriteprotocol' => 'https',
  'dbtype' => 'pgsql',
  'dbhost' => 'localhost',
  'dbname' => '${NC_DB_NAME}',
  'dbuser' => '${NC_DB_USER}',
  'dbpassword' => '${NC_DB_PASS}',
  'dbtableprefix' => 'oc_',
  'memcache.local' => '\\\\OC\\\\Memcache\\\\APCu',
  'memcache.distributed' => '\\\\OC\\\\Memcache\\\\Redis',
  'memcache.locking' => '\\\\OC\\\\Memcache\\\\Redis',
  'redis' => [
    'host' => '127.0.0.1',
    'port' => 6379,
    'password' => '${REDIS_PASS}',
  ],
  'log_type' => 'file',
  'logfile' => '${NC_DATA_DIR}/nextcloud.log',
  'loglevel' => 2,
  'remember_login_cookie_lifetime' => 60 * 60 * 24 * 15,
  'session_lifetime' => 60 * 60 * 24,
  'default_phone_region' => 'ID',
  'filesystem_check_changes' => 1,
];
EOF
  chown www-data:www-data "${conf}"
  chmod 640 "${conf}"

  # occ install
  occ maintenance:install \
    --database=pgsql \
    --database-name="${NC_DB_NAME}" \
    --database-user="${NC_DB_USER}" \
    --database-pass="${NC_DB_PASS}" \
    --database-host="localhost" \
    --admin-user="${NC_ADMIN_USER}" \
    --admin-pass="${NC_ADMIN_PASS}" \
    --data-dir="${NC_DATA_DIR}" 2>&1 | tee -a "${LOG}"

  occ config:system:set trusted_domains 0 --value="${NC_DOMAIN}"

  # Disable user registration & lost password
  occ config:system:set allow_user_registration --value=false --type=boolean
  occ config:system:set lost_password_link --value=""

  # Disable WebAuthn (Login with device)
  occ app:disable twofactor_webauthn 2>/dev/null || true

  # Background jobs every 5 minutes
  ( crontab -l 2>/dev/null | grep -v 'nextcloud/cron.php'; \
    echo "*/5 * * * * php -f ${NC_BASE}/cron.php" ) | crontab -

  # preserve generated credentials for later phases
  mkdir -p "${DEPLOY_DIR}/.secrets"
  umask 077
  {
    echo "NC_ADMIN_USER=${NC_ADMIN_USER}"
    echo "NC_ADMIN_PASS=${NC_ADMIN_PASS}"
    echo "NC_DB_PASS=${NC_DB_PASS}"
    echo "REDIS_PASS=${REDIS_PASS}"
    echo "GRAFANA_DB_PASS=${GRAFANA_DB_PASS}"
  } > "${DEPLOY_DIR}/.secrets/cloudvault.env"

  log "Nextcloud ready at https://${NC_DOMAIN}"
}

# ---------------------------------------------------------------------------
# Phase 4 - Nginx + TLS + Brotli + PHP tuning
# ---------------------------------------------------------------------------
phase4_web() {
  require_root
  log "Phase 4: Nginx, TLS, compression, PHP tuning"

  cp -r "${CONFIG_DIR}/nginx/." /etc/nginx/
  cp "${CONFIG_DIR}/php/8.4/fpm/pool.d/www.conf" /etc/php/${NC_PHP_VER}/fpm/pool.d/www.conf

  local site=/etc/nginx/sites-available/cloudvault.conf
  sed -i "s|__NC_DOMAIN__|${NC_DOMAIN}|g" "${site}"
  ln -sf "${site}" /etc/nginx/sites-enabled/cloudvault.conf
  rm -f /etc/nginx/sites-enabled/default

  # Demo login page (portfolio showcase) served from /demo/
  local demo_src="${SCRIPT_DIR}/../web/demo"
  if [[ -d "${demo_src}" ]]; then
    install -d -o www-data -g www-data -m 755 /var/www/cloudvault-demo
    cp -r "${demo_src}/." /var/www/cloudvault-demo/
    chown -R www-data:www-data /var/www/cloudvault-demo
    log "Demo page deployed at https://${NC_DOMAIN}/demo/ (demo / cloudvault)"
  else
    warn "web/demo not found; skipping demo page deployment."
  fi

  nginx -t || fail "nginx configuration invalid."
  systemctl reload nginx php${NC_PHP_VER}-fpm

  if [[ "${ENABLE_LETSENCRYPT:-yes}" == "yes" ]] && command -v certbot >/dev/null; then
    certbot --nginx --non-interactive --no-redirect \
      -d "${NC_DOMAIN}" --agree-tos -m "${ADMIN_EMAIL}"
    # keep OCSP stapling valid after each renewal
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/usr/bin/env bash
systemctl reload nginx
HOOK
    chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
  fi
  log "Phase 4 complete."
}

# ---------------------------------------------------------------------------
# Phase 5 - hardening + firewall
# ---------------------------------------------------------------------------
phase5_security() {
  require_root
  log "Phase 5: UFW firewall"
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  [[ -n "${ADMIN_IP_WHITELIST}" ]] && ufw allow from "${ADMIN_IP_WHITELIST}" to any port 22/tcp
  ufw allow 80/tcp   # HTTP -> redirect
  ufw allow 443/tcp  # HTTPS
  ufw deny out 25/tcp
  ufw --force enable

  log "Phase 5: Fail2ban jails"
  cp -r "${CONFIG_DIR}/fail2ban/." /etc/fail2ban/
  systemctl enable --now fail2ban
  fail2ban-client reload 2>/dev/null || systemctl restart fail2ban

  log "Phase 5: SSH hardening"
  local sshd=/etc/ssh/sshd_config
  sed -i -E 's/^#?PermitRootLogin.*/PermitRootLogin prohibit-password/' "${sshd}"
  sed -i -E 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' "${sshd}"
  sed -i -E 's/^#?MaxAuthTries.*/MaxAuthTries 3/' "${sshd}"
  sed -i -E 's/^#?AllowTcpForwarding.*/AllowTcpForwarding no/' "${sshd}"
  systemctl reload ssh
  warn "SSH key auth enforced - verify access before disconnecting."

  log "Phase 5 complete."
}

# ---------------------------------------------------------------------------
# Phase 6 - ClamAV + maintenance/backup timers
# ---------------------------------------------------------------------------
phase6_features() {
  require_root
  log "Phase 6: ClamAV integration"

  # AppArmor: allow clamd to scan the Nextcloud data volume
  if [[ -f /etc/apparmor.d/local/usr.sbin.clamd ]]; then
    echo -e "# CloudVault: allow clamd to scan Nextcloud data\nowner /var/www/nextcloud/data/** rk," >> /etc/apparmor.d/local/usr.sbin.clamd
    apparmor_parser -r /etc/apparmor.d/usr.sbin.clamd
  fi

  systemctl enable --now clamav-daemon clamav-freshclam
  freshclam --daemon || true

  # Nextcloud Antivirus app (socket-based clamd client)
  occ app:install files_antivirus || true
  occ config:app:set files_antivirus av_mode --value=daemon
  occ config:app:set files_antivirus av_socket --value=/var/run/clamav/clamd.ctl
  occ config:app:set files_antivirus av_stream_max_length --value=26214400

  log "Phase 6: systemd maintenance & backup timers"
  mkdir -p /etc/systemd/system
  cat > /etc/systemd/system/cloudvault-maintenance.service <<SVC
[Unit]
Description=CloudVault daily Nextcloud maintenance

[Service]
Type=oneshot
ExecStart=${DEPLOY_DIR}/scripts/maintenance.sh
SVC
  cat > /etc/systemd/system/cloudvault-maintenance.timer <<T
[Unit]
Description=CloudVault maintenance timer

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
T
  cat > /etc/systemd/system/cloudvault-backup.service <<SVC
[Unit]
Description=CloudVault encrypted backup

[Service]
Type=oneshot
ExecStart=${DEPLOY_DIR}/scripts/backup.sh
SVC
  cat > /etc/systemd/system/cloudvault-backup.timer <<T
[Unit]
Description=CloudVault backup timer

[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
T
  systemctl daemon-reload
  systemctl enable --now cloudvault-maintenance.timer cloudvault-backup.timer
  log "Phase 6 complete."
}

# ---------------------------------------------------------------------------
# Phase 8 - backup key bootstrap
# ---------------------------------------------------------------------------
phase8_backup() {
  require_root
  mkdir -p "${DEPLOY_DIR}/backup"
  if [[ ! -f /etc/cloudvault/backup.key ]]; then
    mkdir -p /etc/cloudvault && chmod 700 /etc/cloudvault
    openssl rand -hex 32 > /etc/cloudvault/backup.key
    chmod 600 /etc/cloudvault/backup.key
    log "AES-256 backup key created: /etc/cloudvault/backup.key"
    warn "Store this key offsite - without it backups cannot be restored."
  fi
}

# ---------------------------------------------------------------------------
# Phase 7 - monitoring (optional)
# ---------------------------------------------------------------------------
phase7_monitoring() {
  require_root
  if [[ "${ENABLE_MONITORING}" != "yes" ]]; then
    warn "Set ENABLE_MONITORING=yes to install Prometheus/Grafana."
    return 0
  fi
  apt_quiet install -y prometheus prometheus-node-exporter \
    prometheus-postgres-exporter prometheus-redis-exporter grafana

  # bind exporters to loopback only
  sed -i -E 's/^.*web.listen-address.*$/ARGS="--web.listen-address=127.0.0.1:9100"/' /etc/default/prometheus-node-exporter 2>/dev/null || true

  cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: node
    static_configs:
      - targets: ['127.0.0.1:9100']
  - job_name: nginx
    metrics_path: /metrics
    static_configs:
      - targets: ['127.0.0.1:9113']
  - job_name: postgres
    static_configs:
      - targets: ['127.0.0.1:9187']
  - job_name: redis
    static_configs:
      - targets: ['127.0.0.1:9121']
EOF
  systemctl enable --now prometheus prometheus-node-exporter
  systemctl enable --now prometheus-postgres-exporter prometheus-redis-exporter 2>/dev/null || true

  systemctl enable --now grafana-server 2>/dev/null || true
  log "Monitoring ready (Grafana: http://127.0.0.1:3000 behind Nginx TLS proxy)."
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
deploy_scripts
case "${1:-all}" in
  all)        phase1_prep; phase2_packages; phase3_database; phase3_nextcloud;
              phase4_web; phase5_security; phase6_features;
              phase8_backup; phase7_monitoring ;;
  prep)       phase1_prep ;;
  packages)   phase2_packages ;;
  database)   phase3_database ;;
  nextcloud)  phase3_nextcloud ;;
  web)        phase4_web ;;
  security)   phase5_security ;;
  features)   phase6_features ;;
  monitoring) phase7_monitoring ;;
  backup)     phase8_backup ;;
  *) echo "Unknown stage: ${1:-}"; exit 2 ;;
esac

echo
echo "=== CloudVault bootstrap complete ==="
echo "URL      : https://${NC_DOMAIN}"
echo "Admin    : ${NC_ADMIN_USER}"
echo "Secret   : ${DEPLOY_DIR}/.secrets/cloudvault.env"
echo
