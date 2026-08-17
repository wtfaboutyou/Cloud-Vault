# SECURITY.md

Security hardening and intrusion-prevention reference for CloudVault.

---

## 1. TLS & Transport Security (Nginx)

- **TLS 1.3 / 1.2 only**, strict PFS cipher suite.
- **OCSP Stapling** enabled + verify; resolver configured.
- **HSTS preload**: `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
- `server_tokens off`, `ssl_session_tickets off`, session cache shared.

See `config/nginx/sites-available/cloudvault.conf`.

## 2. Security Headers

| Header | Value |
|--------|-------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` |
| `X-Frame-Options` | `SAMEORIGIN` |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `no-referrer-when-downgrade` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | `default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'` |

## 3. Firewall (UFW)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow from <ADMIN_IP> to any port 22/tcp   # optional
ufw allow 80/tcp
ufw allow 443/tcp
ufw deny out 25/tcp
ufw --force enable
```

Managed by `config/ufw/ufw-setup.sh`.

## 4. Fail2ban Jails

| Jail | Monitors | Action |
|------|----------|--------|
| `nextcloud` | `/var/www/nextcloud/data/nextcloud.log` | UFW ban, 5 tries/10 min, 1h ban |
| `nginx-auth` | `/var/log/nginx/error.log` | UFW ban |
| `nginx-botsearch` | `/var/log/nginx/access.log` | UFW ban |
| `sshd` | sshd backend | UFW ban |

**Operations:**

```bash
fail2ban-client status nextcloud
fail2ban-client set nextcloud unbanip <IP>
sudo ufw status numbered            # verify ban rules inserted
```

**Whitelist** admin IPs in `ignoreip` in `/etc/fail2ban/jail.d/nextcloud.conf`.

## 5. SSH Hardening (`/etc/ssh/sshd_config`)

```ini
PermitRootLogin prohibit-password
PasswordAuthentication no
MaxAuthTries 3
AllowTcpForwarding no
```

Apply: `systemctl reload ssh`. **Ensure a valid key is installed first.**

## 6. Redis Hardening

- `bind 127.0.0.1 -::1`, `protected-mode yes`
- `requirepass <strong-password>` (mirrored into Nextcloud `config.php`)
- `rename-command FLUSHALL ""`, `FLUSHDB ""`, `SHUTDOWN ""`
- `maxmemory 1gb`, `maxmemory-policy allkeys-lru`

See `config/redis/redis.conf`.

## 7. PostgreSQL Security

- Localhost-only, peer auth for `postgres`; Nextcloud connects via `md5/scram` over
  loopback with a dedicated role (no superuser).
- Consider editing `pg_hba.conf` to `scram-sha-256`.

## 8. Web Application Hardening

Nginx blocks:

```nginx
location ~ ^/(build|tests|config|lib|3rdparty|templates|data)/ { deny all; }
location ~ ^/(\.ht|\.user\.ini|\.env|\.git|\.svn|\.DS_Store) { deny all; }
```

- Dotfiles, `.env`, VCS dirs are denied.
- Rate limiting zones: `login` (10 r/m), `api` (30 r/m), `generic` (60 r/m).
- `client_max_body_size 10G` for large uploads (WebDAV endpoints set `0`).

## 9. ClamAV Antivirus

- `clamd` scans every upload via Nextcloud **files_antivirus** (socket mode).
- AppArmor profile extended so clamd can read `/var/www/nextcloud/data/**`.
- Update signatures: `freshclam` daemon + systemd service.

## 10. Monitoring Exposure

- Prometheus (9090), Alertmanager (9093), Grafana (3000) bind to **127.0.0.1 only**.
- Grafana is published behind the Nginx TLS proxy with authentication, or blocked
  by UFW for everyone except admin IPs. Never open 9090/3000 to the internet.

## 11. Automatic Security Updates

```bash
apt install unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

## 12. Certificate Lifecycle

- Certbot auto-renews; deploy hook reloads Nginx (`config/ufw/certbot-renew-hook.sh`).
- OCSP stapling keeps the signed response cached and valid after each renewal.

## 13. Backup Encryption

- All archives encrypted **AES-256-CBC** with PBKDF2 (key: `/etc/cloudvault/backup.key`).
- Store the key **offsite**; without it archives cannot be restored.
- SHA-256 checksums are stored beside each archive and verified by `backup.sh verify`.

See [BACKUP.md](BACKUP.md) for the full procedure.
