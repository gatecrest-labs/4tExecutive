# License Status Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface 4thealth-plus's new fleet-wide `license_status` field group (companion plan, separate repo — `~/code/github/ai/4thealth-plus`) in 4tExecutive: a Board widget, a Lifecycle & Support domain row, and fleet-devices drilldown rows.

**Architecture:** `license_status` is a new, purely additive, optional top-level key in the `4thealth`/`4thealth-plus` executive-summary payload — `{devices_licensed, devices_expired, devices_unknown, details, collected_at}`. This plan wires it through 4tExecutive's existing generic pipelines (`metric_extract.py` → `metrics_db` metric_points, `domains.py`'s data-driven `MEMBER_METRICS`/`domain_member_table()`, `devices.py`'s details-list merge, `widgets.py`'s catalog-driven rendering) the same way `lifecycle`/`device_review` were wired in previously — no new subsystem, no template changes (the domain detail page's member table and the devices drilldown are both fully data-driven off these registries already).

**Tech Stack:** Python 3.14, Flask, pytest, SQLite (`metrics_db.py`) — same stack as the rest of this repo. No new dependencies.

**Spec:** `~/code/github/ai/4thealth-plus/docs/superpowers/specs/2026-09-15-license-status-executive-summary-design.md` (spec lives in the companion repo since it covers both sides; this plan implements only this repo's slice, decisions 6-7).

## Global Constraints

- **No domain score changes.** `license_status` rows are informational only — never added to `_SCORERS["lifecycle"]` or `DEFAULT_SCORING`. This mirrors how `change_control.admin_changes_24h` is already a scored-domain member row with no RAG/scoring impact.
- **Absent-safe everywhere.** Every read of `license_status`/`license_status.details` must degrade to `None`/`[]`/"no data yet" when the field is missing (a `4thealth-plus` instance that hasn't shipped this yet, or a `4tlog` source that will never have it) — never raise, never fabricate a count.
- **`details` list convention:** only non-`"licensed"` devices appear in it (per the companion repo's design) — this repo's code must not assume every device appears.
- This is the `4thealth`/`4thealth-plus` `source_system` only — `4tlog` has no `license_status` concept.

---

### Task 1: `metric_extract.py` — new extractors

**Files:**
- Modify: `app/metric_extract.py` (add to the `EXTRACTORS` registry, near the existing `lifecycle` block)
- Test: `tests/test_metric_extract.py` (append)

**Interfaces:**
- Consumes: `_nested(*path) -> Callable[[dict], float | None]` (existing), `_no_scalar` (existing).
- Produces: `EXTRACTORS["license_status"]`, `EXTRACTORS["license_status.devices_licensed"]`, `EXTRACTORS["license_status.devices_expired"]`, `EXTRACTORS["license_status.devices_unknown"]`, `EXTRACTORS["license_status.details"]` — new registry keys, consumed by Task 2 and Task 4's tests via `extract_all()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metric_extract.py`:

```python
def test_extract_all_covers_license_status_fields():
    payload = {
        "license_status": {
            "devices_licensed": 40,
            "devices_expired": 2,
            "devices_unknown": 1,
            "details": [{"device": "fw-a", "adom": "Corp", "status": "expired", "expires": None}],
            "collected_at": "2026-09-16T03:00:00Z",
        }
    }
    points = extract_all(payload)
    assert points["license_status.devices_licensed"] == 40.0
    assert points["license_status.devices_expired"] == 2.0
    assert points["license_status.devices_unknown"] == 1.0
    assert "license_status" not in points
    assert "license_status.details" not in points


def test_extract_all_omits_license_status_keys_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert "license_status.devices_licensed" not in points
    assert "license_status.devices_expired" not in points
    assert "license_status.devices_unknown" not in points
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metric_extract.py -v -k license_status`
Expected: FAIL — `KeyError` inside `extract_all()`, or the assertions simply don't find the keys (since `EXTRACTORS` has no `license_status.*` entries yet, `extract_all()` silently produces no such points — confirm the failure is exactly "key not in points" before proceeding, not an exception).

- [ ] **Step 3: Add the registry entries**

In `app/metric_extract.py`, immediately after the existing block:

```python
    "lifecycle": _no_scalar,
    "lifecycle.devices_hw_eos": _nested("lifecycle", "devices_hw_eos"),
    "lifecycle.devices_hw_eos_12m": _nested("lifecycle", "devices_hw_eos_12m"),
    "lifecycle.models_unknown": _no_scalar,
```

add:

```python
    # License status (4thealth-plus, app.license_status_cache's daily sweep).
    "license_status": _no_scalar,
    "license_status.devices_licensed": _nested("license_status", "devices_licensed"),
    "license_status.devices_expired": _nested("license_status", "devices_expired"),
    "license_status.devices_unknown": _nested("license_status", "devices_unknown"),
    "license_status.details": _no_scalar,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metric_extract.py -v -k license_status`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full metric_extract test file**

Run: `uv run pytest tests/test_metric_extract.py -v`
Expected: PASS, no regressions (including `test_every_catalog_field_has_an_extractor` — this will only pass once Task 4 adds the matching `WIDGET_CATALOG["4thealth.license_status"]["field"] = "license_status"` entry, so it's fine if this specific test is still red until Task 4 lands; every other test in the file must pass now).

- [ ] **Step 6: Lint check**

Run: `uv run ruff check app/metric_extract.py && uv run ruff format --check app/metric_extract.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add app/metric_extract.py tests/test_metric_extract.py
git commit -m "feat: add license_status metric_point extractors"
```

---

### Task 2: `domains.py` — Lifecycle & Support member rows

**Files:**
- Modify: `app/domains.py` (`MEMBER_METRICS["lifecycle"]`, `_domain_inputs()`'s `"lifecycle"` branch)
- Test: `tests/test_domains.py` (append)

**Interfaces:**
- Consumes: `license_status.devices_expired` / `license_status.devices_unknown` metric_points (Task 1), `_fleet_sum(system, metric_key, ts_iso)` (existing helper).
- Produces: two new rows in `domain_member_table("lifecycle")`'s output, keyed `"license_status.devices_expired"` and `"license_status.devices_unknown"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_domains.py`:

```python
def test_domain_member_table_includes_license_status_rows():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "license_status.devices_expired": 2.0,
            "license_status.devices_unknown": 1.0,
        },
    )

    rows = domain_member_table("lifecycle")

    expired_row = next(r for r in rows if r["key"] == "license_status.devices_expired")
    assert expired_row["now"] == 2.0
    # No matching WIDGET_CATALOG entry scores this exact metric_key -> informational, no RAG.
    assert expired_row["rag"] is None

    unknown_row = next(r for r in rows if r["key"] == "license_status.devices_unknown")
    assert unknown_row["now"] == 1.0


def test_domain_member_table_license_status_rows_absent_when_no_data():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"version_compliance_pct": 90.0})

    rows = domain_member_table("lifecycle")

    expired_row = next(r for r in rows if r["key"] == "license_status.devices_expired")
    assert expired_row["now"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_domains.py -v -k license_status`
Expected: FAIL — `StopIteration` (no row with that key exists yet in `domain_member_table("lifecycle")`'s output).

- [ ] **Step 3: Add the MEMBER_METRICS rows and _domain_inputs fields**

In `app/domains.py`, change `MEMBER_METRICS["lifecycle"]` from:

```python
    "lifecycle": [
        {"key": "version_compliance_pct", "label": "Firmware compliance (fleet avg)"},
        {"key": "devices_on_eol_version", "label": "Devices on EOL FortiOS version"},
        {"key": "lifecycle.devices_hw_eos", "label": "Devices with EOS hardware"},
        {"key": "lifecycle.devices_hw_eos_12m", "label": "Devices reaching hardware EOS within 12mo"},
    ],
```

to:

```python
    "lifecycle": [
        {"key": "version_compliance_pct", "label": "Firmware compliance (fleet avg)"},
        {"key": "devices_on_eol_version", "label": "Devices on EOL FortiOS version"},
        {"key": "lifecycle.devices_hw_eos", "label": "Devices with EOS hardware"},
        {"key": "lifecycle.devices_hw_eos_12m", "label": "Devices reaching hardware EOS within 12mo"},
        {"key": "license_status.devices_expired", "label": "Devices with expired license"},
        {"key": "license_status.devices_unknown", "label": "Devices with unknown license status"},
    ],
```

Then in `_domain_inputs()`'s `if name == "lifecycle":` branch, add two entries to the returned dict (after the existing `"firewall_managed_count"` line):

```python
            # License status — informational member rows only (see Global
            # Constraints in the license-status-widget plan); not read by
            # _score_lifecycle, no per-ADOM breakdown to pair with.
            "license_status.devices_expired": _fleet_sum(
                system, "license_status.devices_expired", ts_iso
            ),
            "license_status.devices_unknown": _fleet_sum(
                system, "license_status.devices_unknown", ts_iso
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_domains.py -v -k license_status`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full domains test file**

Run: `uv run pytest tests/test_domains.py -v`
Expected: PASS, no regressions — in particular confirm every existing `lifecycle` scoring test (`test_compute_domain_lifecycle_*`) still passes unchanged, proving the new inputs don't affect `_score_lifecycle`.

- [ ] **Step 6: Lint check**

Run: `uv run ruff check app/domains.py && uv run ruff format --check app/domains.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add app/domains.py tests/test_domains.py
git commit -m "feat: add license_status rows to the Lifecycle & Support domain table"
```

---

### Task 3: `devices.py` — fleet devices drilldown

**Files:**
- Modify: `app/devices.py` (`_rows_lifecycle()`)
- Test: `tests/test_devices.py` (append)

**Interfaces:**
- Consumes: `license_status.details` (a list of `{device, adom, status, expires}` dicts, per the companion repo's spec).
- Produces: additional rows appended to `get_domain_devices("lifecycle")`'s output, each with a `detail_text` describing the license problem.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
def test_get_domain_devices_lifecycle_includes_license_status_details():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {
            "license_status": {
                "devices_licensed": 40,
                "devices_expired": 1,
                "devices_unknown": 1,
                "details": [
                    {"device": "fw-expired", "adom": "Corp", "status": "expired", "expires": "2026-08-01"},
                    {"device": "fw-unknown", "adom": "Corp", "status": "unknown", "expires": None},
                ],
            }
        },
        _iso(5),
    )

    rows = get_domain_devices("lifecycle")

    expired_row = next(r for r in rows if r["device"] == "fw-expired")
    assert expired_row["detail_text"] == "license expired (2026-08-01)"

    unknown_row = next(r for r in rows if r["device"] == "fw-unknown")
    assert unknown_row["detail_text"] == "license status unknown"


def test_get_domain_devices_lifecycle_license_status_absent_yields_no_extra_rows():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 92}, _iso(5))

    rows = get_domain_devices("lifecycle")

    assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_devices.py -v -k license_status`
Expected: FAIL — `StopIteration` (no such rows produced yet).

- [ ] **Step 3: Extend `_rows_lifecycle()`**

In `app/devices.py`, change `_rows_lifecycle()` from:

```python
def _rows_lifecycle(value: dict) -> list[dict]:
    rows = []
    for entry in _as_list(value.get("version_breakdown")):
        if not isinstance(entry, dict) or not entry.get("eol"):
            continue
        version = entry.get("version")
        for device in _as_list(entry.get("devices")):
            if not isinstance(device, dict):
                continue
            row = dict(device)
            row.setdefault("version", version)
            row["detail_text"] = str(row.get("version"))
            rows.append(row)
    return rows
```

to:

```python
def _rows_lifecycle(value: dict) -> list[dict]:
    rows = []
    for entry in _as_list(value.get("version_breakdown")):
        if not isinstance(entry, dict) or not entry.get("eol"):
            continue
        version = entry.get("version")
        for device in _as_list(entry.get("devices")):
            if not isinstance(device, dict):
                continue
            row = dict(device)
            row.setdefault("version", version)
            row["detail_text"] = str(row.get("version"))
            rows.append(row)
    # License status — only non-"licensed" devices ever appear in this list
    # (see the companion 4thealth-plus repo's license_status_cache design),
    # so every entry here is already a problem worth surfacing.
    for entry in _as_list(_as_dict(value.get("license_status")).get("details")):
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        if entry.get("status") == "expired":
            expires = entry.get("expires")
            row["detail_text"] = f"license expired ({expires})" if expires else "license expired"
        else:
            row["detail_text"] = "license status unknown"
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_devices.py -v -k license_status`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full devices test file**

Run: `uv run pytest tests/test_devices.py -v`
Expected: PASS, no regressions — confirm `test_get_domain_devices_lifecycle_only_eol_versions` still passes unchanged (proves the EOL-version rows and license-status rows coexist without interfering).

- [ ] **Step 6: Lint check**

Run: `uv run ruff check app/devices.py && uv run ruff format --check app/devices.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add app/devices.py tests/test_devices.py
git commit -m "feat: surface license_status.details in the Lifecycle devices drilldown"
```

---

### Task 4: `widgets.py` — Board widget

**Files:**
- Modify: `app/widgets.py` (`_FIELD_GROUP_FRESHNESS`, `WIDGET_CATALOG`, `_empty_bar()`, `get_widget_series()`, `default_layout()`)
- Test: `tests/test_widgets.py` (append)

**Interfaces:**
- Consumes: `latest["value"]["license_status"]` (the raw payload field, `{devices_licensed, devices_expired, devices_unknown, details, collected_at}`), `_attach_rag()`, `rag_state()` (existing).
- Produces: `WIDGET_CATALOG["4thealth.license_status"]`, exercised via `get_widget_series({"type": "4thealth.license_status", "source_instance": ...}, "30d")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_widgets.py`:

```python
def test_catalog_has_license_status_widget():
    entry = WIDGET_CATALOG["4thealth.license_status"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "bar"
    assert entry["field"] == "license_status"
    assert entry["metric_key"] == "license_status.devices_expired"


def test_get_widget_series_license_status_computes_bar_and_red_rag():
    write_snapshot(
        "s1", "summary",
        {
            "license_status": {
                "devices_licensed": 40,
                "devices_expired": 2,
                "devices_unknown": 1,
                "details": [],
                "collected_at": "2026-09-16T03:00:00Z",
            }
        },
        "2026-09-16T09:00:00Z",
    )
    widget = {"type": "4thealth.license_status", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"Licensed": 40, "Expired": 2, "Unknown": 1}
    assert result["collected_at"] == "2026-09-16T09:00:00Z"
    assert result["rag"] == "red"


def test_get_widget_series_license_status_green_when_none_expired():
    write_snapshot(
        "s1", "summary",
        {
            "license_status": {
                "devices_licensed": 40,
                "devices_expired": 0,
                "devices_unknown": 0,
                "details": [],
                "collected_at": "2026-09-16T03:00:00Z",
            }
        },
        "2026-09-16T09:00:00Z",
    )
    widget = {"type": "4thealth.license_status", "source_instance": "s1"}

    assert get_widget_series(widget, "30d")["rag"] == "green"


def test_get_widget_series_license_status_no_data_when_absent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-09-16T09:00:00Z")
    widget = {"type": "4thealth.license_status", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert "rag" not in result


def test_get_widget_series_license_status_no_data_paths_share_one_shape():
    never_polled = get_widget_series(
        {"type": "4thealth.license_status", "source_instance": "unpolled"}, "30d"
    )
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-09-16T09:00:00Z")
    rollup_absent = get_widget_series(
        {"type": "4thealth.license_status", "source_instance": "s1"}, "30d"
    )

    expected = {"chart", "data", "collected_at"}
    assert set(never_polled) == expected
    assert set(rollup_absent) == expected


def test_is_stale_license_status_uses_collected_at():
    value = {"license_status": {"collected_at": _iso(200)}}  # 200 min ago
    assert _is_stale(value, "4thealth.license_status") is True

    value_fresh = {"license_status": {"collected_at": _iso(5)}}
    assert _is_stale(value_fresh, "4thealth.license_status") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_widgets.py -v -k license_status`
Expected: FAIL — `KeyError: '4thealth.license_status'` (no catalog entry yet).

- [ ] **Step 3: Add `_FIELD_GROUP_FRESHNESS` entry**

In `app/widgets.py`, add to `_FIELD_GROUP_FRESHNESS` (after the existing `"4thealth.device_review_posture": ("device_review", 2880),` line):

```python
    # 2880 = 2x a daily sweep's expected interval (24h), same reasoning as
    # device_review_posture's 48h threshold for its own daily-ish rollup.
    "4thealth.license_status": ("license_status", 2880),
```

Note this reads `value["license_status"]["collected_at"]` via `_freshness_collected_at()`'s existing `device_review`-shaped fallback path — but that fallback is currently hardcoded to the literal key `"device_review"` (see `_freshness_collected_at()`'s `if key != "device_review":` / `device_review = value.get("device_review")` block). `"license_status"` needs the same nested-`collected_at` lookup, so this step also requires generalizing that special case — change:

```python
    if key != "device_review":
        candidate = value.get(key)
        if candidate is not None:
            return candidate

    device_review = value.get("device_review")
    if isinstance(device_review, dict):
        candidate = device_review.get("collected_at")
        if candidate is not None:
            return candidate

    return None
```

to:

```python
    candidate = value.get(key)
    if isinstance(candidate, str):
        return candidate

    nested = value.get(key)
    if isinstance(nested, dict):
        candidate = nested.get("collected_at")
        if candidate is not None:
            return candidate

    return None
```

This is a strict generalization: `key="device_review"` behaves identically (`value.get("device_review")` is a dict, not a string, so the first branch is skipped and the second branch reads its `collected_at` exactly as before); every other existing key (e.g. `"device_sweep_collected_at"`) is a top-level string, so the first branch still returns it unchanged. `key="license_status"` now works the same way `"device_review"` already did.

- [ ] **Step 4: Add the `WIDGET_CATALOG` entry**

Immediately after `"4thealth.device_review_posture"`'s entry (ends right before `"4thealth.ai_usage_24h"`), add:

```python
    "4thealth.license_status": {
        "label": "License Status",
        "description": "Fleet-wide FortiGate license status: licensed, expired, or unknown.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "license_status",
        "metric_key": "license_status.devices_expired",
        "direction": "lower",
        "default_size": "2x2",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
```

- [ ] **Step 5: Add the `_empty_bar()` branch**

In `_empty_bar()`, the `if widget_type == "4thealth.version_breakdown": ... elif widget_type == "4thealth.device_review_posture": ...` chain needs no new branch — `license_status`'s empty shape is just `{"chart": "bar", "data": {}, "collected_at": None}`, identical to the base `empty` dict with no extra keys. Confirm this by checking `test_get_widget_series_license_status_no_data_paths_share_one_shape` (Step 1) expects exactly `{"chart", "data", "collected_at"}` — no extra keys — so this step is a no-op; skip it.

- [ ] **Step 6: Add the `get_widget_series()` branch**

In the `if chart_type == "bar":` block, immediately after the `"4thealth.device_review_posture"` branch (ends right before `if widget_instance["type"] == "4thealth.rule_hygiene":`), add:

```python
        if widget_instance["type"] == "4thealth.license_status":
            license_status = latest["value"].get("license_status")
            if not license_status:
                return _attach_rag(
                    widget_instance["type"], entry, _empty_bar(widget_instance["type"])
                )
            licensed = license_status.get("devices_licensed") or 0
            expired = license_status.get("devices_expired") or 0
            unknown = license_status.get("devices_unknown") or 0
            result = {
                "chart": "bar",
                "data": {"Licensed": licensed, "Expired": expired, "Unknown": unknown},
                "collected_at": latest["collected_at"],
            }
            result["rag"] = "red" if expired > 0 else "green"
            return result

```

(placed before the `if widget_instance["type"] == "4thealth.rule_hygiene":` line)

- [ ] **Step 7: Add the `default_layout()` conditional**

In `default_layout()`, change:

```python
            elif widget_type in (
                "4thealth.device_review_posture",
                "4thealth.rule_hygiene",
                "4tlog.silent_devices",
            ):
```

to:

```python
            elif widget_type in (
                "4thealth.device_review_posture",
                "4thealth.rule_hygiene",
                "4thealth.license_status",
                "4tlog.silent_devices",
            ):
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_widgets.py -v -k license_status`
Expected: PASS (6 tests)

- [ ] **Step 9: Run the full widgets test file**

Run: `uv run pytest tests/test_widgets.py -v`
Expected: PASS, no regressions — in particular every existing `device_review` freshness/staleness test, since Step 3 changed shared code in `_freshness_collected_at()`.

- [ ] **Step 10: Run the full metric_extract test file again**

Run: `uv run pytest tests/test_metric_extract.py -v`
Expected: PASS, including `test_every_catalog_field_has_an_extractor` (now green — `license_status` has both a catalog entry and an extractor).

- [ ] **Step 11: Lint check**

Run: `uv run ruff check app/widgets.py && uv run ruff format --check app/widgets.py`
Expected: clean

- [ ] **Step 12: Commit**

```bash
git add app/widgets.py tests/test_widgets.py
git commit -m "feat: add License Status Board widget

Generalizes _freshness_collected_at()'s device_review-specific nested
collected_at lookup to work for any field group shaped the same way,
so license_status's freshness tracking can reuse it."
```

---

### Task 5: `board.py` — Trend Board grouping

**Files:**
- Modify: `app/board.py` (`WIDGET_DOMAIN`)
- Test: `tests/test_board.py` (append, if such assertions exist there — otherwise add a minimal one)

**Interfaces:**
- Consumes: nothing new.
- Produces: `WIDGET_DOMAIN["4thealth.license_status"] == "lifecycle"`.

- [ ] **Step 1: Check whether `tests/test_board.py` already asserts full `WIDGET_DOMAIN` coverage**

Run: `grep -n "WIDGET_DOMAIN" tests/test_board.py`

If a test asserts every `WIDGET_CATALOG` key has a `WIDGET_DOMAIN` entry (similar to `metric_extract.py`'s `test_every_catalog_field_has_an_extractor`), that test will already be failing after Task 4 — this step's Step 3 below fixes it. If no such test exists, write one now:

```python
def test_every_catalog_widget_has_a_board_domain():
    from app.widgets import WIDGET_CATALOG
    from app.board import WIDGET_DOMAIN

    for widget_type in WIDGET_CATALOG:
        assert widget_type in WIDGET_DOMAIN, f"missing WIDGET_DOMAIN entry for {widget_type!r}"
```

(Skip adding this if an equivalent test is already present — don't duplicate.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_board.py -v -k board_domain`
Expected: FAIL — `4thealth.license_status` missing from `WIDGET_DOMAIN`.

- [ ] **Step 3: Add the entry**

In `app/board.py`, add to `WIDGET_DOMAIN` (after the existing `"4thealth.version_breakdown": "lifecycle",` line):

```python
    "4thealth.license_status": "lifecycle",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_board.py -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Lint check**

Run: `uv run ruff check app/board.py && uv run ruff format --check app/board.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add app/board.py tests/test_board.py
git commit -m "feat: group the License Status widget under the lifecycle domain on the Board"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/integrations.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a `license_status` section**

In `docs/integrations.md`, immediately after the existing `lifecycle` section (ends right before the `by_adom` section — look for the paragraph starting `` `by_adom` is a nested object ``), insert:

````markdown
`license_status` is a nested object (from 4thealth-plus's
`app.license_status_cache` daily sweep; absent on sources that haven't
shipped it yet) containing fleet-wide FortiGate license status:

```json
{
  "license_status": {
    "devices_licensed": 40,
    "devices_expired": 2,
    "devices_unknown": 1,
    "details": [
      {"device": "fw-branch12", "adom": "Corp", "status": "expired", "expires": "2026-08-01"},
      {"device": "fw-branch7", "adom": "Corp", "status": "unknown", "expires": null}
    ],
    "collected_at": "2026-09-16T03:00:00Z"
  }
}
```

- `devices_licensed` / `devices_expired` / `devices_unknown` — fleet-wide
  device counts by license classification, from one FMG proxy call per
  device (no bulk endpoint exists) run on a daily cadence.
- `details` — only non-`"licensed"` devices ever appear here (expired or
  unknown) — same "surface problems, not clean state" convention as
  `lifecycle.models_unknown`. A clean fleet produces an empty list.
- `collected_at` — timestamp of the daily sweep.
- **Informational only — does not feed any domain score.** Unlike
  `version_compliance_pct`/`devices_on_eol_version`/`lifecycle.devices_hw_eos`,
  which are the three real inputs to the Lifecycle & Support domain's score
  formula, `license_status.devices_expired`/`devices_unknown` are shown as
  additional rows on that domain's detail page and as a Board widget, but
  never change the computed grade.

`extract_all()` flattens this into `license_status.devices_licensed`,
`license_status.devices_expired`, and `license_status.devices_unknown`
metric_points; `license_status` and `license_status.details` themselves are
composite and always extract to nothing (same pattern as `lifecycle`/
`lifecycle.models_unknown`).
````

Then update the "Optional `details` lists" table (in the `### schema_version 2` section) by adding a row:

```markdown
| `license_status`                | `details`                                  | `{device, adom, status, expires}` |
```

And update the closing sentence that lists every nested/collection-tracking field (currently `` Along with `version_breakdown`, `device_review`, `rule_hygiene`, `psirt`, `change_control`, `lifecycle`, `by_adom`, `infra`, and `ai_usage_24h`, `` ) to also include `license_status`:

```markdown
Along with `version_breakdown`, `device_review`, `rule_hygiene`, `psirt`, `change_control`, `lifecycle`, `license_status`, `by_adom`, `infra`, and `ai_usage_24h`,
```

- [ ] **Step 2: Add a widget entry to the `4thealth` field table near the top of the doc**

In the same file's earlier `**4thealth**` field table, add a row after the `lifecycle` row:

```markdown
| `license_status`              | License Status                  |
```

- [ ] **Step 3: Commit**

```bash
git add docs/integrations.md
git commit -m "docs: document the license_status executive-summary field group"
```

---

### Task 7: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS, all tests green.

- [ ] **Step 2: Run lint across the whole repo**

Run: `uv run ruff check .`
Expected: clean

- [ ] **Step 3: Manual end-to-end check (requires the companion 4thealth-plus plan already deployed to a reachable instance)**

1. In the running 4thealth-plus instance, confirm `GET /external/api/executive/summary` returns a `license_status` key (see the companion plan's Task 7, Step 3).
2. In 4tExecutive Admin → Sources, use "Refresh now" on that source.
3. Confirm the Board shows a "License Status" row grouped under Lifecycle & Support, with the correct RAG color.
4. Open the Lifecycle & Support domain detail page — confirm "Devices with expired license" / "Devices with unknown license status" rows appear with the right counts.
5. Open `/devices` (fleet drilldown) — confirm any expired/unknown-license devices appear with the right `detail_text`.

If no reachable 4thealth-plus instance with the new field is available yet, skip this step and note it in the PR description as "pending live verification."

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feature/license-status-widget
```
