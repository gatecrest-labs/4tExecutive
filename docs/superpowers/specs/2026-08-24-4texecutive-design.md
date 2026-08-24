# 4tExecutive — Executive Dashboard — Design

## Purpose

A new web application, `4tExecutive`, gives an executive audience a single
place to review metrics pulled from the organization's existing
FortiGate-related tools — `4thealth` / `4thealth-plus`, `4tlog`, and
(phase 2) `4tAnalyst` — without those executives needing access to the
underlying operational tools themselves.

It follows the architectural and security conventions already established
in `4thealth`/`4tlog`: Flask, JSON-file config store with `*.example.json`
templates, bcrypt + `groups.json` local auth, APScheduler background jobs,
Docker/Ansible deployment. It is a **new app built to match those
conventions**, not a fork — 4thealth/4thealth-plus carry firewall-specific
machinery (zone policy DB, device review, backup engine, rule hygiene
engine, FortiManager client) that has nothing to do with an aggregation
dashboard, and stripping that out of a clone is more work and more risk
than starting clean.

## Scope

**In scope (this spec):**
- 4tExecutive app: Dashboard tab (personalized) + Admin tab (restricted)
- Source integration with 4thealth / 4thealth-plus (already has an
  external API blueprint to extend) and 4tlog (needs one added)
- Config file relocation to a dedicated `config/` folder
- Local scheduled collector + SQLite cache, no live source calls on page
  render

**Out of scope / deferred:**
- 4tAnalyst integration — it's a set of MCP servers (`fortimanager_mcp`,
  `zone_mcp`, `standards_mcp`, `feedback_mcp`, `fwanalyst_server`), not a
  Flask app with a REST API, so it needs a different bridge (likely a
  small adapter process, not a REST poll). Tracked as a follow-up spec.
- SSO/external identity provider integration — v1 uses local bcrypt +
  `groups.json` auth, matching 4thealth/4tlog. Flagged as a future
  swap-in if the org later wants centralized identity.
- Cross-instance rollup/comparison UI (e.g. one widget aggregating
  multiple 4thealth sites into a single number) — the source registry
  supports multiple named instances per system type from day one, but
  building comparison/rollup widgets is left for a later iteration once
  it's clear which comparisons executives actually want.

## Architecture

Three logical pieces inside one Flask app (`app/`, blueprints under
`app/routes/`, matching 4thealth's layout):

1. **Source registry** (`config/sources.json`) — admin-managed list of
   named source instances:
   ```json
   {
     "sources": [
       {
         "id": "4thealth-east",
         "system": "4thealth",
         "name": "East DC",
         "base_url": "https://4thealth-east.internal:8100",
         "token_hash": "...",
         "poll_interval_minutes": 15,
         "enabled": true
       }
     ]
   }
   ```
   Supports multiple instances per system type (e.g. several 4thealth
   deployments per site/business unit) without a schema change, per the
   "assume separate servers/containers, or a single server" requirement.

2. **Collector** — an APScheduler job (same pattern as 4thealth's
   scheduler modules) that, per configured source and its
   `poll_interval_minutes`, calls that source's
   `/external/api/executive/summary` endpoint over HTTPS with the stored
   bearer token, and writes the result into a local SQLite cache
   (`metrics.db`, same shape/conventions as 4thealth's `host_metrics.db`).
   A manual "Refresh now" action in Admin triggers an out-of-band poll,
   mirroring 4thealth's `poll_now()` pattern in `faz_health_cache.py`.

3. **Web app** — reads only from `metrics.db`; never calls a source
   synchronously during a page render. Two tabs:
   - **Dashboard** — personalized per user (see below)
   - **Admin** — source registry CRUD, users/groups, refresh intervals,
     token management, widget catalog config. Gated by `groups.json`
     `allowed_tabs` containing `"admin"`, the same mechanism 4thealth
     already uses to gate tabs like `rule_hygiene`.

### Source-side changes required

- **4thealth / 4thealth-plus**: add new routes to the existing
  `app/routes/external_api_routes.py` blueprint (already bearer-token
  gated, already toggleable from Admin → External API):
  `GET /external/api/executive/summary` returning hygiene score, device
  version compliance %, pending config-diff count, last backup status,
  firewall online/offline counts.
- **4tlog**: has no external API blueprint today (only internal
  `faz_health_cache.py` / `faz_client.py`). Add a new
  `app/routes/external_api_routes.py` blueprint following 4thealth's
  exact pattern (bearer token via `api_tokens.py`-equivalent, feature
  flag in Admin) exposing `GET /external/api/executive/summary` with
  FortiAnalyzer CPU/mem health per target and log volume trend.
- Tokens issued by each source are scoped: an executive-API token can
  only call `/external/api/executive/*`, not e.g. 4thealth's existing
  `/external/api/zone/*` endpoints used by FW-Analyst. This is a new
  `scope` field on the token record, checked in each blueprint's `_gate()`.

## Config file layout

All configuration — currently scattered loose in 4thealth's repo root as
paired `x.json` / `x.example.json` files — moves under one `config/`
directory:

```
config/
  examples/                  # tracked in git — templates
    users.example.json
    groups.example.json
    sources.example.json
    app_settings.example.json
    smtp_config.example.json
  users.json                 # gitignored, real values
  groups.json
  sources.json
  app_settings.json
  smtp_config.json
  certs/
metrics.db                    # data, not config — stays at repo root
```

- `app/config_paths.py` defines `CONFIG_DIR = Path(__file__).parent.parent
  / "config"`; every module resolves config paths through this constant
  instead of ad hoc `Path(__file__).parent.parent / "x.json"` (the
  pattern 4thealth currently repeats per-module).
- `docker-compose.yml` mounts a single `./config:/app/config:rw` volume
  instead of one bind mount per file — simpler compose file, and it's
  the natural boundary for tighter filesystem permissions (`chmod 700
  config/`) since every secret (tokens, SMTP creds, bcrypt hashes) now
  lives in one place.
- A first-run bootstrap step copies any missing `config/examples/*.example.*`
  to its real counterpart in `config/`, centralizing what 4thealth
  currently expects a human to do manually per file.
- `.gitignore` excludes `config/*.json` and `config/certs/` but not
  `config/examples/`.

## Security

- **Per-source bearer tokens**, hashed (SHA-256, matching 4thealth's
  `api_tokens.py`) in `config/sources.json`; plaintext shown once at
  creation time in Admin, never stored or logged.
- **Token scoping**: executive-API tokens are restricted to
  `/external/api/executive/*` on the source side (see above) — a
  compromised 4tExecutive token cannot be used to query e.g. zone policy
  data on 4thealth.
- **Outbound TLS verified**: the collector validates each source's
  certificate against `config/certs/` (read-only mount, matching
  4thealth's `certs:ro` convention); no unverified-context HTTPS calls
  except the container's own loopback healthcheck.
- **Local auth**: bcrypt-hashed passwords in `config/users.json`;
  `config/groups.json` gates both which tabs a user sees (`dashboard`,
  `admin`) and, in v1, treats `admin` as a single all-or-nothing
  permission (matching 4thealth's current granularity — splitting Admin
  into finer sub-permissions is a natural v2 if needed).
- **Secrets never committed**: everything under `config/*.json` (outside
  `examples/`) and `.env` is gitignored, following 4thealth's existing
  convention.
- **Network posture**: the collector only needs outbound HTTPS to each
  source's external-API port — no shared filesystem access, no SSH, no
  elevated privileges — so 4tExecutive can run in a more locked-down
  network zone than the operational tools it aggregates, consistent with
  it being an executive-facing, higher-visibility, lower-privilege
  surface.

## Dashboard personalization & widget catalog

**Model: predefined widget catalog** (not a generic metric/query
builder) — safer, simpler to build, and sufficient for the known metric
set. A widget instance is:

```json
{
  "type": "4thealth.hygiene_score",
  "source_instance": "4thealth-east",
  "title": "East DC — Hygiene Score",
  "size": "1x1",
  "date_range": "30d"
}
```

Sizes: `1x1`, `2x1`, `2x2` on a grid layout. A user's arrangement is
stored per-username (either `config`-adjacent JSON or a `layouts` table
in `metrics.db` — implementation detail for the plan) as an ordered list
of placed widgets. An "Edit Dashboard" mode lets a user add widgets from
the catalog, drag/resize/reorder, and set each widget's date range;
"view mode" renders the saved layout read-only.

### Initial widget catalog (v1)

From 4thealth / 4thealth-plus:
- Hygiene score (rollup of unnamed/unlogged/shadow/disabled/expired/unhit
  rule counts)
- Device version compliance %
- Pending config-diff count
- Last backup status
- Firewall online/offline count

From 4tlog:
- FortiAnalyzer CPU/mem health per target
- Log volume trend

From 4tAnalyst — deferred to phase 2 per Scope above.

All widget data is read from `metrics.db`, populated by the collector;
no widget triggers a live source call on render.

## Testing

- Unit tests for the collector (mock source HTTP responses, verify cache
  writes, verify a source outage doesn't crash the poll loop — matching
  4thealth's "catch, log, degrade gracefully" convention already codified
  in its `ruff` config).
- Unit tests for token scoping on the new source-side executive endpoints
  (valid token/wrong scope/disabled feature/missing token → correct
  status codes).
- Route tests for Admin (source CRUD, group/tab gating) and Dashboard
  (layout save/load, widget rendering from cached data).
- No live-network integration tests against real 4thealth/4tlog
  instances in CI; use recorded/mocked responses.

## Open questions for the implementation plan

- Exact storage for dashboard layouts: JSON file under `config/` vs. a
  table in `metrics.db`. Leaning `metrics.db` since layouts are
  user-generated data, not admin config, but worth confirming during
  planning.
- Whether `admin` needs sub-permissions (source management vs. user
  management) in v1 or can wait — current lean is wait, matching
  4thealth's current single-permission granularity.
