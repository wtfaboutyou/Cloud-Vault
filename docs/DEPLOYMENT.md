# DEPLOYMENT.md

Post-install verification, go-live, and day-2 operations for CloudVault.

---

## 1. First Login

1. Browse to `https://<NC_DOMAIN>`.
2. Log in with the admin user from `.secrets/cloudvault.env`:
   ```bash
   cat /opt/cloudvault/.secrets/cloudvault.env
   ```
3. In **Settings → Overview** confirm:
   - Security & setup warnings empty (or addressed)
   - Background jobs: **Cron**
   - Database: **PostgreSQL**
   - No "missing indexes / columns / primary keys" warnings.

## 2. Verify Every Service

```bash
sudo bash /opt/cloudvault/scripts/healthcheck.sh
```

Expected green output for: nginx, php8.4-fpm, postgresql, redis-server, fail2ban,
clamav-daemon, clamav-freshclam, ufw, disk, memory, ssl.

## 3. Verification Matrix

| Check | Command | Expected |
|-------|---------|----------|
| Web root | `curl -skI https://<NC_DOMAIN>` | `200`, security headers present |
| HSTS preload | `curl -sI ... | grep -i strict-transport` | `max-age=63072000; ... preload` |
| TLS 1.3 | `openssl s_client -connect ... -tls1_3` | handshake OK |
| OCSP stapling | `openssl s_client -status -connect ...` | `OCSP Response Status: successful` |
| Brotli | `curl -sH 'Accept-Encoding: br' -D - -o /dev/null ...` | `content-encoding: br` |
| Rate limit | 11 rapid logins | `429 Too Many Requests` |
| Fail2ban | `fail2ban-client status nextcloud` | jail active |
| Redis | `redis-cli -a $REDIS_PASS ping` | `PONG` |
| PostgreSQL | `sudo -u postgres psql -c '\conninfo'` | connected |
| ClamAV | `clamdscan /var/www/nextcloud/data` | OK |

## 4. TLS Quality (SSL Labs)

```bash
# install sslscan for a quick check
apt install sslscan
sslscan https://<NC_DOMAIN>
```

Score on [SSL Labs](https://www.ssllabs.com/ssltest/) should be **A+** given:
TLS 1.3, HSTS preload, PFS ciphers, OCSP stapling, no TLS session tickets.

## 5. Go-Live Tasks

1. **Change the admin password** to a strong value.
2. **Send the admin an email invite** for new users, or use `occ user:add`.
3. **Restrict admin IPs**:
   ```bash
   sudo ufw allow from <ADMIN_IP> to any port 22/tcp
   ```
4. **Set trusted proxies** if behind an additional load balancer (optional).
5. **Review PHP settings** shown in Settings → Overview; adjust memory limit for
   large files if needed.
6. **Run first backups**:
   ```bash
   sudo bash /opt/cloudvault/scripts/backup.sh
   sudo bash /opt/cloudvault/scripts/backup.sh verify
   ```
7. **Enable UFW** already active from Phase 5 — confirm `ufw status` shows active.

## 6. Day-2 Operations

### Scheduled tasks
```bash
systemctl list-timers cloudvault-*            # maintenance 02:30, backup 03:00
systemctl list-timers --all | grep certbot    # TLS renewal
```

### Manual maintenance
```bash
sudo -u www-data php /var/www/nextcloud/occ maintenance:mode --on
sudo bash /opt/cloudvault/scripts/maintenance.sh
sudo -u www-data php /var/www/nextcloud/occ maintenance:mode --off
```

### Scaling (memory) adjustments
- PostgreSQL: `shared_buffers`/`effective_cache_size` in `postgresql.conf`.
- PHP-FPM: `pm.max_children` in `www.conf`.
- Redis: `maxmemory` in `redis.conf`.

## 7. Rollback

See [BACKUP.md](BACKUP.md) — `restore.sh` restores config, database, and data in
one step, wrapping the instance in maintenance mode.

## 8. TLS Renewal

Certbot auto-renews. The deploy hook reloads Nginx:

```bash
certbot renew --dry-run
cat /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```
