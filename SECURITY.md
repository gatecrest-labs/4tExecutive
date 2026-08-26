# Security

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue.
Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
for this repository (Security tab → "Report a vulnerability"), or contact the
maintainer directly. <!-- TODO: add a contact email or security-advisory link here before making the repo public -->

## Threat model

4tExecutive is designed to run on an internal network, aggregating
read-only executive metrics from operational tools it never mutates. Its
network posture is deliberately narrow: the collector only needs outbound
HTTPS to each configured source's external-API port. It needs no shared
filesystem access, no SSH, and no elevated privileges.

## Secrets and config

- `SECRET_KEY` (Flask session signing) is required outside test mode; the
  app refuses to start if it's unset or still the `.env.example` placeholder.
- Per-source bearer tokens are stored in `config/sources.json`, encrypted at
  rest (`app/crypto.py`, Fernet/AES-128-CBC+HMAC, key derived from
  `SECRET_KEY`) and decrypted only in-process when the collector builds the
  outbound `Authorization` header. The original design spec
  (`docs/superpowers/specs/2026-08-24-4texecutive-design.md`) called for
  storing a token *hash* instead — that doesn't actually work here, since
  4tExecutive is the one presenting the token to each source's API on every
  poll and needs the plaintext back, not just a comparison hash. Encryption
  is the correct fit for a secret the app must recover, and is what's
  implemented.
- User passwords are bcrypt-hashed in `config/users.json` (a hash is
  correct there — the app only ever needs to verify a login, never recover
  the password).
- `config/*.json` (outside `config/examples/`), `.env`, and `certs/` are all
  gitignored — never commit real values from these paths.
- Admin routes reject any source `base_url` that isn't `https://`, so bearer
  tokens are never sent in cleartext.
- All state-changing routes (login, Admin source CRUD) require a CSRF token
  (`flask-wtf`'s `CSRFProtect`, wired in `app/__init__.py`); every form in
  `app/templates/` includes one, and a `csrf-token` `<meta>` tag in
  `base.html` is available for any future JS-driven POST (e.g. the
  Dashboard edit-mode save, once that UI exists — see
  `app/routes/dashboard_routes.py`).
- The login route is rate-limited (`flask-limiter`, 10 attempts/minute per
  IP, `app/routes/auth_routes.py`) to slow down password brute-forcing.
  Storage is in-memory and per-process — matches the Dockerfile's single
  gunicorn worker; scaling to multiple workers/instances needs a shared
  backend (e.g. Redis) or each process enforces its own independent limit.

## Known gaps / hardening opportunities

- No audit log of admin actions (source add/delete/refresh, user
  create/delete).
- No account lockout or backoff tied to a specific *username* — the login
  rate limit is per source IP only, so a distributed attempt across many
  IPs isn't slowed down by it.

## Supported versions

This project does not yet have tagged releases or a versioning policy;
security fixes land on `main`.
