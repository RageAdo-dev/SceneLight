# Performance

SceneLight reuses prepared movie lighting and sprite maps, and avoids repeated
shader work. These optimizations retain lighting resolution, detail and timing.
See [prepared playback](prepared-playback.md) and [hardware requirements](COMPATIBILITY.md).

## Installation and update finalization

**Historical beta 27 measurement.** Windows verification changed in beta 28.
The large-file timing run has not been repeated for that revision or 1.1.0;
the numbers below describe beta 27 only.

Measured on 29 September 2026 using 43,835 generated runtime files (2.03 GB) on
Windows/NTFS and a WDC WD4005FZBX mechanical SATA drive. The previous installer and
beta 27 used the same host and file-size distribution. Every final owned file was
independently SHA-256 audited; validation did not trust the reuse cache.

| Operation | Previous | Beta 27 |
| --- | ---: | ---: |
| Fresh-install finalization | 173.23 s | 33.63 s |
| Asset-update finalization | 241.62 s | 67.39 s |
| Publish an already prepared fresh runtime | 154.16 s | 9.95 s |
| Publish an already prepared refreshed runtime | 192.82 s | 33.42 s |
| Verify unchanged owned files | 19.99 s | 11.80 s |

Fresh finalization includes the prepared-file hash and publication. Refresh also
includes the initial ownership check, old-runtime cleanup and temporary-runtime
cleanup. File generation, capture, image analysis and recreation of analyzer output
were outside the measured intervals. The size distribution was 75% 16 KiB,
20% 64 KiB, 4% 256 KiB and 1% 1 MiB. Disk cache and machine activity affect results.
They measure file operations only; whole-install speed also depends on capture and analysis.

The installer transfers a private prepared runtime on the same volume instead of
copying it again. Cross-volume or linked trees keep the copy fallback. Verification
can reuse a checksum when file identity, size, write time and OS change time match.
Beta 28 additionally requires a Windows NTFS/ReFS journal sequence and an exclusive
handle before reusing a checksum. Timestamps alone can collide for rapid edits;
other open handles can also coalesce journal records. Missing journal information
or an exclusive-open conflict forces a full read without a reusable stamp. Missing stamps, unsupported filesystems
and changed identities require byte reads. Initial full-file hashing is sequential
to avoid competing seeks on hard drives. Cached checks use bounded concurrency.

This change preserves the final ownership check, rollback, native-launcher recovery,
source files and saves. Source artwork still uses byte-based change detection.
Filesystem-assisted verification is not a fresh byte-for-byte disk-corruption audit;
the benchmark's independent byte audit was a separate validation step.

The four small native Ren’Py 7/8 player/developer rehearsals also verified unchanged
updates, one new sprite/background, reuse of old maps, preserved settings and a
real save restored to its prior gameplay checkpoint. Their sub-second unchanged
updates are fixture results, not timings for an 18,000-sprite project.

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
