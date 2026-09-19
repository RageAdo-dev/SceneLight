# Performance

SceneLight reuses prepared movie lighting and sprite maps, and avoids repeated
shader work. These optimizations retain lighting resolution, detail and timing.
See [prepared playback](prepared-playback.md) and [older-hardware results](BETA_VALIDATION.md#playback-and-hardware).

## Live analysis measurements

On 9 September 2026, an alternating old/new comparison on a Ryzen 7800X3D and
RTX 4090 measured the following. These are desktop measurements, not a guarantee
for integrated graphics or every scene.

| Measurement | Before | After |
| --- | ---: | ---: |
| Complete analysis, synthetic 640×360 video, Preview inputs | 8.94 ms | 4.09 ms |
| Complete analysis, same video, Ren'Py inputs | 8.97 ms | 4.16 ms |
| Complete Preview GPU drawing, 2160×1215 viewport | 8.30 ms | 4.22 ms |
| Preview presentation rate | 60.07 fps | 60.07 fps |
| Analyzer texture allocations, same 640×360 source | 248.9 MiB | 144.8 MiB |

Every shader input was byte-identical across all 180 synthetic video frames in
both host modes and sampled frames from two game videos. The CPU-reference
comparison suite also passed. These comparisons do not claim byte identity for
every possible input or graphics driver. Native Ren'Py 7.7.1 animation and
save/load/rollback checks passed; a three-minute Ren'Py 8.5.2 run retained bounded
memory and live lighting.

These comparisons use stateless analysis. [Light continuity](live-continuity.md)
separately fixes direction jumps by keeping nearly tied lights in a stable order;
it uses current-frame values without averaging or delaying brightness changes.

The analyzer uses shared-memory histograms, parallel quantiles, FFT filters and
single-channel float storage. Texture swizzles preserve sampling behavior.
Compute shaders are optional; equivalent raster passes remain available.

## CPU and graphics requirements

### Sprite-map resolution

On September 18, 2026, two real sprites were compared at a 512-pixel maximum
dimension and at their original resolution. Median times after worker warmup
include analysis and lossless PNG encoding; each form was measured six times.

| Sprite size | 512px preparation | Full-resolution preparation | 512px GPU draw | Full-resolution GPU draw |
| --- | ---: | ---: | ---: | ---: |
| 550×978 | 0.039 s | 0.142 s | 0.086 ms | 0.087 ms |
| 960×960 | 0.075 s | 0.261 s | 0.086 ms | 0.089 ms |

GPU draws used an RTX 4090 at 1280×720, with an already analyzed background and
one moving character. These timings exclude background analysis, presentation,
and first texture upload; they are not a guarantee for integrated graphics.
The extra preprocessing occurs once per unique sprite and is cached. The two
full-resolution map sets used about 3.2–3.4 times the compressed disk space of
their 512px versions. Full resolution is now used consistently in game and Preview;
large inputs reduce analysis concurrency to stay within the memory budget.

The existing CPU reference remains unsuitable for per-frame live analysis. On
the same desktop, complete field generation with the default single-worker
transport path took about 1.1 seconds after warmup. With eight point workers,
transport alone still took about 0.26 seconds. This excludes CPU rendering of
the final character. The benchmark's `--cpu` switch disables CUDA; a `--live`
Preview still uses OpenGL and must not be described as CPU-only.

Modern Ren'Py requires working graphics acceleration and supports integrated
graphics; a dedicated graphics card is not required. See
[Ren'Py's graphics requirements](https://www.renpy.org/doc/html/problems.html).
The desktop benchmark did not expose an integrated adapter. Its results cannot
establish low-end laptop frame rates or battery use.

GPU utilization depends on clocks, scheduling and other applications. Compare GPU
elapsed time, frame pacing and measured power on the same machine; draw time does
not translate to a fixed Task Manager percentage.

## Reproduction tools

- `tools/profile_live_analysis.py`: CPU stages, complete analysis latency,
  instrumented GPU passes, and texture allocations.
- `tools/compare_live_analysis.py`: alternating implementations on identical
  decoded frames, comparing every output field.
- `tools/audit_preview_playback.py`: presentation and memory measurements;
  `--gpu-timing` adds GPU elapsed queries, and `--maximized` tests a larger view.
- `tools/fixtures/live_memory_audit.rpy`: opt-in Windows native memory audit for
  a disposable game copy, with a memory ceiling and automatic exit.
