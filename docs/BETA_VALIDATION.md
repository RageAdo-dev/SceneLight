# Compatibility and validation

Coverage updated on 15 September 2026. Automatic discovery does not recognize
every game, and a successful installation is not a complete playthrough.

## Current local candidate

The local suite passed **629 tests**, with no failures or skips. Regression checks
cover side-light reversal, consistent normals across sprite sizes, bounded painted
relief, dark-scene response and continuity when bright regions meet. Fresh Ren'Py
7.7.1 and 8.5.3 fixtures passed prepared playback, movement, transitions and
save/load using form-map v6; original authored files were preserved.

The actual Preview export path retained all 1,799 frames of the colored-background
clip and all 900 storm frames at 1080p and their original frame rates. The Windows
launcher has been checked with an isolated bundled interpreter; this is not a
clean Windows virtual-machine test.

Repeated before/after analysis runs on the development PC measured approximately
4.0–4.2 ms before and 3.27–3.29 ms after. GPU analysis render targets decreased
from 191 to 160. These short runs measure analysis rather than total game frame
rate, utilization or power. The older Radeon host was unreachable for this revision.

## Previous published validation

The preceding local suite passed **618 tests**. All six
[Windows/Linux CI jobs](https://github.com/RageAdo-dev/SceneLight/actions/runs/34939242237)
passed for commit `a5d21bf`: each Windows test job passed 591 tests and skipped 27;
each Linux test job passed 590 and skipped 28. Hosted runners lack the graphics
features needed by those rendering tests; Linux also skips the Windows process
check. The full local run covered them. A fresh source-package installation
completed scan, install, verify and remove without changing the synthetic game's
original files.

The animation correction was checked across six moving backgrounds and six
synthetic cases, including fades, flashes and cuts. Live and prepared Preview
rendering matched exactly. Native Ren'Py 7.7.1 and 8.5.3 played the prepared
waterfall frames and passed save/load; a DDLC animation lab and Amy's opening
dialogue also passed. The first DDLC harness copy omitted its root `characters`
directory; the complete fixture passed after that setup error was corrected.

The real video check exposed different RGB conversion in Ren'Py 8. The cache now
stores both exact decoder variants rather than falling back for that clip.
This correction changes Preview exposure by removing a redundant video-only
adjustment. It does not hold lighting fixed or reduce the source frame rate.

| Area | Recorded coverage |
| --- | --- |
| Player setup | Install, verify, update, launch, save/load, remove and reinstall |
| Author setup | Embed, inspect, source edit, refresh and unembed |
| Native engines | Opening-story checks on 7.4.8 and 8.5.3; animation/save-load labs on 7.7.1 and 8.5.3 |
| Legacy games | A disposable Ren'Py 6 mod through the 7.7.1 compatibility runtime |
| Animation | GIF playback/export in Preview; ATL and VP9/WebM playback in Ren'Py |
| Surface maps | Previous v5 migration; current v6 resolution and painted-relief checks |
| Source protection | Original hashes and isolated save sentinels preserved |

Fourteen of fifteen games in the regression corpus passed automatic install and
verification. **Axiom** produced no background/sprite mappings and is not counted
as automatically compatible. Opening-story checks covered eight dialogue
interactions each in Amy, Still With You and Crossing Over. Full routes and every
custom asset were not exercised. [Detailed corpus results](history/validation-2026-09-11.md).

Form-map v5 passed movement, lighting-mode, transition and save/load checks on
Ren'Py 7.7.1 and 8.5.3. The vertex and fallback shaders produced identical pixels
for the Eileen example. The older Radeon machine was unavailable for this final
surface follow-up; its measurements below concern the preceding optimization pass.

## Playback and hardware

Windows is the supported Setup platform. Live analysis requires OpenGL 3.3 or
OpenGL ES 3.0 with the required floating-point rendering operations. Compatible
integrated graphics can work; CUDA and a dedicated GPU are not required. The CPU
analysis fallback does not turn playback into a CPU-only renderer.

| Older Radeon HD 6700M measurement | Result |
| --- | --- |
| GPU drawing at 2160×1215 | 14.62 ms → 11.98 ms with vertex sampling (about 18% less) |
| 24 fps movie playback | About 22 presented frames/s |
| 30-minute run | 28 scene cycles and two save/load cycles, no renderer errors |
| Private memory after warm-up | Five-minute medians of 499.4–525.3 MiB; peak 541.0 MiB |
| Final engine texture counter | 154.4 MiB after the transition-memory fix |

That iMac runs **Windows**, so these are not macOS results. The figures do not
establish performance for every laptop or procedural effect, and GPU elapsed time
is not a utilization or power measurement.

Eighteen synthetic comparisons were pixel-identical on the tested NVIDIA and AMD
GPUs. Real-game AMD captures differed by at most 4/255 in a channel on 305 of
921,600 pixels. Driver and engine differences therefore prevent a universal
bit-identity claim. [Full numerical and memory record](history/validation-2026-09-11.md).

Prepared movie lighting is lossless and retains the analysis resolution and light
count. Frame advances were verified after loading saves. Movies whose transforms
or decoded-frame signatures cannot select a valid cached result use live analysis.
See [prepared playback](prepared-playback.md) and [performance](performance.md).

Ren'Py 7.8.7 is excluded as the supplied compatibility runtime because its texture
leak was reproduced. The current pinned runtime is **7.7.1**. Historical tests using
7.8.7 do not recommend that version for new installations.

## Reproduction and reporting

Generate an original lab with:

```text
python examples/synthetic/make_release_lab.py <new-directory>
python tools/audit_vertex_sampling.py <lab>/game/scenelight_lab <new-output-directory>
```

The second command needs Preview dependencies and OpenGL 3.3. It checks images and
GPU draw time, not total game frame rate. Use `--ddlc` on the lab generator only
for an overlay in a disposable, separately obtained DDLC copy.

For a bug report, include SceneLight and Ren'Py versions, OS, GPU/driver, input
format and a short reproduction. State whether it occurs in Preview or a game,
and whether a scene change, resize or save/load triggers it. Review logs for local
paths before sharing. [Validation procedure](../VALIDATION.md).
