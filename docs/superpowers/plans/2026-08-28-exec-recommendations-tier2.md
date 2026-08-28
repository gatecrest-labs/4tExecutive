# Exec Recommendations Tier 2 (4tExecutive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume the new Tier 2 fields from 4thealth+'s executive-summary payload —
`device_review`, `rule_hygiene`, `ai_usage_by_feature`, EOL-annotated `version_breakdown`, and
per-field-group freshness — as new/updated dashboard widgets.

**Architecture:** New `WIDGET_CATALOG` entries following the Tier 1 pattern (RAG thresholds via
`app/thresholds.py`, special-cased nested-field handling in `get_widget_series` matching the
existing `ai_usage_24h`/`fleet_availability` precedent). All new fields degrade to "No data yet"
when a polled 4thealth+ instance hasn't shipped Tier 2 yet — no coupling to a specific 4thealth+
release (per the design doc's independent-release decision).

**Tech Stack:** Flask, Jinja2, SQLite (existing `metrics.db`), pytest.

**Spec:** `docs/Exec-recommendations.md` (section 2 "Tier 2") and
`docs/superpowers/specs/2026-08-28-exec-recommendations-tier2-design.md` (section 8 "4tExecutive
widgets", plus sections 2/9 for the payload shape this plan consumes) — this plan implements
design-doc section 8. The companion plan
`docs/superpowers/plans/2026-08-28-exec-recommendations-tier2.md` in the `4thealth-plus` repo
implements the payload/backend side this plan reads from.

## Global Constraints

- 4thealth+'s Tier 2 payload changes are additive — every new field must be read defensively
  (`.get(...)`, never a bare `[...]` index) since a polled source may not have shipped Tier 2
  yet, or may be mid-rollout with only some fields present.
- `version_breakdown`'s per-entry shape changes from `int` to `{count, eol}` in 4thealth+ Tier 2
  — this is the one field that is NOT shape-backward-compatible. The widget code must handle
  BOTH shapes (old flat int, new `{count, eol}` dict) since 4tExecutive polls 4thealth+ instances
  independently and some may not have upgraded yet.
- Follows the Tier 1-established RAG/threshold/delta/staleness conventions in `app/widgets.py`
  and `app/thresholds.py` — do not introduce a second styling mechanism.
- Every new widget field keeps the "missing key ⇒ No data yet" convention.
- `pytest tests/ -v` and this repo's linter must pass before each commit.

---

## File Structure

- `app/widgets.py` (modify) — three new `WIDGET_CATALOG` entries
  (`4thealth.device_review_posture`, `4thealth.rule_hygiene`, `4thealth.ai_usage_by_feature`);
  `get_widget_series` special-cases for all three (nested-field extraction, same pattern as
  `fleet_availability`/`ai_usage_24h`); `version_breakdown`'s bar-chart branch updated to handle
  both the old flat-int and new `{count, eol}` shapes; per-widget staleness helper reading the
  new per-field-group `collected_at` values.
- `app/templates/dashboard.html` (modify) — bar-chart EOL coloring, a small breakdown-table
  block for `rule_hygiene`/`device_review_posture`, staleness CSS class on the widget card.
- `app/templates/_charts.html` (modify) — `bar_chart` macro gains an optional per-bar highlight
  set (for EOL red bars).
- `app/static/css/app.css` (modify) — `.widget-stale` style, reusing `--status-amber`.
- `docs/integrations.md` (modify) — document every new field per Tier 1's established contract
  discipline.
- `tests/test_widgets.py`, `tests/test_dashboard_routes.py` (modify).

---

### Task 1: `version_breakdown` EOL coloring (handles both payload shapes)

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/_charts.html`
- Modify: `app/templates/dashboard.html`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Changes: `get_widget_series` for `"4thealth.version_breakdown"` now returns `{"chart": "bar",
  "data": {version: count}, "eol_versions": [version, ...], "collected_at": ...}` instead of
  passing the raw snapshot value straight through.
- Changes: `bar_chart(data, highlight=None)` macro — bars whose label is in `highlight` render
  in `var(--status-failed)` instead of `var(--accent)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_get_widget_series_version_breakdown_handles_new_eol_shape():
    write_snapshot(
        "s1", "summary",
        {"version_breakdown": {"7.4.5": {"count": 12, "eol": False}, "6.4.2": {"count": 3, "eol": True}}},
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"7.4.5": 12, "6.4.2": 3}
    assert result["eol_versions"] == ["6.4.2"]


def test_get_widget_series_version_breakdown_handles_old_flat_shape():
    write_snapshot(
        "s1", "summary", {"version_breakdown": {"7.4.5": 12, "6.4.2": 3}}, "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"7.4.5": 12, "6.4.2": 3}
    assert result["eol_versions"] == []


def test_get_widget_series_version_breakdown_empty_when_no_data():
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert result["eol_versions"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k version_breakdown -v`
Expected: FAIL — current bar branch returns the raw dict directly under `"data"`, with no
`"eol_versions"` key, and would return `{"7.4.5": {"count": 12, "eol": False}, ...}` unchanged
for the new-shape test.

- [ ] **Step 3: Write the implementation**

In `app/widgets.py`, in `get_widget_series`'s `if chart_type == "bar":` branch, replace the
generic `"data": latest["value"].get(entry["field"]) or {}` handling with a special case for
`4thealth.version_breakdown`:

```python
    if chart_type == "bar":
        latest = get_latest(source_id, entry["metric_type"])
        if latest is None:
            empty = {"chart": "bar", "data": {}, "collected_at": None}
            if widget_instance["type"] == "4thealth.version_breakdown":
                empty["eol_versions"] = []
            return _attach_rag(widget_instance["type"], entry, empty)

        raw = latest["value"].get(entry["field"]) or {}
        if widget_instance["type"] == "4thealth.version_breakdown":
            data = {}
            eol_versions = []
            for version, entry_value in raw.items():
                if isinstance(entry_value, dict):
                    data[version] = entry_value.get("count")
                    if entry_value.get("eol"):
                        eol_versions.append(version)
                else:
                    data[version] = entry_value
            return _attach_rag(
                widget_instance["type"],
                entry,
                {"chart": "bar", "data": data, "eol_versions": eol_versions, "collected_at": latest["collected_at"]},
            )

        return _attach_rag(
            widget_instance["type"],
            entry,
            {"chart": "bar", "data": raw, "collected_at": latest["collected_at"]},
        )
```

(This replaces the existing `if chart_type == "bar":` block in full.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -k version_breakdown -v`
Expected: PASS

- [ ] **Step 5: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_colors_eol_version_bars_red(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.version_breakdown", "source_instance": "s1", "size": "2x2", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary",
        {"version_breakdown": {"7.4.5": {"count": 12, "eol": False}, "6.4.2": {"count": 3, "eol": True}}},
        "2026-08-28T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"var(--status-failed)" in response.data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py -k eol_version_bars -v`
Expected: FAIL — bar_chart macro has no highlight/coloring logic yet.

- [ ] **Step 7: Update the bar_chart macro and template call site**

In `app/templates/_charts.html`, update `bar_chart`:

```html
{% macro bar_chart(data, highlight=[]) %}
{% set count = data | length %}
{% set max_v = data.values() | max %}
<svg class="chart-svg chart-bar" viewBox="0 0 240 80" preserveAspectRatio="none">
  {% for version, value in data.items() %}
  {% set bar_w = 240 / count %}
  {% set bar_h = (value / max_v) * 55 if max_v else 0 %}
  <rect x="{{ '%.2f' | format(loop.index0 * bar_w + 4) }}" y="{{ '%.2f' | format(70 - bar_h) }}" width="{{ '%.2f' | format(bar_w - 8) }}" height="{{ '%.2f' | format(bar_h) }}" fill="{{ 'var(--status-failed)' if version in highlight else 'var(--accent)' }}" />
  <text x="{{ '%.2f' | format(loop.index0 * bar_w + bar_w / 2) }}" y="{{ '%.2f' | format(70 - bar_h - 3) }}" text-anchor="middle" class="chart-bar-count">{{ value }}</text>
  <text x="{{ '%.2f' | format(loop.index0 * bar_w + bar_w / 2) }}" y="78" text-anchor="middle" class="chart-bar-label">{{ version }}</text>
  {% endfor %}
</svg>
{% endmacro %}
```

In `app/templates/dashboard.html`, update the bar-chart call site:

```html
      {% elif widget.data and widget.data.chart == 'bar' %}
        {% if widget.data.data %}
          {{ charts.bar_chart(widget.data.data, widget.data.eol_versions|default([])) }}
          <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
        {% else %}
          <p class="widget-empty">No data yet</p>
        {% endif %}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/widgets.py app/templates/_charts.html app/templates/dashboard.html tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Color EOL FortiOS versions red on the version breakdown widget"
```

---

### Task 2: Configuration Posture widget (device review rollup)

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/dashboard.html`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: new catalog entry `4thealth.device_review_posture` (`chart_type: "bar"`,
  `default_size: "2x2"`).
- `get_widget_series` special case reads `latest["value"].get("device_review")` (a nested dict
  or `None`), returns `{"chart": "bar", "data": {"Passing": n, "Failing": n},
  "top_failing_checks": [...], "collected_at": ...}`, RAG driven by
  `findings_by_severity.critical`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_catalog_has_device_review_posture_widget():
    entry = WIDGET_CATALOG["4thealth.device_review_posture"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "bar"
    assert entry["default_size"] == "2x2"


def test_get_widget_series_device_review_posture_computes_pass_fail_and_rag():
    write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 42,
                "devices_with_failures": 7,
                "findings_by_severity": {"critical": 1, "high": 3, "medium": 9, "low": 4},
                "top_failing_checks": [{"check": "default_admin", "count": 5}],
                "collected_at": "2026-08-28T06:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"Passing": 35, "Failing": 7}
    assert result["top_failing_checks"] == [{"check": "default_admin", "count": 5}]
    assert result["collected_at"] == "2026-08-28T06:00:00Z"
    assert result["rag"] == "red"


def test_get_widget_series_device_review_posture_green_when_no_critical_findings():
    write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 10, "devices_with_failures": 0,
                "findings_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "top_failing_checks": [], "collected_at": "2026-08-28T06:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    assert get_widget_series(widget, "30d")["rag"] == "green"


def test_get_widget_series_device_review_posture_no_data_when_rollup_absent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert "rag" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k device_review_posture -v`
Expected: FAIL — `KeyError: '4thealth.device_review_posture'`.

- [ ] **Step 3: Write the implementation**

Add the catalog entry to `app/widgets.py`, after `4thealth.version_breakdown`:

```python
    "4thealth.device_review_posture": {
        "label": "Configuration Posture",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "device_review",
        "default_size": "2x2",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
```

(`rag` here is a placeholder threshold spec never actually reached by `_rag_state` for this
widget — the real RAG value is computed manually below and assigned directly, bypassing
`_attach_rag`'s numeric classification. Keeping a `rag` key present is what makes
`get_thresholds` resolve non-`None` for this widget type, which is required for the "eligible
for a `rag` key" contract the posture strip and per-widget staleness rely on; the specific
green/amber numbers are unused since this widget's RAG is set explicitly, not via
`_rag_state`.)

In `get_widget_series`'s `if chart_type == "bar":` branch (from Task 1), add a case above the
`version_breakdown` special-case:

```python
        if widget_instance["type"] == "4thealth.device_review_posture":
            device_review = latest["value"].get("device_review")
            if not device_review:
                return _attach_rag(
                    widget_instance["type"], entry,
                    {"chart": "bar", "data": {}, "top_failing_checks": [], "collected_at": None},
                )
            reviewed = device_review.get("devices_reviewed") or 0
            failing = device_review.get("devices_with_failures") or 0
            result = {
                "chart": "bar",
                "data": {"Passing": reviewed - failing, "Failing": failing},
                "top_failing_checks": device_review.get("top_failing_checks") or [],
                "collected_at": device_review.get("collected_at"),
            }
            critical = (device_review.get("findings_by_severity") or {}).get("critical") or 0
            result["rag"] = "red" if critical > 0 else "green"
            return result
```

(Note this branch returns directly rather than through `_attach_rag`, since RAG here is a
manual critical-count check, not the generic `_rag_state` numeric classifier — `_attach_rag`
would try to classify `result["value"]`, which doesn't exist on a bar-chart result, and no-op;
returning the dict with `"rag"` already set achieves the same visible effect without fighting
that helper.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_device_review_posture_widget(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.device_review_posture", "source_instance": "s1", "size": "2x2", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 42, "devices_with_failures": 7,
                "findings_by_severity": {"critical": 1, "high": 3, "medium": 9, "low": 4},
                "top_failing_checks": [{"check": "default_admin", "count": 5}],
                "collected_at": "2026-08-28T06:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Configuration Posture" in response.data
    assert b"default_admin" in response.data
    assert b"rag-red" in response.data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py -k device_review_posture -v`
Expected: FAIL — `top_failing_checks` isn't rendered anywhere in the template yet.

- [ ] **Step 7: Update the template**

In `app/templates/dashboard.html`, inside the bar-chart branch, add a failing-checks list after
the chart:

```html
      {% elif widget.data and widget.data.chart == 'bar' %}
        {% if widget.data.data %}
          {{ charts.bar_chart(widget.data.data, widget.data.eol_versions|default([])) }}
          {% if widget.data.top_failing_checks %}
          <ul class="widget-breakdown">
            {% for item in widget.data.top_failing_checks %}
            <li>{{ item.check }} — {{ item.count }}</li>
            {% endfor %}
          </ul>
          {% endif %}
          <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
        {% else %}
          <p class="widget-empty">No data yet</p>
        {% endif %}
```

- [ ] **Step 8: Add CSS**

In `app/static/css/app.css`, add near `.widget-table`:

```css
.widget-breakdown { margin: 0.3rem 0 0; padding-left: 1.1rem; font-size: 0.75rem; color: var(--text-muted); }
.widget-breakdown li { margin: 0.1rem 0; }
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 10: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add app/widgets.py app/templates/dashboard.html app/static/css/app.css tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add Configuration Posture widget for the device review rollup"
```

---

### Task 3: Rule Hygiene widget

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/dashboard.html`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: new catalog entry `4thealth.rule_hygiene` (`chart_type: "line"`, `default_size:
  "2x2"`, **no `rag` key** — informational, per design doc section 8).
- `get_widget_series` special case: line points from `rule_hygiene.rule_findings_total` history,
  `breakdown` field carrying the latest snapshot's `rule_findings_by_type`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_catalog_has_rule_hygiene_widget_with_no_rag():
    entry = WIDGET_CATALOG["4thealth.rule_hygiene"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "line"
    assert "rag" not in entry


def test_get_widget_series_rule_hygiene_line_points_and_breakdown():
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 100, "rule_findings_by_type": {"shadow": 4, "unhit": 60}}},
        _iso(600),
    )
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 118, "rule_findings_by_type": {"shadow": 5, "unhit": 65}}},
        _iso(5),
    )
    widget = {"type": "4thealth.rule_hygiene", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert [v for _, v in result["points"]] == [100, 118]
    assert result["breakdown"] == {"shadow": 5, "unhit": 65}
    assert result["delta"] == 18
    assert "rag" not in result


def test_get_widget_series_rule_hygiene_skips_snapshots_without_rollup():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, _iso(10))
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 118, "rule_findings_by_type": {}}},
        _iso(5),
    )
    widget = {"type": "4thealth.rule_hygiene", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert len(result["points"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k rule_hygiene -v`
Expected: FAIL — `KeyError: '4thealth.rule_hygiene'`.

- [ ] **Step 3: Write the implementation**

Add the catalog entry, after `4thealth.device_review_posture`:

```python
    "4thealth.rule_hygiene": {
        "label": "Rule Hygiene",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_hygiene",
        "default_size": "2x2",
        "chart_type": "line",
    },
```

In `get_widget_series`, add a branch to the existing `if widget_instance["type"] ==
"4thealth.ai_usage_24h": ... elif ... == "4thealth.fleet_availability": ... else:` chain (the
line-chart special-casing added in Tier 1):

```python
    elif widget_instance["type"] == "4thealth.rule_hygiene":
        points = [
            (h["collected_at"], (h["value"].get("rule_hygiene") or {}).get("rule_findings_total"))
            for h in history
        ]
        breakdown = (history[-1]["value"].get("rule_hygiene") or {}).get("rule_findings_by_type")
```

(This sits alongside the existing `fleet_availability`/`ai_usage_24h` `elif` branches — add it
as a sibling `elif`, before the final `else:`.)

The existing downstream filter `points = [(t, v) for t, v in points if v is not None and
isinstance(v, (int, float)) ...]` already drops the snapshot-without-rollup entries — no change
needed there.

At the final `return _attach_rag(...)` for the line-chart case, add `"breakdown":
locals().get("breakdown"),` — **avoid `locals()`**, instead initialize `breakdown = None` before
the `if widget_instance["type"] == "4thealth.ai_usage_24h":` chain begins (alongside the existing
`extra_label = None` initialization), so every branch has it in scope, then add `"breakdown":
breakdown,` to the final returned dict literal (next to `"delta": delta,`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_rule_hygiene_breakdown(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.rule_hygiene", "source_instance": "s1", "size": "2x2", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 118, "rule_findings_by_type": {"shadow": 5, "unhit": 65}}},
        "2026-08-28T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Rule Hygiene" in response.data
    assert b"shadow" in response.data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py -k rule_hygiene_breakdown -v`
Expected: FAIL — breakdown isn't rendered.

- [ ] **Step 7: Update the template**

In `app/templates/dashboard.html`, inside the line-chart branch, add the breakdown table after
the delta line:

```html
          {% if widget.data.delta is not none %}
            <p class="widget-delta">{% if widget.data.delta > 0 %}▲ +{{ widget.data.delta }}{% elif widget.data.delta < 0 %}▼ {{ widget.data.delta }}{% else %}— 0{% endif %}</p>
          {% endif %}
          {% if widget.data.breakdown %}
          <ul class="widget-breakdown">
            {% for check, count in widget.data.breakdown.items() %}
            <li>{{ check }} — {{ count }}</li>
            {% endfor %}
          </ul>
          {% endif %}
          <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/widgets.py app/templates/dashboard.html tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add Rule Hygiene widget with per-type findings breakdown"
```

---

### Task 4: AI usage by-feature breakdown

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/dashboard.html`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Changes: `get_widget_series` for `4thealth.ai_usage_24h` gains an optional `"by_feature"` key
  in its returned dict when the latest snapshot's payload includes `ai_usage_by_feature`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_widgets.py`:

```python
def test_get_widget_series_ai_usage_includes_by_feature_breakdown_when_present():
    write_snapshot(
        "s1", "summary",
        {
            "ai_usage_24h": {"ai_connection_count_24h": 12, "ai_estimated_cost_24h_usd": 0.41},
            "ai_usage_by_feature": {"device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0}},
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.ai_usage_24h", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["by_feature"] == {"device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0}}


def test_get_widget_series_ai_usage_by_feature_absent_when_not_in_payload():
    write_snapshot(
        "s1", "summary",
        {"ai_usage_24h": {"ai_connection_count_24h": 12, "ai_estimated_cost_24h_usd": 0.41}},
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.ai_usage_24h", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["by_feature"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k ai_usage_.*by_feature -v`
Expected: FAIL — `KeyError: 'by_feature'`.

- [ ] **Step 3: Write the implementation**

In `get_widget_series`'s `if widget_instance["type"] == "4thealth.ai_usage_24h":` branch, add
after the existing `cost`/`extra_label` lines:

```python
        by_feature = history[-1]["value"].get("ai_usage_by_feature")
```

Initialize `by_feature = None` alongside `breakdown = None` (from Task 3) before the branch
chain, and add `"by_feature": by_feature,` to the final returned dict literal.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_ai_usage_by_feature(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.ai_usage_24h", "source_instance": "s1", "size": "2x2", "date_range": "1d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary",
        {
            "ai_usage_24h": {"ai_connection_count_24h": 12, "ai_estimated_cost_24h_usd": 0.41},
            "ai_usage_by_feature": {"device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0}},
        },
        "2026-08-28T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"device_review_summary" in response.data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py -k ai_usage_by_feature -v`
Expected: FAIL.

- [ ] **Step 7: Update the template**

In `app/templates/dashboard.html`, in the line-chart branch, after the `breakdown` block added
in Task 3:

```html
          {% if widget.data.by_feature %}
          <ul class="widget-breakdown">
            {% for feature, stats in widget.data.by_feature.items() %}
            <li>{{ feature }} — {{ stats.calls }} calls, ${{ "%.2f"|format(stats.cost_usd) }}</li>
            {% endfor %}
          </ul>
          {% endif %}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/widgets.py app/templates/dashboard.html tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Show AI usage by-feature breakdown on the AI Usage widget"
```

---

### Task 5: Per-widget staleness using per-field-group freshness

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/app.css`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: `get_widget_value`/`get_widget_series` results gain an optional `"stale": bool` key
  for widget types mapped to a known field-group freshness key, computed against the *payload's*
  own `<group>_collected_at` value (not the poll-time snapshot `collected_at` already used
  elsewhere) — this is deliberately the "how fresh is the underlying 4thealth+ computation"
  signal the design doc asks for in rec 2.4, distinct from "when did 4tExecutive last poll."

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_get_widget_value_stale_true_when_field_group_collected_at_old():
    old_ts = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1", "summary",
        {"hygiene_score": 90, "hygiene_sweep_collected_at": old_ts},
        "2026-08-28T09:00:00Z",  # poll-time collected_at is fresh; field-group collected_at is stale
    )
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert result["stale"] is True


def test_get_widget_value_stale_false_when_field_group_collected_at_recent():
    recent_ts = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1", "summary",
        {"hygiene_score": 90, "hygiene_sweep_collected_at": recent_ts},
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["stale"] is False


def test_get_widget_value_no_stale_key_when_field_group_collected_at_absent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert "stale" not in get_widget_value(widget)


def test_get_widget_value_no_stale_key_for_widget_type_without_a_field_group():
    write_snapshot("s1", "summary", {"adom_count": 4}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.adom_count", "source_instance": "s1"}

    assert "stale" not in get_widget_value(widget)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -k stale -v`
Expected: FAIL — `KeyError: 'stale'` / assertion mismatches.

- [ ] **Step 3: Write the implementation**

In `app/widgets.py`, add near the top (after `RANGES`/`DEFAULT_RANGE`, or alongside
`WIDGET_CATALOG`):

```python
# Maps a widget type to the payload's per-field-group freshness key and the
# threshold (minutes) past which that group's data is considered stale --
# 2x the group's expected refresh interval, per design doc section 8.
_FIELD_GROUP_FRESHNESS: dict[str, tuple[str, int]] = {
    "4thealth.hygiene_score": ("hygiene_sweep_collected_at", 120),
    "4thealth.version_compliance": ("device_sweep_collected_at", 30),
    "4thealth.pending_config_diffs": ("device_sweep_collected_at", 30),
    "4thealth.fleet_availability": ("device_sweep_collected_at", 30),
    "4thealth.firewall_online_count": ("device_sweep_collected_at", 30),
    "4thealth.firewall_managed_count": ("device_sweep_collected_at", 30),
    "4thealth.rule_count_total": ("rule_count_collected_at", 120),
    "4thealth.rule_hygiene": ("hygiene_sweep_collected_at", 120),
    "4thealth.device_review_posture": ("device_review", 2880),
}


def _is_stale(value: dict, widget_type: str) -> bool | None:
    """Return whether the widget type's underlying field group is stale, or
    None if this widget type has no known field-group freshness key."""
    freshness_key = _FIELD_GROUP_FRESHNESS.get(widget_type)
    if freshness_key is None:
        return None
    key, threshold_minutes = freshness_key
    if key == "device_review":
        collected_at = (value.get("device_review") or {}).get("collected_at")
    else:
        collected_at = value.get(key)
    if not collected_at:
        return None
    try:
        collected_dt = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    age_minutes = (datetime.now(UTC) - collected_dt).total_seconds() / 60
    return age_minutes > threshold_minutes
```

In `get_widget_value`, after building `result` and before `return _attach_rag(...)`:

```python
    stale = _is_stale(latest["value"], widget_instance["type"])
    if stale is not None:
        result["stale"] = stale
    return _attach_rag(widget_instance["type"], entry, result)
```

For `get_widget_series`'s line-chart path, apply the same check using `history[-1]["value"]`
right before the final `return _attach_rag(...)`:

```python
    stale = _is_stale(history[-1]["value"], widget_instance["type"])
    result = {
        "chart": "line",
        "points": points,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "extra_label": extra_label,
        "breakdown": breakdown,
        "by_feature": by_feature,
        "delta": delta,
        "collected_at": history[-1]["collected_at"],
    }
    if stale is not None:
        result["stale"] = stale
    return _attach_rag(widget_instance["type"], entry, result, line_rag_value=latest_numeric_value)
```

(This replaces the existing final `return _attach_rag(...)` call — fold the dict-literal
construction out of the call so `"stale"` can be added conditionally before returning.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing template test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_stale_widget_gets_stale_css_class(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    old_ts = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    metrics_db.write_snapshot(
        "s1", "summary", {"hygiene_score": 90, "hygiene_sweep_collected_at": old_ts}, "2026-08-28T09:00:00Z",
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"widget-stale" in response.data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py -k stale_css -v`
Expected: FAIL — no `widget-stale` class rendered.

- [ ] **Step 7: Update the template and CSS**

In `app/templates/dashboard.html`, update the widget-card opening `div`:

```html
    <div id="widget-{{ loop.index }}" class="widget widget-{{ widget.size|default('1x1') }}{% if widget.data and widget.data.rag %} rag-{{ widget.data.rag }}{% endif %}{% if widget.data and widget.data.stale %} widget-stale{% endif %}">
```

In `app/static/css/app.css`, add:

```css
.widget-stale { opacity: 0.85; }
.widget-stale .widget-updated { color: var(--status-amber); }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/widgets.py app/templates/dashboard.html app/static/css/app.css tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add per-widget staleness coloring from per-field-group freshness"
```

---

### Task 6: Contract documentation

**Files:**
- Modify: `docs/integrations.md`

- [ ] **Step 1: Document every new/changed field**

Add entries to `docs/integrations.md` (following its existing per-field table format — read the
existing entries for `hygiene_score`/`version_breakdown`/`ai_usage_24h` first to match the exact
column structure this doc already uses) for: `schema_version`, `device_review`, `rule_hygiene`,
`ai_usage_by_feature`, `device_sweep_status`, `hygiene_sweep_status`,
`device_sweep_collected_at`, `hygiene_sweep_collected_at`, `rule_count_collected_at`, and the
`version_breakdown` shape change (flat int → `{count, eol}`, with an explicit backward-compat
note that 4tExecutive handles both shapes). Include type, null semantics ("absent/null until the
first scheduled rollup run" for `device_review`/`rule_hygiene"), and freshness (which sweep/job
each field's `collected_at` reflects).

- [ ] **Step 2: Commit**

```bash
git add docs/integrations.md
git commit -m "Document Tier 2 executive payload fields in integrations.md"
```

---

### Task 7: Full-suite verification and manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS, zero failures.

- [ ] **Step 2: Run lint**

Run: `ruff check app/ tests/`
Expected: no errors. Fix any and re-run.

- [ ] **Step 3: Manual smoke check**

Start the app, log in, and confirm in a browser (against a 4thealth+ instance running the
companion Tier 2 plan, or by manually inserting a snapshot row with the new fields via the
Python shell if no live Tier 2 4thealth+ instance is available yet):

1. Version breakdown bar chart renders EOL versions in red.
2. Configuration Posture widget shows a pass/fail bar + top-3 failing checks, red-bordered when
   `findings_by_severity.critical > 0`.
3. Rule Hygiene widget shows a trend line + findings-by-type breakdown, no colored border
   (informational).
4. AI Usage widget (with AI enabled on the source) shows a by-feature breakdown list.
5. A widget whose underlying field group is stale (simulate by writing an old
   `hygiene_sweep_collected_at` into a snapshot) renders dimmed with an amber "as of" line.
6. Poll a 4thealth+ instance that has NOT deployed Tier 2 yet (or a saved snapshot from before
   this work) — dashboard renders unchanged, no crashes, new widgets show "No data yet" if added
   to a layout.
7. Toggle dark mode — new colors (EOL red bars, staleness amber) remain legible in both themes.

- [ ] **Step 4: Report results to the user**

No commit for this task — verification only.

---

## Self-Review Notes

- **Spec coverage:** design doc section 8's five bullet points map to Tasks 1 (EOL coloring), 2
  (Configuration Posture), 3 (Rule Hygiene), 4 (AI usage by-feature), 5 (staleness coloring).
- **Backward compatibility:** Task 1 explicitly handles both the old flat-int and new `{count,
  eol}` `version_breakdown` shapes, since 4thealth+ and 4tExecutive release independently and a
  polled source may be on either payload version.
- **Type consistency:** `_is_stale()`'s `_FIELD_GROUP_FRESHNESS` keys match exactly the widget
  types defined across Tasks 1–4 and Tier 1; `device_review_posture`'s freshness key is handled
  as a special case (`"device_review"` sentinel) since its `collected_at` is nested one level
  deeper than the flat `*_collected_at` fields the other entries read.
