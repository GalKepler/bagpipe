"""Load machine-specific config from config/local.yaml.

config/local.yaml is git-ignored — it holds real paths and secrets. Code must
read paths/credentials only through this module, never hardcode them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_CONFIG_PATH = REPO_ROOT / "config" / "local.yaml"


class ConfigError(RuntimeError):
    pass


@lru_cache
def load_config(path: Path = LOCAL_CONFIG_PATH) -> dict:
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy config/local.yaml.example to config/local.yaml "
            "and fill in your machine's paths."
        )
    with path.open() as f:
        return yaml.safe_load(f)


def get_path(key: str) -> Path:
    """Look up a path under config['paths'][key]."""
    cfg = load_config()
    try:
        value = cfg["paths"][key]
    except KeyError as e:
        raise ConfigError(f"paths.{key} not set in {LOCAL_CONFIG_PATH}") from e
    if value is None:
        raise ConfigError(f"paths.{key} is null in {LOCAL_CONFIG_PATH}")
    return Path(value)
