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

Explicit exclusions in **Characters…** take precedence over tag registration.
Recheck a family and apply the update to enable it again.

After adding assets, use **Check new assets → Update SceneLight**. Existing poses
can use a generic surface until their own maps are ready. Updates reuse valid
analysis and stop if an owned runtime file was changed.

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

### Inspect an actual game scene

Press **Shift+F9**, or call `$ scenelight.inspector()`. Select a visible sprite.
In SceneLight Setup, select the project and open **Settings → Advanced → Include
in-game inspector**, then **Apply to project**. Turning it off removes the inspector
source, helper and compiled script from the selected installation; neither the
shortcut nor the API opens a panel after restarting the game. Turning it on adds
the tool back. This does not change lighting, rebuild asset maps or change saved
player preferences. The choice survives both code-only and full asset updates.
For a new project, Apply saves the choice for its next installation. The default
remains enabled. A different/older runtime may need a normal SceneLight update
before the current inspector can be enabled. Exclude it before building a mod
release if players should not have the debugging tool.

**Applied settings** shows each effective value and its winning source.
**All sources** includes values overridden by a later scope, the installed profile,
saved player master, last drawn strength, map availability and detected external
color grading, including nested lighting passes. Rules created by this runtime
also record their script filename and line. Older saved rules may lack that
location until the relevant script call executes again.
A transition can retain a frozen earlier state; that is identified
separately from current rules.

Drag a numeric value's slider for live adjustment, or use **Edit** to enter an
exact number. Both apply a temporary test value only to the selected background/tag/image.
Master edits affect all sprites temporarily. Original story rules and persistent
preferences are untouched. **Reset** restores one value; **Clear all test edits**
restores the complete original state. Closing the panel keeps edits active with a
visible badge. New game, load or restart clears them.

**Checks** lists observed conflicts, missing exact sprite maps, external grading,
disabled lighting and differing master/author values. Add reproduction notes there.

**Export report** now writes one `scenelight-support-*.zip` beside `game/` with
readable `report.html`, settings and provenance JSON, exact runtime hashes,
installation metadata, engine logs, notes and any recorded samples. It includes a
screenshot only when selected in Checks. It does not include scripts, saves or
source artwork. A `scenelight-inspector.json` copy remains available for
**Settings → Activity → Include game logs… → Export report…**.
`scenelight.inspect()` returns the same diagnostic data; pass a tag such as
`scenelight.inspect("hero")` to select one character.

### Updating large projects

Compatible SceneLight code updates verify authored inputs and the existing
installation, then replace only changed runtime code. They do not capture sprites,
analyze backgrounds, copy the map collection or reinstall the game. A recovery
journal restores interrupted code replacements on the next update. Concurrent
updates to the same project are refused.

Lighting/profile edits and selection changes among already prepared character
families use a settings-only update when asset-discovery inputs and source files
are unchanged. Existing maps stay in place, and per-background calibration is
updated for static and animated scenes. Newly selected unprepared families or
switching to automatic discovery from manual selection may require analysis.
The main update window and Activity show why analysis is needed when that occurs.

Changed source files, asset-discovery changes, unknown older metadata or a new
analysis contract use the regular inventory/build workflow. Unchanged form maps
and background transport are reused; background scene fields are cached too.
Those new field caches are populated the first time, then reused on later runs.
Dynamic script/archive changes can still require a broad runtime inventory pass
because one definition can alter thousands of expressions. Source hashing and
integrity checks still take time on large projects. Activity records why an update
took its route and the build report includes cache counts.

### Control a background's color cast

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

| Call | Applies to |
| --- | --- |
| `scenelight.configure(**settings)` | Project defaults |
| `scenelight.background(name, **settings)` | A background; the leading `bg ` is optional |
| `scenelight.scene(**settings)` | The current sequence, until cleared |
| `scenelight.character(tag, **settings)` | Every image with that tag |
| `scenelight.image(name, **settings)` | One exact registered image name |
| `scenelight.group(name, members=None, anchor=None, **settings)` | Shared lighting for registered sprite tags; see [groups](#lighting-groups) |

For ungrouped sprites, the first five scopes apply in that order. A more specific rule replaces only the settings it
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
preserve both sets of controls. For effects
such as fire, put the settings on the image or tag so other characters do not glow.

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

Rain, glitch, and custom effect packs remain deferred until after launch.

### Glow selected colors on a sprite

Use **Calibrate → Color glow** on the loaded Preview sprite. Add as many color
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
that scope. A more specific list replaces the inherited list. **Save profile** and **Export config** preserve these values. In a mod, use
`scenelight.character(...)` or `scenelight.image(...)` for independent targets.

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
