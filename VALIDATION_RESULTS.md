# Validation results

The latest recorded checks, hardware measurements and known limits are in
[Compatibility and validation](docs/BETA_VALIDATION.md).

- **Local candidate:** 630 tests passed on 15 September 2026, with no failures
  or skips. Ruff checks and formatting passed; Bandit reported no medium/high
  severity findings, and the dependency audit found no known vulnerabilities.
  Wheel and source-distribution builds passed.
- **Directional lighting:** regression tests cover direction reversal, surface-map
  resolution, painted-edge relief, dark scenes and continuity as bright regions meet.
- **Exports:** the Preview export path produced all 1,799 colored-background frames
  and all 900 storm frames at 1920 × 1080 and the original frame rates. Video
  exports are cut to the exact frame count the caller declares, so a short audio
  track can no longer end the file early; a count mismatch is refused instead of
  publishing a shortened video.
- **Native rendering:** fresh Ren'Py 7.7.1 and 8.5.3 fixtures passed movement,
  transitions, prepared animation and save/load with form-map version 6. Original
  authored files were preserved.
- **Performance:** repeated analysis measured about 20% faster on the development
  PC. This is analysis time, not total frame rate, GPU utilization or power.
  The older Radeon machine was unreachable for this revision.
- **Hosted checks:** all six [Windows/Linux CI jobs](https://github.com/RageAdo-dev/SceneLight/actions/runs/35032521064)
  passed for the directional-lighting commit, and the
  [Windows package build](https://github.com/RageAdo-dev/SceneLight/actions/runs/35032802013)
  produced the linked download from that same commit.

A successful installation or short playback test does not establish compatibility
with every route, asset or custom displayable in a game.

## Historical records

- [Detailed results through 5 September](docs/history/validation-through-2026-09-05.md)
- [11 September compatibility and memory results](docs/history/validation-2026-09-11.md)
- [Cached animation timing audit](docs/history/temporal-validation-2026-09-05.md)
- [Live analysis implementation checks](docs/history/live-analysis-2026-09-09.md)

The original measurements and failed or incomplete checks remain in these records.
[Validation procedure](VALIDATION.md).
