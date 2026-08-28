# Exec Recommendations Tier 2 — Design

Date: 2026-08-28
Spec source: `docs/Exec-recommendations.md`, section 2 "Tier 2" (recs 2.1–2.7)
Repos: `4thealth-plus` (`/Users/alanw/code/github/ai/4thealth-plus`), `4tExecutive` (this repo)

## 1. Scope

Ships Tier 2 recs **2.1, 2.2, 2.4, 2.5, 2.6, 2.7** across both repos, plus a `schema_version`
field on the external executive-summary payload (per the doc's section 5 contract-discipline
note — this is the first payload-shape change since that note was written).

**2.3 (PSIRT exposure) is explicitly dropped from this spec.** Investigation found the doc's
premise wrong: PSIRT assessment (`app/psirt/engine.py::assess()`) is ad hoc only — triggered
per-advisory from a user-pasted email/file via an LLM extraction step. There is no advisory
catalog to sweep against, no persistence of past assessments, and no scheduler. Building
fleet-wide `psirt_critical_devices`/`psirt_high_devices` counts would require a new advisory
catalog, a persistence layer, and a new scheduled job — i.e. a new collector, which is exactly
what Tier 2's "no new collectors" premise rules out. This becomes a Tier 3 item once an
advisory catalog exists to build on.

4thealth+ and 4tExecutive changes ship as independent releases. All 4thealth+ payload changes
are additive/backward-compatible; nothing in 4tExecutive depends on a specific 4thealth+
release being live (missing fields degrade to "No data yet", the existing convention).

## 2. Payload contract (4thealth+ `/external/api/executive/summary`)

New/changed top-level fields:

```jsonc
{
  "schema_version": 1,

  "device_review": {
    "devices_reviewed": 42,
    "devices_with_failures": 7,
    "findings_by_severity": {"critical": 1, "high": 3, "medium": 9, "low": 4},
    "top_failing_checks": [{"check": "Default Admin Enabled", "count": 5}, ...],
    "collected_at": "2026-08-28T06:00:00Z"
  },

  "rule_hygiene": {
    "rule_findings_total": 118,
    "rule_findings_by_type": {
      "shadow": 4, "unhit": 60, "unlogged": 12, "expired": 8,
      "disabled": 20, "unnamed": 6, "unused_objects": 8
    },
    "collected_at": "2026-08-28T09:00:00Z"
  },

  "ai_usage_by_feature": {
    "device_review_summary": {"calls": 12, "cost_usd": 0.41, "failures": 0},
    "psirt_extract": {"calls": 3, "cost_usd": 0.09, "failures": 1}
  },

  "rule_count_total": 14203,

  "version_breakdown": {
    "7.4.5": {"count": 12, "eol": false},
    "6.4.2": {"count": 3, "eol": true}
  },

  "device_sweep_status": "ok",
  "hygiene_sweep_status": "ok",
  "device_sweep_collected_at": "2026-08-28T09:45:00Z",
  "hygiene_sweep_collected_at": "2026-08-28T09:00:00Z",
  "rule_count_collected_at": "2026-08-28T09:00:00Z",

  "status": "ok",
  "last_updated": "2026-08-28T09:45:00Z"
}
```

Notes:
- `schema_version` is a new top-level int, bumped on any future breaking change. This payload
  is version `1`.
- `status`/`last_updated` are kept as deprecated aliases of `device_sweep_status`/the newest
  `collected_at` across groups, for one release, so existing consumers don't break immediately.
  Removed in a later cleanup once consumers can gate on `schema_version`.
- `rule_count_total` keeps its existing flat scalar shape — only its cadence and source change
  (see section 5).
- `firewall_managed_count` stays an alias of `firewalls_total` — unchanged, out of scope here
  (already addressed in Tier 1's widget merge on the 4tExecutive side).
- Missing/null fields follow the existing convention: absence means "not computed yet," never a
  crash on the consumer side.

## 3. Device Review rollup (4thealth+)

**Where it's computed:** `app/device_review_scheduler.py::_execute_job()` already builds the
full per-check row list (via `bulk_device_review_adom()`) before emailing it and discarding it.
Add an aggregation step there, before the rows are discarded, that produces and persists a
rollup.

**Severity mapping:** new static table (`app/device_review_severity.py`), one entry per
`device_review.CHECKS` key, hand-classified from the existing CIS-derived check descriptions
into `critical|high|medium|low`. Reviewed as part of implementation — not derived from the
description text at runtime.

**Aggregation:**
- `devices_reviewed` = count of distinct devices in the run's row set.
- `devices_with_failures` = count of distinct devices with ≥1 row whose `result` is not
  `PASS`/`INFO`.
- `findings_by_severity` = count of such rows, grouped via the severity table (a row's `check`
  display name maps back to its `CHECKS` key for lookup).
- `top_failing_checks` = the 3 check keys with the most non-PASS/INFO rows, `{check, count}`.

**Persistence:** `device_review_rollup.json`, atomic-written via the same `atomic_write_json`
helper used by `api_tokens.json`, holding a bounded history list (last 30 runs) in the same
shape as `device_review_jobs.json`'s existing `_append_run()` pattern:
`{ran_at, devices_reviewed, devices_with_failures, findings_by_severity, top_failing_checks}`.

**Freshness tradeoff (explicit, not a defect):** this rollup's cadence is whatever
`device_review_scheduler`'s per-ADOM cron jobs are configured for by the user — potentially
less frequent than the 15/60-min sweeps. `device_review.collected_at` reflects "last scheduled
review run." No new scheduler is introduced; this reuses the existing job on its existing
cadence.

## 4. Rule Hygiene rollup (4thealth+)

**Where it's computed:** inside `executive_summary_cache.py::_run_hygiene_sweep()`, which
already loops every policy package calling `hygiene.run_checks()`. Add a call to
`hygiene.find_unused_objects()` per package (reusing the `policies`/`addresses`/`addr_groups`/
`services`/`svc_groups` already fetched in that loop — no new API calls), and accumulate
per-check-type counts across all packages.

**Fields:** `rule_findings_total` (sum across all 6 `CHECKS` types + unused objects) and
`rule_findings_by_type` (`shadow`, `unhit`, `unlogged`, `expired`, `disabled`, `unnamed`,
`unused_objects`) — fleet-wide totals only, no per-device breakdown (findings are inherently
per-policy-package, which can span multiple devices; per-device attribution is out of scope).

**Persistence:** `hygiene_rollup.json`, same pattern as section 3 — bounded history so
4tExecutive can trend `rule_findings_total` over time.

## 5. Rule count cadence fix (4thealth+)

Investigation found the doc's "compute from 30-min caches" premise doesn't match the code — no
existing 15/30-min cache fetches policy/rule data. However, `_run_hygiene_sweep()` (60-min
default cadence) already accumulates `total_policies` as a byproduct of its `find_unused_objects`
loop (structurally identical to `summary_job.py`'s `rules_total`) — it's just never stored.

**Correction found during plan-writing:** `summary_job.py`'s daily job is not solely an
executive-payload input — its `_run_job` also calls `app.summary_history.record_today()`, the
sole writer behind `app/routes/api_routes.py::summary_history()`, a live internal 4thealth+
route serving a 30-day firewalls/rules trend graph unrelated to the executive API. Deleting the
job would silently break that internal feature. It stays.

**Change:** store `total_policies` as a new `_store["rule_count_total"]` field inside
`_run_hygiene_sweep()`. The external API route reads it from there instead of
`summary_job.get_summary()`. `summary_job.py` is untouched — it keeps running daily, still
recording `summary_history.json` for the internal trend graph — only the *external payload's*
source for `rule_count_total` changes.

**Result:** the external payload's `rule_count_total` cadence goes from ~24h-stale (worst case,
just before the 01:00 run) to ~60min, with zero new API calls (reuses data the hygiene sweep
already fetches). The internal 30-day trend graph is unaffected.

## 6. Version EOL flagging (4thealth+)

Small static table (e.g. `app/version_eol.py`: `{"6.4.2": True, "6.4.14": True, ...}` or a
version-range rule set — implementation detail resolved during coding) shipped in code. The
`_version_breakdown()` route helper annotates each `version_breakdown` entry with `eol: bool`
looked up against the table. No FortiGuard/vendor API call — matches the "small static table"
scope from the doc.

## 7. AI usage attribution (4thealth+)

**Schema:** add nullable `feature TEXT`, `user TEXT` columns to the `ai_usage` table
(`app/ai_usage.py`'s `_SCHEMA`). Migration is a guarded `ALTER TABLE ADD COLUMN`, checked via
`PRAGMA table_info` before altering so it's idempotent on every app start (matches the
single-SQLite-file, no-migration-framework reality of this codebase).

**Call sites:** every `narrate()` function in `app/llm/*_provider.py` that calls
`record_usage()` passes a static `feature` string identifying the calling code path (e.g.
`"device_review_summary"`, `"psirt_extract"`) and `user` from the Flask session where available
(`None` for background/scheduled jobs).

**Reads:** `usage_summary()` gains an optional `by_feature: bool` param returning
`{feature: {calls, cost_usd, failures}}`. Used by both the existing admin AI-usage rollup UI and
the new `ai_usage_by_feature` payload field (only present when `ai_enabled`).

**Retention:** prune rows older than 90 days (matching host-metrics' existing retention
discipline), via whichever mechanism host-metrics actually uses today (opportunistic prune-on-
write vs. a periodic job — confirmed and matched during implementation, not re-decided here).

## 8. 4tExecutive widgets

New `WIDGET_CATALOG` entries, following the Tier 1 pattern (RAG thresholds via
`app/thresholds.py`, special-cased nested-field handling in `get_widget_series` matching the
existing `ai_usage_24h`/`fleet_availability` precedent):

- **`4thealth.device_review_posture`** (2x2) — pass/fail stacked bar or donut + top-3 failing
  checks list, trended from the rollup history. RAG driven by `findings_by_severity.critical`
  (>0 → red) — the specific ratio-vs-count threshold shape is an implementation detail resolved
  during coding, consistent with Tier 1's `_rag_state` design.
- **`4thealth.rule_hygiene`** — total findings trend line (reuses Tier 1's existing delta
  annotation mechanism) + breakdown by type. **Informational, no RAG** — a rising rule-findings
  count isn't inherently bad in isolation (same reasoning the doc already applied to delta
  color-coding in Tier 1).
- **`4thealth.version_breakdown`** (existing widget) — bar segments for `eol: true` entries
  render in `--status-failed` red regardless of magnitude.
- **`4thealth.ai_usage_by_feature`** — optional add-on under the existing AI usage widget: a
  small breakdown table/list, only rendered when the field is present.
- **Existing RAG-eligible widgets** gain amber staleness coloring when their `collected_at` is
  older than 2× that field group's expected interval — extends Tier 1's posture-strip freshness
  convention to per-widget display.

## 9. Contract discipline

- Every new field documented in `docs/integrations.md` (4tExecutive side) with type, null
  semantics, and freshness — same discipline as Tier 1.
- `schema_version: 1` ships with this release; future breaking payload changes bump it.
- No crashes on malformed/missing new fields — same null-guard stance established in Tier 1 and
  the recent whole-branch-review fixes.

## 10. Explicitly out of scope

- 2.3 PSIRT exposure (see section 1) — deferred to a future Tier 3 spec once an advisory
  catalog/persistence/scheduler exist to build on.
- Per-device rule-hygiene attribution (packages span devices; fleet totals only, per section 4).
- Any 4tlog work (Tier 3, unrelated repo).
