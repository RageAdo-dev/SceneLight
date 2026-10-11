# Changelog

## 1.1.0

- Added lighting groups: shared background sampling and settings for separate sprites, with moving, member-based or fixed anchors. Per-sprite glow and disabled-member rules remain available.
- Show group membership and shared position in the in-game inspector. Groups survive save/load and rollback, and can be cleared during a scene.
- Setup detects source changes while it stays open, invalidates stale scans and offers updates for both direct installs and separate player copies. Saves and generated caches do not trigger this check.
- Updated the API guide, examples, download page and release instructions. Simplified comments and documentation while retaining technical explanations.

## 1.0.0-beta

### Lighting and playback

- Reduced washed-out lighting on bright backgrounds. Automatic positive exposure now has a soft limit for already exposed artwork, neutral backgrounds no longer act as a desaturation filter, and highlight protection preserves existing painted detail while compressing newly added highlights. Preview at zero strength preserves the original artwork; explicit glow remains independent. Preview and the game share the correction without changing cached lighting-map formats.

- Added live numeric sliders to the in-game inspector while retaining exact-value Edit and Reset. Master strength also has a slider; signed color influence and exposure retain their full ranges. Removed the Record 10 seconds button.

- Made Preview's lighting and glow controls visible on its default Adjust page. Persistent category buttons replace the hidden dropdown; Sprite glow has strength/halo sliders and numeric inputs, Color glow has a clearer empty state, and Cast light is a separate page. Compact spacing fits the primary glow controls at 1280×720. Scrolling the panel no longer changes numeric or slider values.

- Lighting/profile edits and choices among already prepared character families now update runtime settings without recapturing backgrounds or rebuilding maps. The updater compares asset-discovery inputs separately and still analyzes changed sources, newly requested families, or unknown legacy inputs. The main update window shows the reason for its chosen path.
- Shortened the inspector option description to its enabled/disabled state and restart instruction.

- Added a per-project Setup option to include or exclude the in-game inspector. Apply changes only its optional source/helper/compiled files, retains asset maps, and persists across updates. Excluded games have no inspector screen or Shift+F9 binding. Interrupted changes use the existing recovery journal.

- Moved Preview calibration into the right sidebar with live controls and uninterrupted sprite dragging. Save/export now opens a review page showing every current value, the destination and exact output before an explicit write. Existing scene/sprite rules are preserved; stale or failed writes cannot silently overwrite the reviewed file. Editing one control preserves precision in untouched settings.

- Preserve source-backed Ren'Py bytecode and its statement identities in player copies across updates. Raw analysis snapshots/restores the prior playback bytecode, including interrupted-run recovery, so analyzer compilation cannot move existing saves to an earlier checkpoint.

- Detect newly reported Ren'Py script parse errors immediately, retain the file/line in support reports, and skip further graphics-backend retries for that runtime while allowing a different compatible engine to be tried.

- In-game support exports now bundle a readable report, conflict checks, exact runtime identity, engine logs, reproduction notes and a ten-second settings recording. Screenshots are optional. Activity preserves complete inspector JSON instead of truncating it into an invalid tail.
- Compatible runtime updates now replace only changed code after source/integrity checks, leaving existing maps in place. Updates use a recovery journal and a per-project writer lock. Background scene fields join transport/form caches; update decisions and cache counts are reported. Authored Python and data files also invalidate visual inventories.

- Added an in-game lighting inspector (Shift+F9) with effective values, override chains, authored script locations, master strength, nested lighting passes, temporary test edits, reset and diagnostic export. New games and loads clear test edits; story rules and saved player preferences remain unchanged.
- Added selective background-light color adjustment through a hex target, signed influence and a soft hue range. The game API and Preview share the controls; the default amount is zero. Activity support exports include the inspector report.

- Setup now shows finalization stages after sprite maps reach 100%: worker shutdown, index/report writing, background-video preparation, cache copying, runtime copying and verification, and workspace cleanup. Large copies/hashes report file counts; video preparation reports the current video and frame counts. Otherwise the active stage and elapsed time remain visible. Activity records the same live stages, refreshes while visible, follows new entries at the bottom, and preserves the view when reading older entries.
- An active installation/update no longer displays the previous installation as "installed and ready"; it explicitly asks users to wait for completion.

- Missing, unsupported, or unreadable sprite assets now skip individually during capture, including parallel batches, while valid assets continue through installation. Completed skips are reusable on retry and repaired source assets are rediscovered on update.
- Activity and support exports now include skipped asset names and reasons, with captured/skipped totals. Developer install/update also show the skip count. Unreported worker omissions and failures writing output remain visible errors.

- Smoothed colored-light handovers, including lights close to a character. Preserved the forward light direction and removed an over-sharpening blend; Preview and gameplay share the correction.
- Interrupted capture retains completed worker batches even when available memory changes the worker count. Clean memory-saving restarts no longer consume the crash retry budget; unresolved errors remain visible and progress stays available for retry.

- Restored the simple single-sprite Preview controls. Removed the extra library/scene toolbar and character list, preserved the right-side placement and lighting controls, and fixed drag coordinates being rounded back onto a percentage grid. Per-target controls remain in the mod API.
- Sprite glow and color-rule glow strength now support 0–10 in Preview, profiles, and the mod API. Other lighting and halo ranges remain unchanged.
- Added independent color-selective glow rules per sprite. Match nearby artwork shades with range and softness controls, adjust each rule's strength and halo spread, and retain the rules in saved scenes, library presets, profiles, and author exports.
- Init-authored lighting rules now seed new games correctly and recover from older untouched empty save states. Save/load keeps intentional runtime overrides and resets.
- Character exclusions remain effective during gameplay, including when a mod registers the same tag during initialization.

- Removed the fixed floor-shadow oval previously drawn into transparent sprite pixels. Interior lighting and self-shading remain active.
- Added independent per-image/tag glow and emitted-light controls. Effect sprites can glow, illuminate nearby selected characters, or do both; defaults remain off. Preview calibration and the Developer guide include the controls. Rain, glitch, and custom effect packs remain deferred.

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

- Windows checksum reuse now requires a file-journal sequence and exclusive access. This detects rapid writes with identical timestamps and avoids reused checksums while another handle could coalesce journal records. Unsupported journals and sharing conflicts fall back to byte reads. Earlier timestamp-only verification stamps are invalidated.

- Large installs transfer a private prepared runtime directly when it is on the same volume, avoiding another full copy. Verification reuses checksums only when the filesystem confirms the same file identity and change time; modified files, older records and unsupported filesystems still require byte reads. Verification uses bounded workers, retains a final ownership check, and returns prepared files on failed publication. Source edits made after analysis remain pending for the next update.
- Removed a duplicate update ownership pass and an extra source scan during finalization. Transfer checks and prepared-file verification stay visible in Activity. Full file reads stay sequential to avoid competing disk seeks on hard drives; cached identity checks use bounded concurrency. Large-file benchmarks measure finalization separately from asset capture and analysis.

- Character selection can be reopened and refreshed for installed projects. Automatic inclusion of newly detected characters defaults on, with persistent exclusions; disabling it keeps a fixed selection. Asset changes are prepared by Scan/Update in both player and developer workflows.

- Added persistent support sessions with searchable stage/error views, separate retained console output, capture-worker context, runtime sprite-binding evidence, and exportable support ZIPs. Reports include a readable HTML browser and omit artwork/saves; common secrets and personal home paths are redacted.
- Added an artwork-to-custom-color tint slider. Preview retains lighting profiles and config exports; per-image lighting, glow, and emitted light are available through the mod API.

- Preview calibration tabs now use readable dark backgrounds, bright labels, and distinct selected, hover, and keyboard-focus states.
- Preview separates sprite glow from cast-light settings. A custom glow color picker changes the visible sprite and halo; an explicit hint explains when glow is off. Profiles and per-image author rules retain independent glow and cast-light colors.

- Isolated capture workers' temporary directories so mod single-instance guards do not collide through a shared SDK launcher. Blocked workers finish sequentially from checkpoints when a guard still prevents parallel capture. Persistent conflicts now identify the actual cause instead of retrying graphics backends.

- Settings → Advanced now includes an offline Developer guide with searchable commands, lighting controls, and copyable Ren'Py examples. Each example explains where to put it, with no project selection or extra download required. Effects remain deferred until after launch.
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
- Rain, glitch, and custom effect packs are reserved for a post-launch update.

### Documentation

- Shorter installation and author guides, with rendered surface-map examples.
- A lossless 60 fps movement demo.

Form-map version 8 requires rebuilding older maps through **Update SceneLight**.
This update also refreshes scene lighting and prepared movies.

[Development history](docs/history/development-changelog.md) · [Compatibility and validation](docs/BETA_VALIDATION.md)
