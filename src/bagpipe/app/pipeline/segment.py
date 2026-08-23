"""segment stage — wraps the CAT12 Apptainer container invocation.
docs/design_inference_pipeline.md § Stage specifications: segment,
docs/cat12_container_spec.md §5 invocation contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from bagpipe.app.pipeline.base import ErrorCode, PipelineError, StageResult
from bagpipe.core.config import get_path

DEFAULT_TIMEOUT_S = 90 * 60


class SegmentStage:
    name = "segment"

    def __init__(self, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s

    def run(self, workspace: Path, manifest) -> StageResult:  # noqa: ARG002
        anon_t1w = workspace / "anon" / "T1w.nii.gz"
        cat12_dir = workspace / "cat12"
        cat12_dir.mkdir(exist_ok=True)
        staged = cat12_dir / "T1w.nii.gz"
        staged.write_bytes(anon_t1w.read_bytes())

        image = get_path("cat12_apptainer_image")
        try:
            proc = subprocess.run(
                [
                    "apptainer",
                    "run",
                    "--writable-tmpfs",  # required — the container still needs a
                    # writable overlay for CAT12's own scratch/report files, even
                    # though the CTF is now pre-extracted into the image itself
                    # (cat12.def %post) rather than self-extracted at runtime.
                    "--env",
                    # Apptainer leaks the host's $SHELL into the container by
                    # default; MATLAB's compiled runtime uses $SHELL to spawn
                    # every external system() call (every CAT_* surface/thickness
                    # binary among them). The host here runs zsh, which doesn't
                    # exist in the Ubuntu 22.04 container — every such call failed
                    # with execve ENOENT, surfaced by CAT12 as a misleading
                    # generic "File permissions/binary compat/antivirus" error.
                    # Root-caused via strace 2026-08-23. Segmentation itself
                    # doesn't hit this (no surface calls), but pin it regardless.
                    "SHELL=/bin/bash",
                    "--bind",
                    f"{cat12_dir}:/data",
                    str(image),
                    "/data/T1w.nii.gz",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise PipelineError(
                ErrorCode.CAT12_TIMEOUT,
                f"CAT12 exceeded {self.timeout_s}s timeout",
                user_message="Processing your scan took too long. Please try again later.",
            ) from e

        # CAT12's classic (BIDS.BIDSno=0) output mode writes into mri/,
        # report/, label/ subdirs next to the input — confirmed via a real
        # smoke test 2026-08-21 ("Segmentations are saved in /data/mri",
        # "Reports are saved in /data/report"). An earlier "fix" here
        # assumed flat output based on the real SNBB training tree, but
        # that tree was produced via a DIFFERENT code path (BIDS.BIDSyes
        # redirect mode, which does flatten) — comparing the wrong thing.
        # Classic mode's subdirs are real; reverted.
        #
        # proc.returncode can't be trusted as a success signal —
        # cat_standalone.sh unconditionally `exit 0`s in standalone mode
        # regardless of whether the underlying MCR executable actually
        # succeeded (confirmed by reading it directly) — only real output
        # existence is a valid check.
        cat_xml = cat12_dir / "report" / "cat_T1w.xml"
        catroi_xml = cat12_dir / "label" / "catROI_T1w.xml"
        if not cat_xml.exists() or not catroi_xml.exists():
            raise PipelineError(
                ErrorCode.CAT12_FAILED,
                f"CAT12 run did not produce expected output (rc={proc.returncode}): "
                f"{proc.stdout[-2000:]}",
                user_message="We couldn't process your scan. Please check it's a valid T1w image.",
            )

        return StageResult(
            outputs={
                "cat_xml": str(cat_xml.relative_to(workspace)),
                "catroi_xml": str(catroi_xml.relative_to(workspace)),
            },
            metrics={"cat12_image": str(image)},
        )
