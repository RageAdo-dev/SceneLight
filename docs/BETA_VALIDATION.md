# Beta validation and compatibility

SceneLight is a private beta candidate. Automatic discovery does not cover every Ren'Py game,
and a successful install is not a complete game playthrough.

## Current validation

The local Windows suite passed 566 tests on 2026-09-10, with no failures,
errors or skips. Lint, formatting, package builds, dependency checks and the
configured static/dependency audits are also release gates. GitHub CI runs the
committed source on Windows and Linux, with a separate player-only installation
job that excludes the optional Preview stack.

The default player package was installed in an empty Python environment and
prepared all frames of a test movie. Qt Essentials and FFmpeg are required player
components; the full Qt Preview interface and PyOpenGL remain optional. Missing
preparation components cause an actionable installation error instead of silently
selecting a more expensive live playback path.

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

When reporting a problem, include the SceneLight version, Ren'Py version, OS,
GPU/driver, input format and a short reproduction. Describe whether the issue
occurs in Preview or in a game and whether it starts after a scene change,
resize or save/load. Review logs before sharing them, since they can contain
local paths. Use a minimal original fixture where possible.
