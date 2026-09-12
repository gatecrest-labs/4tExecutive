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
| `schema_version`              | (versioning; not a widget)     |
| `hygiene_score`               | Hygiene Score                  |
| `version_compliance_pct`      | Device Version Compliance %    |
| `pending_config_diff_count`   | Pending Config Diffs           |
| `last_backup_status`          | App Config Backup              |
| `firewall_online_count`       | Firewalls Online               |
| `firewall_managed_count`      | Firewalls Managed              |
| `rule_count_total`            | Total Rules                    |
| `adom_count`                  | ADOMs Configured                |
| `version_breakdown`           | FortiOS Versions (table)       |
| `device_review`               | Configuration Posture          |
| `rule_hygiene`                | Rule Hygiene                   |
| `psirt`                       | Vulnerability domain score      |
| `change_control`               | Availability & Change domain rows |
| `lifecycle`                    | Lifecycle & Support domain score |
| `by_adom`                       | ADOM filter (Board, Scorecard) |
| `infra`                        | Infrastructure card (Availability & Change domain page) |
| `ai_usage_by_feature`         | (detail breakdown for AI Usage)|
| `device_sweep_status`         | (internal sweep tracking)      |
| `hygiene_sweep_status`        | (internal sweep tracking)      |
| `device_sweep_collected_at`   | (timestamp for device sweep)   |
| `hygiene_sweep_collected_at`  | (timestamp for hygiene sweep)  |
| `rule_count_collected_at`     | (timestamp for rule count)     |

`firewall_online_count` and `firewall_managed_count` are still the two raw
fields a source reports, and both remain individually addable widgets (e.g.
in a saved custom layout), but the *default* dashboard no longer shows them
as separate tiles — it computes both fields together into one "Fleet
Availability" widget (`online / managed` as a percentage, with RAG
thresholds) and shows that instead. A source only needs to keep reporting
both raw fields; nothing else changes on the source side.

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

| JSON key                            | Widget                  |
|--------------------------------------|--------------------------|
| `faz_health`                        | FortiAnalyzer Health     |
| `log_volume_events_per_sec`          | Log Volume Trend         |
| `devices_logging` / `devices_silent` | Silent Devices           |

`log_volume_trend` (the field name) is retired — it was never implemented by any 4tlog release
(see the original recommendations doc, section 1.4), so this is not a breaking change to a real
payload, just a rename before the field's first real implementation.

Example response body from a 4tlog instance:

```json
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

- `faz_health` is not shown above — it is not yet emitted by 4tlog's summary payload (tracked
  separately; the widget currently reads whatever a source chooses to send under that key, if
  anything, and displays "No data yet" otherwise).
- `devices_logging`/`devices_silent` are flat top-level integers (not nested, unlike
  `4thealth`'s `device_review`) — a 4tlog instance is a single source of these fleet-wide counts,
  there's no per-check breakdown to nest.
- `silent_device_threshold_minutes` is informational only — 4tExecutive does not use it in
  computation, it only exists so an operator reading the raw payload knows what threshold
  produced the silent count.
- `log_stats_collected_at` drives this widget's staleness (see `_FIELD_GROUP_FRESHNESS` in
  `app/widgets.py`): stale past 40 minutes (2x the realistic worst-case age of 4tlog's 5-minute
  logstats collection interval plus 4tExecutive's own default 15-minute poll interval — this
  timestamp only advances when 4tExecutive polls the source, not on 4tlog's internal cadence
  alone).

Example response body from a 4thealth instance (minimal):

```json
{
  "schema_version": 1,
  "hygiene_score": 92,
  "version_compliance_pct": 88,
  "pending_config_diff_count": 3,
  "last_backup_status": "ok",
  "firewall_online_count": 14,
  "firewall_managed_count": 15,
  "device_sweep_status": "completed",
  "device_sweep_collected_at": "2026-08-28T09:00:00Z",
  "hygiene_sweep_status": "completed",
  "hygiene_sweep_collected_at": "2026-08-28T08:30:00Z",
  "rule_count_collected_at": "2026-08-28T08:15:00Z"
}
```

A richer example including optional nested objects (device_review, rule_hygiene):

```json
{
  "schema_version": 1,
  "hygiene_score": 92,
  "version_breakdown": {"7.4.5": {"count": 62, "eol": false}, "7.2.9": {"count": 41, "eol": false}},
  "device_review": {
    "devices_reviewed": 103,
    "devices_with_failures": 8,
    "findings_by_severity": {"critical": 1, "high": 2, "medium": 5, "low": 3},
    "top_failing_checks": [{"check": "admin_restriction", "count": 4}],
    "collected_at": "2026-08-28T06:00:00Z"
  },
  "rule_hygiene": {
    "rule_findings_total": 118,
    "rule_findings_by_type": {"shadow": 5, "unhit": 65},
    "collected_at": "2026-08-28T09:00:00Z"
  },
  "ai_enabled": true,
  "ai_usage_24h": {"ai_connection_count_24h": 340, "ai_estimated_cost_24h_usd": 4.10},
  "ai_usage_by_feature": {"device_review_summary": {"calls": 45, "cost_usd": 2.3, "failures": 0}},
  "device_sweep_collected_at": "2026-08-28T09:00:00Z",
  "hygiene_sweep_collected_at": "2026-08-28T08:30:00Z"
}
```

`version_breakdown`'s value is a JSON object mapping version string to
firewall count. **Shape changed from flat int to nested object:**
- **Old format** (still supported): `{"7.4.5": 62, "7.2.9": 41, "7.0.14": 25}`
- **New format**: `{"7.4.5": {"count": 62, "eol": false}, "7.2.9": {"count": 41, "eol": false}, "7.0.14": {"count": 25, "eol": true}}`

4tExecutive handles both shapes for backward compatibility — if your source sends the old flat shape, widgets display it as before; if it sends the new shape with `eol` flags, the dashboard also displays which versions are end-of-life.

**Freshness note**: The `version_breakdown` widget currently has no staleness tracking — there is no `collected_at` timestamp for this field and `_is_stale()` returns `None` for it (no entry in `_FIELD_GROUP_FRESHNESS`).

`device_review` is a nested object (absent/null until the first scheduled
device-review rollup run) containing configuration posture details:

```json
{
  "device_review": {
    "devices_reviewed": 42,
    "devices_with_failures": 7,
    "findings_by_severity": {"critical": 1, "high": 3, "medium": 9, "low": 4},
    "top_failing_checks": [{"check": "default_admin", "count": 5}],
    "collected_at": "2026-08-28T06:00:00Z"
  }
}
```

The nested `collected_at` timestamp (inside `device_review`) drives this widget's staleness tracking — **not** `device_sweep_collected_at`. The Configuration Posture widget considers data stale if the `device_review.collected_at` timestamp is older than 2880 minutes (48 hours), per the design doc's expected refresh interval (see `_FIELD_GROUP_FRESHNESS` in `app/widgets.py`).

`rule_hygiene` is a nested object (absent/null until the first scheduled
hygiene-sweep rollup run) containing rule quality metrics:

```json
{
  "rule_hygiene": {
    "rule_findings_total": 100,
    "rule_findings_by_type": {"shadow": 4, "unhit": 60},
    "collected_at": "2026-08-28T09:00:00Z"
  }
}
```

`change_control` is a nested object (from 4thealth-plus schema_version 2
onward; absent on schema_version 1 sources) containing config-drift and
admin-activity metrics:

```json
{
  "change_control": {
    "devices_out_of_sync": 4,
    "admin_changes_24h": 12,
    "admin_changes_by_user": [{"user": "alice", "count": 8}, {"user": "bob", "count": 4}],
    "collected_at": "2026-09-10T01:00:00Z"
  }
}
```

- `devices_out_of_sync` — device count whose normalized `conf_status` is not `"insync"`; sourced from the same device sweep as `firewall_online_count` (freshness: `device_sweep_collected_at`).
- `admin_changes_24h` / `admin_changes_by_user` — from a separate hourly FortiManager admin audit-log sweep; `admin_changes_by_user` is the top 5 users by change count, as `[{user, count}]`.
- `collected_at` — timestamp of that hourly audit-log sweep (not the device sweep — `devices_out_of_sync` tracks `device_sweep_collected_at` instead).
- **No `oldest_pending_change_days` key.** 4thealth-plus's `dvmdb` device object carries no confirmed per-device modification timestamp; the key is omitted rather than fabricated. See that repo's docs/features.md for the full rationale.

`extract_all()` flattens this into `change_control.devices_out_of_sync` and `change_control.admin_changes_24h` metric_points (`change_control` and `change_control.admin_changes_by_user` are composite and always extract to nothing, same pattern as `psirt`/`psirt.top_advisory`). Both land as rows on the **Availability & Change** domain page (`app/domains.py` `MEMBER_METRICS["availability"]`) and as Trend Board rows (`app/widgets.py`'s `4thealth.devices_out_of_sync` / `4thealth.admin_changes_24h` catalog entries, grouped under "availability" in `app/board.py`'s `WIDGET_DOMAIN`): `devices_out_of_sync` has `direction: "lower"` with RAG green at 0 / amber at 3+; `admin_changes_24h` has `direction: "none"` (informational — no single count is inherently good or bad). Neither is wired into the Availability & Change domain **score** formula, which stays online/managed-count only.

`lifecycle` is a nested object (from 4thealth-plus schema_version 2
onward; absent on schema_version 1 sources) containing hardware
end-of-support exposure:

```json
{
  "lifecycle": {
    "devices_hw_eos": 3,
    "devices_hw_eos_12m": 5,
    "models_unknown": ["FortiGate-Unicorn"],
    "collected_at": "2026-09-10T00:00:00Z"
  }
}
```

- `devices_hw_eos` — device count whose hardware platform has already reached end-of-support, per 4thealth-plus's static `app/model_eos.py` table.
- `devices_hw_eos_12m` — device count reaching (or already past) hardware EOS within the next 12 months; a superset of `devices_hw_eos`.
- `models_unknown` — distinct platform strings 4thealth-plus's table has no EOS date for — a hardware family it can't yet assess, surfaced rather than silently treated as "not EOS".
- `collected_at` — same timestamp as `device_sweep_collected_at` (same sweep computes both).
- **No `device_backup` key.** 4thealth-plus could not confirm the FMG revision-history endpoint needed to compute device configuration backup age against its lab FortiManager — see that repo's `docs/superpowers/specs/2026-09-10-device-backup-age-spike.md`. The `4thealth-plus App Config Backup` widget (renamed from "App Config Backup" to disambiguate) is a placeholder for where `device_backup` fields will sit once that lands — it currently reports 4thealth-plus's own *application* config backup, not device backup.

`extract_all()` flattens this into `lifecycle.devices_hw_eos` and `lifecycle.devices_hw_eos_12m` metric_points (`lifecycle` and `lifecycle.models_unknown` are composite and always extract to nothing). A third derived metric, `devices_on_eol_version`, is computed from `version_breakdown`'s per-version `eol` flags (summing the `count` of every version flagged EOL) rather than read directly off the payload.

These three feed the **Lifecycle & Support** domain score (`app/domains.py`): firmware compliance (`version_compliance_pct`, weight 0.5) + a software-EOL component (`100 − devices_on_eol_version / firewall_managed_count × 100`, weight 0.25) + a hardware-EOS component (`100 − devices_hw_eos / firewall_managed_count × 100`, weight 0.25). Any missing component defaults optimistically to a full-health value (100 for firmware compliance, 0% for the EOL/EOS device shares) rather than penalizing a fleet for data 4thealth-plus hasn't reported yet — the domain scores `None` ("not yet measured") only when none of the three inputs have any data at all. `version_compliance_pct`, `devices_on_eol_version`, `lifecycle.devices_hw_eos`, and `lifecycle.devices_hw_eos_12m` all appear as rows on the Lifecycle & Support domain detail page.

`by_adom` is a nested object (from 4thealth-plus schema_version 2 onward;
absent on schema_version 1 sources), keyed by ADOM name, each value
`{firewalls_total, firewall_online_count, version_compliance_pct,
pending_config_diff_count, devices_with_failures}`:

```json
{
  "by_adom": {
    "Corp": {
      "firewalls_total": 42,
      "firewall_online_count": 40,
      "version_compliance_pct": 92.9,
      "pending_config_diff_count": 3,
      "devices_with_failures": 5
    }
  }
}
```

`extract_all()` flattens each ADOM's fields into `by_adom.<adom>.<field>`
metric_points (dynamically, like `rule_hygiene.rule_findings_by_type.*`,
since the set of ADOMs varies) — `by_adom` itself is composite and always
extracts to nothing. `app.metric_extract.BY_ADOM_FIELD_MAP` maps each
fleet-wide metric_key (e.g. `firewall_managed_count`) to its by_adom field
name (`firewalls_total` — note the name differs; that's intentional, not a
typo) for the metrics that have a per-ADOM breakdown; anything not in that
map has no per-ADOM equivalent.

This powers an **ADOM filter** on both the Trend Board (`/board?adom=`)
and the Scorecard (`/?adom=`, and each domain detail page
`/domain/<name>?adom=`) — persisted in an `adom_filter` cookie the same
way `compare_to`/`sparkline`/`domain`/`source` already are. When set, every
row/score/member-metric backed by a by_adom-mapped field reads that ADOM's
value instead of the fleet-wide one; anything without a per-ADOM
breakdown (e.g. `hygiene_score`, `psirt.*`, `lifecycle.devices_hw_eos`)
keeps showing its fleet-wide value regardless of the filter — the UI marks
which rows are actually ADOM-scoped with a small badge. The Scorecard
domain-score **trend chart** is always fleet-wide even under a filter,
since per-ADOM score history isn't tracked (`app/domains.py::
compute_domain()`'s docstring covers this). The list of known ADOM names
for the filter dropdown (`app.metrics_db.list_by_adom_names()`) is derived
from whatever `by_adom.*` metric_points already exist — no separate "list
ADOMs" call to any source.

`infra` is a nested LIST (from 4thealth-plus schema_version 2 and 4tlog
onward), one entry per FortiManager/FortiAnalyzer/FortiAuthenticator
target: `{role, label, hostname, cpu, mem, disk_pct (4thealth-plus) or
disk_used_pct (4tlog), ha_role, status, last_updated}`. Read directly from
each enabled source's latest snapshot (`app.domains.get_infra_devices()`)
rather than through metric_points — it's a per-device list, not a single
fleet scalar, so there's nothing to extract a scalar metric_key from; this
card shows "now" status only, no delta or history. `get_infra_devices()`
merges every enabled `4thealth`/`4tlog` source's `infra` list into one,
normalizing 4tlog's `disk_used_pct` field name to 4thealth-plus's own
`disk_pct` and 4tlog's `"yellow"` status value to `"amber"` (4thealth-plus
and this card's own CSS both use "amber" for that tier), so the merged
list has one consistent shape regardless of source. Rendered as an
**Infrastructure card** on the Availability & Change domain detail page
only (`/domain/availability`) — every other domain page has no infra card.

`psirt` is a nested object (from 4thealth-plus schema_version 2 onward;
absent on schema_version 1 sources) containing fleet-wide PSIRT advisory
exposure, computed from that app's persisted advisory/assessment history
(`app/psirt_store.py`) rather than a per-poll sweep:

```json
{
  "psirt": {
    "open_advisories": 3,
    "devices_critical": 5,
    "devices_high": 2,
    "devices_medium": 0,
    "devices_critical_mitigated": 1.0,
    "kev_exposed_devices": 2,
    "top_advisory": {"advisory_id": "FG-IR-24-001", "cvss": 9.8, "kev": true, "devices": 5},
    "mean_days_to_remediate_90d": 12.5,
    "collected_at": "2026-09-10T00:00:00Z"
  }
}
```

- `open_advisories` — advisories saved but not yet closed.
- `devices_critical` / `devices_high` / `devices_medium` — device counts affected by open advisories in that priority band. A device counts here whether or not a workaround is applied — this is never silently reduced for mitigation.
- `devices_critical_mitigated` — critical-band devices with a confirmed workaround in place, counted **at half weight** (e.g. `1.0` = 2 devices). A separate field on purpose, so it can never be used to silently shrink `devices_critical`.
- `kev_exposed_devices` — distinct devices affected by any open advisory listed in the CISA KEV catalog.
- `top_advisory` — the single highest-priority open advisory (ties broken by CVSS, then device count); `null` if none are open.
- `mean_days_to_remediate_90d` — mean days between an advisory being first saved and closed, over closures in the trailing 90 days; `null` if none closed in that window.
- `collected_at` — ISO 8601 timestamp of when the source computed this rollup (computed fresh on each request, not cached, so it tracks the poll time rather than a sweep cadence).

`extract_all()` (`app/metric_extract.py`) flattens this into `psirt.open_advisories`, `psirt.devices_critical`, `psirt.devices_high`, `psirt.devices_medium`, `psirt.devices_critical_mitigated`, `psirt.kev_exposed_devices`, and `psirt.mean_days_to_remediate_90d` metric_points; `psirt` and `psirt.top_advisory` themselves are composite objects with no single scalar and always extract to nothing. The **Vulnerability** domain score (`app/domains.py`) is built entirely from these fields: start at 100, subtract 20 per device that is either KEV-listed or in the critical band (capped at 60), 3 per high-band device (capped at 30), and 1 per medium-band device (capped at 10) — then floor the grade to **F** whenever `kev_exposed_devices > 0`, regardless of the numeric score, since a single actively-tracked KEV exposure is an escalation a passing letter grade should never mask.

`ai_usage_by_feature` is an optional nested object (present only if AI usage
data is available, keyed by feature name) containing per-feature cost and usage
breakdown:

```json
{
  "ai_usage_by_feature": {
    "device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0},
    "rule_analysis": {"calls": 3, "cost_usd": 0.15, "failures": 1}
  }
}
```

**Sweep status and collection timestamps** — freshness tracking for async rollup jobs:
- `device_sweep_status` — current status of the device-sweep job (opaque string value from the companion 4thealth+ API; 4tExecutive does not validate or enforce a specific enum of status values)
- `hygiene_sweep_status` — current status of the hygiene-sweep job (opaque string value from the companion 4thealth+ API; 4tExecutive does not validate or enforce a specific enum of status values)
- `device_sweep_collected_at` — ISO 8601 timestamp of the latest completed device sweep (collected data freshness for version_compliance_pct, pending_config_diff_count, firewall counts, etc.; see `_FIELD_GROUP_FRESHNESS` in `app/widgets.py` for which widgets use this timestamp and their staleness thresholds)
- `hygiene_sweep_collected_at` — ISO 8601 timestamp of the latest completed hygiene sweep (collected data freshness for hygiene_score and rule_hygiene)
- `rule_count_collected_at` — ISO 8601 timestamp of the latest rule count collection (freshness for rule_count_total)

These `*_collected_at` timestamps reflect when each respective job last completed a full rollup and collected its data; widgets check these to determine staleness (see `_FIELD_GROUP_FRESHNESS` in `app/widgets.py`).

`schema_version` — optional integer field indicating the contract version of the
payload structure. Sources may omit this field (default assumes latest version
compatible with 4tExecutive). Included for future API evolution scenarios.
4thealth-plus is on `schema_version: 2` as of the `psirt` field's introduction —
the bump is additive (every `1` key is still present), so 4tExecutive accepts
either version and simply has no `psirt` data to show from a `1` source.

### schema_version 2: `freshness` map and optional `details` lists

4thealth-plus and 4tlog are concurrently moving toward another additive
`schema_version: 2` change: a top-level `freshness` field-group timestamp
map, kept **alongside** every existing v1 `*_collected_at`/nested
`collected_at` key for at least one release, plus a handful of new
**optional** `details` lists inside existing rollups. 4tExecutive accepts
both schema versions for both changes — nothing about them is required, and
neither introduces a breaking change to a `schema_version: 1` payload.

**`freshness` map** (staleness only): when `schema_version == 2` and a
top-level `freshness` object is present, `app/widgets.py`'s
`_freshness_collected_at()` prefers `freshness[<field-group key>]` over the
payload's own v1 timestamp field for that group, trying the key as-given
first and then with any `_collected_at` suffix stripped (some sibling
payloads key the map by the bare group name). If `freshness` is
missing/not-a-dict, or the specific key isn't present in it, 4tExecutive
falls back to exactly the v1 lookup — see
[architecture.md](architecture.md#schema-v1v2-freshness-acceptance) for the
full fallback chain. Example v2 payload shape:

```json
{
  "schema_version": 2,
  "device_sweep_collected_at": "2026-09-10T09:00:00Z",
  "freshness": {
    "device_sweep_collected_at": "2026-09-10T09:00:00Z",
    "hygiene_sweep": "2026-09-10T08:30:00Z"
  }
}
```

**Optional `details` lists** (device-level drill-down, feeds `/devices` and
each domain's "Devices" section — see `app/devices.py`): every list below is
treated as optional/absent-safe — a missing list is simply not shown, never
synthesized from an aggregate count.

| Rollup                          | Optional list field                       | Row shape (per entry) |
|----------------------------------|--------------------------------------------|------------------------|
| `device_review`                 | `details`                                  | `{device, adom, failed_checks: [key], worst_severity}` |
| `rule_hygiene`                   | `details`                                  | `{package, adom, findings}` |
| `version_breakdown` (per-version entry) | `devices` (EOL versions only)      | `{device, adom, version}` |
| top-level (4tlog)                | `silent_devices`                           | `{devid, devname, last_log_at}` |
| `psirt.top_advisory`             | `devices`                                  | `{device, adom, version, workaround_applied}` |

None of these lists affect scoring or any existing scalar/rollup field —
they're purely additive, read-only drill-down data.

### PDF report generation — a correction from the original design doc

The design doc this repo's Weekly Executive Brief was built from assumed
4thealth-plus does headless-Chrome PDF conversion for its own `"pdf"` report
format. **It does not** — 4thealth-plus's `"pdf"` format is actually a
styled HTML attachment (the format name is a mislabel in that codebase, not
a real conversion step). 4tExecutive's own weekly brief (`app/brief_pdf.py`)
implements *real* PDF generation itself, independently of that repo: it
shells out to a headless Chrome/Chromium binary (`CHROME_BINARY` env var, or
a fixed fallback search list) via `subprocess`, and gracefully skips the PDF
attachment (the HTML email still sends) when no such binary is found on the
host. If you're comparing behavior against 4thealth-plus's "pdf" report
expecting a rendered PDF there, you won't find one — that gap is what this
repo's `brief_pdf.py` was built to actually close for 4tExecutive's own
brief.

Along with `version_breakdown`, `device_review`, `rule_hygiene`, `psirt`, `change_control`, `lifecycle`, `by_adom`, `infra`, and `ai_usage_24h`,
these nested and collection-tracking fields form the complete contract; every other
field above is a scalar.

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
