# Atlas provenance

Referenced from `docs/cat12_container_spec.md` §2/§3. Every file here is
baked into `container/cat12.sif` (`cat12.def` `%files`/`%post`) or read
directly by bagpipe host-side (`bagpipe.app.surface_atlas`) — see that spec
for which.

## Volume: `schaefer2018n400n7tian2020s2.nii` / `.csv`

- **Atlas**: Schaefer 2018 (400-parcel, 7-network) cortical parcellation +
  Tian 2020 (S2, subcortical) — the combined cortical+subcortical atlas the
  production stacked-ensemble model (`config/models/stacked.yaml`) trains
  its regional features on.
- **Source file**: `schaefer2018n400n7tian2020s2__toCAT12.nii`, copied
  (renamed, content unchanged) from
  `/media/storage/yalab-dev/derivatives/MATLAB_atlases/qsirecon/atlas-Schaefer2018N400n7Tian2020S2/`
  on this workstation — originally prepared for the qsirecon dMRI pipeline,
  reused here because it's the same atlas the production model's training
  features were extracted against.
- **Space**: MNI152NLin2009cAsym, affine, **1mm isotropic** (confirmed by
  inspecting the NIfTI header directly, 2026-08-21 — not 1.5mm as an
  earlier draft assumed). CAT12 resamples the ROI atlas onto its own
  internal grid at extraction time regardless of `registration.vox`, so
  the mismatch with CAT12's 1.5mm normalization voxel size is not a bug.
- **`.csv`**: index → ROI name map. Names are the literal column names in
  bagpipe's `features` table (`atlas__region__metric`) — this file is the
  feature schema, not just documentation, and must never be regenerated
  independently of the `.nii` it indexes.
- **License**: Schaefer2018 (MIT, `ThomasYeoLab/CBIG`), Tian2020 (CC BY 4.0,
  `yetianmed/subcortex`). Both permit redistribution; only the `.nii`
  itself is git-ignored here (binary, regenerable from the source path
  above), not for license reasons.

## Surface: `{lh,rh}.schaefer2018_400p_7n.annot`

- **Atlas**: Schaefer 2018, 400-parcel, 7-network, **surface** (fsaverage)
  version — same parcellation as the volume atlas above, for the (currently
  unused by inference, see below) surface pipeline.
- **Source**: `ThomasYeoLab/CBIG`, `stable_projects/brain_parcellation/
  Schaefer2018_LocalGlobal`, fsaverage 164k resolution, downloaded
  2026-08-23. MIT license.
- **Status**: staged into `container/cat12.sif` but **not actually used** —
  CAT12's own-atlas surface batch field
  (`output.sROImenu.satlases.ownatlas`) was confirmed not to work on this
  CAT26 build (docs/cat12_container_spec.md §4b, real single-subject test
  2026-08-23). Regional surface thickness is instead computed post-hoc in
  Python from CAT12's native per-vertex output
  (`bagpipe.app.surface_atlas.custom_surface_regional`), which reads the
  **host-side** copies of these `.annot` files directly — the in-container
  copies are dead weight, kept rather than re-triggering a rebuild to strip
  them.

## Surface: `{lh,rh}.aparc_DK40.freesurfer.annot`

- **Atlas**: Desikan-Killiany 40-region cortical parcellation, the
  standard FreeSurfer/CAT12-bundled atlas — used **only as a validation
  reference**, not in production. `bagpipe.app.surface_atlas`'s
  nearest-vertex resampling method was validated by re-deriving DK40
  regional thickness from CAT12's native output and comparing against
  CAT12's own `catROIs_*.xml` DK40 output for the same subject (max diff
  0.0029mm, mean diff 0.0006mm — `tests/test_surface_atlas.py`,
  2026-08-23). Same CBIG source repo as the Schaefer `.annot` files above
  (FreeSurfer's own `fsaverage/label/`, mirrored there for convenience).

## Surface: `{lh,rh}.sphere.freesurfer.gii`

- **What it is**: the fsaverage reference sphere CAT12's own surface
  pipeline registers every subject's native mesh onto
  (`templates_surfaces/{lh,rh}.sphere.freesurfer.gii`, bundled inside the
  CAT12 standalone package itself) — copied out here so
  `bagpipe.app.surface_atlas` can do the same nearest-vertex matching CAT12
  does internally, in Python, on the host.
- **Source**: extracted directly from the staged
  `container/cat-standalone-Linux.zip` (CAT26.0.rc3/r2874) at build time,
  not downloaded separately — these must stay in lockstep with whichever
  CAT12 release is actually running in `cat12.sif`. If the container is
  rebuilt against a newer CAT12 release, re-extract these two files from
  the new zip before trusting `bagpipe.app.surface_atlas`'s output.
