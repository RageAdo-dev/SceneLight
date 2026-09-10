# SceneLight mod-author API

SceneLight has one Windows entry point: **SceneLight.bat**. The opening window
supports both player installations and the explicit **For mod developers**
workflow. After setup, players start the game's normal executable; no gameplay
BAT is required. The developer workflow analyzes the selected project and
installs the runtime and script API under the reserved
`game/scenelight_runtime/` folder.

The author installer does not rewrite existing `.rpy` files. It writes an
ownership manifest and refuses to overwrite an existing SceneLight folder.
Safe removal verifies every owned file first. This makes the installed folder
suitable for source control and distribution with a mod.

## Choose the character families

The setup app scans first, then presents every semantic image family it can
identify with a representative preview. For archive-only projects it performs
that review with the project's compatible Ren'Py renderer in an isolated copy,
so `Character` and `LayeredImage` families do not depend on filename guessing.
Check the character tags and leave UI, stickers, props, cut-ins, and poem art
unchecked. This manual selection is the authoritative default; unchecked
families cannot be reintroduced by later discovery. You can also enter an
unusual or intentionally small character's Ren'Py image tag directly.

Authors who deliberately prefer inference can select **Automatic suggestions**
in the same window. The selection is stored outside the project while testing.
To commit it with a mod, use the equivalent project configuration:

```json
{
  "character_selection": "manual",
  "character_tags": ["monika", "natsuki", "sayori", "yuri"]
}
```

## Refresh after adding project assets

Separate managed copies detect changed scripts, images, videos, and profiles on
normal launch. A direct author installation also records exactly which visual
inputs were analyzed. When Setup reports project changes:

1. choose **Check new assets**;
2. check any newly suggested semantic character family, or type a custom Ren'Py
   image tag explicitly; and
3. choose **Update SceneLight**.

Unchanged transport/form maps remain content-cached. The existing owned runtime
stays installed while the new build runs, and refresh verifies it again before
transactionally swapping the completed namespace. It refuses to start analysis
if an owned file is missing, modified, or mixed with unknown content. A failed
directory swap restores the previous verified runtime and ownership manifest.

New poses using an already selected tag can use the generic surface fallback
immediately, but refresh generates their exact maps. A new background or video
is intentionally not assigned some other scene's transport; refresh measures its
own lighting first. This preserves the Studio-quality model instead of hiding
staleness with a tint or guessed character/background rule.

## Whole-mod lighting

Once the author installation is complete, SceneLight is active throughout the
mod. Existing `scene`, `show`, `hide`, ATL, and dialogue statements do not need
to change.

Automatic suggestions are intentionally conservative. A registered image is lit
only when SceneLight can establish that it is a foreground character family.
Small stickers, UI art, logos, poem pages, cut-ins, and props are left alone
even when they use `show` on the master layer. This prevents decorative art
from inheriting character lighting merely because it shares Ren'Py's image/tag
mechanism.

For an unusual small character or other intentional exception, include the tag
in the review window or in `scenelight.json` before running the author installer:

```json
{
  "character_selection": "manual",
  "character_tags": ["chibi_hero"]
}
```

The same opt-in can be declared during init when the runtime is already
installed:

```renpy
init python:
    scenelight_register_tag("chibi_hero")
```

To keep a particular registered family unlit, use the ordinary authored rule:

```renpy
init python:
    scenelight.character("sayori_sticker", enabled=False)
```

Use one optional call near the beginning of the story to set the whole-mod
baseline:

```renpy
label start:
    $ scenelight.configure(strength=1.0, color_adaptation=0.78)
    jump chapter_one
```

The generated background and sprite analysis remains the automatic baseline.
API values adjust that result; they do not replace it with fixed lighting.

## Third-party shaders and MVN templates

SceneLight preserves Ren'Py model-based shader transforms as independent GPU
passes. The
[Make Visual Novels! RenPy Shader Pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
works with SceneLight unchanged, including its aberration, simulated-lighting,
animated, Manga, VHS, noise, reveal, and color presets. Its transforms already
set `mesh True`, which is the correct isolation boundary for layered sprites.

Use MVN transforms through ordinary Ren'Py syntax:

```renpy
show sayori teeth at wf21, IntenseAberate
show yuri 1a at t11, SunsetLighting
```

With `show ... at MVNTransform`, SceneLight relights the selected character
first and Ren'Py applies MVN as the final pass. SceneLight does not copy,
replace, rename, or merge MVN's shader names and uniforms. MVN animation clocks
and ATL movement continue normally.

An MVN transform placed inside an image declaration also works, but the order is
reversed: MVN renders into the image first and SceneLight adapts that result to
the scene. Use the ordinary `show ... at` form when the MVN preset must be the
exact final look.

MVN's `SimulatedLighting` and SceneLight are both lighting effects, so combining
them deliberately produces both contributions. For an exact MVN-only lighting
preset, bypass SceneLight for that character or sequence:

```renpy
$ scenelight.off()
show sayori at TheFuzz
# ...
$ scenelight.clear_scene()
```

or keep other characters relit while excluding one tag:

```renpy
init python:
    scenelight.character("sayori", enabled=False)
```

SceneLight still only touches explicitly selected character families. A shader
that an author applies to an entire Ren'Py layer or camera will affect that
layer's contents by design; place UI on a separate layer when that third-party
effect should not process it.

## Per-scene control

Use `scenelight.scene()` before showing the characters that need the override.
Scene values remain active until `clear_scene()` is called, and participate in
Ren'Py save, load, and rollback.

```renpy
label power_outage:
    scene bg club_night
    $ scenelight.scene(
        strength=0.82,
        exposure_bias=-0.35,
        color_adaptation=0.92,
        rim_strength=0.78,
        light_mode="physical",
    )
    show monika 1a at t11
    m "The power is out."

    $ scenelight.clear_scene()
    return
```

Temporarily disable lighting for a sequence, then restore the inherited
whole-mod and named rules:

```renpy
    $ scenelight.off()
    scene black
    show special_flat_art
    "This image is intentionally unlit."
    $ scenelight.clear_scene()
```

`scenelight.on()` explicitly enables the current sequence. `enable()` and
`disable()` are equivalent aliases. A scene-level `off()` is a hard bypass:
character and exact-image rules cannot accidentally turn lighting back on
until `clear_scene()` is called.

## Reusable rules

Rules can be authored once instead of repeated in every label:

```renpy
init python:
    # The optional leading "bg" is accepted either way.
    scenelight.background("bg rooftop sunset", exposure_bias=-0.18,
                          color_adaptation=0.94, rim_strength=0.82)

    # Applies to every image whose Ren'Py tag is "yuri".
    scenelight.character("yuri", strength=0.94, highlight_rolloff=1.35)

    # Applies only to this exact registered image name.
    scenelight.image("monika 1e", rim_strength=0.9, specular_strength=0.3)
```

The precedence from broadest to most specific is:

1. whole-mod defaults;
2. the current background;
3. the current script-scene override;
4. the character tag; and
5. the exact image name.

More-specific values override only the settings they define. Other values keep
flowing through from broader scopes and automatic analysis.

## Lighting settings

Every scope accepts the same keyword settings.

| Setting | Range | Meaning |
| --- | ---: | --- |
| `enabled` | boolean | Enables or bypasses SceneLight at this scope. |
| `strength` | 0–2 | Final mix between the original and relit sprite. |
| `auto_strength` | 0–2 | Strength of the automatic scene match. |
| `exposure_bias` | -4–4 | Exposure compensation in stops. |
| `ambient_strength` | 0–2 | Environmental illumination. |
| `color_adaptation` | 0–2 | Adaptation to the scene's light color. |
| `contrast_match` | 0–2 | Match to the background's contrast. |
| `saturation_match` | 0–2 | Match to the background's saturation. |
| `highlight_rolloff` | 0–2 | Protection and compression of bright sprite colors. |
| `key_strength` | 0–2 | Directional key-light response. |
| `ray_shadow_strength` | 0–2 | Screen-space light blocking and directional shadowing. |
| `ambient_occlusion` | 0–2 | Recessed-form and contact darkening. |
| `probe_strength` | 0–2 | Local irradiance-probe contribution. |
| `bounce_strength` | 0–2 | Indirect environmental bounce light. |
| `specular_strength` | 0–2 | Surface highlight response. |
| `rim_strength` | 0–2 | Edge light from nearby sources. |
| `wrap_strength` | 0–2 | Soft light wrapping around reconstructed form. |
| `grain_match` | 0–2 | Match to the scene's image texture. |
| `shadow_strength` | 0–2 | Overall authored shadow response. |
| `individual_light_colors` | 0–2 | Separates detected source colors for a stylized result. |
| `adaptive_light_colors` | 0–2 | Automatically separates strong colors only when their emitters are spatially and chromatically distinct. |

SceneLight has three deliberate light modes:

- `light_mode="physical"` keeps the energy-balanced measured-light result and
  automatically preserves distinct source directions when the scene contains
  multiple strong colored emitters (`individual_light_colors=0.0`,
  `adaptive_light_colors=1.0`). Ordinary and single-hue scenes remain on the
  combined path.
- `light_mode="cinematic"` uses restrained separated source colors with
  compressed automatic exposure: `strength=0.72`, `exposure_bias=-0.22`,
  `color_adaptation=0.92`, and `individual_light_colors=1.0`.
- `light_mode="separate"` keeps the fully exaggerated source-color treatment
  (`individual_light_colors=1.0` at the current strength).

Set `adaptive_light_colors=0.0` for a strict aggregate-only result. This is not
needed for normal scenes; it is an explicit compatibility/authoring override.

Explicit settings in the same call override a mode preset regardless of keyword
order. For example, `scenelight.scene(light_mode="cinematic", strength=0.84)`
keeps the cinematic exposure/color behavior at the authored strength. The
aliases `lighting_strength`, `exposure`, and `separate_light_colors` are also
accepted.

A light mode is a complete look: selecting another mode at the same scope resets
that scope's lighting values to the selected preset before applying explicit
values from the call. A saved Preview strength is the global default; an authored
`strength` at a matching scope replaces it rather than multiplying it.

## Clearing and inspection

```renpy
$ scenelight.clear_defaults()
$ scenelight.clear_scene()
$ scenelight.clear_background("rooftop sunset")
$ scenelight.clear_character("yuri")
$ scenelight.clear_image("monika 1e")
$ scenelight.reset()
$ current_rules = scenelight.state()
```

Calls at the same scope merge. For example, two consecutive `scene()` calls can
adjust exposure and rim strength independently. Clear the scope to inherit its
values again.

The optional effects API remains separate, so lighting controls can be combined
with rain, wetness, or glitch effects without either API resetting the other:

```renpy
$ scenelight.scene(exposure_bias=-0.2, rim_strength=0.8)
$ scenelight_fx.scene("rain", intensity=0.75, wetness=0.82)
```
