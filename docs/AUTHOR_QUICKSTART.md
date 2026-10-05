# Author quickstart

For a searchable command browser, open **Settings → Advanced → Developer guide**.
It works offline and includes explanations, accepted ranges, and copyable examples
with instructions for where to put them. No project selection is needed to read it.

Keep a backup of your project and saves before installing. You can restore it if
setup is interrupted or your project isn’t compatible.

## Install

1. Open **SceneLight.exe → For mod developers** and select the project containing `game/`.
2. Scan the project and select its character image tags. Leave UI, stickers and props unchecked.
3. Add any missing tag, then choose **Install developer API**.

SceneLight installs under `game/scenelight_runtime` without rewriting your story
scripts. Existing `scene`, `show`, `hide`, ATL and transitions continue to work.

To keep character selection in source control, put `scenelight.json` beside `game/`:

```json
{
  "character_selection": "manual",
  "character_tags": ["hero", "companion"]
}
```

Preview's **Export config** can save lighting settings and strength into the same
project configuration. Tags refer to Ren'Py image names: selecting `hero` covers
`hero happy`, `hero worried` and its other expressions.

Use **Characters…** beside the selected folder to refresh discovery and reopen
the checklist at any time. **Automatically include new characters on scan / update**
defaults on for new projects; unchecked families remain excluded. Turning it off
keeps a fixed selection. Existing manual selections retain that choice. For an
installed project, **Apply selection & update** saves the choices and prepares them.

For the same automatic policy in project configuration, use
`"auto_include_new_characters": true` and
`"excluded_character_tags": ["sticker"]`; `character_tags` can also explicitly
include unusual families such as fire or other glow artwork. User selections in
Setup override project configuration without rewriting your configuration file.

## Set the lighting

Automatic lighting needs no script calls. Add defaults or change a sequence when needed:

```renpy
init python:
    scenelight.configure(strength=1.0, color_adaptation=0.78)

label evening:
    scene bg street_night
    $ scenelight.scene(exposure_bias=-0.2, light_mode="cinematic")
    show hero worried at left
    "The streetlights came on."
    $ scenelight.clear_scene()
    return
```

`clear_scene()` removes the temporary override and restores inherited rules.
Rules can also target a background, character or exact image:

```renpy
init python:
    scenelight.background("street_night", exposure_bias=-0.2)
    scenelight.character("companion", strength=0.9)
    scenelight.image("hero happy", rim_strength=0.8)
    scenelight.character("hero_sticker", enabled=False)
```

The order is defaults → background → scene → character → exact image.
Use `scenelight.off()` to bypass lighting for a sequence and
`scenelight.clear_scene()` to restore it. Rules support save/load and rollback.

## Glow and selected colors

```renpy
init python:
    scenelight.image("fire burning", glow_strength=4.0, emission_strength=0.5)
    scenelight.image("hero happy", glow_rules=[
        {"color": [1.0, 0.1, 0.02], "strength": 2.0,
         "tolerance": 0.2, "softness": 0.1, "radius": 1.0}
    ])
```

Glow strength reaches 10. Color rules match similar shades in the original artwork;
tolerance and softness control the selection. Emitted light can illuminate other
selected characters in-game. [All settings and scopes](MOD_AUTHOR_API.md).

## Inspect the result in-game

Press **Shift+F9** with a sprite visible. Select it to inspect effective settings,
winning rules and overridden values. Try sliders or **Edit**, then export a report
if you find a discrepancy. Edits are temporary; put permanent choices in your
project config or script rules. The inspector can be included or removed in
Setup’s **Settings → Advanced** before distributing your game.
[Inspector guide](MOD_AUTHOR_API.md#inspect-an-actual-game-scene).

Preview exports open a review page before writing. Choose the intended project,
review the exact values, save, run **Update SceneLight**, and restart the game.
Per-scene/per-image rules and player settings may override exported defaults;
**All sources** makes those differences visible.

## Transforms and shaders

An outer `show hero at CustomShader` transform receives the lit sprite. A shader
inside an image declaration runs before SceneLight. Model shader transforms should
use `mesh True` to keep their rendering passes separate.

The [Make Visual Novels! shader pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
was tested with this ordering. See the [API reference](MOD_AUTHOR_API.md#shaders-and-transforms)
for composition and bypass examples.

## Update and check your project

After adding assets, use **For mod developers → Check new assets → Update SceneLight**.
Newly detected characters follow the saved automatic-inclusion policy. Existing poses can use the generic fallback until their
own maps are prepared. Updates stop if SceneLight-owned files were edited.
SceneLight does not continuously monitor your source directory; run this update
after adding, replacing, or removing assets. Downloading a newer app alone does not
refresh a game's installed runtime.

Before distributing a game, check movement, expression changes, scene transitions,
custom shaders, unlit UI and save/load/rollback with your own assets.

[Full API reference](MOD_AUTHOR_API.md) · [Installation and removal](INSTALL.md) · [Compatibility](BETA_VALIDATION.md)
