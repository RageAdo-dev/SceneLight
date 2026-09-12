# Validation

Run these checks for changes that affect installation, rendering or distribution.
The [results page](VALIDATION_RESULTS.md) records completed coverage; this checklist
does not imply that every target has passed for the current change.

## Integration matrix

| Target | Required checks |
| --- | --- |
| Synthetic Ren'Py project | Install, compile, launch and verify lighting changes as a character moves |
| Local DDLC fixture | Discover character tags without name presets; check movement and transitions |
| Independent mod | Install in a disposable copy, render a controlled scene and preserve the original source |
| Preview & Calibrator | Compile the production shader; compare Relit, Original and Split; round-trip calibration |

Use both legacy and current Ren'Py generations when a change affects them.
Renderer changes need image comparisons as well as numerical and timing checks.

## Package checks

1. Run the commands in [Contributing](CONTRIBUTING.md), including the dependency audit.
2. Install the built archive into a temporary Python environment.
3. Scan, install, verify and remove a synthetic project. Compare source hashes before and after.
4. Redirect `SCENELIGHT_COMPONENT_ROOT` into the test directory and confirm dependencies do not change global Python.
5. Inspect archives for private game data, runtime caches, local paths and debug output. Licensed documentation figures must retain their credits and notices.
6. Verify checksums and exercise launcher paths containing spaces, percent signs and environment-variable-like text.
7. Remove the temporary component environment after testing. Record cleanup or verification steps that could not complete.

Before public distribution, complete the [fresh Windows checks](docs/FRESH_MACHINE_VALIDATION.md).
Keep physical GPU validation separate from virtual-machine compatibility checks.
Audit the exact base, Preview, packaging and optional CUDA dependency sets.

## Optional effects

Check disabled-effect image parity, enabled rain/glitch rendering, scene and
character scopes, movement, transitions, save/load, rollback and skip behavior.
Verify that the disabled player panel and hotkey stay absent. Custom packs need
separate checks against their intended sprites and renderer.

Keep private fixtures, saves and captures outside the repository. Record engine,
GPU, source identity, method and limitations alongside each result.
