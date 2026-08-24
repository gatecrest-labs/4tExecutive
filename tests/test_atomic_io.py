import json

from app.atomic_io import atomic_write_json, read_json


def test_atomic_write_json_creates_file(tmp_path):
    path = tmp_path / "data.json"
    atomic_write_json(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}


def test_atomic_write_json_overwrites_existing(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("old")
    atomic_write_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 2}


def test_read_json_returns_default_when_missing(tmp_path):
    path = tmp_path / "missing.json"
    assert read_json(path, default={}) == {}


def test_read_json_returns_default_on_corrupt_file(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    assert read_json(path, default={"fallback": True}) == {"fallback": True}


def test_read_json_reads_existing_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"a": 1}))
    assert read_json(path) == {"a": 1}
