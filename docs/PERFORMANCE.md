# CloudVault - PERFORMANCE.md

Performance tuning and benchmarking reference for CloudVault.

---

## 1. Nginx (Loading & Download Speed)

Main config: `config/nginx/nginx.conf` + `config/nginx/sites-available/cloudvault.conf`.

```nginx
worker_processes auto;
worker_connections 4096;
sendfile on;
sendfile_max_chunk 1m;      # don't pin a worker on one huge download
tcp_nopush on;
tcp_nodelay on;
keepalive_timeout 65;
keepalive_requests 1000;    # reuse the same TCP connection for many requests
```

- **HTTP/2** on the TLS listener + keepalive = far fewer round-trips per page load.
- **`fastcgi_buffering off`** streams large file downloads straight to the client
  instead of buffering the whole file in Nginx RAM.
- **Static assets** get `expires 30d` + `Cache-Control: public, immutable` and
  `open_file_cache` so Nginx serves CSS/JS/logos from kernel cache without re-hitting disk.
- **Upstream `keepalive 32`** reuses the PHP-FPM Unix socket connections instead of
  opening a fresh socket per request. (Full `fastcgi_keepalive` reuse needs Nginx ≥
  1.27; the Debian 13 stock Nginx 1.26 still benefits from OS-level socket reuse via
  the `keepalive` upstream directive.)

```
brotli on; brotli_comp_level 6;   # sub-second TLS, Brotli, keepalive
```

## 2. Upload Speed

Uploads pass from client → Nginx → PHP-FPM → Nextcloud storage. Bottlenecks there are
disk spooling, worker starvation, and timeouts. Config tuned for fast large-file uploads:

- `client_max_body_size 10G` — biggest allowed single upload.
- `client_body_buffer_size 128k` — small bodies buffered in RAM, not spooled to disk.
- `client_body_temp_path /var/lib/nginx/body 2 4d` — big uploads stage on the fast
  (SSD) spool instead of the system temp disk.
- `client_body_timeout 3600` — slow/limited uplinks aren't killed mid-upload.
- `fastcgi_request_buffering off` — streaming to PHP-FPM without Nginx buffering the
  whole body, so uploads start writing to disk immediately.
- PHP-FPM: mirrored `upload_tmp_dir = /var/lib/nginx/body`, `post_max_size 11G`,
  `upload_max_filesize 10G`.

### PHP-FPM 8.4

From `config/php/8.4/fpm/pool.d/www.conf`:

```ini
pm = dynamic
pm.max_children = 100
pm.start_servers = 10
pm.min_spare_servers = 8
pm.max_spare_servers = 20
pm.max_requests = 2000

php_value[memory_limit] = 1G
php_value[upload_max_filesize] = 10G
php_value[post_max_size] = 11G
php_value[realpath_cache_size] = 4096k
php_value[realpath_cache_ttl] = 600
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 20000
opcache.jit = tracing
opcache.jit_buffer_size = 100M
```

- **Realpath cache** (4096k) skips repeated filesystem stat() calls when Nextcloud
  scans directories — big effect on large file listings.
- **OPcache + JIT** cut PHP CPU per request.
- More pool workers (100) absorb upload concurrency without queueing.
- `request_slowlog_timeout = 5s` catches slow endpoints.

## 3. PostgreSQL 17

From `config/postgresql/17/main/postgresql.conf`:

```ini
shared_buffers = 1GB           # 25% RAM
effective_cache_size = 3GB     # 75% RAM
work_mem = 16MB
maintenance_work_mem = 256MB
wal_buffers = 16MB
synchronous_commit = off       # perf trade-off
checkpoint_completion_target = 0.9
random_page_cost = 1.1         # SSD/NVMe
effective_io_concurrency = 200 # NVMe
```

Scale these proportionally to server RAM (see comments in the file).

## 4. Redis 7

From `config/redis/redis.conf`:

```ini
maxmemory 1gb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
```

- `allkeys-lru` keeps hot cache keys resident.
- `appendfsync everysec` balances durability vs throughput.
- Nextcloud uses Redis for `memcache.local` (APCu) / `memcache.distributed` /
  `memcache.locking`, eliminating per-request DB hits and file-lock contention.

## 5. Compression Test

```bash
# plain
curl -sk -o /dev/null -w '%{size_download}\n' https://<DOMAIN>/
# gzip
curl -sk -H 'Accept-Encoding: gzip' -o /dev/null -w '%{size_download}\n' https://<DOMAIN>/
# brotli
curl -sk -H 'Accept-Encoding: br' -o /dev/null -w '%{size_download}\n' https://<DOMAIN>/
```

Expected: brotli < gzip < plain for text assets.

## 6. Benchmarking

`/opt/cloudvault/benchmark/benchmark.sh` measures response time, TLS handshake,
compression sizes, and throughput:

```bash
bash /opt/cloudvault/benchmark/benchmark.sh https://localhost
```

Results are written to `benchmark/results/`.

## 7. Tuning Checklist by RAM

| RAM  | Postgres `shared_buffers` | `effective_cache_size` | PHP `pm.max_children` |
|------|---------------------------|------------------------|-----------------------|
| 4 GB | 1 GB                      | 3 GB                   | 30                   |
| 8 GB | 2 GB                      | 6 GB                   | 50                   |
| 16 GB| 4 GB                      | 12 GB                  | 100                  |

## 8. Measured Benchmark Results (Phase 9, 2026-08-17)

Environment: VM, 3 vCPU / 3.8 GB RAM, SATA disk, ClamAV active (socket scan on
every upload), Nextcloud 34.0.2. Raw files: `benchmark/results/`.

### WebDAV throughput (3 rounds, warm cache, via localhost HTTPS)

| Size  | Upload best | Upload avg | Download best | Download avg |
|-------|-------------|------------|---------------|--------------|
| 1 MB  | 0.6 s  (1.6 MB/s) | 3.7 s | 0.5 s (2.0 MB/s)  | 1.4 s |
| 5 MB  | 0.7 s  (7.6 MB/s) | 8.3 s | 0.5 s (10.0 MB/s) | 0.5 s |
| 25 MB | 1.9 s  (12.9 MB/s) | 38.5 s | 0.6 s (43.3 MB/s) | 0.6 s |

Interpretation:
- **Download** scales linearly with size and is disk/network bound (~40 MB/s).
- **Upload avg >> best**: the spread is caused by synchronous **ClamAV socket
  scanning** of every uploaded file plus RAM/IO contention on the 3.8 GB VM
  (ClamAV daemon alone holds ~1 GB RSS). On idle runs 1 MB uploads complete in
  ~0.6–1.8 s. Reducing upload latency = larger ClamAV `StreamMaxLength`/`MaxFileSize`
  exemptions, more RAM, or NVMe.
- First request after a cold PHP-FPM/OPcache restart is slower (5–20 s warm-up),
  not representative of steady state.

### Compression (CSS asset, 9711 bytes plain)

| Encoding | Size | Savings |
|----------|------|---------|
| none     | 9711 B | — |
| gzip     | 2888 B | 70.3% |
| brotli   | 2610 B | 73.1% |

### SSL / TLS (self-signed test cert)

- Protocols: TLS 1.3 + TLS 1.2 only (TLS 1.0/1.1 rejected).
- Negotiated: TLSv1.3 `TLS_AES_256_GCM_SHA384`; TLS 1.2 `ECDHE-RSA-AES256-GCM-SHA384`.
- Weak suites (EXPORT/NULL/RC4/DES) rejected.
- HSTS `max-age=63072000; includeSubDomains; preload` present.
- HTTP/2 active. OCSP stapling off (self-signed — enable with a real CA cert).

> NOTE: documented tuning values (e.g. `pm.max_children 100`,
> `client_body_buffer_size 128k`) are the target production profile. The live
> test VM runs a smaller profile (`pm.max_children 12`, `512k`) suited to its
> 3.8 GB RAM — align before real-world deployment.

## 9. Known Trade-offs

- `synchronous_commit = off` reduces write durability slightly in exchange for
  throughput — acceptable because file blobs are on disk and backups are nightly.
- Rate limiting intentionally throttles login/API to mitigate brute-force; tune the
  `burst` parameter if legitimate clients hit `429`.
