# Phase 0 — Environment & Data Audit

Status: in progress. No real subject IDs, paths revealing personal directory
names, or data content go in this file — structure and counts only.

## Environment

- OS: Ubuntu 24.04.4 LTS (noble)
- CPU: 32 cores
- RAM: 125 GiB
- Python: 3.11.8, package manager: `uv` 0.9.28
- GPU: NVIDIA GeForce RTX 3070 Ti (GA104) present on PCI bus, **driver not
  loaded** — `nvidia-smi` fails ("couldn't communicate with the NVIDIA
  driver"), no `nvidia` kernel module resident, no CUDA toolkit (`nvcc`) on
  PATH. **Action needed before Pillar 2 (SFCN training): install/repair the
  NVIDIA driver + CUDA toolkit matching the PyTorch build.**
- Local disk: `/` (nvme0n1p2) 457G, 68G free (85% used) — tight. **Resolved:**
  repo moved to `/media/storage/bagpipe` (local ext4, `/dev/sdb1`, 12T,
  6.2T free). `config/local.yaml` db_path/mlflow_dir/outputs all point there.

## Storage / mounts relevant to this project

Several SMB shares mounted read/write, sizes only (no listing depth beyond
top-level dirs / subject folder naming pattern):

| Mount | Size | Used | Role (proposed) |
|---|---|---|---|
| `/mnt/62/Bids` | 100T | 8.2T | **BIDS root** — top-level has standard BIDS files (`dataset_description.json`, `participants.tsv`, etc.) + `sub-S######` folders |
| `/mnt/62/Processed_Data/derivatives/qsiprep` | (shared with Processed_Data, 301T/44%) | — | qsiprep derivatives, `sub-S######` folders |
| `/mnt/62/Processed_Data/derivatives/qsirecon` | — | — | qsirecon derivatives, `sub-S######` folders, `atlases/` + `derivatives/tabular` subdirs |
| `/mnt/62/Processed_Data/derivatives/tabular_cat12` | — | — | CAT12 ROI/tabular outputs — **candidate for `paths.cat12_dir`**. Contains both ID schemes: `sub-S######` (SNBB, matches BIDS) and `sub-<12-digit timestamp, YYYYMMDDHHMM>` (legacy pre-SNBB data never assigned an S#### ID — confirmed by user, not a mapping problem). Ingestion should treat timestamp-ID subjects as a separate cohort/dataset row in `datasets`/`subject_dataset`, not attempt to join them into SNBB's `id_map` |
| `/mnt/62/Processed_Data/derivatives/tabular` | — | — | qsirecon-side tabular exports, `sub-S######` (matches BIDS ID scheme), plus `group/` and per-atlas `*_failures.csv` (Brainnetome246Ext, Gordon333Ext, HCPex, Schaefer2018N400n7) — QC/failure logs per atlas, useful for the audit's QC-status column |
| `/mnt/62/Processed_Data/derivatives/responses` | — | — | **not** questionnaire data — 3 group-level qsirecon dMRI response-function files (`median_response_{csf,gm,wm}_balanced_1426.txt`), standard qsirecon/MRtrix output. Questionnaire/demographics data is still Sheets/Excel, not yet located on this machine — ask user |
| `/mnt/snbb` (SNBB_DB share) | 82T | 35T | raw MRI data by acquisition batch (`snbb_*_mri_data` folders) — likely upstream of the BIDS conversion, not consumed directly by bagpipe |

Subject ID pattern observed in BIDS: `sub-S######` (6-digit numeric suffix).
This is the **imaging ID** side of `id_map` — need the questionnaire ID
scheme and the mapping file/table to fill `id_map`.

## Open items

- [ ] GPU driver/CUDA install (blocks Pillar 2, not Pillar 1)
- [x] `tabular_cat12/` timestamp-ID folders resolved — legacy pre-SNBB
      cohort, no S#### ID exists, not a join problem. Modeled as parallel
      `legacy_participant`/`legacy_imaging_path` tables (see
      `docs/DESIGN.md` §3.2 deviation note), not a `datasets` row — no
      `datasets` table exists yet.
- [x] Confirmed `tabular_cat12` (TSV, self-describing BIDS-entity filenames)
      and CAT12 image (`.nii`) formats via sample inspection; parsers live in
      `src/bagpipe/db/ingest_cat12.py` and `ingest_t1w_paths.py`.
- [x] Imaging ID ↔ questionnaire ID mapping — handled by brainlink's identity
      resolution (`participant`/`session` tables), not a bagpipe `id_map`
      table. Legacy cohort matched via `ScanIdentifier` (underscores
      stripped) in a separate CSV — see DESIGN.md §3.2.
- [x] Demographics/questionnaire ingested for both cohorts (brainlink Sheets
      ingest for SNBB; local CSV for the legacy cohort, PII columns dropped).
- [x] `config/local.yaml` filled in, including `db_path` (points at
      brainlink's DB, not a bagpipe-native `snbb.sqlite`), `cat12_images_dir`,
      `datasets_dir`, `legacy_demographics_csv`.
- [ ] Backup status of `/mnt/62/Bids` and `/mnt/62/Processed_Data` — not yet
      verified (CLAUDE.md flags this as a hard constraint before large ops)

## Next steps

1. Resolve GPU driver before Phase 2 modeling work starts.
2. Verify backup status of the SMB derivative shares.
3. qsirecon/dMRI ingestion (deferred — T1w-only for the current phase).
4. `events` table + per-event longitudinal counts, ahead of Phase 3.
