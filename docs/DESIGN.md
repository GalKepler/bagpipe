# bagpipe — Brain Age Gap Project Design Document (v0.2)

*Draft for discussion. Everything here is a proposal; push back on anything.*

## 1. Summary of the situation

We have one single-site Israeli dataset (SNBB): ~4,500 participants, ~6,000 sessions with repeated measures, all with T1w and most with dMRI, already in BIDS and already processed (CAT12 for T1w, qsiprep+qsirecon for dMRI). Tabular demographics and a one-time questionnaire live in Google Sheets/Excel with a *different* ID scheme than the imaging data. Everything sits on a personal workstation with a single GPU, must stay local, and the codebase will be public on GitHub with extensive documentation for you, your PI, and collaborators.

This shapes every choice below: the stack is single-machine, file-based, Python-first, and free. The code is public; the data never is. That separation (public code / private data) is a first-class design constraint.

## 2. Architecture overview

One monorepo, four packages sharing a common core, all reading from a single canonical database:

```
bagpipe/                           # public GitHub repo
├── pyproject.toml                 # one installable package: `bagpipe` (CLI: `bag`)
├── README.md, docs/               # mkdocs-material documentation site
├── config/                        # YAML configs (paths, model configs, etc.)
├── src/bagpipe/
│   ├── core/                      # shared: config loading, logging, ID mapping, paths
│   ├── db/                        # Pillar 1: schema, ingestion, queries, exports
│   ├── models/                    # Pillar 2: datasets, base/meta learners, CNNs, eval
│   ├── causal/                    # Pillar 3: cohort builders, designs, analyses
│   └── app/                       # Pillar 4: FastAPI app, worker, report generation
├── scripts/                       # one-off CLI entry points (ingest, train, serve)
├── tests/
└── notebooks/                     # exploration; never the source of truth
```

The critical invariant: **all data access goes through `bagpipe.db`**. Models, causal analyses, and the web app never touch raw CSVs or Google Sheets directly — they query the database. This is what makes adding future datasets cheap: new data gets ingested once, and every downstream consumer picks it up automatically.

A second invariant: **paths and secrets live in a local, git-ignored config file** (`config/local.yaml`), never in code. The public repo contains the schema, the ingestion logic, and example configs — nothing that identifies the data.

## 3. Pillar 1 — Database

### 3.1 Storage choice: SQLite (canonical) + Parquet (analytical exports)

Recommendation: **SQLite** as the single source of truth, via SQLAlchemy models.

Reasoning: it's a single file (easy to back up — and please do back it up, along with the raw data, given that everything currently lives on one personal machine); it needs zero server administration; it handles this scale trivially (6,000 sessions × a few thousand features is small); the Pillar 4 web app can use the same engine for its job queue; and it satisfies the GUI wish for free — **DB Browser for SQLite** gives you and your PI point-and-click table browsing, and **Datasette** can serve a read-only local web UI in one command. For heavy analytical work (wide feature matrices for model training), `bagpipe.db` will provide export functions that materialize tidy Parquet files, which pandas/DuckDB read at full speed. SQLite is the truth; Parquet is the cache.

### 3.2 Schema (core tables) — **superseded, see deviation note below**

> **Deviation (2026-08-19):** the schema below was the original from-scratch
> proposal. In practice, a separate pre-existing project, **brainlink**, already
> implemented identity resolution, session/demographics ingestion from Google
> Sheets, and a file-manifest processing monitor against real SNBB data.
> Rather than duplicate that work, bagpipe **extends brainlink's SQLite DB**
> (physically `/media/storage/brainlink/brainlink.db`, pointed to by
> `config/local.yaml`'s `db_path`) instead of building `subjects`/`id_map`/
> `sessions`/`scans`/`derivatives`/`questionnaire` from scratch.
>
> brainlink owns: `participant` (uid PK), `session` (session_id PK, uid FK,
> lab, scan_date, ...), `demographics`, `questionnaire_response`,
> `imaging_path` (BIDS-entity-parsed file paths), plus ingest/validation
> logging tables. bagpipe adds, in `src/bagpipe/db/models.py`:
> - `features` — long format, as originally designed: `(subject_key,
>   uid|legacy_subject_id, session_id, source, atlas, region, metric, value)`.
>   Populated from CAT12 tabular outputs (`bag ingest cat12`).
> - `legacy_participant` / `legacy_imaging_path` — a second, un-joined cohort:
>   CAT12 has ~1,100 pre-SNBB subjects (12-digit timestamp IDs, never assigned
>   an SNBB `S######` ID). They have no `participant` row, so they get
>   parallel bagpipe-owned tables instead of brainlink's uid-FK'd ones.
>
> `predictions`, `models_registry`, `events`, `datasets`/`subject_dataset`
> are not yet implemented — planned for Phase 2/3 as originally scoped, still
> as bagpipe-owned tables extending the same DB file.
>
> Analytical exports (`bag export training-table`) materialize three Parquet
> caches under `paths.datasets_dir`: `globals.parquet` (wide, tabular model
> input), `regional.parquet` (long, per-region base-learner input), and
> `image_paths.parquet` (CNN input) — consistent with §3.1's "SQLite is the
> truth, Parquet is the cache."

```sql

```sql
subjects        (subject_id PK, sex, birth_year_or_dob, ...)         -- one row per person
id_map          (subject_id FK, source, external_id)                  -- imaging ID ↔ questionnaire ID
sessions        (session_id PK, subject_id FK, scan_date, age_at_scan,
                 session_label, scanner, protocol_version)
scans           (scan_id PK, session_id FK, modality,                 -- T1w, dwi, ...
                 bids_path, qc_status, qc_notes)
derivatives     (derivative_id PK, scan_id FK, pipeline,              -- 'cat12', 'qsiprep', ...
                 pipeline_version, path)
features        (scan_id FK, feature_set, atlas, region,             -- long format
                 metric, value)                                       -- e.g. ('cat12','neuromorphometrics','Hippocampus_L','GMvol', 3.91)
questionnaire   (subject_id FK, instrument, item, value, administered_date)
datasets        (dataset_id PK, name, description)                    -- SNBB now; others later
subject_dataset (subject_id FK, dataset_id FK)
predictions     (scan_id FK, model_id FK, predicted_age, bag_raw, bag_corrected)
models_registry (model_id PK, name, type, version, config_json, trained_date, metrics_json)
events          (event_id PK, name, start_date, end_date)             -- Oct 7, COVID waves, ...
```

Notes on the design. The `id_map` table is the answer to your ID-harmonization problem: subject identity is an internal `subject_id`, and every external scheme (imaging DB ID, questionnaire ID, any future dataset's IDs) maps into it. Features are stored long, not wide — this is what makes the DB extensible to new atlases, new metrics, and new pipelines without schema migrations; wide matrices are produced on demand by pivot queries. The `events` table exists so Pillar 3 analyses are reproducible queries rather than hand-edited date filters. And `predictions` + `models_registry` mean every BAG value in the system is traceable to a specific, versioned model.

### 3.3 Ingestion

Four ingestion modules, each idempotent (safe to re-run): (a) a BIDS walker that populates `sessions`/`scans` from the folder tree; (b) a CAT12 parser that reads the ROI XML/TSV outputs into `features`; (c) a qsirecon parser doing the same for dMRI regional metrics (FA, MD, etc.); (d) a tabular ingester for the Google Sheets/Excel exports (download the Sheets as CSV/XLSX first — the ingester works on files, keeping the pipeline offline-capable). The ID harmonization step will need a mapping file from you (imaging ID ↔ questionnaire ID); the ingester validates it, reports unmatched IDs on both sides, and stores the result in `id_map`.

The very first deliverable of Pillar 1 is a **data audit report**: how many subjects match across imaging/questionnaire, scan-date distributions, repeated-measures counts, and — crucially for Pillar 3 — how many subjects have scans straddling each event of interest. You said we'd know the longitudinal numbers "once Pillar 1 is done"; this report is where they appear.

## 4. Pillar 2 — Modeling framework

### 4.1 Structure

A config-driven harness with three layers. **Data layer:** functions that build model-ready matrices/volumes from the DB given a feature spec (e.g., "CAT12 GM volumes, neuromorphometrics atlas" or "T1w volumes, CAT12-normalized"). **Model layer:** a registry where each model type implements a common interface (`fit`, `predict`, `save`, `load`): tabular regressors (LightGBM/XGBoost/linear via scikit-learn), your per-region stacked ensemble, and 3D CNNs. **Evaluation layer:** a single CV engine that everything runs through.

Non-negotiable evaluation rules baked into the harness: splits are **grouped by subject** (a subject's repeated scans never span train/test); the stacked model's OOF predictions for the meta-learner are generated inside the same fold structure (no leakage from base to meta); metrics are MAE (primary) plus r/R² (reported); and **age-bias correction is a pluggable step** — I'll implement de Lange & Cole-style linear correction as the default (fit `predicted_age ~ true_age` on training folds, apply to test) with Beheshti's variant as an alternative, selected by config. Corrected and uncorrected BAG are both stored in `predictions`.

Your stacked approach ports in naturally: base learners are per-region models over that region's feature vector (GM vol, CSF, WM, MD, FA, ...), the meta-learner consumes their OOF predictions. The framework treats it as just another registered model, so it's directly comparable to a plain tabular model and to the CNN on identical splits.

### 4.2 CNN recommendation

Start with **SFCN** (Simple Fully Convolutional Network, Peng et al. 2021) — it's the architecture that won the PAC 2019 brain-age challenge, it's small enough to train on a single GPU, and pretrained UK Biobank weights are publicly available for fine-tuning. Plan: (1) fine-tune pretrained SFCN on SNBB, (2) train from scratch as a comparison, (3) optionally add a ResNet-3D baseline later. Input: since CAT12 has already run, use its affine-registered, bias-corrected, skull-stripped images in MNI space at ~1–1.5 mm — this reuses trusted preprocessing and, importantly, is a pipeline we can reproduce for Pillar 4 uploads. MONAI on top of PyTorch for transforms/augmentation (it's a PyTorch library, not a replacement).

### 4.3 Experiment tracking

**MLflow, self-hosted locally.** It's free, runs entirely on your workstation (one `mlflow ui` command), stores runs in a local folder or the same SQLite instance, and logs params/metrics/artifacts/model files. W&B has a slicker UI but pushes data to their cloud by default — MLflow fits the "everything stays local" constraint with zero friction. Every training run logs its config, git commit, CV metrics, and the serialized model; promoted models get registered in `models_registry`.

## 5. Pillar 3 — Causal framework

Honest framing first: with an opportunistic (not planned) longitudinal sample, a single scanner but a multi-year window, and covariates measured only at baseline, we will be estimating **event-associated changes under explicit assumptions**, and the framework's job is to make those assumptions visible and testable rather than to promise clean causal identification. That's still publishable and valuable — it just needs to be built with the threats in view: selection into re-scanning, age/period/cohort entanglement, and secular drift.

Proposed design toolkit (Python: statsmodels + linearmodels, with a possible R/brms escape hatch later): the workhorse is a **linear mixed model on longitudinal BAG** — `BAG_corrected ~ time + post_event + exposure×post_event + covariates + (1|subject)` — which is a within-subject difference-in-differences when exposure varies (your questionnaire's geography/exposure items define the dose gradient; send that data over and I'll map what's usable). Around it: an **event-study / interrupted-time-series** version with flexible time trends to check for pre-trends; **placebo events** (fake event dates in quiet periods) as a falsification test; and an explicit **selection-bias analysis** comparing baseline characteristics of re-scanned vs. single-scan subjects, with inverse-probability-of-rescan weights as a sensitivity analysis. The `events` table drives all of it, so re-running every analysis for Oct 7 vs. COVID vs. the judicial-reform period is a config change.

One structural gift in your data: same scanner, same protocol throughout removes the single biggest confounder in longitudinal neuroimaging. The main remaining time-confound is model-related — BAG estimates must come from a model whose training respects temporal leakage concerns (we'll evaluate whether to train on first-scans only, or use cross-fitted predictions so no subject's BAG comes from a model that saw their own data — the harness in Pillar 2 already supports this).

## 6. Pillar 4 — Public BAG report pipeline

Flow: user uploads DICOM zip on a web page → job enters a queue → worker converts (dcm2niix) → defaces (pydeface) → runs the **same CAT12 preprocessing used in training** (CAT12 standalone build, which runs without a MATLAB license, wrapped in a container) → QC checks → inference with the registered production model → HTML report rendered to PDF (WeasyPrint) → emailed → uploaded data deleted (default) or retained with explicit opt-in consent, in which case it's ingested into the DB via the standard Pillar 1 path.

Stack: **FastAPI** for the web app, a lightweight SQLite-backed job queue (Huey or a simple jobs table — no Redis needed at this scale), and the existing workstation GPU for inference. "Processed within X hours, emailed" matches this perfectly — CAT12 takes tens of minutes per scan on CPU, which is fine for an async queue.

Report contents: predicted age and corrected BAG with an uncertainty range; normative percentile curves (BAG and key regional volumes against the SNBB age distribution); hippocampal, ventricular, and total GM/WM/CSF measures; a QC summary; and a clear, prominent statement that this is a research/informational tool, not a medical device, with no diagnostic claims. (When this actually opens to the public, it's worth one conversation with your institution about consent text and liability wording — flagging it now so it's not a surprise later.)

Two things Pillar 4 inherits from earlier pillars: the production model must be a **frozen, versioned artifact** from `models_registry`, and the preprocessing container must be **bit-identical** to what produced the training features — otherwise public users get biased BAGs. This is why the CAT12-based preprocessing choice in Pillar 2 matters.

## 7. Phased build plan

**Phase 0 — Audit (short).** Inventory the workstation: disk layout, data size, GPU model, CAT12/qsirecon output formats, the actual Sheets. Establish backups. Deliverable: environment + data audit notes.

**Phase 1 — Database.** Schema, ingestion of BIDS + CAT12 + qsirecon + tabular, ID harmonization, the data audit report (including longitudinal counts per event). Deliverable: `snbb.sqlite`, Datasette browsing, audit report. *This unblocks everything else.*

*Status (2026-08-19): core done, via the brainlink deviation in §3.2 —
CAT12 tabular features, T1w image paths, and demographics for both cohorts
(SNBB + legacy) are ingested and idempotent; `notebooks/db_review.ipynb`
serves as the interim audit report. Not yet done: qsirecon/dMRI ingestion,
Datasette wiring, and per-event longitudinal counts (needs the `events`
table, deferred to Phase 3 kickoff).*

**Phase 2 — Modeling.** Evaluation harness + bias correction, tabular baselines, port of your stacked model, SFCN fine-tune, MLflow tracking. Deliverable: model leaderboard on identical splits; a promoted v1 production model.

**Phase 3 — Causal.** Exposure mapping from the questionnaire, cohort builders, mixed-model/DiD/event-study analyses with the falsification and selection-bias batteries. Deliverable: analysis notebooks + a results report per event. (Sequenced after Phase 2 because it consumes BAG predictions, but exposure mapping can start as soon as Phase 1's audit lands.)

**Phase 4 — Web app.** Preprocessing container, FastAPI app + queue + worker, report template, email delivery, deletion/consent logic. Deliverable: locally deployed service processing a DICOM upload end to end.

Documentation and tests grow alongside every phase (mkdocs site, CI on GitHub Actions running tests against a small synthetic fixture dataset — never real data).

## 8. What I need from you to start Phase 0/1

The imaging↔questionnaire ID mapping (or whatever partial mapping exists); the questionnaire/demographics Sheets (or exports of them), including the exposure-related items you mentioned; a listing of the BIDS root and the CAT12/qsirecon derivative folders (`tree -L 3` output is enough); and the GPU model (`nvidia-smi`). With those, Phase 1 can begin immediately.

## 9. Open decisions (fine to defer)

Whether dMRI-based and multimodal CNNs are in scope for v1 or only tabular dMRI features; whether the causal analyses eventually get a Bayesian (brms) companion for partial pooling across regions; and domain/hosting for the public app when it outgrows the workstation.
