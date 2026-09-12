# Changelog

## 1.0.0 (unreleased)

### Lighting and playback

- Background lighting follows character movement, scene changes and supported animations.
- Supported movies prepare lighting for every frame once, then reuse it during playback.
- Live analysis handles backgrounds changed by code or visual effects.
- Surface maps retain fine painted detail while smoothing artificial silhouette ridges.
- Directional color blending no longer turns small surface slopes into sharp seams.
- Compatible renderers reuse constant scene samples in the vertex shader to reduce draw time.
- Transition snapshots keep their lighting and release their graphics textures correctly.

### Setup and author tools

- One launcher opens Setup and Preview & Calibrator.
- Install in place or create a separate playable copy. Review character tags before installation.
- Updates reuse valid analysis, rebuild changed inputs and preserve recovery data.
- Large captures resume after interruption and limit workers according to available memory.
- Ren'Py 6 games can use the verified 7.7.1 compatibility runtime.
- Authors can control lighting by project, background, scene, character or image.
- Rain and glitch effects are available through the author API; the player effects panel is disabled.

### Documentation

- Shorter installation and author guides, with rendered surface-map examples.
- A lossless 60 fps movement demo.

Form-map version 5 requires rebuilding older maps through **Update SceneLight**.

[Development history](docs/history/development-changelog.md) · [Compatibility and validation](docs/BETA_VALIDATION.md)
