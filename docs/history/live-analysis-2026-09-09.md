# SceneLight live scene analysis — 9 September 2026

> Historical development record. Versions, measurements and remaining work below
> describe that revision, not the current release. Start with the
> [current documentation](../README.md) and [compatibility notes](../BETA_VALIDATION.md).

The shared scene analyzer now runs in Preview and the reusable Ren’Py runtime.
Lighting is derived from the background being displayed, without preparing a
whole movie. Sprite reconstruction and the established lighting response remain
the reference model.

## Implemented behavior

- The graphics device performs resizing, linear-light preparation, robust
  luminance statistics, physical source classification, creative hue families,
  exposure metering, directional probes, transport synthesis, emitter fields,
  and environment wrap. No per-frame image readback or CUDA work is required.
- Optional compute shaders handle connected components, overlapping component
  rings, histograms, compaction, and sorting. The raster implementation retains
  the same model on contexts without compute shaders. Float rendering and
  accumulation are validated before activation.
- Analysis scratch targets and identical shader programs are shared. A static
  background retains its fields; moving a character or changing a calibration
  control only redraws the lighting shader. Each retained Ren’Py field set is
  approximately 185 KiB, independent of the larger shared analysis workspace.
- Ren’Py observes the existing background render, including image transforms
  and placement. A showing binding survives current-store copies. Frozen
  sprites retain their exact completed field set. GPU handles stay outside saves
  and rollback; restored bindings rebuild fields at the next interaction.
- Preview streams video with bounded lookahead, decode-completion notifications,
  and presentation deadlines. Opening video does not hash or decode its full
  payload. Live export renders every requested source frame; playback callbacks
  are paused during export, and playback resumes from a coherent first frame.
- New installs default to `scene_analysis: live`, capturing one background
  fallback and preparing sprite forms. `scene_analysis: cached` retains the
  complete offline timeline path. Shared analysis modules ship as owned `.txt`
  resources so Ren’Py’s asset loader and archives can include them.

## Visual validation

The GPU tests compare the actual generated textures against the CPU reference,
including dark and near-black frames, uniform and diffuse illumination, multiple
colored sources, textured source rings, portrait aspect ratios, and a forced
compute failure. Transport, irradiance, emitter, and Preview-wrap bytes agree
within one 8-bit level; packed grain/sharpness agree within 0.000003. The same
compute/raster fixture outputs are identical.

Native still captures exercise physical, cinematic, and separate-light modes
in classroom, red-room, and pool scenes. Nine Ren’Py 8 comparisons against the
previous installation differ by at most 5/255 in an individual channel, with
whole-image mean differences no greater than 0.21/255. These are not bit-identical:
the old analysis used screenshot-resampled source images, while live analysis
uses the rendered background texture. The source preparation difference is
recorded separately from the numerical CPU/GPU comparison.

Real Ren’Py 7.8.7 and 8.5.2 tests verify live movie/dynamic backgrounds, saves,
loads, rollback, and fixed transition snapshots. The transition midpoint retains
the existing renderer’s baseline residual relative to an ideal arithmetic blend;
it is not described as a pixel-perfect arithmetic dissolve.

## Performance and evidence

Performance runs use an RTX 4090 on Windows. Ren’Py 7.8.7 processed 59.93 live
updates/s and Ren’Py 8.5.2 processed 60.00 updates/s on the 60-fps test movie.
The updated installed Preview processed 60.23 presentations/s, with 0.768 seconds
of opening/preparation time and three missed source frames during the measured
five-second window. No temporal-analysis worker or CUDA background analysis ran.
These are observed application events, not a guarantee for every device or
measured panel scanout. The shared workspace uses approximately 290 MiB for the
audited 1280×720 scene, including its buffers; engine textures and driver storage
are additional.

Validation passed in a clean environment using the pinned project dependencies,
with no CUDA package installed: 392 tests, Ruff lint, source/test formatting,
Bandit, dependency consistency, dependency vulnerability audit, and wheel/sdist
build. Full-repository formatting still identifies four pre-existing audit tools:
`audit_preview_runtime_parity.py`, `audit_temporal_continuity.py`,
`audit_transport_layout.py`, and `build_visual_review.py`. They were not changed
by this update.

The reusable source, matching extracted Preview, and Backrooms Copy (2) have
been refreshed. The game’s 636 owned files verify clean. Only the bootstrap and
runtime manifest changed, plus the two shared analysis resources; existing maps,
story files, and art were preserved. Both installed copies identify the same
source-content fingerprint. Backups and the complete local validation record
accompany the update. Restart running instances to load the new engine.

Reproducible checks:

- `tests/test_live_gpu.py`: numerical parity and real GL state restoration.
- `tests/test_live_gpu_device.py`: texture-name reuse and format allocation.
- `tests/test_live_runtime_host.py`: showing copies, retained frames, device
  recreation, and failure handling.
- `tests/test_live_install.py`: owned shared modules and no movie-wide preparation.
- `tools/audit_preview_playback.py --live --cpu`: actual Preview delivery.
- `tools/smoke_video_export.py --live`: complete frame export, with cached scene
  analysis forbidden by the harness.
- `tools/fixtures/live_runtime_audit.rpy`, `live_lifecycle_audit.rpy`,
  `live_field_audit.rpy`, and `transition_reference.rpy`: disposable native-engine
  checks. These fixtures are not installed in user games.

## Compatibility limits

A dedicated graphics card and CUDA are not required. Live analysis uses OpenGL
3.3 or OpenGL ES 3.0 with float render targets and accumulation. Compute shaders
are optional. A failed capability check preserves cached lighting; in a new live
install this is the first-frame fallback. Use `scene_analysis: cached` when a
renderer needs complete precomputed animation lighting. Modern Ren’Py itself
requires working graphics acceleration; see its [graphics requirements](https://www.renpy.org/doc/html/display_problems.html).

The raster fallback is verified on the available graphics device. Physical
integrated-GPU, AMD, macOS, Linux, and mobile performance has not been measured.
The context-recreation unit test and real save/load tests do not constitute a
physical driver-reset or suspend/resume test.
