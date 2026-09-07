"""Session-wide synthetic config.

`config/local.yaml` holds real machine paths and secrets and is git-ignored,
so it does not exist in CI — but several app modules read it at *import*
time (`bagpipe.app.queue` builds its `SqliteHuey` at module scope), which
made `tests/test_api.py` and `tests/test_queue.py` fail during collection
and took the whole run down with them.

This installs a synthetic config before any test module is imported, derived
from `config/local.yaml.example` so a newly-added key is picked up
automatically, with every path redirected into a temp directory. Tests are
hermetic either way: they never read a developer's real config, and never
touch a real data location (CLAUDE.md — tests and CI use synthetic data
only, and must never require real data to pass).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from bagpipe.core import config as _config

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="bagpipe-tests-"))


def _synthetic_config() -> dict:
    cfg = yaml.safe_load((_config.REPO_ROOT / "config" / "local.yaml.example").read_text())
    # Every configured path becomes a throwaway one under a single temp root,
    # so a test that accidentally reaches the filesystem writes there rather
    # than into /mnt/62 or /media/storage.
    cfg["paths"] = {
        key: (str(_TMP_ROOT / key) if value is not None else None)
        for key, value in cfg["paths"].items()
    }
    return cfg


_CONFIG_PATH = _TMP_ROOT / "local.yaml"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
_CONFIG_PATH.write_text(yaml.safe_dump(_synthetic_config()))

# `load_config` resolves this at call time (see bagpipe.core.config), so
# repointing it here covers the import-time readers too.
_config.LOCAL_CONFIG_PATH = _CONFIG_PATH
_config.load_config.cache_clear()
