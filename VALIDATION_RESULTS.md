# Validation results

The latest recorded checks, hardware measurements and known limits are in
[Compatibility and validation](docs/BETA_VALIDATION.md).

- **Automated checks:** 618 tests passed locally on 15 September 2026, with no
  failures or skips. Earlier Windows/Linux CI results concern the recorded earlier revisions.
- **Native rendering:** Ren'Py 7.7.1 and 8.5.3 checks covered movement,
  transitions and save/load with form-map version 5.
- **Installation:** a fresh environment installed the source package, scanned,
  installed, verified and removed a synthetic game without changing its source files.
- **Older hardware:** recorded Radeon measurements predate the final surface-map
  correction. That follow-up could not be repeated while the machine was offline.
- **Animation correction:** twelve video and synthetic cases; identical live and
  prepared replay; native 7.7.1/8.5.3 prepared playback and save/load, plus DDLC and
  Amy integration checks. The older Radeon host was unreachable for this revision.

A successful installation or short playback test does not establish compatibility
with every route, asset or custom displayable in a game.

## Historical records

- [Detailed results through 5 September](docs/history/validation-through-2026-09-05.md)
- [11 September compatibility and memory results](docs/history/validation-2026-09-11.md)
- [Cached animation timing audit](docs/history/temporal-validation-2026-09-05.md)
- [Live analysis implementation checks](docs/history/live-analysis-2026-09-09.md)

The original measurements and failed or incomplete checks remain in these records.
[Validation procedure](VALIDATION.md).
