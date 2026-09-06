"""Regression test for the DISPLAY/XAUTHORITY leak into `apptainer run
cat12.sif` (docs/CLAUDE.md Phase 4, 2026-09-03 launch-hardening update):
CAT12's MATLAB runtime tries to start a desktop Java session against a
leaked host DISPLAY, fails, and `cat_standalone.sh` masks it with exit 0 —
every real invocation (app inference + `bag preprocess repro-test`) failed
identically at segment before this fix.
"""

from bagpipe.core.apptainer import apptainer_env


def test_strips_display_and_xauthority(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setenv("XAUTHORITY", "/run/user/1000/gdm/Xauthority")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = apptainer_env()

    assert "DISPLAY" not in env
    assert "XAUTHORITY" not in env
    assert env["PATH"] == "/usr/bin:/bin"


def test_no_op_when_unset(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("XAUTHORITY", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = apptainer_env()

    assert env["PATH"] == "/usr/bin:/bin"
