# Changelog

## 1.0.1

- Finish stopping background operations when Setup closes.
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

## 1.0.0

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
