# Changelog

## 1.0.11

### Fixes

- Name every character capture by its form digest alone, so saved pixels and layered-composite jobs are found again when a later plan spells the same form differently.

## 1.0.10

### Fixes

- List the sprite forms that were skipped when the character review finishes, so a missing lighting family is named in Activity and the support report.

## 1.0.9

### Fixes

- Keep a sprite form whose pixels were written but whose checkpoint marker was lost when the renderer stopped, instead of rendering it again.
- Record how many forms restored, recovered and were missing, so a stopped capture explains itself in one line.

## 1.0.8

### Fixes

- Find saved sprite pixels by the form's stable digest instead of its planned spelling, so a resumed process keeps every finished form instead of re-rendering the same ones and stopping again.

## 1.0.7

### Fixes

- Start a fresh capture cache when the resolver changes, and delete the superseded review caches automatically, so an upgrade needs no manual cleanup.

## 1.0.6

### Fixes

- Fit every layered character form into the capture surface, so teeth, wing and charge layers that use their own offsets keep their lighting instead of stopping the renderer.

## 1.0.5

### Fixes

- Fit layered images that place zoomed children outside their canvas into the capture surface, so those wings and overlays keep their lighting instead of stopping the renderer.

## 1.0.4

### Fixes

- Skip a sprite form after a single renderer stop instead of retrying it, so a family of layered images that crashes Ren'Py is left out instead of ending the scan.
- Stop counting a skipped form against the renderer, which previously abandoned the backend two crashes into a scan.

## 1.0.3

### Fixes

- Retry a component install with the newest compatible versions when the running Python has no wheel for a pinned one, instead of failing on a missing C compiler.
- Name the package and the Python version in the setup failure message and the activity log.

## 1.0.2

### Fixes

- Update Pillow to 13.0.0, clearing the published advisories that now block a signed build.
- Require Python 3.11 or newer for source installs.

## 1.0.1

### Fixes

- Use the Ren'Py SDK that matches the version a project was built with instead of quietly scanning newer games with the bundled Ren'Py 7 runtime.
- Keep completed sprite forms when a renderer stops mid-capture, and name the form it stopped on in the support report.
- Record each capture step with its image sources, output path and memory use so a stopped renderer can be diagnosed from the support export.
- Skip a sprite form that stops the renderer twice instead of failing the whole character inventory.
- Name the bundled Ren'Py 7 runtime as such instead of reporting it as the selected Ren'Py SDK.

## 1.0.0

### Fixes

- Finish stopping background operations when Setup closes.
- Stop the active operation on close even when an earlier cancellation is still finishing.
- Prevent simultaneous projects from interrupting a shared compatibility-runtime download.
- Keep shared analysis memory tracked until its owner finishes, including interrupted Linux workers.

- Recover interrupted installs, full updates and removals without losing the previous installation.
- Reject linked paths in installation records before changing game files.
- Fix GLES lighting precision and release GPU resources when the Preview is resized.
- Keep low-opacity sprites intact during contrast analysis.
- Use the same project settings in Preview and installation; review both files when an export also updates a saved profile.
- Preserve the current composition after failed or canceled media opens and exports.
- Add progress and cancellation for large media opens, and prevent concurrent cache writes.
- Redact structured credentials from diagnostic exports.
- Sign launchers before packaging and verify their bytes and signatures in each distribution.
- Correct installation, settings, effects and in-app help instructions.

### Lighting

- Background lighting for Ren’Py sprites, including animated backgrounds.
- Lighting groups for sprites that share a pose or position.
- Sprite glow, selected-color glow and light cast onto nearby characters.
- Rules for backgrounds, scenes, characters and individual images.
- Bright-scene detail preservation and smooth colored-light transitions.

### Preview and inspector

- Draggable placement, lighting and glow controls, with Original/Split comparisons.
- Settings review before export and PNG, GIF or video output at up to 4K.
- Optional **Shift+F9** inspector with sliders, exact edits, rule sources and reports.

### Installation

- Online setup and offline Windows package.
- Install in place or create a separate playable copy.
- Character selection and project change detection while Setup stays open.
- Updates reuse compatible prepared data and preserve settings and saves.
- Interrupted captures resume from completed work; unsupported assets are reported and skipped.
- Bundled Ren’Py 7.7.1 compatibility runtime for supported older games.

[Downloads](https://github.com/RageAdo-dev/SceneLight/releases) · [Compatibility](docs/COMPATIBILITY.md)
