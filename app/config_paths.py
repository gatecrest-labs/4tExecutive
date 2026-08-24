"""Central config directory paths and first-run bootstrap."""

from __future__ import annotations

import shutil
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
EXAMPLES_DIR = CONFIG_DIR / "examples"


def bootstrap_config() -> None:
    """Copy any missing config/examples/*.example.json to config/<name>.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not EXAMPLES_DIR.exists():
        return
    for example in EXAMPLES_DIR.glob("*.example.json"):
        target_name = example.name.replace(".example.json", ".json")
        target = CONFIG_DIR / target_name
        if not target.exists():
            shutil.copy(example, target)
