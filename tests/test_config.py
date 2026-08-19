import pytest

from bagpipe.core.config import ConfigError, load_config


def test_missing_config_raises(tmp_path):
    load_config.cache_clear()
    missing = tmp_path / "local.yaml"
    with pytest.raises(ConfigError):
        load_config(missing)


def test_get_path_reads_from_config(tmp_path):
    load_config.cache_clear()
    cfg_path = tmp_path / "local.yaml"
    cfg_path.write_text("paths:\n  bids_root: /some/path\n")
    assert load_config(cfg_path)["paths"]["bids_root"] == "/some/path"
