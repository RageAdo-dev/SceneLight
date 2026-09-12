# Beta validation and compatibility

SceneLight is a private beta candidate. Automatic discovery does not cover every Ren'Py game,
and a successful install is not a complete game playthrough.

## Current validation

The local Windows suite passed 600 tests on 2026-09-11, with no failures,
errors or skips. Lint, formatting, package builds, dependency checks and the
configured static/dependency audits are also release gates. GitHub CI runs the
committed source on Windows and Linux, with a separate player-only installation
job that excludes the optional Preview stack.

The surface-seam correction was checked against the selected Eileen render:
the production output matches it pixel for pixel. The optimized and fallback
shader paths also match on that scene. Ren'Py 7.7.1 and 8.5.3 completed movement,
colored-light mode changes, a fixed midpoint transition, and save/load using the
new form maps. Form-map version 4 rebuilds older maps during an update. The
older Radeon machine was unavailable for this follow-up; the hardware results
below describe the preceding optimization pass, not a new measurement of this fix.

The default player package was installed in an empty Python environment and
prepared all frames of a test movie. Qt Essentials and FFmpeg are required player
components; the full Qt Preview interface and PyOpenGL remain optional. Missing
preparation components cause an actionable installation error instead of silently
selecting a more expensive live playback path.

Unchanged managed installs now reuse complete raw captures. Generated Ren'Py
bytecode is excluded from the capture identity only when the managed-copy record
identifies its existing authored source; bytecode supplied by the author remains
an input. Native tests verified cache hits, invalidation for same-size/same-time
script edits, changed captured pixels, and restoration of the original pixels.
One shared content hash also replaces two full game-file hashing passes per
capture request.

| Area | Tested scope |
|---|---|
| Packages | Wheel, source ZIP and Windows ZIP player/developer workflows |
| Player workflow | Install, verify, edit, update, launch, save/load, remove and reinstall |
| Developer workflow | Embed, status, source edit, refresh and unembed |
| Edits | Add/remove/rename and pixel changes preserving file size and timestamp |
| Native engines | Opening-story probes on 7.4.8 and 8.5.3; animation/save-load labs on 7.7.1 and 8.5.3 |
| Legacy DDLC | Disposable mod launched through the 7.7.1 compatibility runtime |
| Animation | Actual GIF playback/export in Preview; corresponding ATL and VP9 movie playback in Ren'Py |
| Source protection | Original source/archive hashes and isolated save sentinels preserved |

Fourteen of fifteen unrelated games passed automatic install/verify in the
regression corpus: A Short Story Of Amy, Daisy, Gobo Adventure, Still with you,
Nonsense and Stuff, RECONSTRUCT_ME.exe, Six Hours at Joe's, TURNED ON!, Beyond Silence,
Vampliar, Crossing Over, Pippy's Ultimate Quest for Friendship (and Lessons)!!!,
A Maimed Rite and Motherly. Titles identify test
inputs, not endorsements or bundled content. Axiom produced no automatic
background/sprite mappings and is **not counted as a default-compatible game**.
The mapping requirement was not removed to force a pass.

Opening-story checks covered eight dialogue interactions each in Amy,
Still With You and Crossing Over. Other corpus coverage consists of native
capture/preflight, install and verification. Full stories, every optional route,
arbitrary Python-generated assets and all cross-version saves remain outside
that evidence.

## Playback and hardware

The shared Preview/Ren'Py shader now samples lighting values that are constant
across a character in the vertex stage. It keeps the same lighting formulas,
texture resolution, light count and source frames. Unsupported varying/texture
limits or a rejected combined shader select the original implementation. Games
using Ren'Py's custom shader-part filter also retain the original implementation,
so their filter receives the established public shader name.

On the older Radeon HD 6700M, an ABBA GPU timer comparison at 2160x1215 measured
14.62/14.61 ms for the original draw and 11.98/11.98 ms for vertex sampling: about
18% less GPU drawing time. This is not a measurement of GPU utilization or power.
Four 70-second real-game playback runs remained around 22 presented movie frames
per second for a 24-fps video, with the same 128,010,714-byte engine texture count.
The reduced shader work did not remove that machine's remaining playback limit.

All 18 synthetic Preview comparisons were pixel-identical on both tested GPUs.
Native Ren'Py 7.7.1 and 8.5.3 comparisons on NVIDIA covered two sprites, rotation,
scaling, transparency, physical/separate light colors, transition snapshots and
actual save/load; the captured pixels matched exactly. A game shader-filter test
and deliberately rejected optional shaders preserved original rendering and
save/load. On the old AMD driver, real-game captures had tiny rounding differences:
at most 305 of 921,600 pixels differed, with a maximum channel difference of 4/255.
Visual equivalence, rather than universal bit identity across shader stages, is
the accepted target; no resolution or lighting-detail reduction was introduced.

Prepared movie playback keeps the same lighting calculation, resolution and
light count. The resulting shader inputs are cached losslessly. Tests observed
prepared frames advancing while live-analysis evaluations stayed flat, including
after loading a save. Ambiguous decoded frames and visually transformed movies
retain live analysis of the actual rendered background.

The transition texture fix passed native playback and actual save/load on
Ren'Py 7.7.1 and 8.5.3, including saving during an active transition and loading
that save. Ten settled captures and six fixed-time transition
captures were pixel-identical to their respective pre-change references.
The original form-map hashes also pass on Windows and Linux with AVX-512 enabled;
the small sRGB lookup-table initialization no longer depends on float32 SIMD power
rounding. Per-frame shader calculations and approved map bytes are unchanged.

The older iMac test machine runs **Windows**, not macOS. Earlier measurements
showed that its live analyzer was too slow for smooth movies; prepared playback
addressed that workload. The final 30-minute retest completed 28 scene cycles and
two actual save/load cycles with lighting active and no renderer errors. The
last five-minute median of process-private memory fell from 762.3 MiB before the
transition fix to 525.3 MiB after it (31% lower). After warm-up, five-minute medians
spanned 499.4–525.3 MiB; peak private memory was 541.0 MiB. The final engine texture
counter fell from 432.5 to 154.4 MiB (64% lower).

The snapshot ownership trace found no unowned engine texture bytes after the fix.
Separate 80-cycle/160-transition tests filled rollback history on both engines:
late texture variation was under 0.2 MiB on Ren'Py 7 and zero on Ren'Py 8. These
checks passed the candidate's memory-stability gate. Prepared movie-frame advances
averaged 22.0/s after the fix versus 22.5/s before it for the 24-fps test movie;
this is not a 60-fps performance claim or a measurement of GPU utilization.
Those results do not establish performance for every low-end laptop or procedural effect.

The vertex-sampling candidate also completed a 194.5-second iMac scene-cycle
check: ten movie/static cycles, one actual save/load, 3,023 prepared frames and no
renderer failures. Peak sampled private memory was 541.7 MiB; final engine texture
storage was 154,255,899 bytes. This shorter check supplements the earlier memory
tests rather than replacing the 30-minute result.

Rendering uses Ren'Py's graphics renderer. A compatible integrated GPU can be
sufficient; CPU-only rendering and zero GPU usage are not promised. Native GIF
files are not used as animated Ren'Py images in the test lab: the lab uses decoded
ATL frames, while Preview opens the actual GIF. Desktop Ren'Py does not decode
H.264; the native fixture uses VP9/WebM.

## Reproduction and reporting

Run the repository's test/CI commands and generate the original procedural lab
with `python examples/synthetic/make_release_lab.py <new-directory>`.
Use `--ddlc` only to create an overlay for a disposable, separately obtained DDLC
copy. No commercial game, third-party game art, saves or private captures are
included in the source or release artifacts.

With the optional Preview dependencies installed, run
`python tools/audit_vertex_sampling.py <lab>/game/scenelight_lab <new-output-directory>`
to reproduce the 18 exact-image checks and the offscreen ABBA GPU timer comparison.
The report records the production shader hash and retains images if a comparison
differs. The command requires an OpenGL 3.3 context and does not measure total game
frame rate or GPU utilization.

When reporting a problem, include the SceneLight version, Ren'Py version, OS,
GPU/driver, input format and a short reproduction. Describe whether the issue
occurs in Preview or in a game and whether it starts after a scene change,
resize or save/load. Review logs before sharing them, since they can contain
local paths. Use a minimal original fixture where possible.
