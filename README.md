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

- **Dashboard tab** — each user builds their own layout from a predefined
  widget catalog, arranged on a `1x1` / `2x1` / `2x2` grid. Widgets include:
  hygiene score, device version compliance % (with end-of-support versions
  flagged), pending config diffs, app config backup status, fleet
  availability (firewalls online / total), configuration posture (a
  pass/fail rollup of a 26-check device review), rule hygiene (shadowed,
  unhit, unlogged, expired, disabled rules), AI usage, FortiAnalyzer health,
  log volume trend, and silent-device count (appliances that have stopped
  sending logs). See "Reading the dashboard" below for what the colors and
  symbols mean.
- **Admin tab** — a single tabbed page: Sources (add/remove/refresh the
  source systems 4tExecutive polls), Users, Settings (display timezone),
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

## Reading the dashboard

4tExecutive is designed to be scanned in five seconds, not read widget by
widget. Three visual cues carry that:

**The posture strip**, one row above the range selector, is the single
"is anything wrong?" answer:

| Pill | Meaning |
|---|---|
| 🟢 **OK** | Every widget with a defined threshold is within its healthy range. |
| 🟡 **Attention** | At least one widget has crossed its warning threshold. A count ("N critical · M attention") links to the first one. |
| 🔴 **Critical** | At least one widget has crossed its critical threshold. |

The strip also shows the age of the oldest data on the page (e.g. "oldest
data: 12 min ago"), tinted amber if any source hasn't reported in longer
than expected — a hint that a number might be stale rather than actually
fine.

**Per-widget colored borders** apply the same green/amber/red logic to
individual widgets that have a meaningful threshold:

| Widget | Green | Amber | Red |
|---|---|---|---|
| Hygiene Score | ≥ 90 | ≥ 75 | < 75 |
| Device Version Compliance % | ≥ 95 | ≥ 85 | < 85 |
| Pending Config Diffs | 0 | 1–5 | > 5 |
| Fleet Availability | 100% online | ≥ 90% online | < 90% online |
| App Config Backup | reports "ok" | — | anything else |
| Configuration Posture, Silent Devices | no critical findings / no silent devices | — | any critical finding / any silent device |

A widget with no defined threshold (rule count, ADOM count, version
breakdown, rule hygiene, AI usage, host metrics, FortiAnalyzer health, log
volume) is purely informational and never colored — silence there just
means "nothing to alert on," not "unmeasured."

**Delta arrows** next to a trend chart's current value show direction of
change since the start of the selected range — "▲ +3", "▼ −2", or "— 0" —
in neutral gray. The arrow only means "up" or "down," not "good" or "bad"
(a rising rule count isn't inherently a problem); the color-coded border is
what actually flags a concern.

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
