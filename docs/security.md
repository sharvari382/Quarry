# Security

What is protected, how, and which test proves it. Tests live in `backend/tests/security/`
and `backend/tests/unit/test_security_primitives.py`.

## Authentication and sessions

| Control | Implementation | Test |
|---|---|---|
| Password storage | Argon2id (t=3, m=19 MiB), automatic rehash on login when parameters change | `test_argon2_hash_and_verify` |
| Password policy | 10 to 128 chars, letter + number, common-password deny list, must not contain email name | `test_password_policy` |
| Session tokens never touch JavaScript | Access JWT (15 min) and refresh token (7 days) in `HttpOnly`, `Secure`, `SameSite=Strict` cookies; refresh cookie scoped to `/api/auth` | `test_register_sets_secure_session_cookies` |
| JWT hardening | HS256 pinned (no `alg` negotiation), `exp`/`sub` required, token type checked | `test_alg_none_and_wrong_type_rejected`, `test_expired_token_rejected` |
| Refresh rotation + theft detection | Each refresh issues a new token; replaying an old one revokes the whole token family | `test_refresh_token_reuse_revokes_family` |
| Logout | Revokes the refresh token server side and clears cookies; "sign out of all devices" revokes every token | `test_logout_revokes_refresh_token` |
| Password change | Revokes all other sessions | `test_change_password_signs_out_other_sessions` |
| User enumeration | Same message and same Argon2 work for unknown email and wrong password | `test_wrong_password_is_generic` |
| Brute force | Per-account lockout (5 failures / 15 min), per-IP login and registration limits in the app, plus nginx limits | `test_login_lockout_after_repeated_failures`, `test_registration_is_rate_limited_per_ip` |
| CSRF | `SameSite=Strict` plus double-submit token header on every state-changing request; token stays stable across refreshes so multi-tab use works | `test_csrf_required_for_state_changes`, `test_refresh_keeps_csrf_token_stable_for_other_tabs` |

## Authorization (multi-tenant isolation)

* Every user-owned row has `owner_id`; every lookup filters on it. Foreign ids return **404**, not 403,
  so ids cannot be probed.
* SQL runs on a connection that contains only the caller's tables. Naming another user's table fails
  with "does not exist" because it does not exist in that sandbox.

Tests: `test_users_cannot_see_each_others_data`, `test_sql_cannot_reach_other_users_tables`.

## Data protection

* **At rest**: uploaded files are converted to Parquet and encrypted with Fernet (AES-128-CBC +
  HMAC-SHA256) before they reach disk. Keys come from `DATA_ENCRYPTION_KEYS`; MultiFernet supports
  rotation (prepend a new key, old data stays readable, `crypto.rotate()` re-encrypts).
  Tests: `test_data_is_encrypted_on_disk`, `test_encryption_roundtrip_and_integrity`, `test_key_rotation`.
* **In transit**: terminate TLS in front of nginx (cloud load balancer, Caddy, or certbot), then
  uncomment the HSTS header in `nginx/nginx.conf`. `COOKIE_SECURE=true` is enforced in production.
* **Refresh tokens** are stored only as SHA-256 hashes.
* **Logs** are structured JSON with request ids; keys like `password`, `token`, `cookie` are redacted.
* **Postgres and Redis** sit on an internal Docker network with no published ports and no internet.

## LLM-specific risks

| Risk | Mitigation |
|---|---|
| Model writes destructive or exfiltrating SQL | 3-layer sandbox (see architecture). `test_unsafe_sql_from_model_is_blocked`, `test_blocks_unsafe_queries` (17 cases) |
| Prompt injection inside CSV cells | Tools are read-only, so obeying injected text cannot change data; the system prompt marks cell values as untrusted. `test_prompt_injection_in_data_cannot_escalate` |
| Runaway queries (cross joins) | 10 s watchdog interrupts DuckDB; 512 MB memory cap; 5,000-row result cap. `test_runaway_query_is_interrupted` |
| Runaway agent loops | Max 6 tool steps per question. `test_step_limit_terminates` |
| Cost abuse | Per-user chat rate limit and daily LLM call quota. `test_chat_rate_limit` |
| Model output rendered as HTML (XSS) | Markdown rendered by react-markdown with raw HTML disabled; strict CSP (`script-src 'self'`). Frontend test checks a `<script>` in an answer is not rendered. |
| Executing model-written Python | Never done. Pandas code is display-only. |

## Upload abuse

Size cap streamed (stops reading past the limit), binary sniffing, row/column caps, per-user dataset
quota and upload rate, filename path stripping, spreadsheet formula escaping on CSV export
(`=`, `+`, `-`, `@`). Tests: `test_oversized_upload_rejected`, `test_dataset_quota`,
`test_path_traversal_filename_is_neutralised`, `test_csv_formula_injection_escaped`.

## HTTP hardening

CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control:
no-store` on API responses, `server_tokens off`. OpenAPI docs disabled in production. Errors never
include stack traces (`test_errors_do_not_leak_internals`). Containers run as non-root with a
read-only filesystem, `no-new-privileges` and all Linux capabilities dropped.

## Not in scope (would be next)

Email verification and password reset (needs an email provider), MFA, SSO/SAML, per-tenant KMS
keys, malware scanning of uploads, a WAF in front of nginx, secrets from a vault instead of env.
