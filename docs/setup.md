# Setup

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker + Docker Compose, if deploying via container

## Local development

```bash
git clone <this-repo>
cd 4tExecutive
uv sync --group dev
cp .env.example .env
```

Edit `.env`:

- `SECRET_KEY` — required outside test mode. The app refuses to start if
  this is unset or still the `.env.example` placeholder value. Generate one
  with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- `SSL_CERT` / `SSL_KEY` — see [TLS certificates](#tls-certificates) below.
- `COOKIE_SECURE` — leave as `auto` unless you have a specific reason to
  force it; see [app/__init__.py](../app/__init__.py).

Create your first admin user:

```bash
uv run python manage_users.py create admin yourpassword
```

By default a fresh checkout has no `config/groups.json`, so that user has no
tab permissions yet. On first run the app copies
`config/examples/groups.example.json` to `config/groups.json`, which grants
`admin` both the `dashboard` and `admin` tabs — edit that file (or add your
username to it) if you used a different username than `admin`.

Run the app:

```bash
uv run python wsgi.py
```

### TLS certificates

The app auto-enables secure cookies when `SSL_CERT`/`SSL_KEY` both exist
(`COOKIE_SECURE=auto`). For local development, generate a self-signed pair:

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=localhost"
```

You can also run without TLS locally by leaving `certs/` empty — the app
will serve over plain HTTP and secure cookies stay off.

### Tests and linting

```bash
uv run pytest
uv run ruff check .
```

### Demo data

```bash
uv run python seed_demo_data.py
```

Writes fake sources, users, groups, and metrics snapshots with no network
calls — useful for visual QA of the dashboard without a real 4thealth/4tlog
instance to poll. Prints a demo username/password.

## Docker deployment

```bash
cp .env.example .env    # set SECRET_KEY as above
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/key.pem -out certs/cert.pem -subj "/CN=localhost"
docker compose up --build
```

The container runs `gunicorn` with TLS terminated inside gunicorn itself
(matching the source app's convention) rather than behind a reverse proxy —
`docker-compose.yml` mounts `./certs:/app/certs:ro`. If you're deploying
behind a reverse proxy or load balancer that already terminates TLS,
adjust the `CMD` in [Dockerfile](../Dockerfile) to drop `--certfile`/
`--keyfile` and serve plain HTTP internally instead.

`docker-compose.yml` mounts three things from the host:

- `./config:/app/config:rw,z` — persists users/groups/sources across
  container restarts
- `./metrics.db:/app/metrics.db:rw,z` — persists the metrics cache
- `./certs:/app/certs:ro,z` — TLS cert/key, read-only

The `:z` SELinux label is for RHEL/Fedora-family hosts; drop it on Debian/
Ubuntu if it causes issues (it's a harmless no-op there, but not needed).

After the container is up, create your first user the same way as local dev,
just run it inside the container:

```bash
docker compose exec app python manage_users.py create admin yourpassword
```

## Production notes

- Set a real `SECRET_KEY` — never reuse the `.env.example` placeholder or a
  value used in another environment.
- Use real TLS certificates (not self-signed) in production, or terminate
  TLS at a load balancer in front of the container and adjust the Dockerfile
  `CMD` accordingly.
- `config/` and `metrics.db` hold all persistent state — back these up.
  Everything else in the container is rebuildable from the image.
- The collector only needs outbound HTTPS to each configured source's
  external-API port; no other outbound access, no SSH, no elevated
  container privileges are required.
