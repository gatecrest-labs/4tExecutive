import json

from app.config_paths import bootstrap_config


def test_bootstrap_copies_missing_examples(tmp_config_dir):
    config_dir, examples_dir = tmp_config_dir
    (examples_dir / "sources.example.json").write_text(json.dumps({"sources": []}))

    bootstrap_config()

    assert (config_dir / "sources.json").exists()
    assert json.loads((config_dir / "sources.json").read_text()) == {"sources": []}


def test_bootstrap_does_not_overwrite_existing_file(tmp_config_dir):
    config_dir, examples_dir = tmp_config_dir
    (examples_dir / "sources.example.json").write_text(json.dumps({"sources": []}))
    (config_dir / "sources.json").write_text(json.dumps({"sources": [{"id": "keep-me"}]}))

    bootstrap_config()

    assert json.loads((config_dir / "sources.json").read_text()) == {
        "sources": [{"id": "keep-me"}]
    }
