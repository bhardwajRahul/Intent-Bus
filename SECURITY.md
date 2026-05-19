# Security Policy

## Supported Versions

| Component | Version | Status |
| :--- | :--- | :--- |
| Intent Bus Server | v7.6+ | ✅ Supported |
| Python SDK (`intent-bus`) | v2.0.0+ | ✅ Supported |

---

## Security Model Overview

Intent Bus uses a **Dual-Auth Model** to balance simplicity and security.

### 1. Standard Authentication

Requires:

```http
X-API-KEY: <key>
```

Used over HTTPS, this protects against passive network interception.

#### Limitation

Standard authentication does **not** provide replay protection. Captured requests may be replayed by an attacker capable of intercepting traffic.

---

### 2. Strict Authentication (HMAC)

Each request includes:

- Timestamp
- Nonce
- HMAC-SHA256 signature

Provides:

- Replay protection
- Payload integrity
- Request authenticity

#### Cryptographic Guarantees

- **Constant-Time Verification:** HMAC signatures are verified using constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.
- **Replay Window:** Strict authentication enforces a bounded timestamp validity window to prevent delayed replay attacks. The enforced clock skew tolerance is **±300 seconds**.
- **Nonce Storage:** Nonces are stored persistently in the SQLite `request_nonces` table (scoped per API key) to prevent reuse within the validity window. Expired nonces are automatically purged during the server's scheduled cleanup passes.

#### Signature Format

Strict Auth signs a canonical request representation. The HMAC-SHA256 signature is computed using the API key as the secret over the following newline-delimited (`\n`) string:

```text
HTTP_METHOD
CANONICAL_REQUEST_PATH
TIMESTAMP
NONCE
REQUEST_BODY
```
*Note: `CANONICAL_REQUEST_PATH` includes sorted query parameters. `REQUEST_BODY` uses the exact bytes transmitted in the request body (empty bodies serialize as an empty string).*

#### Recommendation

Use Strict Auth in all production environments.
Enable globally with:

```bash
BUS_REQUIRE_SIGNATURES=true
```

---

## Server Operations

### Admin & Dashboard Access

Admin endpoints (`/admin/*`) and the dashboard use a separate privileged authentication layer.
Supported methods:

1. Header authentication:

```http
X-Admin-Token: <BUS_ADMIN_SECRET>
```

2. HTTP Basic authentication:

```text
Username: admin
Password: <DASHBOARD_PASSWORD>
```

---

### Reverse Proxy & HTTPS

The server can strictly enforce HTTPS in production:

```bash
BUS_ENFORCE_HTTPS=true
```

If deploying behind Nginx, Apache, Traefik, or another reverse proxy:

- Ensure `X-Forwarded-Proto` is forwarded correctly
- Set `BUS_TRUST_PROXY=true` to enable Werkzeug `ProxyFix` support.

#### Security Headers

The Intent Bus server automatically sets the following baseline headers on all HTTP responses (including errors):
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Cache-Control: no-store`

When deploying behind a reverse proxy in production, you SHOULD additionally configure:
- `Strict-Transport-Security` (HSTS)

---

## Threat Model (High-Level)

### Security Assumptions
Intent Bus assumes:
- Trusted server host environment
- Correct TLS termination at the proxy or network edge
- Secure storage of API credentials by clients
- Reasonably synchronized system clocks across clients and servers when using Strict Auth

### Mitigated

- Replay attacks (Strict Auth only)
- Concurrent claim race conditions (SQLite transactional locking)
- Infinite retry loops (configurable max attempts)
- Cross-tenant access (API key + namespace isolation)
- Basic denial-of-service abuse (rate limits and payload caps)
- Log Injection and SIEM spoofing (strict X-Request-ID regex validation)

### Not Mitigated

- Arbitrary code execution by workers (workers act as un-sandboxed execution agents by design; host isolation is the user's responsibility)
- Compromised API keys
- Host/VPS compromise
- Side-channel attacks

---

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Report privately via:

- **Email:** dsecurity49@gmail.com

---

### Include in Your Report

- Clear description of the issue
- Step-by-step reproduction
- Proof of concept (if available)
- Impact assessment

---

### Response Policy

- **Acknowledgement:** within 48 hours
- **Initial triage:** within 3–5 days
- **Fix timeline:** depends on severity

Valid reports may receive:

- Credit in release notes (optional)
- Fast-tracked fixes

---

## Security Best Practices

When using Intent Bus:

- **Key Entropy:** API keys should contain at least 128 bits of entropy and be generated using a cryptographically secure random source.
- NEVER expose API keys in client-side code
- ALWAYS use HTTPS
- USE Strict Auth in production
- ROTATE API keys periodically
- AVOID storing sensitive data in payloads

---

## Known Limitations

### 1. Payload Exposure

Payloads are **not encrypted at rest** within the SQLite database.

> ⚠️ **CRITICAL: Public intents (`visibility="public"`) may be claimed by any authenticated worker in the same namespace. They should be treated as non-confidential broadcast work items.**

#### Do NOT include:

- API keys
- Passwords
- PII
- Secrets of any kind

---

### 2. Data Retention

- Intents are ephemeral.
- Open intents expire via TTL (default: 24 hours).
- Fulfilled intents and dead letters are **eligible for deletion** after 7 days during scheduled cleanup passes.
- KV store values expire at their configured TTL.

---

### 3. Hardcoded Limits (Anti-DoS)

The following limits are enforced to protect the single-file SQLite architecture:

| Limit | Value |
| --- | --- |
| Payload Size | 8KB maximum |
| Rate Limit | 60 requests / minute (Enforced per API key) |
| Open Intent Cap | 2000 open intents per publisher key |

*Note: Admin keys globally bypass rate limits and open-intent caps across all endpoints.*

---

### 4. Concurrency & Horizontal Scaling

SQLite is operated in **WAL (Write-Ahead Logging) mode** for improved concurrent read/write behavior. However, it remains a single-writer model.
Under high load:

- Increased latency may occur
- Requests may temporarily fail with:

```http
503 Service Unavailable
```

Clients SHOULD implement exponential backoff with jitter. For workloads exceeding thousands of jobs per minute, users should implement a federation pattern or migrate the `get_db()` implementation to PostgreSQL.

---

### 5. Replay Protection Scope

Replay protection is enforced **only** when using Strict Auth.

Standard authentication is replayable by design.

---

## Out of Scope

The following are NOT considered vulnerabilities:

- Denial-of-service using valid requests
- Worker-side execution bugs
- Unsafe user code (e.g. `eval`)
- API key misuse by authorized users
- Expected retry behavior
- SQLite `database is locked` errors under heavy concurrency

---

## Responsible Disclosure

### 2026-05-17: Privilege Escalation and Default Credential Fixes
- **Default Secret in Debug Mode:** Previously, the server allowed the default `dev_secret` API key if the application was started in debug mode. This was patched to unconditionally reject the default secret in all environments to prevent accidental exposure.
- **Admin Token Fallback:** Previously, if `BUS_ADMIN_SECRET` was left unset, the server fell back to accepting the standard `BUS_SECRET` as an admin token. This was patched to fail closed. If an admin token is not explicitly configured, header-based admin authentication is disabled to prevent privilege escalation from leaked tester keys.

---

## Disclosure Policy

- Fixes are released before public disclosure
- Critical patches may be shipped without advance notice
- Changelogs include relevant security notes when applicable

---

## Contact

For security concerns:

- **Email:** dsecurity49@gmail.com
- **Discord:** https://discord.gg/bzAneAQzGX

For non-sensitive communication, DM `dsecurity`.

---

## License

MIT
