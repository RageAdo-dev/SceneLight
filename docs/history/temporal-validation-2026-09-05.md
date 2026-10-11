# Animated-background verification — 2026-09-05

> Historical development record. Versions, measurements and remaining work below
> describe that revision, not the current release. Start with the
> [current documentation](../README.md) and [compatibility notes](../BETA_VALIDATION.md).

Historical test target: a disposable Backrooms Media Lab copy only.
Engine: Ren'Py 7.8.7, gl2, Windows, RTX 4090. Runtime manifest 8; capture protocol 42.

## Reproduced causes

1. Ren'Py script code resolves `dict` to `RevertableDict`. JSON returns builtin
   dictionaries. The previous `isinstance(sequence, dict)` rejected valid
   timelines and silently selected the static base field. The shipped resolver
   now checks the standard Mapping interface. Regression tests execute the
   shipped functions with Ren'Py-like type substitution.
2. `get_game_runtime()` advances at interaction boundaries, not on every rendered
   frame. It cannot drive lighting during a long dialogue pause.
3. A four-second discovery window is not an animation's period. The previous
   independent loop could not synchronize to arbitrary authored durations.

## Actual engine results

The audit holds each background over multiple loops, changes Monika's expression
without changing the dynamic background, and records the field the character
actually used. Movie expectations use the playing channel's decoder position.

| Background | Compared observations | Distinct lighting fields | Mismatches |
|---|---:|---:|---:|
| Dynamic four-room switch | 213 | 4 | 0 |
| Legacy Animation / extracted GIF | 164 | 16 | 0 |
| ATL frame animation | 161 | 12 | 0 |
| Static-noise Animation | 84 | 8 | 0 |
| Looping yellow movie | 262 | 41 | 0 |
| Manual movie channel | 329 | 41 | 0 |
| Pool movie | 329 | 41 | 0 |
| Real VHS movie | 389 | 46 | 0 |
| Optical GIF frames | 91 | 8 | 0 |
| TV-static GIF frames | 79 | 5 | 0 |
| Static classroom | 27 | 1 | 0 |

Before the fix, all these cases used only one lighting field. The baseline
logged 174 mismatches for DynamicDisplayable, 163 for ATL, and 318 for the movie.
Baseline legacy Animation observations did not record the selected image, so no
before mismatch percentage is claimed for those cases. Eleven movie startup
observations in the final runs had no decoder position and were not compared.
All 2,128 comparable observations passed across all ten named animated
backgrounds and the static control.

An intermediate extended run caught two movie boundary disagreements when the
observer sampled the decoder later than the character in the same frame. The
runtime now samples each movie channel once per presented frame, shared by all
characters. Final verification compares the field with that frame's decoder
sample and separately logs the later observer position. This also prevents
characters from choosing different temporal samples within a slow frame.
The intermediate run is retained under `extended/`, not discarded.

Classroom screenshot comparison: mean absolute RGB channel difference 0.001918
on the 0–255 scale; maximum 7. Atlas packing changed, but exposure, saturation,
transport analysis, and shader lighting coefficients were not changed.

Privately retained evidence: `temporal-audit-20260905/index.html`,
`results.json`, `final/observations.json`, `final-extended/observations.json`,
and `verified-game.mp4`.
The video samples actual game screenshots at about 5 Hz; it is not an FPS benchmark.

## Reproduction

Copy `tools/fixtures/temporal_audit.rpy` to an isolated Backrooms fixture's
`game/zz_scenelight_temporal_audit.rpy`. Set `SCENELIGHT_TEMPORAL_AUDIT` to an
existing output directory and optionally `SCENELIGHT_AUDIT_VIDEO=1`, then launch
the fixture with its Ren'Py SDK. The audit overrides startup only when the
environment variable is present, uses a separate save directory, and quits when
finished. Never ship this helper inside a player's game.

Run `tools/build_temporal_audit_report.py <evidence-root> <fixture-root>` to
compare observations and produce the HTML/MP4. It exits unsuccessfully if any
compared state mismatches or a tested scene has no comparable observations.

## Launch safeguards exercised

- Cancellation during subprocess creation is not lost.
- A real silent Windows worker and its child both terminate on cancellation.
- An interrupted recapture can be retried; prior runtime files are recovered
  before reseeding form caches. Conflicting generated files are preserved in
  `recovered-runtime-conflicts`, not deleted.
- Atlas packing grows horizontally within Ren'Py's 4096-pixel texture limit.
  Oversized inventories fail with an actionable error before atlas allocation.
- A capture completion marker is written only after result validation.
- Fine mouse-wheel deltas accumulate; Home/End in the character-tag entry no
  longer scroll the character list.

## Coverage limits

These checks cover the named master-layer paths above. They do not cover arbitrary
screen-layer composites, masked movies, simultaneous differently positioned
video sources, or all custom displayables on every Ren'Py release/GPU.
Legacy Animation frames are explicitly inventoried; ATL/Python source-state
discovery remains bounded to four seconds at 25-ms sample intervals. A later
unseen source is left unlit and logged instead of inheriting unrelated lighting.
Procedural changes to the pixels of the same source, time-varying shader grades,
and arbitrary compositing need additional integration coverage.
Movie light fields are sampled at approximately 8 Hz; the decoder clock selects
among those samples. This is not per-decoded-frame analysis.
