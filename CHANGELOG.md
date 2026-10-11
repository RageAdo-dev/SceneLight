# Changelog

## 1.1.1

- Updated Python dependencies and GitHub Actions. Fixed Setup checking for outdated component versions after a dependency update.
- Shortened the guides and removed obsolete development reports from the current documentation.
- Tagged releases upload directly to GitHub Releases. Optional Actions downloads expire after one day.

## 1.1.0

- Added lighting groups so separate sprites can share settings and a lighting position. Groups support moving or fixed anchors, save/load, and rollback.
- Added group details to the in-game inspector.
- Setup now detects project edits while it stays open and offers **Check changed assets → Update SceneLight**. Restart the game after updating.

## 1.0.0-beta

### Lighting

- Automatic background lighting, full-resolution sprite surface maps, and animated-background support.
- Reduced bright-scene washout and smoothed transitions between colored lights.
- Fixed stale surface maps after pose changes and resource handling during window resizing.
- Added sprite glow, selected-color glow, emitted light, and controls for background color influence.
- Added rules for backgrounds, scenes, characters and individual images.

### Preview and diagnostics

- Preview with draggable placement, lighting and glow controls, and Original/Split comparisons.
- Reviewed profile/config exports and PNG, GIF or video output at up to 4K.
- Optional **Shift+F9** inspector with sliders, exact edits, rule sources and report export.
- Persistent Activity logs with progress, skipped assets and support reports.

### Installation

- Bundled Windows app; install in place or create a separate playable copy.
- Character selection with persistent exclusions and optional inclusion of new characters.
- Updates reuse compatible prepared data and preserve settings and saves.
- Interrupted captures resume from completed work; missing or unsupported assets are skipped individually.
- Ren’Py 7.7.1 compatibility runtime for supported older games.

[Downloads](https://github.com/RageAdo-dev/SceneLight/releases) · [Compatibility](docs/COMPATIBILITY.md)
