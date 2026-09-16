# Changelog

## 1.0.0 (unreleased)

### Lighting and playback

- Surface direction is consistent across sprite resolutions, with bounded relief at painted color boundaries.
- Side lights produce a stronger difference between lit and shaded surfaces.
- Overlapping light regions prevent jumps when bright areas split or merge.
- Dark scenes retain their darkness; compact lights still contribute energy and real flashes remain immediate.
- Background lighting follows character movement, scene changes and supported animations.
- Supported movies prepare lighting for every frame once, then reuse it during playback.
- Live analysis handles backgrounds changed by code or visual effects.
- Surface maps retain fine painted detail while smoothing artificial silhouette ridges.
- Directional color blending no longer turns small surface slopes into sharp seams.
- Animated lighting blends between source estimates instead of switching at detection cutoffs.
- Fading colored lights retain their measured direction and fade out gradually.
- Preview no longer applies a second exposure adjustment to fully analyzed video frames.
- Prepared movies include the exact color conversions used by legacy and current decoders.
- Compatible renderers reuse constant scene samples in the vertex shader to reduce draw time.
- Transition snapshots keep their lighting and release their graphics textures correctly.
- Live analysis runs in about a quarter less time on an older Radeon laptop GPU, with fewer GPU passes and smaller analysis buffers.

### Setup and author tools

- SceneLight.exe opens Setup and Preview with a bundled Windows runtime.
- SceneLight.exe reports the product name and version in Windows file properties.
- Preview exports at 720p, 1080p or 4K, with settings recorded beside the file.
- GIF export retains one frame at a time; short audio tracks no longer truncate video exports.
- Install in place or create a separate playable copy. Review character tags before installation.
- Updates reuse valid analysis, rebuild changed inputs and preserve recovery data.
- Large captures resume after interruption and limit workers according to available memory.
- The release workflow signs both launchers when signing credentials are configured, and fails the build on an invalid signature.
- Ren'Py 6 games can use the verified 7.7.1 compatibility runtime.
- Authors can control lighting by project, background, scene, character or image.
- Rain and glitch effects are available through the author API; the player effects panel is disabled.

### Documentation

- Shorter installation and author guides, with rendered surface-map examples.
- A lossless 60 fps movement demo.

Form-map version 6 requires rebuilding older maps through **Update SceneLight**.
This update also refreshes scene lighting and prepared movies.

[Development history](docs/history/development-changelog.md) · [Compatibility and validation](docs/BETA_VALIDATION.md)
