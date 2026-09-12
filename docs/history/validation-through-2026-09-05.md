# SceneLight validation results

> Historical development record. Versions, measurements and remaining work below
> describe that revision, not the current release. Start with the
> [current documentation](../README.md) and [compatibility notes](../BETA_VALIDATION.md).

This file retains the historical validation record through 2026-09-05.
For the current private beta's test counts, package checks, native playback and
low-end memory results, see [Beta validation](../BETA_VALIDATION.md).

## Animated-background correction

The earlier background smoke route did not prove character-lighting synchronization.
An actual-game audit reproduced frozen lighting and identified the Ren'Py
RevertableDict/builtin-dict mismatch, interaction-only clock, and guessed loop
period. See [Temporal validation](../TEMPORAL_VALIDATION.md) for the evidence,
reproduction route, and explicit compatibility limits.

The corrected Copy (2) runs had zero mismatches across 2,128 compared observations,
covering ATL, legacy Animation/GIF frames, DynamicDisplayable, a looping movie,
and a static classroom. The full Python suite passed: 351 tests. Ruff and the
isolated wheel/source build passed. An initial `--no-isolation` build failed
because the machine's existing setuptools was too old; the normal isolated
build installed the project's pinned backend and succeeded without changing
package metadata or weakening checks.

These results supersede earlier temporal smoke-test claims, not the separately
documented lighting-math and static-scene checks below.

The release candidate was exercised as an online Windows package, a Python
package, a reversible in-place attachment, a separate managed copy, and a live
Ren'Py GPU runtime. Game copies and visual captures remain outside this
repository so no game or third-party art is distributed with SceneLight.

## 1.0.0 first public release candidate

- Final visual review exposed a capture-validity defect hidden by the earlier
  count/hash checks: Ren'Py returns a small red `Image '...' not found` Text
  displayable when developer mode is off, and SceneLight had accepted it as
  source art. The retained broken install contained 313 character captures only
  34 pixels tall plus case-only background collisions where the live lowercase
  lookup selected an error strip instead of the real 1280×720 scene. The
  resolver now rejects unresolved `ImageReference` objects, scene identities are
  normalized before analysis, and capture pixel version 2 forces existing
  installations to discard those raw checkpoints.
- The corrected pipeline was rerun through the ordinary separate-copy install
  on a new byte-matched 1,227,165,592-byte, 2,312-file Interaction source. It
  completed with 136 real backgrounds and 7,073 real sprite forms. Every
  installed character capture is 960 or 982 pixels tall, with zero captures
  under 200 pixels, zero 34-pixel placeholders, and zero case-insensitive scene
  duplicates. Independent `verify` passed with four intended character tags,
  zero skipped sprites, and `source_untouched: true`. That capture-validation
  correction did not change the lighting equations or calibration defaults.
- A ten-frame in-engine reproduction then isolated the remaining extreme-color
  defect with SceneLight disabled/enabled pairs. The ordinary classroom control
  stayed close to the authored sprite, but base Sayori on the sunset background
  jumped from red dominance 28.9 to 135.8; the mod's dusk Sayori reached 191.6,
  the two-character dusk pair reached 173.4, and the blue-room pair shifted from
  blue dominance -9.9 to 42.7. This proved that a pre-tinted form amplified the
  failure but was not required to trigger it. The production shader now
  compresses only unusually large environment-chroma spans and preserves the
  sprite's incoming reflectance at the generated luminance. In the identical
  reproduction, the classroom control changed red dominance by 7.3, sunset
  base by 31.6, dusk Sayori by 32.2, the dusk pair by 33.3, and the blue pair by
  28.5 while retaining visible warm/cool scene lighting. All ten comparison
  frames were rendered by the real Ren'Py 8.2 runtime, not an offline mock.
- The final adaptive multi-emitter pass was exercised against a 30-second
  moving RGB ambient-light video in the production OpenGL preview. On a strong
  multicolor frame, automatic separation was pixel-identical to the explicit
  separated-light mode and changed 9.96% of frame pixels from the strict
  aggregate result (maximum channel delta 51), visibly assigning green-cyan
  light to the lower-left hand/body and warm light to the upper form. The same
  automatic path was byte-identical to strict aggregate lighting on the
  ordinary classroom, sunny forest, and night-house controls. Packaged-preview
  video playback advanced on CUDA without shader or media errors. The disposable
  Interaction managed copy then rebuilt all 136 scene transports, reused all
  7,073 sprite forms, matched the local runtime hash, and passed `verify` with
  `source_untouched: true`.
- The final scene-stable transport pass regenerated all 136 Interaction
  backgrounds plus three supplied reference backgrounds directly from the
  current analyzer and production shader. All 29 ordinary controls were
  pixel-identical between adaptive and aggregate color paths; 48 scenes used
  measured spatial color separation. All 138 unique scene caches and all 121
  video-anchor caches contained zero grids with mixed physical/hue-family plane
  identities and zero metadata/layout disagreements.
- The supplied 1,799-frame, 59.94-fps video retained all 121 exact anchors and
  validated all 1,678 interpolated frames. Six genuine layout transitions use
  the primary-key crossfade; the worst mean per-frame transport step fell from
  12.6997 to 6.6974 with zero unsafe transitions. A conservative cold run completed in
  30.053 seconds total, including 16.712 seconds of analysis, versus the retained
  297.935-second baseline.
- A malformed-tail MP4 reported 663 frames through OpenCV but contained only
  661 decodable frames. Preview verified that tail before planning, analyzed
  through frame 660, exported exactly 661 frames at 30 fps in 17.614 seconds,
  and decoded the exported final frame successfully. A separately triggered
  **Cancel export** stopped the real export in 0.583 seconds and left no partial
  MP4.
- The source-only Ren'Py 7.8.7 Backrooms media fixture originally installed only
  5 scene fields because static discovery suppressed runtime inventory after its
  first success. The authoritative runtime pass found all 34 registered scenes.
  Temporal capture then produced 32 samples/12 unique fields for ATL stairs,
  32/4 for its DynamicDisplayable room cycle, and 32/14 for its frame animation.
  Two authored five-second WebM backgrounds each produced 41 independently
  analyzed fields. The final manifest contains 141 derived fields, five temporal
  timelines, all 197 prior character forms, and zero runtime-capture errors.
  The real hidden smoke route completed under the recorded Ren'Py 7.8.7 runtime
  without a script, shader, or renderer error. Static scenes remain single-field.
- A neutral-key/red-practical dungeon reference retained two independent lights
  and changed 14.32% of the frame between aggregate and adaptive rendering.
  The red response was spatially strongest on the source-facing body region,
  while the neutral side stayed anchored to the photographed key. The exact
  previously reported Sayori night form also rendered without its horizontal
  face boundary.
- The final managed Interaction rebuild verified 136 scenes, 7,073 cached exact
  forms, four character families, zero skipped forms, and `source_untouched:
  true`. Preview and installed Ren'Py runtime both used shader SHA-256
  `17a42d66f2a5cf4399433d64e2dc3122f2bf7aa640a327eabbd47f04d04c000f`.
  Six ordinary, night, sunny, mixed-color, and single-practical scenes matched
  Preview to runtime byte-for-byte for irradiance, emitter, environment wrap,
  all 26 transport planes, and every scene metadata field.
- The extracted-package Setup UI was also opened with an empty project field.
  **Open Preview & Calibrator** remained enabled, launched without a `--project`
  argument, and retained the selected-project argument when one was supplied.
  Focused regressions cover both states and the packaged Preview video smoke
  test still advances with temporal CUDA lighting.

- A protected 1.23 GB base of Doki Doki Interaction was never used as an output.
  A byte-matched disposable copy supplied a 50,400-statement, 157-background,
  7,386-form stress case. The original four core-file SHA-256 values remained
  unchanged throughout capture development.
- The prior clean full-surface capture took 291.308 seconds. A literal-name
  checkpoint defect then reproduced a 407.752-second run: five Ren'Py processes
  wrote 16,213 spellings for only 7,343 semantic attribute sets. The fixed
  semantic journal restored all 7,386 planned forms after a renderer exit.
- Adaptive isolated workers, per-worker renderer fallback, and a shared
  component store reduced the valid cold capture to 50.982 seconds with 152
  captured scenes, 7,386 sprite forms, and all 4,647 requested forms resolved.
  Balanced family-local shards, engine/runtime hard-links, crash-only restarts,
  isolated process-tree supervision, and cached output-path validation reduced
  the parallel worker stage to 34.554 seconds. The five reported errors are five
  source-game background declarations whose referenced PNG files are absent.
  The unchanged warm result reloads in 1.036 seconds; before distinct-path
  memoization it took 24.041 seconds.
- The optimized result was compared against the retained native-renderer
  reference by semantic tag plus sorted attribute set. All 7,386 forms matched:
  zero missing, added, changed, or conflicting forms across direct pixels and
  layered component manifests. All 151 stable background captures also matched.
  The only differing scene was `club_day2`, whose source mod deliberately builds
  time-varying bulletin-board content during capture.
- The full unchanged install/update path, including preflight, cache restore,
  derived-map verification, managed-copy transaction, and final verification,
  completed in 25.929 seconds with exit code 0. A subsequent supported `verify`
  reported 152 scenes, 7,386 forms, the four intended character tags, zero
  skipped forms, and `source_untouched: true`.
- A second cold-copy regression used the same untouched 1,227,165,592-byte,
  2,312-file source through the extracted release package. Long Yuri glitch-form
  names reproduced three legacy Windows `MAX_PATH` failures in renderer
  checkpoints, host normalization, and transactional cache preservation. Compact
  same-directory temporary names fixed all three without changing capture or
  lighting pixels. The completed install reported 152 scenes, all 7,386 forms,
  four intended character tags, zero skipped forms, and `source_untouched: true`;
  the independent verifier passed. The source retained zero SceneLight files and
  all four recorded core-file SHA-256 values.
- The same final ZIP was hash-verified on the Windows installation of a 2011
  iMac after the prior SceneLight runtime was quarantined and the normal
  `%LOCALAPPDATA%\SceneLight` root was confirmed absent. Python 3.11.9 was
  bootstrapped by the shipped script and all four core dependencies were
  downloaded into a new private environment with the package cache disabled.
  An initial SSH Session-0 preflight safely rejected all three renderers after
  their 90-second timeouts; the identical command then ran through an
  interactive-only scheduled task in the logged-in console session. The truly
  cold 50,400-statement/152-scene/7,386-form install completed in 2,688.7
  seconds with exit code 0. Independent `verify` and `pip check` passed. The
  remote source remained 2,312 files and 1,227,165,592 bytes with zero
  SceneLight files and all four core hashes unchanged. The temporary task,
  runner, exit marker, and log were removed afterward.
- Static reconstruction was compared against retained native-renderer output on
  a real 960×960 Monika LayeredImage, an offset 978×982 Natsuki LayeredImage,
  and Natsuki's TintMatrix dusk form. Every comparison had zero changed pixels
  and zero changed channels; the performance path did not alter lighting or raw
  sprite pixels.
- A clean Python 3.11.9 environment installed the exact core and Preview pins.
  All 305 tests passed; Ruff, formatting, and the installed SceneLight
  environment's `pip check` passed. Bandit 1.9.4 reported zero medium/high
  findings; its one scoped B310 suppression covers an HTTPS download whose host,
  path, and digest are allowlisted and verified. Pip-audit 2.10.1 found no known
  vulnerability in the complete pinned Preview dependency set.
- The isolated PEP 517 build produced the 1.0.0 wheel and source distribution.
  An archive inspection and install-style resource probe verified that both
  contain the legacy save-compatibility asset as well as the runtime scripts,
  launcher binary, and Preview modules.
- The compact online ZIP contains 48 entries and is 269,939 bytes. Inside its
  single `SceneLight-1.0.0` directory, the only roots are `SceneLight.bat`, the
  player-first README, license/notices, and `_scenelight`. It contains no game
  archives, bytecode, cache directories, private art, user names, or local
  development paths. Direct extraction/import reports SceneLight 1.0.0, all
  Setup/Preview imports pass, and the extracted shipped-content fingerprint is
  identical to the source candidate. It contains zero VFX raster/video assets,
  game archives, bytecode files, or local paths. The ZIP SHA-256 is
  `388c76d4de16d59106aa4d16b0ff746b2a6e67b3e4ce3f559cae344130fb8a0b`.
- A cloned, clean pre-1.0 DDLC direct installation was classified as an internal
  build and refreshed through the real ownership-checked transaction. The final
  runtime has 29 measured backgrounds, 449 sprite forms, exactly the Monika,
  Natsuki, Sayori, and Yuri tags, zero skipped forms, a version-3 form manifest,
  and a clean 1,323-file ownership record. The original 3,383-file source tree
  retained the exact pre-test inventory hash
  `eb7b06d64848fa6a783100a792011b3aab88ccec86b64fe97349dcbbec116748`.
- Compatible reuse was tested separately from cold recovery. With all layers
  cached, an unchanged refresh reused runtime capture, all 29 transports, and
  all 449 form maps in 21.92 seconds. When the external cache was absent, the
  current refresh rebuilt all background transport, reused 446 form
  maps, rebuilt three changed forms, and safely repopulated the external cache;
  under simultaneous workstation load that recovery took 648.48 seconds. The
  slow recovery is recorded rather than presented as the normal cache-hit time.
- The disposable copy launched through its ordinary `DDLC.exe`, selected the
  audited Ren'Py 7.8.7 compatibility runtime, entered real Sayori story
  gameplay, and rendered the supplied residential frame with the character lit
  while the textbox/UI remained unaffected. The transition stall was traced to
  Ren'Py's synchronous framebuffer readback and PNG encoding. The installed
  replacement contains the GPU Flatten transition path and zero
  `screenshot_to_bytes` calls; its replay log has zero traceback, exception, or
  shader-failure matches. Perceptual confirmation of that wipe is the remaining
  manual sign-off for this candidate.

## Internal build 1.8.7 repository and release-package audit

- A fresh Python 3.11.9 environment installed `.[dev,preview]` from the current
  tree. `pip check` reported no broken requirements, and the Preview entry point
  found every declared module without the removed `scikit-image` dependency.
- All 244 tests passed with `DeprecationWarning` promoted to an error. Ruff
  passed, Bandit reported zero medium/high findings and no inline `# nosec`
  suppressions, and `pip-audit` found no known vulnerability in the pinned
  Preview dependency set.
- The wheel and source distribution built as version 1.8.7 from an isolated PEP
  517 environment. The public source root now has one Windows launcher and one
  canonical Ren'Py runtime source; obsolete wrapper BAT files and the duplicate
  runtime mirror are absent.
- The online Windows ZIP has 44 entries and is 226,913 bytes. Its only root
  entries are `SceneLight.bat`, the player-first README, license/notices, and
  `_scenelight`. Extraction and direct source import reported version 1.8.7, and
  the complete Preview module check passed from the archive.
- The archive contains no `.rpa`, bytecode, cache directories, obsolete
  launchers, private game content, usernames, developer-machine paths, or
  references to the removed dependency. Its SHA-256 is
  `8fe1e3d9faafeca4077351946408e7d8b27511ff0c5649ba124bcce450f6a3d9`.

## 1.8.6 exact-analysis performance and gameplay validation

- Static DDLC `im.Composite` forms now export their archive PNG components once
  and are materialized concurrently on the host while Ren'Py continues capture.
  A byte comparison against the retained renderer path matched all 423 safe
  static composites exactly. The remaining five changing results were dynamic
  ATL/random displayables and correctly stayed on the renderer-backed path.
- Host composition reproduces Pygame 1.9's integer SRCALPHA behavior, including
  overlapping antialiased layers. The difficult `natsuki 12a` composite and the
  original RGBA composite matched the established renderer output byte-for-byte;
  no reduced-resolution source capture or approximate lighting model was added.
- Normalization and structural-composition concurrency is adaptive rather than a
  fixed six-worker pool. It selects the minimum of current free-memory capacity,
  logical processors, remaining jobs, and a 16-worker emergency ceiling. Tests
  select one worker with 580 MiB free, four on the four-thread validation laptop,
  and sixteen on a simulated 32-thread/64-GiB workstation.
- On the 8-GB, four-thread Intel HD Graphics 4000 laptop, 423 safe static forms
  were exported in 49.77 seconds and the last pipelined composite completed 60.77
  seconds after the first job appeared. This is approximately one minute on the
  slow validation machine. A high-end local exact-map benchmark processed 96
  forms at 13.17 forms/second, projecting about 33 seconds for 436 forms.
- The form builder now decodes and composites each uncached form once, reuses an
  exact per-worker Lambert response table, and packs the same six logical surface
  channels into two RGB textures. Form-map version 3 retains the original pixel
  hash/dimensions and full 64×64 response while bounding large derived textures
  to a deterministic 512-pixel maximum. On the laptop, 449 forms inventoried and
  428 unique maps completed in 45.48 seconds (44.11 seconds of surface work),
  down from roughly 150 seconds. The generated directory fell again from about
  765 MiB to 234.35 MiB.
- The 512-pixel policy was compared against retained full-size GPU captures, not
  accepted from timing alone. Physical, Separate, Cinematic, hide/re-entry, and
  refreshed-background frames changed only the sprite region. Physical and
  Cinematic remained above 50 dB PSNR; the deliberately amplified Separate mode
  measured 46.25 dB. Visual inspection found no lost form detail, while the
  background and UI stayed byte-identical. Ren'Py's strict screenshot suite then
  passed all five regenerated production baselines. Ren'Py 7.8.7 GL2 separately
  rendered the bounded real-Sayori map through its legacy texture path, produced
  a 676,126-byte capture, and exited with zero traceback, shader-error, or
  exception matches after its isolated test save was reset.
- A truly cold CPU install on the same laptop took 300.54 seconds because exact
  transport for 29 backgrounds remains the dominant 29-scene cost. With scene
  transport cached, the complete preflight/rebuild/verification pass took 69.29
  seconds. These timings are reported separately so the under-one-minute form
  result is not presented as an under-one-minute whole-game cold analysis.
- The final remote build verified as hybrid-GPU with 29 scenes, 449 forms, the
  four DDLC character tags, and zero skipped forms. Its 949-file source copy still
  contained zero SceneLight paths and matched its pre-install file/byte inventory.
- The managed copy was launched through its ordinary `DDLC.exe`, retained DDLC's
  existing save namespace, and entered real story gameplay. Sayori's dissolve,
  expression changes, subsequent dialogue, and the residential scene rendered
  with live relighting on Intel GL2. The completed log contained no traceback,
  exception, or shader failure; the first-run missing shader-cache message was
  followed by successful GL2 initialization and is expected cache creation.
- The final 1.8.6 package was then tested from a genuinely clean laptop state:
  the old SceneLight Python registration was removed with Python's verified
  uninstaller and both owned test trees were recycled. The new small online
  ZIP and untouched 231,593,427-byte DDLC archive matched their source hashes.
  Bootstrap downloaded/verified Python 3.11.9 and completed in 83.89 seconds;
  the isolated four-component setup verified 4/4 imports, and `pip check`
  reported no broken requirements. A stale exact-SceneLight registration was
  also reproduced and restored successfully by the new guarded repair path.
- The final managed copy verified clean with 29 scenes, 434 usable sprite forms,
  four explicit DDLC character tags, and form-map manifest version 3. Its normal
  `DDLC.exe` entered the original `start` and `ch0_main` labels in the laptop's
  logged-in GPU session, captured real residential-story gameplay, and exited
  with zero traceback, shader-error, or exception matches. The original
  `DDLC.exe` retained SHA-256
  `0F9EC1AEDE2A8397C23801200DF606BF03E400FBD09B32F762C33F37A9137085`
  and contained no SceneLight runtime files. Temporary scripts, saves, remote
  control tasks, and the old remote-test tree were removed afterward.
- The latest official Ren'Py 8.5.3 SDK ZIP was downloaded separately and matched
  its published SHA-256
  `ff57648f9c04f27e381c48af6d8e3ee3cdec296bed4d3831f47f09b0a71b505e`.
  A fresh author sandbox passed preflight, capture, analysis, embedding, lint,
  and the native automated-test runner under Python 3.12.7 and Ren'Py 8.5.3.
  The visual reference used the exact real `sayori 1a` composite reconstructed
  from private DDLC archive components; the custom Nova `Character` and real
  `LayeredImage` remained as a separate generic API fixture.
- On an RTX 4090 GL2 renderer, physical and exaggerated separate-light captures
  changed 196,500 pixels inside the fixed Sayori reference region with a mean
  absolute channel difference of 4.01. The background and deliberately unlit UI
  badge remained byte-identical. After hide, dissolve, and re-entry, the settled
  separate-light frame above the dialogue area was byte-identical to its earlier
  state: zero changed pixels and zero maximum channel difference. The Ren'Py test
  passed and the log contained no traceback, exception, or shader failure.
- The user-discovered hybrid was reproduced exactly as separated source colors
  at 0.72 strength, -0.22-stop bias, and 0.92 color adaptation. A production-
  shader matrix then tested eight candidate methods across all 45 retained Studio
  originals with the exact real Sayori form. Physical, separate, the exact
  hybrid, a decomposed hybrid, and three additional filmic/restrained candidates
  all used identical cached transport/form inputs. The exact hybrid had median
  source-detail correlation 0.98352 versus 0.97693 physical and 0.96970 full
  separation, with zero clipping/detail/luminance outliers across the 45 scenes.
- A second difficult-scene matrix used exact real Sayori plus private Natsuki,
  Yuri, and Monika forms. The exact hybrid retained median detail correlation
  0.97840 versus 0.96495 physical, produced zero clipping outliers, and avoided
  the stronger candidates' inconsistent detail loss. No character, palette,
  filename, or scene-specific rule was introduced; reference art and generated
  experiment output remain outside the repository and release.
- The hybrid is now the deliberate `light_mode="cinematic"` preset while the
  established physical default remains unchanged and Separate remains fully
  exaggerated. Preview exposes all three complete looks. Its version-1 profile
  schema now carries the independent lighting strength, older profiles default
  safely to 1.0, and an authored strength replaces rather than compounds that
  saved global value.
- Managed launch bookkeeping now hashes the external Preview profile and treats
  a project-owned `scenelight.json` edit as a visual-source change. Regression
  tests cover a profile created after installation, an unchanged cache hit, and
  a same-size lighting edit that must rebuild before play.
- Direct developer installs now retain a privacy-safe metadata inventory of
  analyzed `game/` visual inputs and root `scenelight.json`. Source-backed Ren'Py
  bytecode, saves/caches, test captures, and the reserved runtime are excluded.
  Unit coverage detects added art and changed profiles, verifies ownership before
  analysis, carries legacy normal-EXE recovery files through refresh, restores
  the previous runtime after a simulated directory-swap failure, and leaves
  source story/art/save files unchanged.
- A real post-install sandbox update added `bg foggy_park` and a new explicit
  `guest` Character/LayeredImage family. The clean existing installation reported
  refresh required before analysis. Transactional refresh completed with two
  measured backgrounds, five resolved forms, three selected character tags,
  zero skipped sprites, and a clean 21-file ownership record. Ren'Py 8.5.3 GL2
  then passed its automated story test and captured the newly added LayeredImage
  using the exact real Sayori source against the new background.
- Preview interaction was stressed with a real 194-frame, 24-fps video upscaled
  to 1920×1080 while temporal transport analysis remained active. Over four
  seconds the video advanced exactly 96 frames while 297 forced placement/repaint
  updates completed. Video decode moved to a dedicated bounded worker; the final
  run had 0.96 ms p95 GPU submission, 26.83 ms conservative forced-present p95,
  no dropped video progression, and zero scene/form-analysis calls from dragging.
- The fresh real-Sayori author sandbox rendered the Cinematic preset through
  Ren'Py 8.5.3 and Ren'Py 7.8.7 GL2. Modern Cinematic versus physical changed
  196,521 sprite-region pixels; the background and UI badge remained byte-
  identical, and a hide/dissolve/re-entry settled frame remained byte-identical.
  The legacy capture visibly matched the same restrained warm/cool result and
  exited without a shader, script, or runtime failure.
- All 243 Pytest tests and Ruff pass. Bandit reports no medium/high findings,
  `pip-audit` reports no known vulnerabilities in the pinned Preview dependency
  set, and the 1.8.6 wheel and source distribution build successfully. The final
  online ZIP has 44 file entries, is 226,858 bytes, imports as version 1.8.6
  directly from the archive, and exposes only `SceneLight.bat`, the player-first
  README, license/notices, and `_scenelight` at its root. Its SHA-256 is
  `e8c972fa43fb63e2c2cf892589842404d72b25ee74f0431a4a03b30cdcd8b8b7`.

## 1.8.5 clean-PC DDLC validation

- The compact online package was copied over SSH to a second Windows computer
  and exercised in its logged-in desktop session. That computer has 8 GB of RAM
  and Intel HD Graphics 4000; it did not use the development checkout.
- The supplied fresh-PC failure was reproduced. Python's OpenSSL defaults had no
  usable CA file, even though Windows trusted the Ren'Py download. SceneLight now
  imports the Windows trusted ROOT store into a verified HTTPS context. A real
  164,677,000-byte Ren'Py 7.8.7 download completed, retained its pinned SHA-256
  verification, and installed successfully. The isolated runtime can also import
  the packaged `scenelight.compatibility` module on that machine.
- Selecting a 949-file stock DDLC 1.1.1 copy kept the window responsive and
  showed live preparation progress. Archive-backed review identified exactly
  `monika`, `natsuki`, `sayori`, and `yuri`, displayed native Tk thumbnails, and
  did not offer sticker or UI families.
- Compiled-story inventory reduced DDLC's capture set from 798 registered forms
  to 449 reachable forms. The direct static-surface path reached form 320 of 449
  at 1 minute 46 seconds total elapsed with about 43 seconds remaining; the old
  GPU screenshot path had taken about 4.5 seconds per form and predicted roughly
  58 minutes for 798 forms. Backgrounds, LayeredImages, transforms, and dynamic
  displayables still use renderer-backed capture.
- Direct captures are converted to the legacy renderer's alpha-readback
  semantics before analysis. Against an old renderer capture of `monika 1`, the
  result differed in 8,039 channels across 5,314 of 921,600 pixels, always by at
  most one value. Derived form textures differed only by at most one value, with
  99 percent of channels identical. Large conversion batches now run in
  disposable workers so their image buffers cannot reduce later map concurrency.
- A forced recapture of the completed install exposed and fixed an update-only
  slowdown: the old SceneLight wrapper had been turning static images back into
  renderer-only displayables. The final updater suspended that owned wrapper in
  the private cache, cleared generated Ren'Py bytecode, reached form 375 of 449
  on the fast path, and restored the runtime with no leftover helper. The large
  conversion then used two approximately 57 MB workers while the long-lived
  installer stayed near 25 MB; after completion the install re-verified cleanly.
- The complete GUI **Create separate copy** flow finished with 29 scenes, 449
  forms, four selected character tags, zero skipped sprites, and a successful
  hybrid-GPU verification. Throughout capture, transport analysis, and form-map
  generation the UI displayed the current stage, exact item count, elapsed time,
  and remaining estimate.
- The selected source still matched its before-install manifest exactly: 949
  files, zero changed/removed files, zero additions, and zero SceneLight paths.
  The managed launcher retained a stock `DDLC.exe` backup with SHA-256
  `0F9EC1AEDE2A8397C23801200DF606BF03E400FBD09B32F762C33F37A9137085`.
  Setup preserved save namespace `DDLC-1454445547` and created its safety-snapshot
  record before committing generated output.
- Launching the managed copy's ordinary `DDLC.exe` opened real story gameplay
  through the compatibility runtime on Intel HD Graphics 4000. The residential
  and classroom scenes, two Sayori forms, and a scene transition rendered with
  live lighting while dialogue and settings UI remained unlit. The live log used
  the GL2 renderer and contained no traceback, exception, or shader failure.
- A second fully installed benchmark copy verified successfully, was removed
  through the supported command, and disappeared without touching its 949-file
  source or adding SceneLight files there. The completed GUI copy remains on the
  second PC for user testing.
- A fresh one-scene author sandbox was created on the second PC with one custom
  `Character`, a real `LayeredImage`, ATL movement, dissolve/hide/re-entry, and
  an unselected UI badge. Developer embedding produced 15 owned files; ownership
  status reported installed, clean, and no missing, modified, or unowned files.
  Real GPU playback showed physical combined lighting, a visibly stronger
  red/blue separate-light mode, continuous movement, and an unchanged white UI
  badge. Its portable launch batch was then exercised successfully.
- Ruff and all 213 Pytest tests pass. Bandit reports no medium/high findings,
  `pip-audit` reports no known vulnerabilities in the pinned Preview dependency
  set, and the 1.8.5 wheel and source distribution build successfully. The final
  online ZIP has 44 entries, is 214,199 bytes, and contains only `SceneLight.bat`,
  the player-first README, license/notices, and `_scenelight` at its root. Its
  SHA-256 is
  `206ef779f46542591e95a7b689f8a70eafbbbe53d11e9e619fbb142531a90a9e`.

## 1.8.4 fresh-computer setup checks

- The first-time failure reported from a separate computer was reproduced at
  its import boundary: the isolated Python runtime could not resolve
  `scenelight.compatibility` because the compact ZIP keeps the package under
  `_scenelight/src` instead of installing SceneLight into that environment.
- Every supervised subprocess now receives that exact packaged source path. A
  clean extraction created a brand-new empty virtual environment and used the
  packaged operation environment to import `scenelight.compatibility`
  successfully. The reported module path was inside the extracted 1.8.4 ZIP,
  not the development tree or a globally installed package.
- A second clean environment completed the full online first-time component
  workflow from the extracted package: runtime creation, installer-tool setup,
  and all eight Preview/analysis components. Final inspection reported the
  runtime ready and 8 of 8 exact versions verified.
- That new runtime then executed the same
  `python.exe -m scenelight.compatibility` command that failed in the supplied
  screenshot. It found the verified Ren'Py 7.8.7 support runtime and exited with
  code zero.
- Packaged UI captures at 780 by 540 verified phase 2 is now **Prepare**, the
  action is **Prepare this game**, and active work replaces the disabled button
  with a fully visible status. A simulated real pip transfer displayed
  `Downloading PySide6 Addons — 72.6 of 160.2 MB…` beneath a determinate bar.
- Fresh-machine bootstrap copy now says `Downloading Python 3.11.9 runtime` and
  `Installing SceneLight runtime`; internal `official` and `private` phrasing is
  no longer shown as product-facing status.
- Ruff passed and all 200 Pytest tests passed. Bandit reported no medium/high
  findings, and `pip-audit` reported no known vulnerabilities in the resolved
  Preview dependency set.
- The wheel and source distribution built successfully. The normal online ZIP
  is 209,909 bytes with 44 entries and no bytecode, game assets, generated maps,
  captures, reports, backups, or development clutter. Its SHA-256 is
  `af8ee77a5a59a0dd4a2535abb8106f44be559cf6c34c8e7489417ebaf2a67886`.

## 1.8.3 MVN shader-composition checks

- The current official Make Visual Novels Ren'Py Shader Pack was obtained from
  the creator's itch.io download and retained only in the external validation
  area. SceneLight does not redistribute it. The tested files were
  `MVNRSP1.rpy` SHA-256
  `D9BC3669100FA25D38EBF49665EE39F379ED1D5289469F6B90549FDAE5B3AF15`,
  `MVNTemplates.rpy` SHA-256
  `658849140FD6FB36708A0C1F7F2B0352136D50D60F53237358A2FFF4F955EF61`,
  and `SimulatedLightingExpansion.rpy` SHA-256
  `1CF6C0F730C082DD1AE0363707BA27CB05EFFBF3A179138D93FEDC3ABD8B8F4A`.
- The unchanged MVN files passed SceneLight preflight, form capture, analysis,
  and in-place developer installation with three Nova forms, 18 owned runtime
  files, no modified third-party files, and zero skipped sprites.
- All 29 current MVN transform presets rendered through the installed runtime on
  both Ren'Py 7.8.7 and Ren'Py 8.5.2. Each hidden automated run exited with code
  zero, produced twelve 1920 by 1080 GPU captures plus a manifest, and logged no
  shader or script error. Static sprite and background pixels matched exactly
  between engines; their only cross-engine difference was the expected text
  rasterization inside the deliberately unlit UI badge.
- With SceneLight enabled, MVN's outer aberration still changed 240,835 pixels,
  SceneLight still changed 318,588 pixels through that pass, and MVN simulated
  lighting still changed 271,946 pixels. The inverse image-declaration nesting
  retained a 319,514-pixel SceneLight contribution. MVN animated uniforms and
  combined MVN/ATL movement advanced on both engines.
- The UI badge crop was byte-identical across every captured state. This proves
  SceneLight remained limited to the selected character while MVN's own pass
  ordering remained under the author's Ren'Py transforms.
- The extracted 1.8.3 online package repeated the embed, ownership verification,
  Ren'Py 7/8 capture matrix, and clean 18-file removal. Final status was clean
  and uninstalled, and the three MVN source hashes remained unchanged.
- Ruff passed and all 193 Pytest tests passed. Bandit reported no medium/high
  findings, and `pip-audit` reported no known vulnerabilities in the resolved
  Preview dependency set.
- The wheel and source distribution built successfully. The normal online ZIP
  is 207,267 bytes with 44 entries and no MVN source, bytecode, game assets,
  generated maps, captures, reports, backups, or development clutter. Its
  SHA-256 is
  `7e6733925390c5c1699fc811fa6e94907f3857d7454aaa9926563d216c0ac61b`.

## 1.8.2 release-candidate checks

- Ruff passed and all 192 Pytest tests passed. Bandit reported no medium/high
  findings, and `pip-audit` reported no known vulnerabilities in the resolved
  Preview dependency set.
- Selecting an existing DDLC installation returned control to Tk in 0.0018
  seconds while the approximately 2.9-second archive and ownership inspection
  ran on a worker. Automated captures showed a live progress bar during that
  interval and the correct `Play installed game` action afterward.
- Captures at the app's normal 780 by 540 logical size verified the four-stage
  player flow, a visible primary action, distinct clean/new/existing install
  messages, and the scrollable per-component verification list. A pristine DDLC
  selection correctly offered `Check compatibility`; a verified direct install
  correctly offered normal-executable playback.
- A fresh seven-file Ren'Py 7.8.7 author sandbox passed renderer preflight,
  identified its explicit `nova` Character and LayeredImage, captured two forms,
  built one transport cache and one deduplicated surface map, verified all 15
  owned developer-runtime files, and removed them cleanly. The UI badge remained
  outside the selected character tag. All generated lint/cache/save artifacts
  were archived outside the handed-off fixture.
- The separate stock-DDLC player fixture exactly matches its 949-file pristine
  source by relative path, size, and total 279,603,684 bytes. `DDLC.exe` retains
  SHA-256 `0F9EC1AEDE2A8397C23801200DF606BF03E400FBD09B32F762C33F37A9137085`,
  and the fixture contains no SceneLight files.
- The wheel and source distribution built successfully. The normal online ZIP
  is 206,877 bytes with 44 entries and only `SceneLight.bat`, the player-first
  `README.md`, license/notices, and `_scenelight` at its root. Archive inspection
  found no bytecode, RPA archives, generated maps, captures, validation reports,
  backups, or development clutter. Its SHA-256 is
  `32b1aca25a26635142c9e61fa274a437aee130a43c183ec7e8897e64e71b9032`.
- A clean extraction reported SceneLight 1.8.2, rendered the redesigned setup
  states from packaged code, and passed the real Ren'Py renderer review of the
  author sandbox without changing its source tree.

The following 1.8.1 real-game results remain applicable because 1.8.2 changes
only setup inspection, status presentation, and documentation; it does not
change the production analysis or GPU runtime.

## Real Ren'Py 6.99 / DDLC path

A fresh stock DDLC 1.1.1 copy passed preflight through the Ren'Py 7.8.7
compatibility runtime before analysis. In-place attachment completed with 29
scenes, 798 sprite forms, four deliberately selected tags, and no skipped
forms. The native `DDLC.exe` remained the player entry point and opened the
actual game through the compatibility runtime while retaining save directory
`DDLC-1454445547`.

An in-engine GPU probe launched through that normal executable exercised show,
move, hide, dissolve, a background change, physical lighting, separated-light
mode, and an unrelated sticker. The moved frame and its following stable frame
were byte-identical. Physical versus separate mode changed 1,157,005 sprite
pixels; the background and sticker crops were byte-identical. Runtime registry
inspection identified the character as `SceneLightImageLike` and the sticker
as an ordinary `ATLTransform`.

Removal verified and deleted all 2,325 SceneLight-owned files and restored the
original `DDLC.exe` SHA-256 exactly. Every original file matched the retained
949-file clean fixture. Three Ren'Py bytecode caches and `game/saves/persistent`
created by gameplay remained intentionally present, proving removal did not
erase save data or unrelated engine output. Final embed status was clean and
uninstalled.

## Real modern Ren'Py path

A fresh archive-backed Ren'Py 8.5.2 game returned 18 semantic character
families during isolated review. A separate-copy installation then completed
with 70 scenes and 326 forms using the game's native renderer. The selected
source remained exactly 1,390 files with tree SHA-256
`0ed8e9c7919d5456563dff70e94d19f882c4c5039d35086ad62c7bc9a520a899`
before installation, after installation, and after managed-copy removal.

The normal game executable reached actual story dialogue under an isolated
validation save profile. A real LayeredImage was registered as
`SceneLightImageLike`; a per-character `enabled=False` override changed only
that displayable while a background-only region remained byte-identical.

A deliberately unrenderable `broken unsupported` displayable was then added to
the disposable source copy and selected explicitly. Installation still
completed with all 326 valid forms. Both its result and a later `verify`
reported the failed image, `runtime-capture` stage, and exact error in
`skipped_sprites`. The injected source was removed afterward and the original
tree hash was restored before the managed copy was safely removed.

## Preview, creative lighting, and retained renderer quality

The production Preview opened a generated 96-frame video, began playback in
3.27 seconds, and advanced to frame 12 while exact temporal lighting continued
caching in the background. It reported CUDA active, eight process workers, and
no playback errors.

The production GPU shader was also rendered against a controlled warm/cyan
scene at physical, separate, and maximum creative settings. Separate mode
changed 13.60% of the frame with a maximum channel delta of 58; maximum creative
mode changed 13.61% with a maximum delta of 96. The three images visibly retain
energy-balanced physical lighting at zero and increasingly distinct local
colored-light lobes at one and two. The 1.8.3 shader-composition contract does
not modify the established production shader equations.

## Retained earlier renderer and compatibility evidence

The detailed 1.6.3 evidence below is retained for the renderer-quality,
performance, sandbox, and broader Ren'Py generation matrix that 1.8.3 did not
replace.

## Ren'Py generation compatibility

The finalized Windows offline archive includes a trimmed, unmodified official
Ren'Py 7.5.3 compatibility runtime for legacy games whose bundled Ren'Py 6.99
engine cannot run SceneLight's live shader. SceneLight selects that runtime
automatically; Ren'Py 7 and Ren'Py 8 games continue to use their own compatible
engine. The retained runtime files were compared byte-for-byte with the audited
source tree after packaging.

Real title-screen launches and SceneLight verification passed on seven desktop
projects spanning Ren'Py 6.99, 7.3, 7.4, 7.5, 8.2, and 8.5. The original DDLC
1.1.1 test resolved 29 background scenes and 835 sprite forms. The final ZIP was
then extracted into a clean directory and installed, verified, and launched
without an explicit SDK path; it selected the included compatibility runtime,
opened the actual DDLC title, and reported the source project unchanged.

Windows Sandbox separately exposed only legacy OpenGL without the shader entry
points SceneLight Preview and live gameplay require. SceneLight now identifies
that driver limitation before compiling the Preview shader and reports it in
plain language. Exact CPU asset analysis remains available; live relighting
still requires a normal GPU driver or a virtual machine with working 3D
acceleration.

## Automated checks

- Ruff static analysis: passed.
- Pytest: 146 tests passed on the finalized source tree.
- Bandit static security analysis: no medium- or high-severity findings, no
  files skipped, and no inline suppression markers.
- Source distribution and universal wheel: built successfully.
- Release hygiene: no RPA archives, generated transport maps, game assets,
  validation captures, backups, or user-specific paths are included.
- The release ZIP checksum matched, and a clean extracted ZIP completed
  scan/install/verify/remove from a redirected private Python environment.
- The selected synthetic project had the same complete SHA-256 tree digest
  before and after that workflow; the managed-project root had zero children
  after removal.
- Installing both required and preview dependencies into the redirected
  SceneLight environment left the global Python package inventory unchanged.
- The extracted Setup window initialized as SceneLight Setup 1.6.3. A separate
  clean environment installed the final wheel, loaded its packaged runtime,
  extracted its production fragment shader, and reported SceneLight 1.6.3 from
  the installed command-line entry point.
- Generated batch-launcher arguments were exercised with spaces, percent signs,
  and environment-variable-like path text; all percent signs remained literal.
- The resolved base, preview, and optional CUDA dependency sets passed a
  published-vulnerability audit with no known findings after affected pins
  were updated.
- Both the source and offline Windows ZIPs built successfully. The offline
  builder accepted the valid Python Software Foundation signature, refused an
  unsigned substitute before creating a staging tree, and both resulting
  SHA-256 files matched their archives. Archive inspection found no Python or
  Ren'Py bytecode caches.

## Setup progress, preflight, and lossless bookkeeping optimization

The setup progress parser was exercised for native-game preflight, dynamic
resolver forms, background transport, scene packing, sprite inventory, and
unique-form analysis. A 1,517-form status was verified to contain the exact
current/total count, percentage, elapsed time, and estimated time remaining.
Native Ren'Py capture also publishes sparse atomic JSON checkpoints while its
console output is buffered, so the setup window can report background and form
progress reliably without changing the analysis or rendered assets.

Player attachment now completes an empty-request native Ren'Py renderer
preflight before background or form analysis. Integration tests verify that a
preflight failure prevents the builder from starting and that the successful
result is recorded in the installation report.

The preserved pre-change release and current source independently analyzed the
same original synthetic fixture. All 10 generated lighting and form-map PNGs,
including the transport atlas, were byte-for-byte identical. An isolated
1,517-entry manifest benchmark on the validation system measured 7.7684 seconds
for the previous every-form rewrite and 0.4875 seconds for 16-form checkpoint
batches, a 15.93x reduction in that bookkeeping stage. The final manifest hash
was identical. This optimization does not change image analysis, texture
compression, shader data, or the interruption-safe final atomic write.

The finalized process-based form executor was also compared directly with the
previous thread executor on 96 real discovered DDLC forms at 16 workers. All
288 generated form-map PNG files were byte-for-byte identical. The thread run
took 29.8856 seconds and the process run took 8.4952 seconds on the validation
machine, a 3.518x speedup in that stage without changing its calculation.

Version 1.6.3 adds a live available-memory limit to that process executor. A
simulated low-memory process-pool termination was recovered by halving only the
number of workers and retrying unfinished forms. Every resulting normal,
height/AO/edge, and material-response PNG was byte-for-byte identical to the
single-worker baseline. This prevents a large 806-form project from starting
16 NumPy/OpenCV processes in a memory-constrained VM while preserving the full
analysis resolution and equations.

## Renderer implemented and tested

The installed manifest is version 6 and uses the full hybrid renderer: four
detected lights, eight irradiance probes, a 26-plane `16x9` transport field,
ambient occlusion, directional distance-field rim response, specular response,
ground bounce, environment wrap, and self-shadowing. Background transport and
raw sprite form are cached; final lit character frames are never prebaked.
Position-dependent lighting is evaluated by the GPU from the sprite's final
transformed screen position on every rendered frame.

There is one production renderer and one result path.

## Preview & Calibrator parity

The Preview & Calibrator extracts its fragment source directly from the
packaged production Ren'Py runtime. On the validation machine, the finalized
shader hash was
`c40dee60f9d9530ea894ba83f598de5a564fd790aaf97da758b88bd407de40dd` and
compiled in a real OpenGL 3.3 core context on an NVIDIA RTX 4090.

An uncached original synthetic scene and sprite were analyzed, uploaded, and
rendered in Relit, Original, and Split modes. Relit versus Original mean
absolute byte error was 6.005721; Split differed from both endpoints, proving
the tester exercised all three GPU branches rather than presenting a static
image. The default calibration profile and the in-game runtime bind the same
five versioned calibration vectors.

Pillow 12.3.0 replaced an older affected decoder release during the security
pass. To guard visual compatibility, the same CPU analysis was run once with
each decoder version: all 15 generated atlas/form PNGs had a maximum pixel
difference of zero.

Result: passed.

## Optional GPU effects

Rain/wetness and glitch/corruption were exercised in the real Ren'Py 8.5.2 GL2
renderer, both scene-wide and on individual image tags. The runtime passed
actual engine save/load and rollback restoration, skip stability, dissolve
state stability, multi-character scene/character composition, and use of the
saved-game runtime as its deterministic animation clock. The player-facing
effects panel and `Shift+F8` hotkey are deliberately disabled for 1.0.0; these
effects remain developer-controlled through the documented API.

With both intensities at their defaults of zero, a fresh GPU capture matched
the protected pre-effects PNG byte-for-byte: equal SHA-256 hashes, zero changed
pixels, and no difference bounding box. Rain and glitch are therefore opt-in
shader branches rather than a change to ordinary SceneLight output.

An experimental automatic eye-glow detector was rejected during visual QA. It
localized only one member of a varied custom-sprite sample reliably and placed
false eye regions on the others. The public release contains no automatic eye
detector, player toggle, or Eyes Everywhere effect.

Result: passed for rain/wetness and glitch/corruption; the experimental player
panel, custom effect-pack templates, and automatic eye glow are intentionally
not shipped in 1.0.0.

## Setup-window and runtime-capture regression

- The selected source project remained free of SceneLight runtime, map, cache,
  launcher, and compiler outputs; those files existed only in a path-keyed
  managed project under local application data.
- Green Eyes launched from its managed copy with its own bundled Ren'Py 7.5.3
  executable. This removes the former Ren'Py 8.5-on-7.5 `Init.varname` crash
  without changing the original mod.
- Green Eyes also completed forced live character renders for both optional
  effects under its own Ren'Py 7.5.3 GL2 renderer. The runtime uses an adaptive
  full-bounds texture path and a 7.5 shader-declaration compatibility preamble;
  the lighting equations and Ren'Py 8 path are unchanged.
- Managed-copy removal was tested independently and left the source scripts in
  place. Managed-native saves and caches survived automatic source sync.
- Developer embedding was tested as a separate opt-in workflow. It added only
  a new reserved namespace plus ownership manifest, cleanly removed its own
  files, recognized native compiler output, and refused before any deletion
  when an owned file, manifest path, or unknown namespace file was altered.
  Its project-relative ownership record also remained removable after the
  source tree was moved to a different path.

- A fresh original LayeredImage fixture completed an uncached CUDA install in
  9.3 seconds with no visible Ren'Py helper window.
- Green Eyes exercised an archive-heavy real mod assembled over a fresh DDLC
  base with 39 usable backgrounds, 1,566 resolved sprite declarations (1,517
  unique rendered forms), and nine discovered character tags. Native Ren'Py 7
  capture, installation, launch, and `verify` completed successfully. Capture
  diagnostics were limited to optional declarations whose referenced image
  files are absent from the mod itself; they were not treated as SceneLight
  assets or silently substituted.
- The capture supervisor accepted only an atomically published result and then
  stopped its private renderer, so mod-defined quit labels and Ren'Py error UI
  could not strand setup in a blank or "Not Responding" game window.
- A deliberately interrupted form-map build resumed from content checkpoints
  and processed only the remaining forms.

## Full custom-character DDLC mod

The public Episode 47 release of Doki Doki Club Meetings was attached at the
production grid without modifying its story scripts. It exercises stock DDLC
characters plus Ayami, Fuyuki, Ms. Ida, Kagami, Kenzo, Rie, and Ryan.

- 12 character image tags discovered automatically.
- 54 usable backgrounds measured into the transport atlas.
- 1,668 canonical sprite/form names resolved from source, `LayeredImage`, and
  archive-backed declarations by the target game's own Ren'Py runtime.
- Zero character-name, filename, skin-tone, or palette-specific lighting
  rules.
- Manifest verification, Ren'Py 8.5.2 compile, and lint passed. The one runtime
  capture diagnostic is a genuine source typo (`monika turned casual...`) for
  a pose the mod does not define; ordinary unsupported backgrounds remain
  normally rendered and are listed rather than guessed.

### Canonical LayeredImage form regression

Ren'Py can omit inherited/default `LayeredImage` attributes from the visible
runtime image name. Previously that made a valid expression miss its detailed
form cache and silently use the generic fallback. The production resolver now
matches the smallest canonical attribute superset, with exact-name matching
first and the generic map last. This is universal attribute logic, not a
Monika fix.

Against the exact CPU form-map renderer used by SceneLight, after
sub-pixel registration of the visible sprite content:

| Episode 47 pose | Mean Delta E | P95 Delta E | SSIM | Local form error |
|---|---:|---:|---:|---:|
| Monika, left | 0.730 | - | 0.9919 | 0.0285 stops |
| Monika, right | 0.851 | 1.992 | 0.9895 | 0.0304 stops |
| Natsuki, center | 0.888 | - | 0.9897 | 0.0261 stops |

The originally reported right-side Monika case fell from mean Delta E 2.001 to
0.851. Its mean luminance drift fell from 0.01899 to 0.00497. This directly
tests the edge, directional form, and self-shadow detail that was missing from
the generic fallback.

### Motion, scene cuts, and transitions

- A 14-second Monika left-to-right sweep produced distinct left, middle, and
  right captures with continuously changing warm/cool, rim, and shadow
  response.
- The first frame of an instant cut to the bright bathroom and the stable frame
  were byte-identical PNGs, proving there is no one-frame color pop.
- During a dissolve, the outgoing character retained the outgoing scene's
  lighting while the incoming character used the incoming scene's field.
- The installed mod completed the normal playable story-start path without the
  former `LayeredImage.visit_all` crash.

### Runtime performance

On the validation machine (Ren'Py GL2, NVIDIA RTX 4090, 1280x720 logical):

- One character: 143.999 FPS enabled versus 143.997 FPS disabled; both median
  frame times were 7.0 ms.
- Four characters: 143.602 FPS enabled versus 144.001 FPS disabled, a measured
  0.277% FPS cost; median frame cost was 0.0 ms.

Both runs were refresh-rate limited, so these figures show no measurable
median-frame compromise at the tested load rather than claiming zero shader
work on every GPU.

Result: passed.

## Exact CUDA analysis performance

The production analyzer now executes its full-resolution geometry, 144-position
metering, radiance probes, and transport reductions with CUDA while sharing the
approved CPU component decisions. It does not use a smaller grid, downsampled
preview, provisional lighting, or cache hits in the cold benchmark. CUDA is an
optional acceleration path; an unavailable or failed CUDA backend falls back
to the complete CPU analyzer and is covered by an automated regression test.

On the Windows validation machine with an NVIDIA RTX 4090:

- A cold 700-background run completed in 114.4644 seconds (1.9077 minutes), or
  6.1154 complete backgrounds/second.
- The corpus cycled through 38 real source backgrounds and 15 analysis shapes
  with eight preparation workers; no cache hits were used.
- CUDA transport work accounted for 64.7244 seconds, averaging 0.09246 seconds
  per background.
- A fresh full SceneLight Studio artifact for foggy park completed in 0.888086
  seconds after CUDA startup warmup; a complete cache hit took 0.001069 seconds.
- Fresh 960x960 arbitrary bear form analysis remains 0.703 seconds; warm
  background and form lookups remain below 1 ms each.

Six difficult real scenes were compared against the unchanged approved CPU
reference: fog, backrooms, red corridor, bright greenhouse, Photo 09, and
sunset meadow. Each 14,976-byte CUDA transport LUT differed in only 4 to 29
bytes, every difference was at most one 8-bit step, and mean absolute error was
0.000267 to 0.001937 of a byte. Sparse component layouts matched at all 144
positions in every scene. The CPU reference hashes remained unchanged.

Result: passed.

## Non-DDLC Ren'Py project

An original Ren'Py 8.5.2 project used a custom `Character(image="nova")` and a
real two-layer `LayeredImage`, not a flattened compatibility stand-in.

- The installer discovered the custom tag and resolved both form aliases
  automatically.
- Content-addressed form data deduplicated identical rendered forms.
- Production `16x9` attachment, verification, compile, lint, and live GL2
  rendering passed.
- First resolver refresh took 3.456 seconds; an unchanged repeat attachment
  took 0.719 seconds and reported a cache hit.
- Left, center, and right captures were all different and showed warm-to-mixed-
  to-cool spatial response plus form shading.
- `final_sprite_prebake` remained `false`.

Result: passed.

## Broad renderer regression corpus

The finalized hybrid core was also compared across six environments and ten
very different transparent subjects, including the four stock DDLC girls,
black fur, a white shirt, alternate clothing, and Demonika.

- 60-case mean color error: Delta E 1.486.
- Worst case: Delta E 2.103.
- Mean structural similarity: 0.965.
- Local form error: 0.088 stops.
- Eight alternate expressions: mean Delta E 1.555.
- Movement and transition suite: 67 captures passed.
- The previously approved 25-background desktop gallery remains unchanged.

Result: passed.

## Safety boundary

A background created only by arbitrary Python after player interaction, or a
`DynamicDisplayable` that changes pixels without changing its `bg` image
attributes, cannot be inferred reliably ahead of time. It may be explicitly
mapped in `scenelight.json`; otherwise SceneLight reports it and leaves it
normally rendered. This boundary does not require character-specific setup and
does not affect ordinary DDLC/Ren'Py scene declarations.

## Dynamic capture alpha and lifetime regression (2026-08-26)

The release capture helper was exercised through the target engines after the
alpha-preserving software-compositor change:

- Ren'Py 8.2.1 completed the full Interaction manifest: 10,743 original
  requests, 10,778 canonical forms, and zero unresolved requests or capture
  errors. Several native access violations were recovered from atomic form
  checkpoints without discarding completed forms.
- A forced termination after 137 real Interaction forms resumed in a new native
  process and finished 500/500 requests with zero errors.
- The final helper completed 700 real requests across its controlled 512-form
  batch boundary, then expanded to 800 requests while reusing the normalized
  content-addressed captures. The second run resolved 800/800 requests in
  25.383 seconds and did not normalize reused forms twice.
- A separate 3,000-real-request run completed 3,008 canonical forms with zero
  errors while naturally recovering from renderer exits.
- Ren'Py 6.99 and Ren'Py 8.5.2 each completed a fresh dynamic alpha capture with
  the same helper and zero errors.
- Exact Interaction Sayori and Yuri forms remained 960x960 RGBA with alpha
  extrema 0–254 rather than an opaque framebuffer capture.

The fix bounds garbage collection for cyclic Ren'Py Render/pygame surface
graphs. It does not change transport analysis, form-map reconstruction, or the
live lighting shader. Capture contract version 26 prevents older opaque or
non-resumable captures from being reused.

Result: passed.
