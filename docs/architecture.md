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

Every successful write also runs `app.metric_extract.extract_all` on the
payload and inserts the result into `metric_points` (see "Derived metric
time series" below) — best-effort, so an extractor bug never breaks polling.
A separate scheduler job, `metrics_retention` (daily), calls
`apply_retention()` to prune old snapshots and downsample old metric points.

## Derived metric time series

Every snapshot is stored verbatim (see Data storage), but widgets that need
*trends* — a delta against a baseline, or a sparkline — read from a second,
uniform table instead of re-parsing each snapshot's nested JSON:

```
metric_points(source_id, metric_key, ts, value REAL)
  PRIMARY KEY (source_id, metric_key, ts)
```

`app/metric_extract.py` holds the extractor registry: one
`metric_key -> callable(payload) -> float | None` entry per scalar
`WIDGET_CATALOG` reads, plus nested rollup scalars
(`device_review.devices_with_failures`,
`device_review.findings_by_severity.{critical,high,medium,low}`,
`rule_hygiene.rule_findings_total`,
`rule_hygiene.rule_findings_by_type.<check_name>` — expanded dynamically
since the set of check names varies per payload) and derived metrics
(`fleet_availability_pct`). A composite field with no single sensible scalar
(`version_breakdown`, `device_review`, `ai_usage_24h`, `rule_hygiene`) still
has a registry entry, so every catalog field is covered, but its extractor
always returns `None`.

`extract_all(payload)` runs the whole registry and returns
`{metric_key: value}`, dropping `None`s. `app/collector.py` calls it after
every successful `write_snapshot`. `python -m app.metric_extract --backfill`
walks every existing snapshot through the same extractors — idempotent
(re-running just re-derives the same values), for populating `metric_points`
from history that predates this table.

**Retention:** raw `snapshots` are kept 90 days. `metric_points` are kept 13
months; rows older than 90 days are downsampled to one point per calendar day
(mean of that day's points) by the daily `metrics_retention` scheduler job
(`app/metric_extract.apply_retention`).

`app/widgets.py`'s `annotate()` reads `metric_points` to attach, per widget,
`data["now"]` (latest value), `data["baseline_delta"]` (now minus the value
at a baseline — `yesterday` / `7d` / `30d` / `quarter_start`, passed in as
`compare_to`), `data["better"]` (`true`/`false`/`null`, from the catalog
entry's `direction`: `higher`/`lower`/`none`), and `data["series"]` (points
over a `sparkline` window — `30d`/`90d`/`1y` — downsampled to at most 120
points). These are additive to the existing `value`/`points`/`chart`/`delta`
keys computed from `snapshots` history — no template consumes them yet.

## Web app

Four blueprints, registered in `app/__init__.py`:

- **`auth`** (`app/routes/auth_routes.py`) — login/logout, bcrypt password
  check against `config/users.json`.
- **`scorecard`** (`app/routes/scorecard_routes.py`) — the landing page (`/`):
  six domain grades (`app/domains.py`) and each domain's drill-down
  (`/domain/<name>`).
- **`dashboard`** (`app/routes/dashboard_routes.py`) — the Trend Board
  (`/board`, `/board.csv`): one row per (metric, source), built by
  `app/board.py` from the same fixed widget universe as
  `app/widgets.py:default_layout()` (not a per-user saved layout — the
  `/dashboard/edit` + `/dashboard/layout` saved-layout endpoints still exist
  and work, they're just not read by any page anymore).
- **`admin`** (`app/routes/admin_routes.py`) — source registry CRUD, manual
  refresh, and Scoring config. Gated by `@tab_required("admin")`.

Both `dashboard`/`scorecard` and `admin` tab visibility are controlled
per-user by `config/groups.json` — a user only sees a tab if their group's
`allowed_tabs` includes it (`app/groups.py`, `app/decorators.py`); both
`scorecard` and `dashboard` routes are gated by the same `"dashboard"` tab.

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
  snapshots, the derived `metric_points` time series (see "Derived metric
  time series" above), plus each user's saved dashboard layout. This is
  data, not config, so it stays outside `config/` and is gitignored.
- **`config/*.json`** — admin-managed configuration: users, groups, source
  registry, app settings.

## Design history

`docs/superpowers/specs/` and `docs/superpowers/plans/` hold the original
design spec and implementation plan this app was built from. They're kept
for historical context on *why* certain choices were made (e.g. why local
auth instead of SSO, why a predefined widget catalog instead of a generic
query builder) — treat this file and the code as the current source of truth
where the two disagree.
