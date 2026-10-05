# Validation results

The latest recorded checks, hardware measurements and known limits are in
[Compatibility and validation](../BETA_VALIDATION.md).

- **Layered sprite sampling:** reproduced displaced face and clothing shading in
  an Interaction save with Sayori and Monika visible after the transition.
  The shader received the 160 × 90 light-field dimensions through `res0`
  instead of the sprite dimensions. A dedicated sprite-size uniform corrects
  the sample offsets; missing-map sprites continue through the full lighting
  pass. Verified the saved frame with lighting enabled, disabled, re-enabled,
  and at multiple window sizes on Ren'Py 8.2.1. A separate DDLC fixture passed
  pose changes, resizing and lighting on/off on Ren'Py 7.7.1. This is a regression
  check, not a claim of complete mod playthrough coverage.
- **Expression sequences:** replayed the reported classroom lines and eight
  consecutive nurse-office dialogue states, including Monika's expression
  change. The scanner skipped `TranslateSay` nodes, missing both the spoken
  expression and the inherited pose used by later statements. Native planning
  now includes those states. A second fault retained the previous pose's map
  when `keep_running_transform` replaced its child with a named image.
  Capture and replacement regressions cover these two paths, including
  temporary attributes and rebinding maps after save loading. The previous
  single-pass candidate was rejected because it weakened already-correct
  lighting; the original pass structure is restored. At matching window size,
  Monika's approved head-and-torso reference area is pixel-identical before
  and after the full inventory repair. Native capture recovered 8,906 additional
  states without capture errors. The original neighborhood line also uses its
  current pose's map. After resizing away and back, and after toggling lighting
  off and on, pixels above the dialogue area are unchanged at matching size.
  Exact expression matching and the missing-map shadow guard remain. Player
  saves are not used as test outputs. These checks
  cover the reported sequences, not a complete playthrough of the mod.
- **Local candidate:** 668 tests passed on 17 September 2026, with no failures
  or skips. Ruff checks and formatting passed; Bandit reported no medium/high
  severity findings, and the dependency audit found no known vulnerabilities.
  Wheel and source-distribution builds passed.
- **Lamp handover:** creative colour separation raises each detected hue family
  to an exponent and then renormalises the lobes against each other, so the
  exponent decided how sharply one lamp handed over to the next. The old
  exponent collapsed that handover to a step, and because the lobes are shaped
  by a direction field that reverses through the sprite's form centre, the step
  landed on a straight line down the middle of a character. Measured through the
  production shader on the Interaction mod's own sprite, the handover widened
  from 27 to 79 form-map pixels at one detected family and 16 to 35 at two. The
  lamp colours, numbered regions, term weights and rest of the lighting model
  are unchanged.
- **Painted shading:** the inferred surface reads painted detail at form scale, so
  an artist's shading bands and line boundaries no longer render as creases. The
  silhouette term, term weights, relief bound and lighting model are unchanged;
  faceting in the inferred normals drops by about half while fine painted detail is
  retained.
- **Directional lighting:** regression tests cover direction reversal, surface-map
  resolution, painted-edge relief, dark scenes and continuity as bright regions meet.
- **Exports:** the Preview export path produced all 1,799 colored-background frames
  and all 900 storm frames at 1920 × 1080 and the original frame rates. Video
  exports are cut to the exact frame count the caller declares, so a short audio
  track can no longer end the file early; a count mismatch is refused instead of
  publishing a shortened video.
- **Native rendering:** fresh Ren'Py 7.7.1 and 8.5.3 fixtures passed movement,
  transitions, prepared animation and save/load with form-map version 8. Original
  authored files were preserved.
- **Low-end host:** on the Radeon HD 6700M test machine, warm-scene analysis fell
  from 177.5 ms to 137.1 ms and cool-scene analysis from 171.1 ms to 123.6 ms
  (23–28% lower), with GPU passes down from 131 to 97 and analysis render targets
  from 163.4 MiB to 131.6 MiB. A 183-second run held 435.6–525.5 MiB of private
  memory after warm-up across 10 scene cycles and one save/load.
- **Long session:** 48 interactions of *Still With You* ran with lighting enabled
  across three backgrounds and two characters, with no renderer failure.
- **Repository:** example animations are re-encoded as page-weight previews, with
  full-quality originals attached to the private beta release. The Windows
  launchers carry the product name, version, publisher and copyright in their
  version resources, and the release workflow signs both when signing secrets
  are present.
- **Window resizing:** a resize or fullscreen toggle during play could leave a
  character drawn as a black silhouette, show a doubled sprite during a scene
  transition, or leave a stale background behind the dialogue box. Ren'Py frees
  every GPU name on a resize, so the runtime now retires its own lighting
  textures as part of that change instead of letting their finalizers delete
  names the engine had already handed to something else. The engine's own leak
  counter reports zero across two resizes, and the frame after a resize is
  byte-identical to the frame before it.
- **Hosted checks:** all six [Windows/Linux CI jobs](https://github.com/RageAdo-dev/SceneLight/actions/workflows/ci.yml)
  pass on the current `main`, covering the full test suite on Windows and Linux
  plus dependency resolution for a plain install. The linked download is built
  from `main` and its checksum is published beside it.
- **Clean machine:** a Windows Sandbox with no Python installed ran the packaged
  EXE, scanned and installed a corpus game with `source_untouched`, verified it,
  launched it, and removed it again with the game's file hash unchanged. Windows
  reported the launcher as version 1.0.0, product SceneLight.
- **Package:** the [private beta release](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.0.0-beta)
  holds the current ZIP, its checksum and the full-quality example media. The ZIP
  matches a rebuild of the current `main` commit, byte for byte.

A successful installation or short playback test does not establish compatibility
with every route, asset or custom displayable in a game.

## Historical records

- [Detailed results through 5 September](validation-through-2026-09-05.md)
- [11 September compatibility and memory results](validation-2026-09-11.md)
- [Cached animation timing audit](temporal-validation-2026-09-05.md)
- [Live analysis implementation checks](live-analysis-2026-09-09.md)

The original measurements and failed or incomplete checks remain in these records.
[Validation procedure](../../VALIDATION.md).
