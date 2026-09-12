# Fresh Windows checks

Use a disposable environment and original fixtures to check the built package
without relying on development dependencies or caches.

## Test environments

- **Windows Sandbox or a clean VM:** checks first-run setup, dependency installation,
  source preservation and removal. Revert or recreate it between candidates.
- **Physical Windows machine with supported graphics:** checks shader compilation,
  appearance, frame pacing and memory. Virtual-GPU results do not validate a
  physical vendor's driver or establish laptop performance.

For Sandbox, map only a dedicated input folder as read-only. Copy its contents
into the guest before running them. Disable clipboard, microphone, camera and
printer redirection. Allow networking only when the package needs dependency
setup; an offline package should use `--no-index --find-links`.

A game copy is not a security sandbox. Use trusted games and keep private art and
saves out of published evidence.

## Checklist

Record Windows, Python, SceneLight, Ren'Py, GPU/driver and renderer versions.
Then check:

1. The extracted package opens without a development checkout or preinstalled Python.
2. Setup explains required components, asks before installation, and shows progress and the dependency command.
3. Python and Ren'Py downloads pass their pinned checksum checks; the Python installer passes its signature check.
4. Components install under SceneLight's application-data folder without administrator access, PATH changes, services or startup tasks.
5. Static scanning preserves the selected source. Renderer-backed discovery runs in a working copy and completes preflight before long analysis.
6. A broken renderer produces a clear error and leaves the source unchanged. With virtual graphics disabled, expect a capability check, not CPU-only live rendering.
7. Both **Add to this game** and **Create separate copy** work and report their destination correctly.
8. Preview opens and renders Original, Relit and Split. Check static and video backgrounds, animated sprites and calibration export.
9. The game opens through its normal executable. Check movement, expression changes, multiple characters, transitions and save/load.
10. Removal validates ownership and preserves original files and saves. Compare complete source hashes for the separate-copy workflow.
11. Close the guest and discard its temporary environments, logs and saves. The host input folder must remain unchanged.

Test developer embedding separately. Modify an owned file and add an unknown file
to confirm removal refuses both cases; restore the fixture, then verify clean
unembedding. Check the legacy launcher's backup and restoration where applicable.

## Evidence

Retain package checksums, dependency audit output, source hashes, renderer details,
timings and original-fixture screenshots. Record failed and skipped checks.
Review logs for private paths or other sensitive data before sharing them.

[Validation matrix](../VALIDATION.md) · [Release checklist](RELEASING.md)
