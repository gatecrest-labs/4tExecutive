# Exec Recommendations Tier 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the six Tier 1 "presentation only" recommendations from the Exec Recommendations review — RAG thresholds, a posture strip, the fleet-availability widget merge, backup-widget relabel, host-metrics relocation, and delta annotations — using only data 4tExecutive already collects.

**Architecture:** RAG thresholds are computed server-side in the data layer (`app/widgets.py`) from a new `app/thresholds.py` resolver (catalog default + optional `config/thresholds.json` override), attached to widget results as a `"rag"` key, and rendered as a CSS class on each widget card. A route-level aggregation (`dashboard_routes._posture`) rolls the already-computed per-widget RAG states into one posture strip — no new queries. Host metrics move off the dashboard to a new Admin → System page, reusing the existing widget-card/chart-macro rendering.

**Tech Stack:** Flask, Jinja2, SQLite (existing `metrics.db`), pytest.

**Spec:** `docs/Exec-recommendations.md` (sections 2 "Tier 1", 4 "Tier 1 implementation notes")

## Global Constraints

- No 4thealth+/4tlog changes in this plan — 4tExecutive only (spec section 4 preamble).
- Thresholds: catalog `WIDGET_CATALOG[...]["rag"]` defaults, overridable by `config/thresholds.json` keyed by widget type, merged at read time — no admin UI in Tier 1 (spec 4.1).
- Saved layouts referencing removed-from-default-layout widget types (`firewall_online_count`, `firewall_managed_count`, host metrics) must keep rendering unchanged — only `default_layout()` changes, catalog entries stay (spec 4.4, 4.6).
- A widget with a `rag` spec but no classifiable value renders neutral (no `"rag"` key), never a false red (spec 4.2).
- Every new/changed widget field must keep the existing "missing key ⇒ No data yet" convention — no crashes on malformed data (spec section 5).

---

## File Structure

- `app/thresholds.py` (new) — RAG threshold resolution: catalog default vs. `config/thresholds.json` override.
- `app/widgets.py` (modify) — catalog `rag` keys + label change, `_rag_state`/`_attach_rag` helpers wired into `get_widget_value`/`get_widget_series`, new `4thealth.fleet_availability` catalog entry + computation, delta computation, `default_layout()` exclusions, `annotate`/`_source_name` promoted from `dashboard_routes.py` (task 7 only).
- `app/routes/dashboard_routes.py` (modify) — posture-strip aggregation (`_posture`), wires `annotate` import (task 7).
- `app/routes/admin_routes.py` (modify) — new `/admin/system` route (task 7).
- `app/templates/dashboard.html` (modify) — RAG border class, posture strip markup, delta annotation markup.
- `app/templates/admin/system.html` (new) — host metrics page (task 7).
- `app/templates/admin/sources.html`, `app/templates/admin/users.html` (modify) — nav link to System page (task 7).
- `app/static/css/app.css` (modify) — `--status-amber` var, `.rag-*` classes, `.posture-strip` styles, `.widget-delta` style.
- `tests/test_thresholds.py` (new), `tests/test_widgets.py`, `tests/test_dashboard_routes.py`, `tests/test_admin_routes.py` (modify).

---

### Task 1: RAG threshold resolution module

**Files:**
- Create: `app/thresholds.py`
- Create: `tests/test_thresholds.py`

**Interfaces:**
- Produces: `get_thresholds(widget_type: str, catalog_default: dict | None) -> dict | None` — used by Task 2.
- Produces: `THRESHOLDS_PATH: Path` — module attribute, monkeypatched by tests (same pattern as `SOURCES_PATH`, `USERS_PATH`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for RAG threshold resolution and config/thresholds.json overrides."""

from __future__ import annotations

import json

import app.thresholds as thresholds_module
from app.thresholds import get_thresholds


def test_get_thresholds_returns_catalog_default_when_no_override_file(tmp_path, monkeypatch):
    monkeypatch.setattr(thresholds_module, "THRESHOLDS_PATH", tmp_path / "thresholds.json")

    result = get_thresholds("4thealth.hygiene_score", {"direction": "higher", "green": 90, "amber": 75})

    assert result == {"direction": "higher", "green": 90, "amber": 75}


def test_get_thresholds_returns_none_when_no_default_and_no_override(tmp_path, monkeypatch):
    monkeypatch.setattr(thresholds_module, "THRESHOLDS_PATH", tmp_path / "thresholds.json")

    assert get_thresholds("4thealth.rule_count_total", None) is None


def test_get_thresholds_override_file_takes_priority_over_catalog_default(tmp_path, monkeypatch):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"4thealth.hygiene_score": {"direction": "higher", "green": 99, "amber": 80}}))
    monkeypatch.setattr(thresholds_module, "THRESHOLDS_PATH", path)

    result = get_thresholds("4thealth.hygiene_score", {"direction": "higher", "green": 90, "amber": 75})

    assert result == {"direction": "higher", "green": 99, "amber": 80}


def test_get_thresholds_override_file_can_add_thresholds_for_widget_with_no_catalog_default(tmp_path, monkeypatch):
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps({"4thealth.rule_count_total": {"direction": "lower", "green": 10000, "amber": 15000}})
    )
    monkeypatch.setattr(thresholds_module, "THRESHOLDS_PATH", path)

    result = get_thresholds("4thealth.rule_count_total", None)

    assert result == {"direction": "lower", "green": 10000, "amber": 15000}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_thresholds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.thresholds'`

- [ ] **Step 3: Write the implementation**

```python
"""Widget RAG threshold resolution: WIDGET_CATALOG defaults, overridable by config/thresholds.json."""

from __future__ import annotations

from app.atomic_io import read_json
from app.config_paths import CONFIG_DIR

THRESHOLDS_PATH = CONFIG_DIR / "thresholds.json"


def get_thresholds(widget_type: str, catalog_default: dict | None) -> dict | None:
    """Return the RAG threshold spec for a widget type.

    config/thresholds.json (if present) is keyed by widget type and takes
    priority over WIDGET_CATALOG's own "rag" entry; a widget type with
    neither returns None (no RAG state — informational widget).
    """
    overrides = read_json(THRESHOLDS_PATH, default={})
    return overrides.get(widget_type, catalog_default)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_thresholds.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/thresholds.py tests/test_thresholds.py
git commit -m "Add RAG threshold resolution with config/thresholds.json override"
```

---

### Task 2: RAG state computation wired into the widget data layer

**Files:**
- Modify: `app/widgets.py`
- Modify: `tests/test_widgets.py`

**Interfaces:**
- Consumes: `get_thresholds(widget_type, catalog_default)` from Task 1.
- Produces: `get_widget_value(...)` and `get_widget_series(...)` results gain an optional `"rag"` key (`"green"|"amber"|"red"`), present only when the widget type has resolvable thresholds and a classifiable value.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py` (near the top-level imports, add `import app.thresholds as thresholds_module` and update the `get_widget_value`/`get_widget_series` import line to also import nothing new — helpers are private):

```python
def test_get_widget_value_returns_field_from_latest_snapshot():
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 92}, "2026-08-24T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "4thealth-east"}

    result = get_widget_value(widget)

    assert result == {"value": 92, "collected_at": "2026-08-24T10:00:00Z", "rag": "green"}
```

(This replaces the existing test of the same name — update it in place rather than duplicating.)

Add new tests:

```python
def test_get_widget_value_rag_amber_between_thresholds():
    write_snapshot("s1", "summary", {"hygiene_score": 80}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["rag"] == "amber"


def test_get_widget_value_rag_red_below_thresholds():
    write_snapshot("s1", "summary", {"hygiene_score": 40}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["rag"] == "red"


def test_get_widget_value_no_rag_key_for_informational_widget():
    write_snapshot("s1", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.rule_count_total", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert "rag" not in result


def test_get_widget_value_rag_none_when_value_missing():
    write_snapshot("s1", "summary", {"some_other_field": 1}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert result["value"] is None
    assert result["rag"] is None


def test_get_widget_value_rag_lower_direction_for_pending_config_diffs():
    write_snapshot("s1", "summary", {"pending_config_diff_count": 0}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.pending_config_diffs", "source_instance": "s1"}
    assert get_widget_value(widget)["rag"] == "green"

    write_snapshot("s1", "summary", {"pending_config_diff_count": 3}, "2026-08-27T10:01:00Z")
    assert get_widget_value(widget)["rag"] == "amber"

    write_snapshot("s1", "summary", {"pending_config_diff_count": 9}, "2026-08-27T10:02:00Z")
    assert get_widget_value(widget)["rag"] == "red"


def test_get_widget_value_rag_string_ok_for_backup_status():
    write_snapshot("s1", "summary", {"last_backup_status": "ok"}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.last_backup_status", "source_instance": "s1"}
    assert get_widget_value(widget)["rag"] == "green"

    write_snapshot("s1", "summary", {"last_backup_status": "failed: disk full"}, "2026-08-27T10:01:00Z")
    assert get_widget_value(widget)["rag"] == "red"


def test_widget_catalog_backup_widget_relabeled():
    assert WIDGET_CATALOG["4thealth.last_backup_status"]["label"] == "App Config Backup"


def test_get_widget_series_delegates_to_get_widget_value_for_unflagged_widget():
    write_snapshot("s1", "summary", {"hygiene_score": 92}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result == {"value": 92, "collected_at": "2026-08-27T10:00:00Z", "rag": "green"}
    assert "chart" not in result


```

`test_get_widget_series_delegates_to_get_widget_value_for_unflagged_widget` already exists in `tests/test_widgets.py` — update it in place to the new expected dict shown above rather than duplicating it. No `chart_type: "line"` widget gets a `rag` catalog entry in this task, so the first line-chart RAG test is added in Task 4 against `4thealth.fleet_availability`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -v`
Expected: FAIL — `AssertionError` on the updated/new RAG assertions (catalog has no `rag` keys yet, `_attach_rag` doesn't exist).

- [ ] **Step 3: Write the implementation**

In `app/widgets.py`, add the import:

```python
from app.thresholds import get_thresholds
```

Update these four catalog entries (edit in place, keep every other key unchanged):

```python
    "4thealth.hygiene_score": {
        "label": "Hygiene Score",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "hygiene_score",
        "default_size": "1x1",
        "rag": {"direction": "higher", "green": 90, "amber": 75},
    },
    "4thealth.version_compliance": {
        "label": "Device Version Compliance %",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_compliance_pct",
        "default_size": "1x1",
        "rag": {"direction": "higher", "green": 95, "amber": 85},
    },
    "4thealth.pending_config_diffs": {
        "label": "Pending Config Diffs",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "pending_config_diff_count",
        "default_size": "1x1",
        "rag": {"direction": "lower", "green": 0, "amber": 5},
    },
    "4thealth.last_backup_status": {
        "label": "App Config Backup",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "last_backup_status",
        "default_size": "1x1",
        "rag": {"direction": "string_ok"},
    },
```

Add the RAG helpers directly above `get_widget_value`:

```python
def _rag_state(value, thresholds: dict) -> str | None:
    """Classify value as green/amber/red per a threshold spec, or None if unclassifiable."""
    if value is None:
        return None
    direction = thresholds["direction"]
    if direction == "string_ok":
        return "green" if isinstance(value, str) and value.strip().lower().startswith("ok") else "red"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    green = thresholds.get("green")
    amber = thresholds.get("amber")
    if direction in ("higher", "ratio"):
        if green is not None and value >= green:
            return "green"
        if amber is not None and value >= amber:
            return "amber"
        return "red"
    if direction == "lower":
        if green is not None and value <= green:
            return "green"
        if amber is not None and value <= amber:
            return "amber"
        return "red"
    return None


def _attach_rag(widget_type: str, entry: dict, result: dict) -> dict:
    """Add a "rag" key to result when the widget type has RAG thresholds and a classifiable value.

    Reads the value to classify from result["value"] (get_widget_value shape)
    or, for line charts, the most recent point in result["points"].
    """
    thresholds = get_thresholds(widget_type, entry.get("rag"))
    if thresholds is None:
        return result
    if "value" in result:
        value = result["value"]
    elif result.get("chart") == "line":
        value = result["points"][-1][1] if result["points"] else None
    else:
        return result
    result["rag"] = _rag_state(value, thresholds)
    return result
```

Update `get_widget_value`:

```python
def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    result = {
        "value": latest["value"].get(entry["field"]),
        "collected_at": latest["collected_at"],
    }
    return _attach_rag(widget_instance["type"], entry, result)
```

In `get_widget_series`, wrap all three `return {...}` dicts (bar-empty is unaffected since bar widgets never carry `rag`, but wrap it too for consistency) with `_attach_rag(widget_instance["type"], entry, ...)`:

```python
    if chart_type == "bar":
        latest = get_latest(source_id, entry["metric_type"])
        if latest is None:
            return _attach_rag(widget_instance["type"], entry, {"chart": "bar", "data": {}, "collected_at": None})
        return _attach_rag(
            widget_instance["type"],
            entry,
            {
                "chart": "bar",
                "data": latest["value"].get(entry["field"]) or {},
                "collected_at": latest["collected_at"],
            },
        )

    range_delta = RANGES.get(range_key, RANGES[DEFAULT_RANGE])
    since = (datetime.now(UTC) - range_delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    history = get_history(source_id, entry["metric_type"], since)
    if not history:
        return _attach_rag(
            widget_instance["type"],
            entry,
            {"chart": "line", "points": [], "min": None, "max": None, "extra_label": None, "collected_at": None},
        )
```

and the final return:

```python
    return _attach_rag(
        widget_instance["type"],
        entry,
        {
            "chart": "line",
            "points": points,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "extra_label": extra_label,
            "collected_at": history[-1]["collected_at"],
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS (all tests, including updated/new ones)

- [ ] **Step 5: Run the full test suite to catch any other exact-dict-equality breakage**

Run: `pytest tests/ -v`
Expected: PASS. If any other test asserts an exact dict for `hygiene_score`, `version_compliance`, `pending_config_diffs`, or `last_backup_status`, update it the same way (add the expected `"rag"` key).

- [ ] **Step 6: Commit**

```bash
git add app/widgets.py tests/test_widgets.py
git commit -m "Compute RAG state for threshold-eligible widgets, relabel backup widget"
```

---

### Task 3: Render RAG state on widget cards

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/app.css`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Consumes: `widget.data.rag` (`"green"|"amber"|"red"|None`, or key absent) from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_rag_class_on_widget_card(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 40}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"rag-red" in response.data


def test_dashboard_no_rag_class_for_informational_widget(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.rule_count_total", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"rag-" not in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_routes.py -k rag -v`
Expected: FAIL — no `rag-*` class in output yet.

- [ ] **Step 3: Update the template**

In `app/templates/dashboard.html`, change the widget card opening `div` (also add an `id` for the posture-strip anchor used by Task 6):

```html
    <div id="widget-{{ loop.index }}" class="widget widget-{{ widget.size|default('1x1') }}{% if widget.data and widget.data.rag %} rag-{{ widget.data.rag }}{% endif %}">
```

- [ ] **Step 4: Add CSS**

In `app/static/css/app.css`, add `--status-amber` next to the existing status vars:

```css
:root[data-theme="light"] {
  --bg: #eef1f6;
  --surface: #ffffff;
  --surface-border: #dfe3ea;
  --text: #1a2233;
  --text-muted: #5b6478;
  --accent: #1c3d78;
  --accent-fg: #ffffff;
  --status-ok: #1a7f37;
  --status-amber: #b98900;
  --status-failed: #b00020;
  --status-pending: #8a939c;
}

:root[data-theme="dark"] {
  --bg: #10141f;
  --surface: #181f30;
  --surface-border: #262f45;
  --text: #e9edf7;
  --text-muted: #9aa3b8;
  --accent: #6f93e0;
  --accent-fg: #0d1626;
  --status-ok: #3fca6c;
  --status-amber: #e0a940;
  --status-failed: #ff6b6b;
  --status-pending: #9aa3b8;
}
```

Add near the `.widget` rules:

```css
.rag-green { border-left: 4px solid var(--status-ok); }
.rag-amber { border-left: 4px solid var(--status-amber); }
.rag-red { border-left: 4px solid var(--status-failed); }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/templates/dashboard.html app/static/css/app.css tests/test_dashboard_routes.py
git commit -m "Render RAG border color on widget cards"
```

---

### Task 4: Fleet Availability widget (merge online/managed)

**Files:**
- Modify: `app/widgets.py`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: new catalog entry `4thealth.fleet_availability` (`chart_type: "line"`, `rag: {"direction": "ratio", "green": 100, "amber": 90}`), included in `default_layout()`.
- Changes: `4thealth.firewall_online_count` and `4thealth.firewall_managed_count` stay in `WIDGET_CATALOG` (back-compat for saved layouts) but are excluded from `default_layout()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_catalog_has_fleet_availability_widget():
    entry = WIDGET_CATALOG["4thealth.fleet_availability"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "line"
    assert entry["rag"] == {"direction": "ratio", "green": 100, "amber": 90}


def test_default_layout_includes_fleet_availability_not_the_aliased_pair():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    types = {w["type"] for w in layout}
    assert "4thealth.fleet_availability" in types
    assert "4thealth.firewall_online_count" not in types
    assert "4thealth.firewall_managed_count" not in types


def test_get_widget_series_fleet_availability_computes_percentage_points():
    write_snapshot(
        "s1", "summary", {"firewall_online_count": 8, "firewall_managed_count": 10}, _iso(30)
    )
    write_snapshot(
        "s1", "summary", {"firewall_online_count": 10, "firewall_managed_count": 10}, _iso(5)
    )
    widget = {"type": "4thealth.fleet_availability", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["chart"] == "line"
    assert [v for _, v in result["points"]] == [80.0, 100.0]
    assert result["extra_label"] == "10 / 10 (100%)"
    assert result["rag"] == "green"


def test_get_widget_series_fleet_availability_amber_and_red():
    write_snapshot("s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, _iso(5))
    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")
    assert result["rag"] == "amber"

    write_snapshot("s1", "summary", {"firewall_online_count": 5, "firewall_managed_count": 10}, _iso(1))
    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")
    assert result["rag"] == "red"


def test_get_widget_series_fleet_availability_skips_snapshots_missing_a_side():
    write_snapshot("s1", "summary", {"firewall_online_count": 8}, _iso(10))
    write_snapshot("s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, _iso(5))

    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")

    assert len(result["points"]) == 1
```

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_fleet_availability_widget(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.fleet_availability", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Fleet Availability" in response.data
    assert b"9 / 10 (90%)" in response.data
    assert b"rag-amber" in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py tests/test_dashboard_routes.py -k "fleet_availability" -v`
Expected: FAIL — `KeyError: '4thealth.fleet_availability'`.

- [ ] **Step 3: Write the implementation**

Add the catalog entry to `app/widgets.py` (place after `4thealth.firewall_managed_count`):

```python
    "4thealth.fleet_availability": {
        "label": "Fleet Availability",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
        "chart_type": "line",
        "rag": {"direction": "ratio", "green": 100, "amber": 90},
    },
```

(`field` is unused for this composite widget type but the catalog schema requires the key; `firewall_online_count` documents intent.)

In `default_layout()`, exclude the two aliased widgets from the per-source loop:

```python
def default_layout() -> list[dict]:
    ...
    widgets = []
    for widget_type, entry in WIDGET_CATALOG.items():
        if widget_type in {"4thealth.firewall_online_count", "4thealth.firewall_managed_count"}:
            continue
        for source in list_sources():
            ...
```

In `get_widget_series`, add a branch for the composite type. Replace the existing:

```python
    extra_label = None
    if widget_instance["type"] == "4thealth.ai_usage_24h":
        points = [
            (h["collected_at"], (h["value"].get("ai_usage_24h") or {}).get("ai_connection_count_24h"))
            for h in history
        ]
        cost = (history[-1]["value"].get("ai_usage_24h") or {}).get("ai_estimated_cost_24h_usd")
        if cost is not None:
            extra_label = f"${cost:.2f} est. cost (24h)"
    else:
        points = [(h["collected_at"], h["value"].get(entry["field"])) for h in history]
```

with:

```python
    extra_label = None
    if widget_instance["type"] == "4thealth.ai_usage_24h":
        points = [
            (h["collected_at"], (h["value"].get("ai_usage_24h") or {}).get("ai_connection_count_24h"))
            for h in history
        ]
        cost = (history[-1]["value"].get("ai_usage_24h") or {}).get("ai_estimated_cost_24h_usd")
        if cost is not None:
            extra_label = f"${cost:.2f} est. cost (24h)"
    elif widget_instance["type"] == "4thealth.fleet_availability":
        points = []
        for h in history:
            online = h["value"].get("firewall_online_count")
            total = h["value"].get("firewall_managed_count")
            if isinstance(online, (int, float)) and isinstance(total, (int, float)) and total:
                points.append((h["collected_at"], round(online / total * 100, 1)))
        latest_online = history[-1]["value"].get("firewall_online_count")
        latest_total = history[-1]["value"].get("firewall_managed_count")
        if isinstance(latest_online, (int, float)) and isinstance(latest_total, (int, float)) and latest_total:
            extra_label = f"{latest_online} / {latest_total} ({round(latest_online / latest_total * 100)}%)"
    else:
        points = [(h["collected_at"], h["value"].get(entry["field"])) for h in history]
```

The existing downstream filter (`points = [(t, v) for t, v in points if v is not None and isinstance(v, (int, float)) ...]`) already handles the composite points unchanged — no further edits needed there.

Add the extra_label rendering to `app/templates/dashboard.html` if not already covered — check: the line-chart branch already renders `widget.data.extra_label` (added for AI usage). No template change needed for Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/widgets.py tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add Fleet Availability widget, drop aliased pair from default layout"
```

---

### Task 5: Delta annotations on line charts

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/app.css`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Produces: line-chart results from `get_widget_series` gain an optional `"delta"` key (`float | int | None`), present when `len(points) >= 2`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_widgets.py`:

```python
def test_get_widget_series_line_includes_delta_when_two_or_more_points():
    write_snapshot("s1", "summary", {"rule_count_total": 100}, _iso(600))
    write_snapshot("s1", "summary", {"rule_count_total": 130}, _iso(5))

    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "30d")

    assert result["delta"] == 30


def test_get_widget_series_line_delta_none_with_one_point():
    write_snapshot("s1", "summary", {"rule_count_total": 100}, _iso(5))

    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "1d")

    assert result["delta"] is None


def test_get_widget_series_line_delta_none_with_no_history():
    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "1d")

    assert result["delta"] is None
```

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_renders_delta_annotation(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.rule_count_total", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"rule_count_total": 100}, "2026-08-01T10:00:00Z")
    metrics_db.write_snapshot("s1", "summary", {"rule_count_total": 130}, "2026-08-27T10:00:00Z")

    response = client.get("/?range=30d")

    assert response.status_code == 200
    assert "▲ +30".encode() in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py tests/test_dashboard_routes.py -k delta -v`
Expected: FAIL — `KeyError: 'delta'`.

- [ ] **Step 3: Write the implementation**

In `app/widgets.py`, immediately before the final `return _attach_rag(...)` in `get_widget_series` (after `values = [v for _, v in points]`), add:

```python
    delta = (values[-1] - values[0]) if len(values) >= 2 else None
```

Add `"delta": delta,` to the final returned dict:

```python
    return _attach_rag(
        widget_instance["type"],
        entry,
        {
            "chart": "line",
            "points": points,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "extra_label": extra_label,
            "delta": delta,
            "collected_at": history[-1]["collected_at"],
        },
    )
```

Also add `"delta": None` to the empty-history early return dict:

```python
        return _attach_rag(
            widget_instance["type"],
            entry,
            {
                "chart": "line",
                "points": [],
                "min": None,
                "max": None,
                "extra_label": None,
                "delta": None,
                "collected_at": None,
            },
        )
```

In `app/templates/dashboard.html`, inside the `{% if widget.data and widget.data.chart == 'line' %}` branch, add delta rendering after the `extra_label` line:

```html
      {% if widget.data and widget.data.chart == 'line' %}
        {% if widget.data.points %}
          {{ charts.line_chart(widget.data.points, widget.data.min, widget.data.max) }}
          {% if widget.data.extra_label %}<p class="widget-extra">{{ widget.data.extra_label }}</p>{% endif %}
          {% if widget.data.delta is not none %}
            <p class="widget-delta">{% if widget.data.delta > 0 %}▲ +{{ widget.data.delta }}{% elif widget.data.delta < 0 %}▼ {{ widget.data.delta }}{% else %}— 0{% endif %}</p>
          {% endif %}
          <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
        {% else %}
          <p class="widget-empty">No data yet</p>
        {% endif %}
```

In `app/static/css/app.css`, add near `.widget-extra`:

```css
.widget-delta { margin: 0.2rem 0 0; font-size: 0.72rem; color: var(--text-muted); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py tests/test_dashboard_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/widgets.py app/templates/dashboard.html app/static/css/app.css tests/test_widgets.py tests/test_dashboard_routes.py
git commit -m "Add delta annotations to line-chart widgets"
```

---

### Task 6: Posture strip

**Files:**
- Modify: `app/routes/dashboard_routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/app.css`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Consumes: annotated widget list (each with `data.rag`, `data.collected_at`) already built by `index()`; `get_source(source_instance)` from `app.sources` (already imported).
- Produces: `_posture(widgets: list[dict]) -> dict | None`, passed to the template as `posture`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard_routes.py`:

```python
def test_dashboard_posture_strip_ok_when_all_green(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 95}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"posture-ok" in response.data
    assert b"OK" in response.data


def test_dashboard_posture_strip_critical_when_any_red(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [
            {"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"},
            {"type": "4thealth.pending_config_diffs", "source_instance": "s1", "size": "1x1", "date_range": "30d"},
        ],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 95}, "2026-08-27T10:00:00Z")
    metrics_db.write_snapshot("s1", "summary", {"pending_config_diff_count": 20}, "2026-08-27T10:01:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"posture-critical" in response.data
    assert b"Critical" in response.data
    assert b"1 critical" in response.data


def test_dashboard_no_posture_strip_when_no_rag_eligible_widgets(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.rule_count_total", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"posture-strip" not in response.data


def test_dashboard_posture_strip_hidden_in_edit_mode(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 95}, "2026-08-27T10:00:00Z")

    response = client.get("/dashboard/edit")

    assert response.status_code == 200
    assert b"posture-strip" not in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_routes.py -k posture -v`
Expected: FAIL — no posture markup exists yet.

- [ ] **Step 3: Write the implementation**

In `app/routes/dashboard_routes.py`, add imports and the aggregation function:

```python
from datetime import UTC, datetime
```

(add to the existing `from flask import ...` import block's neighboring imports at the top of the file)

```python
def _posture(widgets: list[dict]) -> dict | None:
    """Aggregate already-computed per-widget RAG state and freshness into one summary row.

    No new queries — reads widget["data"]["rag"] / ["collected_at"] from the
    already-annotated widget list. Returns None when no widget in the layout
    carries a RAG state (nothing to summarize).
    """
    rag_widgets = [(i, w) for i, w in enumerate(widgets, start=1) if w.get("data") and w["data"].get("rag")]
    if not rag_widgets:
        return None

    reds = [i for i, w in rag_widgets if w["data"]["rag"] == "red"]
    ambers = [i for i, w in rag_widgets if w["data"]["rag"] == "amber"]
    overall = "Critical" if reds else "Attention" if ambers else "OK"
    first_offender_index = reds[0] if reds else (ambers[0] if ambers else None)

    timestamps = [w["data"]["collected_at"] for w in widgets if w.get("data") and w["data"].get("collected_at")]
    oldest_minutes_ago = None
    stale = False
    if timestamps:
        oldest = min(timestamps)
        oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
        oldest_minutes_ago = round((datetime.now(UTC) - oldest_dt).total_seconds() / 60)
        longest_interval = max(
            (get_source(w["source_instance"]) or {}).get("poll_interval_minutes", 15) for w in widgets
        )
        stale = oldest_minutes_ago > 2 * longest_interval

    return {
        "overall": overall,
        "critical_count": len(reds),
        "attention_count": len(ambers),
        "oldest_minutes_ago": oldest_minutes_ago,
        "stale": stale,
        "first_offender_index": first_offender_index,
    }
```

Wire it into `index()`:

```python
@bp.route("/")
@tab_required("dashboard")
def index():
    range_key = _resolve_range()
    layout = get_layout(session["username"]) or default_layout()
    widgets = [_annotate(widget, with_data=True, range_key=range_key) for widget in layout]
    posture = _posture(widgets)
    response = make_response(
        render_template(
            "dashboard.html",
            widgets=widgets,
            edit_mode=False,
            catalog=None,
            range_key=range_key,
            ranges=list(RANGES),
            posture=posture,
        )
    )
    if request.args.get("range"):
        response.set_cookie("range", range_key, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
```

Add `posture=None` isn't needed on the `edit()` route — the template guards on `edit_mode`, not on `posture` being defined; `edit()` doesn't pass `posture` at all, and Jinja renders an undefined variable used only inside a falsy-guarded `{% if %}` as falsy, so no change to `edit()` is required. Verify this assumption in Step 4; if edit mode raises `UndefinedError`, add `posture=None` to the `edit()` render call.

In `app/templates/dashboard.html`, add the strip above the range selector:

```html
{% if not edit_mode and posture %}
<div class="posture-strip posture-{{ posture.overall|lower }}">
  <span class="posture-pill">{{ posture.overall }}</span>
  {% if posture.critical_count or posture.attention_count %}
  <a class="posture-counts" href="#widget-{{ posture.first_offender_index }}">{{ posture.critical_count }} critical · {{ posture.attention_count }} attention</a>
  {% endif %}
  {% if posture.oldest_minutes_ago is not none %}
  <span class="posture-freshness{% if posture.stale %} posture-stale{% endif %}">oldest data: {{ posture.oldest_minutes_ago }} min ago</span>
  {% endif %}
</div>
{% endif %}
{% if not edit_mode %}
<div class="range-selector">
```

(insert directly before the existing `<div class="range-selector">` block; the existing `{% if not edit_mode %}` that already wraps the range selector stays as-is — just add the new block immediately above it, each with its own `{% if %}`/`{% endif %}`.)

In `app/static/css/app.css`, add:

```css
.posture-strip { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; padding: 0.6rem 0.9rem; border-radius: 8px; background: var(--surface); border: 1px solid var(--surface-border); font-size: 0.85rem; }
.posture-pill { font-weight: 700; padding: 0.15rem 0.6rem; border-radius: 999px; color: var(--accent-fg); }
.posture-ok .posture-pill { background: var(--status-ok); }
.posture-attention .posture-pill { background: var(--status-amber); }
.posture-critical .posture-pill { background: var(--status-failed); }
.posture-counts { color: var(--text); text-decoration: none; }
.posture-counts:hover { text-decoration: underline; }
.posture-freshness { margin-left: auto; color: var(--text-muted); font-size: 0.78rem; }
.posture-stale { color: var(--status-amber); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS. If the edit-mode assumption above is wrong, fix `edit()` as noted and re-run.

- [ ] **Step 5: Commit**

```bash
git add app/routes/dashboard_routes.py app/templates/dashboard.html app/static/css/app.css tests/test_dashboard_routes.py
git commit -m "Add posture strip summarizing RAG state and data freshness"
```

---

### Task 7: Move host metrics to Admin → System page

**Files:**
- Modify: `app/widgets.py`
- Modify: `app/routes/dashboard_routes.py`
- Modify: `app/routes/admin_routes.py`
- Create: `app/templates/admin/system.html`
- Modify: `app/templates/admin/sources.html`
- Modify: `app/templates/admin/users.html`
- Modify: `tests/test_widgets.py`
- Modify: `tests/test_admin_routes.py`

**Interfaces:**
- Produces: `annotate(widget: dict, *, with_data: bool, range_key: str = DEFAULT_RANGE) -> dict` and `source_name(source_instance: str) -> str` in `app/widgets.py` (promoted from the private `_annotate`/`_source_name` in `dashboard_routes.py`).
- Produces: `GET /admin/system` route (`admin.system`).
- Changes: `default_layout()` no longer includes `4texecutive.*` widgets.

- [ ] **Step 1: Write the failing tests**

Update the existing default-layout tests in `tests/test_widgets.py` — these currently assert host widgets appear; change them to assert an **empty** default layout when no sources are configured:

```python
def test_default_layout_empty_when_no_sources():
    layout = default_layout()
    assert layout == []


def test_default_layout_no_longer_includes_host_metrics():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    types = {w["type"] for w in layout}
    assert "4texecutive.cpu_percent" not in types
    assert "4texecutive.memory_percent" not in types
    assert "4texecutive.disk_percent" not in types
```

Replace `test_default_layout_only_host_widgets_when_no_sources`, `test_default_layout_skips_disabled_sources`, and `test_default_layout_ignores_source_whose_system_has_no_widgets` (each currently asserts `types == {"4texecutive.cpu_percent", "4texecutive.memory_percent", "4texecutive.disk_percent"}`) — change that assertion in each to `assert types == set()`.

Add to `tests/test_admin_routes.py`:

```python
def test_admin_system_page_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/system")
    assert response.status_code == 403


def test_admin_system_page_renders_host_metrics(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    from app import metrics_db

    metrics_db.init_db()
    metrics_db.write_snapshot(
        "_self", "summary", {"cpu_percent": 12.5, "memory_percent": 40, "disk_percent": 55}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/admin/system")

    assert response.status_code == 200
    assert b"Host CPU" in response.data
    assert b"Host Memory" in response.data
    assert b"Host Disk" in response.data
```

Note: `tests/test_admin_routes.py` does not currently set up a temp `metrics.db` — check whether the `app` fixture in `conftest.py` already monkeypatches `metrics_db.DB_PATH` (it does, per `tests/conftest.py`'s `app` fixture). No extra fixture needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py tests/test_admin_routes.py -v`
Expected: FAIL — default layout still includes host widgets; `/admin/system` is a 404.

- [ ] **Step 3: Write the implementation**

In `app/widgets.py`, remove the second loop in `default_layout()` (the `4texecutive` host-widget loop) entirely:

```python
def default_layout() -> list[dict]:
    """..."""
    widgets = []
    for widget_type, entry in WIDGET_CATALOG.items():
        if widget_type in {"4thealth.firewall_online_count", "4thealth.firewall_managed_count"}:
            continue
        for source in list_sources():
            if source.get("system") != entry["source_system"] or not source.get("enabled", True):
                continue
            if widget_type == "4thealth.ai_usage_24h":
                latest = get_latest(source["id"], entry["metric_type"])
                if latest is None or not latest["value"].get("ai_enabled"):
                    continue
            widgets.append(
                {
                    "type": widget_type,
                    "source_instance": source["id"],
                    "size": entry["default_size"],
                    "date_range": "30d",
                }
            )

    return widgets
```

Update the function's docstring to drop the now-inaccurate host-widget-loop description (keep the AI-usage paragraph):

```python
def default_layout() -> list[dict]:
    """Auto-generated fallback shown when a user has no saved layout: one
    widget per catalog entry x each enabled source whose system matches, so
    the dashboard shows everything currently configured instead of being
    blank until someone builds a real per-user editor. Host metrics
    (4texecutive.*) are excluded — they live on the Admin > System page,
    not the executive dashboard.

    The AI usage widget is the one exception — it's only included when the
    source's latest snapshot reports ai_enabled: true, since most 4thealth
    instances won't have AI turned on and an always-empty tile isn't useful
    default clutter. A user who manually saves a layout containing it still
    sees it regardless (falls back to "No data yet" like any other widget
    with a missing field) — this skip only affects the auto-generated
    default.
    """
```

Add `annotate` and `source_name` to `app/widgets.py` (add the import at the top: `from app.sources import get_source, list_sources`, replacing the existing `from app.sources import list_sources`):

```python
def source_name(source_instance: str) -> str:
    source = get_source(source_instance)
    return source["name"] if source else source_instance


def annotate(widget: dict, *, with_data: bool, range_key: str = DEFAULT_RANGE) -> dict:
    entry = WIDGET_CATALOG[widget["type"]]
    annotated = {
        **widget,
        "label": entry["label"],
        "source_name": source_name(widget["source_instance"]),
    }
    if with_data:
        annotated["data"] = get_widget_series(widget, range_key)
    return annotated
```

Place these after `RANGES`/`DEFAULT_RANGE` are defined (they're used by `annotate`'s default arg) — put them at the end of the file, after `get_widget_series`.

In `app/routes/dashboard_routes.py`, remove the now-duplicated `_source_name` and `_annotate` functions and import the promoted versions instead:

```python
from app.widgets import DEFAULT_RANGE, RANGES, WIDGET_CATALOG, annotate, default_layout
```

(drop `get_widget_series` from this import line — it's no longer called directly here — and drop the `from app.sources import get_source` import only if nothing else in the file uses `get_source`; Task 6 added `get_source` usage inside `_posture`, so **keep** that import.)

Delete the `_source_name` and `_annotate` function definitions from `dashboard_routes.py`, and replace their two call sites (`index()` and `edit()`) from `_annotate(...)` to `annotate(...)`.

In `app/routes/admin_routes.py`, add:

```python
from app.widgets import DEFAULT_RANGE, WIDGET_CATALOG, annotate

_HOST_WIDGET_TYPES = ["4texecutive.cpu_percent", "4texecutive.memory_percent", "4texecutive.disk_percent"]


@bp.route("/system", methods=["GET"])
@tab_required("admin")
def system():
    widgets = [
        annotate(
            {"type": t, "source_instance": "_self", "size": WIDGET_CATALOG[t]["default_size"]},
            with_data=True,
            range_key=DEFAULT_RANGE,
        )
        for t in _HOST_WIDGET_TYPES
    ]
    return render_template("admin/system.html", widgets=widgets)
```

Create `app/templates/admin/system.html`:

```html
{% extends "base.html" %}
{% import "_charts.html" as charts %}
{% block content %}
<h1>Admin — System</h1>
<p><a href="{{ url_for('admin.sources') }}">Manage sources →</a></p>
<div class="widget-grid">
  {% for widget in widgets %}
    <div class="widget widget-{{ widget.size|default('1x1') }}">
      <h3>{{ widget.label }}</h3>
      {% if widget.data and widget.data.chart == 'line' %}
        {% if widget.data.points %}
          {{ charts.line_chart(widget.data.points, widget.data.min, widget.data.max) }}
          <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
        {% else %}
          <p class="widget-empty">No data yet</p>
        {% endif %}
      {% else %}
        <p class="widget-empty">No data yet</p>
      {% endif %}
    </div>
  {% endfor %}
</div>
{% endblock %}
```

Add a nav link in `app/templates/admin/sources.html` (next to the existing "Manage users" link):

```html
<p><a href="{{ url_for('admin.users') }}">Manage users →</a> · <a href="{{ url_for('admin.system') }}">System →</a></p>
```

Add the same in `app/templates/admin/users.html` (next to "Manage sources"):

```html
<p><a href="{{ url_for('admin.sources') }}">Manage sources →</a> · <a href="{{ url_for('admin.system') }}">System →</a></p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ -v`
Expected: PASS across the whole suite.

- [ ] **Step 5: Commit**

```bash
git add app/widgets.py app/routes/dashboard_routes.py app/routes/admin_routes.py app/templates/admin/system.html app/templates/admin/sources.html app/templates/admin/users.html tests/test_widgets.py tests/test_admin_routes.py
git commit -m "Move host metrics from dashboard default layout to Admin > System page"
```

---

### Task 8: Full-suite verification and manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS, zero failures.

- [ ] **Step 2: Run lint**

Run: `ruff check app/ tests/`
Expected: no errors. Fix any and re-run.

- [ ] **Step 3: Manual smoke check**

Start the app (`flask --app app run` or the project's existing run command — check `README.md`/`Makefile` if one exists), log in, and confirm in a browser:
1. Dashboard shows colored left borders on hygiene score / version compliance / pending diffs / backup / fleet availability widgets.
2. A posture strip appears above the range selector with the correct pill (OK/Attention/Critical) and "oldest data: N min ago".
3. "Firewalls Online" / "Firewalls Managed" are gone from the default dashboard; "Fleet Availability" shows `online / total (pct%)`.
4. Line-chart widgets with ≥2 history points show a ▲/▼/— delta line.
5. `/admin/system` shows Host CPU/Memory/Disk charts; they no longer appear on the dashboard.
6. Toggle dark mode — RAG colors and posture strip remain legible in both themes.

- [ ] **Step 4: Report results to the user**

No commit for this task — it's verification only.

---

## Self-Review Notes

- **Spec coverage:** 1.1 (Task 2/3), 1.2 (Task 6), 1.3 (Task 4), 1.4 (Task 2), 1.5 (Task 7), 1.6 (Task 5) — all six Tier 1 recommendations map to a task.
- **Back-compat:** `firewall_online_count`/`firewall_managed_count` and the three `4texecutive.*` entries stay in `WIDGET_CATALOG` for saved-layout rendering (spec 4.4/4.6) — only `default_layout()` changes remove them from the auto-generated default.
- **Type consistency:** `annotate`/`source_name` signatures match between their Task 7 definition in `app/widgets.py` and their call sites in `dashboard_routes.py` and `admin_routes.py`.
