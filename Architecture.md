![Debian](https://img.shields.io/badge/Debian-13-A81D33?logo=debian&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-Latest-009639?logo=nginx&logoColor=white)
![Nextcloud](https://img.shields.io/badge/Nextcloud-Latest-0082C9?logo=nextcloud&logoColor=white)
![PHP](https://img.shields.io/badge/PHP-8.4.24-777BB4?logo=php&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

# Cloud Vault
CloudVault is a self-hosted cloud storage platform powered by Nextcloud, Nginx, PostgreSQL, and Redis on Debian 13. The project focuses on native deployment, web server architecture, security hardening, performance optimization, and Linux server administration without using Docker.

## ✨ Key Features

- 🔒 **HTTPS with Let's Encrypt**
  Secure all client-server communication using SSL/TLS certificates.

- 🌐 **Nginx Reverse Proxy**
  Efficient request routing with optimized web server configuration.

- 🛡️ **Security Hardening**
  Security headers, UFW firewall, Fail2Ban, and secure PHP-FPM configuration.

- ⚡ **Performance Optimization**
  Gzip compression, browser caching, optimized PHP-FPM, PostgreSQL, and Redis.

- 🚦 **Rate Limiting**
  Protect login and upload endpoints from brute-force and abuse.

- 🗄️ **PostgreSQL Integration**
  Reliable metadata storage with optimized database configuration.

- 🚀 **Redis File Locking & Caching**
  Improve responsiveness and prevent file conflicts during concurrent access.

- 📊 **Server Monitoring**
  Real-time monitoring with Prometheus and Grafana dashboards.

- 💾 **Automated Backup & Recovery**
  Scheduled backups for database, application configuration, and uploaded files.

- 📁 **Self-Hosted Cloud Storage**
  Private cloud storage powered by Nextcloud with full control over infrastructure.

- 🖥️ **Native Debian Deployment**
  Deploy directly on Debian 12 without Docker, providing full control over system administration.


## Project Structure
```
cloud-vault/
│
├── README.md
├── ROADMAP.md
├── LICENSE
│
├── configs/
│   ├── nginx/
│   ├── php/
│   ├── postgresql/
│   └── redis/
│
├── scripts/
│
├── docs/
│   ├── INSTALLATION.md
│   ├── DEPLOYMENT.md
│   ├── NGINX.md
│   ├── DATABASE.md
│   ├── SECURITY.md
│   ├── BACKUP.md
│   ├── MONITORING.md
│   └── SYSTEM_ARCHITECTURE.md
│
└── assets/
    ├── architecture.png
    ├── screenshots/
    └── diagrams/
```

## Roadmap

### Phase 1 — Environment Preparation

- [x] Install Debian 13
- [x] Configure hostname
- [x] Configure DNS
- [x] Update repositories
- [x] Configure swap
- [x] Create deployment directory

---

### Phase 2 — Core Services

- [x] Install Nginx
- [x] Install PHP-FPM 8.4
- [x] Install PostgreSQL 17
- [x] Install Redis 7
- [x] Install Nextcloud

---

### Phase 3 — Web Server Configuration

- [x] Configure Nginx
- [ ] Configure PHP-FPM
- [ ] Enable HTTPS
- [ ] Enable Brotli
- [ ] Configure Rate Limiting
- [ ] Configure Security Headers

---

### Phase 4 — Database & Storage

- [ ] Configure PostgreSQL
- [ ] Configure Redis
- [ ] Configure Data Directory
- [ ] Configure File Permissions

---

### Phase 5 — Security

- [ ] Configure UFW
- [ ] Configure Fail2ban
- [ ] Configure ClamAV
- [ ] Harden SSH
- [ ] Enable OCSP Stapling

---

### Phase 6 — Monitoring

- [ ] Install Prometheus
- [ ] Install Grafana
- [ ] Configure Exporters
- [ ] Create Dashboard

---

### Phase 7 — Backup & Maintenance

- [ ] Create Backup Script
- [ ] Create Restore Script
- [ ] Configure Cron Jobs
- [ ] Configure Health Check

---

### Phase 8 — Documentation

- [ ] Complete README
- [ ] Write Installation Guide
- [ ] Write Deployment Guide
- [ ] Write Security Guide
- [ ] Write Monitoring Guide

---

### Phase 9 — Testing & Optimization

- [ ] Upload Benchmark
- [ ] Download Benchmark
- [ ] SSL Test
- [ ] Security Validation
- [ ] Final Production Review
