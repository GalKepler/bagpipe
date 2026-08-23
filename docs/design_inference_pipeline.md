# Pillar 4 — Inference Pipeline: Stage Interface & Job Manifest

> Addition to `docs/DESIGN.md` (proposed section: **4.x Inference Pipeline Architecture**).
> Status: draft v0.1. Companion document: `docs/cat12_container_spec.md`.

## Scope

This section specifies the internal architecture of the preprocessing-to-inference pipeline that turns a user-uploaded T1w image (DICOM or NIfTI) into a BAG report. It covers the stage abstraction, the per-job workspace layout, the job manifest schema, error taxonomy, and the worker execution model. It deliberately excludes the FastAPI request layer, email delivery, and report rendering, which are specified elsewhere.

## Design principles

1. **Training–inference parity.** Every preprocessing step at inference must be identical to the pipeline that produced training features. Parity is enforced by (a) containerizing CAT12 with pinned versions, (b) recording all version identifiers in the manifest, and (c) a reproducibility test (see companion spec) that gates any container change.
2. **One job, one workspace, one manifest.** All state for a job lives under a single directory. The manifest is the sole source of truth about what happened; the SQLite queue row only tracks scheduling state.
3. **Fail early, fail loudly.** Cheap validation precedes expensive computation. Any stage failure produces a typed error code that maps to a user-facing message; no stage silently imputes or coerces.
4. **Stages are restartable, jobs are not resumable (v1).** A failed job is rerun from scratch. Stage-level resume is a possible v2 optimization; the manifest structure already supports it (per-stage status), but v1 keeps the worker simple.
5. **Privacy by default.** The workspace is deleted after report delivery unless the user opted into retention. Anonymization runs before any output that could persist.

## Stage graph

Linear, no branching (v1):

```
ingest → anonymize → segment (CAT12) → qc_gate → extract_features → predict → report
```

Each stage reads only from the workspace, writes only to its own output subdirectory, and appends its record to the manifest. Stages never communicate except through files.

## Package layout

```
src/bagpipe/app/
├── pipeline/
│   ├── __init__.py
│   ├── base.py          # Stage protocol, StageResult, PipelineError taxonomy
│   ├── runner.py        # Executes the stage sequence for one job, owns the manifest
│   ├── ingest.py
│   ├── anonymize.py
│   ├── segment.py       # wraps the CAT12 container invocation
│   ├── qc.py
│   ├── features.py
│   ├── predict.py
│   └── report.py
├── worker.py            # queue polling loop; spawns runner per job
└── models.py            # pydantic models: Manifest, StageRecord, JobInput, ...
```

## Stage interface

Stages implement a minimal protocol. Keeping the interface to a single method with a workspace argument makes stages trivially testable against fixture directories.

```python
# base.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol


class ErrorCode(str, Enum):
    # ingest
    UNSUPPORTED_FORMAT = "unsupported_format"
    DICOM_CONVERSION_FAILED = "dicom_conversion_failed"
    NOT_T1W = "not_t1w"
    GEOMETRY_INVALID = "geometry_invalid"      # dims/voxel size out of bounds
    MULTIPLE_SERIES_AMBIGUOUS = "multiple_series_ambiguous"
    # segment
    CAT12_FAILED = "cat12_failed"
    CAT12_TIMEOUT = "cat12_timeout"
    # qc
    QC_BELOW_THRESHOLD = "qc_below_threshold"
    # features
    FEATURE_SCHEMA_MISMATCH = "feature_schema_mismatch"
    ROI_PARSE_FAILED = "roi_parse_failed"
    # predict
    AGE_OUT_OF_RANGE = "age_out_of_range"
    MODEL_LOAD_FAILED = "model_load_failed"
    # generic
    INTERNAL = "internal"


class PipelineError(Exception):
    def __init__(self, code: ErrorCode, message: str, user_message: str | None = None):
        self.code = code
        self.message = message              # logged, technical
        self.user_message = user_message    # shown in report/email; safe wording
        super().__init__(message)


@dataclass
class StageResult:
    outputs: dict[str, str] = field(default_factory=dict)   # name -> path relative to workspace
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Stage(Protocol):
    name: str

    def run(self, workspace: Path, manifest: "Manifest") -> StageResult:
        """Execute against the job workspace. Raise PipelineError on failure.

        May read manifest entries of earlier stages (e.g. predict reads the
        feature file path recorded by extract_features). Must not mutate the
        manifest directly; the runner records the StageResult.
        """
        ...
```

The **runner** wraps each stage: records start/end timestamps, catches `PipelineError` (typed failure) vs. any other exception (mapped to `INTERNAL`), writes the updated manifest atomically after every stage (write to `manifest.json.tmp`, then `os.replace`), and stops at the first failure.

## Workspace layout

```
jobs/{job_id}/
├── manifest.json
├── input/                  # raw upload, exactly as received (zip or nii[.gz])
├── ingest/                 #  converted, validated T1w:  T1w.nii.gz + sidecar.json
├── anon/                   #  header-stripped (and defaced, if retention opted in)
├── cat12/                  #  CAT12 output (classic/BIDS.BIDSno=0 mode) —
                            #  mri/, report/, label/ subdirs next to the
                            #  input (cat12/report/cat_T1w.xml,
                            #  cat12/label/catROI_T1w.xml, cat12/mri/
                            #  mwp1T1w.nii). Confirmed via a real smoke
                            #  test, 2026-08-21 ("Segmentations are saved
                            #  in /data/mri", "Reports are saved in
                            #  /data/report") — an earlier draft of this
                            #  doc claimed flat output, comparing against
                            #  the real SNBB training tree, which turned
                            #  out to be produced via a DIFFERENT code path
                            #  (BIDS.BIDSyes redirect mode, which *does*
                            #  flatten) — wrong comparison, now corrected.
├── features/               #  features.parquet (long format, matching DB schema)
├── predict/                #  prediction.json
└── report/                 #  report.pdf / report.html
```

`input/` is deleted immediately after `anonymize` succeeds regardless of retention setting; retention (opt-in) applies to `anon/` and `cat12/` only. Everything is deleted after delivery unless opted in.

## Job manifest schema

The manifest is the audit trail and the contract between stages. Pydantic models, serialized to `manifest.json`.

```json
{
  "schema_version": "1.0",
  "job_id": "8f4c2a1e-...",
  "created_at": "2026-08-21T14:03:22Z",
  "status": "succeeded",
  "input": {
    "upload_format": "dicom_zip",
    "upload_sha256": "…",
    "upload_size_bytes": 48211004,
    "chronological_age": 34.2,
    "sex": "F",
    "retention_opt_in": false
  },
  "environment": {
    "bagpipe_version": "0.3.1",
    "bagpipe_git_sha": "a1b2c3d",
    "cat12_image": "ghcr.io/…/bagpipe-cat12@sha256:…",
    "cat12_version": "12.9_R2023b",
    "model_id": "stacked_ensemble_v1",
    "model_sha256": "…",
    "bias_correction_id": "delange_v1",
    "feature_schema_id": "cat12_neuromorphometrics_v1",
    "atlas_id": "custom_atlas_v2"
  },
  "stages": [
    {
      "name": "ingest",
      "status": "succeeded",
      "started_at": "…",
      "ended_at": "…",
      "duration_s": 41.2,
      "outputs": {"t1w": "ingest/T1w.nii.gz", "sidecar": "ingest/sidecar.json"},
      "metrics": {
        "n_series_found": 3,
        "selected_series": "MPRAGE_sag",
        "voxel_size_mm": "1.0x1.0x1.0",
        "dims": "176x256x256"
      },
      "warnings": []
    },
    {
      "name": "qc_gate",
      "status": "succeeded",
      "metrics": {"cat12_iqr": 87.4, "iqr_grade": "B+", "threshold": 70.0}
    },
    {
      "name": "predict",
      "status": "succeeded",
      "metrics": {
        "predicted_age": 38.9,
        "bag_raw": 4.7,
        "bag_corrected": 3.1,
        "model_mae_reference": 3.6
      }
    }
  ],
  "error": null
}
```

On failure, `status` is `"failed"` and `error` carries `{"stage": "...", "code": "...", "message": "...", "user_message": "..."}`.

Notes on specific fields:

- **`environment` is populated once at job start** from the deployed configuration, never inferred post hoc. `feature_schema_id` names the exact ordered feature list the model expects; `extract_features` hard-fails with `FEATURE_SCHEMA_MISMATCH` if the parsed ROI set doesn't produce it exactly (no reindexing, no NaN-filling).
- **`chronological_age` and `sex`** are user inputs collected at upload. `predict` enforces the training-support age range (configured per model, e.g. `[18, 90]`) and raises `AGE_OUT_OF_RANGE` outside it. Consider a soft band (flagged in report) near the edges vs. hard rejection outside.
- **`model_mae_reference`** is baked into the model registry entry so the report can contextualize BAG magnitude against test-set MAE, consistent with the reporting standards used elsewhere in bagpipe.

## Stage specifications (v1)

**ingest.** Detect format by extension/magic bytes. DICOM zip → extract to temp, run `dcm2niix`, enumerate produced series. Select the T1w series by: (1) sidecar `SeriesDescription`/`ProtocolName` regex (mprage|t1|tfl|spgr, case-insensitive), (2) 3D check (≥ 100 slices, no 4th dim), (3) contrast heuristic — median intensity in an eroded central WM-ish region vs. cortical ribbon proxy is expensive pre-segmentation, so v1 uses a cheaper proxy: histogram shape check (T2w/FLAIR reject). If more than one candidate survives, raise `MULTIPLE_SERIES_AMBIGUOUS` and ask the user to upload a single series. NIfTI uploads skip conversion but pass identical validation. Geometry bounds: voxel size 0.5–1.5 mm iso-ish (max anisotropy ratio 2), matrix ≥ 120 in each axis.

**anonymize.** Rewrite NIfTI header retaining only geometry-critical fields (`pixdim`, affine, datatype); clear `descrip`, `aux_file`, and any extensions. If `retention_opt_in`, additionally deface (e.g. `pydeface`) before storage. Delete `input/`.

**segment.** Invoke the CAT12 container (see companion spec) with the workspace bind-mounted, and `--writable-tmpfs` — required, not optional: without it MCR can't extract its CTF archive into the (otherwise read-only) image filesystem and fails immediately (confirmed via a real smoke test, 2026-08-21). Enforce wall-clock timeout (default 90 min) in Python (`subprocess` timeout + process-group kill) — Apptainer has no Docker-style `--memory` cap, unlike an earlier draft of this doc assumed; see `docs/cat12_container_spec.md` §5. **Exit code cannot be trusted as a success signal** — `cat_standalone.sh` unconditionally exits 0 in standalone mode regardless of whether the underlying MCR executable actually succeeded (confirmed by reading it directly). Missing expected outputs (`cat12/report/cat_*.xml`, `cat12/label/catROI_*.xml`) is the only valid failure signal → `CAT12_FAILED` with the tail of CAT12's own stdout attached to `message`.

**qc_gate.** Parse `cat12/report/cat_*.xml` (see workspace layout) for IQR (weighted image quality). Threshold configurable, default IQR ≥ 70 (grade C or better); below → `QC_BELOW_THRESHOLD` with a user message explaining the scan quality was insufficient for a reliable estimate. Record IQR regardless of outcome. Additional guards: GM+WM+CSF total intracranial volume within plausible bounds (e.g. 1000–2100 ml) as a segmentation-sanity check.

**extract_features.** Parse ROI label XMLs for the configured atlas into the long-format schema (`subject`, `session`, `feature_name`, `value`, `source`), then pivot and validate against `feature_schema_id` (exact names, exact count). Write `features/features.parquet`.

**predict.** Load model + frozen bias-correction parameters from the model registry (path + sha256 verified). Compute predicted age, raw BAG, corrected BAG. Write `predict/prediction.json` including the uncertainty estimate if the model provides one (the stacked ensemble can expose base-learner spread as a heuristic interval; whether to surface this to users is an open question below).

**report.** Render HTML → PDF: corrected BAG with context (reference MAE, QC grade, age-range note), explicit framing that this is not a diagnostic instrument, and the environment block (model + container versions) in a technical appendix for reproducibility.

## Worker execution model

- Single worker process (`bagpipe.app.worker`) polls the SQLite queue (`SELECT ... WHERE status='queued' ORDER BY created_at LIMIT 1` inside an `UPDATE ... RETURNING` claim, WAL mode).
- Concurrency: worker runs up to `N_CONCURRENT` jobs (default 1 on the single-GPU workstation; CAT12 is CPU-bound, so this is a CPU/RAM budget decision — with 24 GB per job cap, size to physical RAM).
- Claimed-but-stale jobs (worker crash) are re-queued by a startup sweep: any job `status='running'` with heartbeat older than timeout → reset to `queued`, workspace wiped.
- The queue row stores only: `job_id`, `status`, `created_at`, `claimed_at`, `heartbeat_at`, `workspace_path`, `notify_email`. Everything else lives in the manifest.

## Error → user communication mapping

Each `ErrorCode` maps to one of three user-facing categories in the email/report: **"fix your upload"** (`UNSUPPORTED_FORMAT`, `NOT_T1W`, `MULTIPLE_SERIES_AMBIGUOUS`, `GEOMETRY_INVALID`, `AGE_OUT_OF_RANGE`), **"scan quality insufficient"** (`QC_BELOW_THRESHOLD`), and **"our fault, try later"** (everything else). Technical details never leak into user messages; they live in the manifest and logs.

## Testing strategy

1. **Stage unit tests** against fixture workspaces (tiny synthetic NIfTIs for ingest/anonymize/features; recorded CAT12 output trees for qc/features).
2. **Golden-path integration test**: 3–5 held-out SNBB subjects run end-to-end through the containerized pipeline; assert corrected BAG within tolerance of values computed through the original training pipeline (tolerance defined in companion spec §6).
3. **Adversarial ingest suite**: T2w upload, 4D fMRI, 2-slice localizer, anisotropic clinical scan, zip with 3 series, corrupted DICOM. Each must fail with the correct `ErrorCode`.
4. **Schema-drift test**: mutate one ROI name in a recorded CAT12 output; assert `FEATURE_SCHEMA_MISMATCH`.

## Open questions

- Surface prediction uncertainty (ensemble spread) to end users, or keep it internal? Leaning internal for v1 to avoid misinterpretation.
- Soft vs. hard age-range boundary behavior at the edges of training support.
- Whether `qc_gate` should also run a registration-sanity check (correlation of normalized image with template) beyond IQR.
- v2: stage-level resume; parallel worker processes if deployed off the workstation.
