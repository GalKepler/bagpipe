"""_delete_imaging — deletion-by-default privacy behavior
(docs/design_inference_pipeline.md § Privacy by default).
"""

from __future__ import annotations

from bagpipe.app.queue import _delete_imaging


def test_delete_imaging_removes_only_imaging_dirs(tmp_path):
    for sub in ("anon", "cat12", "features", "predict", "report"):
        d = tmp_path / sub
        d.mkdir()
        (d / "x.txt").write_text("data")
    (tmp_path / "manifest.json").write_text("{}")

    _delete_imaging(tmp_path)

    assert not (tmp_path / "anon").exists()
    assert not (tmp_path / "cat12").exists()
    assert (tmp_path / "features").exists()
    assert (tmp_path / "predict").exists()
    assert (tmp_path / "report").exists()
    assert (tmp_path / "manifest.json").exists()


def test_delete_imaging_ignores_missing_dirs(tmp_path):
    _delete_imaging(tmp_path)  # no anon/ or cat12/ present — must not raise
