#!/bin/bash
# CloudVault — 6 Advanced Features Demo (Simple Commands)
# Jalankan: sudo bash /root/cloudvault/scripts/demo-features.sh

C='\033[0;36m'
G='\033[0;32m'
Y='\033[1;33m'
B='\033[1m'
NC='\033[0m'

pause() { echo -e "\n${Y}>>> Tekan Enter untuk lanjut...${NC}"; read; }

echo -e "${B}"
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║   CloudVault — 6 Advanced Features Demo       ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo -e "${NC}"

# ═══════════════════════════════════════════════════
# FEATURE 1
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  1. Intrusion Prevention${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ ufw status verbose${NC}\n"
ufw status verbose

echo -e "\n${Y}\$ fail2ban-client status${NC}\n"
fail2ban-client status

echo -e "\n${Y}\$ grep limit_req_zone /opt/cloudvault/config/nginx/nginx.conf${NC}\n"
grep limit_req_zone /opt/cloudvault/config/nginx/nginx.conf

pause

# ═══════════════════════════════════════════════════
# FEATURE 2
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  2. Brotli Compression + TLS 1.3 Hardening${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ openssl s_client -connect localhost:443 </dev/null | grep Protocol${NC}\n"
openssl s_client -connect localhost:443 </dev/null 2>&1 | grep Protocol | head -1

echo -e "\n${Y}\$ curl -skI https://localhost${NC}\n"
curl -skI https://localhost 2>/dev/null | grep -iE "HTTP/2|strict-transport|server:"

echo -e "\n${Y}\$ curl -sk -H 'Accept-Encoding: br' -o /dev/null -w '%{size_download}' https://localhost/${NC}\n"
plain=$(curl -skL -o /dev/null -w "%{size_download}" https://localhost/ 2>/dev/null)
brotli=$(curl -skL -H 'Accept-Encoding: br' -o /dev/null -w "%{size_download}" https://localhost/ 2>/dev/null)
gzip=$(curl -skL -H 'Accept-Encoding: gzip' -o /dev/null -w "%{size_download}" https://localhost/ 2>/dev/null)
echo "  Plain:   ${plain} bytes"
echo "  Gzip:    ${gzip} bytes"
echo "  Brotli:  ${brotli} bytes"
[ "$plain" -gt 0 ] 2>/dev/null && echo "  Saving:  $((100 - brotli * 100 / plain))% smaller with Brotli"

pause

# ═══════════════════════════════════════════════════
# FEATURE 3
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  3. ClamAV Antivirus Auto-Scanning${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ systemctl status clamav-daemon${NC}\n"
systemctl status clamav-daemon --no-pager | head -8

echo -e "\n${Y}\$ clamdscan --version${NC}\n"
clamdscan --version 2>/dev/null | head -1

echo -e "\n${Y}\$ ls /var/run/clamav/clamd.ctl${NC}\n"
ls -la /var/run/clamav/clamd.ctl 2>/dev/null

pause

# ═══════════════════════════════════════════════════
# FEATURE 4
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  4. Automated OCC Maintenance${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ systemctl list-timers cloudvault-*${NC}\n"
systemctl list-timers cloudvault-* --no-pager

echo -e "\n${Y}\$ grep occ /opt/cloudvault/scripts/maintenance.sh${NC}\n"
grep "occ" /opt/cloudvault/scripts/maintenance.sh | grep -v "^#"

pause

# ═══════════════════════════════════════════════════
# FEATURE 5
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  5. Encrypted Backup + Retention${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ ls -la /opt/cloudvault/backup/${NC}\n"
ls -la /opt/cloudvault/backup/

echo -e "\n${Y}\$ ls -la /etc/cloudvault/backup.key${NC}\n"
ls -la /etc/cloudvault/backup.key

echo -e "\n${Y}\$ sudo bash /opt/cloudvault/scripts/backup.sh${NC}\n"
echo "  (skip — hanya tampilkan struktur backup)"
ls -lh /opt/cloudvault/backup/daily/ 2>/dev/null | tail -5

pause

# ═══════════════════════════════════════════════════
# FEATURE 6
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  6. Health Checks + Grafana Alerting${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${Y}\$ sudo bash /opt/cloudvault/scripts/healthcheck.sh${NC}\n"
sudo bash /opt/cloudvault/scripts/healthcheck.sh 2>/dev/null

echo -e "\n${Y}\$ curl -s http://127.0.0.1:9090/api/v1/targets${NC}\n"
curl -s http://127.0.0.1:9090/api/v1/targets 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for t in data.get('data',{}).get('activeTargets',[]):
        print(f\"    {t['labels'].get('job','?'):15s} {t['health']:5s} {t['scrapeUrl']}\")
except: pass
" 2>/dev/null

# ═══════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════
echo -e "\n${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${B}  SELESAI — 6 Advanced Production Features${NC}"
echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
