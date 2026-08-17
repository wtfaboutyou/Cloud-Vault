# MONITORING.md

Monitoring, metrics, dashboards, and alerting for CloudVault.

---

## 1. Components

| Component | Port | Role |
|-----------|------|------|
| Prometheus | 9090 | Metrics collection (loopback) |
| Alertmanager | 9093 | Alert routing/notifications (loopback) |
| Grafana | 3000 | Dashboards + alert UI (loopback, published via Nginx TLS) |
| node-exporter | 9100 | Host metrics (loopback) |
| nginx stub_status | 9113 | Nginx active connections (loopback) |
| postgres-exporter | 9187 | PostgreSQL metrics (loopback) |
| redis-exporter | 9121 | Redis metrics (loopback) |

> All exporters bind to `127.0.0.1` only — **never** expose 9090/3000 publicly.

## 2. Installation

```bash
ENABLE_MONITORING=yes sudo bash scripts/install.sh monitoring
```

Installs Prometheus, exporters, and Grafana and deploys:

- `/etc/prometheus/prometheus.yml` (see `config/prometheus/prometheus.yml`)
- `/etc/prometheus/alert.rules.yml` (see `config/prometheus/alert.rules.yml`)

## 3. Scrape Targets

```yaml
scrape_configs:
  - job_name: node      → 127.0.0.1:9100
  - job_name: nginx     → 127.0.0.1:9113/metrics   (nginx-prometheus-exporter)
  - job_name: postgres  → 127.0.0.1:9187
  - job_name: redis     → 127.0.0.1:9121
```

Nginx metrics rely on the `stub_status` endpoint defined in the Nginx config under a
loopback-only listener (`127.0.0.1:9113/metrics`).

## 4. Alert Rules

Alertmanager rules (in `alert.rules.yml`) fire on:

- **ServiceDown** — any scraped target unreachable.
- **HighCPUUsage** — >90% for 10m.
- **HighMemoryUsage** — >85% used for 10m.
- **DiskSpaceLow / Critical** — <15% / <5% free (matches the >85% storage threshold in
  the spec).
- **PostgresReplicationLag**, **RedisConnectionErrors**.

Install Alertmanager to route e.g. email/webhook/Slack:

```bash
apt install prometheus-alertmanager
# configure /etc/prometheus/alertmanager.yml and restart
```

Grafana dashboards then surface these as notification panels.

## 5. Grafana Setup

1. Log in at `https://<DOMAIN>/grafana` (or via SSH tunnel to `127.0.0.1:3000`).
2. Add **Prometheus** data source → `http://127.0.0.1:9090`.
3. Import the Nextcloud/Postgres/Redis dashboards (IDs from grafana.com/import).
4. Configure **Alerting → Notification channels** (email, webhook, Slack).

## 6. Application-Level Health

`/opt/cloudvault/scripts/healthcheck.sh` is the single source of truth for the
Nextcloud platform:

```bash
sudo bash /opt/cloudvault/scripts/healthcheck.sh       # human report
sudo bash /opt/cloudvault/scripts/healthcheck.sh --json   # JSON for scraping
```

Checks: nginx, php-fpm, postgresql, redis, fail2ban(+banned IP count), clamav,
UFW active, disk usage %, memory %, load avg, TLS cert expiry days, Nextcloud `occ`.
Exit code: `0` healthy, `1` warnings, `2` critical.

The JSON output can be tailed by Prometheus `textfile` collector so alerts can
fire on Nextcloud-application symptoms too.

## 7. Key Metrics to Watch

| Metric | PromQL example | Alert on |
|--------|----------------|----------|
| CPU | `100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100)` | >90% |
| Memory | `(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)*100` | >85% |
| Disk | `node_filesystem_avail_bytes{...} / node_filesystem_size_bytes{...}` | <15% |
| Nginx connections | `nginx_connections_active` | >4096 |
| Postgres connections | `pg_stat_database_numbackends` | near max_connections |
| Redis memory | `redis_memory_used_bytes` | >maxmemory |
| Fail2ban bans | `fail2ban banned` health output | rapid rise |

## 8. Security Note

- Prometheus/Grafana are bound to loopback; UFW blocks external access.
- To publish Grafana, reverse-proxy it through the CloudVault Nginx with a
  `location /grafana/` block, TLS, and authentication — do not open the raw port.

## 9. Operational Commands

```bash
systemctl status prometheus grafana-server prometheus-node-exporter
systemctl restart prometheus grafana-server
sudo bash /opt/cloudvault/scripts/healthcheck.sh --json
```