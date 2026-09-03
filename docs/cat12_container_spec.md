# CAT12 Standalone Container Specification

> `docs/cat12_container_spec.md`, draft v0.1. Companion to `docs/design_inference_pipeline.md` (§ segment stage).
> Goal: a pinned, license-free, reproducible CAT12 segmentation artifact whose outputs are provably interchangeable with the training-time preprocessing of SNBB.

## 1. Why CAT12 standalone

The training features were produced with CAT12 (SPM/MATLAB). For a public inference service we cannot depend on a MATLAB license, so we use the **CAT12 standalone/compiled release**, which bundles compiled SPM+CAT and runs on the free MATLAB Compiler Runtime (MCR). The critical constraint: **the standalone version must match the interactive version used for training feature extraction** (same CAT12 release line and, ideally, identical revision). If SNBB was processed with a different CAT12 revision than the chosen standalone release, the reproducibility test in §6 decides whether the discrepancy is acceptable or whether SNBB training features must be re-extracted with the containerized version — the latter is the cleaner outcome and worth budgeting for.

~~Action item before building: record the exact CAT12 revision and SPM revision used for the existing SNBB CAT12 outputs (`cat_*.xml` → `<software>` block contains both). Fill in §2 pins from that.~~ **Done (2026-08-21):** pulled from a real SNBB `cat_*.xml` — `version_cat=12.9`, `revision_cat=2577`, `version_spm=7771`, `version_matlab=24.1`. Matches the derivatives folder name (`CAT12.9_2577.new`) as a sanity check. §2 filled in.

> **Reconciliation note (2026-08-21):** §2–§4 below originally proposed a
> Docker build (`docker/cat12/`) later converted to Apptainer. That never
> got built — instead `container/cat12.def` (Apptainer-native, per
> DESIGN.md §6 "Why Apptainer, not Docker") was written directly and is
> the real, current artifact. §2–§5 are rewritten below to describe it as
> it exists. **Second reconciliation, same day**: the maintainer placed
> the real CAT12 standalone zip and, inspecting it directly (it's a
> non-secret zip, readable without running anything), several assumptions
> below turned out wrong and are now fixed against the real package
> contents rather than guesses: the real entrypoint is `cat_standalone.sh`
> (not `run_spm*.sh` directly — that script owns `<UNDEFINED>` batch
> substitution and argument parsing; `run_spm25.sh` is a low-level MCR
> launcher it calls internally), a batch field was renamed across CAT12
> releases (`opts.biasacc` → `opts.biasstr`), CAT12.9's default batch has
> `output.BIDS.BIDSno = 1` which restructures output — patched off,
> because real training output (verified against the actual SNBB
> derivatives tree) is **flat**, not nested into `mri/`/`report/`/`label/`
> as originally assumed, and `ownatlas` doesn't need injecting into
> CAT12's own toolbox tree (impossible anyway — its templates are compiled
> into a CTF archive, not plain files at build time) since it's just a
> file path CAT12 reads at runtime.
>
> Also: the maintainer is deliberately moving off `CAT12.9_2577` to a
> newer CAT12 release and will re-extract SNBB training features with the
> new container later — exactly the case DESIGN.md §6's interpretation
> rule anticipates (re-fit training to match the container, not the
> reverse). §2's exact revision pin is therefore provisional until that
> re-extraction happens; what's confirmed and stable is the *mechanism*
> (§3–§5), not the specific CAT12/SPM revision numbers.
>
> **Third reconciliation, same day — a real `apptainer build` + real
> smoke tests, not just reading zip contents.** Two more things the
> second reconciliation got wrong, both confirmed empirically:
> **`--writable-tmpfs` is a hard requirement**, not an implementation
> detail — MCR cannot extract its CTF archive into the image's otherwise
> read-only filesystem without it; every invocation (`segment.py`'s
> subprocess call, the cohort driver, and manual testing) failed
> identically every time without the flag and succeeded every time with
> it. **The "flat, not nested" output claim above was wrong** — real
> classic-mode (`BIDS.BIDSno=0`) output goes into `mri/`/`report/`/
> `label/` subdirs (confirmed: "Segmentations are saved in /data/mri",
> real smoke test, 2026-08-21). The flat claim was comparing against the
> real SNBB training tree, but that tree turns out to have been produced
> via `BIDS.BIDSyes` redirect mode (which *does* flatten), not classic
> mode — the wrong comparison. §4/§5 below and
> `bagpipe.app.pipeline.segment`/`features` are corrected accordingly.
> Also found and fixed: the atlas `.csv` (region names) was staged via
> `%files` but never actually copied to sit next to the `.nii` in
> `/opt/atlas/` — `%post` copied only the `.nii`, producing a real
> (non-fatal, but avoidable) warning: `Cannot find ... csv-file with
> region names!`.

## 2. Version pins (single source of truth)

Pins live in `container/cat12.def`'s `%help` block and are echoed into every job manifest at runtime (no separate `versions.env` — one file is the whole artifact):

```
CAT_VERSION=26.0.rc3          # confirmed from a real run's actual output XML,
REVISION=2874                 # 2026-08-21 — NOT 12.9/2577 as a stale docstring
SPM_VERSION=00.00              # inside cat_standalone_segment.m implied (SPM25
MATLAB_VERSION=23.2            # codebase — SPM12's version numbering doesn't apply)
MCR_VERSION=R2023b (v232)     # confirmed from the standalone zip's own readme.txt +
                               # requiredMCRProducts.txt, 2026-08-21 — NOT R2017b as an
                               # earlier draft of this doc guessed from cat12.def's
                               # then-unverified %help comment
ATLAS_ID=schaefer2018n400n7tian2020s2
```

Genuinely a different, newer release line than SNBB training's CAT12.9/2577/SPM12(7771) — re-extracting SNBB training features through this container is necessary before it can serve as the production inference container, not optional (§6 will confirm the extent of the drift).

Both `cat-standalone-Linux.zip` and `mcr.zip` are login-walled downloads (Neuro Debian / dbm.neuro.uni-jena.de account for CAT12; MathWorks account for MCR) — `cat12.def`'s `%help` documents where to get them and where to stage them (`container/`, git-ignored via `container/*.zip`). The manifest records the built image's immutable digest, never a mutable tag.

## 3. Image contents

```
container/
├── cat12.def                      # Apptainer recipe — the whole build (%files/%post/%runscript)
├── cat-standalone-Linux.zip        # staged locally, git-ignored, login-walled download
│                                    # (may itself wrap a nested zip — %post handles it)
├── mcr.zip                         # staged locally, git-ignored, login-walled download —
│                                    # either an already-installed MCR runtime tree, or a
│                                    # raw MathWorks installer package; %post handles both
└── atlas/
    ├── schaefer2018n400n7tian2020s2.nii   # git-ignored (*.nii), MNI152NLin2009cAsym affine, 1mm iso
    ├── schaefer2018n400n7tian2020s2.csv   # committed — index → ROI name map (exact names = feature schema)
    └── PROVENANCE.md                       # TODO: where the atlas came from, space, resampling method
```

No separate batch `.m` file is committed — see §4. `%post` steps (in order): extract the (possibly double-nested) standalone zip; locate `cat_standalone.sh` and `run_spm*.sh` by `find` (layout varies by release, fails loudly rather than guessing a hardcoded path); extract the MCR zip and either use its already-installed `v###/` runtime dir as-is, or run its installer silently if it's a raw MathWorks package; copy the real atlas to a fixed image path (`/opt/atlas/`, independent of CAT12's own install tree); locate CAT12's own bundled `cat_standalone_segment.m` and patch it (§4); write all resolved paths to `/opt/cat12/paths.env`, sourced by `%runscript`.

## 4. Batch template

CAT12's standalone package ships its own `cat_standalone_segment.m` with many undocumented-but-load-bearing defaults. Rather than reconstruct the whole `matlabbatch` from scratch (real risk of silently diverging from stock behavior in a field nobody thought to pin), `cat12.def`'s `%post` copies CAT12's own bundled template and `sed`-patches only the fields confirmed to matter, matched by field-name pattern (not a fixed value assumption) because names drift across releases:

| field | value | source |
|---|---|---|
| `opts.affreg` | `'mni'` | confirmed, real SNBB XML; already the shipped default in the 2026-08-21 zip too |
| `opts.biasacc` (older CAT12) / `opts.biasstr` (this build) | `0.5` | confirmed, real SNBB XML — same value, renamed field; sed pattern matches either name |
| `extopts.segmentation.APP` | `1070` | confirmed, real SNBB XML; already the shipped default too |
| `extopts.registration.vox` | `1.5` | confirmed, real SNBB XML; already the shipped default too |
| `output.surface` | `1` (unpatched, shipped default) | **Changed 2026-08-24**: no longer forced to `0` for inference. Production model still only uses `vol_gm`/`vol_wm`/`vol_csf`, but surface is now always run so `stools.surfextract` (job 2, see §4c) can compute gyrification/sulcal depth/fractal dimension/area for every subject through one shared template, at the cost of real per-request latency for inference too (~2-3x a volume-only run, §7) — a deliberate tradeoff, not an oversight (see `cat12.def`'s `%help`) |
| `output.BIDS.BIDSno` | `0` | **must patch**: this build's shipped default is `1` (BIDS-style redirect, which the cohort driver *does* want — see `config/cat12_cohort.yaml`). `0` (classic mode) is what inference wants: output in `mri/`/`report/`/`label/` subdirs next to the input, confirmed via a real smoke test 2026-08-21 |
| `output.ROImenu.atlases.neuromorphometrics` | `0` | computed for SNBB but never ingested into bagpipe's `features` table — dead weight. Shipped default is `1`, must patch |
| `output.ROImenu.atlases.cobra` | `0` | same reasoning — an extra atlas not in the feature schema, shipped default `1`, must patch |
| `output.ROImenu.atlases.ownatlas` | `/opt/atlas/schaefer2018n400n7tian2020s2.nii` | the atlas the production model actually trains on (verified against `outputs/datasets/regional.parquet`, 2026-08-21) — **not** `neuromorphometrics`/`custom_atlas_v2` as an earlier draft of this doc assumed, and it's a fixed image path outside CAT12's own install tree (see §3), not somewhere inside `templates_MNI152NLin2009cAsym/` — that dir isn't a plain-file location at build time (CTF-compiled) |
| `output.GM.mod` / `output.WM.mod` | `1` | needed for the modulated volume outputs `ingest_cat12`/`cat12_parse` read; already the shipped default too |

`%post` fails loudly (`grep` check on the patched `ownatlas` line) if any sed pattern didn't apply — a silently-unpatched field is worse than a build failure. Any change to this patch list needs re-verifying against a real SNBB `cat_*.xml` and triggers §6.

### 4d. Additional surface parameters — gyrification/sulcal depth/fractal dimension/area (2026-08-24)

`output.surf_measures = 1`, previously listed here as a batch-line override in `config/cat12_cohort.yaml`, was a **real bug**: no such field exists anywhere in `cat_standalone_segment.m`'s real schema (checked the bundled `.m` directly). Silently ignored — same failure class as the `sROImenu.satlases.ownatlas` bug below. Confirmed on real cohort output: `surf/` only ever had `thickness`/`pbt`/mesh files despite the line being set, across the whole 2026-08-23 cohort run.

Gyrification (GI), sulcal depth (SD), and fractal dimension (FD) are computed by a genuinely separate CAT12 module, `spm.tools.cat.stools.surfextract` ("Extract Additional Surface Parameters" in the GUI) — not shipped as a standalone-package `.m` template (only `segment`/`resample`/`deface`/etc. are) and not exposed by any field on `estwrite`. Per-vertex surface area comes from the same module.

Wired into `container/cat12.def`'s `%post` as **job 2** appended to `batch_template.m`, chained to job 1's central-surface output by directly constructing the deterministic output path (`surf/{lh,rh}.central.<input-stem>.gii`) rather than `cfg_dep` — `stools.surfextract`'s real `cfg_dep` substruct lives inside the compiled `spm25.ctf` archive with no plaintext source to read it from, so a hand-written `cfg_dep` would be equally unverifiable guesswork of a different, harder-to-debug kind. Field values (`GI=1`, `FD=1`, `SD=1`, `tGMV=0`, `nproc=0`, `lazy=0`) are a best-effort read of CAT12's documented batch GUI fields.

**Not yet verified against a real container run** (no `cat12.sif` built on the authoring machine as of 2026-08-24) — both the `surfextract` field names and the resulting `surf/{lh,rh}.{gyrification,depth,fractaldimension,area}.*` filenames (assumed by `bagpipe.app.surface_atlas.SURFACE_METRICS` / `bagpipe.app.cat12_parse.SURFACE_METRIC_TAGS`) are unconfirmed guesses. Before trusting any of this: rebuild `cat12.sif`, run `bag preprocess cat12-cohort --config config/cat12_cohort.yaml` with `limit: 2`, and check for those files under `surf/` — if the field names are wrong, job 2 will either error (batch validation failure) or silently no-op depending on where CAT12's own arg validation catches it; either way, don't extend §6's reproducibility suite to these metrics until a real run confirms the files exist with plausible values.

### 4b. Surface ROI, custom atlas (2026-08-23 — CAT12 batch field abandoned, done in Python instead)

CAT12 ships Schaefer surface atlases natively, but only 17-network (`cat_defaults.m`'s `extopts.satlas`) — the production model's 7-network parcellation has no native surface counterpart, same gap the volume `ownatlas` above works around. First attempt mirrored the volume fix: `container/atlas/{lh,rh}.schaefer2018_400p_7n.annot` (CBIG-published fsaverage 164k, `ThomasYeoLab/CBIG` `Schaefer2018_LocalGlobal`) baked into the image, wired via `output.sROImenu.satlases.ownatlas` in `config/cat12_cohort.yaml`'s `extra_batch_lines`.

**Real single-subject test (2026-08-23) showed this field has no effect**: `catROIs_*.xml` only ever contained `aparc_DK40`/`aparc_a2009s` (CAT12's own defaults). The smoking gun: the volume `ownatlas` self-registers into `cat_*.xml`'s atlas registry (`/opt/atlas/schaefer2018n400n7tian2020s2.nii` shows up there, and `ROI estimation of 'schaefer2018n400n7tian2020s2' atlas` runs) — the surface `<satlas>` registry block never gained our entry at all. Root cause unconfirmed: CAT26's surface-ROI code ships compiled/p-coded inside `spm25.ctf` (confirmed no plaintext strings survive compilation, even for field names), so the actual reason the job-level field is ignored can't be inspected. Removed from `config/cat12_cohort.yaml` — a dead, silently-ignored batch line is worse than no line.

**Fixed instead in Python, post-hoc, from CAT12's own native output** — `bagpipe.app.surface_atlas.custom_surface_regional()`. CAT12 already produces, for every surface-processed subject regardless of atlas choice: native per-vertex thickness (`surf/{lh,rh}.thickness.<name>`, FreeSurfer curv format) and the native mesh registered onto CAT12's own fsaverage-space reference sphere (`surf/{lh,rh}.sphere.reg.<name>.gii`). Mirrors what CAT12's own `cat_surf_surf2roi` does for non-pre-resampled data: nearest-neighbor-match each atlas vertex (on CAT12's bundled reference sphere, `templates_surfaces/{lh,rh}.sphere.freesurfer.gii`, copied into `container/atlas/`) to the closest native vertex via both meshes' unit-sphere coordinates, then average per atlas region.

**Validated against CAT12's own ground truth**: ran the same method with CAT12's *own* bundled DK40 `.annot` (in place of the custom Schaefer one) and compared to `catROIs_*.xml`'s real DK40 output for the same subject — max diff 0.0029mm, mean diff 0.0006mm, on a ~2.5mm mean thickness (68 regions compared). Then applied to the real Schaefer2018N400n7 surface atlas: 400 regions, plausible thickness distribution (mean 2.42mm, matching DK40's 2.52mm mean). See `tests/test_surface_atlas.py`.

`container/atlas/{lh,rh}.schaefer2018_400p_7n.annot` staged into the image (`cat12.def` `%files`/`%post`) are now dead weight — harmless, not worth another rebuild to strip, but not read by anything; the real copies used at ingest time are the repo-tracked `container/atlas/` files read directly by bagpipe (host-side), not anything inside the container.

## 5. Invocation contract (segment stage ↔ container)

Real syntax (matches `cat12.def`'s `%runscript`, which calls `cat_standalone.sh` — the real entrypoint, not `run_spm*.sh` directly):

```bash
apptainer run \
  --writable-tmpfs \
  --env SHELL=/bin/bash \
  --bind {workspace}/cat12:/data \
  cat12.sif \
  /data/T1w.nii.gz
```

`--writable-tmpfs` is a **hard requirement**, confirmed via a real smoke test 2026-08-21 — without it MCR cannot extract its CTF archive (`spm25.ctf`) into the image's otherwise read-only filesystem and fails immediately with `Failed to create a directory required to extract the CTF file`, every time. (Superseded detail: `cat12.def` now pre-extracts the CTF at build time into an in-image path — see §4a below — so this requirement is now about CAT12's own scratch/report files, not CTF extraction.)

`--env SHELL=/bin/bash` is also a **hard requirement**, root-caused 2026-08-23: Apptainer leaks the host's `$SHELL` into the container by default, and MATLAB's compiled runtime uses `$SHELL` to spawn every external `system()` call — including every `CAT_*` surface/thickness binary. The maintainer's host shell is zsh, which doesn't exist in this Ubuntu 22.04 container, so every such call failed with `execve(...zsh...) = -1 ENOENT` (confirmed via `strace -f -e trace=execve` on a real run) — CAT12 catches the failure and reports its generic, misleading "(1) File permissions are not correct (2) CAT binaries are not compatible (3) Antivirus/Gatekeeper blocking" message, which is what misdirected the earlier 2026-08-22 investigation. Segmentation itself doesn't hit this (no external `system()` calls), only surface/thickness (§4a) — pin the env var on every invocation regardless.

### 4a. Surface/thickness CTF pre-extraction

`cat_standalone_segment.m`'s surface/thickness binaries (`CAT_VolThicknessPbt`, `CAT_VolMarchingCubes`, etc.) aren't plain files in the standalone package — they're bundled inside `spm25.ctf` and self-extract into an `spm25_mcr/` directory created **next to the standalone binary itself** (not under `$MCR_CACHE_ROOT`, contrary to the initial 2026-08-22 assumption). `cat12.def`'s `%post` now triggers this extraction once at build time (any invocation of `cat_standalone.sh` extracts the CTF before it even parses batch args, so an intentionally-incomplete batch is fine — only the extraction side effect matters), then `chmod -R a+rX` + explicit `+x` on every `CAT_*`/`*.exe` file found inside it. This bakes a correctly-permissioned extraction into the read-only image layer, so no CTF extraction happens at runtime at all. Verified end-to-end: a real subject with `output.surface`/`surf_measures`/`ct.native` all `= 1` (plus `--env SHELL=/bin/bash`, above) produced full `surf/lh.*.gii`/`surf/rh.*.gii` + thickness maps, no errors, SIQR 88.25% (B+), ~53 min total.

Internally, `%runscript` runs `cat_standalone.sh -m $MCR_ROOT -b $BATCH_TEMPLATE -pr 1 "$1"` — batch+input as documented positional args (confirmed by reading `cat_standalone.sh` directly, not inferred from a tutorial), `-pr 1` skips PDF/surface report rendering (no OpenGL in a headless container). CAT12 has no output-dir arg; classic mode (`BIDS.BIDSno=0`, §4) writes into `mri/`/`report/`/`label/` subdirs next to the input, confirmed via a real smoke test 2026-08-21 — an earlier draft of this doc claimed flat output, which was wrong (see the "Third reconciliation" note above).

Unlike Docker, Apptainer has no `--memory`/`--cpus`/`--network=none`/`--read-only` equivalents without extra host-side cgroup setup — accepted for v1 given the single-user, no-root-daemon, single-workstation deployment DESIGN.md's §6 "Why Apptainer" already argues for; revisit only if this ever runs multi-tenant.

Python `segment` stage responsibilities (no `entrypoint.sh` — `%runscript` is the entire in-container logic, patched at build time per §4):

1. Copy the anonymized T1w into `{workspace}/cat12/T1w.nii.gz` — the bind target must be read-write since CAT12 writes there.
2. Invoke `apptainer run --writable-tmpfs --env SHELL=/bin/bash` per above; enforce the wall-clock timeout (90 min default) in Python by killing the subprocess (no container-runtime-level timeout available).
3. **Exit code cannot be trusted** — `cat_standalone.sh` unconditionally `exit 0`s in standalone mode regardless of whether the underlying MCR executable actually succeeded (confirmed by reading it directly). Verify expected outputs exist instead: `{workspace}/cat12/report/cat_T1w.xml`, `{workspace}/cat12/label/catROI_T1w.xml`; raise `CAT12_FAILED` (with the tail of CAT12's own stdout attached) if either is missing.
4. Provenance is the job manifest's `environment.cat12_image` digest (per `design_inference_pipeline.md`) — no separate `provenance/` dir needed, that would just duplicate it.

## 6. Reproducibility acceptance test (gates every image change)

Purpose: prove the containerized standalone reproduces training-time features. Runs on the local workstation against SNBB data (never in CI, never leaves the machine).

**Protocol.**

1. Sample n = 12 SNBB subjects stratified by age tertile and sex, plus 2 subjects flagged with the lowest IQR in the cohort (stress cases).
2. Run raw T1w through the container; extract features with the production `extract_features` code.
3. Compare against the stored training features for the same sessions.

**Acceptance criteria** (all must hold; record results in `docs/repro_reports/{image_digest}.md`):

- Per-feature concordance across subjects: Pearson r ≥ 0.999 for volumetric ROI features; ≥ 0.995 for surface features if present.
- Per-subject max relative deviation: |Δ|/σ_feature ≤ 0.05 for ≥ 99% of feature–subject pairs (σ_feature = cohort SD of that feature).
- Downstream: corrected BAG deviation |Δ_BAG| ≤ 0.3 years for every test subject (well under model MAE; tighten if the observed distribution allows).
- IQR from container within ±2 points of original run's IQR for each subject.

**Interpretation rule.** If criteria fail and the cause is a genuine CAT12 revision difference vs. the original SNBB processing (not a bug), the resolution is to re-extract SNBB training features with the container and retrain/re-fit downstream, not to loosen tolerances. Training–inference parity is the invariant; which side moves is a cost decision, but they must match.

**Determinism note.** CAT12/SPM segmentation is deterministic for a fixed input, binary, and parameter set on the same hardware; tiny cross-hardware numeric differences (BLAS, CPU) are possible. Since both training re-extraction (if needed) and serving run on the same workstation initially, this is moot for v1 — but rerun §6 if the serving host ever changes.

## 7. Runtime and capacity expectations

Volume-only pipeline on 4 modern cores: ~15–30 min/subject; with surface: ~40–80 min. Peak RAM typically 6–12 GB, with pathological inputs higher — hence the 24 GB cap. On the single workstation with `N_CONCURRENT=1`, worst-case daily throughput ≈ 20–50 jobs; fine for launch, and the queue absorbs bursts. Revisit only if demand shows up.

## 8. Build & release procedure

1. Edit `container/cat12.def` (batch `sed` patches, atlas, pins) → bump the version comment.
2. Stage `container/cat-standalone-Linux.zip` and `container/mcr.zip` locally (login-walled, see `cat12.def` `%help`).
3. `apptainer build cat12.sif container/cat12.def`; record the `.sif`'s sha256 as its digest (Apptainer images aren't content-addressed like Docker registries — hash the file yourself).
4. Run §6 suite; commit the repro report referencing the digest.
5. Update `paths.cat12_apptainer_image` in `config/local.yaml` and the digest recorded in the deployed job manifest template. Old `.sif` files are never deleted while any manifest references them.

## 9. Open items

- [x] Extract CAT12/SPM revision + full parameter set from an SNBB `cat_*.xml` and finalize §2/§4 pins. Done 2026-08-21 (see §1/§2).
- [x] Confirm feature schema needs: volume-only vs. surface. Done 2026-08-21 — production model (`config/models/stacked.yaml`) is `vol_gm`/`vol_wm`/`vol_csf` only. **Superseded 2026-08-24**: `output.surface = 0` for inference was reverted — surface + `surfextract` (§4d) now run for every caller so gyrification/sulcal-depth/fractal-dimension/area get ingested from CAT12's own native output, at the cost of inference latency (see §4's table). Not yet verified against a real run.
- [x] Verify atlas space. Done 2026-08-21 — real atlas file (`schaefer2018n400n7tian2020s2__toCAT12.nii`, sourced from `/media/storage/yalab-dev/derivatives/MATLAB_atlases/qsirecon/atlas-Schaefer2018N400n7Tian2020S2/`) is MNI152NLin2009cAsym affine, **1mm iso** (not 1.5mm as originally assumed — doesn't block anything, CAT12 resamples the ROI atlas at extraction regardless of the `registration.vox` normalization resolution, but note it correctly in `PROVENANCE.md`).
- [x] Decide neuromorphometrics inclusion. Done 2026-08-21 — dropped (§4), unused by the production model.
- [x] **Correction, not just confirmation**: the atlas this doc originally specified (`custom_atlas_v2`, a placeholder name) was wrong — the model actually trains on `Schaefer2018N400n7Tian2020S2`. Fixed throughout this doc 2026-08-21, real `.nii`/`.csv` copied into `container/atlas/`.
- [x] Reconciled this whole doc against the real, already-existing `container/cat12.def` (Apptainer-native, not the Docker plan §2–§5 originally proposed) — found and fixed two real bugs in it: `%runscript` misused `-a1`/`-a2` (real CAT12 standalone syntax is positional), and it had no atlas-install/batch-patch step at all. Done 2026-08-21.
- [x] Stage the login-walled `cat-standalone-Linux.zip` download. Done 2026-08-21 — maintainer placed it in `container/`. Inspecting it directly (readable without running anything) surfaced and fixed several more real bugs: real entrypoint is `cat_standalone.sh` not `run_spm*.sh`; `opts.biasacc` renamed to `opts.biasstr` in this build; `output.BIDS.BIDSno` defaults to `1` and must be patched to `0` to match real (flat, non-BIDS) SNBB training output; `ownatlas` must point to a fixed image path, not somewhere inside CAT12's own install tree (impossible anyway — its templates are CTF-compiled, not plain files at build time). MCR confirmed **R2023b/v232** from the zip's own `readme.txt`/`requiredMCRProducts.txt` — the earlier `R2017b` correction (made from `cat12.def`'s own then-unverified `%help` comment) was also wrong. All fixed in `cat12.def` and this doc, 2026-08-21. Also: a `cat_standalone_segment.m` header comment inside this zip read "Version 2577 (CAT12.9) 2024-05-03", which was wrongly taken as this build's real version — that comment is stale docstring text in a script that ships alongside a separately-compiled binary, not the binary's actual version. **Corrected same day, from a real run's actual output XML** (not a comment): the compiled binary is genuinely **`version_cat=26.0.rc3`, `revision_cat=2874`, `version_spm=00.00` (SPM25 codebase — SPM12's version numbering doesn't apply), `version_matlab=23.2`** — a real, different release line from SNBB training's CAT12.9/2577/SPM12(7771), confirming re-extraction of SNBB training features through this container will be necessary before it can serve as the production inference container, exactly as the maintainer already planned.
- [x] MCR (`container/mcr.zip`) — staged and built, 2026-08-21 (see below).
- [x] Write `container/atlas/PROVENANCE.md`. Done 2026-08-24 — provenance/source/space for every file in `container/atlas/`, including which are actually read at runtime vs dead weight (§4b).
- [x] First full build + real smoke test. Done 2026-08-21 — `apptainer build container/cat12.sif container/cat12.def` succeeded, and a real single-subject run through it completed segmentation in 12m26s (SIQR 87.22%, B+). Found and fixed three more real bugs along the way, none catchable without an actual run: `--writable-tmpfs` is required (MCR can't extract its CTF archive otherwise); classic-mode output goes into `mri/`/`report/`/`label/` subdirs, not flat as previously assumed (see "Third reconciliation" note above); the atlas `.csv` wasn't actually being copied next to the `.nii` in `%post` (only the `.nii` was). All fixed in `cat12.def`, `bagpipe.app.pipeline.segment`/`features`, and `bagpipe.preprocess.cat12_cohort`. Also confirmed the real CAT version from the run's own output XML: `26.0.rc3` r`2874` (§2), correcting an earlier wrong reading of a stale docstring.
- [ ] §6 reproducibility suite (12 stratified + 2 stress subjects, comparing against stored training features). Tooling built 2026-08-24 (`bagpipe.preprocess.repro_test`, `bag preprocess repro-test --config config/repro_test.yaml`) — runs the real `run_manifest` stage graph per subject and diffs against stored `features`/`predictions` rows, writes `docs/repro_reports/{digest}.md`. Subject-selection query verified against the real DB (stratified 12 + 2 lowest-IQR stress cases pulled correctly). **Not yet actually run**: `paths.bids_root` (`//132.66.46.62/Bids`) was unreachable (`Host is down`, confirmed via `ping`) when this was built — the raw T1w files the test needs to feed into the container aren't accessible from this machine right now. Run `bag preprocess repro-test` once that share is back.
