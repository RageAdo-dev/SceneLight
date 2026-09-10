# Changelog

## 1.0.0 — first public release

- Fixes a Ren'Py type-substitution bug that rejected JSON animation data and
  silently froze lighting on the first field. Uses the visible source state
  for frame animations and decoder position for movies, not a dialogue clock
  or guessed four-second period. Adds actual-engine synchronization evidence.
- Recovers interrupted raw capture before reseeding caches, preserving conflicting
  generated files. Closes the process-start cancellation race and tests a real
  Windows worker/child cancellation. Bounds atlas allocation to the supported
  texture limit and improves character-list wheel and text-key behavior.

- Establishes SceneLight 1.0.0 as the first stable public GitHub release. All
  earlier 1.x-numbered packages were internal development builds and were never
  public releases.
- Detects clean versionless installations as **pre-1.0 internal builds** instead
  of silently launching them. Player and developer workflows now present an
  explicit update action and confirmation, with a choice to keep and launch the
  current installation.
- Records the SceneLight product version and the runtime, transport, sprite-map,
  capture, and manifest contracts in every new direct or separate installation.
  Compatible cached analysis is reused; changed inputs or bumped algorithm
  contracts rebuild only the affected data.
- Keeps scene wipes and dissolves on the GPU. Transition stabilization no longer
  performs a synchronous framebuffer readback and PNG encode, eliminating the
  story-advance hitch seen at first background changes.
- Treats the dynamic-asset capture timeout as a stalled-renderer limit instead
  of a total-size limit. Healthy captures with thousands of canonical forms no
  longer restart every 15 minutes, and genuine renderer retries are identified
  explicitly in the Activity log.
- Writes dynamic forms as atomic resumable checkpoints. Healthy parallel
  renderers stay alive; if Ren'Py exits, only that worker continues from its
  completed forms. Later scans also reuse normalized forms when only the
  requested character list changes. Completed GPU backgrounds are checkpointed
  separately.
- Rejects Ren'Py's red missing-image placeholder before background or character
  analysis. Scene keys now use the same case-insensitive identity as the live
  runtime, and the capture-pixel contract was bumped so an update cannot reuse
  poisoned PNG checkpoints. On the Interaction stress case this removed 313
  bogus 34-pixel character maps and 16 invalid background entries without
  changing the lighting model.
- Prevents strongly graded sunset/night backgrounds from multiplying their
  chroma into a character until the sprite collapses to solid red or blue.
  Extreme scene chroma is compressed continuously, and already-authored sprite
  color is retained at SceneLight's generated luminance. The guard uses only
  measured scene and material values—never character, image, form, or
  background names—and leaves neutral scenes on the original shader path.
- Preserves up to three canonical colored emitter families alongside the
  energy-balanced physical aggregate. Automatic separation activates for two
  strong, differently colored, spatially distinct families, or for one strong
  colored practical that is spatially separated from a neutral key. Weak props
  and ordinary single-hue scenes remain on the aggregate path.
- Uses each colored emitter's measured screen-space direction instead of
  rotating secondary directions artistically. One scene-wide transport layout
  keeps every plane's identity stable across the complete 16x9 spatial grid.
  Video layout changes fade incompatible secondaries through the shared primary
  key instead of popping or blending unrelated lights.
- Classifies each video anchor's background emitters once in scene coordinates,
  while retaining all 144 position-dependent meters, probes, and light-to-form
  directions. The supplied 30-second/121-anchor GPU regression dropped from
  297.9 seconds to 30.1 seconds cold (16.7 seconds of analysis) without reducing
  anchor rate or transport resolution.
- Verifies a video's decodable tail instead of trusting an overreported MP4
  frame count. Export now omits empty container samples rather than failing on
  the nonexistent final frame. Its progress dialog appears before live analysis
  is joined, exposes a persistent **Cancel export** action, propagates that
  cancellation into temporal batches and GPU rendering, and removes partial
  FFmpeg output.
- Makes the loaded Ren'Py image registry authoritative for full installation
  instead of stopping discovery after the source parser finds one usable scene.
  Archive-backed images, aliases, Composite, LiveTile, ATL, Animation, Movie,
  and DynamicDisplayable backgrounds now augment the conservative static pass.
- Precomputes temporal lighting for changing backgrounds. Ren'Py animations,
  ATL, and DynamicDisplayable scenes are sampled at 8 Hz for four seconds and
  deduplicated before analysis; authored Movie sources are decoded across their
  complete loop. The runtime advances through those fields at the same cadence,
  while ordinary static scenes retain one field and no continuous redraw.
- Adds a persistent Cancel action to Setup operations and terminates the entire
  supervised installer/renderer process tree. User cancellation is reported as
  cancellation rather than a failed install. The character-review list gains
  themed scrollbars, wheel/Page/Home/End navigation, and a readable dark entry.
- Launches source-only Ren'Py projects through the exact compatible runtime
  recorded during installation. Setup no longer claims that a bundled Windows
  executable is required when a valid SDK playback command exists.
- Makes Preview & Calibrator genuinely standalone: its Tools button remains
  available before a game is selected, installs optional Preview components on
  demand, and passes `--project` only when a valid game was actually chosen.
- Labels the installed-project operation **Updating SceneLight** and reports an
  actual renderer failure instead of presenting the last progress line as the
  error.
- Prevents a modern Ren'Py game from falling through to a different-major SDK
  after a renderer failure. In particular, Ren'Py 8 protocol-5 archive indexes
  are no longer handed to the Ren'Py 7 legacy compatibility runtime.
- Declares every texture and lighting uniform used only by reusable fragment
  functions explicitly. This fixes shader compilation on Ren'Py 8.2, whose
  shader assembler otherwise omitted those function-only dependencies.
- Reports project inspection, isolated-copy preparation, file counts, runtime
  testing, and candidate finalization during **Scan game**. Character review now
  states that suggestions come from the selected game's Character objects,
  LayeredImages, registered images, and compiled story usage rather than a
  built-in DDLC name list.
- Reports compiled-story inventory, image-family discovery, character geometry,
  image cataloging, background capture, form planning, checkpoint restoration,
  parallel capture, deduplication, and normalization. A completed phase can no
  longer leave Setup displaying a stale 100% line while another long phase runs.
- Keys restart checkpoints by Ren'Py's order-independent image-attribute identity
  while retaining the first valid longest-prefix spelling for rendering. Native
  renderer exits now restore every completed semantic form instead of repeating
  the same form under shuffled attribute orderings.
- Uses adaptive isolated Ren'Py workers for very large character plans. Each
  worker receives a disposable runtime clone, so mod-supplied single-instance
  guards and writable compiler state remain intact. Balanced contiguous shards
  preserve character-family cache locality; immutable engine/runtime files are
  hard-linked when supported, while authored game files stay private. Workers
  share a process-safe component store, retain atomic journals, and retry only
  the affected shard on another compatible renderer. Small projects keep the
  single-process path.
- Reduced the 7,386-form Interaction regression from 291.3 seconds on the prior
  clean path (407.8 seconds with the discovered restart defect) to 50.98 seconds
  cold. An unchanged result now reloads in 1.04 seconds instead of 24 seconds.
  Every semantic sprite form remained pixel/component-identical to the retained
  native-renderer reference.
- Keeps the experimental player effects panel and custom effect-pack templates
  dormant for 1.0.0. No hotkey is registered and the Windows ZIP does not
  include or advertise the next-update effect packs. Normal SceneLight lighting,
  Preview, and the documented rain/glitch developer API are unchanged.
- Documents the brief GPU-target rebuild that can occur when resizing or
  maximizing Ren'Py.
- Includes the final pre-release lighting, third-party shader composition, live
  transition redraw, legacy save-compatibility, performance, installer, and
  developer-API work summarized below.

## Pre-1.0 internal development history

The identifiers below were local engineering build numbers. They were not
published GitHub releases and do not outrank the public 1.0.0 release.

### Internal build 1.8.7 (pre-release)

- Fixed the Preview launcher after the 1.8.6 dependency reduction. It no longer
  checks for the removed `scikit-image` package, so a fresh Preview installation
  starts with the exact published dependency set.
- Consolidated the public Windows entry point on `SceneLight.bat`. Obsolete
  player, developer, Preview, and setup wrapper BAT files were removed from the
  source root, which now matches the release package's single-launcher layout.
- Updated player, author, security, compatibility-runtime, and release
  documentation to use current online-first installation language and the
  validated Ren'Py 7.8.7 compatibility runtime.
- Linked the upstream Make Visual Novels! shader pack used by the unchanged
  shader-composition regression and clarified exact-map versus live-fallback
  behavior for newly added character forms.

### Internal build 1.8.6 (pre-release)

- Added an optional `light_mode="cinematic"` author preset that formalizes a
  validated compromise between physical and exaggerated separated lighting.
  It compresses automatic scene exposure while retaining restrained local
  source colors. The physical default and full separate mode are unchanged,
  and explicit values in the same call override every preset value.
- Preview profiles and exported project configs now preserve lighting strength
  as well as calibration, so the exact Cinematic result survives reopening,
  installation, and gameplay. Authored strength overrides replace that saved
  default instead of accidentally multiplying it.
- Normal managed launches now fingerprint the external Preview profile and treat
  project-owned `scenelight.json` changes as visual inputs. A new or edited look
  is rebuilt before play; an unchanged profile retains immediate cache reuse.
- Direct mod-developer installs now record their analyzed source inventory and
  expose a verified **Check new assets → Update SceneLight** workflow. New
  backgrounds, videos, scripts, poses, and explicit character tags reuse
  unchanged caches, build before mutation, and transactionally replace only the
  owned runtime. Swap failure restores the previous verified runtime, including
  legacy normal-EXE recovery files.
- Streamed Preview video decoding moved off Tk/Qt's interaction thread onto a
  bounded worker. Dragging remains a GPU placement update even while 1080p video
  and exact temporal lighting advance concurrently.
- Form-map version 3 keeps one reconstructed surface per distinct form while
  bounding large derived textures to a deterministic 512-pixel maximum
  dimension. Original dimensions and pixel SHA-256, normalized placement, the
  64×64 directional response, and lossless PNG channels remain explicit. On the
  four-thread validation laptop, 449 forms inventoried and 428 unique surfaces
  completed in 45.48 seconds instead of roughly 150 seconds; generated form-map
  storage fell from about 765 MiB to 234.35 MiB. Real Ren'Py 8 physical,
  separate, cinematic, transition, and refreshed-background frames passed the
  new strict baselines after quantified comparison with the retained full-size
  captures. Ren'Py 7.8.7 GL2 also rendered the same bounded real-Sayori form
  through its legacy texture path and exited with a clean log.
- Fresh setup now recovers when SceneLight's registered Python runtime files were
  manually removed. The verified installer enters repair only when the Windows
  registration points to SceneLight's exact owned directory; unrelated Python
  installations are never repaired or changed. Online and optional offline
  bootstrap paths share the same guarded implementation.
- Reduced fresh-player setup downloads to the four components used by analysis
  and installation. The substantially larger Qt/OpenGL/video Preview stack is
  now installed only when Preview & Calibrator is opened.
- Moved `psutil` into the required core set because renderer-tree supervision
  uses it during normal installation, and removed the unused `scikit-image`
  dependency instead of downloading its SciPy dependency chain.
- Reuse the background's exact HSV hue-sector fields across all 144 transport
  positions. This removes repeated color conversion and hue-distance work while
  keeping the encoded CUDA transport byte-for-byte identical to the prior
  implementation on the retained Green Eyes regression scene.
- Avoid duplicate exact component classification when transport placements
  converge after clamping, then expand the immutable result back to the full
  grid. Transport resolution and GPU sampling remain unchanged.
- Copy plain archive-backed PNG image bytes through Ren'Py's own loader instead
  of decoding and re-encoding every background and sprite inside the legacy
  renderer. The host still applies the validated renderer-alpha normalization;
  LayeredImages, transforms, SVGs, oversampled art, and non-PNG formats retain
  the renderer-backed path.
- Export safe static `im.Composite` structures as a deduplicated set of archive
  PNG components, then reproduce Pygame's integer SRCALPHA composition exactly
  in disposable host workers. Composition is pipelined while Ren'Py exports
  later forms; LayeredImages, ATL/transforms, and mixed dynamic composites keep
  the renderer fallback. All 423 static DDLC composites matched the retained
  renderer captures byte-for-byte.
- Use a lossless low-CPU RGBA checkpoint for cached Ren'Py surfaces, then apply
  the established renderer-alpha conversion and fast lossless PNG compression
  on the host instead of blocking the legacy runtime on maximum compression.
- Adapt normalization/composition from one to sixteen disposable processes
  according to live memory, logical CPUs, pending work, and concurrent Ren'Py
  load. A 512 MiB reserve and automatic one-worker fallback remain in place.
- Reuse one exact 64-by-64 Lambert response matrix per form worker and use a
  bit-exact uint8 sRGB lookup while reconstructing sprite maps. The response
  texture and pseudo-surface regression paths remain byte-identical, while the
  corrected 256 MiB worker estimate lets an 8 GB four-core computer use all of
  its cores safely.
- Avoid decoding/composing every sprite once for inventory and again for map
  generation. A cheap ordered source fingerprint now provides safe cache and
  duplicate detection; the worker composes each uncached form only once and
  still records the established exact decoded-pixel digest.
- Repack the same six full-resolution form channels into two RGB textures so
  smooth normal/edge data compresses together and deterministic grain occupies
  only one channel. Shader regression reconstructs the prior logical inputs
  byte-for-byte; map resolution and live lighting calculations are unchanged.
- Added a reusable separate-light calibration profile for local testing and mod
  authors under `examples/renpy/separate_light_profile.json`, plus the validated
  Cinematic profile under `examples/renpy/cinematic_light_profile.json`.

### Internal build 1.8.5 (pre-release)

- Fixed legacy Ren'Py support downloads on clean Windows computers whose Python
  runtime has no usable OpenSSL CA file. SceneLight now adds the Windows trusted
  ROOT certificate store to its verified HTTPS context instead of weakening or
  disabling certificate validation.
- Kept the pinned Ren'Py archive SHA-256 check and atomic partial-download flow.
  Failed transfers are removed, and incomplete responses are rejected before
  extraction or installation.
- Fixed setup result parsing so a nested JSON dictionary can no longer replace
  the complete CLI report. Archive-backed DDLC review now receives the four
  renderer-discovered character families and their previews instead of showing
  an empty candidate list.
- Added a native Tk PNG thumbnail path for the lightweight setup runtime, so
  renderer-created character previews remain visible even before optional
  analysis components such as Pillow are available to that Python process.
- Changed legacy renderer cleanup from a full cache purge after every sprite to
  bounded batches. Shared pose and facial components now remain reusable across
  nearby forms while periodic render/image purges still cap memory use on
  32-bit Ren'Py games.
- Supervise the full renderer child-process tree, including detached Ren'Py SDK
  launchers whose executable lives outside the managed game copy. Setup now
  waits for the real renderer result and reliably stops those children on
  completion, timeout, or cancellation instead of reporting a false failure or
  leaving an orphan process.
- For archive-only games, recover exact `show` statements and character-dialogue
  attributes from Ren'Py's compiled AST and capture only story-reachable forms.
  A deliberately selected tag with no visible story use still falls back to its
  registered family, preserving custom/dynamic projects without making normal
  games process every unused expression in their archives.
- Save static Ren'Py image-manipulator and `im.Composite` forms directly from
  the engine's exact cached RGBA surface, then reproduce the legacy renderer's
  alpha-readback semantics before analysis. This removes the per-form GPU
  screenshot round-trip while preserving established SceneLight map output;
  LayeredImages, transforms, and dynamic displayables continue through the
  renderer-backed capture path.
- Run large alpha-normalization batches in short-lived worker processes. Their
  image buffers are released before form-map analysis starts, preserving safe
  multi-core analysis on memory-constrained Windows computers.
- During an update or renewed character review, temporarily suspend the existing
  SceneLight wrapper and its generated Ren'Py bytecode while raw assets are
  inspected. The prior runtime is restored on every failure path, so existing
  installations keep the fast static capture path without sacrificing recovery
  safety.

### Internal build 1.8.4 (pre-release)

- Fixed first-time setup from the compact Windows ZIP. Every isolated-runtime
  subprocess now receives the packaged SceneLight source path, so the newly
  created runtime can import `scenelight.compatibility` immediately instead of
  failing with `ModuleNotFoundError` on a fresh computer.
- Renamed phase 2 from **Check** to **Prepare** and replaced internal-sounding
  runtime/dependency language with direct player-facing SceneLight runtime and
  component language.
- Replaced the component installer’s indeterminate animation with live,
  determinate transfer progress. The main window now names the package being
  prepared or downloaded, reports transferred and total sizes, and distinguishes
  runtime creation, installer preparation, package installation, and final
  version verification.
- Hid the inactive working button while a task runs so the live progress text
  always fits at normal Windows scaling. Component setup started from the main
  workflow now continues into game preparation automatically after verification.

### Internal build 1.8.3 (pre-release)

- Made SceneLight's third-party shader composition boundary an explicit,
  regression-tested runtime contract. Child shaders finish in their own
  render-to-texture pass, foreign uniforms and GL properties are never copied,
  and deliberately combined lower-priority parts feed SceneLight through
  `gl_FragColor` instead of being replaced.
- Validated all 29 transforms in the official July 2025 Make Visual Novels
  shader/template pack unchanged on real Ren'Py 7.8.7 and 8.5.2 renderers.
  SceneLight, MVN effects, MVN animated uniforms, ATL movement, and unselected
  UI all remained independently active.
- Documented predictable shader order for ordinary `show ... at` transforms,
  image-declared transforms, MVN simulated-lighting combinations, and deliberate
  per-character or per-scene bypasses.

### Internal build 1.8.2 (pre-release)

- Redesigned the player setup flow as four visible stages with clearer project,
  compatibility, prior-installation, and primary-action states.
- Moved project and installation ownership inspection off the Tk event thread.
  Selecting a large or archived game now shows live inspection progress instead
  of freezing the setup window.
- Recognized verified direct installs, managed copies, incomplete installs, and
  unowned reserved runtime files as distinct states. Existing installations now
  offer the safe play, launch, verify, or recovery action instead of presenting
  a misleading setup button.
- Added a scrollable Advanced requirements checklist that reports the private
  Python runtime and every pinned dependency individually as verified or
  missing.

### Internal build 1.8.1 (pre-release)

- Added a renderer-backed, read-only character review for archive-only games.
  It inventories semantic `Character` and `LayeredImage` families in an
  isolated copy, produces one bounded preview per family, and leaves every new
  suggestion unchecked until the player deliberately selects it.
- Moved the in-place ownership conflict check ahead of renderer capture and
  analysis, so an already modified or unmanaged destination is refused before
  any expensive work starts.
- Made per-sprite runtime capture failures first-class structured skips. A bad
  displayable no longer hides in a generic resolver log: setup and later
  verification name the image, failed stage, and error while valid sprites
  continue through installation.
- Stopped a compatibility-scan sidecar from being mistaken for a completed
  managed installation in the setup UI.
- Preserved an existing automatic/manual review choice when the character
  review is reopened; only explicit manual selections start checked.

### Internal build 1.8.0 (pre-release)

- Added a mandatory character-family review between compatibility scanning and
  analysis. Newly discovered families start unchecked, can be reviewed with a
  representative preview, and can also be entered directly by Ren'Py image tag.
- Made manual selection authoritative across static images, LayeredImages, and
  archive-backed runtime capture, so unchecked stickers, UI, props, and cut-ins
  cannot be silently reintroduced by later discovery.
- Stored player selections in a per-project SceneLight profile outside the
  selected game. Mod authors can commit the same selection through
  `character_selection` and `character_tags` in `scenelight.json`.
- Kept conservative automatic discovery as an explicit alternative and added
  a rescan/review action to the setup tools window.

### Internal build 1.7.1 (pre-release)

- Preserved live sprite lighting through ATL entrances, exits, replacements,
  moves, hides, dissolves, and scene transitions by forwarding Ren'Py's full
  displayable lifecycle and resolving lit transition sides before temporary
  framebuffer transforms change screen-space coordinates.
- Made automatic character discovery conservative. Ren'Py image tags now need
  semantic character evidence plus foreground geometry; stickers, UI art,
  logos, poem pages, and cut-ins remain unlit unless explicitly opted in.
- Added explicit `character_tags` documentation for unusual small/chibi
  characters and retained per-tag `enabled=False` as the author opt-out.
- Added transition lifecycle, false-positive art, explicit opt-in, legacy
  parsing, and clean archived-DDLC installation regressions.

### Internal build 1.7.0 (pre-release)

- Made the game's normal executable the SceneLight entry point for legacy
  Ren'Py titles, with a hash-verified backup and exact restoration on removal;
  a separate batch-file launch is no longer required.
- Preserved each game's native Ren'Py save namespace when using the
  compatibility runtime and added timestamped project and roaming-save
  snapshots before attachment.
- Moved renderer, runtime, and empty-capture compatibility checks ahead of the
  expensive background and sprite analysis pass.
- Made malformed or unsupported sprite forms non-fatal. SceneLight now skips
  only the affected form and records its image name, failed stage, and error in
  the result manifest and setup activity log.
- Made verification aware of both reversible in-place installs and managed
  copies, so a healthy in-place attachment is no longer reported as missing.
- Added a first-class Ren'Py author API with rollback-safe whole-mod, current
  scene, background, character-tag, and exact-image controls.
- Added per-scene enable/disable and complete lighting calibration overrides;
  authored settings layer over automatic analysis without replacing it.
- Added a dedicated mod-developer installer entry point alongside the existing
  player installer. It uses the existing ownership manifest and verified safe
  removal path without rewriting authored scripts.
- Documented API precedence, every supported setting, and a copyable Ren'Py
  integration example.
- Stopped the setup window from repeatedly launching dependency probes and
  rechecking the installed project while idle. Missing requirements still
  refresh promptly; a ready system now performs only an infrequent safety check.

### Internal build 1.6.6 (pre-release)

- Made the compact online Windows package the primary release. On a machine
  without Python, its launcher asks before downloading the pinned official
  Python 3.11.9 installer, verifies both its SHA-256 digest and Python Software
  Foundation signature, and installs it only in SceneLight's private data
  directory.
- Fixed high-motion videos appearing frozen in Preview. The exact first-frame
  solve now has priority, playback begins as soon as it is ready, and exact
  temporal analysis continues in the background without stopping the video.
  Each displayed frame still updates its live environmental color immediately;
  completed transport anchors are reused on every later playback.
- Retained the large offline Windows package as an optional no-network fallback.

### Internal build 1.6.5 (pre-release)

- Made **Individual light colors** retain several saturated hue families even
  when nearby lamps merge into one physical source during normal analysis.
- Added a deliberately stylized separation path that lets warm, cyan, and
  green emitters paint different regions of a flat sprite at higher creative
  settings instead of collapsing into one scene-wide warm tint.
- Kept the realistic default pixel-identical: creative-only sources have zero
  physical intensity and are ignored while the control is set to zero.
- Added synthetic multicolor transport regressions and an exact production-GPU
  comparison renderer for difficult practical-light scenes.

### Internal build 1.6.4 (pre-release)

- Added a default-off **Individual light colors** calibration control. It
  preserves the validated energy-balanced renderer at zero and can creatively
  separate the four strongest detected source groups across directional form
  shading and colored rim response without adding exposure.
- Kept the creative branch out of the disabled shader path so existing profiles
  retain their prior appearance and runtime cost.

### Internal build 1.6.3 (pre-release)

- Made exact sprite-form generation size its process pool from currently
  available memory as well as CPU count, preventing high-core, memory-limited
  systems and virtual machines from terminating workers during large mods.
- Added automatic exact-quality recovery from a memory-terminated form worker
  pool. SceneLight resumes unfinished forms at lower concurrency without
  changing the analysis or any generated texel.
- Replaced PyOpenGL's raw undefined-function error with an early explanation
  when a virtual machine exposes only legacy OpenGL without shader support.

### Internal build 1.6.2 (pre-release)

- Added automatic Ren'Py 7 compatibility-runtime discovery for legacy Ren'Py
  6.99 games, fixing the false `No static background scenes could be resolved`
  failure on original DDLC without requiring a user-selected SDK.
- Added early Ren'Py 7 asset-loading fallbacks and validated real launches on
  Ren'Py 6.99, 7.3, 7.4, 7.5, 8.2, and 8.5 projects.
- Added an audited release-builder input for the official Ren'Py 7 compatibility
  runtime, with completeness, version, and retained-license checks.

### Internal build 1.6.1 (pre-release)

- Added automatic renderer negotiation for native asset capture. SceneLight now
  retries the ANGLE/DirectX and OpenGL backends actually bundled with old
  Ren'Py games, plus matching GL2 backends for modern SDKs, before reporting an
  incompatible graphics environment.
- Split setup into two clear installation choices: a reversible in-place
  attachment or a separate managed playable copy.
- Made in-place attachment create only SceneLight's reserved namespace and
  ownership manifest, remove its temporary build copy after success, and keep
  hash-verified refusal semantics during removal.
- Corrected installed-state detection so missing owned files cannot be reported
  as a clean attachment.

### Internal build 1.6.0 (pre-release)

- Added a self-contained offline Windows release path. Setup verifies an
  official Python Software Foundation signature, asks before installing a
  private per-user runtime, and installs pinned components without requiring a
  preinstalled Python or changing PATH, file associations, or global packages.
- Added a native empty-request Ren'Py preflight before expensive player-attach
  analysis, so an incompatible or broken game fails early.
- Added current/total progress, percentage, elapsed time, and ETA for scene,
  transport, sprite inventory, and unique-form analysis, including large mods
  with thousands of forms. Native Ren'Py capture publishes sparse atomic
  checkpoints so this remains visible even when a game buffers console output.
- Kept those checkpoints atomic while retrying transient Windows sharing
  violations from an old Ren'Py writer racing the setup window's reader.
- Reduced lossless form-analysis bookkeeping by checkpointing the manifest in
  small batches and atomically writing the final manifest; generated textures
  and final data are unchanged.
- Moved independent sprite-form analysis from GIL-constrained threads to an
  adaptive process pool (up to 16 logical workers). Each form still executes
  the same reference calculation and writes the same lossless PNG texels.
- Made managed-copy removal tolerate the short-lived Windows file handle that
  Ren'Py can retain after its last window closes. Removal retries only the
  ownership-verified private path and gives a clear close-the-game message if
  another process continues to use it; the selected mod is never targeted.
- Clarified cross-vendor behavior: live Ren'Py relighting uses the supported GPU
  renderer on Intel, AMD, and NVIDIA; optional first-time CUDA analysis remains
  NVIDIA-specific with the exact CPU analyzer as the universal fallback.
- Recommend the optional CuPy analyzer only when both NVIDIA hardware and a
  compatible local CUDA toolkit are detected, avoiding a useless CUDA download
  on display-driver-only systems and disposable graphics-only VMs.
- Added the optional Preview & Calibrator, which executes the production GPU
  shader directly and supports still images, animated sprites, GIFs, and video
  backgrounds without maintaining a second lighting implementation.
- Added Relit, Original, and split comparison views for visual calibration.
- Added bounded, versioned calibration profiles shared by the preview,
  managed player attachments, and embedded mod-author integrations.
- Stored player calibration outside selected projects by default. Explicit
  project-config export preserves existing discovery settings and requires a
  visible user action.
- Moved preview analysis caches out of the source checkout and into the user's
  SceneLight application-data directory.
- Added clear dependency guidance when the preview is opened on a fresh Python
  installation, while retaining explicit confirmation before package download.
- Isolated source-ZIP dependencies in `%LOCALAPPDATA%\SceneLight\python-env`
  instead of changing the user's global Python packages, with exact runtime and
  packaging-tool versions and a release vulnerability audit.
- Added automatic adjacent `wheelhouse` detection for a fully offline,
  shell-free dependency installation using the same Setup window.
- Hardened generated Windows launcher arguments against environment-variable
  expansion in unusual project paths.
- Added a clean-Windows validation plan covering disposable installation,
  read-only host inputs, complete removal, CPU fallback, and separate physical
  GPU verification.
- Advanced the generated manifest to version 6 for calibration metadata.
- Made runtime-only asset capture native-first and compatible with both Ren'Py
  7/Python 2 and Ren'Py 8/Python 3 projects, with an optional SDK fallback only
  when a project has no bundled runtime.
- Corrected native Ren'Py 7 capture registration, displayable resolution,
  rendering, atomic result publication, and process launch semantics.

### Internal build 1.5.0 (pre-release)

- Added optional live GPU rain/wetness and glitch/corruption effects after the
  approved physical relighting pass. Both can be applied scene-wide or to one
  character and are deterministic under save/load, rollback, skip, motion, and
  scene transitions.
- Added a player effects panel on `Shift+F8` and a small `scenelight_fx` API for
  mod authors. All effect intensities default to zero, preserving the approved
  relighting output byte-for-byte until an effect is explicitly enabled.
- Kept effects universal: no character names, filenames, palettes, or scene
  presets select their behavior.
- Removed the experimental automatic eye-glow feature after cross-sprite visual
  validation found unacceptable false localization. No detector, eye metadata,
  shader branch, API, or player control for it ships in this release.
- Fixed actual shader-render compatibility with Ren'Py 7.5.3, including its
  older full-bounds texture API and declaration ordering. This was verified by
  rendered rain/glitch captures, not only by launching the mod.

### Internal build 1.4.0 (pre-release)

- Split the setup window into an ordinary player attachment and an explicit
  mod-author integration, with clear source-mutation warnings for the latter.
- Added ownership-safe `embed`, `embed-status`, and `unembed` commands. Author
  integration writes only a previously nonexistent reserved namespace and a
  hash manifest; removal refuses before deleting anything when it finds a
  modified or unowned file.
- Included plain-text manual recovery instructions inside every embedded
  integration so authors can restore the original source layout without the
  SceneLight application.
- Preserved the read-only managed-copy workflow as the default for players.

### Internal build 1.3.0 (pre-release)

- Replaced in-place mod injection with an isolated managed sidecar under the
  user's local application data. The selected game or mod is now read-only.
- Launch SceneLight gameplay with each distribution's own bundled Ren'Py
  executable instead of forcing the analysis SDK onto an older mod.
- Synchronize ongoing source edits before launch and rebuild lighting only when
  relevant scripts, archives, backgrounds, sprites, or videos changed.
- Added one-click managed-copy removal. Removing SceneLight leaves the selected
  game and its normal launcher untouched and independently playable.
- Preserved native runtime saves and caches inside the managed copy without
  importing source-project saves or compiler caches.
- Validated the sidecar against Green Eyes on its bundled Ren'Py 7.5.3 runtime,
  eliminating the cross-version `Init.varname` startup crash.

### Internal build 1.2.1 (pre-release)

- Kept Ren'Py's temporary GPU capture surface hidden during setup and exposed
  dynamic-sprite progress in the SceneLight window.
- Made runtime capture finish reliably when a mod overrides `label quit`, fails
  during startup under a resolver SDK, or enters Ren'Py's error-display path.
- Published capture results atomically so the setup supervisor can distinguish
  a complete render from an interrupted one.

### Internal build 1.2.0 (pre-release)

- Added a native Windows setup window with project selection, read-only scan,
  planned-change review, explicit install confirmation, verification, launch,
  and a complete visible activity log.
- Added NVIDIA detection and an explicit CUDA dependency/performance option so
  the GUI cannot silently downgrade a requested accelerated install to CPU.
- Preserved the existing CLI contract for automation and non-Windows use.
- Added exact CUDA background analysis with approved CPU fallback, reusable
  caches, and the full live hybrid GPU runtime.
- Added automatic target-Ren'Py capture for LayeredImage and archive-backed
  declarations without prebaking final relit sprites.
- Added source-release ZIP/checksum automation and Windows multiprocessing-safe
  launchers.
