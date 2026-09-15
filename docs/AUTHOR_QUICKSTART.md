# Author quickstart

Keep a backup of your project and saves before installing. You can restore it if
setup is interrupted or your project needs a compatibility adjustment.

## Install

1. Open **SceneLight.bat → For mod developers** and select the project containing `game/`.
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

## Transforms and shaders

An outer `show hero at CustomShader` transform receives the lit sprite. A shader
inside an image declaration runs before SceneLight. Model shader transforms should
use `mesh True` to keep their rendering passes separate.

The [Make Visual Novels! shader pack](https://makevisualnovels.itch.io/make-visual-novels-rspv1)
was tested with this ordering. See the [API reference](MOD_AUTHOR_API.md#shaders-and-transforms)
for composition and bypass examples.

## Update and check your project

After adding assets, use **For mod developers → Check new assets → Update SceneLight**.
Review new character tags. Existing poses can use the generic fallback until their
own maps are prepared. Updates stop if SceneLight-owned files were edited.

Before distributing a game, check movement, expression changes, scene transitions,
custom shaders, unlit UI and save/load/rollback with your own assets.

[Full API reference](MOD_AUTHOR_API.md) · [Installation and removal](INSTALL.md) · [Compatibility](BETA_VALIDATION.md)
