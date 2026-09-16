"""Devices drill-down: per-domain and fleet-wide device lists extracted from
the latest "summary" snapshot of every enabled source, mirroring the
"read latest snapshot per enabled source of the right system, merge into
one list" pattern app.domains.get_infra_devices() already uses for the
Infrastructure card.

Every details list this module reads (device_review.details,
rule_hygiene.details, version_breakdown's per-version "devices", top-level
silent_devices, psirt.top_advisory.devices) is OPTIONAL and may be absent
from any given payload — every lookup below uses `.get(...)`/isinstance
guards and never assumes presence, so a partial or empty payload degrades to
an empty list rather than raising.

Kept free of Flask imports (pure data functions), matching app/domains.py's
separation of data logic from app/routes/scorecard_routes.py.
"""

from __future__ import annotations

import csv
import io

from app.domains import DOMAINS
from app.metrics_db import get_latest
from app.sources import list_sources


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _rows_posture(value: dict) -> list[dict]:
    entries = _as_list(_as_dict(value.get("device_review")).get("details"))
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        failed_checks = _as_list(entry.get("failed_checks"))
        row["detail_text"] = f"{len(failed_checks)} failed checks ({entry.get('worst_severity')})"
        rows.append(row)
    return rows


def _rows_hygiene(value: dict) -> list[dict]:
    entries = _as_list(_as_dict(value.get("rule_hygiene")).get("details"))
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        # 4thealth-plus's rule_hygiene.details[].findings is a list of
        # finding objects (policy_id, check, detail, ...), not a count.
        row["detail_text"] = f"{len(_as_list(entry.get('findings')))} findings"
        rows.append(row)
    return rows


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
    # License status — devices still "licensed" but expiring within 90 days
    # (see 4thealth-plus's app.license_status_cache.compute_expiring_soon()).
    # Distinct from the "details" loop above, which only ever lists devices
    # already expired/unknown -- these are still-valid licenses that need
    # review before they become one of those.
    for entry in _as_list(_as_dict(value.get("license_status")).get("expiring_soon")):
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        days_until = entry.get("days_until")
        expires = entry.get("expires")
        if isinstance(days_until, (int, float)):
            row["detail_text"] = f"license expires in {days_until:.0f} days ({expires})"
        else:
            row["detail_text"] = (
                f"license expires soon ({expires})" if expires else "license expiring soon"
            )
        rows.append(row)
    return rows


def _rows_logging(value: dict) -> list[dict]:
    # 4tlog's executive-summary payload exposes this list as
    # "devices_silent_details" (see 4tlog's app/log_stats_cache.py
    # build_silent_details()), not "silent_devices".
    rows = []
    for entry in _as_list(value.get("devices_silent_details")):
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        last_log_at = entry.get("last_log_at")
        # 4tlog's devices_silent_details currently always sends
        # last_log_at: null (see that repo's silent-devices-proxy-spike
        # doc) — render that as "no recent logs" rather than the literal
        # string "None".
        row["detail_text"] = f"last log {last_log_at}" if last_log_at else "no recent logs"
        rows.append(row)
    return rows


def _rows_vulnerability(value: dict) -> list[dict]:
    top_advisory = _as_dict(_as_dict(value.get("psirt")).get("top_advisory"))
    advisory_id = top_advisory.get("advisory_id") or top_advisory.get("id") or top_advisory.get("cve") or "advisory"
    rows = []
    for entry in _as_list(top_advisory.get("devices")):
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        workaround = "workaround applied" if entry.get("workaround_applied") else "no workaround"
        row["detail_text"] = f"{advisory_id} ({workaround})"
        rows.append(row)
    return rows


# Domain -> details-list-extraction function. Domains with no mapped details
# list (e.g. "availability") are simply absent here; get_domain_devices()
# guards on that with a dict.get(name, None) below.
_DOMAIN_ROW_FUNCS = {
    "posture": _rows_posture,
    "hygiene": _rows_hygiene,
    "lifecycle": _rows_lifecycle,
    "logging": _rows_logging,
    "vulnerability": _rows_vulnerability,
}

# Domain -> the fleet-row field it populates on get_fleet_devices()'s output.
_DOMAIN_FLEET_FIELD = {
    "posture": "posture",
    "hygiene": "hygiene",
    "lifecycle": "eol",
    "logging": "silent",
    "vulnerability": "vulnerability",
}

DOMAIN_DEVICE_CSV_COLUMNS: list[tuple[str, str]] = [
    ("device_label", "Device"),
    ("adom", "ADOM"),
    ("source_name", "Source"),
    ("detail_text", "Detail"),
]

FLEET_DEVICE_CSV_COLUMNS: list[tuple[str, str]] = [
    ("device", "Device"),
    ("adom", "ADOM"),
    ("posture", "Posture"),
    ("hygiene", "Hygiene"),
    ("eol", "EOL"),
    ("silent", "Silent"),
    ("vulnerability", "PSIRT"),
]


def get_domain_devices(name: str) -> list[dict]:
    """Every device-level row for one domain, merged across every enabled
    source of that domain's system, in list_sources() order. Returns []
    when the domain has no details-list mapping (e.g. "availability") or
    when nothing is present in any source's snapshot yet."""
    row_func = _DOMAIN_ROW_FUNCS.get(name)
    if row_func is None:
        return []
    system = DOMAINS.get(name, {}).get("system")
    if system is None:
        return []
    rows: list[dict] = []
    for source in list_sources():
        if not source.get("enabled", True) or source.get("system") != system:
            continue
        latest = get_latest(source["id"], "summary")
        if latest is None:
            continue
        value = _as_dict(latest["value"])
        for entry in row_func(value):
            row = dict(entry)
            row["source_name"] = source["name"]
            row["device_label"] = (
                row.get("device") or row.get("devname") or row.get("package") or row.get("devid") or "—"
            )
            rows.append(row)
    return rows


def get_fleet_devices() -> list[dict]:
    """One row per distinct device across every domain's details lists,
    keyed by (device_or_devname, adom) -- falling back to the bare name
    when adom is absent (silent-device rows don't carry one). A device with
    no entries in any list is never synthesized."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for domain_name, field in _DOMAIN_FLEET_FIELD.items():
        for row in get_domain_devices(domain_name):
            device = row["device_label"]
            adom = row.get("adom")
            key = (device, adom) if adom else (device,)
            if key not in merged:
                merged[key] = {
                    "device": device,
                    "adom": adom,
                    "posture": None,
                    "hygiene": None,
                    "eol": None,
                    "silent": None,
                    "vulnerability": None,
                }
                order.append(key)
            merged[key][field] = row["detail_text"]
    return [merged[key] for key in order]


def devices_to_csv(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    """Small stdlib-csv helper: columns is [(key, header)] pairs so both the
    per-domain table and the fleet page can reuse it with their own column
    sets."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([row.get(key, "") if row.get(key) is not None else "" for key, _ in columns])
    return buffer.getvalue()
