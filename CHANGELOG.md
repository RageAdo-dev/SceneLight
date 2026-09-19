# Changelog

## 1.0.0-beta

### Lighting and playback

- Whole-image sprite aliases share automatic exposure instead of repeatedly darkening the same character. Authored grades, per-image controls, highlights and frozen transitions retain their own lighting behavior.
- Automatic color separation no longer treats every broad patch of foliage or colored wall as an additional lamp. Environmental tint and bounce remain active, compact colored lights retain separation, and explicit artistic color separation is unchanged.
- Capture now follows pose and expression changes in compiled dialogue, including translated dialogue and temporary speaking attributes. Old capture plans are rebuilt so those states receive matching surface maps.
- Sprite replacements under a running animation now refresh their surface-map bindings instead of retaining the previous pose. Saved sprites rebind to the current inventory after loading. Existing lighting depth and grading are preserved; unmapped expressions cannot borrow another pose's geometry or cast distant shadows from painted colors.
- Sprite sampling now uses the character canvas dimensions instead of a renderer-assigned texture slot. This fixes displaced facial and clothing shading on layered sprites while keeping lighting enabled, including sprites without prepared surface maps.
- Surface direction is consistent across sprite resolutions, with bounded relief at painted color boundaries.
- Side lights produce a stronger difference between lit and shaded surfaces.
- Overlapping light regions prevent jumps when bright areas split or merge.
- Dark scenes retain their darkness; compact lights still contribute energy and real flashes remain immediate.
- Background lighting follows character movement, scene changes and supported animations.
- Supported movies prepare lighting for every frame once, then reuse it during playback.
- Live analysis handles backgrounds changed by code or visual effects.
- Surface maps retain fine painted detail while smoothing artificial silhouette ridges.
- Painted shading bands are read at form scale, so an artist's own band and line
  boundaries no longer appear as ridges across a face, sleeve or cardigan.
- Directional color blending no longer turns small surface slopes into sharp seams.
- Animated lighting blends between source estimates instead of switching at detection cutoffs.
- Fading colored lights retain their measured direction and fade out gradually.
- Preview no longer applies a second exposure adjustment to fully analyzed video frames.
- Prepared movies include the exact color conversions used by legacy and current decoders.
- Compatible renderers reuse constant scene samples in the vertex shader to reduce draw time.
- Transition snapshots keep their lighting and release their graphics textures correctly.
- Live analysis runs in about a quarter less time on an older Radeon laptop GPU, with fewer GPU passes and smaller analysis buffers.

### Setup and author tools

- Setup now supplies the correct native icon sizes to Windows, fixing a blurry taskbar icon caused by stretching the smallest image. The approved S artwork and gradient are unchanged.
- SceneLight now has its own warm-to-cyan S icon in the Windows executable, Setup, Preview, and taskbar instead of an empty icon.
- Game sprite lighting maps now use full source resolution, matching Preview. Both paths use the same transparent-canvas composition, preventing hidden RGB differences. Updating an older installation rebuilds reduced-resolution maps; analysis concurrency accounts for large sprites without reducing detail.
- Setup detects actual NVIDIA CUDA devices in the background, checks the selected runtime or compatible CUDA 12 tools, and names the GPU in its recommendation. Optional acceleration can be declined to continue on CPU; prompts show the actual installation directory.
- The game picker resolves a single game inside nested extraction folders. Multiple matches require an explicit choice, and discovery stays bounded without following linked directories. SDK paths retain their separate behavior.
- Preview treats MPO/JPEG auxiliary images (including HDR gain maps) and TIFF pages as still-image data instead of animation frames. Existing mistaken animation caches are ignored; true GIF, APNG, WebP and other timed formats retain playback.
- Rounded controls use larger image tiles to avoid thousands of native paint operations per button. Bundled menus check their own package environment directly instead of spawning another interpreter. Preview opens without requiring optional CUDA analysis components.
- Setup uses rounded buttons and tabs with clear hover, selection and keyboard focus states. System and Advanced now share the same verified component count, including the runtime and counting shared package bindings once.
- Windows releases offer a small online installer alongside the complete offline ZIP. Online setup downloads the exact verified offline payload into SceneLight's own cache and reuses it on later launches without modifying system Python.
- SceneLight.exe opens Setup and Preview with a bundled Windows runtime.
- SceneLight.exe and the bundled game launcher report the product name, version,
  publisher and copyright in Windows file properties.
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

Form-map version 8 requires rebuilding older maps through **Update SceneLight**.
This update also refreshes scene lighting and prepared movies.

[Development history](docs/history/development-changelog.md) · [Compatibility and validation](docs/BETA_VALIDATION.md)
