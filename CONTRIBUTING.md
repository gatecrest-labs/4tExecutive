# Contributing

## Setup

See [docs/setup.md](docs/setup.md) for local dev setup, then:

```bash
uv sync --group dev
```

## Workflow

1. Create a branch off `main`.
2. Make your change. Add or update tests under `tests/` — this repo follows
   one test file per module (`app/foo.py` → `tests/test_foo.py`).
3. Run the checks below before opening a PR.
4. Open a PR describing the change and why it's needed.

## Checks

```bash
uv run pytest
uv run ruff check .
```

Both must pass locally, and both run in CI on every push and PR
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Conventions

- **Config access** goes through `app/config_paths.py`'s `CONFIG_DIR`, not
  ad hoc relative paths — keeps every module resolving config the same way
  regardless of working directory.
- **Failure handling in the collector**: a source outage or bad response is
  caught, logged, and skipped — it must never crash the poll loop or take
  down other sources' polling. Match this pattern in any new collector code.
- **Config writes are atomic** — use `app/atomic_io.py`'s
  `atomic_write_json`/`read_json` for any new file-backed config or
  registry, rather than writing JSON directly.
- **No live source calls on page render** — the web app only ever reads from
  `metrics.db`. If a new feature needs live data, it belongs in the
  collector (scheduled) or an explicit manual-refresh action, not in a route
  handler.
- **Secrets never committed** — anything under `config/*.json` outside
  `config/examples/`, `.env`, and `certs/` is gitignored. Never add example
  data with a real-looking token/password; use obvious placeholders.

## Reporting bugs / requesting features

Open an issue with steps to reproduce (for bugs) or the use case (for
features). For anything touching auth, token handling, or config file
permissions, see [SECURITY.md](SECURITY.md) instead.
