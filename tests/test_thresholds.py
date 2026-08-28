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
