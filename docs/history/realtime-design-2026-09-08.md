# SceneLight real-time redesign

> Historical development record. Versions, measurements and remaining work below
> describe that revision, not the current release. Start with the
> [current documentation](../README.md) and [compatibility notes](../BETA_VALIDATION.md).

Decision record, September 8, 2026. This is an investigated implementation plan,
not a completed renderer replacement or a claim of visual approval.

Implementation status, September 9: the shared scene analyzer now runs in Preview
and the Ren'Py runtime. The observations below describe the original system that
motivated the rewrite. See
[the implementation and validation record](../REALTIME_IMPLEMENTATION_STATUS.md).

## Decision

Build a shared GPU scene-analysis pipeline driven by the background that is
actually being rendered. Retain sprite surface reconstruction and the established
lighting response as the quality reference. Make full-video lighting preparation
an optional reference/export facility, rather than a prerequisite for live play.

The existing project has GPU **application** of previously calculated lighting.
It does not have per-frame GPU **analysis** of the changing background. Increasing
the redraw rate cannot overcome the temporal information missing from its cache.

The first implementation milestone should be a measured live rendering prototype
in both the Preview host and the actual Ren'Py 7.8.7 fixture. The difficult parts
are background composition, GPU source classification, and quality equivalence.
Those must be proved before replacing the production path.

## Evidence from the actual implementation

The inspected source runtime and Copy (2)'s installed `bootstrap.rpy` are byte
identical, SHA-256:

`0a4fa4462a910a79530eb5bbad40f02f7e9c3f50382b7417b84955868a53797a`

### Game

Copy (2)'s manifest has 263 scene records. Its yellow and pool movie timelines
contain 41 samples each, normally 125 ms apart. The VHS timeline has 46 samples,
normally 133–134 ms apart. `capture.py` explicitly targets eight samples per
second for game movies. `_scenelight_timed_scene` chooses the last sample at or
before the decoder position and holds that complete record. It does not blend
neighboring movie fields.

An instrumented, isolated copy of that game ran on Ren'Py 7.8.7, GL2, RTX 4090.
No screenshot readback was performed during measurement. An observer requested
continuous redraw; these are render-scheduling timestamps, not measured display
presentation or GPU execution times. Statistics exclude the first 0.5 seconds
and last 0.1 seconds of each phase.

| Phase | Scheduled updates/s | Frame interval p99 | Sprite CPU render p99 | Lighting hold median |
|---|---:|---:|---:|---:|
| Yellow movie, lighting disabled | 144.00 | 7.089 ms | 0.335 ms | 125.025 ms |
| Yellow movie, lighting enabled | 144.00 | 7.163 ms | 0.486 ms | 131.883 ms |
| VHS movie, lighting enabled | 144.00 | 7.050 ms | 0.486 ms | 131.922 ms |
| Expression dissolve | 90.29 | 22.549 ms | 0.437 ms | 130.106 ms |

The disabled case still resolves scene records; its lighting hold statistic is
internal state selection, not visible lighting. The enabled cases show why a
fast game loop can still display visibly stepped lighting. Movie decoder cadence
and render scheduling can extend a hold beyond the nominal cache interval.

The transition callback attempts to freeze **both** sides into textures. In this
particular engine run, both attempts returned the fallback `Flatten`, and the
new sprite continued rendering. Therefore this audit does **not** claim that the
tested transition froze the movie. The swallowed exception and the difference
between fallback and successful snapshot behavior need a separate investigation.
The transition timing dip is observed; its CPU/GPU cause is not yet isolated.

Other concrete limits in the source:

- Visible-source routing recognizes filenames, not the final blended,
  transformed, or shader-modified background pixels.
- A missing or multiple-source match returns no lighting, creating a possible
  lit/unlit discontinuity. Later unseen Python states are explicitly skipped.
- ATL/Python discovery is bounded to four seconds. Legacy finite Animation
  lists receive additional frame-boundary coverage.
- The existing verification compares selected cache records against expected
  cache records. Its approximately 5-Hz screenshot video cannot establish smooth
  60-Hz playback, short-flash response, or independence from the cache's limits.

### Preview

`MainWindow._poll_background_video_frame` submits a decode on one timer tick,
returns the completed frame on a later tick, and waits until another tick to
submit the next decode. A deterministic probe of this production method with
instant decoding and exact 15-ms ticks delivered **199 frames in six seconds**
from a 60-fps source: **33.17 fps**, with 30-ms median delivery intervals. This
isolates a scheduler limit; it is not a measurement of an actual Qt window.

The preview interpolates complete scene textures and metadata on the CPU, then
uploads the results. Playback is permitted while future scene states are still
being built. Beyond the available cache horizon, interpolation returns the last
available state. Late arrivals can change the lighting without a new background
event. Unlike the game, the preview does interpolate, so the two hosts' temporal
behavior is not equivalent even though they share a final fragment shader.

The current analyzer exceeds the frame budget:

| Warm sequential stage | Median, five runs |
|---|---:|
| Prepare image and classify sources | 123.341 ms |
| Build scene maps and metadata | 139.224 ms |
| CUDA transport, CPU readback and packing | 44.198 ms |
| CPU wrap map | 1.006 ms |
| Complete sequential solve | 305.578 ms |

This used frame 30 of `yellow_drift.webm`, in memory, one OpenCV thread, after
one warmup. It excludes decoding, file encoding, process startup, and rendering.
The CUDA row includes host work and synchronization; it is not pure GPU time.
Parallel batch throughput must not be confused with the latency of a new frame.
The per-stage medians need not sum exactly to the median total.

A separate cold run of the existing temporal benchmark built 21 preview anchors
for the same five-second, 24-fps movie in 8.543 seconds: 2.376 seconds extracting
analysis frames and 5.715 seconds in batched analysis. This is one local workload,
not a hardware-wide benchmark. Cold startup and warm per-frame latency are
different measurements, and both matter.

## Proposed rendering pipeline

```text
Current background composition and source timestamp
                    |
        GPU texture shared by all characters
                    |
  Linear-light reduction, luminance, saliency, source moments
                    |
  Irradiance / exposure / directional lights / probe textures
                    |
       Existing cached sprite surface information
                    |
       Shared physical sprite-lighting shader
                    |
             Authored scene composition
```

### 1. Use the actual background render

Tap the registered background composition after its own placement, animation,
movie frame, and relevant background effects. Exclude characters, dialogue,
stickers, and UI so they cannot feed their own light back into the analysis.
An author API must identify background contributors for ambiguous screen-based
compositions; guessing a filename is not enough.

Give each render context a scene generation, source-frame identity/timestamp,
and explicit transform mapping. Cache the resulting GPU products once for that
context and source state, then share them across all characters. Old and new
transition sides require separate contexts. A global last-scene variable cannot
represent both correctly.

The displayed movie frame must own the analysis timestamp. An independently
queried audio/decoder clock can differ from the texture actually presented.
Static backgrounds reuse their result. Movement that changes the visible
background or its mapping invalidates the appropriate result.
Reuse the engine's rendering dependency graph; do not run a DynamicDisplayable
callback a second time just to obtain a lighting input. Keep GPU resource handles
out of serialized/rollback state and rebuild transient contexts after load or
device loss.

### 2. Move the changing scene solve to GPU passes

Prototype a small analysis texture, initially 320x180, with a measured quality
comparison against the current 640-pixel analysis. Implement the necessary
linear-light conversions, robust exposure statistics, source saliency,
directional transport, and environment probes as bounded passes. The existing
16x9 placement grid and 26-plane contract provide a useful reference, not an
obligation to preserve an inefficient execution order.

Robust quantiles, connected components, and source ranking are substantial work.
Evaluate GPU histograms/reductions and component labeling against a spatial
source representation with stable identities. Reject an alternative if it loses
distinct emitters, changes exposure materially, or changes the reference lighting results.
An average background color cannot represent multiple directional sources.

Use reusable GPU targets and texture-based scene parameters. Keep full-image
readbacks, PNG encoding, disk cache misses, worker synchronization, and Python
metadata reconstruction out of the live dependency chain. An optional slower
reference analyzer can evaluate results without holding up playback; it must not
periodically overwrite live fields and cause another pop.

Use OpenGL shader/render passes compatible with the target model renderer as
the first portability route. Do not assume CUDA graphics interop, compute
shaders, floating-point targets, or Ren'Py 8-only APIs exist on Ren'Py 7.
Validate texture formats, precision, sampler limits, and target reuse in the
actual engine before selecting them. Treat Ren'Py 6.99's pre-model renderer as
an explicit legacy capability boundary.

### 3. Keep source identity stable over time

Brightness ranking must not reorder persistent light slots on every frame.
Preserve spatial/source identities and use hysteresis for uncertain detection.
Smooth noisy estimates according to elapsed time, while responding immediately
to actual hard cuts and authored flashes. Reset or reconstruct state on seek,
loop, load, rollback, and scene replacement. Test loop seams separately.

Temporal smoothing is a controlled part of the estimator. A blanket fade on
every update would hide brief intended lighting events and add delay.

### 4. Repair composition and preview scheduling

Keep the incoming transition side live for transitions whose authored content
is live. Preserve the outgoing side according to Ren'Py's transition semantics.
Carry explicit coordinate mappings into offscreen passes so lighting does not
depend accidentally on the destination framebuffer. Validate the existing
third-party shader and LayeredImage behavior throughout this change.

In Preview, use a bounded decoder queue driven by source timestamps and
completion events. Keep decoding ahead without building a backlog; present the
latest appropriate complete frame and derive its lighting in the same update.
Batch texture work in the rendering context. Use the same analysis passes,
temporal rules, and lighting shader as the game. A cache can accelerate reopening
assets, but opening a movie must not require analysis of its full duration.

### 5. Retain useful preprocessing

Sprite normals, height, AO, edges, and response maps do not generally depend on
the background. Preserve this reusable work. Predict/prewarm likely sprites and
reuse content-identical inputs; separately measure first appearance and
expression changes. Do not promise zero preparation for arbitrary unseen sprite
geometry. An expression or layer change that affects geometry must invalidate
the appropriate surface data.

## Alternatives considered

| Technique | Benefit | Remaining limitation | Decision |
|---|---|---|---|
| Interpolate the game's cached fields | Removes obvious stepping on covered movies | Still misses unseen states, effects, and unrepresented flashes; needs compatible light identities | Possible migration aid, not the primary redesign |
| Bake every video frame | Accurate known-frame selection | Preparation and storage scale with duration; live composites remain unsupported | Reference/export option |
| Run the existing CPU/CUDA analyzer asynchronously | Reuses the current solver | Warm latency is hundreds of milliseconds in this probe; queues can become stale | Offline reference only |
| Shared GPU analysis of the current scene | Removes the timeline and readback bottlenecks | Requires new analysis kernels, render-context integration, and quality validation | Recommended implementation |

## Implementation milestones and acceptance gates

1. **Baseline and instrumentation — completed for this audit.** Retain source
   fingerprints, unlit/lit scheduling, state-hold duration, preview scheduler
   behavior, and cold/warm analysis costs. Add GPU queries and presentation
   timestamps before attributing any remaining frame-time cost to the GPU.
2. **Live texture and context prototype.** Prove a background texture can feed
   multiple sprite passes at the correct frame and placement in both hosts.
   Include movies, ATL blends, background shaders, expressions, and dissolves.
   Confirm no character/UI feedback and no source mutations.
3. **GPU analysis and quality comparison.** Port the complete scene-dependent
   lighting terms incrementally. Compare static and dynamic outputs against the
   established reference. Benchmark the complete pipeline, including texture
   transfers and any synchronization. Commit to the algorithm only after its
   hardest source-detection and exposure cases pass.
4. **Temporal and host integration.** Introduce stable source identities,
   cut-aware state, the timestamped decoder queue, and render-context transition
   ownership. Remove the finite timeline as a dependency for supported live
   sources. Keep an explicit compatible fallback during migration.
5. **Broader validation and installation changes.** Test actual games on Ren'Py
   7 and 8, then representative NVIDIA, AMD, and integrated GPUs. Make background
   movie preanalysis optional only after the new path passes. Preserve owned
   installation updates and removal behavior.

Initial engineering targets, not achieved measurements:

- 60-fps source playback with 16.67-ms total frame budget on an agreed baseline
  machine; budget roughly 2 ms for live SceneLight analysis plus relighting,
  then refine from complete-pipeline measurements. Also test 120/144-Hz displays.
- Lighting corresponds to the rendered source frame with at most one frame of
  additional pipeline delay; no backlog that grows with movie length.
- Constant memory with movie duration and no full-video analysis wait before
  playback. Report first-frame latency separately from steady-state frame times.
- No unintended unlit frames, source-slot jumps, stale generations, loop seams,
  or incoming-animation freezes. Preserve real hard cuts and short flashes.
- Quality checks cover multiple colored emitters, neutral scenes, bright/dark
  clothes, different character shapes, thin sources, exposure changes, and
  movement. Compare every shader-facing term as well as final pixels; require
  visual approval of representative motion, not only matching selected IDs.

Tests should use independent stimulus: authored light pulses and known movement
with known timestamps, plus decoded source-frame references. Record missed and
duplicated frames, source-to-light delay, frame-time p50/p95/p99, longest stall,
and CPU/GPU cost. Keep performance runs separate from screenshot/video readback.

## Evidence and reproduction

Historical evidence directory: `realtime-design-audit-20260908/` (not distributed).

- `game-fixture/` is a separate copy; the user's Copy (2) was not modified.
- `game-observations.json` contains raw scheduling, CPU submission, and transition
  records; `game-summary.json` contains the trimmed statistics above.
- `preview_probe.py` and `preview-probe.json` reproduce the scheduler simulation
  and warm in-memory analysis measurement.
- `cold-yellow/` contains the cold temporal benchmark artifacts;
  `cold-benchmark.json` retains the measured console result.
- `tools/fixtures/realtime_budget_audit.rpy` is the reusable, development-only
  Ren'Py probe. Copy it into an isolated game's `game/` directory, set
  `SCENELIGHT_REALTIME_AUDIT` to an existing output directory, and launch the
  Backrooms fixture with its Ren'Py 7.8.7 SDK. It uses its own save namespace and
  quits after the measured sequence. Do not distribute it in a player's game.

The official [model rendering documentation](https://www.renpy.org/doc/html/model.html)
and [custom displayable documentation](https://www.renpy.org/doc/html/cdd.html)
describe render-to-texture models and shader inputs. They support the proposed
integration mechanism; they do not establish that the new solver already meets
its quality or performance targets. The target 7.8.7 engine source was also
inspected rather than assuming the current online API applies unchanged.

## Validation of this audit

- The new Ren'Py probe compiled and completed its sequence in the isolated
  7.8.7 game. Its raw output records both successful playback and the actual
  transition fallback, rather than assuming the snapshot path succeeded.
- 27 existing focused runtime/preview temporal tests passed.
- Repository `ruff check .` passed. The standalone preview probe also passed
  Ruff checks. No type-check command is configured in the inspected project.
- `python -m build` produced the wheel and source archive in the audit output
  directory. The development probe is absent from the wheel.
- `ruff format --check .` reported seven pre-existing formatting failures in
  `cuda_backend.py`, `preview/temporal.py`, and five existing audit/review tools.
  This investigation did not reformat unrelated production work.
- The full test suite, a new GPU solver benchmark, and visual certification of
  a replacement renderer were not performed: this change adds an investigation
  document and development probe, with no production renderer changes.
- Final review checked the reported figures against raw observations, verified
  that Copy (2)'s runtime hash remained unchanged, and confirmed the probe was
  absent from the original game. This investigation added the design record and
  `tools/fixtures/realtime_budget_audit.rpy`.
