# Lighting API

The in-app **Settings → Advanced → Developer guide** provides searchable commands,
lighting settings, and copyable examples. This page is the written reference.

Install through **For mod developers → Install developer API** before using these
calls. Existing story statements and transforms keep their normal syntax.
[Quickstart](AUTHOR_QUICKSTART.md).

## Character selection and updates

Select character image tags in Setup. A tag covers its poses and expressions;
UI and stickers should remain unchecked. Select effect tags such as `fire` when
you intentionally want them to glow or illuminate characters. To store the selection with a project:

```json
{
  "character_selection": "manual",
  "character_tags": ["hero", "companion"]
}
```

Save this as `scenelight.json` beside `game/`. An installed runtime can also
register a tag during initialization:

```renpy
init python:
    scenelight_register_tag("hero")
    scenelight.character("hero_sticker", enabled=False)
```

After adding assets, use **Check new assets → Update SceneLight**. Existing poses
can use a generic surface until their own maps are ready. Updates reuse valid
analysis and stop if an owned runtime file was changed.

## Scopes and precedence

| Call | Applies to |
| --- | --- |
| `scenelight.configure(**settings)` | Project defaults |
| `scenelight.background(name, **settings)` | A background; the leading `bg ` is optional |
| `scenelight.scene(**settings)` | The current sequence, until cleared |
| `scenelight.character(tag, **settings)` | Every image with that tag |
| `scenelight.image(name, **settings)` | One exact registered image name |

Values apply in that order. A more specific rule replaces only the settings it
contains. Repeated calls at the same scope merge their values. Rule state supports
Ren'Py save/load and rollback.

```renpy
init python:
    scenelight.configure(strength=1.0, color_adaptation=0.78)
    scenelight.background("street_night", exposure_bias=-0.2)
    scenelight.character("companion", strength=0.9)
    scenelight.image("hero worried", rim_strength=0.8)

label power_outage:
    scene bg street_night
    $ scenelight.scene(exposure_bias=-0.35, key_strength=0.7)
    show hero worried at left
    "The lights went out."
    $ scenelight.clear_scene()
    return
```

## Enable, disable and clear

`scenelight.off()` bypasses lighting for the sequence, even if a character or image
rule enables it. `on()` enables the scene scope; `clear_scene()` removes all scene
overrides and restores inherited rules.

```renpy
$ scenelight.off()
show special_flat_art
pause 0.5
$ scenelight.clear_scene()
```

Other clearing and inspection calls:

```renpy
$ scenelight.clear_defaults()
$ scenelight.clear_background("street_night")
$ scenelight.clear_character("companion")
$ scenelight.clear_image("hero worried")
$ scenelight.reset()
$ current_rules = scenelight.state()
```

`reset()` clears all lighting rules. `state()` returns a copy of the current rules.
Aliases: `defaults()` is `configure()`, `enable()` is `on()`, and `disable()` is `off()`.

## Light modes

| Mode | Behavior |
| --- | --- |
| `physical` | Measured lighting with automatic separation of strong, distinct colored sources |
| `cinematic` | A restrained color treatment with reduced strength and exposure |
| `separate` | Stronger separation of individual source colors |

```renpy
$ scenelight.scene(light_mode="cinematic", strength=0.84)
```

A mode resets that scope's lighting values to its preset, then applies any explicit
settings in the same call. Keyword order does not matter. Cinematic sets strength
0.72, exposure bias -0.22, color adaptation 0.92 and individual light colors 1.0.
Physical sets individual light colors 0.0 and adaptive light colors 1.0; Separate
sets individual light colors 1.0. Both reset strength to 1.0 unless the same call
supplies another value. Mode aliases are `combined`/`realistic` for Physical and
`individual`/`creative` for Separate.

An authored `strength` replaces the saved Preview strength at its matching scope.
The player's persistent master strength remains multiplicative.

## Settings

All lighting scopes accept these settings. Numeric values are clamped to their range.

| Setting | Range | Controls |
| --- | ---: | --- |
| `enabled` | boolean | Lighting at this scope |
| `strength` | 0–2 | Overall relighting strength |
| `auto_strength` | 0–2 | Automatic scene matching |
| `exposure_bias` | -4–4 | Exposure compensation in stops |
| `ambient_strength` | 0–2 | Ambient illumination |
| `color_adaptation` | 0–2 | Adaptation to the background's light color |
| `contrast_match` | 0–2 | Contrast matching |
| `saturation_match` | 0–2 | Saturation matching |
| `highlight_rolloff` | 0–2 | Compression of bright colors |
| `key_strength` | 0–2 | Directional light response |
| `ray_shadow_strength` | 0–2 | Directional self-shadowing |
| `ambient_occlusion` | 0–2 | Shading in estimated recesses |
| `probe_strength` | 0–2 | Surrounding light samples |
| `bounce_strength` | 0–2 | Indirect bounce light |
| `specular_strength` | 0–2 | Surface highlights |
| `rim_strength` | 0–2 | Edge lighting |
| `wrap_strength` | 0–2 | Environmental color at the silhouette |
| `grain_match` | 0–2 | Background grain matching |
| `shadow_strength` | 0–2 | Overall shadow contribution |
| `individual_light_colors` | 0–2 | Stylized separation of source colors |
| `adaptive_light_colors` | 0–2 | Automatic separation of distinct colored sources |
| `glow_strength` | 0–2 | Luminous sprite and soft halo in the artwork's colors; default 0 |
| `glow_radius` | 0–2 | Halo spread; 1 means 4% of the shorter sprite canvas edge |
| `glow_color_mix` | 0–1 | 0 uses artwork colors (default); 1 uses custom glow RGB |
| `glow_red`, `glow_green`, `glow_blue` | 0–1 | Custom sprite and halo color; defaults 1, 1, 1 |
| `emission_strength` | 0–2 | Light cast onto other selected sprites; default 0 |
| `emission_radius` | 0–2 | Light reach in screen heights; default 0.35 |
| `emission_red`, `emission_green`, `emission_blue` | 0–2 | Emitted light RGB intensity; defaults 1, 1, 1 |

Set `adaptive_light_colors=0.0` to disable automatic source-color separation.
Accepted setting aliases are `lighting_strength`, `exposure` and
`separate_light_colors` for `strength`, `exposure_bias` and `individual_light_colors`.

## Independent sprite settings and glow

Every setting above works independently through `character()` or `image()`,
including strength, exposure, colors, shadows, and glow. Exact-image rules override
only the fields they specify; other poses and characters keep their own values.

```renpy
init python:
    scenelight.character("hero", strength=0.65, rim_strength=0.4)
    scenelight.image("hero worried", strength=0.9, exposure_bias=-0.15)
    scenelight.image("fire burning",
        glow_strength=0.8, glow_radius=1.2,
        emission_strength=1.0, emission_radius=0.45,
        emission_red=1.0, emission_green=0.35, emission_blue=0.08)
```

Use `emission_strength=0` for self glow alone, or `glow_strength=0` to cast light
without glowing. `glow_radius=0` keeps the luminous sprite without a halo. Leave
transparent padding around the art to contain the halo; it stays inside the image
canvas. Neither option creates a floor shadow. Normal surface shading stays active.

Emission follows the visible sprite's screen center and fades to zero at its
configured radius. Hidden sprites stop emitting. Up to four sources can illuminate
each receiver; the strongest have priority. This is 2D illumination of selected
sprites, without wall occlusion or relighting the background. It requires an active
SceneLight background, just like the other sprite lighting controls. The player's
master switch disables glow and emitted light as well.

Preview → Calibrate → **Glow & emitted light** adjusts these values. The
single-sprite Preview displays self glow; use a second selected character in-game
to see emitted light. Exported profiles preserve both sets of controls. For effects
such as fire, put the settings on the image or tag so other characters do not glow.

To change the color you see in Preview, increase **Sprite glow** above zero, then
use **Choose color** in the Sprite glow group. The picker enables **Custom glow
color** automatically. Uncheck it to restore artwork colors. The separate
**Cast-light color** controls affect light cast onto other characters only.

For example, this makes a sprite and its halo glow blue without lighting neighbors:

```renpy
$ scenelight.image("magic glowing", glow_strength=0.8, glow_color_mix=1.0,
    glow_red=0.1, glow_green=0.3, glow_blue=1.0, emission_strength=0.0)
```

Setting `glow_color_mix=0` restores artwork colors. A zero `glow_strength`
disables self glow regardless of the chosen color.

Rain, glitch, and custom effect packs remain deferred until after launch.

## Shaders and transforms

An outer `show ... at` model shader receives SceneLight's lit character. A shader
inside an image declaration runs first, making its result SceneLight's input.
Use `mesh True` to give a model shader its own rendering pass.

The [Make Visual Novels! shader pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
was validated with this ordering on Ren'Py 7.8.7 and 8.5.2. That is historical
composition coverage, not a recommendation to install the leaking 7.8.7 runtime.

```renpy
show hero happy at left, IntenseAberate
```

Here `IntenseAberate` is an MVN transform and runs after SceneLight. Combining MVN
simulated lighting with SceneLight applies both effects. Use `scenelight.off()`
for a sequence or `scenelight.character("hero", enabled=False)` for a tag when
only the other lighting effect is wanted. Layer-wide effects also affect that
layer's UI; keep UI on a separate layer when appropriate.

Custom code that replaces scene-list internals or ignores its child texture needs
its own compatibility check.

[Compatibility](BETA_VALIDATION.md)
