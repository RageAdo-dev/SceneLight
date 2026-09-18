# Compatibility and validation

Coverage updated on 18 September 2026. Automatic discovery does not recognize
every game, and a successful installation is not a complete playthrough.

## Current local candidate

The latest tester build passed **737 tests** locally. It includes the sprite-map
and exposure corrections, responsive Setup controls, optional-CUDA-independent
Preview startup, and correct still-image handling for JPEG/MPO HDR gain maps.
The reported HDR photo produced identical pixels across six consecutive Preview
frames with live lighting active. Windows release ZIP integrity and bundled
source contents were verified.

| GPU family | Current evidence |
| --- | --- |
| NVIDIA | Current Preview rendering and reported game scenes checked on an RTX 4090 |
| AMD | Previous physical Radeon HD 6700M coverage, detailed below; the latest build still needs a fresh AMD tester pass |
| Intel | Uses the same capability-based OpenGL path; no physical Intel validation recorded for this candidate |

CUDA is optional setup acceleration. Its absence does not block Preview, and the
CPU analysis path remains available. These results do not establish support for
every GPU or driver; testers should report their GPU model and driver version.

## Earlier local candidate

The local suite passed **641 tests**, with no failures or skips. Regression checks
cover side-light reversal, consistent normals across sprite sizes, bounded painted
relief, dark-scene response and continuity when bright regions meet. Fresh Ren'Py
7.7.1 and 8.5.3 fixtures passed prepared playback, movement, transitions and
save/load using form-map v8; original authored files were preserved.

Creative colour separation gives every detected hue family equal standing by
raising its lobe to an exponent and renormalising the lobes against each other.
That exponent therefore set how sharply one lamp handed over to the next, and at
the previous value the handover collapsed to a step. Because the lobes are shaped
by a direction field that reverses through the sprite's form centre, the step fell
on a straight line down the middle of a character, drawing a hard-edged vertical
seam and terraced patches across a face, neck, hands and cardigan. Rendering the
production shader with the Interaction mod's own Sayori sprite and two strongly
separated lamps measured a 27 form-map pixel handover at one detected family and
16 at two; the loosened exponent widens those to 79 and 35. The lamp colours, the
numbered regions, the term weights and the rest of the lighting model are
unchanged.

Painted shading is now read at form scale, so an artist's own shading bands and
line boundaries no longer arrive as steps in the inferred surface. This is general
to any sprite with painted shading; it was measured against the approved surface,
where faceting in the inferred normals drops by about half while a small painted
highlight still reaches the surface at 81% of its previous strength.

All six [Windows/Linux CI jobs](https://github.com/RageAdo-dev/SceneLight/actions/workflows/ci.yml)
pass on the current `main`. The linked download is built from `main`, and its
checksum is published beside it. Hosted runners skip the graphics-dependent tests,
which the local runs cover.

A window resize or fullscreen toggle during play could previously leave a
character drawn as a solid black silhouette, show a doubled sprite across a scene
transition, or hold a stale background behind the dialogue box. Ren'Py deletes
every GPU name when the drawable changes, then reuses those names, so the runtime
now retires its own lighting textures as part of that change rather than letting
their destructors free names the engine had already reassigned. On the resize
probe the engine's leak counter reports zero across two resizes, down from 27
before the fix and 236 in the original failing session, and the frame captured
after the resize is byte-identical to the frame captured before it.

The actual Preview export path retained all 1,799 frames of the colored-background
clip and all 900 storm frames at 1080p and their original frame rates. The Windows
launcher has been checked with an isolated bundled interpreter; this is not a
clean Windows virtual-machine test.

Video export length is now determined by the number of frames the exporter
declares, not by how long the source audio happens to last. An encoder that
receives the wrong number of frames refuses to publish the file, so a truncated
export fails loudly instead of shipping.

The directional revision was measured on the older Radeon HD 6700M host by running
one frame of analysis on each build, back to back, through the same offscreen
context. Warm-scene analysis fell from 177.5 ms to 137.1 ms and cool-scene analysis
from 171.1 ms to 123.6 ms (23–28% lower). GPU passes fell from 131 to 97 per frame
and analysis render targets from 163.4 MiB to 131.6 MiB. These are analysis
measurements, not total frame rate, utilization or power.

A 183-second run of the same host stayed between 435.6 and 525.5 MiB of private
memory after warm-up, finished 10 scene cycles and one save/load, and never
disabled the renderer. Prepared movie lighting from an earlier build is rejected
after an engine change and rebuilt by the installer; that run covers live analysis
instead, because it copied the runtime into a game without re-running setup.

A 48-interaction scripted session in *Still With You* on Ren'Py 8.5.3 kept live
lighting enabled across three backgrounds and two characters with several
expressions, with no renderer failures. It stopped at an author-authored pause the
probe does not drive, so this is a long opening session rather than a full route.

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
verification. **Axiom** is a monologue over full-screen painted art: none of its
ten images has any transparency, so it contains no character sprites and
SceneLight correctly installs nothing. It is a game with nothing to light rather
than a detection failure. Opening-story checks covered eight dialogue interactions
each in Amy, Still With You and Crossing Over, and the longer session above covers
48 interactions in Still With You. Full routes and every custom asset were not
exercised. [Detailed corpus results](history/validation-2026-09-11.md).

Example media in the repository is re-encoded as page-weight previews; the
full-quality originals are attached to the
[private beta release](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.0.0-beta).
The Windows launcher now carries product version metadata, and the release workflow
signs both launchers and fails the build on an invalid signature when the signing
secrets are configured. No certificate is configured yet, so published builds are
still unsigned and Windows will show "Unknown Publisher".

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
