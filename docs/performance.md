# Live lighting performance

SceneLight keeps the lighting model, analysis resolution, field resolution, and
animation timing when selecting faster implementations. It does not lower
quality to reach a frame-rate target.

The live analyzer now uses shared-memory integer histograms and parallel prefix
sums for quantiles, shared-memory FFTs for wide Gaussian filters and convolution,
and single-channel 32-bit storage for scalar fields. Scalar texture swizzles
preserve the original four-channel sampling behavior. Compute shaders are
optional: the equivalent raster implementation remains available.

Live playback also retains light identities when physical emitter scores are
nearly tied. This separately fixes temporal direction jumps; it intentionally
changes the ordering that caused those jumps. Current-frame light values are
not averaged or delayed. The historical byte-parity measurements below concern
the stateless optimization path, not a guarantee that an unstable old animation
must remain unchanged. See [live continuity](live-continuity.md).

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

GPU utilization percentages depend on clock speed, scheduling, and other active
applications. Lower frame cost does not imply a fixed percentage reduction in a
Task Manager graph. Prefer GPU elapsed time, frame pacing, and measured power
when comparing a specific machine.

The existing CPU reference remains unsuitable for per-frame live analysis. On
the same desktop, complete field generation with the default single-worker
transport path took about 1.1 seconds after warmup. With eight point workers,
transport alone still took about 0.26 seconds. This excludes CPU rendering of
the final character. The benchmark's `--cpu` switch disables CUDA; a `--live`
Preview still uses OpenGL and must not be described as CPU-only.

Modern Ren'Py requires working graphics acceleration and supports integrated
graphics; a dedicated graphics card is not required. See
[Ren'Py's graphics requirements](https://www.renpy.org/doc/html/problems.html).
No integrated adapter was exposed on the test computer. Low-end laptop frame
rates and battery use therefore still require measurements on those laptops.

Reproduction tools:

- `tools/profile_live_analysis.py`: CPU stages, complete analysis latency,
  instrumented GPU passes, and texture allocations.
- `tools/compare_live_analysis.py`: alternating implementations on identical
  decoded frames, comparing every output field.
- `tools/audit_preview_playback.py`: presentation and memory measurements;
  `--gpu-timing` adds GPU elapsed queries, and `--maximized` tests a larger view.
- `tools/fixtures/live_memory_audit.rpy`: opt-in Windows native memory audit for
  a disposable game copy, with a memory ceiling and automatic exit.
