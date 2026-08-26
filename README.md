# 4tExecutive

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
  widget catalog (hygiene score, device compliance %, backup status,
  FortiAnalyzer health, log volume trend, etc.), arranged on a `1x1` / `2x1` /
  `2x2` grid.
- **Admin tab** — manage the source registry (add/remove/refresh source
  instances), users, and groups. Gated behind the `admin` tab permission in
  `config/groups.json`.
- **Scheduled collector** — polls each source on its own
  `poll_interval_minutes`, with a manual "refresh now" per source. A source
  outage is logged and skipped, never crashes the poll loop.
- **Local auth** — bcrypt-hashed passwords, group-based tab permissions, no
  external identity provider required.

See [docs/architecture.md](docs/architecture.md) for how the pieces fit
together.

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
docs/                  Setup, architecture, and customization docs
tests/                 pytest suite, one file per module
manage_users.py        CLI for creating/deleting/listing users
seed_demo_data.py       Fake data for visual QA
wsgi.py                 gunicorn entrypoint
```

## Security

See [SECURITY.md](SECURITY.md) for the threat model, token handling, and how
to report a vulnerability.

## License

[MIT](LICENSE)
