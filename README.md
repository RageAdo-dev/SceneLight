# SceneLight for Ren'Py

SceneLight matches transparent character sprites to the lighting of the current
background. Lighting follows characters while they move, change pose, enter,
leave, or move between scenes.

SceneLight prepares supported movie backgrounds once during setup, preserving
the full lighting calculation for every frame in a lossless cache. Playback
reuses those results while Ren'Py draws the characters normally. Procedural or
visually transformed backgrounds use live analysis of their actual appearance.
Preview uses the same scene analyzer and lighting shader as the Ren'Py runtime.

This is a private development candidate. See [compatibility and validation](docs/BETA_VALIDATION.md)
for tested workflows and limits; automatic mapping does not cover every game.

## Use SceneLight with a game or mod

This section is for players. You do not need to edit Ren'Py scripts.

1. Download the Windows ZIP from **Releases** and extract it.
2. Double-click `SceneLight.bat`.
3. Choose the folder containing the game's `.exe` and `game` folder.
4. Scan the game and review the detected character groups.
   Uncheck stickers, interface art, props, and anything else that should not be
   lit as a character.
5. Choose one installation:
   - **Add to this game** keeps one game folder and adds SceneLight reversibly.
   - **Create separate copy** leaves the selected folder untouched and creates a
     SceneLight-enabled copy.

Setup checks the selected folder in the background, so the window stays
responsive. If SceneLight is already present, Setup offers the appropriate next
step and does not overwrite unknown files.
6. When setup finishes, launch the normal game `.exe`.

The first setup installs the components required to analyze and play the game,
then prepares character surfaces, background fallbacks and supported movies.
Movie preparation takes time and disk space once; later playback does not repeat
that analysis. Qt Essentials and the video decoder are included in normal player
setup. The larger Preview & Calibrator interface remains optional and is installed
when you open it. Preview can be opened from **Settings → Tools** before selecting a
game; selecting a game only associates that project's saved calibration
profile. Setup shows downloads, installation, analysis progress, and skipped
assets as they happen.
Later launches reuse the cache. If one image cannot be analyzed, SceneLight
reports and skips it instead of failing the whole installation.

Very large archive-only mods are divided across isolated Ren'Py workers chosen
from the current CPU count, free memory, and number of forms. This does not run
Ren'Py rendering APIs on unsafe background threads. If a renderer process exits,
the Activity log reports the retry and only that worker resumes its completed
semantic forms. Healthy workers remain alive, and ordered forms stay grouped for
better character-family cache locality. Every long discovery, capture,
checkpoint, and pixel-preparation phase shows current/total progress rather than
leaving an old 100% message on screen.

Resizing or maximizing the game can briefly pause while Ren'Py recreates its
full GPU render targets, so set the window size before continuing the story when
possible.

SceneLight checks the game and its graphics renderer before starting the
installation analysis. Preparation and live analysis use standard OpenGL, with an
optional compute-shader acceleration path. Playback does not require NVIDIA CUDA.

A dedicated graphics card is not required: compatible graphics integrated into
an Intel or AMD processor can run the lighting shaders. Live analysis requires
OpenGL 3.3 or OpenGL ES 3.0 with floating-point rendering and accumulation.
The renderer checks these capabilities. The project option
`"scene_analysis": "cached"` retains full offline scene preparation for older
renderers; the default is `"live"`. Modern Ren'Py itself needs
working graphics acceleration; its old software renderer has been removed.
See [Ren'Py's graphics requirements](https://www.renpy.org/doc/html/display_problems.html).

For games that keep scripts or images in Ren'Py archives, this review runs the
game's own compatible renderer against an isolated working copy. SceneLight
shows one representative preview for each semantic character family instead of
guessing from every image filename. Newly found families remain unchecked until
you select them, or you can explicitly choose **Automatic suggestions**.

If a prerequisite is missing, SceneLight names exactly what it needs and asks
before installing it into SceneLight's folder under `%LOCALAPPDATA%\SceneLight`.
It does not require administrator access, modify system Python or PATH, upload
game art, install a service, or run at startup. Publishers may also provide an
optional offline release for computers without internet access. If SceneLight's
registered runtime files were removed outside Setup, the verified Python
installer repairs them only when Windows records the install location as
SceneLight's exact owned directory; an unrelated Python installation is never
repaired or changed.

Use **Settings** to:

- change which image groups count as characters;
- open the Preview & Calibrator;
- verify or remove an installation; and
- view every required component individually, plus technical details and the
  activity log.

Before removing an in-place installation, SceneLight checks that none of its
files were changed and backs up current saves again. If a legacy Ren'Py 6 game has
saves written by SceneLight's Ren'Py 7 compatibility runtime, removal keeps one
small verified `game/scenelight_save_compat.rpy` bridge so the original engine
can still load that progress. The bridge contains no lighting code. A
managed-copy installation never changes the selected original. Only use games
and mods you trust: SceneLight does not make third-party Ren'Py code safe.

## Use SceneLight in a Ren'Py project

This section is for modders and game creators. The same download includes the
complete author API; there is no separate developer package or launcher.

1. Double-click `SceneLight.bat` and select **For mod developers**.
2. Choose the project folder containing `game`.
3. Scan the project and review the character tags SceneLight found.
4. Select **Install developer API**.

The installer adds SceneLight under `game/scenelight_runtime`. Existing scripts
are not rewritten. The project continues to use its
normal executable and ordinary `scene`, `show`, `hide`, ATL, and transition
statements. SceneLight is automatic by default, so this is enough to enable it
for the whole project.

### Select characters explicitly

Automatic suggestions are only a starting point. Register actual character
tags and exclude non-character images such as stickers or props:

```renpy
init python:
    scenelight_register_tag("hero")
    scenelight_register_tag("sayori")
    scenelight.character("sayori_sticker", enabled=False)
```

This targets Ren'Py image tags, not filenames. An image such as
`show hero happy at right` keeps the same script syntax and receives lighting
because its tag is `hero`.

### Whole-project defaults

Set a baseline once during initialization:

```renpy
init python:
    scenelight.configure(
        strength=1.0,
        color_adaptation=0.78,
        light_mode="physical",
    )
```

`light_mode="physical"` uses energy-balanced behavior and automatically keeps
multiple strong, differently colored emitters spatially distinct. A red source
on the left and cyan source on the right illuminate different parts of the
sprite. A strong colored practical can also separate from a neutral key; weak
props and ordinary single-hue scenes remain on the normal combined path.
Use `light_mode="cinematic"` for a restrained colored-light treatment with
compressed scene exposure, or `light_mode="separate"` for the fully exaggerated
look in which the strongest individual light colors remain distinct across the
sprite. Explicit values in the same call override a mode preset.

### Per-scene control

Override only what a scene needs, then clear the override:

```renpy
label rooftop_sunset:
    $ scenelight.scene(
        exposure_bias=-0.20,
        rim_strength=0.82,
        light_mode="physical",
    )
    scene bg rooftop sunset
    show hero happy at right
    hero "The normal Ren'Py workflow does not change."

    $ scenelight.clear_scene()
```

Temporarily disable and restore lighting around intentionally flat artwork,
menus, CGs, or special effects:

```renpy
$ scenelight.off()
show chapter_card
$ scenelight.on()
```

### Reusable rules

Rules let a background, character tag, or exact image carry its own adjustment:

```renpy
init python:
    scenelight.background(
        "bg rooftop sunset",
        exposure_bias=-0.18,
        rim_strength=0.76,
    )
    scenelight.character(
        "yuri",
        strength=0.94,
        highlight_rolloff=1.35,
    )
    scenelight.image(
        "monika 1e",
        rim_strength=0.90,
        specular_strength=0.30,
    )
```

Specific image rules override character rules, which override the global
configuration. A temporary `scenelight.scene(...)` override is intended for the
current sequence and is removed by `scenelight.clear_scene()`.

Optional rain, wetness, and glitch effects are disabled unless requested:

```renpy
$ scenelight_fx.scene("rain", intensity=0.75, wetness=0.82)
$ scenelight_fx.character("monika", "glitch", intensity=0.65)
$ scenelight_fx.clear_all()
```

The Preview & Calibrator can inspect a background, sprite, animation, or video
before a scene is authored. **Save profile** keeps the complete personal look,
including lighting strength, outside the project; **Export config** writes that
same result into settings intended to be committed by the developer.

When a mod changes, SceneLight does not apply old lighting data to new art.
Separate copies update changed `.rpy`, image, video, and profile inputs before
launch. For a direct developer installation, reopen **For mod developers**,
choose **Check new assets**, review any newly suggested character family, then
choose **Update SceneLight**. The current installation stays playable until the
update finishes.
New poses under an already selected tag remain safely lit by the generic fallback
until refresh creates their exact form maps; a new background waits for its own
measured transport rather than borrowing an unrelated scene.

SceneLight 1.0.0 is the first public release. An installation made by an earlier
internal build has no public product version, so Setup labels it **pre-1.0** and
offers an explicit update instead of silently launching the old runtime. The
confirmation lets players update, keep and launch the current installation, or
cancel. Updates preserve game content, saves, character choices, and profiles.

Preview placement remains live while videos play. Dragging changes only GPU
placement uniforms; video decoding and temporal transport preparation run on
bounded workers and never invoke sprite/background analysis from the drag path.

To remove the author integration, use **Settings → Remove developer API**.
SceneLight checks its installed files and refuses removal if one was changed, so
project edits are not deleted by mistake. Successful removal also clears that
project's path-keyed analysis cache; it never broadens deletion to another game
or SceneLight's shared storage root.

## What SceneLight does

SceneLight estimates exposure, environmental color, contrast, and visible light
sources from a background. It builds reusable surface maps from a transparent
sprite's silhouette and existing shading. Ren'Py's GPU shader combines both at
the sprite's current screen position to produce directional shading, colored
light, rim response, and exposure matching.

Each successfully prepared sprite form receives reconstructed normal, height,
occlusion, edge, grain, material-response, and directional-response data. For
large sprites, the derived per-pixel textures use a deterministic 512-pixel
maximum dimension while retaining the original source dimensions, pixel
identity, normalized placement, and full 64×64 directional response. A newly
added or unsupported form under an explicitly selected character tag uses the
live generic surface fallback until refresh can prepare its exact maps. Neither
path introduces character-specific lighting rules.

This is screen-space 2D relighting. It does not recover hidden 3D geometry from
a flat image.

## Compatibility

- Packaged Ren'Py 7 and Ren'Py 8 games are supported directly; current GPU
  validation includes Ren'Py 8.5.3.
- Original-DDLC-era Ren'Py 6.99 games use a Ren'Py 7 compatibility
  runtime selected by SceneLight after permission.
- The Python 2 compatibility runtime is pinned to Ren'Py 7.7.1. The 7.8.7
  binaries leak uploaded graphics textures; live analysis amplifies that engine
  defect. Setup tests actual texture cleanup and rejects a failing runtime.
  Existing Python 2 projects can use the verified compatibility runtime;
  Python 3 projects should use a corrected Ren'Py 8 runtime. See the
  [upstream report](https://github.com/renpy/renpy/issues/6514).
- Transparent PNG sprites and common Ren'Py image declarations are supported.
- Model-based `mesh True` shader transforms compose as isolated GPU passes. The
  [Make Visual Novels! RenPy Shader Pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
  is renderer-tested unchanged on Ren'Py 7.8.7 and 8.5.2; ordinary
  `show ... at MVNTransform` syntax keeps the MVN preset as the final pass.
- Ordinary image backgrounds and supported Ren'Py animations/video can be
  analyzed.
- Windows is the supported graphical setup platform for this release.

The GitHub source repository also contains tests, build tooling, validation
records, and architecture notes for contributors. Those files are intentionally
not placed in the normal player's download root.

## License

See `LICENSE` and `THIRD_PARTY_NOTICES.md`. Contributor setup and validation
expectations are in `CONTRIBUTING.md`. The reproducible game matrix, clean
Windows procedure, and publication gates are in `VALIDATION.md`; the latest
completed evidence is recorded in `VALIDATION_RESULTS.md`.
