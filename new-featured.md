# CLOUDVAULT WATCHTOWER — MASTER IMPLEMENTATION SPECIFICATION

You are working on the existing CloudVault repository:

https://github.com/wtfaboutyou/Cloud-Vault

CloudVault is an existing self-hosted infrastructure project built around Nextcloud.

IMPORTANT:
This is NOT a request to rebuild CloudVault.
This is NOT a request to replace Nextcloud.
This is NOT a request to redesign the existing infrastructure.

The goal is to ADD a new operational layer called:

    CloudVault Watchtower

Watchtower provides:

- Telegram notifications
- Telegram-based server status/health visibility
- background notification processing
- integration with Prometheus
- integration with Alertmanager
- integration with existing CloudVault healthchecks
- integration with existing backup/job events where safely possible
- operational observability

The existing CloudVault architecture is the foundation and MUST remain intact.

============================================================
0. ABSOLUTE ARCHITECTURE RULE
============================================================

WATCHTOWER IS ADDITIVE.

It must integrate WITH the existing CloudVault infrastructure.

It must NOT replace existing infrastructure.

It must NOT become a new application layer replacing Nextcloud.

It must NOT modify Nextcloud core.

It must NOT replace existing CloudVault automation.

It must NOT replace existing monitoring.

Think of Watchtower as:

    operational integration + notification + monitoring interface

NOT:

    replacement cloud application

============================================================
1. BEFORE WRITING CODE
============================================================

DO NOT immediately implement the feature.

First inspect the repository thoroughly.

Inspect at minimum:

- README
- directory structure
- deployment scripts
- install scripts
- systemd units
- systemd timers
- Nginx configuration
- PHP-FPM configuration
- Nextcloud configuration
- PostgreSQL configuration
- Redis configuration
- ClamAV configuration
- AppArmor configuration
- Fail2ban configuration
- Prometheus configuration
- Grafana configuration
- Alertmanager configuration
- existing healthchecks
- backup scripts
- restore scripts
- cron configuration
- monitoring scripts
- environment/secrets handling
- documentation
- existing tests
- existing CI/CD if present

Determine the ACTUAL current architecture.

Do not rely on assumptions from this prompt.

If the repository differs from this specification, the repository's existing architecture takes precedence unless a change is explicitly required for Watchtower.

After inspection, produce an architecture report before implementing.

The report must contain:

1. Current CloudVault architecture
2. Existing monitoring architecture
3. Existing backup architecture
4. Existing job/cron architecture
5. Existing authentication/user architecture
6. Existing healthcheck architecture
7. Where Watchtower can integrate safely
8. Files/configuration that should NOT be modified
9. Files/configuration that need to be added
10. Proposed implementation plan
11. Security risks
12. Rollback strategy

DO NOT modify files during this discovery phase.

============================================================
2. EXISTING CLOUDVAULT MUST REMAIN INTACT
============================================================

The following are existing infrastructure responsibilities.

They must remain the source of truth.

APPLICATION:

- Nextcloud

WEB:

- Nginx
- PHP-FPM

DATA:

- PostgreSQL
- Redis

SECURITY:

- ClamAV
- AppArmor
- Fail2ban

MONITORING:

- Prometheus
- Grafana
- Alertmanager

AUTOMATION:

- existing cron jobs
- existing systemd timers
- existing maintenance scripts
- existing backup scripts
- existing restore procedures
- existing healthchecks

Watchtower must integrate with these systems.

It must NOT silently replace them.

============================================================
3. HARD "DO NOT" RULES
============================================================

DO NOT:

1. Modify Nextcloud core.
2. Fork Nextcloud.
3. Replace Nextcloud with a custom file-storage application.
4. Build a second file-storage system.
5. Replace Nextcloud's cron system.
6. Replace existing Nextcloud background jobs.
7. Replace existing backup scripts.
8. Replace existing restore scripts.
9. Replace Prometheus.
10. Replace Grafana.
11. Replace Alertmanager.
12. Replace existing healthchecks.
13. Move existing services to a new architecture.
14. Introduce Docker/containers if the existing architecture is native Debian/systemd.
15. Introduce Kubernetes.
16. Expose Prometheus publicly.
17. Expose PostgreSQL publicly.
18. Expose Redis publicly.
19. Make Telegram a requirement for CloudVault operation.
20. Make Telegram the primary CloudVault authentication mechanism.
21. Store CloudVault passwords in Telegram.
22. Store Telegram bot tokens in the frontend.
23. Hard-code secrets.
24. Log Telegram bot tokens.
25. Log linking tokens.
26. Execute arbitrary shell commands from Telegram.
27. Implement arbitrary remote shell access.
28. Implement destructive Telegram commands in phase 1.
29. Scrape Grafana HTML for metrics.
30. Make Watchtower dependent on Grafana.
31. Make Nextcloud dependent on Watchtower.
32. Make backups dependent on Telegram.
33. Make uploads dependent on Telegram.
34. Make normal file operations dependent on Prometheus.
35. Rewrite unrelated parts of CloudVault.

If a feature seems to require one of these changes:

STOP.

Explain the conflict and propose an architecture-compatible alternative.

============================================================
4. FINAL ARCHITECTURE
============================================================

Conceptual architecture:

                         INTERNET / LAN
                              |
                              v
                     +------------------+
                     |      NGINX       |
                     | TLS / Proxy      |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     |    NEXTCLOUD     |
                     |   PHP-FPM        |
                     +--------+---------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
             +-------------+     +-------------+
             | PostgreSQL  |     |    Redis    |
             +-------------+     +-------------+


                  EXISTING MONITORING LAYER

             +----------------------------+
             |         PROMETHEUS         |
             +-------------+--------------+
                           |
                +----------+----------+
                |                     |
                v                     v
        +---------------+     +---------------+
        |    GRAFANA    |     | ALERTMANAGER  |
        +---------------+     +-------+-------+
                                      |
                                      v

                       +------------------------+
                       | CLOUDVAULT WATCHTOWER  |
                       |                        |
                       | Telegram Bot           |
                       | Notification Service   |
                       | Health Aggregator      |
                       | Prometheus Client      |
                       | Alert Receiver         |
                       +-----------+------------+
                                   |
                                   v
                            +--------------+
                            |   TELEGRAM   |
                            |     BOT      |
                            +--------------+

The important separation is:

Nextcloud = application/file storage

Prometheus = metrics source

Grafana = visualization

Alertmanager = monitoring alert routing

Watchtower = operational integration and notification layer

Telegram = administrator/user notification interface

============================================================
5. WATCHTOWER RESPONSIBILITIES
============================================================

Watchtower should handle:

A. Telegram bot integration
B. Telegram account linking
C. notification preferences
D. Telegram notifications
E. Telegram read-only commands
F. Prometheus metric queries
G. health aggregation
H. Alertmanager event handling
I. notification queue/retry
J. operational logging
K. Watchtower metrics
L. graceful failure handling

Watchtower should NOT handle:

- file storage
- file upload
- file download
- Nextcloud authentication
- database management
- Redis management
- replacing Nextcloud cron
- replacing backup
- replacing Prometheus
- replacing Grafana
- replacing Alertmanager

============================================================
6. WATCHTOWER DEPLOYMENT MODEL
============================================================

Use the existing CloudVault deployment philosophy.

If CloudVault is native Debian/systemd:

Watchtower should preferably be:

    cloudvault-watchtower.service

managed by systemd.

Do not introduce a container runtime just for Watchtower.

The service should:

- run as a dedicated least-privileged user if possible
- use a dedicated configuration directory
- use secure permissions
- restart automatically on failure
- have resource limits where appropriate
- not run as root unless absolutely necessary
- not require shell access
- not require privileged capabilities unless explicitly necessary

Watchtower should not listen on a public TCP port unless required.

If Telegram webhook is required, use the existing Nginx/TLS infrastructure to route the webhook securely.

============================================================
7. TELEGRAM BOT
============================================================

Create one CloudVault Telegram bot.

The Telegram bot token must be provided through the existing secret/environment mechanism.

Example:

TELEGRAM_BOT_TOKEN=<secret>

Do not hard-code this.

Do not commit it.

Do not expose it to frontend code.

Do not log it.

Prefer Telegram webhook architecture for production.

Conceptual flow:

Telegram
   |
   | HTTPS webhook
   v
Nginx
   |
   v
Watchtower
   |
   +-- authentication
   +-- authorization
   +-- command routing
   +-- notification handling
   +-- Prometheus integration

============================================================
8. TELEGRAM ACCOUNT LINKING
============================================================

Telegram is NOT the CloudVault authentication system.

Instead, it is linked to an existing CloudVault account.

Flow:

Authenticated CloudVault user
        |
        v
Settings
        |
        v
Connect Telegram
        |
        v
Generate short-lived one-time token
        |
        v
Telegram deep link
        |
        v
User opens CloudVault Telegram bot
        |
        v
/start <token>
        |
        v
Watchtower validates token
        |
        v
Telegram numeric user ID is linked
        |
        v
Connection confirmed

The linking token must:

- be cryptographically random
- expire quickly
- be single-use
- never contain a password
- not be logged
- preferably be stored hashed
- be invalidated after successful use
- be invalidated after expiration

Telegram numeric user ID must be the stable identity.

Do NOT rely on Telegram username.

Username may be stored as optional metadata.

Potential model:

CloudVault User
    |
    +-- telegram_user_id
    +-- telegram_username
    +-- telegram_connected_at

Enforce uniqueness according to the intended account model.

============================================================
9. TELEGRAM DISCONNECT
============================================================

The CloudVault web interface must provide:

Disconnect Telegram

Disconnecting should:

- invalidate the association
- invalidate active linking state
- stop notifications
- not delete the CloudVault user
- not delete CloudVault files
- not affect Nextcloud authentication

============================================================
10. TELEGRAM NOTIFICATION PREFERENCES
============================================================

Add notification preferences.

Possible events:

UPLOAD_COMPLETED
UPLOAD_FAILED
BACKUP_COMPLETED
BACKUP_FAILED
SECURITY_ALERT
HEALTH_ALERT
BACKGROUND_JOB_FAILED
STORAGE_WARNING
STORAGE_CRITICAL

Do not assume every event can be integrated immediately.

First inspect the existing CloudVault/Nextcloud event mechanisms.

Use the safest existing integration point.

The notification system must be centralized.

Do NOT add Telegram API calls directly to random scripts throughout the repository.

Preferred:

Existing event
      |
      v
Watchtower event/notification layer
      |
      v
Notification queue
      |
      v
Telegram

============================================================
11. TELEGRAM COMMANDS — PHASE 1
============================================================

Phase 1 commands are READ-ONLY.

Implement:

/start
/help
/status
/health
/metrics
/storage
/jobs
/alerts

Do NOT implement:

/shell
/exec
/restart
/shutdown
/delete
/run
/command

in phase 1.

============================================================
12. /STATUS
============================================================

Return a concise operational summary.

Example:

CloudVault Status

Overall: HEALTHY

Server
CPU: 24%
RAM: 61%
Disk: 72%

Services
Nginx: OK
PostgreSQL: OK
Redis: OK
ClamAV: OK

Monitoring
Prometheus: OK
Grafana: OK

Background jobs
Running: 2
Queued: 4
Failed: 0

Last backup:
SUCCESS
2026-08-27 03:00 UTC

The exact services must be based on the actual repository.

Do not hard-code services that do not exist.

============================================================
13. /HEALTH
============================================================

Return:

HEALTHY
DEGRADED
UNHEALTHY
UNKNOWN

Health must be based on multiple components.

Do not determine overall health from a single metric.

Example:

CloudVault Health

Overall: HEALTHY

Infrastructure
OK CPU
OK Memory
OK Disk
OK Network

Services
OK Nginx
OK PostgreSQL
OK Redis
OK ClamAV

Monitoring
OK Prometheus
OK Grafana

If a component cannot be checked:

UNKNOWN

If Prometheus is unavailable:

Monitoring metrics unavailable.

Do not crash.

============================================================
14. /METRICS
============================================================

Prometheus is the source of truth.

Watchtower must query Prometheus's HTTP API.

DO NOT query Grafana dashboards.

DO NOT scrape Grafana HTML.

DO NOT expose arbitrary PromQL execution to Telegram users.

Use predefined safe queries.

Possible metrics:

- CPU utilization
- memory utilization
- disk utilization
- network traffic
- system availability
- storage
- CloudVault-specific metrics if already available

If Prometheus is unavailable:

Return:

Monitoring unavailable

Do not crash.

============================================================
15. /STORAGE
============================================================

Return storage information based on existing CloudVault/system metrics.

Example:

Storage

Used: 742 GB
Available: 258 GB
Total: 1 TB
Usage: 74.2%

If storage growth information already exists, optionally show it.

Do not invent metrics.

============================================================
16. /JOBS
============================================================

Show background job information.

IMPORTANT:

Do not replace existing Nextcloud cron/background jobs.

First inspect how jobs currently work.

Watchtower should observe or integrate with existing jobs where possible.

Example:

Background Jobs

Running: 2
Queued: 4
Failed: 0

Show only safe operational information.

Do not expose sensitive job payloads.

============================================================
17. /ALERTS
============================================================

Show active/recent operational alerts.

Use Alertmanager where appropriate.

Do not create a second independent alerting engine if Prometheus/Alertmanager already handles the same problem.

============================================================
18. PROMETHEUS INTEGRATION
============================================================

Prometheus is the source of truth for metrics.

Watchtower should have a Prometheus client.

Example architecture:

Prometheus
    |
    +----> Grafana
    |
    +----> Watchtower

Watchtower should use predefined queries.

Examples:

CPU utilization
Memory utilization
Disk utilization
Network traffic
Node availability

Do not allow arbitrary user-provided PromQL.

Do not expose Prometheus directly to the internet.

Use internal/private networking.

============================================================
19. GRAFANA INTEGRATION
============================================================

Grafana remains the visualization system.

Watchtower may include configurable Grafana URLs in Telegram messages.

Example:

[View Grafana]

The URL must come from configuration.

Do not hard-code production URLs.

Do not make Watchtower dependent on Grafana for metrics.

Metrics:

Prometheus

Visualization:

Grafana

Telegram:

Watchtower

============================================================
20. ALERTMANAGER INTEGRATION
============================================================

Existing Prometheus/Alertmanager infrastructure must remain intact.

If Alertmanager exists:

Prometheus
    |
    v
Alertmanager
    |
    v
Watchtower
    |
    v
Telegram

Watchtower should receive alert events through a secure integration.

Do not bypass Alertmanager for alerts that already belong there.

Possible alert classes:

- disk critical
- node unavailable
- service unavailable
- high memory
- backup failure
- storage critical
- SSL expiry warning
- CloudVault health failure

Use the existing project's alert definitions where possible.

Do not duplicate alert rules unnecessarily.

============================================================
21. ALERT EXAMPLE
============================================================

Telegram:

CLOUDVAULT ALERT

Status: DEGRADED

Disk usage: 92%

Server:
cloudvault

Used:
920 GB / 1 TB

Available:
80 GB

Threshold:
90%

[View Grafana]

The actual content should be generated dynamically.

============================================================
22. UPLOAD NOTIFICATION
============================================================

The original desired feature is:

User starts a large upload.
User can leave the browser.
When the upload finishes, Telegram informs them.

IMPORTANT:

Do NOT create a parallel upload system.

Do NOT intercept or replace Nextcloud's upload mechanism.

First inspect Nextcloud's existing event/hook capabilities.

If a reliable event exists:

Nextcloud
    |
    v
Existing event mechanism
    |
    v
Watchtower integration
    |
    v
Notification queue
    |
    v
Telegram

Example:

Upload completed

File:
backup-server.tar.zst

Size:
8.42 GB

Duration:
4m 32s

Integrity:
Verified

Antivirus:
Clean

The exact fields depend on what information is safely available.

If reliable upload completion events cannot be integrated without modifying Nextcloud core, do NOT hack around it.

Document the limitation and propose an officially supported integration mechanism.

============================================================
23. BACKGROUND NOTIFICATION QUEUE
============================================================

Use the existing Redis infrastructure if suitable.

Do not introduce a second queue system without a strong reason.

The notification queue is separate conceptually from Nextcloud's own job system.

Example:

CloudVault Event
      |
      v
Notification Queue
      |
      v
Watchtower Worker
      |
      v
Telegram API

Statuses:

QUEUED
PROCESSING
SENT
FAILED
RETRYING

Notifications must not block normal CloudVault operations.

If Telegram is down:

Upload remains successful.

Backup remains successful.

Healthcheck remains successful.

Notification can be retried independently.

============================================================
24. RETRY POLICY
============================================================

Telegram/API failures should use controlled retries.

Requirements:

- limited retry count
- exponential backoff where appropriate
- no infinite retry loops
- failed notifications must be observable
- do not overload Telegram API

Do not retry permanent failures indefinitely.

============================================================
25. HEALTH INDEPENDENCE
============================================================

The system must be fault tolerant.

Case:

Watchtower down

Result:

Nextcloud: continues
Nginx: continues
PostgreSQL: continues
Redis: continues
Prometheus: continues
Grafana: continues

Only Telegram/Watchtower functionality is affected.

Case:

Telegram unavailable

Result:

CloudVault continues normally.

Case:

Prometheus unavailable

Result:

CloudVault continues normally.
Telegram reports monitoring unavailable.

Case:

Grafana unavailable

Result:

Prometheus continues.
Watchtower can still query Prometheus.
Telegram health/metrics continue if Prometheus is available.

============================================================
26. SECURITY
============================================================

Watchtower handles sensitive operational information.

Requirements:

- least privilege
- no root unless required
- secure file permissions
- secure secret storage
- no secret logging
- no arbitrary command execution
- Telegram authorization
- rate limiting
- webhook verification
- secure linking tokens
- audit security-sensitive operations
- no public Prometheus
- no public PostgreSQL
- no public Redis
- no arbitrary PromQL
- no user-controlled shell commands

Telegram identity:

Use Telegram numeric user ID.

Do not use username as identity.

CloudVault identity:

Use existing CloudVault authentication/user model.

Telegram is an integration channel, not the authentication authority.

============================================================
27. ADMIN INFORMATION BOUNDARY
============================================================

Separate user notifications from infrastructure administration.

USER-SCOPE:

- upload completed
- upload failed
- personal backup events if applicable
- personal notification settings

ADMIN/INFRASTRUCTURE-SCOPE:

- CPU
- memory
- disk
- services
- Prometheus
- Alertmanager
- backup infrastructure
- server health
- infrastructure alerts

A normal CloudVault user must not automatically receive infrastructure information.

Use existing CloudVault role/admin concepts.

Do not invent a parallel permission system if the existing application already has one.

============================================================
28. WATCHTOWER OBSERVABILITY
============================================================

Watchtower itself should be observable.

If compatible with the existing Prometheus setup, expose metrics such as:

watchtower_notifications_total
watchtower_notification_failures_total
watchtower_webhook_requests_total
watchtower_command_requests_total
watchtower_notification_queue_depth
watchtower_notification_processing_seconds

Avoid high-cardinality labels.

Never use:

- filenames
- Telegram IDs
- user IDs
- IP addresses
- arbitrary message contents

as Prometheus labels.

============================================================
29. LOGGING
============================================================

Logs must be operationally useful.

Include:

- timestamp
- severity
- component
- event
- success/failure
- safe identifiers

Do NOT log:

- Telegram bot token
- linking token
- passwords
- authentication secrets
- full Telegram payloads if they contain sensitive information
- private file contents

============================================================
30. DATABASE
============================================================

Inspect existing database architecture first.

If a database is needed for Telegram linking/preferences:

Use the existing database and migration mechanism.

Potential conceptual entities:

telegram_connection
telegram_link_token
notification_preference

Do not create these exact schemas blindly.

Adapt to the existing architecture.

Potential connection data:

- id
- user_id
- telegram_user_id
- telegram_username
- connected_at
- last_seen_at

Potential linking token data:

- id
- user_id
- token_hash
- expires_at
- used_at
- created_at

Use proper uniqueness constraints.

============================================================
31. WEB UI
============================================================

Add Telegram configuration to the existing settings UI.

Do not create a separate frontend application.

Concept:

Settings
  |
  +-- Notifications
       |
       +-- Telegram

Disconnected:

Telegram

Status:
Not connected

[Connect Telegram]

Connected:

Telegram

Status:
Connected

@username

Notifications:

[x] Upload completed
[x] Upload failed
[x] Backup completed
[x] Backup failed
[x] Health alerts
[x] Security alerts
[x] Background job failures

[Send Test Notification]

[Disconnect Telegram]

Use the existing UI conventions.

============================================================
32. TELEGRAM CONNECT FLOW
============================================================

Preferred UX:

CloudVault web:

Connect Telegram

    |
    v

Generate one-time token

    |
    v

Display:
Open Telegram

or QR/deep link

    |
    v

Telegram:

/start <token>

    |
    v

CloudVault validates

    |
    v

Telegram:

CloudVault account connected successfully.

The web UI should update connection state.

Do not require users to type passwords into Telegram.

============================================================
33. TESTING
============================================================

Add tests according to existing repository conventions.

At minimum test:

- token generation
- token expiration
- token single-use
- Telegram account linking
- duplicate Telegram account handling
- disconnect
- authorization
- notification preferences
- Telegram API failure
- notification retry
- Prometheus unavailable
- /status
- /health
- /metrics
- /storage
- /jobs
- /alerts
- Alertmanager payload handling
- no secrets in logs

Mock:

- Telegram API
- Prometheus API
- Alertmanager webhook

Do not require production services for unit tests.

============================================================
34. DEPLOYMENT
============================================================

Update deployment documentation and scripts only where necessary.

If Watchtower is a systemd service, document:

- service installation
- environment/secrets
- permissions
- dependencies
- restart behavior
- logging
- webhook routing
- health verification

Do not modify unrelated deployment behavior.

============================================================
35. ROLLBACK
============================================================

The implementation must be removable without destroying CloudVault.

Removing Watchtower must NOT:

- delete Nextcloud data
- delete PostgreSQL data
- delete Redis data
- disable Prometheus
- disable Grafana
- disable Alertmanager
- break Nginx
- break Nextcloud
- remove backups

Document rollback steps.

============================================================
36. IMPLEMENTATION PHASES
============================================================

Do not implement everything in one giant change.

PHASE 0 — DISCOVERY

Inspect repository.

No code modifications.

Produce architecture report.

PHASE 1 — WATCHTOWER FOUNDATION

Create minimal Watchtower service.

Requirements:

- systemd integration
- configuration
- logging
- graceful shutdown
- health endpoint/internal health mechanism if appropriate
- least privilege

No Telegram yet.

PHASE 2 — PROMETHEUS INTEGRATION

Add:

- Prometheus client
- predefined queries
- health aggregation
- /status
- /health
- /metrics
- /storage

Verify that existing Prometheus/Grafana continue working.

PHASE 3 — TELEGRAM FOUNDATION

Add:

- bot
- webhook
- secure token handling
- /start
- /help

No privileged commands.

PHASE 4 — TELEGRAM LINKING

Add:

- web UI
- one-time linking token
- Telegram numeric ID association
- disconnect
- notification preferences

PHASE 5 — TELEGRAM STATUS COMMANDS

Add:

/status
/health
/metrics
/storage
/jobs
/alerts

PHASE 6 — ALERTMANAGER

Integrate existing Alertmanager alerts.

Send operational alerts to authorized Telegram users/admins.

PHASE 7 — EVENT NOTIFICATIONS

Integrate safe existing CloudVault/Nextcloud events.

Start with:

- backup completed
- backup failed
- health alerts

Then investigate upload-completed events.

Do NOT modify Nextcloud core.

PHASE 8 — NOTIFICATION QUEUE

Add Redis-backed notification queue if needed.

Implement:

- retries
- failure tracking
- non-blocking notifications

PHASE 9 — OBSERVABILITY

Expose Watchtower metrics to existing Prometheus.

Add Grafana dashboard only if it fits the existing dashboard architecture.

============================================================
37. ACCEPTANCE CRITERIA
============================================================

The feature is considered successful only if:

1. Existing CloudVault functionality remains intact.
2. Nextcloud remains the application/file-storage layer.
3. No Nextcloud core modifications are required.
4. Existing backup mechanisms continue working.
5. Existing cron/systemd timers continue working.
6. Prometheus continues working.
7. Grafana continues working.
8. Alertmanager continues working.
9. Watchtower can operate independently.
10. Telegram can be disconnected without affecting CloudVault.
11. Telegram bot token is never exposed.
12. Telegram account linking is secure.
13. Unauthorized Telegram users cannot access CloudVault information.
14. /status works.
15. /health works.
16. /metrics works.
17. /storage works.
18. /jobs works where job data is available.
19. /alerts works where Alertmanager is available.
20. Telegram failures do not break CloudVault.
21. Prometheus failures do not break CloudVault.
22. Watchtower failures do not break CloudVault.
23. Watchtower itself is observable.
24. Documentation is updated.
25. Rollback is documented.
26. Tests cover security-sensitive behavior.

============================================================
38. IMPORTANT IMPLEMENTATION PRINCIPLE
============================================================

Prefer integration over replacement.

Prefer existing mechanisms over new mechanisms.

Prefer official APIs/events over filesystem scraping.

Prefer Prometheus API over Grafana scraping.

Prefer existing Redis over introducing another queue.

Prefer existing systemd over introducing containers.

Prefer existing authentication/roles over creating a parallel authentication system.

Prefer existing Nextcloud events/hooks over modifying Nextcloud core.

Prefer graceful degradation over hard dependencies.

Prefer small incremental changes over large rewrites.

============================================================
39. FINAL INSTRUCTION TO THE AGENT
============================================================

START WITH DISCOVERY.

Do not modify the repository until you have:

1. inspected the actual architecture,
2. identified safe integration points,
3. identified components that must remain untouched,
4. produced a concrete implementation plan,
5. explained any conflicts between this specification and the current repository.

If any requirement cannot be implemented safely without modifying existing CloudVault architecture, do not improvise.

Stop and explain:

- what prevents the implementation,
- why it conflicts with the current architecture,
- what alternatives exist,
- which alternative is least invasive.

The goal is NOT to maximize the number of new features.

The goal is to add CloudVault Watchtower while preserving the reliability, security, simplicity, and architecture of the existing CloudVault project.

