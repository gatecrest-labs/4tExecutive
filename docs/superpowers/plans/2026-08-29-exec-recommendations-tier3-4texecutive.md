# Exec Recommendations Tier 3 — 4tExecutive Widget Consumption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume 4tlog's new `/external/api/executive/summary` payload (rec 3.1–3.3) — turn
`log_volume_trend` into a real trended line-chart widget and add a new Silent Devices widget —
so 4tExecutive's two long-dormant 4tlog widget slots become real.

**Architecture:** `log_volume_trend`'s catalog entry gets a `chart_type: "line"` and its `field`
renamed to the new payload key `log_volume_events_per_sec` — it needs no special-casing in
`get_widget_series` because a plain scalar field already falls through that function's generic
`else` branch (the same path `4thealth.pending_config_diffs` and other flat scalars use). A new
`4tlog.silent_devices` catalog entry follows Tier 2's `device_review_posture` pattern exactly: a
bar-chart special case in `get_widget_series` with manually-assigned RAG (red when any device is
silent).

**Tech Stack:** Flask, Jinja2, SQLite (existing `metrics.db`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-exec-recommendations-tier3-4tlog-design.md`
(sections 2 and 7) — this plan implements design-doc section 7. The companion plan
`docs/superpowers/plans/2026-08-29-exec-recommendations-tier3.md` in the `4tlog` repo
(`/Users/alanw/code/github/web/4tlog`) implements the payload/backend side this plan reads from.

## Global Constraints

- 4tlog's payload changes are additive/renamed, not universally backward-compatible on one
  field: `log_volume_trend`'s old (never-implemented) key is replaced by
  `log_volume_events_per_sec`. This is safe because the old key was never populated by any real
  4tlog deployment (confirmed in the original recommendations doc, section 1.4) — there is no
  live payload shape to preserve compatibility with.
- Every new field is read defensively (`.get(...)`), never a bare `[...]` index — a polled 4tlog
  instance may not have shipped this work yet.
- Follows the Tier 1/2-established RAG/threshold/staleness conventions in `app/widgets.py` and
  `app/thresholds.py` — do not introduce a second styling mechanism.
- `pytest tests/ -v` and `ruff check app/ tests/` must pass before each commit.

---

## File Structure

- `app/widgets.py` (modify) — `4tlog.log_volume_trend` catalog entry (field rename +
  `chart_type`), new `4tlog.silent_devices` catalog entry, its `get_widget_series` bar-chart
  special case, a `_FIELD_GROUP_FRESHNESS` entry for both widgets, `default_layout()`'s
  conditional-inclusion gating.
- `docs/integrations.md` (modify) — document the new/renamed 4tlog fields.
- `tests/test_widgets.py`, `tests/test_dashboard_routes.py` (modify).

---

### Task 1: `log_volume_trend` becomes a real line-chart widget

**Files:**
- Modify: `app/widgets.py`
- Modify: `tests/test_widgets.py`

**Interfaces:**
- Changes: `WIDGET_CATALOG["4tlog.log_volume_trend"]["field"]` from `"log_volume_trend"` to
  `"log_volume_events_per_sec"`; gains `"chart_type": "line"`.
- Changes: `_FIELD_GROUP_FRESHNESS` gains `"4tlog.log_volume_trend": ("log_stats_collected_at", 10)`
  — 4tlog's `LOG_STATS_POLL_INTERVAL` default is 5 minutes, so 2x that is 10 minutes (matching
  the existing "2x expected refresh interval" convention documented at the top of
  `_FIELD_GROUP_FRESHNESS`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_catalog_log_volume_trend_is_a_line_chart_on_new_field():
    entry = WIDGET_CATALOG["4tlog.log_volume_trend"]
    assert entry["chart_type"] == "line"
    assert entry["field"] == "log_volume_events_per_sec"


def test_get_widget_series_log_volume_trend_charts_the_new_field():
    write_snapshot("s1", "summary", {"log_volume_events_per_sec": 812.4}, _iso(600))
    write_snapshot("s1", "summary", {"log_volume_events_per_sec": 950.0}, _iso(5))
    widget = {"type": "4tlog.log_volume_trend", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert [v for _, v in result["points"]] == [812.4, 950.0]
    assert result["delta"] == pytest.approx(137.6)


def test_get_widget_series_log_volume_trend_stale_from_log_stats_collected_at():
    old_ts = (datetime.now(UTC) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1", "summary",
        {"log_volume_events_per_sec": 100.0, "log_stats_collected_at": old_ts},
        "2026-08-29T09:00:00Z",
    )
    widget = {"type": "4tlog.log_volume_trend", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["stale"] is True
```

(These use this test file's existing `write_snapshot`/`_iso` helpers and `datetime`/`UTC`/
`timedelta` imports — confirm they're already imported at the top of `tests/test_widgets.py`
from the Tier 2 work; if `pytest` isn't already imported there, add `import pytest` for
`pytest.approx`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k log_volume_trend -v`
Expected: FAIL — catalog entry has no `chart_type`, so `get_widget_series` falls back to
`get_widget_value` and returns a flat value, not `{"points": [...], ...}`.

- [ ] **Step 3: Update the catalog entry**

In `app/widgets.py`, replace:

```python
    "4tlog.log_volume_trend": {
        "label": "Log Volume Trend",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "log_volume_trend",
        "default_size": "2x2",
    },
```

with:

```python
    "4tlog.log_volume_trend": {
        "label": "Log Volume Trend",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "log_volume_events_per_sec",
        "default_size": "2x2",
        "chart_type": "line",
    },
```

- [ ] **Step 4: Add the freshness entry**

In `_FIELD_GROUP_FRESHNESS`, add after the `"4thealth.device_review_posture"` line:

```python
    "4tlog.log_volume_trend": ("log_stats_collected_at", 10),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -k log_volume_trend -v`
Expected: PASS. No special-casing was needed in `get_widget_series` — a widget with a
`chart_type: "line"` and no matching `elif` branch in the special-case chain already falls
through to the generic `else: points = [(h["collected_at"], h["value"].get(entry["field"])) for h in history]` path.

- [ ] **Step 6: Run the full widgets test file**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS, no regressions (in particular, confirm no other test asserted the old
`log_volume_trend` field name).

- [ ] **Step 7: Commit**

```bash
git add app/widgets.py tests/test_widgets.py
git commit -m "Chart 4tlog log volume as a real trend line on the new payload field"
```

---

### Task 2: Silent Devices widget

**Files:**
- Modify: `app/widgets.py`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: new catalog entry `4tlog.silent_devices` (`chart_type: "bar"`, `default_size: "1x1"`).
- `get_widget_series` special case reads `latest["value"].get("devices_logging")` and
  `.get("devices_silent")` (flat top-level ints, not nested), returns
  `{"chart": "bar", "data": {"Logging": n, "Silent": n}, "collected_at": ...}`, `rag` red when
  `devices_silent > 0`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_catalog_has_silent_devices_widget():
    entry = WIDGET_CATALOG["4tlog.silent_devices"]
    assert entry["source_system"] == "4tlog"
    assert entry["chart_type"] == "bar"
    assert entry["default_size"] == "1x1"


def test_get_widget_series_silent_devices_computes_bar_and_red_rag():
    write_snapshot(
        "s1", "summary",
        {"devices_logging": 38, "devices_silent": 2, "silent_device_threshold_minutes": 60},
        "2026-08-29T09:00:00Z",
    )
    widget = {"type": "4tlog.silent_devices", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"Logging": 38, "Silent": 2}
    assert result["rag"] == "red"
    assert result["collected_at"] == "2026-08-29T09:00:00Z"


def test_get_widget_series_silent_devices_green_when_none_silent():
    write_snapshot(
        "s1", "summary", {"devices_logging": 40, "devices_silent": 0}, "2026-08-29T09:00:00Z",
    )
    widget = {"type": "4tlog.silent_devices", "source_instance": "s1"}

    assert get_widget_series(widget, "30d")["rag"] == "green"


def test_get_widget_series_silent_devices_no_data_when_absent():
    write_snapshot("s1", "summary", {"faz_targets_total": 3}, "2026-08-29T09:00:00Z")
    widget = {"type": "4tlog.silent_devices", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert "rag" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k silent_devices -v`
Expected: FAIL — `KeyError: '4tlog.silent_devices'`.

- [ ] **Step 3: Add the catalog entry**

In `app/widgets.py`, add after `"4tlog.log_volume_trend"`:

```python
    "4tlog.silent_devices": {
        "label": "Silent Devices",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "devices_logging",
        "default_size": "1x1",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
```

(As with `device_review_posture` in Tier 2, this `rag` spec is a placeholder never actually
reached by `_rag_state` — it exists only so `get_thresholds` resolves non-`None` for this widget
type. The real RAG value is computed manually below and assigned directly.)

- [ ] **Step 4: Add the `get_widget_series` bar-chart special case**

In `get_widget_series`'s `if chart_type == "bar":` branch, add a case above the
`4thealth.device_review_posture` special-case (order doesn't matter functionally, but keeping
Tier 2's device-posture case first and this new one alongside it keeps the two "manual RAG,
returns directly" bar widgets together):

```python
        if widget_instance["type"] == "4tlog.silent_devices":
            devices_logging = latest["value"].get("devices_logging")
            devices_silent = latest["value"].get("devices_silent")
            if devices_logging is None and devices_silent is None:
                return _attach_rag(
                    widget_instance["type"], entry, _empty_bar(widget_instance["type"])
                )
            devices_logging = devices_logging or 0
            devices_silent = devices_silent or 0
            result = {
                "chart": "bar",
                "data": {"Logging": devices_logging, "Silent": devices_silent},
                "collected_at": latest["collected_at"],
            }
            result["rag"] = "red" if devices_silent > 0 else "green"
            return result
```

- [ ] **Step 5: Gate the widget out of `default_layout()` until a source has real data**

In `default_layout()`, extend the existing conditional-inclusion tuple:

```python
            elif widget_type in (
                "4thealth.device_review_posture",
                "4thealth.rule_hygiene",
                "4tlog.silent_devices",
            ):
```

(This reuses the existing branch's `latest["value"].get(entry["field"]) is None` check — for
`4tlog.silent_devices`, `entry["field"]` is `"devices_logging"`, so a 4tlog source that hasn't
shipped this work — where that key is absent — is skipped from the auto-generated default
layout, same as `device_review_posture`/`rule_hygiene` skip pre-Tier-2 4thealth+ sources. A user
who manually adds it to a saved layout still sees "No data yet" as normal.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS

- [ ] **Step 7: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_silent_devices_widget(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4tlog.silent_devices", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary", {"devices_logging": 38, "devices_silent": 2}, "2026-08-29T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Silent Devices" in response.data
    assert b"rag-red" in response.data
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_dashboard_routes.py -k silent_devices -v`
Expected: PASS immediately — this widget renders through the same bar-chart template branch
`4thealth.device_review_posture` already established in Tier 2 (`app/templates/dashboard.html`'s
`{% elif widget.data and widget.data.chart == 'bar' %}` block), so no template changes are
needed. If it fails, inspect the rendered response body to confirm which existing template
assumption (e.g. `top_failing_checks` always being iterable) this widget's `None`/absent value
violates, and fix that assumption defensively (e.g. `widget.data.top_failing_checks|default([])`)
rather than adding a new branch.

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/widgets.py tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add Silent Devices widget from 4tlog's logstats rollup"
```

---

### Task 3: Contract documentation

**Files:**
- Modify: `docs/integrations.md`

- [ ] **Step 1: Update the 4tlog section**

In `docs/integrations.md`, replace the existing `4tlog` widget table and add a worked example.
Replace:

```markdown
**`4tlog`**:

| JSON key            | Widget                  |
|-----------------------|--------------------------|
| `faz_health`          | FortiAnalyzer Health     |
| `log_volume_trend`    | Log Volume Trend         |
```

with:

```markdown
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
  `app/widgets.py`): stale past 10 minutes (2x 4tlog's default 5-minute logstats poll interval).
```

- [ ] **Step 2: Commit**

```bash
git add docs/integrations.md
git commit -m "Document Tier 3 4tlog payload fields in integrations.md"
```

---

### Task 4: Full-suite verification and manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS, zero failures.

- [ ] **Step 2: Run lint**

Run: `ruff check app/ tests/`
Expected: no errors. Fix any and re-run.

- [ ] **Step 3: Manual smoke check**

Start the app, log in, and confirm in a browser (against a 4tlog instance running the companion
plan, or by manually inserting a snapshot row with the new fields via the Python shell if no live
Tier 3 4tlog instance is available yet):

1. Log Volume Trend renders as a real line chart (not a raw string/empty tile), with a delta
   annotation.
2. Silent Devices widget shows a Logging/Silent bar split, red-bordered when
   `devices_silent > 0`, green otherwise.
3. Poll a 4tlog instance that has NOT deployed Tier 3 yet (or a saved snapshot from before this
   work) — dashboard renders unchanged, no crashes; Silent Devices does not appear in the
   auto-generated default layout for that source (still renders "No data yet" if a user manually
   added it to a saved layout).
4. Toggle dark mode — the new bar colors remain legible in both themes (reuses existing bar-chart
   styling, no new CSS expected).

- [ ] **Step 4: Report results to the user**

No commit for this task — verification only.

---

## Self-Review Notes

- **Spec coverage:** design doc §7's widget-consumption bullets map to Task 1 (log volume trend)
  and Task 2 (silent devices).
- **Type consistency:** `4tlog.silent_devices`'s field names (`devices_logging`,
  `devices_silent`) match exactly what the companion 4tlog plan's
  `app/routes/external_api_routes.py` (Task 7 there) puts in the payload.
- **Backward compatibility:** `log_volume_trend`'s field rename is a deliberate one-time break,
  justified in Global Constraints — there is no real deployment sending the old key today.
