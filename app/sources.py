"""Source registry: named source instances 4tExecutive polls for metrics."""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

SOURCES_PATH = CONFIG_DIR / "sources.json"


def _load() -> list[dict]:
    return read_json(SOURCES_PATH, default={"sources": []}).get("sources", [])


def _save(sources: list[dict]) -> None:
    atomic_write_json(SOURCES_PATH, {"sources": sources})


def list_sources() -> list[dict]:
    return _load()


def get_source(source_id: str) -> dict | None:
    for source in _load():
        if source["id"] == source_id:
            return source
    return None


def add_source(
    id: str,
    system: str,
    name: str,
    base_url: str,
    token: str,
    poll_interval_minutes: int = 15,
    enabled: bool = True,
) -> dict:
    sources = _load()
    if any(s["id"] == id for s in sources):
        raise ValueError(f"source id already exists: {id}")
    record = {
        "id": id,
        "system": system,
        "name": name,
        "base_url": base_url,
        "token": token,
        "poll_interval_minutes": poll_interval_minutes,
        "enabled": enabled,
    }
    sources.append(record)
    _save(sources)
    return record


def update_source(source_id: str, **fields) -> dict | None:
    sources = _load()
    for source in sources:
        if source["id"] == source_id:
            source.update(fields)
            _save(sources)
            return source
    return None


def delete_source(source_id: str) -> None:
    sources = [s for s in _load() if s["id"] != source_id]
    _save(sources)


def source_headers(source: dict) -> dict:
    return {"Authorization": f"Bearer {source['token']}"}
