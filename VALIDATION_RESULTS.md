# Validation results

The latest recorded checks, hardware measurements and known limits are in
[Compatibility and validation](docs/BETA_VALIDATION.md).

- **Local candidate:** 639 tests passed on 16 September 2026, with no failures
  or skips. Ruff checks and formatting passed; Bandit reported no medium/high
  severity findings, and the dependency audit found no known vulnerabilities.
  Wheel and source-distribution builds passed.
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

- [Detailed results through 5 September](docs/history/validation-through-2026-09-05.md)
- [11 September compatibility and memory results](docs/history/validation-2026-09-11.md)
- [Cached animation timing audit](docs/history/temporal-validation-2026-09-05.md)
- [Live analysis implementation checks](docs/history/live-analysis-2026-09-09.md)

The original measurements and failed or incomplete checks remain in these records.
[Validation procedure](VALIDATION.md).
