# Connecting a source system

4tExecutive never talks to your operational tools' normal UI or internal
APIs — it polls one specific, purpose-built endpoint per source instance
and caches whatever that endpoint returns. Wiring up a new source is two
separate steps in two separate codebases:

1. **On the source system** (`4thealth`/`4thealth-plus`, `4tlog`, ...) —
   add the executive-summary endpoint described below. This is not part of
   this repo; it's a change to that system's own codebase.
2. **In 4tExecutive** — register the running instance as a source in
   Admin, and it starts polling on its configured interval.

## The contract 4tExecutive expects

`app/collector.py`'s `poll_source()` does exactly this, once per source
per its `poll_interval_minutes`:

```
GET {base_url}/external/api/executive/summary
Authorization: Bearer <token>
```

- Must be `https://` — Admin rejects any source whose `base_url` isn't
  (see [SECURITY.md](../SECURITY.md)).
- A `200` response body is stored **verbatim** as that source's latest
  snapshot — there's no field allowlist or transformation in between. Any
  other status code is treated as a failed poll (logged, retried next
  interval, doesn't affect other sources).
- The body must be a **JSON object** whose top-level keys match whatever
  the widget catalog (`app/widgets.py`) expects to read for that `system`
  — see the per-system field lists below. Most fields are scalars, but
  `version_breakdown` and `ai_usage_24h` are two exceptions whose values
  are nested JSON objects rather than scalars. Extra keys are ignored;
  a missing key just means that widget shows "No data yet"
  (`get_widget_value()` returns `None` for a missing field).

Nothing else about the endpoint is prescribed — timeouts
(`REQUEST_TIMEOUT_SECONDS = 10` in `app/collector.py`), retry behavior, and
auth are entirely on the 4tExecutive side; the source only needs to return
the right shape.

## Fields each system's widgets expect

From `WIDGET_CATALOG` in `app/widgets.py`:

**`4thealth`** (and `4thealth-plus`, same `system` tag):

| JSON key                     | Widget                        |
|-------------------------------|--------------------------------|
| `hygiene_score`               | Hygiene Score                  |
| `version_compliance_pct`      | Device Version Compliance %    |
| `pending_config_diff_count`   | Pending Config Diffs           |
| `last_backup_status`          | Last Backup Status             |
| `firewall_online_count`       | Firewalls Online               |
| `firewall_managed_count`      | Firewalls Managed              |
| `rule_count_total`            | Total Rules                    |
| `adom_count`                  | ADOMs Configured                |
| `version_breakdown`           | FortiOS Versions (table)       |

**`4thealth-plus` AI usage fields** (optional — omit entirely if AI isn't
enabled on that instance):

| JSON key       | Widget          |
|-----------------|------------------|
| `ai_enabled`    | (controls whether the AI Usage widget appears at all) |
| `ai_usage_24h`  | AI Usage (24h)   |

`ai_enabled` and `ai_usage_24h` are both top-level keys, but `ai_usage_24h`
itself is a nested object, not a scalar: `get_widget_value()` looks up the
`ai_usage_24h` key and returns its value as-is, so the connection count and
cost must be nested under it as sub-fields:

```json
{
  "ai_enabled": true,
  "ai_usage_24h": {
    "ai_connection_count_24h": 340,
    "ai_estimated_cost_24h_usd": 4.10
  }
}
```

`ai_enabled` stays top-level (checked directly by `default_layout()`, not
through the widget catalog) while the widget's own display value
(`ai_usage_24h`) carries the connection count and cost together as one
object, the same way `version_breakdown` carries a dict instead of a scalar.

**`4tlog`**:

| JSON key            | Widget                  |
|-----------------------|--------------------------|
| `faz_health`          | FortiAnalyzer Health     |
| `log_volume_trend`    | Log Volume Trend         |

Example response body from a 4thealth instance:

```json
{
  "hygiene_score": 92,
  "version_compliance_pct": 88,
  "pending_config_diff_count": 3,
  "last_backup_status": "ok",
  "firewall_online_count": 14
}
```

`version_breakdown`'s value is a JSON object mapping version string to
firewall count, e.g. `{"7.4.5": 62, "7.2.9": 41, "7.0.14": 25}`. Along with
`ai_usage_24h`, these are the only two fields whose value is a nested
object; every other field above is a scalar.

See [customizing-dashboard.md](customizing-dashboard.md) for adding a new
widget/field beyond this initial catalog.

## Token scoping (source-side requirement)

The design spec calls for the token a source issues to 4tExecutive to be
**scoped to only this endpoint** — a leaked/compromised 4tExecutive token
must not be usable against that source's other APIs (e.g. 4thealth's
`/external/api/zone/*` used by FW-Analyst). Implement this as a `scope`
field on the source's token record, checked in that endpoint's auth gate,
matching the pattern 4thealth's `api_tokens.py` already uses for its other
external-API tokens. This is enforced on the source side; 4tExecutive just
sends whatever bearer token you paste into Admin.

## Registering a source in 4tExecutive

Once the endpoint exists and you have a token for it:

1. Log in to 4tExecutive as an admin user and go to **Admin**.
2. Fill in the "Add source" form:
   - **ID** — a unique slug, e.g. `4thealth-east`.
   - **System** — must exactly match a `source_system` value in
     `WIDGET_CATALOG` (`4thealth` or `4tlog` today) so the dashboard's
     widgets can find data for it.
   - **Name** — display name, e.g. "East DC".
   - **Base URL** — `https://host:port`, no trailing path.
   - **Token** — the bearer token that instance issued. Stored encrypted
     at rest (see [SECURITY.md](../SECURITY.md)).
   - **Poll interval (minutes)** — how often to collect.
   - **"This source uses a self-signed/internal certificate"** — check
     this if the source's TLS cert isn't from a CA your system trusts
     (the common case for a local/internal instance). Unchecked, the
     collector validates the cert normally and a self-signed source will
     fail every poll with an SSL error. Checking it disables certificate
     verification for *that source only* — see the security note below.
3. Submit. The collector picks it up on its next scheduler tick (checks
   every minute whether any source is due).
4. Use **Refresh now** in Admin to trigger an out-of-band poll instead of
   waiting for the interval — useful for confirming the connection works
   before walking away.

The Admin sources table shows a per-source **status marker** — OK (with
the last successful poll time), Failed (with the actual error, e.g. an
SSL failure or HTTP status), or Not yet polled. A poll failure (network
error, non-200, bad JSON) is logged and skipped; it never crashes the
scheduler or blocks other sources from polling.

### Self-signed certificates

Checking "self-signed/internal certificate" on a source disables TLS
certificate verification for requests to it (`verify=False` on the
collector's HTTP client) — the connection is still encrypted, but
4tExecutive can no longer confirm it's actually talking to the system you
configured rather than something impersonating it on the network. That's
an acceptable trade-off for a source you control on a private network, and
is why it's opt-in per source rather than a global setting. For anything
beyond local testing, prefer giving the source a certificate from a CA
4tExecutive already trusts (or point `REQUESTS_CA_BUNDLE` at that CA's
cert when starting the container — `requests` honors that env var
automatically) over leaving verification off indefinitely.

## 4tAnalyst — not yet supported

4tAnalyst is out of scope for the contract above: per the design spec, it's
a set of MCP servers (`fortimanager_mcp`, `zone_mcp`, `standards_mcp`,
`feedback_mcp`, `fwanalyst_server`), not a Flask app exposing a REST API.
It can't just grow an `/external/api/executive/summary` route the way
4thealth/4tlog can — connecting it needs a small adapter process that
speaks MCP on one side and this HTTP contract (or a direct `metrics_db`
write) on the other. That adapter doesn't exist yet; treat 4tAnalyst
widgets as a future addition once that bridge is designed.
