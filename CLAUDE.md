# CLAUDE.md — bagpipe (Brain Age Gap PIPEline)

## What this project is

A framework for deep investigation of Brain Age Gap (BAG), built on the SNBB dataset
(single-site Israeli cohort, ~4,500 participants, ~6,000 sessions including repeated
measures; all T1w, most dMRI; BIDS-organized; preprocessed with CAT12 for T1w and
qsiprep+qsirecon for dMRI). Four pillars:

1. **Database** (`src/bagpipe/db/`) — SQLite canonical store unifying imaging metadata,
   CAT12/qsirecon features, and questionnaire/demographic data; extensible to future datasets.
2. **Modeling** (`src/bagpipe/models/`) — config-driven harness for brain-age models:
   tabular regressors, a per-region stacked ensemble (base learners per region over
   GM vol/CSF/WM/MD/FA etc., meta-learner on OOF predictions), and 3D CNNs (SFCN first).
3. **Causal** (`src/bagpipe/causal/`) — longitudinal analyses of event-associated BAG change
   (Oct 7 2023/war, COVID lockdowns, 2023 judicial-reform period) using mixed-model
   DiD, event studies, placebo tests, and selection-bias diagnostics.
4. **Web app** (`src/bagpipe/app/`) — public FastAPI service: DICOM upload → deface →
   CAT12 preprocessing → inference with a frozen registered model → emailed PDF report.

**The authoritative plan is `docs/DESIGN.md`. Read it before large tasks. If
implementation must deviate from it, say so explicitly and update the doc in the
same PR.**

## Hard constraints — never violate

- **This repo is PUBLIC. The data is PRIVATE.** Never commit, copy into the repo,
  or embed in code/tests/docs/notebook outputs: any imaging file, any row of real
  subject data, any real subject/session ID, any questionnaire content, or any
  absolute path revealing personal directory names.
- Data locations, credentials, and machine-specific paths live ONLY in
  `config/local.yaml` (git-ignored). Code reads them via `bagpipe.core.config`. Never
  hardcode them.
- Real data stays on this machine. Never upload it anywhere, never include it in
  web requests, never write it outside the configured data/output directories.
- Subject identifiers in the DB are anonymized; keep it that way. The imaging-ID ↔
  questionnaire-ID mapping file is sensitive: git-ignored, referenced by config path only.
- Tests and CI use synthetic fixture data only (see `tests/fixtures/`). Never write
  a test that requires real data to pass in CI.
- Before any `git add`/commit, verify no data files are staged. Respect
  `.gitignore`; if you create a new output/cache directory, add it to `.gitignore`
  in the same change.
- Destructive operations on the database or raw data directories (deletes, moves,
  overwrites of `snbb.sqlite`) require explicit confirmation from the user first.

## Tech stack (decided — don't relitigate without asking)

- Python ≥3.11, single `bagpipe` package (CLI command: `bag`), `pyproject.toml`, managed with `uv`.
- **DB:** SQLite via SQLAlchemy 2.x models; long-format `features` table; Parquet
  exports for model training; Datasette for read-only browsing.
- **ML:** PyTorch (+ MONAI for 3D transforms); scikit-learn/LightGBM for tabular;
  SFCN for the first CNN. Experiment tracking: **MLflow, local**.
- **Evaluation:** subject-grouped CV always (a subject's sessions never span
  train/test); MAE primary metric; age-bias correction is a pluggable, configurable
  step (de Lange & Cole-style linear correction as default; Beheshti variant
  available); store both raw and corrected BAG in `predictions`.
- **Causal:** statsmodels/linearmodels; analyses driven by the `events` table.
- **App:** FastAPI + SQLite-backed job queue (Huey); dcm2niix; pydeface; CAT12
  standalone (containerized) for preprocessing — must match training preprocessing
  exactly; WeasyPrint for PDF reports; English reports; uploads deleted by default,
  retained only with explicit opt-in.
- Compute: single workstation, single GPU. Prefer solutions that fit this footprint;
  no cluster/cloud assumptions.

## Conventions

- Config-driven everything: experiments, ingestion runs, and analyses are defined
  by YAML in `config/`, executed by CLI entry points in `scripts/`. No magic
  constants in code.
- All data access from pillars 2–4 goes through `bagpipe.db` query functions — never
  read raw CSVs/Sheets exports directly outside the ingestion modules.
- Ingestion modules must be idempotent (safe to re-run) and must log a summary
  (rows added/updated/skipped, unmatched IDs).
- Every new module gets tests (pytest) against synthetic fixtures, type hints, and
  a docstring; public-facing behavior gets a docs page (mkdocs-material in `docs/`).
- Style: ruff (lint + format) via pre-commit. Keep functions small; prefer pure
  functions for transforms.
- Documentation audience: the maintainer, their PI, and external collaborators —
  write docs so a new collaborator can go from clone to first query in under 30
  minutes (`docs/getting_started.md`).
- Commits: small, scoped, imperative messages. Reference the pillar/phase
  (e.g., `db: add CAT12 ROI parser (phase 1)`).
- Notebooks are for exploration only and must be stripped of outputs before commit
  (nbstripout in pre-commit) — outputs may contain real data.

## Current status / roadmap

- [x] **Phase 0 — Audit:** environment + data inventory → `docs/data_audit.md`.
      Done 2026-08-19. Open: GPU driver not installed (blocks Phase 2 only),
      backup status of `/mnt/62` unverified.
- [x] **Phase 1 — Database (core):** ingestion of CAT12 tabular features, T1w
      image paths, and both cohorts' demographics is live; identity/session
      resolution and ID harmonization are handled by **brainlink** (a separate,
      pre-existing project this repo now depends on) instead of a
      bagpipe-native `id_map` — see `docs/DESIGN.md` §3.2 deviation note.
      Done 2026-08-19. Open: per-event repeated-measures counts (needs an
      `events` table, deferred to Phase 3 kickoff).
- [ ] **Phase 2 — Modeling:** eval harness + bias correction, tabular baselines,
      stacked ensemble port, SFCN fine-tune, MLflow, model registry.
      *Status (2026-08-19): eval harness done (`src/bagpipe/models/evaluate.py`)
      — subject-grouped `GroupKFold`, pluggable bias correction (`cole`/
      `beheshti`/`none`), MAE/R² raw+corrected. TIV/sex region adjustment
      (`covariate_adjustment.py`, residualized on train fold only). Tabular
      baselines live (`baseline.py`, `bag models train-baseline --config
      config/models/*.yaml`): `linear`, `ridge` (RidgeCV, alpha tuned
      internally — GM-volume-only flat model, MAE≈5.0y raw, see the
      2026-08-19 update below for why this number changed and is no longer
      the leaderboard leader), `lightgbm` (kept
      in code, dropped from the demo notebook per maintainer request — no
      real accuracy edge over ridge here and much slower). MLflow logging
      wired (local, SQLite-backed tracking store at `paths.mlflow_dir`).
      Demo: `notebooks/baseline_model_demo.ipynb` (export → region matrix →
      harness → leaderboard → prediction/BAG/sex diagnostics → MLflow).
      **Fixed a real bug**: bias corrector was fitting on in-sample training
      predictions, which barely corrects flexible models (LightGBM nearly
      memorizes training data) — now fits on nested out-of-fold predictions
      within the training fold. Verified: raw BAG-vs-age slope -0.29 (p≈0)
      → corrected slope ~0.01 (n.s.). Finding worth carrying into Phase 3:
      corrected BAG differs by sex (Female +0.63y vs Male -0.42y, p<0.0001,
      n=2326/3124, Ridge model) — real, survives proper bias correction,
      not an artifact. Not yet done: SFCN fine-tune (blocked on GPU driver,
      see Phase 0), model registry/promotion.
      Also: `pyproject.toml` now excludes `notebooks/` from ruff lint
      (exploration-only; pre-existing `db_review.ipynb` had unrelated lint
      debt — nbstripout still handles their output hygiene).*

      *Update (2026-08-19): stacked ensemble ported (`stacked.py`,
      `bag models train-stacked --config config/models/stacked.yaml`),
      using **regional-stacker** — the maintainer's own pre-existing
      sklearn-compatible package
      ([github.com/GalKepler/regional-stacker](https://github.com/GalKepler/regional-stacker),
      pinned as a git dependency at tag `v1.0.0`; not yet on PyPI) —
      rather than a from-scratch port. Wires the same TIV/sex-adjustment
      wrapper and grouped-CV eval harness `baseline.py` uses; region
      grouping (`build_region_mapping` in `tabular.py`) collapses the flat
      `atlas__region__metric` columns into one region block per
      `atlas__region` (432 regions from the current CAT12 export) for the
      stacker's per-region base learners.

      **Caught and fixed a real bug the same day**, flagged by the
      maintainer during review of the review notebook: `build_region_matrix`
      had no metric filter, so the "flat" `linear`/`ridge` baselines were
      silently getting **GM+WM+CSF volumes concatenated into one
      undifferentiated flat vector** (1296 columns) — not the GM-volumes-only
      model `docs/DESIGN.md` §4.1 describes ("CAT12 GM volumes,
      neuromorphometrics atlas"). Fixed: `build_region_matrix(..., metrics=
      [...])` now filters explicitly; every `config/models/*.yaml` carries
      its own `features.metrics` (baselines: `[vol_gm]`; `stacked.yaml`:
      `[vol_gm, vol_wm, vol_csf]`) so the feature spec is config-visible and
      MLflow-logged, not implicit in which script ran. **This changes the
      leaderboard conclusion**: re-run against the real DB with the fix,
      ridge (GM-only) is MAE≈5.0-5.1y raw — worse than before, because it
      lost the WM/CSF columns it was wrongly getting — while the stacked
      ensemble (all three metrics, correctly grouped per region) is MAE≈4.7-
      4.8y raw and is now **the leaderboard leader**, which is the result
      the stacked-ensemble design was supposed to produce (multi-metric
      fusion per region beats a single metric). RidgeCV base + RidgeCV meta,
      no hyperparameter search beyond RidgeCV's internal alpha grid. Bias
      correction verified sound on both models (BAG-age slope flattens to
      ~0 post-correction on each). **Diagnostic worth carrying forward**: on
      both models, `mae_corrected` is *worse* than `mae_raw` even though the
      correction properly flattens the BAG-age slope — the known
      Cole-correction tradeoff (an affine transform optimized to remove
      age-dependent bias, not MAE), not a bug. Sex effect in corrected BAG
      reproduces on the stacked model too (same direction/magnitude as
      ridge). Review notebook: `notebooks/stacked_ensemble_review.ipynb`
      (leaderboard incl. stacked vs. baselines on their correct feature
      specs → diagnostics → per-region CV-R² inspection via
      `regional_stacker`'s `region_cv_scores_` → MLflow). Not yet done:
      non-linear base/meta estimators (LightGBM base learners per region),
      wider hyperparameter search, SFCN fine-tune, model registry.*
- [ ] **Phase 3 — Causal:** exposure mapping from questionnaire, cohort builders,
      mixed-model/DiD/event-study analyses + falsification and selection batteries.
- [ ] **Phase 4 — Web app:** preprocessing container, upload→queue→worker→report
      pipeline, consent/deletion logic.

Update the checkboxes and add dated notes here as phases complete, so every session
starts with accurate context.

## Machine-specific facts (filled in during Phase 0, 2026-08-19)

- BIDS root: `/mnt/62/Bids` (SMB share; referenced via config, never hardcoded)
- CAT12 tabular (ROI/global scalars): `/mnt/62/Processed_Data/derivatives/tabular_cat12` (SMB)
- CAT12 images (mwp1/wm NIfTI, used for training): `/media/storage/yalab-dev/BIDS/derivatives/CAT12.9_2577.new` (local disk)
- qsiprep/qsirecon derivatives: `/mnt/62/Processed_Data/derivatives/{qsiprep,qsirecon,tabular}` (SMB, not yet ingested — dMRI is a later phase)
- Tabular exports directory: `/mnt/62/Processed_Data/derivatives/tabular` (SMB)
- Shared DB (brainlink + bagpipe tables): `/media/storage/brainlink/brainlink.db`
- GPU: NVIDIA GeForce RTX 3070 Ti — driver not currently loaded, needs install before Phase 2
- OS: Ubuntu 24.04.4 LTS; CUDA: not yet installed
