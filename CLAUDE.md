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

      *Update (2026-08-19): GPU driver/CUDA confirmed working (see
      `docs/data_audit.md`) — Pillar 2's SFCN blocker is gone. Added
      `torch`, `monai`, `nibabel` to `pyproject.toml`. SFCN scaffold ported
      (`sfcn.py`, `bag models train-sfcn --config config/models/sfcn.yaml`):
      regression-head SFCN (5 conv-bn-maxpool-relu blocks + 1 conv-bn-relu +
      global-avg-pool + linear) — a documented simplification of the
      paper's soft age-classification head, on the reasoning that it's
      simpler and MAE-equivalent for a first working model; revisit if it
      underperforms. `SFCNRegressor` is sklearn-compatible (`fit`/`predict`)
      so it runs through the same `evaluate()` grouped-CV + bias-correction
      harness as the tabular/stacked models — same non-negotiable rules
      apply, same MLflow logging. Input: `build_image_matrix()` in
      `tabular.py` joins `image_paths.parquet`'s `image_path_mwp1` (CAT12 GM
      density map, MNI space) against `globals.parquet` for age — 5,461 real
      sessions have both. MONAI (`LoadImage`/`EnsureChannelFirst`/
      `NormalizeIntensity`) handles loading/normalization, per the decided
      stack (DESIGN.md §"Tech stack"). `pretrained_weights_path` is a config
      slot for UKB-pretrained SFCN weights (DESIGN.md §4.2 fine-tuning plan)
      but nothing auto-downloads them yet — from-scratch training only for
      now. **Verified against real data**: ran `fit`/`predict` on 16 real
      `sub-S######` sessions on the actual GPU (confirmed `device == cuda`);
      pipeline runs end to end, join finds the expected session count.
      Synthetic test suite: `tests/test_sfcn.py` (tiny random volumes, tiny
      channels, 2 epochs — forward-shape check + fit/predict +
      config-driven `run()` through the harness). Overnight multi-epoch
      training run launched 2026-08-19, in progress. **Not yet done**:
      SFCN run completion + SFCN-vs-stacked leaderboard comparison.*

      *Update (2026-08-19): model registry + promotion added
      (`src/bagpipe/db/models.py::ModelRegistry`,
      `src/bagpipe/models/promote.py`, `bag models promote --name stacked
      --config config/models/stacked.yaml --version v1`) — fits the model
      on full data (not just CV folds), serializes with **cloudpickle**
      (plain `joblib`/`pickle` can't serialize the stacker's closures —
      `stacker_fn`/`model_fn` in `stacked.py` are locals), stores the
      artifact under `paths.models_dir` (new config key, `outputs/models/`,
      git-ignored under the existing `outputs/` rule), and inserts a
      `models_registry` row (config/metrics JSON, MLflow run ID, stage).
      Promoting a `stage="production"` row auto-archives any prior
      production row with the same `name`. **Stacked ensemble promoted as
      v1 production model** (`model_id=1`), verified against real data:
      artifact loads and predicts on the real region matrix (5-sample
      sanity check, predictions in plausible age range). Real-data CV
      metrics logged: MAE raw≈4.70y, MAE corrected≈5.71y (same Cole-
      correction-worsens-MAE tradeoff noted in the earlier stacked-ensemble
      update — expected, not a bug). Only `stacked` is wired into
      `RUNNERS` in `promote.py` so far — baseline/SFCN promotion would need
      their own `run()` to expose `model_fn`/`config` in `info` the same
      way `stacked.run()` now does. Not yet done: SFCN comparison before
      considering a v2 promotion, `predictions` table (BAG values aren't
      yet persisted per-prediction, only aggregate CV metrics).*

      *Update (2026-08-19/20): SFCN scratch training completed and its
      architecture ablated. First completed scratch run
      (`sfcn-scratch-overnight-2026-08-19c`) swapped BatchNorm3d for
      GroupNorm (theory: batch_size=2, forced by 8GB VRAM, gives BatchNorm
      too-noisy running stats), added AMP and train-only flip+affine
      augmentation, and fixed a real leakage bug — the inner train/val split
      used for early stopping was plain-random, not subject-grouped,
      violating the non-negotiable grouped-CV rule at the inner level even
      though the outer harness enforced it correctly (`sfcn.py`). Result:
      mae_raw≈7.45y — worse than the stacked ensemble (4.7-4.8y). Maintainer
      asked to revert to an earlier, better-looking run; checked first and
      that run was invalid to compare against on two counts — it was killed
      early (fold 1, epoch 2) so it never produced a final `mae_raw` at all,
      and even its logged per-epoch numbers were the *inner* early-stopping
      split's MAE (not the outer test metric), measured under the leaky
      split this commit fixed. Instead made `norm` config-driven
      (`model.norm: group|batch`) and ran a fair ablation, same split/
      epochs/budget, only the norm layer differing
      (`sfcn-scratch-batchnorm-ablation-2026-08-20`). **BatchNorm won
      decisively**: mae_raw≈4.68y, beating GroupNorm by a wide margin and
      landing on par with the stacked ensemble — the noisy-running-stats
      theory was never actually validated and turned out wrong here.
      `norm: batch` is now `sfcn.yaml`'s default. Also added
      `accumulation_steps` (gradient accumulation, default 1/no-op) as an
      unused-so-far lever for the batch_size=2 VRAM ceiling. Not yet done:
      SFCN-vs-stacked promotion decision (SFCN now competitive but not yet
      wired into `promote.py`'s `RUNNERS`), TIV/sex covariate fusion, LR
      schedule, soft age-classification head — all flagged as future
      levers, none blocking.*

      *Update (2026-08-20): SFCN-vs-stacked promotion decision made.
      Both evaluated on identical grouped 5-fold CV against real data:
      stacked mae_raw≈4.696y (production run, `model_id=2`), SFCN
      mae_raw≈4.675y (batchnorm-ablation run) — a 0.02y gap, not a real
      accuracy difference. Maintainer flagged region-level interpretability
      as a deciding factor. Stacked gets it for free: `regional_stacker`
      exposes per-region CV-R² (`region_cv_scores_`), already surfaced in
      `notebooks/stacked_ensemble_review.ipynb`. SFCN is a black-box 3D
      CNN — region attribution would need saliency/occlusion/Grad-CAM, none
      implemented, nontrivial to validate, and computationally expensive.
      With accuracy tied, no case to build that tooling. **Stacked stays
      the production model.** SFCN not wired into `promote.py`'s `RUNNERS`
      — remains a documented comparison baseline; revisit only if a future
      SFCN change (soft classification head, TIV/sex fusion, LR schedule)
      produces a real accuracy edge over stacked.*
- [ ] **Phase 3 — Causal:** exposure mapping from questionnaire, cohort builders,
      mixed-model/DiD/event-study analyses + falsification and selection batteries.
      *Status (2026-08-19): kickoff started. `events` table added
      (`src/bagpipe/db/models.py::Event`, seeded idempotently from
      `config/events.yaml` via `bag ingest events` — Oct 7 war, judicial
      reform, 3 COVID lockdown waves, all public dates). Walkthrough
      notebook (`notebooks/causal_bag_walkthrough.ipynb`) builds the
      longitudinal BAG panel from `predictions` + `events`, and runs the
      mixed-model DiD, event-study, placebo, and selection-bias designs from
      DESIGN.md §5 — verified end-to-end against the real DB (926 subjects
      with ≥2 sessions). Caught a real bug during verification: joining
      predictions to scan dates on `session_id` alone fans rows out ~2x,
      because SNBB's per-scan `session_id` and the legacy cohort's 12-digit
      `subject_id` share the same timestamp-ID format and collide across
      cohorts — fixed by joining on `(subject_key, session_id)`. **Not yet
      done, and the actual blocker**: exposure/dose mapping from the
      questionnaire. Candidate geography columns exist
      (`Place_of_Residense`, `Living_environment`, `Current_Environment`,
      `Childhood_envinronmnet`) and candidate outcome/severity instruments
      too (`PCL-5`, `OASIS`, `GAD7`, `PHQ9`, `LongCovid`, `HolocaustLineage`)
      but which is exposure vs. outcome, and how to turn geography into a
      dose gradient, is a domain call — needs the maintainer, not assumed
      in the notebook. All designs currently run binary post/pre only until
      that's resolved.*
- [ ] **Phase 4 — Web app:** Apptainer CAT12 preprocessing image, upload→queue
      →worker→report pipeline, consent/deletion logic.
      *Status (2026-08-19): kicked off early (maintainer request) — pipeline
      skeleton is real code, not just a plan. `bagpipe.app.pipeline.run()`
      chains DICOM-or-NIfTI → dcm2niix → pydeface → CAT12 (Apptainer,
      `container/cat12.def`) → `bagpipe.app.cat12_parse` (ported from the
      maintainer's private `update_tabular_cat12.py`) → prediction against
      the promoted model, vectorized onto its exact training columns
      (`bagpipe.models.tabular.region_columns_for`, new) → Cole bias
      correction fit live from that model's own stored `predictions` rows
      (no new corrector-persistence step) → regional age/sex/TIV-adjusted
      z-scores (`bagpipe.app.normative`, the maintainer's separate
      `normative` project's approach ported in-line, not depended on).
      FastAPI app (`bagpipe.app.api`, `bag app serve`) exposes `POST
      /predict`, synchronous for now. Synthetic tests pass (10 new,
      `tests/test_cat12_parse.py`, `tests/test_normative.py`,
      `tests/test_pipeline.py`, `test_tabular.py::test_region_columns_for`);
      full suite (27) + ruff clean. **Not yet verified against real data or
      a real CAT12 container** — `container/cat12.def` documents the
      Apptainer build (`Bootstrap: docker`, Ubuntu 22.04 base) but the CAT12
      standalone MCR install is a manual, license-gated download not
      scripted into `%post`; until a `.sif` is built at
      `paths.cat12_apptainer_image`, `run_cat12()` is untestable end-to-end.
      Not yet done: job queue (currently runs in-request, will time out on
      a real ~tens-of-minutes CAT12 run), HTML/PDF report template, email
      delivery, consent/deletion logic, and a real-data verification pass
      (run against an actual scan through the built container) before
      calling any of this done.*

      *Update (2026-08-21): two design docs added
      (`docs/design_inference_pipeline.md`: stage/manifest/worker
      architecture; `docs/cat12_container_spec.md`: container version pins,
      batch template, reproducibility test) and both acted on same day.
      **Real bug found and fixed**: the container spec's atlas was wrong
      from the start — it assumed a placeholder `custom_atlas_v2`/
      `neuromorphometrics`, but checking a real SNBB `cat_*.xml` plus the
      production feature export (`outputs/datasets/regional.parquet`)
      showed the promoted stacked model actually trains on
      **Schaefer2018N400n7Tian2020S2** ROI volumes only —
      `neuromorphometrics` was computed for SNBB but never ingested.
      Fixed throughout `cat12_container_spec.md`; real atlas files copied
      into `container/atlas/` (`.nii` git-ignored, `.csv` label map
      committed). CAT12 pins confirmed from the same real XML:
      `version_cat=12.9`, `revision_cat=2577`, `version_spm=7771`,
      `version_matlab=24.1` (matches the `CAT12.9_2577.new` derivatives
      folder name as a sanity check). **Second bug found and fixed**, in
      `container/cat12.def` itself (which already existed, Apptainer-
      native, contra the container spec doc's stale Docker-then-convert
      plan — doc now reconciled to describe the real `.def` file): its
      `%runscript` misused `-a1`/`-a2` for the input path/output dir,
      but those flags are for extra numbered `<UNDEFINED>` batch
      placeholders (e.g. resample smoothing kernel), not a data-path/
      output-dir mechanism — confirmed via `jhuguetn/cat12-docker`'s real
      invocation syntax (positional `-b batch.m input.nii`, output always
      lands next to input, no output-dir arg exists). Fixed. `%post` also
      gained the previously-missing atlas-install and batch-patch steps
      (patches CAT12's own bundled `cat_standalone_segment.m` via `sed` on
      only the fields confirmed to differ from stock, rather than
      reconstructing the whole batch from scratch — safer given CAT12's
      many undocumented defaults). MCR pin corrected too: `.def`'s
      `%help` already said `R2017b`/`v93`; container spec doc had wrongly
      guessed `R2023b`, now fixed to match. **Also**: `src/bagpipe/app/`
      refactored from a flat `pipeline.py` into a `pipeline/` package
      matching `design_inference_pipeline.md`'s stage-graph design —
      `base.py` (Stage protocol, `ErrorCode`, `PipelineError`),
      `models.py` (pydantic `Manifest`/`StageRecord`), `runner.py`
      (executes stages, atomic `manifest.json` writes, stops at first
      failure), and one file per stage (`ingest`, `anonymize`, `segment`,
      `qc_gate`, `extract_features`, `predict`, `report`). `qc_gate` found
      a real gap while writing it: CAT12's raw `<IQR>` XML tag is a 1–6
      "mark" scale, not the 0–100 percent grade the design doc's threshold
      (`≥70`) assumes — parses the percent+letter grade from the report's
      human-readable text line instead of reimplementing CAT12's
      mark-to-percent formula. `bagpipe.app.pipeline.run()`/`PipelineError`/
      `BAGResult` kept as the package's public API so `bagpipe.app.api`
      needed no changes. Full test suite (30, `tests/test_pipeline.py`
      rewritten against the new `predict.py` stage) + ruff pass. **Still
      not done**: `container/atlas/PROVENANCE.md`, staging the login-walled
      standalone/MCR zips, the actual `apptainer build` + §6 reproducibility
      test, job queue, report template, email delivery — same real-data
      verification gap as the 2026-08-19 update, now one layer closer.*

      *Update (2026-08-21, same day): real CAT12 standalone + MCR zips
      staged and `apptainer build container/cat12.sif container/cat12.def`
      actually run. **Six more real bugs found and fixed, none catchable
      without the real files**: (1) `%help` text literally contained the
      strings `%post`/`%files` mid-sentence — Apptainer's def parser
      treats any line starting with `%` (after whitespace-trim) as a new
      section header, context-blind, so a wrapped line beginning `%post
      uses it as-is)...` broke parsing of the whole file; reworded to
      never start a line with `%word`. (2) `%files` source paths are
      resolved relative to the invoking shell's CWD, not the `.def`
      file's own directory — fixed to `container/`-prefixed paths. (3)
      the MCR installer (a raw MathWorks installer package, confirmed by
      inspecting the zip — not an already-built runtime as briefly
      guessed) installs into `<destinationFolder>/R2023b/`, not a
      `v###/`-named dir as its own generic example docs implied — the
      `find` regex only matched `v[0-9]+`; broadened to match `R20YY[ab]`
      too, confirmed against the real installed tree. (4) same MCR
      confirmation: **R2023b/v232**, matching the earlier correction.
      Real, working image: `container/cat12.sif` (~9.8GB). Verified
      inside the built image: `paths.env` resolves to the real
      `cat_standalone.sh`/MCR paths, and all 9 batch-patch fields
      (`affreg`, `biasstr`, `APP`, `vox`, `surface`, `BIDSno`,
      `neuromorphometrics`, `cobra`, `ownatlas`, `GM.mod`, `WM.mod`)
      landed correctly in the patched `batch_template.m` — confirmed by
      `grep` inside the running container. **Real end-to-end smoke test
      launched** against an actual SNBB T1w scan (`apptainer run
      container/cat12.sif`, monitored for completion/error markers) —
      see next update for the result once it lands.

      Also same day: `%runscript` changed to forward `"$@"` instead of
      `"$1"` (needs a rebuild to take effect on `.sif` — the smoke test
      above ran against the pre-change image, unaffected since it only
      ever passed one arg) so the same image serves both the inference
      pipeline (`bagpipe.app.pipeline.segment`, one file, no extra args)
      and a new bulk-reprocessing driver without the two ever drifying
      apart on segmentation params — the actual training-inference parity
      invariant. New: `src/bagpipe/preprocess/cat12_cohort.py` (`bag
      preprocess cat12-cohort --config config/cat12_cohort.yaml`),
      replacing the maintainer's old single-subject, desktop-MATLAB,
      `nproc=5` script (`~/Projects/learning_for_luna/src/
      cat12_runner_new.m`) with a config-driven, chunked, concurrent
      driver over the same container. Real gotcha caught before it could
      silently drop config: `cat_standalone.sh`'s `-a` flag **overwrites**
      a scalar, it does not accumulate across multiple `-a` invocations
      (confirmed by reading its real `parse_args()`) — all extra batch
      lines (surface/thickness on, extra atlases, BIDS-folder redirect,
      lazy skip-existing) are joined into one newline-separated string and
      passed as a single `-a`. Config (`config/cat12_cohort.yaml`)
      documents the real tradeoff explicitly: surface+cortical-thickness
      extraction (not currently in bagpipe's feature space at all) is a
      literature-backed addition worth the one-time cost of bulk
      reprocessing, roughly doubling per-subject runtime — a decision
      left visible and reversible in config, not silently baked in.
      3 new tests (`tests/test_cat12_cohort.py`, pure logic — raw-T1w
      filtering against every real CAT12 output-prefix convention,
      BIDSfolder relative-path math, chunking); full suite (33) + ruff
      pass (repo-wide, excluding pre-existing unrelated debt in
      `sfcn.py`).

      *Update (2026-08-21, later same day): smoke test result is in —
      **real success, after three more real bugs found and fixed**, none
      catchable without an actual run against real data. (1)
      `--writable-tmpfs` is required — MCR can't extract its CTF archive
      into the read-only image tree otherwise; failed identically every
      time without it, worked every time with it. Added to both
      `segment.py`'s and `cat12_cohort.py`'s `apptainer run` invocations.
      (2) Classic-mode (`BIDS.BIDSno=0`) output goes into `mri/`/
      `report/`/`label/` subdirs, **not flat** as an earlier "fix" this
      same day assumed — that assumption compared against the real SNBB
      training tree, which turns out to have been produced via a
      *different* code path (`BIDS.BIDSyes` redirect, which does
      flatten). Reverted `segment.py`/`features.py` back to
      subdir-relative paths. (3) The atlas `.csv` (region names) was
      staged via `%files` but never actually copied next to the `.nii` in
      `%post` — fixed, warning gone on rebuild. **Also corrected a wrong
      claim from earlier the same day**: the standalone zip's real CAT
      version, read from an actual run's output XML (not a stale
      docstring in a `.m` file), is **`26.0.rc3` r`2874`** — genuinely a
      different, newer release line than SNBB training's CAT12.9/2577,
      not "still 2577" as first misread. Confirms SNBB re-extraction
      through this container is necessary, not optional, before it can
      serve as the production inference container — matches what the
      maintainer already planned. Real single-subject run: 12m26s, SIQR
      87.22% (B+), clean output at `report/cat_T1w.xml` +
      `label/catROI_T1w.xml`. New `limit` config key added to
      `cat12_cohort.yaml`/`cat12_cohort.py` for validating the
      still-unverified BIDS-redirect (cohort) output-path assumption on
      1-2 subjects before committing to a full run.*

      *Update (2026-08-22): that validation run happened — and the
      BIDS-redirect assumption was indeed wrong, exactly as flagged.
      **Two more real bugs found and fixed, only visible against real
      data**: (1) CAT26's batch schema has no `BIDS.BIDSyes.BIDSfolder`
      field at all (`Item BIDS: No field(s) named BIDSyes`) — replaced
      entirely with input-staging (symlink each file into its desired
      output location, run classic mode) reusing the exact mechanism
      `segment.py` already uses for inference, no redirect field needed.
      (2) CAT12 forks an untrackable background subprocess per file
      whenever a job's file list has more than one file, regardless of
      `nproc` — confirmed by direct A/B testing (every single-file job
      succeeded, every multi-file job failed identically with `"...
      catlog....txt" not exist after 60 seconds`). Fixed: `subjects_per_job`
      forced to `1` — real parallelism comes from `concurrency` (separate
      `apptainer run` invocations), no throughput loss. Also found:
      surface/thickness reconstruction fails inside the container
      (binary-permission-flavored error, not yet root-caused) — non-fatal
      (core ROI output still succeeds), disabled by default since bagpipe
      doesn't consume surface data anyway. **Validated end-to-end**: 2/2
      real subjects succeeded via the actual `bag preprocess cat12-cohort`
      CLI. Not yet done: §6 reproducibility suite, first real full-cohort
      run (deliberately not launched — user runs in their own tmux
      session), `container/atlas/PROVENANCE.md`, root-causing the surface
      binary issue.*

      *Update (2026-08-23): surface/thickness binary issue root-caused and
      fixed — the "File permissions are not correct / binaries not
      compatible / antivirus blocking" error was a red herring. Real
      cause, found via `strace -f -e trace=execve` on a real run: Apptainer
      leaks the host's `$SHELL` into the container by default, and
      MATLAB's compiled runtime uses `$SHELL` to spawn every external
      `system()` call — including every `CAT_*` surface/thickness binary.
      The host runs zsh, which doesn't exist in the Ubuntu 22.04 container,
      so every such call failed with `execve(...zsh...) = -1 ENOENT`,
      which CAT12 reports as its generic misleading three-option message —
      not an actual permission or compatibility problem, and nothing to do
      with the earlier MCR_CACHE_ROOT/CTF-extraction-location theory (also
      corrected along the way: the CTF actually self-extracts into an
      `spm25_mcr/` dir next to the standalone binary, not under
      `$MCR_CACHE_ROOT`). Fixed two ways in `container/cat12.def`: (1)
      `%post` now pre-extracts the CTF once at build time and `chmod`s the
      `CAT_*` binaries inside it, baking a correctly-permissioned
      extraction into the image so no runtime extraction happens at all;
      (2) every `apptainer run` invocation
      (`bagpipe.app.pipeline.segment`, `bagpipe.preprocess.cat12_cohort`)
      now passes `--env SHELL=/bin/bash`. Removed the now-obsolete
      `mcr_cache_dir` config key and its host bind (dead weight now that
      extraction is baked in). **Verified end-to-end**: rebuilt
      `container/cat12.sif`, ran a real SNBB subject through it with
      `output.surface`/`surf_measures`/`ct.native` all `= 1` — full
      `surf/lh.*.gii`/`surf/rh.*.gii` + thickness maps produced, no
      errors, SIQR 88.25% (B+), ~53min total (well under
      `timeout_minutes: 90`). `config/cat12_cohort.yaml`'s
      `extra_batch_lines` surface block is now enabled by default. Not yet
      done: re-running the §6 reproducibility suite / real full-cohort run
      against the rebuilt image (segmentation-only params unchanged, but
      the image itself was rebuilt so this is still owed before trusting
      it as the production inference container), `container/atlas/PROVENANCE.md`.*

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
