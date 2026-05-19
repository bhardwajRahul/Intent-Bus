# Changelog

## [7.6] - 2026-05-17

### Security
- **Queue Exhaustion Armor:** Publisher quota limits now evaluate both `open` and `claimed` states to prevent malicious workers from hoarding jobs and bypassing limits.
- **Log Injection Prevention:** Strict Regex sanitization (`^[a-zA-Z0-9_.:-]{1,128}$`) applied to `X-Request-ID` headers to prevent SIEM spoofing.
- **Default Secret Rejection:** Unconditional rejection of `dev_secret` in production (debug bypass fixed).
- **Admin Auth Hardened:** Fail-closed architecture with no fallback to standard `API_KEY`.
- **Worker Security:** Symlink detection and strict file permissions (mode 600) enforced in edge workers.

### Added
- **Structured Observability:** Context-aware JSON logging with strict telemetry whitelists and defensive serialization fallbacks.
- **Request Tracing:** End-to-end trace IDs (`X-Request-ID`), remote IP capture, and `duration_ms` performance tracking.
- **Cleanup Telemetry:** The garbage collector now emits explicit `cleanup_complete` JSON events with precise row deletion stats.
- **Prometheus Metrics:** Added `/metrics` endpoint for intent counts and system health.
- **CI/CD & Testing:** Added a GitHub Actions matrix pipeline and a robust `pytest` suite covering replay attacks, dead-letters, and capability routing.

### Changed
- **Queue Elasticity:** Increased `MAX_OPEN_INTENTS_PER_KEY` from 100 to 2,000 to act as a better shock absorber for high-throughput publishers during worker downtime.

### Fixed
- **SQLite Thrashing:** Added an explicit 60-second error cooldown (`last_cleanup_error_time`) so the traffic-triggered (lazy) garbage collector doesn't bottleneck the main thread if the database is locked.
- **Silent Debounce Bug:** The cleanup cycle now accurately requires a `True` success signal before advancing its 6-hour timer.
- **Privilege Escalation:** Closed access vulnerabilities in admin routes.
- **Syntax:** Fixed a trailing tuple formatting bug in the 429 limit-exceeded response.

### Contributors
- **Zan (@Ghost-Frame)** — Security auditing + hardening patches
- **Dhanush (@dsecurity49)** — Core architecture, v7.6 protocol updates, and observability
