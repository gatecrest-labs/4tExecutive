# Exec Recommendations Tier 3 — 4tlog Summary API & Silent-Device Detection — Design

Date: 2026-08-29
Spec source: `docs/Exec-recommendations.md`, section 2 "Tier 3" (recs 3.1, 3.2, 3.3)
Repos: `4tlog` (`/Users/alanw/code/github/web/4tlog`), `4tExecutive` (this repo)

## 1. Scope

Ships Tier 3 recs **3.1** (4tlog external summary API), **3.2** (silent-device detection), and
**3.3** (real log volume trend) across both repos. These three share one collector (FAZ
`logview/logstats`) and one payload, so they ship as a single project rather than three.

**Out of scope:** 3.4–3.8 (4thealth+ device-backup age, cert expiry, license expiry, cache
persistence, composite posture score) — separate sub-projects, per the decomposition agreed
before this design.

4tlog and 4tExecutive changes ship as independent releases, following the Tier 1/2 precedent:
all new 4tExecutive widgets degrade to "No data yet" against a 4tlog instance that hasn't shipped
this work; 4tExecutive's poll of an unconfigured/pre-Tier-3 4tlog instance must not crash or
regress the existing `faz_health`/`log_volume_trend` display.

## 2. Payload contract (4tlog `/external/api/executive/summary`, new)

This is a **new** endpoint — 4tlog currently has no external API of any kind. It mirrors
4thealth+'s `/external/api/` pattern: bearer-token auth, a feature-flag gate, tokens hashed at
rest.

```jsonc
{
  "schema_version": 1,

  "faz_targets_total": 3,
  "faz_targets_healthy": 3,
  "faz_disk_used_pct": 61.2,

  "devices_logging": 38,
  "devices_silent": 2,
  "silent_device_threshold_minutes": 60,

  "log_volume_events_per_sec": 812.4,

  "log_stats_collected_at": "2026-08-29T18:00:00Z"
}
```

Field notes:
- `faz_targets_total`/`faz_targets_healthy` — from the existing `faz_health_cache` (healthy =
  `status in ("green", "yellow")`; `red`/`offline`/`gray` count against health, matching the
  Dashboard tab's existing three-tier classification).
- `faz_disk_used_pct` — **max** across all configured targets' parsed `disk_used` values (skip
  targets where it's `"n/a"` or unparseable). Worst-case disk pressure is the actionable signal;
  averaging would mask one appliance nearly full behind healthy others. `None` if no target has a
  parseable value.
- `devices_logging`/`devices_silent` — fleet-wide device counts from the latest `logstats` poll
  across all targets, classified per §3 below. A device with no logstats data (FAZ unreachable
  this poll) is excluded from both counts, not counted as silent — an unreachable FAZ is a
  `faz_targets_healthy` problem, not a device-logging problem.
- `silent_device_threshold_minutes` — echoes the configured threshold so 4tExecutive can label
  the widget correctly without hardcoding the default.
- `log_volume_events_per_sec` — fleet-wide sum of the latest per-device `lograte` values across
  all targets and vdoms. A **scalar**, not an array: 4tExecutive builds its own trend line from
  repeated polls of this field, the same way it already trends `rule_hygiene.rule_findings_total`
  — no new trending convention introduced.
- `log_stats_collected_at` — timestamp of the logstats poll cycle this payload reflects; distinct
  from `faz_health`'s own poll cycle, since they now run on independent intervals (§4).
- Missing/null fields follow the existing convention: absence means "not computed yet" (e.g. no
  logstats poll has completed since startup), never a crash on the consumer side.

## 3. Silent-device classification (4tlog)

**Where:** `app/log_stats_cache.py` (new), structured like `app/faz_health_cache.py`.

**Per FAZ target, per poll:**
1. Call `FAZClient.get_log_stats(adom)` (new method, §5) → list of
   `{devid, devname, last_log_timestamp, lograte}`, one entry per device (per-vdom `lograte`
   summed, per-vdom `last-log-timestamp` taking the max/most-recent across the device's vdoms).
2. Classify each device: `silent = (now - last_log_timestamp) > SILENT_DEVICE_THRESHOLD_MINUTES`
   (default 60, env `SILENT_DEVICE_THRESHOLD_MINUTES`, matching `Config`'s existing
   env-var-with-default pattern in `app/config.py`).
3. A device with `last_log_timestamp` absent/zero (FAZ has never received a log from it) is
   silent by definition — no grace period.

**Fleet-wide aggregation (across all targets):** dedupe by `devid` — a device registered to a
Security Fabric group could theoretically be visible from more than one FAZ target's ADOM view;
the last poll's result for a given `devid` wins if seen twice in one cycle. `devices_logging` =
count not silent; `devices_silent` = count silent.

## 4. Collector & persistence (4tlog)

**Poll cadence:** a new, independent APScheduler job (`log_stats_poll`, 5-minute interval, env
`LOG_STATS_POLL_INTERVAL`), separate from the existing `faz_health_poll`
(`SNMP_POLL_INTERVAL`). Log stats are cheap JSON-RPC calls with no SNMP round-trip; no reason to
couple its cadence to the health/SNMP poll. Guarded by the same
`Config.FAZ_HEALTH_POLL_DISABLED`-style test flag (new `Config.LOG_STATS_POLL_DISABLED`) so tests
never start a real background poller.

**In-memory state:** `log_stats_cache.py` holds the latest per-target, per-device classification
in a lock-guarded dict (`_cache`), read by `get_all_cached()` — same shape as
`faz_health_cache.get_all_cached()`. This is what `devices_logging`/`devices_silent` in the
summary payload reads live; it is rebuilt from scratch on every poll and does not need to survive
a restart on its own.

**Persistence — new `logstats.db` (SQLite), schema mirrors 4tExecutive's `metrics_db.py`:**

```sql
CREATE TABLE IF NOT EXISTS log_volume_history (
    collected_at TEXT NOT NULL,
    devices_logging INTEGER NOT NULL,
    devices_silent INTEGER NOT NULL,
    total_lograte REAL NOT NULL
)
```

One row written per poll cycle (fleet-wide rollup only — no per-device history persisted, keeping
the table small and avoiding a second copy of device-identifying data at rest). Rows older than
30 days are pruned each poll (matching 4tExecutive's snapshot retention and its longest chart
range). This table exists so that immediately after an app restart, before the first new poll
completes, the summary endpoint can serve the last-known rollup instead of nulling out
`devices_logging`/`devices_silent`/`log_volume_events_per_sec` for one full poll interval — the
`/external/api/executive/summary` route reads the in-memory cache first and falls back to this
table's most recent row when the cache is empty (cold start only).

## 5. FAZClient changes (4tlog)

`app/faz_client.py` gains:

```python
def get_log_stats(self, adom: str | None = None) -> list[dict]:
    """Per-device log stats for the given ADOM (or self.adom), via
    /logview/adom/<adom>/logstats. Returns [{devid, devname,
    last_log_timestamp, lograte}], one entry per device, vdoms folded
    into a single per-device record (max timestamp, summed lograte)."""
```

Request/response shape confirmed from the vendored spec
(`api-info/FortiAnalyzer 7.6.7 FortiAnalyzer Modules logview.json`,
`logview.logstats.get.{req,resp}`): POST to the JSON-RPC endpoint (same `_post`/
`_unwrap_result` plumbing as every other `FAZClient` method) with
`url: /logview/adom/<adom>/logstats`, `apiver: 3`. Response:
`result.data.devs[]` → `{devid, devname, vdoms: [{vdom, last-log-timestamp, lograte, ...}]}`.
Per device: `last_log_timestamp = max(v["last-log-timestamp"] for v in vdoms)`,
`lograte = sum(v["lograte"] for v in vdoms)`. A device with an empty `vdoms` array yields
`last_log_timestamp = None`.

Errors follow the existing `FAZError`/connection-error handling already used by every other
`FAZClient` call site — `log_stats_cache.py`'s per-target poll wraps each target independently
(same try/except-per-target shape as `faz_health_cache.poll_all_targets()`), so one target's FAZ
being unreachable never blocks another target's poll or aborts the cycle.

## 6. External API infrastructure (4tlog, new)

Ported near-verbatim from 4thealth+'s pattern (`app/api_tokens.py`,
`app/routes/external_api_routes.py`), scoped down to the one endpoint 4tlog needs:

- **`app/api_tokens.py`** — SHA-256-hashed bearer tokens in `api_tokens.json` (gitignored,
  `.example.json` committed), `TOKEN_PREFIX = "4tl_"` (distinct prefix from 4thealth+'s `4th_`
  so a leaked token's source system is identifiable at a glance). `create_token`/`list_tokens`/
  `revoke_token`/`validate_token`, identical function shapes to 4thealth+'s module.
- **`app/app_settings.py`** (new, or extend if a settings store doesn't already exist in 4tlog —
  confirmed at implementation time; none was found in the initial exploration) — adds
  `external_api_enabled` (default `False`), same JSON-file-backed pattern as 4thealth+'s.
- **`app/routes/external_api_routes.py`** — blueprint at `/external/api`, one route:
  `GET /external/api/executive/summary`. Same `_gate()`/`_authenticate()` shape as 4thealth+'s
  (503 when disabled, 401 on missing/invalid token).
- **Admin UI** — a new "External API" section on the existing Admin tab (token create/list/revoke
  + the enable toggle), following whatever existing Admin sub-tab pattern 4tlog's Admin →
  FAZ Targets page already establishes (reviewed at implementation time, not re-derived here).

## 7. 4tExecutive changes

**`app/widgets.py`:**
- `4tlog.log_volume_trend` — `chart_type` changes from unset (raw scalar) to `"line"`, reading
  `log_volume_events_per_sec`. Trended via 4tExecutive's own snapshot history, identical
  mechanism to `4thealth.rule_hygiene`'s line-chart branch — no special-casing needed beyond
  pointing the field name at the new key. **Field name changes** from the old aspirational
  `log_volume_trend` key to `log_volume_events_per_sec` — this is a breaking rename on the 4tlog
  contract, acceptable because the old field was never implemented on the 4tlog side (per the
  original recommendations doc, section 1.4: "not implemented in 4tlog at all"), so there are no
  real deployments to break.
- New catalog entry `4tlog.silent_devices` (`chart_type: "bar"`, `default_size: "1x1"`): bar data
  `{"Logging": n, "Silent": n}` from `devices_logging`/`devices_silent`, `rag`: red when
  `devices_silent > 0`, green otherwise — same manual-RAG-assignment pattern as
  `4thealth.device_review_posture` (bypasses `_attach_rag`'s numeric classifier, sets `"rag"`
  directly on the returned dict).
- `4tlog.faz_health` — unchanged field/shape, gains a `_FIELD_GROUP_FRESHNESS` entry keyed off
  `log_stats_collected_at` isn't right (that's the logstats cycle, not the health-poll cycle) —
  **no staleness entry added for `faz_health`** in this project; it already carries its own
  `collected_at` via the generic snapshot mechanism, which is sufficient. (Reconsidered from the
  approved design's "gains staleness tracking off `log_stats_collected_at`" — that field is the
  wrong freshness source for this widget; corrected here during spec self-review.)

**`app/templates/dashboard.html`**: reuses the existing bar-chart + `widget-breakdown` rendering
paths untouched by this project (silent_devices renders through the same bar-chart branch
`device_review_posture` already established in Tier 2 — no new template branch needed, only a
new catalog entry).

**`docs/integrations.md`**: document `faz_targets_total`, `faz_targets_healthy`,
`faz_disk_used_pct`, `devices_logging`, `devices_silent`, `silent_device_threshold_minutes`,
`log_volume_events_per_sec`, `log_stats_collected_at`, and the `log_volume_trend` →
`log_volume_events_per_sec` field rename, under the existing `4tlog` section.

## 8. Testing

- **4tlog:** unit tests for `FAZClient.get_log_stats()` (mocked JSON-RPC response, vdoms folding,
  empty-vdoms edge case) mirroring existing `FAZClient` test patterns; `log_stats_cache.py` tests
  for silent classification at the threshold boundary and multi-target dedupe by `devid`;
  `logstats.db` prune-at-30-days test mirroring 4tExecutive's snapshot prune test; route tests for
  the summary endpoint (disabled/unauthorized/happy-path/cold-start-fallback-to-SQLite), mirroring
  4thealth+'s `test_external_api_executive.py`.
- **4tExecutive:** widget catalog + `get_widget_series` tests for `silent_devices`
  (rag red/green, no-data) and `log_volume_trend`'s renamed field, mirroring the Tier 2
  `device_review_posture`/`rule_hygiene` test patterns exactly.

## 9. Contract discipline

Per `docs/Exec-recommendations.md` section 5 (applies to every tier): `schema_version: 1` ships
on 4tlog's very first payload version (no prior unversioned contract to migrate away from, unlike
4thealth+'s Tier 2 addition of the field). All new fields documented in `docs/integrations.md`
before merge. 4tExecutive never crashes on a malformed/missing field from an older or
not-yet-upgraded 4tlog instance.
