"""Group membership and per-tab access control."""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

GROUPS_PATH = CONFIG_DIR / "groups.json"


def _load_groups() -> dict:
    return read_json(GROUPS_PATH, default={})


def _save_groups(groups: dict) -> None:
    atomic_write_json(GROUPS_PATH, groups)


def get_user_groups(username: str) -> list[str]:
    groups = _load_groups()
    return [name for name, cfg in groups.items() if username in cfg.get("members", [])]


def list_group_names() -> list[str]:
    return list(_load_groups().keys())


def user_has_tab(username: str, tab: str) -> bool:
    groups = _load_groups()
    for name in get_user_groups(username):
        if tab in groups.get(name, {}).get("allowed_tabs", []):
            return True
    return False


def set_user_groups(username: str, group_names: list[str]) -> None:
    groups = _load_groups()
    wanted = set(group_names)
    for name, cfg in groups.items():
        members = set(cfg.get("members", []))
        if name in wanted:
            members.add(username)
        else:
            members.discard(username)
        cfg["members"] = sorted(members)
    _save_groups(groups)
