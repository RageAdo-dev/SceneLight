# Architecture

## Native-runtime installation modes

The default separate-copy mode treats the selected folder as read-only input.
SceneLight copies authored files into a path-keyed managed project under
`%LOCALAPPDATA%\SceneLight\projects`, using normal copies rather than hard
links. Generated runtime scripts, maps, capture output, caches, and launchers
exist there. A separate path-keyed analysis cache under
`%LOCALAPPDATA%\SceneLight\analysis-cache` retains only capture and transport
work whose source fingerprints and algorithm contracts still match. Source
saves and compiler caches are excluded; saves and caches produced by the
managed game's native runtime are preserved.

The optional in-place mode adds only the previously unused
`game/scenelight_runtime` namespace and a root ownership manifest. It does not
replace an authored file. Every added file is recorded by hash, and removal
refuses before deleting anything if a file is missing, modified, or mixed with
unowned content.

The managed copy's native Ren'Py runtime is the first choice for resolving
dynamic or archive-backed displayables. An optional compatible SDK is only a
fallback for projects without a bundled executable. After capture, source-owned
files are synchronized again so analysis compiler output cannot reach gameplay.
Playback is always started by the copied distribution's own executable and
therefore retains the mod's intended Ren'Py/Python version. Relevant source edits
trigger a rebuild before launch; unchanged projects reuse their maps immediately.
Removal deletes only a sidecar whose ownership marker and managed-root boundary
both validate.

The builder retains two independent cached products for installation and compatibility:

1. **Scene transport** - irradiance, emitter, wrap, and a 26-plane position
   atlas measured from the background alone at a 16x9 grid.
2. **Sprite form** - normals/noise, height/AO/edge, and a compact directional
   response LUT reconstructed from each source expression alone.

The default `scene_analysis: live` captures one fallback state per background.
It never inventories a whole movie or samples an animation timeline for lighting.
`scene_analysis: cached` retains the complete offline timeline builder. Changing
this option invalidates the requested capture plan while preserving reusable
sprite pixels.

The static scanner handles ordinary source declarations. When declarations
exist only as `LayeredImage` objects, compiled script, or archive-backed image
registry entries, the installer launches the managed copy's native runtime in an
inert resolver mode, falling back to a compatible SDK only when necessary. That
pass renders raw transparent source expressions only. Its results are
content-signature cached and become form inputs; they are not final relit
character frames.

Large runtime plans use a plan-once, capture-many protocol. The planner keeps
Ren'Py's first valid longest-prefix spelling, but journals completion under the
tag plus sorted attribute set because Ren'Py's image state treats attributes as
an unordered set. This makes native renderer restarts deterministic even when a
game's attribute traversal order changes between interpreters.

When the plan exceeds the adaptive threshold, SceneLight creates short-lived
runtime clones beside the already disposable managed project. Immutable archive,
media, executable, engine source, and engine bytecode are hard-linked where the
filesystem allows it; authored game scripts, compiler state, cache, saves, logs,
and output remain private to each worker. This preserves game-supplied
single-instance guards without patching them. CPU, live free memory, and workload
select up to six workers. Ordered forms are divided into balanced contiguous
ranges so each runtime loads fewer unrelated character families. Healthy workers
run to completion; a crashed worker alone resumes from its semantic journal.
Workers share only a process-safe, content-named PNG component store and write
separate form journals/results. The host supervises isolated process trees,
merges the ordinary capture contract, requires every planned form, then removes
the temporary clones.

The protocol version, plan version, and pixel version are separate cache
contracts. UI text or progress changes do not invalidate pixels; form-planning
changes invalidate the plan; only changed pixel logic invalidates raw captures.

## One renderer, two hosts

`runtime/live_gpu.py` implements the complete frame-dependent scene analysis
using the standard library and the host's current graphics context. Both hosts
run the same resize, linear-light preparation, robust statistics, connected
components, creative hue classification, exposure meters, probes, transport
synthesis, emitter field, and environment wrap. OpenGL compute shaders accelerate
labeling, histograms, compaction, and sorting when supported. A raster path
implements the same model without compute shaders or CUDA.

Ren'Py loads the shared module and `live_renpy.py` from owned `.txt` resources
through its asset loader, including archives. Its background displayable taps the
actual child Render after image transforms and placement. It shares a showing
binding across current-store copies. One analysis workspace serves the renderer;
completed fields are small, engine-owned textures. Sprite snapshots retain a
specific completed frame. GPU objects reside outside the save/rollback store;
restored bindings request fresh fields at the next interaction.

Shaders using Ren'Py's draw-time `u_time` or `u_random` uniforms redraw even when
their child Render is cached. Their background canvas is captured at the full
drawable resolution and reused for display, so analysis and display share the
same shader output and random sample. The child/focus tree and placement remain
attached. Transition snapshots pin that completed canvas through a separate weak
reference, rather than saving a GPU object or running the shader again.

The transport texture retains its canonical 26 planes and 16×9 placement grid.
A tenth row stores grain and sharpness in two 24-bit RGB values. Native image
fields follow Ren'Py's premultiplication contract. Preview retains its existing
straight-alpha inputs and display-space wrap. Host GL state, including pixel
layout, samplers, optional compute bindings, and framebuffer state, is restored.

The Preview & Calibrator extracts the production vertex and fragment source
from the packaged Ren'Py runtime and compiles it in an OpenGL 3.3 widget. It
binds the same scene transport, sprite form, calibration blocks, and placement
values as the game. The tester is therefore a second host for one renderer, not
a visually similar reimplementation. Ren'Py always binds comparison mode to
Relit; the preview alone can request Original or a shader-level split view.

Calibration has a versioned schema and nineteen bounded scalar controls. Its
approved defaults are the shader's validated constants. Global values and
optional per-scene overrides are serialized into manifest version 6 as five
`vec4` uniform blocks. A separate bounded strength value is serialized at the
manifest root because it mixes the whole physical result and also compresses
automatic exposure. Player profiles live beside the managed projects under
application data. A mod author must explicitly export a project-owned profile.

The default source-color path is an energy-balanced physical aggregate.
Saturated source saliency is also divided into canonical red-, green-, and
blue-family transport slots. A majority vote over the exact placement analyses
chooses one semantic layout for the whole 16x9 scene grid, so bilinear sampling
can never blend a physical-component plane with a hue-family plane. During
video playback, a layout change fades incompatible secondaries out and back in
through the continuously interpolated primary key rather than hard-switching
or morphing unrelated lights. `adaptive_light_colors` measures pairwise chroma,
screen-space distance, energy, and confidence. It separates either two strong,
genuinely distinct colored families or one strong colored practical separated
from a neutral key. Weak single-color evidence and ordinary neutral scenes
remain on the aggregate path.
`individual_light_colors` is a manual creative override that can force and
exaggerate the same directional lobes and colored rim contributions.

The public Physical, Cinematic, and Separate mode presets all resolve to complete
calibration/strength states. Cinematic uses the validated 0.72 strength,
-0.22-stop bias, 0.92 adaptation, and separated-source branch. A scripted
strength at a matching scope replaces the profile default; only the player's
persistent master strength remains multiplicative.

The Ren'Py fragment shader combines both using the final transformed sprite
position every frame. It performs diffuse response, directional form shading,
multi-light transport, environment probes, edge/rim response, ambient
occlusion, highlight rolloff, and camera/color matching in linear light. The
form cache travels with the displayable, while scene transport is sampled from
the character's current transformed screen position. ATL movement, placement
changes, and zoom therefore update the lighting without regenerating an image.

Third-party model shaders are separated by an explicit render-to-texture
boundary. SceneLight never imports a child render's shader list, uniforms, or GL
properties into its model. Image-declared effects therefore finish as the
sprite texture, while ordinary `show ... at CustomShader` mesh transforms remain
outer passes. The fragment also begins with the existing `gl_FragColor`, so an
author who intentionally combines lower-priority shader parts on one model does
not have that earlier result replaced by a fresh `tex0` sample.

No subject name, source filename, or subject palette is allowed to alter scene
exposure. This is what makes the same pipeline usable for pale clothing, black
fur, brightly colored anime art, and non-human transparent sprites.

Scene-wide transitions render into another framebuffer. The runtime captures
the exact last presented frame only when a supported scene changes and uses it
as the transition's old side, preventing premature color changes. Instant
scene swaps select the new field on the same interaction.

## Optional post-relight effects

Rain/wetness and glitch/corruption are independent, opt-in branches at the end
of the production character shader. Their uniforms come from rollback-aware
Ren'Py store state and their procedural clock is `renpy.get_game_runtime()`.
The rain branch combines directional wet-surface response with deterministic
sprite-space streaks; the glitch branch combines scanlines, block corruption,
tearing, and RGB separation. Scene settings may be overridden by image tag.

Both branches are guarded by a strictly positive intensity and default to
zero. A GL2 capture against the protected pre-effects renderer is therefore a
byte-identical image when effects are disabled. The public tree contains no
automatic eye detector or always-on eye-glow path: broad custom-sprite QA showed
that inferring semantic eye locations from arbitrary transparent art was not
reliable enough to publish. The opt-in Eyes Everywhere preset instead exposes
an explicit normalized source region that an author can calibrate.

Validated JSON effect packs add independent shader parts at fragment priority
600. Active custom parts run in a bounded post-lighting texture pass, so spatial
effects sample the completed lit character rather than the unlit source or any
private transport atlas. They can also run through a texture-only path when no
background has a SceneLight record. A fixed priority-900 alpha guard clamps the
final premultiplied color to the final alpha, preventing an effect that adds RGB
to transparent pixels from revealing the sprite's rectangular canvas. Pack
state uses the same rollback-aware scene/character scopes as built-in effects.

Heavy included VFX are trusted declarative presets. Their pack files contain
only identifiers, metadata, and bounded default values; SceneLight supplies the
versioned GLSL contract. Preset helpers receive an explicit per-effect namespace
before Ren'Py registers them, avoiding helper collisions across sequential
post-lighting passes. Fire, lightning, aura, particles, trails, and shockwaves
are evaluated live from `u_time`; no generated or prepainted VFX imagery is
packaged. The eye-mutation preset resamples a configurable region of the
already-lit source character, so it transforms the real sprite rather than
substituting character art.

## Optional developer embedding

The setup app offers a managed player copy or a reversible in-place attachment.
The in-place workflow first produces the same verified managed build,
then copies its runtime into `game/scenelight_runtime/` and records every added
file in `.scenelight_developer_install.json`. Ren'Py recursively loads the
reserved `bootstrap.rpy`, so the project's normal executable gains the same
live GPU runtime without patching a story, image declaration, GUI, or engine
file.

Installation is create-only: either reserved path already existing is a hard
failure. Uninstallation is validate-then-delete: manifest paths must remain
inside the reserved namespace, owned hashes must match, and no unknown file may
be present. Ownership paths are project-relative, so the check remains valid
after a source checkout is moved or cloned. The operation performs no deletion
until all checks pass. This
gives source control and manual recovery a narrow, auditable boundary while
avoiding compatibility-sensitive script rewriting.

Direct developer manifests also retain a lightweight metadata inventory of
authored visual inputs under `game/`, plus the root `scenelight.json` and a
privacy-safe external-profile marker. Generated caches, saves, source-backed
`.rpyc`, test captures, and the reserved runtime are excluded. Setup can therefore
detect a new/changed background, video, script, sprite, or profile without
hashing or opening hundreds of images on Tk's UI thread.

Refresh performs ownership preflight before analysis, builds in the isolated
managed project, stages the completed runtime beside the owned namespace, then
renames the old and new directories on the same volume. The manifest is replaced
atomically only after the new hashes exist. A failed swap restores the previous
directory/manifest; legacy launcher backup/config files are explicitly carried
forward so normal-EXE removal remains recoverable.

Every direct and separate-copy manifest records the public SceneLight version,
runtime/API and generated-data contract versions, plus a deterministic shipped-
content fingerprint. A missing product version is classified as a pre-1.0
internal build. Setup never silently replaces a pre-release, older, newer, or
same-version/different-content installation: it scans first when required, then
offers update, keep-and-launch, and cancel choices. Direct updates use the
transaction above. Separate-copy updates never modify the selected source game
and are verified before Play is offered. An explicit removal deletes only the
selected project's verified managed/direct installation and deterministic
path-keyed analysis cache; unexpected paths or symlinks are refused.

Form-map version 3 composes and hashes each original RGBA form before deriving
its transport textures. Large forms are reconstructed at a deterministic
512-pixel maximum dimension; the manifest separately records original
`source_size`, derived `map_size`, and the original pixel SHA-256. Normalized UV
placement and the 64×64 directional response remain unchanged, and the two RGB
surface textures remain lossless PNGs. The bound is identical on every computer,
so faster hardware does not silently produce a different lighting result.

Streamed Preview video decoding runs on a dedicated one-worker executor. Decode
completion notifications and presentation deadlines drive a bounded one-frame
lookahead. The Qt paint context uploads the selected frame and performs live
analysis only when that frame changes. Placement changes update three values and request a
GPU repaint; they never call the scene analyzer, form reconstructor, or decoder.

An emitter is fixed in background coordinates, so each background frame performs
connected-component source classification once. The complete 16x9 transport
grid still evaluates position-dependent exposure meters, eight irradiance
probes, broad gradients, source visibility, and source-to-surface directions.
This keeps moving and multicolored light spatial while avoiding 144 redundant
classifications of the same frame.
