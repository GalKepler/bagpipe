"""Shared helper for the two `apptainer run cat12.sif` call sites
(`bagpipe.app.pipeline.segment`, `bagpipe.preprocess.cat12_cohort`) — kept in
one place so a fix here can't drift between the inference and cohort
callers, per CLAUDE.md's "fix once, where all callers route through" rule.
"""

from __future__ import annotations

import os


def apptainer_env() -> dict[str, str]:
    """Environment for an `apptainer run` subprocess invoking `cat12.sif`.

    Apptainer passes the host environment through to the container by
    default; on any machine with a graphical desktop session, that includes
    a live `DISPLAY`/`XAUTHORITY`. CAT12's compiled MATLAB runtime then tries
    to initialize a Swing/AWT desktop against that (unreachable-from-inside-
    the-container) X display, fails ("PostVMInit failed to initialize
    com.mathworks.mwswing.MJStartupForDesktop", "Could not find
    java/awt/Component"), and `cat_standalone.sh` swallows the error and
    still exits 0 — surfacing as an instant (~20s) failure with only the
    environment-setup banner in stdout, `proc.returncode == 0`, and no
    `report/`/`label/` output.

    Root-caused 2026-09-03: reproduced identically from an interactive
    desktop shell (DISPLAY set), absent when launched from a session without
    one — the cohort reprocess's own tmux session happened not to have
    DISPLAY exported, so this was silently invisible there while breaking
    every inference and `bag preprocess repro-test` run launched from a
    desktop terminal (14/14 repro subjects failed identically before this
    fix). Strip both vars rather than the whole environment — `--cleanenv`
    also drops things apptainer itself may want (e.g. `APPTAINER_*` config).
    """
    return {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "XAUTHORITY")}
