# Changelog

## 1.1.0

Character capture is rebuilt. Sprites are drawn by the game's own renderer and
read back with their alpha channel, instead of going through Ren'Py's software
compositor. The software path stopped the engine on any layered sprite that
carried a scaled or rotated layer, which is most of them once wings, glasses or
effects are involved. Those forms now capture normally.

### Capture

- Draw each form through the renderer and read it back as RGBA, keeping the
  alpha channel that lighting needs.
- On Ren'Py 7, which has no offscreen screenshot, draw every form twice, over
  black and over white, and rebuild it on the host. Python 2 games no longer
  need the software compositor.
- Resume from completed forms after a crash or a cancelled run, including
  Python 2 captures whose pairs are already on disk.
- Fit a form that is larger than the driver's framebuffer into it instead of
  clipping it. `SCENELIGHT_MAX_CAPTURE_SIZE` overrides the limit.
- Free each form's render tree once its pixels are written.

### Setup

- Write `capture-report.json` and `capture-stall.json` beside every capture.
  The report records the engine, renderer, per-form timings, stage totals and
  peak memory; the stall record names the form and stage a run stopped on.
- Report the capture and normalization phases separately so a slow scan says
  which one it was.
- Name the reason a capture batch saved nothing instead of failing generically.

### Fixes

- Skip a sprite form that stops the renderer twice instead of failing the whole
  character inventory.
- Keep every preview pointing at the capture that survived deduplication,
  including character candidates.
- Recognize JSON mappings on Ren'Py 7, whose store replaces `dict`. The crash
  journal was unreadable there, so failed forms were retried on every run.
- Stop retrying character forms with the software renderer, which could only
  fail a second time.
- Use the Ren'Py SDK that matches a project's engine instead of scanning newer
  games with the bundled runtime.

## 1.0.0

### Lighting

- Background lighting for Ren'Py sprites, including animated backgrounds.
- Lighting groups for sprites that share a pose or position.
- Sprite glow, selected-color glow and light cast onto nearby characters.
- Rules for backgrounds, scenes, characters and individual images.
- Bright-scene detail preservation and smooth colored-light transitions.

### Preview and inspector

- Draggable placement, lighting and glow controls, with Original/Split comparisons.
- Settings review before export, and PNG, GIF or video output at up to 4K.
- Optional **Shift+F9** inspector with sliders, exact edits, rule sources and reports.

### Installation

- Online setup and offline Windows package.
- Install in place or create a separate playable copy.
- Character selection, and project change detection while Setup stays open.
- Updates reuse compatible prepared data and preserve settings and saves.
- Interrupted captures resume from completed work; unsupported assets are
  reported and skipped.
- Bundled Ren'Py 7.7.1 compatibility runtime for supported older games.

### Fixes

- Finish stopping background operations when Setup closes.
- Recover interrupted installs, full updates and removals without losing the
  previous installation.
- Reject linked paths in installation records before changing game files.
- Fix GLES lighting precision and release GPU resources when the Preview is
  resized.
- Keep low-opacity sprites intact during contrast analysis.
- Use the same project settings in Preview and installation.
- Preserve the current composition after failed or canceled media opens and
  exports, with progress and cancellation for large media opens.
- Redact structured credentials from diagnostic exports.
- Sign launchers before packaging and verify their bytes and signatures in each
  distribution.

[Downloads](https://github.com/RageAdo-dev/SceneLight/releases) · [Compatibility](docs/COMPATIBILITY.md) · [MIT license](LICENSE)
