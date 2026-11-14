# Changelog

## 1.1.0

- Improve capture of layered sprites and transformed image parts on Ren’Py 7 and 8.
- Reuse unchanged captures and lighting maps when updating a project. Check added,
  edited and replaced artwork without copying the whole cache each time.
- Add live updates for mod development, including previews for supported layered
  sprites and an in-game status while lighting is being prepared.
- Show installation stages, individual steps, asset counts and time estimates.
- Recover interrupted updates before checking the existing installation.
- Resume completed capture work and report missing or unsupported forms without
  stopping the rest of the scan.
- Expand diagnostic reports with capture timings, worker failures and update
  details. Redact user-directory names from exported logs.

## 1.0.0

Initial release with automatic sprite lighting, animated backgrounds, lighting
groups, glow, the Preview & Calibrator, and an optional in-game inspector.
Includes the mod API, online and offline Windows setup, and a compatibility
runtime for supported older games.

[Downloads](https://github.com/RageAdo-dev/SceneLight/releases/latest) · [Compatibility](docs/COMPATIBILITY.md) · [MIT license](LICENSE)
