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

## Schema v1/v2 freshness acceptance

Sibling repos (`4thealth-plus`, `4tlog`) are migrating to `schema_version: 2`
payloads that add a top-level `freshness` map (`{field_group_key:
collected_at}`) alongside every existing `schema_version: 1` key — an
additive bump, not a breaking one. `app/widgets.py`'s `_freshness_collected_at(value,
key)` is the single place that resolves a field group's `collected_at` for
staleness checks (`_is_stale`), trying, in order:

1. If `value["schema_version"] == 2` and `value["freshness"]` is a dict: look
   up `freshness[key]`, then `freshness[key without "_collected_at" suffix]`
   (sibling repos may key the freshness map by the bare group name instead of
   repeating the suffix).
2. Otherwise (v1/absent `schema_version`, missing/non-dict `freshness`, or
   neither v2 lookup above hit): fall back to today's v1 behavior —
   `value[key]`, then the `device_review`-specific case
   (`value["device_review"]["collected_at"]`) as a last resort.

Never raises on malformed input (non-dict `freshness`, etc.) — degrades to
`None`, same as "no freshness data yet." This keeps every existing
`_FIELD_GROUP_FRESHNESS` entry working unchanged against v1 payloads while
transparently picking up a v2 source's `freshness` map when present.

The same absent-safe posture extends to the sibling repos' new **optional
`details` lists** inside several rollups (`device_review.details`,
`rule_hygiene.details`, EOL entries in `version_breakdown`, `silent_devices`,
`psirt.top_advisory.devices`) — see "Devices drill-down" below and
[integrations.md](integrations.md) for the exact shapes.

## Devices drill-down

`app/devices.py` (pure data module, no Flask imports, same separation as
`app/domains.py`) extracts device-level rows from each source's latest
`"summary"` snapshot:

- `get_domain_devices(name)` — every row for one domain (posture, hygiene,
  lifecycle/EOL, logging, vulnerability), merged across every enabled source
  of that domain's `system`, via a `name -> extractor` mapping
  (`_DOMAIN_ROW_FUNCS`). A domain with no mapped details list (e.g.
  `availability`) returns `[]`.
- `get_fleet_devices()` — one row per distinct device across *every*
  domain's details lists, keyed by `(device, adom)` (falling back to bare
  device name when `adom` is absent, since silent-device rows carry none).
  Each row has independent `posture`/`hygiene`/`eol`/`silent`/`vulnerability`
  summary-string columns; a device with no entries anywhere is never
  synthesized.
- `devices_to_csv(rows, columns)` — a small stdlib-`csv` helper shared by
  both the per-domain and fleet CSV export routes.

Every lookup is `.get(...)`/`isinstance`-guarded, so a source that doesn't
report a given details list (or reports nothing at all) degrades to an empty
list rather than raising. Rendered by `app/templates/domain_detail.html`'s
"Devices" section (per domain, only shown when non-empty) and
`app/templates/devices.html` (the fleet-wide `/devices` page) — both include
a client-side substring filter box and a CSV export link.

## Weekly Executive Brief

Six modules implement the brief, split along a data/integration boundary:

- **`app/brief.py`** (pure data + string logic, no Flask) —
  `build_status_sentence(events, domain_deltas)` composes the masthead status
  line (critical/attention counts, top critical title, improving/degrading
  domains), and `build_brief(now=None)` assembles everything
  `brief.html`/`brief_email.html` render: the status line, 5 metric tiles
  (each with a 7-day sparkline via `app.widgets.downsample_series`), open
  critical events as "Needs a decision", three posture/compliance panels
  (`device_review`/firmware/`change_control`, read directly from the latest
  snapshot the same way `app.domains.get_infra_devices()` reads `infra`), the
  editable "asks" list (`app.metrics_db.get_brief_asks`), and two 30-day
  trend series (`domain.posture`, `domain.logging`) against their scoring
  targets. Every value is optional/absent-safe — an empty, freshly
  initialized database still renders a valid (if empty) brief. The trailing
  7-day window's baseline is `compute_domain(..., compare_to="7d")` — that
  existing baseline semantic already means "vs. 7 days ago," which is exactly
  the prior-week comparison the brief wants, so no second baseline concept
  was introduced.
- **`app/routes/brief_routes.py`** — see "Web app" above.
- **`app/smtp_client.py`** — `load_smtp_config()`/`save_smtp_config()`
  against `config/smtp.json` (this repo's own `CONFIG_DIR` convention, not
  mirrored from where 4thealth-plus keeps its equivalent file), plus
  `send_email()`/`test_connection()`. The password is encrypted at rest via
  `app.crypto.encrypt_token`/`decrypt_token` (already used for source bearer
  tokens) — **unlike the 4thealth-plus module this one was mirrored from**,
  which stores its SMTP password in cleartext JSON.
- **`app/brief_pdf.py`** — `render_pdf(html_path_or_url, out_path)` generates
  a *real* PDF by shelling out to a headless Chrome/Chromium binary
  (`subprocess.run([..., "--headless=new", "--print-to-pdf=...", ...])`),
  located via the `CHROME_BINARY` env var or a fixed fallback search list
  (`google-chrome`, `chromium`, the macOS `.app` path, etc.). **This is a
  deliberate correction, not a port**: the original design doc modeled this
  on 4thealth-plus's "pdf" report format, believing it did headless-Chrome
  conversion — it does not; that repo's "pdf" format is actually just a
  styled HTML attachment. When no Chrome/Chromium binary is found (or the
  subprocess fails), `render_pdf` returns `False` and logs a warning; callers
  must treat that as "skip the PDF attachment, still send the HTML," never as
  an error. See [integrations.md](integrations.md) for more on this
  correction.
- **`app/brief_schedule.py`** — `get_brief_schedule_config()`/
  `save_brief_schedule_config()` against `config/brief_schedule.json`
  (`{weekday, hour, recipients, enabled}`), and
  `validate_schedule_config(cfg)` (weekday 0-6, hour 0-23, recipients are
  comma-separated addresses each containing `@`, at least one required when
  `enabled`).
- **`app/brief_send.py`** — `send_weekly_brief(app, now=None)`: builds the
  brief, renders `brief_email.html` outside a request (via `app.jinja_env`
  inside `app.app_context()`), writes it to
  `<GENERATED_DIR>/<week_key>.html`, attempts a PDF alongside it, emails both
  (PDF omitted on failure) to the configured recipients, and records the
  outcome via `insert_brief_send` (`"sent"`/`"partial"`/`"failed"`). Every
  step is best-effort/log-and-degrade — a PDF failure never blocks the
  email, and a send failure never crashes the scheduler thread.

`app/collector.py`'s `init_scheduler(app)` registers a `weekly_brief` cron
job (`CronTrigger(day_of_week=weekday, hour=hour)`, sourced from
`get_brief_schedule_config()` at scheduler-start time) alongside the
existing `poll_all`/`poll_self`/`metrics_retention`/`domain_scores` jobs —
skipped entirely when the schedule config's `enabled` is false. Like every
other job in this scheduler, the cron schedule is read once at startup;
changing `config/brief_schedule.json` takes effect on the next app restart,
not live.

`app/config_paths.py` adds `GENERATED_DIR` (`<repo>/generated/briefs/`,
created on demand) holding each week's rendered `<week_key>.html` and
`<week_key>.pdf` — served by Admin > Reports'
`GET /admin/reports/sends/<id>/download.<ext>` route.

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
  refresh, Scoring config, and a Reports panel (SMTP settings, weekly brief
  schedule, "send test", brief-send history/downloads). Gated by
  `@tab_required("admin")`.
- **`brief`** (`app/routes/brief_routes.py`) — `GET /brief` (the Weekly
  Executive Brief page, gated `@tab_required("brief")`) and
  `POST /brief/asks` (save the editable "asks" list, gated
  `@tab_required("brief_edit")`).

`scorecard_routes.py` also adds the fleet devices drill-down: `GET /devices`
and `GET /devices.csv` (fleet-wide), plus `GET /domain/<name>/devices.csv`
(per-domain CSV export) alongside the existing `/domain/<name>` detail page,
all gated `@tab_required("dashboard")`.

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
  smtp.json                  SMTP settings (password encrypted at rest)
  brief_schedule.json        weekly brief send schedule
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
  time series" above), each user's saved dashboard layout, and two brief
  tables: `briefs` (`week_key` PRIMARY KEY, `asks` JSON, `updated_at`,
  `updated_by` — the editable "asks for leadership" list, one row per ISO
  week) and `brief_sends` (`id`, `week_key`, `sent_at`, `recipients`,
  `status`, `error` — a history row per weekly-send attempt, whether
  scheduled or triggered via Admin > Reports' "send test"). This is data,
  not config, so it stays outside `config/` and is gitignored.
- **`config/*.json`** — admin-managed configuration: users, groups, source
  registry, app settings, SMTP settings (`smtp.json`, password encrypted at
  rest), and the weekly brief send schedule (`brief_schedule.json`).
- **`generated/briefs/`** (repo root, gitignored) — rendered
  `<week_key>.html` / `<week_key>.pdf` files from each brief send, served by
  Admin > Reports' download route. See "Weekly Executive Brief" above.

## Design history

`docs/superpowers/specs/` and `docs/superpowers/plans/` hold the original
design spec and implementation plan this app was built from. They're kept
for historical context on *why* certain choices were made (e.g. why local
auth instead of SSO, why a predefined widget catalog instead of a generic
query builder) — treat this file and the code as the current source of truth
where the two disagree.
