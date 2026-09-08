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

      *Update (2026-08-24): CAT26 reprocessing cohort (`features.source=
      "cat12_v26"`, added surface cortical thickness on top of the existing
      volume ROIs, see Phase 4's 2026-08-23 update) wired into the modeling
      pipeline as its own selectable dataset — `bag export training-table
      --source cat12_v26 --out-dir outputs/datasets_v26` (new `--source`/
      `--out-dir` flags; `None` keeps pooling every CAT version like
      before), plus a `datasets_dir` override key model configs can set
      (`baseline_v26.yaml`, `stacked_v26.yaml`, `stacked_v26_surface.yaml`)
      so this doesn't touch the production `outputs/datasets` used by the
      promoted model. As of today, 426/~4500 sessions are reprocessed (337
      with full age/sex/TIV coverage for modeling, 248 with surface
      output). **Real diagnostic run, not just a leaderboard number**: raw
      leaderboard on the v26 cohort looks much worse than production
      (ridge mae_raw≈7.15y, stacked≈6.94y vs. production's ≈4.7y) —
      checked whether this is the new CAT version regressing quality or
      just the much smaller n. Isolated it: re-ran the *old* CAT12.9 ridge
      baseline restricted to the exact same 337 subjects (`source="cat12"`
      pool, no rows added/removed) — mae_raw≈7.17y, statistically
      indistinguishable from the new version's 7.15y on the same subjects.
      **Confirmed: the CAT26 reprocessing isn't degrading model quality,
      the small-n comparison to the full production leaderboard just isn't
      apples-to-apples yet.** Stacked ensemble again beats flat ridge on
      this cohort too (6.94y vs 7.15y), consistent with the earlier
      finding. Tried fusing cortical thickness into the stacked ensemble
      (`stacked_v26_surface.yaml`, `metrics: [vol_gm, vol_wm, vol_csf,
      thickness]`) — mae_raw ticks down to 6.72y but r²_raw collapses
      (0.76→0.59) because thickness is on 3 different surface atlases
      (DK40/Destrieux/Schaefer) with no shared parcellation to volume, and
      the metric filter matches all three, giving 1051 per-region base
      learners against only 197 samples with full coverage — likely noise
      from an underdetermined fit, not a real signal; **don't trust the
      surface-fusion number until surface coverage is much larger than the
      region count.** Not yet done: full-cohort reprocessing (still
      running per Phase 4), re-promoting a v2 model once the reprocessed
      cohort is large enough for a fair leaderboard comparison, restricting
      thickness fusion to one atlas (Schaefer, to match the volume atlas)
      once that comparison is worth trusting.*

      *Update (2026-08-25): **CAT12.9_2577.new (`source="cat12"`) retired as
      the training cohort per maintainer decision** — CAT12.cohort_2026_08
      (`source="cat12_v26"`) is now the only cohort used going forward, even
      mid-reprocessing, because it's on a newer/more reliable CAT version.
      Promoted `stacked v2` (`model_id=3`) trained on it, replacing `v1`
      (archived). **Two real bugs found and fixed getting there**: (1)
      `bag ingest cat12-cohort` scanned on-disk `report/`/`label/` XMLs
      unconditionally — a from-scratch `cat12-cohort` run doesn't clear a
      subject's old output before reprocessing it, so mid-run it silently
      re-ingested **stale pre-surfextract output from before the
      2026-08-24 ledger reset** as if current; DB held 546 `cat12_v26`
      sessions when the ledger's actual current-run count was 186 —
      exactly the discrepancy the maintainer flagged. Fixed:
      `collect_rows` now skips any session the ledger doesn't mark
      `succeeded` (`ingest_cat12_cohort.py`, `_succeeded_session_ids`);
      new test `test_collect_rows_skips_sessions_not_ledger_succeeded`.
      Old stale rows already in `features` aren't purged by this fix (no
      destructive DB op run) — they self-heal via upsert as reprocessing
      reaches each subject, and this training run filtered them out at
      export time instead (join against the ledger's succeeded set,
      137/142 sessions with full age/sex/TIV coverage survived). (2)
      `promote.py`'s final full-data refit hardcoded
      `get_path("datasets_dir")` regardless of the training config's own
      `datasets_dir`/`atlases` — would have silently fit the "production"
      artifact on the wrong (old, pooled) cohort even though CV metrics
      were computed correctly on `outputs/datasets_v26`. Fixed to reuse
      `info["config"]`. **Real numbers, on the currently-reprocessed
      subset (137 sessions, reprocessing still running)**: mae_raw≈4.86y,
      mae_corrected≈6.56y, r²_raw≈0.54 — mae_raw is close to old v1's
      4.70y despite far fewer samples (unlike the 2026-08-24 337-sample
      run's 6.94y), sex gap from v1 does **not** reproduce here (p=0.51,
      n=66/71) — plausibly an n=137 power issue rather than a real
      difference, don't read into it yet. `notebooks/production_model_status.ipynb`
      (added same day, no-retrain "current production model state" view
      reading `models_registry`/`predictions` directly) needed a matching
      fix: its sex join hit `demographics` directly, which only covers the
      SNBB cohort — this v26 subset is all legacy-cohort subjects (sex in
      `legacy_participant.gender`, keyed by `subject_key` not
      `session_id`); now reads sex from the model's own
      `datasets_dir/globals.parquet` instead (the same source
      `export_training_table._cohorts()` used at training time). **Not yet
      done**: cohort still reprocessing — re-promote v2 again once
      coverage is much larger than 137/142, `outputs/datasets`
      (old-cohort default) and `config/models/{baseline,stacked}.yaml`
      still point at the retired cohort and should be repointed/removed
      once v26 coverage matches or exceeds it.*

      *Update (2026-08-25, later same day): found (pre-existing, untracked
      at session start) `scripts/{nightly_cat12_cohort,
      periodic_ingest_export,periodic_train_models}.sh` already live in
      `crontab -l` — nightly reprocessing scan (02:00), ingest+export every
      3h, eval-only retrain every 12h, deliberately **not** auto-promoting.
      **Real root-cause fix applied before wiring daily promotion**:
      `export_training_table.export(source="cat12_v26")` had the same
      staleness gap as `ingest_cat12_cohort.py`'s fixed bug above — it
      pooled every `cat12_v26` row in `features` with no ledger scoping, so
      it would keep re-including old pre-reset sessions that
      `ingest`'s fix stopped adding but never retroactively removed. Fixed
      once, at the shared root (`export()`'s `LEDGER_SCOPED_SOURCES`
      check, reusing `ingest_cat12_cohort.succeeded_session_ids` — renamed
      from `_succeeded_session_ids`, now a cross-module helper): any
      `source="cat12_v26"` export filters to the ledger's current
      `succeeded` set. Per maintainer's explicit request, added
      `scripts/periodic_promote.sh` — daily `bag models promote --name
      stacked --config config/models/stacked_v26.yaml --version
      "v26-$(date +%Y%m%d)"`, cron `0 5 * * *` (after the 02:00 reprocess
      scan + at least one 3h ingest/export cycle), separate from the
      12h eval-only trio so a slow/bad training run there can't block or
      race promotion. Re-promoting daily on a still-growing, still-small
      cohort means production `mae_raw` will be noisy day to day —
      expected, not a bug; check `production_model_status.ipynb` rather
      than trusting any single day's number.*

      *Update (2026-08-27): regional BAG now bias-corrected too, and fit at
      promotion time, not analysis time. `bagpipe.models.bias_correction.
      fit_region_correctors` (called from `promote.py` right after the
      final-refit `fit()`) fits one `ColeCorrection` per region on the
      artifact's own per-region predictions and stores the result as
      `stacker.region_correctors_`, alongside the existing (untouched)
      `region_estimators_` that still feed the meta-learner raw. Consumers
      (e.g. `notebooks/bag_correlates_explorer.ipynb`) call `.transform()`
      on the stored corrector — no fitting happens outside promotion.
      Same in-sample caveat as `region_estimators_` itself. New test:
      `tests/test_bias_correction.py`.*

      *Update (2026-09-06): accuracy-improvement pass kicked off, following
      a real diagnostic of production model 31's own held-out `predictions`
      (n=2260): MAE roughly triples from 3.6y @25-30 to 11.0y @70+, and Cole
      slope 0.713 means the shipped **corrected** number amplifies every
      deviation 1.40x — `mae_corrected` (5.75y) is the metric that matters
      and nothing in the pipeline optimized it. Full plan and root-cause
      analysis (surface/volume region-name mismatch causing 0 fusion,
      untouched age skew, self-inflicted HGBR-vs-speed tradeoff) at
      `~/.claude/plans/at-the-heart-of-whimsical-naur.md`. Phases 0-2 done:

      **Phase 0 (bug fixes)**: `fit_region_correctors` was fitting per-region
      Cole correctors on NaN-contaminated residuals — skipped the same
      median imputation `TIVSexAdjustedRegressor.fit/predict` applies before
      residualizing; fixed (route through `_fillna` first). `stacked.py`'s
      `_build_estimator` did a shallow `dict(spec)` copy, so a config-set
      `alphas` would apply on CV fold 0 only and silently vanish after
      (dormant — no shipped config sets it yet, but Phase 3's capacity work
      will); fixed to a real copy. `region_columns_for(metrics=None)`
      crashed (`.isin(None)`) unlike `build_region_matrix`'s symmetric
      `None`-means-all-metrics; fixed. Stale "2/180"/"248/426"
      surface-coverage comments across `config/models/*.yaml` corrected —
      coverage is now ~93% (2466/2647 v26 sessions).

      **Phase 1 (harness can now answer the question)**: `evaluate()` gained
      per-age-band MAE, `mae_balanced_{raw,corrected}` (mean of per-band
      MAE, so the old tail counts as much as the dominant 18-40 band),
      `mae_over_sd_raw`, and `cole_slope`. Folds are now
      `StratifiedGroupKFold` on age decile (`_make_strata`, shrinks bin
      count rather than the caller's requested fold count on small data) —
      plain `GroupKFold` had no seed and no age balance. New `repeats`
      param reruns the whole CV with different seeds. New
      `bagpipe.models.compare.paired_bootstrap` (resamples *subjects*, not
      rows) gives a leaderboard gap a confidence interval instead of a bare
      point estimate. Wired into `promote()`: promoting to `stage=
      "production"` now compares the challenger against the incumbent's own
      stored `predictions` and raises `PromotionRejected` unless the CI on
      `mae_corrected` confidently favors the challenger (`hi < 0`) —
      `--force` overrides. `AGE_BANDS` moved to `bagpipe.models.evaluate`
      (canonical home) with `bagpipe.app.pipeline.predict` now importing it
      rather than duplicating it — models importing app would have been the
      wrong dependency direction.

      **Phase 2 (freed the compute)**: the nested bias-correction CV cost
      `n_splits * (1 + bias_cv_splits)` model fits (30 at defaults) to get a
      held-out estimate for the corrector. Replaced with a
      leave-one-outer-fold-out estimator (`bias_correction_method="lofo"`,
      now the default): fit all outer folds once, then fit fold k's
      corrector on the pooled OOF predictions of every *other* fold — same
      leakage guarantee (fold k's subjects are never in that pool), 1x the
      fits. **Verified on real data** (`outputs/datasets_v26`, n=2333, 432
      regions, `stacked_v26.yaml`'s ridgecv_interactions): lofo 226s vs
      nested 1339s (5.9x, matches the ~6x prediction), `cole_slope` 0.7294
      vs 0.7154 and `mae_corrected` 5.479 vs 5.574 — agree within noise.
      `bias_correction_method="nested"` kept (not config-exposed — internal/
      validation only) for exactly this check. Second real bug fixed in the
      same pass: `RegionalStackingRegressor`'s own internal `outer_cv` (for
      the meta-learner's OOF matrix) went through `check_cv` unguarded,
      producing a **plain, non-subject-grouped** `KFold` — with ~330
      subjects having >1 session, a subject's sessions could land on both
      sides of the stacker's own internal split, optimistically biasing
      what the meta-learner trains on (the outer bagpipe-level CV stayed
      honest throughout — this was an inner-stage leak, same *class* of bug
      as the SFCN inner-split leak fixed 2026-08-19c). Fixed via
      `stacked._grouped_outer_cv`: precompute a `GroupKFold` split on the
      training fold's own subject array and pass the materialized index
      pairs as `outer_cv=` (`check_cv` accepts a precomputed iterable
      as-is). Required changing `evaluate()`'s `model_fn` contract from
      `model_fn()` to `model_fn(groups)` (the training fold's subject
      array) — three call sites (`baseline.py`, `sfcn.py` ignore it;
      `stacked.py` uses it; `promote.py`'s final refit and
      `scripts/feature_ablation.py`'s stacker builder updated to match).
      Full suite 129/129 passing, ruff clean (no new debt). **Not yet
      done**: Phase 3 (region fusion — surface/volume regions currently
      share 0 names across the two atlas naming conventions, so
      `stacked_v26_surface` never actually fuses modalities per region;
      sample weighting against the 18-40 age skew; spending the freed
      compute on HGBR base learners), Phase 4 (wire surface parsing into
      the app pipeline — currently only `db/ingest_cat12_cohort.py` has it,
      `app/cat12_parse.py` doesn't, so no surface model can serve uploads
      yet), Phase 5 (SFCN+stacked ensemble, promote, re-enable the
      promote cron).*
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

      *Update (2026-08-23): job queue, report, email, and per-job consent
      landed (commit `62afb1f`, not recorded here at the time — this entry
      backfills that gap). Huey/SQLite job queue (`bagpipe.app.queue`,
      `bag app worker`); `POST /predict` enqueues and returns immediately,
      `GET /jobs/{id}` polls status/result (`bagpipe.app.api`, 4 tests in
      `tests/test_api.py`, previously zero coverage). HTML/PDF report via
      WeasyPrint (`bagpipe.app.report`) and email delivery
      (`bagpipe.app.email`, plain `smtplib`). Fixed a real privacy gap:
      `retain_uploads=False` was recorded per job but never enforced —
      added `_delete_imaging()` to actually remove `anon/`+`cat12/` after
      a job finishes. Also: `bag preprocess cat12-cohort` gained surface
      (cortical thickness) ROI extraction — CAT12's own-atlas surface
      batch field doesn't work on this CAT26 build (real single-subject
      test, `docs/cat12_container_spec.md` §4b), replaced with
      `bagpipe.app.surface_atlas` (nearest-vertex resampling from CAT12's
      native thickness + `sphere.reg` onto any atlas grid, validated
      against CAT12's own DK40 output, <0.01mm diff), wired into `bag
      ingest cat12-cohort` so every surface-processed session gets
      Schaefer-7N regional thickness automatically.*

      *Update (2026-08-23, same day): deploy-readiness pass. Two real gaps
      found and fixed: (1) `retain_uploads` (upload retention/consent) was
      only a global config default (`app.retain_uploads`), not the
      per-upload explicit opt-in the design doc and CLAUDE.md's hard
      constraints actually call for — added `retain_uploads` as a
      `/predict` form field, threaded through
      `queue.process_job`/`pipeline.run_manifest`; the global config key
      is gone. (2) `bagpipe.app.api`'s module docstring still said
      retention/deletion wasn't wired, contradicting the code added the
      same day — fixed. Added `deploy/` (systemd unit templates for
      `bagpipe-api`/`bagpipe-worker`, `deploy/README.md`: install, reverse
      proxy requirement — the app has no auth and must never sit directly
      on a public interface — SMTP, retention semantics, and a
      pre-production checklist). `docs/getting_started.md` §5 now points
      there instead of a stale "not yet production-verified" note.
      **Not yet done, and still the real blockers before this is actually
      production-ready**: no request auth on `/predict`/`/jobs/{id}`; the
      §6 reproducibility suite hasn't been re-run against the rebuilt
      `cat12.sif` (owed since the 2026-08-23 surface-binary fix);
      `container/atlas/PROVENANCE.md` still missing; SMTP has no
      TLS/auth wiring (assumes a local relay). None of this was
      exercised against a real upload/GPU/container run this session —
      verified only via the existing synthetic test suite.*

      *Update (2026-08-24): public-abuse protection + email auth, following
      maintainer decisions (this app is meant for the general public, no
      login; recommend-from-scratch on email). Three new layers, all
      config-gated so a fresh `config/local.yaml.example` still works
      unconfigured for local dev: (1) Cloudflare Turnstile
      (`bagpipe.app.turnstile`, stdlib `urllib` POST to Cloudflare's
      siteverify endpoint — fails closed on any error) gates `/predict`,
      skipped with a logged warning if `app.turnstile_secret_key` is unset;
      (2) `app.max_queue_depth` (default 5) rejects new jobs with `503` via
      `huey.pending_count()` once that many are already queued — protects
      the single GPU from an unbounded backlog; (3) an nginx
      `limit_req`-based per-IP throttle documented in `deploy/README.md`.
      Added `GET /` (`bagpipe.app.upload_page`, stdlib `string.Template`
      matching `bagpipe.app.report`'s existing no-framework approach) — a
      plain HTML upload form + poll loop, since a JSON-only API isn't
      actually usable by "general public, no login" without one.
      `bagpipe.app.email.send()` gained optional `smtp_user`/
      `smtp_password` (STARTTLS + `AUTH LOGIN` when set) — the missing
      piece flagged in deploy/README.md's checklist, needed for any real
      transactional provider. `deploy/README.md` now recommends Resend
      (free tier, SMTP-compatible, documented setup) instead of leaving
      SMTP as a "figure it out" TODO. 8 new tests
      (`tests/test_turnstile.py`, `tests/test_email.py` auth paths,
      `tests/test_api.py` upload-page/turnstile/queue-depth cases); 23
      app-layer tests + ruff pass. **Not exercised against a real
      Cloudflare account, real Resend account, or real network traffic**
      — verified only via mocked `urlopen`/`smtplib`. Still not done:
      request auth on `GET /jobs/{id}` (deliberately deferred — treated as
      a possession-of-the-UUID-link model, see deploy/README.md), the §6
      CAT12 reproducibility re-run, `container/atlas/PROVENANCE.md`.*

      *Update (2026-08-24): `container/atlas/PROVENANCE.md` written
      (source/space/license for every atlas file, and which are actually
      read at runtime vs. dead weight per §4b) and §6 reproducibility-suite
      tooling built (`bagpipe.preprocess.repro_test`, `bag preprocess
      repro-test --config config/repro_test.yaml`): stratified subject
      selection (12 age-tertile×sex + 2 lowest-IQR stress cases, queried
      straight from `session`/`demographics`/`cat12_quality`) feeds each
      subject's raw T1w through the real `run_manifest` stage graph — the
      same code `/predict` runs — then diffs its features/BAG against the
      stored `features`/`predictions` rows for that subject, writing
      `docs/repro_reports/{image_digest}.md` per §6's acceptance criteria.
      Subject-selection query verified against the real DB (14/14 selected
      correctly, real subject IDs/ages/IQRs). **Blocked before an actual
      run**: `paths.bids_root` (`//132.66.46.62/Bids`, SMB) is unreachable
      from this machine right now — `ls`/glob against it returned nothing
      and a direct `ping 132.66.46.62` showed 100% packet loss ("Host is
      down"). This is a network/server-availability issue, not a bagpipe
      bug — run `bag preprocess repro-test` once that share is reachable
      again.*

      *Update (2026-08-24): additional surface parameters (gyrification,
      sulcal depth, fractal dimension, area) added, per maintainer request
      to capture more than cortical thickness. **Real bug found first**:
      `output.surf_measures = 1` (`config/cat12_cohort.yaml`) never did
      anything — no such field exists in `cat_standalone_segment.m`'s real
      schema (checked the bundled `.m` directly), silently ignored; real
      cohort output on disk confirmed it — no gyrification/depth/
      fractaldimension files despite the line being set for the whole
      2026-08-23 run. GI/SD/FD/area are a genuinely separate CAT12 module,
      `stools.surfextract`, not exposed via any `estwrite` field and not
      shipped as a standalone-package `.m` template. Wired into
      `container/cat12.def`'s `%post` as **job 2**, chained to job 1's
      central-surface output via direct deterministic-path construction
      (not `cfg_dep` — `surfextract`'s real dependency registration is
      compiled inside `spm25.ctf`, unreadable). Per maintainer's explicit
      choice (asked directly, given the tradeoff), `output.surface` is no
      longer patched to `0` for inference — surface reconstruction +
      `surfextract` now run for **every** caller through the one shared
      `batch_template.m`, not just cohort reprocessing, trading real
      inference latency (~2-3x a volume-only run, already within the
      existing 90-min pipeline timeout) for one template instead of a
      second gated one. `bagpipe.app.surface_atlas` genericized from
      thickness-only to any per-vertex metric (`SURFACE_METRICS`);
      `bagpipe.app.cat12_parse.parse_surface_regional` gained a `metric`
      param (`SURFACE_METRIC_TAGS`) for the DK40/Destrieux path via
      `catROIs_*.xml`; `ingest_cat12_cohort.py` loops all metrics for both
      the native-atlas and custom-Schaefer paths. Full test suite (80) +
      ruff clean. **Not yet verified against real data**: no `cat12.sif`
      built on this machine right now, so the `surfextract` field names
      and the resulting `surf/{lh,rh}.{gyrification,depth,
      fractaldimension,area}.*` filenames are a best-effort read of
      CAT12's documented batch GUI, unconfirmed against this build's
      actual (compiled, uninspectable) behavior. Before trusting any of
      it: rebuild the image, run `bag preprocess cat12-cohort` with
      `limit: 2`, confirm those files actually appear with plausible
      values — see `docs/cat12_container_spec.md` §4d.*

      *Update (2026-08-24, same day): surfextract wiring rebuilt and
      verified against real container runs — two more real bugs found
      and fixed, both only catchable against an actual build. (1) The
      hand-written `surfextract` field spec broke the WHOLE batch load
      ("No executable modules, but still unresolved dependencies or
      incomplete module inputs"), not just a silent no-op — root-caused
      by fetching CAT12's real public source
      (`github.com/ChristianGaser/cat12/blob/main/cat_conf_stools.m`,
      since the compiled build here can't be statically inspected):
      `data_surf`'s cfg_files filter only accepts `^lh.central` — passing
      an rh path (my first attempt) made the required input invalid; also
      `tGMV` isn't a real field (full real list: area, gmv, GI, SD, FD,
      tGI, lGI, GIL, surfaces, norm, FS_HOME, nproc, lazy). Fixed: single
      lh path (CAT12 finds rh itself, same pattern as `stools.surfresamp`),
      `tGMV` dropped. Verified job 2 alone (hardcoded path to an existing
      central surface) ran clean in ~5min producing
      `lh/rh.{area,gyrification,depth,fractaldimension}` — confirming the
      field fix. (2) Re-running the FULL two-job batch through the real
      `apptainer run` interface still failed instantly with the identical
      error — isolated to `cat_standalone.sh`'s own `<UNDEFINED>`/`-a`
      substitution mechanism itself, which works fine for a one-job batch
      but silently breaks once `batch_template.m` has a second job
      (confirmed by hand-substituting the real path into a template copy
      and invoking `cat_standalone.sh -b` directly — that ran clean).
      Root cause inside `cat_standalone.sh` wasn't chased further; fixed
      by moving the substitution into `%runscript` itself (plain shell —
      parses `-a`/positional args, builds the `estwrite.data` cell-array
      literal, sed-substitutes it into a fresh copy of `batch_template.m`,
      then calls `cat_standalone.sh -b <resolved file>` — no `<UNDEFINED>`,
      no `-a`, ever). Caller contract unchanged (`bagpipe.app.pipeline.
      segment` / `bagpipe.preprocess.cat12_cohort` needed no code
      changes). **Real production incident, self-caused and self-fixed
      same session**: `outputs/containers/cat12.sif` (the actual deployed
      image — the earlier "not yet built on this machine" note above was
      about a *different*, unused `container/cat12.sif` path) got
      overwritten with the still-broken first attempt before this was
      caught; reverted from `.bak-2026-08-23` within minutes, verified via
      checksum, before any real inference/cohort traffic hit it. **Fully
      verified end-to-end after the real fix**, twice — once via a direct
      `-b` bypass, once via the actual `apptainer run -a` caller
      interface — both completed clean with no MATLAB errors and all of
      `lh/rh.{area,gyrification,depth,fractaldimension}` present.
      Redeployed to `outputs/containers/cat12.sif` (checksummed against
      `container/cat12.sif`). Per maintainer's explicit request: the
      **entire** cohort ledger was reset to `queued` (not just the
      previously-unprocessed subjects) and a full from-scratch
      reprocessing of all ~5983 subjects launched in a detached `tmux`
      session (`cat12_cohort_full`, survives the maintainer logging out;
      log at `outputs/cat12_cohort_full_run.log`) — every subject,
      including the ~305 already done under the old pre-surfextract
      image, gets the full surface panel this time. `config/
      cat12_cohort.yaml`'s `limit` reset to `null`. Not yet done: the run
      itself is still in progress (multi-day, per the throughput estimate
      in `docs/cat12_container_spec.md` §7) — nothing downstream should
      assume the new surface metrics have real cohort-wide coverage until
      it finishes.*

      *Update (2026-08-24, same day): modeling side wired up for the new
      surface metrics, in parallel with the cohort reprocessing above.
      `bagpipe.models.tabular.build_region_matrix`/`region_columns_for`
      gained an `atlases` filter (threaded through `stacked.py`/
      `baseline.py` as `features.atlases`) — needed because every surface
      metric (thickness included) exists on THREE surface atlases
      (`surf_DK40`/`surf_Destrieux`/`surf_Schaefer2018N400n7`), and
      filtering by `metric` alone (the only filter that existed before)
      pulls all three into one flat matrix — confirmed as the actual
      cause of the 2026-08-24 CAT26-cohort-modeling r² collapse
      (0.76→0.59) when only `thickness` was fused that way.
      `config/models/stacked_v26_surface.yaml` now requests the full
      panel (`vol_gm, vol_wm, vol_csf, thickness, gyrification,
      sulcal_depth, fractal_dimension, area`) restricted to
      `atlases: [Schaefer2018N400n7Tian2020S2, surf_Schaefer2018N400n7]`
      — one consistent 400-region parcellation across every metric,
      instead of the volume atlas fighting three different surface
      atlases for an undersized sample. New test
      (`test_build_region_matrix_atlases_filter`); full suite (81) + ruff
      clean. Notebooks updated to describe the panel:
      `notebooks/surface_atlas_review.ipynb` gained §7 (per-metric
      coverage/distribution/network-structure) and §8 (why the `atlases`
      filter matters); `notebooks/stacked_ensemble_review.ipynb`'s stale
      "why only thickness" note replaced with the real fix description;
      `notebooks/db_review.ipynb`'s surface section/plots fixed to filter
      `metric == "thickness"` explicitly (a real bug this update would
      otherwise have introduced silently — that cell's histogram used to
      implicitly assume one metric per surface row, now false). **Not yet
      done, and the actual next step**: nothing above has real cohort-wide
      data behind it yet — the full reprocessing launched in the previous
      update is still running. Once it's further along, re-run
      `bag export training-table --source cat12_v26` and
      `config/models/stacked_v26_surface.yaml` for a real (not
      197-sample) leaderboard number, and reconsider promoting a v2
      production model only once that's trustworthy.*

      *Update (2026-09-03): pre-launch hardening pass, targeting a public
      deployment at **https://brainage.aevantis.app** (Cloudflare Tunnel,
      domain registered same day). Two independent audits of the app and
      the inference path found four critical defects, all fixed:

      **(1) Arbitrary file write.** `api.py` wrote uploads to
      `job_dir/"input"/file.filename` with the client-supplied multipart
      filename passed through verbatim — Starlette does not sanitize it.
      Verified: `'../../../../../../tmp/pwned.txt'` resolved outside
      `uploads_dir`, and `mkdir(parents=True)` created the path first.
      Unauthenticated arbitrary file write as the app user, on an endpoint
      designed to be open to the public. Fixed: the client filename now
      only *selects an extension* from an allowlist
      (`.nii`/`.nii.gz`/`.zip`); bytes always land at a fixed
      `input/upload<ext>`, so the string never reaches a path.

      **(2) The retention consent was a lie.** There were two `input/`
      dirs — `api.py` wrote the raw upload to `{job_id}/input/`, the
      pipeline copied it to `{job_id}/run/input/`; `anonymize` deleted
      only the latter and `_delete_imaging` only `run/anon`+`run/cat12`.
      **Nothing ever deleted `{job_id}/input/` or `run/ingest/`, both of
      which hold raw PRE-DEFACE T1w.** Found 5 such volumes on disk, every
      one from a job with `retention_opt_in: false`, under filenames
      carrying real subject IDs — while the upload page promised deletion.
      `tests/test_queue.py` had encoded the bug as expected behavior.
      Fixed: `_delete_imaging` now covers all four locations, guards that
      every path resolves under `uploads_dir` before `rmtree`, and runs in
      a `try/finally` so a `_notify` failure can no longer skip cleanup
      (`email.build_success_email`'s unguarded `pdf_path.read_bytes()` was
      the live path that did exactly that — now guarded too, and the mail
      still goes out with the results link if the PDF is unreadable). The
      5 retained scans were moved out of `uploads_dir` to
      `outputs/dev_jobs_archive/` (not deleted — `smoketest_run/` holds a
      complete CAT12 tree worth ~70 min of compute; delete after launch).

      **(3) The promote cron was about to break every upload.**
      `scripts/periodic_promote.sh` had been switched to
      `stacked_v26_surface.yaml`. That model declares five surface metrics,
      but the app's `FeaturesStage` parses `catROI_*.xml` volume tissues
      only — `bagpipe.app.surface_atlas` is wired into
      `db/ingest_cat12_cohort.py` and **nowhere in the app pipeline** — so
      every job would have died at `extract_features` with
      `FEATURE_SCHEMA_MISMATCH`. Caught before its first run (the edit
      landed at 09:08, after that morning's 05:00 promotion, so production
      `model_id=31` was still safely volume-only). Reverted to
      `stacked_v26.yaml` with a comment explaining why it must stay there,
      and **the promote cron is commented out for the launch weekend** —
      re-enable Mon 2026-09-07. A production model that silently changes
      under live users every morning is not a thing to debug during a
      launch.

      **(4) The model is not equally valid across the ages it accepts.**
      Recomputed from the production model's own held-out `predictions`
      (n=2260, 1902 subjects): MAE 4.03y @18-30, 3.95y @30-40, 6.11y
      @40-50, 9.91y @50-60, **10.71y @60-70, 11.00y @70-90**. 80% of
      training is 18-40. Cole's fitted slope is 0.713, so the correction
      **amplifies deviations 1.40x** — and `mae_corrected` (5.75) is worse
      than `mae_raw` (4.85) overall, yet the corrected value is the
      headline. Worse, `predict.py` hard-failed `AGE_OUT_OF_RANGE` on the
      *corrected output*, so a raw 75 became a corrected 91.8 and errored
      **after the full ~70-minute CAT12 run**. Maintainer's decisions:
      accept 18-90, show a per-band accuracy warning, keep the corrected
      headline but print a ±MAE band beside it. Implemented: band MAE is
      computed at request time from the promoted model's own `predictions`
      rows (reusing the query that already refits Cole — it must track
      whichever model is promoted, so nothing is hardcoded), small bands
      fall back to overall MAE, and an out-of-range corrected age is now
      *reported as a warning*, never raised. Real training support
      (9.2-84.7, p5-p95 21.4-60.0) replaced the hardcoded "(18.0, 90.0)"
      in the user-facing text.

      Also fixed: `region_columns_for` was called without `atlases=` at
      inference though `promote.py` passes it at training time (3296 vs
      3515 columns — harmless for today's volume-only model, silently
      wrong for any surface model); `features.py`/`predict.py`/
      `normative.py` fell back to `paths.datasets_dir` (the retired pooled
      export) instead of the model's own `datasets_dir`; no shape
      assertion before `model.predict`; `fit_norms` refit 1296 OLS
      regressions per job despite its own docstring saying to cache;
      `/jobs/{id}` 404'd before worker pickup, which combined with an
      unguarded `body.stages.length` in the poll loop to make the page
      hang on "Queued" forever for any second concurrent user; no upload
      size/type/age/sex validation; no `job_id` UUID validation; no
      subprocess timeout on `pydeface`/`dcm2niix`; uncapped zip
      extraction; no global exception handler; no way to fetch the PDF
      without email. New: `GET /jobs/{id}/report.pdf`, worker-startup
      reconciliation of jobs stuck in `running`, `bag app retention-sweep`
      + `scripts/retention_sweep.sh` (nothing had ever deleted opted-in
      data), and `app.max_upload_size_mb` (100 — Cloudflare's free-plan
      body limit is the real ceiling, so the app rejects first with a
      message we control) and `app.public_base_url`.

      **Stale docs corrected**: CAT12 version parity has been fine since
      2026-08-25 (the training cohort *is* CAT26, produced by the same
      `cat12.sif` the app runs) — the "CAT26.0.rc3 vs CAT12.9/2577
      mismatch" warnings were obsolete. Turnstile config keys were always
      correct. `models_registry` has exactly one production row (the
      `database is locked` traceback rolled its whole transaction back).
      The `/jobs/{id}/volume/t1.nii` 404s were correct behavior — the file
      is deleted for non-retaining jobs.

      Test suite 74 -> **118 passing**, ruff clean (4 pre-existing E501s in
      `style.py`/`test_bias_correction.py` untouched). Deployment: real
      systemd **user** units for api/worker/tunnel live in
      `~/.config/systemd/user/` (NOT the repo — public repo, machine paths);
      `deploy/systemd/*.service` stay as templates and gained a
      `bagpipe-tunnel.service` one. `deploy/README.md` rewritten for the
      tunnel (no nginx in this deployment — Cloudflare terminates TLS and
      a WAF rate-limit rule replaces `limit_req`).

      **Not yet done / owed before calling this launched**: the §6
      reproducibility suite is RUNNING as of this update (`bag preprocess
      repro-test`, 14 stratified real subjects through the real stage
      graph, diffed against their stored `features`/`predictions`) —
      `/mnt/62` came back, which had blocked it since 2026-08-24; nothing
      here is verified against real data until it lands. Also owed: a real
      browser upload through the tunnel with a live Turnstile challenge
      (the captcha correctly fails closed, so this cannot be tested from
      curl); `loginctl enable-linger` (needs sudo, or the services die on
      logout); Resend + rotating the Gmail app password that is still
      plaintext in `config/local.yaml`; the Cloudflare WAF rate-limit
      rule; adding the new hostname to the Turnstile widget. Deliberately
      out of scope for launch: wiring surface metrics into the app (would
      unlock the better model, mae_raw 4.69 vs 4.86), and disabling
      surface reconstruction for inference (uploads currently pay ~2-3x
      latency for `surfextract` output the app never parses — a real win,
      but it needs a container rebuild and re-verify).*

      *Update (2026-09-07): report richness/interactivity pass — the results
      page and the emailed PDF are now one report rendered by shared code,
      not a rich page plus a receipt. Full spec: `docs/report_contents.md`.

      **Readable region names, derived not hand-written.** Every user-facing
      surface showed raw atlas labels (`LH_Vis_23`, `pGP-lh`). New
      `scripts/build_region_names.py` derives an anatomical name for each of
      the 400 Schaefer parcels as the **modal Desikan-Killiany label over its
      vertices** — `container/atlas/{lh,rh}.schaefer2018_400p_7n.annot` and
      `{lh,rh}.aparc_DK40.freesurfer.annot` label the same 164k fsaverage
      surface, so this needs no new input, no network access, and no
      400-row hand-curated table to drift out of sync with the atlas (median
      overlap 0.82; 93 parcels below 0.60 get a two-gyrus name and are
      flagged `approx.` in the UI rather than presented as exact). The 32
      Tian S2 subcortical labels are expanded from their documented
      abbreviation scheme. Output `src/bagpipe/app/static/atlas/
      region_names.json` is committed (atlas metadata, no subject data) and
      read at runtime by `bagpipe.app.region_names` server-side and by the
      three JS widgets browser-side — no nibabel at runtime. Display names
      are numbered within (hemisphere, anatomy) so they're unique.

      **Five figures, shared by both surfaces.** New `bagpipe.app.charts` —
      pure functions returning inline SVG, palette passed in
      (`DARK`/`PRINT`). Server-rendered deliberately: WeasyPrint has no JS,
      so anything drawn client-side is a figure the PDF could never have,
      and the two surfaces drifting apart is exactly what this prevents.
      `bag_distribution` (cohort gap distribution, reader's bin
      highlighted + percentile), `calibration` (predicted-vs-chronological
      band per age bin — makes the model's age-dependent error *visible*
      rather than asserted in a caveat), `network_profile` (Yeo-7 +
      subcortex means, on their own narrow axis so a 57-parcel mean never
      looks like a single parcel's z), `zscore_spread` (the reader's whole
      regional profile against the standard normal — with 432 regions ~20
      land beyond ±2σ by chance, and the overlay says so), and
      `deviation_ranking` (diverging lollipops over a shaded ±1σ band,
      replacing the old bare table of atlas labels).

      **Cohort context, aggregate only.** `predict._population_context`
      computes percentile / histogram / per-5-year-bin calibration from the
      production model's own held-out `predictions` rows (same rows as the
      Cole corrector and the band MAE, so they can't disagree), written into
      `prediction.json` alongside the newly-persisted `chronological_age`.
      **Deliberately aggregate**: the reference cohort is real SNBB data and
      this payload is served to a public browser, so bins below
      `MIN_BAND_N`=10 are dropped and no per-subject row — not even an
      anonymous (age, prediction) pair — leaves the machine.

      **Region explorer + shared selection.** New
      `static/js/region-explorer.js`: search, group by network/lobe/
      hemisphere, sort, filter to beyond ±2σ, per-row diverging bar drawn
      against a fixed ±3σ axis with the ±1σ band shaded (so an ordinary
      value looks ordinary, which a sorted list of numbers alone hides),
      expandable rows showing every tissue metric. New
      `static/js/region-bus.js` gives the explorer, the SVG brain map and
      the 3D viewers one shared selection — clicking a region anywhere
      selects it everywhere, with the brain map switching cortical/
      subcortical atlas as needed and the explorer clearing a filter that
      would hide what the reader just clicked. The 3D viewers' hover readout
      now says "Left fusiform gyrus 1" instead of "Region 217", and a click
      on the mesh selects.

      **LLM prose hook.** New `bagpipe.app.narrative`: `generate()` behind
      which `_llm_narrative` is the (unwired, returns `None`) LLM path and
      `_template_narrative` is a deterministic generator that always runs —
      a report should never ship an empty explanation box, and a rule-based
      paragraph that is *correct* beats an eloquent one that is
      unverifiable. `build_context()` is deliberately the entire future
      prompt payload (derived stats + readable names; no imaging, no
      identifiers, no raw features, no paths — there is a test asserting
      this), `PROMPT_TEMPLATE` and `COPY_RULES` carry the wellness-not-
      medical copy constraints, and the LLM path sits inside `generate`'s
      try/except so a provider outage degrades the prose rather than failing
      an hour-long job at its last stage. Rendered block is labelled with
      its source.

      **Three real bugs fixed along the way**: (1) `brainmap.js`'s deviation
      legend was a hardcoded blue→red gradient while the regions themselves
      were painted teal→amber — the key did not describe the map it belonged
      to; now built from `zToColor`'s own stops. (2) The new results-page CSS
      redefined `.prose`, which `BASE_CSS` already owns as the landing
      page's narrow 34em text column — renamed to `.narrative` (the
      narrative block was rendering as a 400px column mid-page). (3) A chart
      with no data returns `""`, which used to leave an empty framed card
      with a caption floating under it on both surfaces; both now emit the
      whole figure or nothing.

      Tests 129 → **168 passing** (`test_region_names.py`,
      `test_charts.py`, `test_narrative.py`, `test_results_page.py` new;
      `test_report.py` rewritten against real atlas columns and asserting
      raw labels never reach the reader; `test_pipeline.py` extended with
      the population-context privacy contract). Ruff clean on everything
      touched (the 12 remaining repo-wide E501s are pre-existing, in
      `models/`, `scripts/feature_ablation.py` and two model test files).
      **Verified against a real browser**, not just string assertions:
      Chromium/Playwright drives search → group → sort → outlier filter →
      explorer-to-map selection (including the automatic cortex/subcortex
      switch) → map-to-explorer selection → metric switch, with no page
      errors; the PDF is rasterised and inspected page by page. **Not yet
      verified against a real job**: everything here ran against a
      synthetic `prediction.json`, since this session has no DB, no
      promoted model and no CAT12 container — the first real upload after
      deploy is still the thing that proves it end to end.*

      *Update (2026-09-08): recovered a real production regression — a
      2026-09-06 landing-page redesign (multi-page split `/`, `/science`,
      `/team`, `/privacy`, `/upload`; brain panel sticky-centered, not glued
      to the top; click-drag OrbitControls rotation instead of scroll-driven)
      had only ever landed in a `git stash` before a `pull --ff-only`, and a
      later session rebuilt the single-page landing page from its pre-stash
      state without knowing the stash existed — so the redesign was live on
      disk for two days but never actually served. Found via `git stash
      list` + `git log --all` (the stash's untracked-files parent commit
      held the new `pages.py`/`reveal.js`, never committed anywhere).
      Re-applied onto the landing page's current content (which had grown a
      Sample report section since the original stash), splitting
      `landing_page.py` into `bagpipe.app.pages` (`render_landing`/
      `_science`/`_team`/`_privacy`/`_upload`, five routes in `api.py`);
      `cortex-viewer.js` now always runs OrbitControls (click-drag +
      idle auto-rotate, wheel-zoom disabled) instead of the old
      scroll-tied/`interactive`-flag split; new `static/js/reveal.js` drives
      the shared scroll-in-view fade shared by all five pages. Also added
      an `api.py` middleware forcing `Cache-Control: no-cache` on
      `/static/*` — Cloudflare's ~4h edge default for static extensions was
      the first (wrong) theory chased for "why don't I see the fix," and is
      a real risk for the next static-asset deploy even though it wasn't
      the actual cause this time. Full details and the recovery method:
      `docs/design-brief.md` §5's 2026-09-08 note. Test suite 196/196 +
      ruff clean. **Lesson for future sessions**: an uncommitted `git
      stash` survives a `pull --ff-only` on disk but is invisible to
      anyone not specifically looking for it — prefer committing
      work-in-progress to a branch over stashing across a pull.*

      *Update (2026-09-08, later same day): the actual cause of several
      more rounds of "still doesn't work" on the landing brain (idle
      auto-rotate removed, then a real touch-scroll-vs-rotate conflict
      fixed — both real bugs, both correctly fixed) turned out to be a
      third, separate problem underneath: **Cloudflare's edge cache for
      `/static/*` ignores `api.py`'s `Cache-Control: no-cache` origin
      header** and applies its own ~4h Browser Cache TTL instead, and does
      so *inconsistently across edge PoPs* — repeated fetches of the exact
      same URL, seconds apart, alternated between an hours-stale
      `cortex-viewer.js` (no `OrbitControls` at all — pre-dating this whole
      session) and the current one. Confirmed directly: importing the live
      module in-page and reading `CortexViewer.prototype._initScene.
      toString()` showed the *old* source despite `curl` against the same
      URL, moments apart, showing the current one. This is why the landing
      page and the results page's brain viewer (identical code, both go
      through `cortex-viewer.js`) could visibly behave differently for the
      same visitor — not a code difference, a cache one. No code fix closes
      this (versioning the *entry* `<script src>` doesn't help — the actual
      stale resource is a nested `import` inside another module, which
      would need every internal import specifier re-templated per deploy
      to bust the same way). Documented as an infra fix instead:
      `deploy/README.md`'s new "Static asset caching" section — a
      Cloudflare Cache Rule bypassing `/static/*` (or honoring origin
      headers) is required; this needs dashboard/API access this session
      doesn't have. **Until that Cache Rule is added, do not trust "the fix
      didn't work" reports about anything under `static/` as proof the
      code is wrong** — check the served file's actual content in-browser
      (not just `curl`, which can hit a different, luckier edge PoP)
      before re-diagnosing as an app bug.*

Update the checkboxes and add dated notes here as phases complete, so every session
starts with accurate context.

## Machine-specific facts (filled in during Phase 0, 2026-08-19)

- BIDS root: `/mnt/62/Bids` (SMB share; referenced via config, never hardcoded)
- CAT12 tabular (ROI/global scalars): `/mnt/62/Processed_Data/derivatives/tabular_cat12` (SMB)
- CAT12 images (mwp1/wm NIfTI, used for training): `/media/storage/yalab-dev/BIDS/derivatives/CAT12.cohort_2026_08` (local disk, `source="cat12_v26"`) — **the only training cohort as of 2026-08-25**; `CAT12.9_2577.new` (`source="cat12"`) is retired, kept on disk only as the pre-CAT26 comparison baseline, see Phase 2's 2026-08-25 update. Cohort is still being reprocessed (`.bagpipe_cat12_ledger.sqlite` under it tracks progress).
- qsiprep/qsirecon derivatives: `/mnt/62/Processed_Data/derivatives/{qsiprep,qsirecon,tabular}` (SMB, not yet ingested — dMRI is a later phase)
- Tabular exports directory: `/mnt/62/Processed_Data/derivatives/tabular` (SMB)
- Shared DB (brainlink + bagpipe tables): `/media/storage/brainlink/brainlink.db`
- GPU: NVIDIA GeForce RTX 3070 Ti — driver not currently loaded, needs install before Phase 2
- OS: Ubuntu 24.04.4 LTS; CUDA: not yet installed

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
