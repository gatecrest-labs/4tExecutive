import pytest

import app.config_paths as config_paths


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    examples_dir = config_dir / "examples"
    examples_dir.mkdir(parents=True)
    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths, "EXAMPLES_DIR", examples_dir)
    return config_dir, examples_dir
