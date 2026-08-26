# Architecture

4tExecutive is a single Flask app with three logical pieces: a source
registry, a background collector, and a read-only web UI. It never calls a
source system synchronously during a page render — everything the UI shows
comes from a local SQLite cache.

```
        (admin configures)
              |
              v
   config/sources.json  <---- source registry (app/sources.py)
              |
              v
   collector (app/collector.py, APScheduler)
     polls each enabled source on its own
     poll_interval_minutes, over HTTPS with
     a bearer token
              |
              v
       metrics.db (SQLite, app/metrics_db.py)
              |
              v
      Dashboard tab (app/routes/dashboard_routes.py)
        reads only from metrics.db, renders
        each user's saved widget layout
```

## Source registry

`app/sources.py` manages `config/sources.json`, a list of named source
instances the collector polls. `token` is encrypted at rest by
`app/crypto.py` (`add_source`/`update_source` encrypt on write,
`source_headers` decrypts when the collector needs it for the outbound
`Authorization` header) — the value below is illustrative plaintext, not
what's actually written to disk:

```json
{
  "id": "4thealth-east",
  "system": "4thealth",
  "name": "East DC",
  "base_url": "https://4thealth-east.internal:8100",
  "token": "...",
  "poll_interval_minutes": 15,
  "enabled": true
}
```

Multiple instances of the same `system` type are supported without a schema
change (e.g. several 4thealth deployments per site). Admin route validation
in `app/routes/admin_routes.py` requires `base_url` to start with `https://`
so bearer tokens are never sent in cleartext.

## Collector

`app/collector.py` runs as an APScheduler background job started from the
app factory (`init_scheduler`, skipped in test mode). For each enabled
source, once its `poll_interval_minutes` has elapsed, it calls that source's
executive-summary API over HTTPS and writes the result into `metrics.db` via
`write_snapshot`. A failed poll is caught and logged — it never crashes the
scheduler loop, and a missing source is skipped rather than raising. The
Admin tab's "refresh now" button calls `poll_now(source_id)` directly for an
out-of-band poll of a single source.

## Web app

Three blueprints, registered in `app/__init__.py`:

- **`auth`** (`app/routes/auth_routes.py`) — login/logout, bcrypt password
  check against `config/users.json`.
- **`dashboard`** (`app/routes/dashboard_routes.py`) — the personalized
  Dashboard tab: renders a user's saved widget layout (`app/layouts.py`),
  reading widget values from `metrics.db` via `app/widgets.py`.
- **`admin`** (`app/routes/admin_routes.py`) — source registry CRUD and
  manual refresh. Gated by `@tab_required("admin")`.

Both `dashboard` and `admin` tab visibility are controlled per-user by
`config/groups.json` — a user only sees a tab if their group's
`allowed_tabs` includes it (`app/groups.py`, `app/decorators.py`).

## Config layout

All configuration lives under `config/`, with a tracked `examples/`
subdirectory of `*.example.json` templates and a gitignored set of real
files:

```
config/
  examples/                  tracked — templates, safe to commit
    users.example.json
    groups.example.json
    sources.example.json
    app_settings.example.json
  users.json                 gitignored — real values
  groups.json
  sources.json
  app_settings.json
```

`app/config_paths.py` defines `CONFIG_DIR` as the single source of truth for
this path; every module resolves config files through it. On first run
(outside test mode), `bootstrap_config()` copies any missing
`config/examples/*.example.json` to its real counterpart — a fresh checkout
needs no manual file setup beyond creating a user (see
[setup.md](setup.md)).

## Data storage

- **`metrics.db`** (SQLite, repo root) — the collector's cache of source
  snapshots, plus each user's saved dashboard layout. This is data, not
  config, so it stays outside `config/` and is gitignored.
- **`config/*.json`** — admin-managed configuration: users, groups, source
  registry, app settings.

## Design history

`docs/superpowers/specs/` and `docs/superpowers/plans/` hold the original
design spec and implementation plan this app was built from. They're kept
for historical context on *why* certain choices were made (e.g. why local
auth instead of SSO, why a predefined widget catalog instead of a generic
query builder) — treat this file and the code as the current source of truth
where the two disagree.
