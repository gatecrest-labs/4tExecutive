# 4tExecutive — Executive Visibility Review & Recommendations

Date: 2026-08-27
Scope: 4tExecutive (this repo), 4thealth+ (`ai/4thealth-plus`), 4tlog
Lens: a Director of Infrastructure & Networking using this as a daily driver, in a product positioned for other organizations. Recommendations are tiered by effort, with risk/posture framing included.

---

## 1. What the dashboard says today — and how it reads from the director's chair

Current widgets: hygiene score, version compliance %, pending config diffs, last backup status, firewalls online / firewalls managed, total rules, ADOM count, FortiOS version breakdown (bar), AI usage, host CPU/memory/disk, plus two 4tlog widgets (FAZ health, log volume trend).

The recent chart/time-range work gives it motion. But as an executive surface it has five structural problems:

**1. Numbers without judgment.** Every widget is a value with no target, threshold, or state. A hygiene score of 71 and a version compliance of 88% render identically to 94 and 100%. A director's first question — *"is anything wrong?"* — requires reading every widget and knowing the targets by heart. Nothing on the page is ever red.

**2. The richest posture data in the suite is invisible.** 4thealth+ runs a 26-check CIS-style device review (HA sync, weak VPN crypto, admin MFA, trusted hosts, default admin, SNMP config, logging config, …) and a 7-check rule hygiene engine (shadowed, unhit, unlogged, expired, disabled rules; unused objects), plus a deterministic PSIRT advisory assessment. **None of it reaches the executive API.** These are exactly the "how exposed are we?" answers a director is asked for — and the product already computes them.

**3. Redundant and misleading tiles.**
- `firewall_managed_count` is literally an alias of `firewalls_total` in the 4thealth+ endpoint (`external_api_routes.py:221`) — two widgets, one number.
- `last_backup_status` reports 4thealth+'s **own config-file backups**, not device config backups. At exec altitude that label reads as "our firewall configs are backed up," which the data does not say.
- Host CPU/memory/disk of the dashboard host is ops plumbing, not executive signal. It dilutes the page.

**4. The 4tlog side of the story doesn't exist.** The `faz_health` / `log_volume_trend` contract 4tExecutive documents is not implemented in 4tlog at all — no summary API, no token auth, no database, no history. Meanwhile 4tlog vendors the FortiAnalyzer API specs (`logview/logstats`, `eventmgmt` alert counts) that would answer the highest-value logging question a director has: *"which firewalls are not sending logs right now?"* A silent device is a blind spot during an incident — that is an executive metric.

**5. Data trust gaps under the hood.** In the 4thealth+ endpoint: one shared `status` and one `last_updated` cover fields whose real freshness ranges from live to 24 hours (`rule_count_total` refreshes daily at 01:00); a hygiene-sweep error masks a healthy device sweep. Caches are in-memory and per-Gunicorn-worker, so a poller can get different answers on consecutive polls, and a restart blanks the API. A product sold on "one pane of truth" needs the pane to be internally honest about staleness.

---

## 2. Recommendations

### Tier 1 — Presentation only (4tExecutive changes, data already flowing)

| # | Recommendation | Detail |
|---|---|---|
| 1.1 | **Threshold-driven RAG states on every widget** | Per-widget-type green/amber/red thresholds (configurable, shipped with sane defaults: e.g. version compliance ≥95 green, ≥85 amber; firewalls online = total green). Colored left border or status dot on the card. This single change converts the page from a report into a monitor. |
| 1.2 | **A posture strip at the top** | One row, above the range selector: overall state (worst-of RAG across widgets), count of widgets in amber/red, data-freshness indicator. The director's 5-second answer. |
| 1.3 | **Merge availability into one widget** | Replace *Firewalls Online* + *Firewalls Managed* with a single **Fleet Availability** widget: `online / total (percent)` with the line chart tracking the percentage. Drop the alias field from the layout. |
| 1.4 | **Relabel or demote the backup widget** | Rename to "App Config Backup" until real device-backup data exists (Tier 3.4), or move it off the default layout. Never let an exec surface imply fleet backups are covered when they aren't measured. |
| 1.5 | **Move host CPU/memory/disk to an Admin/System page** | Keep collecting; stop spending default-dashboard real estate on the dashboard's own container. |
| 1.6 | **Delta annotations on charts** | "▲ +3 vs. start of range" style deltas next to the current value on line-chart widgets. Trend direction is the exec's unit of change. |

### Tier 2 — New API fields from data 4thealth+ already computes (no new collectors)

| # | Recommendation | 4thealth+ work | 4tExecutive work |
|---|---|---|---|
| 2.1 | **Device Review (CIS) rollup** — the flagship posture widget | Aggregate the review engine's per-device results into fleet numbers: `devices_reviewed`, `devices_with_failures`, `findings_by_severity`, top 3 failing checks. Persist the rollup (results are currently only materialized inside scheduled email runs) and add to the executive payload. | New "Configuration Posture" widget (2x2): pass/fail donut or stacked bar + top failing checks list, trended. |
| 2.2 | **Rule hygiene rollup** | Sum the 7 hygiene checks + unused objects across packages into `rule_findings_total` and `rule_findings_by_type` (shadowed / unhit / unlogged / expired / disabled). | "Rule Hygiene" widget: total findings trend line + breakdown. Pairs with the existing raw rule count to answer *"is our policy base getting cleaner or dirtier?"* |
| 2.3 | **PSIRT exposure** | The PSIRT module already matches advisories to fleet versions. Expose `psirt_critical_devices`, `psirt_high_devices`, `top_advisory`. | "Vulnerability Exposure" widget — red when critical > 0. This is the widget a director shows *their* boss. |
| 2.4 | **Per-field freshness + honest status** | Add `collected_at` per field group (or a `freshness` map) to the payload; separate hygiene-sweep status from device-sweep status so one failure can't mask the other. | Show per-widget staleness ("as of" already exists — color it amber past 2× expected interval). |
| 2.5 | **AI usage attribution** | Add `feature` and `user` columns to `ai_usage.db` writes; expose `ai_usage_by_feature` and token/failure totals (the internal admin rollup already computes them). Add a prune/retention policy to match host-metrics' 90-day discipline. | Optional: AI usage widget gains a by-feature breakdown; cost-per-feature is what makes an AI line item defensible. |
| 2.6 | **Fix `rule_count_total` cadence** | Move the summary job from daily-at-01:00 to hourly (or compute from the 30-min caches). A 24-hour-stale number on a 15-minute dashboard undermines trust in everything else. | None. |
| 2.7 | **Version EOL flagging** | Annotate `version_breakdown` entries with an end-of-support flag from a small static table shipped with the app. | Bar chart colors EOL versions red. Version compliance becomes visually self-explanatory. |

### Tier 3 — New collectors / larger builds

| # | Recommendation | System | Detail |
|---|---|---|---|
| 3.1 | **Implement the 4tlog external summary API** | 4tlog | Bearer-token `/external/api/executive/summary` matching the 4thealth+ pattern (token store, enable toggle). Minimum viable payload from the existing health cache: `faz_targets_total`, `faz_targets_healthy`, `faz_disk_used_pct` (parse the string to numeric). This unblocks the two widgets 4tExecutive already ships. |
| 3.2 | **Silent-device detection** | 4tlog | Call FAZ `logview/logstats` (spec already vendored, never invoked) to get last-log-time and rate per device; expose `devices_logging`, `devices_silent`, `silent_device_threshold_minutes`. **Highest-value new metric in this entire list** — logging blind spots are invisible today in all three apps. Requires 4tlog to grow a small persistence layer (SQLite, mirroring 4tExecutive's `snapshots` pattern) so trends survive restarts. |
| 3.3 | **Log volume trend for real** | 4tlog | Same logstats collection, aggregated fleet-wide per interval, persisted. Replaces the aspirational `log_volume_trend` string with a numeric series 4tExecutive can chart natively. |
| 3.4 | **Device config backup age** | 4thealth+ | Query FortiManager revision history per device; expose `devices_backup_ok` / `devices_backup_stale` (>N days). Makes the backup widget honest (see 1.4). |
| 3.5 | **Certificate expiry** | 4thealth+ | Collect admin/SSL certs per device; expose `certs_expiring_30d`, `certs_expired`. Certificate surprises are a classic director embarrassment; cheap to collect from the API already in use. |
| 3.6 | ~~License / support contract expiry~~ | 4thealth+ | **Superseded by Tier 4 (4.2)** — see below. The premise here ("FortiCare/FortiGuard contract data via FMG") turned out to be wrong: FortiManager does not proxy FortiCare contract data at all. Kept as a struck-through row rather than deleted so old links/discussion referencing "3.6" still resolve to something. |
| 3.7 | **Composite Security Posture Score** | 4thealth+ (compute), 4tExecutive (display) | Weighted composite of hygiene score, device-review pass rate, PSIRT exposure, version compliance — with the weights visible and configurable. Only build this after 2.1–2.3 exist; a composite over missing inputs is theater. |
| 3.8 | **Cache persistence & consistency in 4thealth+** | 4thealth+ | Back the executive-summary caches with SQLite (or pin the sweeps to one worker) so restarts don't blank the API and multi-worker deployments answer consistently. A product requirement more than a feature. |

### Tier 4 — Device lifecycle: hardware end-of-support and paid support contracts

Investigation (2026-08-30) into whether 4thealth+ could answer *"which of our firewalls are running out of vendor support — and when?"* — a question distinct from 2.7's software-version EOL flagging, and one directors are asked at budget time every year.

| # | Recommendation | System | Detail |
|---|---|---|---|
| 4.1 | **Hardware end-of-support (model EOS) flagging** | 4thealth+ | Cheap and high-value: device model (`platform_str`) and serial are **already collected** in the same FortiManager `dvmdb` calls that supply version/conf_status today (`app/fmg_client.py`, consumed in `app/pending_status_cache.py:141-149`, `app/map_cache.py`, `app/versions_cache.py`). No new API integration needed — only a new static table. Follow the exact pattern `app/version_eol.py` already established for FortiOS software versions: a module citing Fortinet's published EOL/EOS-by-model schedule, a small lookup (`_EOL_MODELS: dict[str, date]` keyed by platform string), and an `is_hw_eol(model, as_of=None)` function that returns `False`/unknown for any model not in the table — absence must never render as a false "still supported," but it must also never render as a false "unsupported." Expose `devices_hw_eos_soon` (e.g. within 12 months) / `devices_hw_eos` counts in the executive payload; 4tExecutive gets a widget analogous to the version-compliance one. |
| 4.2 | **Paid support contract (FortiCare) expiry** | 4thealth+ | Genuinely new integration, **not** an FMG call — confirmed by reading `fmg_client.py` in full: no FortiCare/FortiGuard contract or license endpoint exists anywhere in the FMG API surface this app uses. This requires a separate FortiCare REST API client (its own base URL, its own credentials/API key, likely its own poll cadence since FortiCare rate-limits differ from FMG). Scope this as its own small collector before promising a date: confirm asset-registration mapping (FortiCare keys off serial number, which 4thealth+ already has per-device) and confirm what auth FortiCare's API actually requires for this deployment's account tier. Expose `contracts_expiring_90d`, `contracts_expired`, and ideally `support_level` per device. This is the item Fortinet resellers get asked about every renewal cycle — the "talks to procurement" widget from the old 3.6, now scoped correctly. |

Suggested order within Tier 4: **4.1 before 4.2** — 4.1 needs no new integration and can ship in the same wave as 2.7 (software version EOL); 4.2 needs its own discovery spike (does this org even have FortiCare API access enabled? what does the response schema actually look like?) before a real design spec is worth writing.

---

## 3. Suggested build order

1. **Tier 1 complete** (one 4tExecutive release) — RAG thresholds, posture strip, widget cleanup. Biggest perceived-value-per-effort in the list.
2. **2.1 + 2.3** (device review rollup, PSIRT exposure) — turns on the posture story with data that already exists.
3. **3.1 + 3.2** (4tlog API + silent devices) — brings the third system into the pane and adds the standout differentiator.
4. **2.2, 2.4–2.7, 4.1** as a hardening/depth wave — 4.1 (hardware EOS) rides along with 2.7 (software EOL) since both are static-table lookups over data already collected.
5. **3.4, 3.5, 3.8** as roadmap items.
6. **4.2** (FortiCare contract expiry) after a short discovery spike confirms API access and schema; **3.7** last, after 2.1–2.3 exist.

## 4. Tier 1 implementation notes

Decisions resolved here so an implementation session can go straight from this doc to a plan. These apply only to 4tExecutive — no 4thealth+/4tlog changes in Tier 1.

### 4.1 Where thresholds live

RAG thresholds are **defaults in `WIDGET_CATALOG`** (a new optional `rag` key per entry, next to `chart_type`), overridable by an optional `config/thresholds.json` keyed by widget type (same shape, merged over catalog defaults at read time, following the existing `config/*.json` + `atomic_write_json` pattern). No admin UI for editing thresholds in Tier 1 — the JSON file is the override mechanism; a UI is a later nicety.

```python
"4thealth.version_compliance": {
    ...,
    "rag": {"direction": "higher", "green": 95, "amber": 85},
},
```

### 4.2 RAG semantics per widget type

`direction` values and Tier 1 defaults:

| Widget | direction | green | amber | red |
|---|---|---|---|---|
| `version_compliance` | `higher` | ≥95 | ≥85 | <85 |
| `hygiene_score` | `higher` | ≥90 | ≥75 | <75 |
| `pending_config_diffs` | `lower` | 0 | ≤5 | >5 |
| `fleet_availability` (new, see 4.4) | `ratio` (online/total) | 100% | ≥90% | <90% |
| `last_backup_status` | `string_ok` (value starts with "ok"/"OK") | ok | — | anything else |

Everything else (`rule_count_total`, `adom_count`, `version_breakdown`, `ai_usage_24h`, host metrics, 4tlog widgets) is **informational — no `rag` key, no state**, rendered as today. The state is computed server-side in the data layer (`get_widget_series` result gains an optional `"rag": "green"|"amber"|"red"` key) and rendered as a colored card border/status dot via CSS classes on the widget card. A widget with a `rag` spec but no data renders neutral (missing data is a freshness problem, not a red).

### 4.3 Posture strip

One row rendered above the range selector, server-side, from the already-annotated widget list (no extra queries):

- **Overall pill**: worst-of across all RAG-evaluated widgets — `OK` (all green), `Attention` (any amber), `Critical` (any red).
- **Counts**: "N critical · M attention" when nonzero.
- **Freshness**: the stalest `collected_at` among displayed widgets, shown as "oldest data: X min ago"; amber-tinted when older than 2× the longest source poll interval.
- Each amber/red count links to the first offending widget via a fragment anchor (`id` per widget card) — cheap with server rendering, no JS.

### 4.4 Widget merge and backward compatibility (rec 1.3)

- Add a new catalog entry `4thealth.fleet_availability` (`chart_type: "line"`, charting the online/total percentage; the card headline shows `online / total (pct%)`). Data layer computes it from `firewall_online_count` + `firewalls_total` in the same snapshot; if either is missing, "No data yet".
- `4thealth.firewall_online_count` and `4thealth.firewall_managed_count` **stay in the catalog** so saved layouts keep rendering, but are **removed from `default_layout()`**, replaced by the new entry. No migration of saved layouts.

### 4.5 Backup widget (rec 1.4)

Label change only: "Last Backup Status" → "App Config Backup" in the catalog. Stays on the default layout with the `string_ok` RAG mapping (a failing app-config backup is still worth a red). Revisit placement when 3.4 (device backup age) lands.

### 4.6 Host metrics (rec 1.5)

`4texecutive.cpu_percent` / `memory_percent` / `disk_percent` are removed from `default_layout()` (collection via `poll_self()` continues untouched). They render instead in a small "System" section on the existing Admin page, reusing the same widget card + chart macros. Saved layouts that include them still render on the dashboard — same back-compat stance as 4.4.

### 4.7 Delta annotations (rec 1.6)

Computed in `get_widget_series` for line charts with ≥2 points: `delta = last - first` over the selected range, returned as a new optional `"delta"` key. Rendered next to the current value as "▲ +3" / "▼ −2" / "— 0" with muted styling; no color-coding the delta itself (direction ≠ goodness for most metrics — a rising rule count isn't inherently red).

## 5. Contract discipline (applies to every tier)

- Every new field lands in `docs/integrations.md` with type, null semantics, and freshness — the "missing key ⇒ No data yet" convention already in place holds up well; keep it.
- Version the executive payload (a `schema_version` field) before third parties integrate.
- 4tExecutive should never crash on a malformed field (the recent null/non-numeric guards set the right precedent — extend that stance to all new fields).
