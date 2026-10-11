# Validation

For maintainers. Run the checks relevant to the changed behavior and record failures
or skipped coverage. Keep fixture assets and machine-specific reports outside the repository.

## Integration matrix

| Target | Required checks |
| --- | --- |
| Synthetic Ren'Py project | Install, compile, launch and verify lighting changes as a character moves |
| Local DDLC fixture | Discover character tags without name presets; check movement and transitions |
| Independent mod | Install in a disposable copy, render a controlled scene and preserve the original source |
| Preview & Calibrator | Compile the production shader; compare Relit, Original and Split; round-trip calibration |

Use both legacy and current Ren'Py generations when a change affects them.
Renderer changes need image comparisons as well as numerical and timing checks.

## Native update and save rehearsal (Windows)

`tools/validate_native_updates.py` uses the extracted package's actual Python/CLI
and the supplied Ren'Py executable; capture and rendering are not mocked. Supply
`--package`, `--sdk`, a new `--output` directory and `--mode player` or `developer`.
Run both modes against supported Ren'Py versions before a release affecting updates.
`--python` can explicitly select a development interpreter while investigating a fix.

It creates a disposable project with static and layered sprites, custom lighting,
an excluded character, and a real save at a hard gameplay checkpoint. It checks an
unchanged update, adds one sprite/background, verifies cache reuse and untouched
maps/settings/save bytes, loads the earlier save, and checks that playing does not
cause another rebuild. `RESULT.json` records measurements and coverage. These are
small-fixture timings, not estimates for a large mod.

Keep native source-backed `.rpyc` files during updates: Ren'Py uses their prior AST
to preserve save statement identities. Analyzer-created bytecode must not replace
the playback copy. A save file surviving byte-for-byte is not sufficient proof;
the loaded gameplay state and resume point must also be checked.

## Package checks

For file-transfer/verification changes, test same-volume transfer and cross-volume
copy, checksum reuse, edits with restored timestamps, missing prepared files,
concurrent ownership changes, an active Windows writer, unsupported change
identities, hardlink isolation, launcher recovery and failed manifest/swap rollback.
Audit installed bytes independently of cached verification stamps. Benchmark
old/current implementations with equal file counts and sizes, separating capture
and analysis from finalization. Repeat the native update/save rehearsal above in
player and developer modes on Ren'Py 7 and 8.

For bright-scene rendering, compare unchanged source art, zero strength and normal
strength on bright neutral/warm/cool scenes, a snowy photograph, interiors, lake,
forest and colored lamps. Check painted white/gray detail, saturation, automatic
gain, deliberate exposure and independent glow. Render the same source images and
placements in Preview and native Ren'Py 7/8. A shader-only update must retain
existing map bytes and modification times.

For inspector numeric controls, verify slider dragging across refreshes, exact
Edit values, Reset, negative exposure/color influence, glow strength up to 10,
master strength and correct sprite/alias scope in Ren'Py 7 and 8. Authored rules
and saved player preferences must remain unchanged. Confirm the recording button
is absent, with report export and Shift+F9 still available.

For settings-only updates, exercise a newly created selection profile, a formatting-only
edit, lighting and per-scene calibration, excluded and re-enabled prepared families,
and a root `scenelight.json` edit. Require zero capture/analysis calls and unchanged
map bytes/mtime. Unprepared families, changed art, changed asset-discovery inputs
and missing compatibility evidence must still require analysis. Verify atomic
rollback and an external config edit during verification.

For the optional in-game inspector, test include → exclude → include in native
Ren'Py 7 and 8. Exclusion must remove the source/helper and compiled `.rpyc`, the
hotkey must not register, the API must safely do nothing, and rendered lighting
must stay identical. Test persisted choices across both fast and full updates,
new-project choices, edited-file refusal and rollback after a failed removal.

For Preview controls, open calibration while dragging the sprite and verify that
presets, strength, the editor and the review page stay synchronized. Check a
small window and all six visible adjustment categories; navigation must stay
visible while scrolling. Exercise glow strength to 10, halo, tint and independent
color rules; compare the live render with direct settings. Wheel scrolling must
not edit a value under the pointer. Opening either save/export action must
not write a file. Compare the final file byte-for-byte with File preview, retain
existing scene/sprite rules, and exercise a changed, invalid and unwritable
destination. Loaded precision must survive edits to unrelated controls. Keep
large config reads out of the live edit path while the review page is hidden.

1. Run the commands in [Contributing](../CONTRIBUTING.md), including the dependency audit.
2. Install the built archive into a temporary Python environment.
3. Scan, install, verify and remove a synthetic project. Compare source hashes before and after.
4. Redirect `SCENELIGHT_COMPONENT_ROOT` into the test directory and confirm dependencies do not change global Python.
5. Inspect archives for private game data, runtime caches, local paths and debug output. Licensed documentation figures must retain their credits and notices.
6. Verify checksums and exercise launcher paths containing spaces, percent signs and environment-variable-like text.
7. Remove the temporary component environment after testing. Record cleanup or verification steps that could not complete.

Before public distribution, complete the [fresh Windows checks](FRESH_MACHINE_VALIDATION.md).
Keep physical GPU validation separate from virtual-machine compatibility checks.
Audit the exact base, Preview, packaging and optional CUDA dependency sets.

## Optional effects

Check disabled-effect image parity, enabled rain/glitch rendering, scene and
character scopes, movement, transitions, save/load, rollback and skip behavior.
Verify that the disabled player panel and hotkey stay absent. Custom packs need
separate checks against their intended sprites and renderer.

Keep private fixtures, saves and captures outside the repository. Record engine,
GPU, source identity, method and limitations alongside each result.
