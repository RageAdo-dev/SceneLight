# Lighting API

The in-app **Settings → Advanced → Developer guide** provides searchable commands,
lighting settings, and copyable examples. This page is the written reference.

Install through **For mod developers → Install developer API** before using these
calls. Existing story statements and transforms keep their normal syntax.
[Quickstart](AUTHOR_QUICKSTART.md).

## Character selection and updates

Select character image tags in Setup. A tag covers its poses and expressions;
UI and stickers should remain unchecked. Select effect tags such as `fire` when
you want them to glow or illuminate characters. To store the selection with a project:

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

Explicit exclusions in **Characters…** take precedence over tag registration.
Recheck a family and apply the update to enable it again.

To include newly discovered characters automatically, set
`"auto_include_new_characters": true`. Use `"excluded_character_tags": ["sticker"]`
for persistent exclusions. Choices saved in Setup take precedence over the config.


When Setup detects added assets, use **Check changed assets → Update SceneLight**.
New poses can use a generic surface until their maps are prepared. Restart the game
after updating. Updates stop if a SceneLight-owned runtime file was edited.

## Lighting groups

Use a group when several sprites form one pose or should receive the same lighting:

```renpy
# Use the registered image tags selected in Setup.
$ scenelight.group("hug", ["hero", "companion"], strength=0.8)
show hero hugging
show companion hugging

# Optional: follow one member, or use a fixed normalized screen point.
$ scenelight.group("hug", anchor="hero")
$ scenelight.group("hug", anchor=(0.45, 0.5))

# Restore individual lighting after the shared pose.
$ scenelight.clear_group("hug")
```

Without an anchor argument, the group samples the center of the visible members'
combined bounds. The point follows their movement. A hidden member anchor falls
back to the visible group's center. Fixed coordinates run from 0 to 1 across
and down the screen. Members use registered tags on the `master` layer; use
separate registered tags for separate pieces, rather than `show ... as` aliases.

Group members inherit project, background and scene settings, followed by the
group's own overrides. Their individual character/image lighting overrides are
ignored while grouped. Surface maps and painted detail stay individual; this
does not merge or flatten their artwork. Local lighting can still vary across
surfaces. Glow and emitted-light settings stay per member unless the group sets
them. Disabled members and `scenelight.off()` remain disabled. Inspector test
edits can temporarily override a member; the inspector identifies that source.

A tag can belong to one group at a time. Repeated calls merge group settings;
omitting members and anchor keeps them. `clear_group(name)` restores the original
member rules, and `reset()` removes all groups. Calls inside `init python` seed
new games. Story calls, save/load and rollback preserve the current group state.
The inspector shows membership, shared position and applied setting sources.

## Scopes and precedence

| Call | Applies to |
| --- | --- |
| `scenelight.configure(**settings)` | Project defaults |
| `scenelight.background(name, **settings)` | A background; the leading `bg ` is optional |
| `scenelight.scene(**settings)` | The current sequence, until cleared |
| `scenelight.character(tag, **settings)` | Every image with that tag |
| `scenelight.image(name, **settings)` | One exact registered image name |
| `scenelight.group(name, members=None, anchor=None, **settings)` | Shared lighting for registered sprite tags; see [groups](#lighting-groups) |

For ungrouped sprites, the first five scopes apply in that order. A more specific
rule replaces only the settings it contains. Repeated calls at the same scope
merge their values. Rule state supports Ren'Py save/load and rollback.

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

## Control a background's color cast

```renpy
init python:
    scenelight.background("lake", light_color="#4080FF",
        light_color_amount=-0.5, light_color_tolerance=0.25)
```

This reduces the influence of blue light on characters without editing the
background image or selecting blue pixels in the character's artwork. The hex
color chooses the target hue; tolerance includes nearby shades with a soft edge.
Amount ranges from **-1** (neutralize matching light color) through **0** (unchanged)
to **+1** (increase its color). The incoming light's luminance is retained. Grays
have no color cast to adjust. This does not change sprite glow or light emitted
by other sprites. The same control is in Preview's **Adjust → Light color**.

The shorthand sets `light_color_red`, `light_color_green` and `light_color_blue`
(each 0–1). `light_color_amount` is -1–1; `light_color_tolerance` is 0–1. These
settings also work at the other existing lighting scopes and round-trip through
Preview profiles and exported configuration.

## Inspect an actual game scene

Press **Shift+F9** or call `$ scenelight.inspector()` with a sprite visible.
Select the sprite, then use **Applied settings** for effective values and
**All sources** for the rules supplying them. The inspector also identifies
missing maps, external grading and frozen transition state.

Use sliders or **Edit** to try temporary values. **Reset** clears one edit;
**Clear all test edits** clears them all. Closing the panel keeps edits active.
New game, loading or restarting clears them. To keep a change, add it to your
project config or script rules.

**Export report** saves a support ZIP beside `game/`. For a walkthrough, see
[troubleshooting](TROUBLESHOOTING.md). `scenelight.inspect()` returns the diagnostic
data directly; pass a tag, such as `scenelight.inspect("hero")`, to inspect one character.

Include or remove the tool through **Settings → Advanced → Include in-game
inspector → Apply to project**, then restart the game. Removing it removes the
shortcut too. Older installations may need a normal update first.

## Updating projects

Run **Update SceneLight** after changing source assets or saved Preview settings,
then restart the game. Compatible code/settings updates keep prepared maps.
New artwork or changed discovery rules may require analysis; dynamic scripts
and archives can require a wider scan because one definition affects many images.
Activity shows the current work and why preparation is needed.

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
| `saturation_match` | 0–2 | Match scene saturation when the scene contains color; neutral surroundings preserve painted color |
| `highlight_rolloff` | 0–2 | Protect added highlights while retaining brightness and detail already painted into the sprite |
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
| `glow_strength` | 0–10 | Luminous sprite and soft halo in the artwork's colors; default 0 |
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

Preview → Adjust → **Sprite glow** and **Cast light** adjust these values for the loaded
sprite. Check emitted light onto other characters in the mod. Exported profiles
preserve both sets of controls. For effects such as fire, put the settings on the
image or tag so other characters do not glow.

To change the color you see in Preview, increase **Sprite glow** above zero, then
use **Choose color** in the Sprite glow group. The picker enables **Custom glow
color** automatically. Uncheck it to restore artwork colors. The separate
**Cast-light color** controls affect light cast onto other characters only.
Use the **Artwork → color** slider to blend between artwork colors and a full custom
color. An intermediate value such as 35% applies a partial tint.

Preview uses one Lighting strength control for the loaded sprite. Set independent
per-character or per-image strengths with `scenelight.character(...)` or `scenelight.image(...)`.
See the [Preview guide](PREVIEW_WORKSPACE.md) for the controls and profile/config exports.

For example, this makes a sprite and its halo glow blue without lighting neighbors:

```renpy
$ scenelight.image("magic glowing", glow_strength=0.8, glow_color_mix=1.0,
    glow_red=0.1, glow_green=0.3, glow_blue=1.0, emission_strength=0.0)
```

Setting `glow_color_mix=0` restores artwork colors. A zero `glow_strength`
disables self glow regardless of the chosen color.

Rain, glitch, and custom effect packs use an experimental, script-only API,
outside the supported lighting API. The effects panel and its shortcut are
disabled. See [Effect packs](EFFECT_PACKS.md) before using them.

### Glow selected colors on a sprite

Use **Adjust → Color glow** on the loaded Preview sprite. Add as many color
rules as needed, choose an artwork color, and adjust **Color range** to include similar
shades. **Soft edges** feathers the match, **Glow strength** controls brightness, and
**Halo spread** controls its reach. Each rule can be disabled, duplicated, or removed.
More active rules require more rendering time. Leave transparent padding for halos.

```renpy
init python:
    scenelight.image("hero magic", strength=0.7, glow_rules=[
        {"name": "Red gems", "color": [1.0, 0.05, 0.02],
         "tolerance": 0.15, "softness": 0.1, "strength": 0.8, "radius": 1.0},
        {"name": "Blue markings", "color": [0.05, 0.2, 1.0],
         "tolerance": 0.2, "softness": 0.1, "strength": 0.5, "radius": 0.6}
    ])
```

Matching samples the original artwork, so changing scene lighting does not move
the selected color regions. The rules affect only their target; they do not make
every red object in the scene glow. They work on the composed result of layered
sprites. Existing whole-sprite glow/tint and emitted light remain separate.

Rule ranges: RGB channels, tolerance, and softness are 0–1; strength is 0–10
and radius is 0–2. `enabled=False` keeps a rule saved but inactive. `radius=0` suppresses the
halo while brightening the matching artwork. `glow_rules=[]` clears the list at
that scope. A more specific list replaces the inherited list. **Save profile**
and **Export config** preserve these values. In a mod, use
`scenelight.character(...)` or `scenelight.image(...)` for independent targets.

## Shaders and transforms

An outer `show ... at` model shader receives SceneLight's lit character. A shader
inside an image declaration runs first, making its result SceneLight's input.
Use `mesh True` to give a model shader its own rendering pass.

For example, apply a transform from the
[Make Visual Novels! shader pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
after SceneLight:

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

[Compatibility](COMPATIBILITY.md)
