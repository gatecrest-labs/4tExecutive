# 4tExecutive

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo-dark.svg">
  <img alt="4tExecutive logo" src="logo.svg" width="240">
</picture>

An executive-facing dashboard that aggregates metrics from an organization's
existing FortiGate-related tools — `4thealth` / `4thealth-plus` and `4tlog`
today, `4tAnalyst` planned — into one read-only view, without giving
executives access to the operational tools themselves.

4tExecutive never calls a source system live during a page render. A
background collector polls each configured source on a schedule and writes
the results to a local SQLite cache; the dashboard only ever reads from that
cache.

## Features

- **Scorecard (landing page)** — six graded domains (Availability, Config
  Posture, Vulnerability, Policy Hygiene, Logging & Visibility, Lifecycle &
  Support), each rolled up from the widget catalog's metrics into a 0-100
  score and an A-F grade, plus an overall grade for the fleet. Click a
  domain card to see its score history, member metrics, and the live
  formula behind the grade. See "Reading the scorecard" below.
- **Board tab (Trend Board)** — one row per metric per source, grouped by
  domain: current value, delta vs a selectable baseline and vs 30 days ago,
  a sparkline with a target line, a target meter, and a freshness stamp.
  Sortable by status/delta/name, filterable by domain/source, exportable as
  CSV. Fixed and comprehensive (every catalog metric x every enabled
  source) rather than per-user — see "Reading the board" below for what the
  colors and symbols mean.
- **Admin tab** — a single tabbed page: Sources (add/remove/refresh the
  source systems 4tExecutive polls), Users, Settings (display timezone),
  Scoring (the weights and formula parameters behind each domain's grade),
  and System (this server's own CPU/Memory/Disk utilization, charted over a
  selectable time range). Gated behind the `admin` tab permission in
  `config/groups.json`.
- **Scheduled collector** — polls each source on its own
  `poll_interval_minutes`, with a manual "refresh now" per source. A source
  outage is logged and skipped, never crashes the poll loop.
- **Local auth** — bcrypt-hashed passwords, group-based tab permissions, no
  external identity provider required.

See [docs/architecture.md](docs/architecture.md) for how the pieces fit
together.

## Reading the scorecard

Each of the six domains gets a **letter grade** (A ≥ 90, B ≥ 80, C ≥ 70,
D ≥ 60, F below that) computed from a start-at-100-and-subtract formula over
that domain's metrics — e.g. Availability starts from online/managed
firewalls, Policy Hygiene subtracts for rule findings per 1000 rules. A
domain with no measured inputs yet (Vulnerability and Lifecycle & Support,
until their underlying metrics ship) shows **"not yet measured"** instead of
a grade — that's not a red flag, just data that doesn't exist yet.

The **overall grade** is a weighted mean across whichever domains are
currently measured (an unmeasured domain is excluded, not scored as zero),
and its color follows the worst measured domain's grade — one red domain
makes the whole scorecard red, the same "worst wins" logic as the Board's
posture strip.

Click any domain card to see its score history (30/90/365 days), the
individual metrics feeding it with their own current value and delta, and a
"how this score is computed" panel that prints the formula with the domain's
actual current numbers substituted — the same math shown, so a director can
verify a grade rather than take it on faith. The weights and caps behind
every formula are editable in Admin → Scoring.

## Reading the board

The Trend Board is one row per (metric, source), grouped into the same six
domains as the Scorecard, sorted (status/delta/name) and filtered
(domain/source) via the controls above the table.

**The status dot** on each row is that metric's own RAG state, same
thresholds the Scorecard's formulas read from:

| Metric | Green | Amber | Red |
|---|---|---|---|
| Hygiene Score | ≥ 90 | ≥ 75 | < 75 |
| Device Version Compliance % | ≥ 95 | ≥ 85 | < 85 |
| Pending Config Diffs | 0 | 1–5 | > 5 |
| Fleet Availability | 100% online | ≥ 90% online | < 90% online |
| App Config Backup | reports "ok" | — | anything else |
| Configuration Posture, Silent Devices | no critical findings / no silent devices | — | any critical finding / any silent device |

A gray dot (rule count, ADOM count, version breakdown, rule hygiene, AI
usage, FortiAnalyzer health, log volume) means the metric has no defined
threshold — purely informational, not "unmeasured." Its Target column reads
"informational" instead of a target/meter for the same reason.

**Delta columns** ("vs {compare to}" and "vs 30d") show direction with an
arrow and magnitude ("▲ +3", "▼ −2", "— 0"), colored by whether that
direction is actually an improvement for this specific metric — green when
better, red when worse, gray when the metric has no defined direction (a
rising rule count isn't inherently good or bad). The legend line under the
table restates this.

**The sparkline** charts the selected window (30d/90d/1y) with the metric's
healthy target as a dashed line; hover any point for its exact value and
date. **Target meters** fill toward 100% as a "higher is better" metric
approaches its green threshold, or drain toward empty as a "lower is
better" metric rises toward its amber threshold.

**Export CSV** downloads the exact rows currently shown (same
sort/filter/baseline as the page).

On the Admin → Sources page, each source's last-poll status is a small dot:
🟢 **OK** (last poll succeeded), 🔴 **Failed** (hover for the error), or
⚪ **Not yet polled**.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo>
cd 4tExecutive
uv sync
cp .env.example .env
# edit .env: set SECRET_KEY to a real random value
python manage_users.py create admin yourpassword
uv run python wsgi.py
```

Visit `https://localhost:8200` (or `http://` if you haven't set up
`certs/cert.pem` / `certs/key.pem` — see
[docs/setup.md](docs/setup.md#tls-certificates)) and log in with the user you
just created.

On first run, 4tExecutive copies `config/examples/*.example.json` to
`config/*.json` automatically — nothing to set up by hand beyond your first
admin user.

For Docker, production deployment, and a from-scratch walkthrough, see
[docs/setup.md](docs/setup.md).

## Demo data

To explore the UI without wiring up real source systems:

```bash
python seed_demo_data.py
```

This writes fake sources, users, and metrics snapshots directly (no network
calls). It prints a demo username/password you can log in with.

## Connecting a source system

See [docs/integrations.md](docs/integrations.md) for the API contract a
source (`4thealth`, `4tlog`, ...) must expose, which fields each existing
widget expects, and how to register a running instance in Admin.

## Customizing the dashboard

See [docs/customizing-dashboard.md](docs/customizing-dashboard.md) for how to
add a new widget type, add a new source system, or change tab/group
permissions.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and conventions.

## Project layout

```
app/
  routes/            Flask blueprints (auth, dashboard, admin)
  templates/          Jinja templates
  collector.py         APScheduler polling job
  metrics_db.py        SQLite cache reads/writes
  sources.py           Source registry CRUD
  widgets.py           Widget catalog + value lookup
  auth.py, groups.py    Local auth and tab permissions
  config_paths.py       Central config directory + first-run bootstrap
config/
  examples/            Tracked *.example.json templates
  *.json               Gitignored, real config (users, groups, sources, ...)
docs/                  Setup, architecture, integrations, and customization docs
tests/                 pytest suite, one file per module
manage_users.py        CLI for creating/deleting/listing users, changing passwords
seed_demo_data.py       Fake data for visual QA
wsgi.py                 gunicorn entrypoint
```

## Security

See [SECURITY.md](SECURITY.md) for the threat model, token handling, and how
to report a vulnerability.

## License

[MIT](LICENSE)
