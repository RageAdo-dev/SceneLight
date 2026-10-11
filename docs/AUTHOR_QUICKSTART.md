# Add SceneLight to your mod

## Install

1. Back up your project and saves.
2. Open **SceneLight.exe → For mod developers** and select the project containing `game/`.
3. Scan, choose the character image tags, and select **Install developer API**.

SceneLight installs under `game/scenelight_runtime`. Keep using your existing
`scene`, `show`, `hide`, ATL and transitions. Selecting a tag such as `hero`
covers its poses and expressions. Use **Characters…** to change the selection.

## Set lighting rules

Automatic lighting needs no script calls. Add rules when you want to change it:

```renpy
init python:
    scenelight.background("street_night", strength=0.25)
    scenelight.character("companion", strength=0.9)
    scenelight.image("hero happy", rim_strength=0.8)
```

Authored strength ranges from 0 to 2; 1 is normal strength: **78% in Preview is `strength=0.78`**. For a sequence:

```renpy
label evening:
    scene bg street_night
    $ scenelight.scene(exposure_bias=-0.2)
    show hero worried at left
    "The streetlights came on."
    $ scenelight.clear_scene()
    return
```

`clear_scene()` restores inherited settings. Use `scenelight.off()` to disable
lighting for a sequence, then `clear_scene()` to restore it.

## Light separate sprites together

For a shared pose, group the image tags so they share settings and a lighting position:

```renpy
$ scenelight.group("hug", ["hero", "companion"], anchor="hero", strength=0.8)
# When the pose ends:
$ scenelight.clear_group("hug")
```

Without an explicit anchor, lighting follows the center of the visible group.
Each sprite keeps its surface detail and glow.
[Group settings and rule precedence](MOD_AUTHOR_API.md#lighting-groups).

## Add glow

```renpy
init python:
    scenelight.image("fire burning", glow_strength=4.0, emission_strength=0.5)
```

Glow affects the sprite; emission lights nearby characters. You can also match
specific artwork colors with [color glow rules](MOD_AUTHOR_API.md#glow-selected-colors-on-a-sprite).

## Adjust and check

Use [Preview](PREVIEW_WORKSPACE.md) to tune defaults. Review the export destination
and values, save to the project, run **Update SceneLight**, and restart the game.

In-game, press **Shift+F9** to inspect applied values and their sources. Try sliders
or exact edits. These changes are temporary; put permanent choices in your config
or script. The inspector can be removed through **Settings → Advanced** before
distributing the mod.

Setup detects project edits while it is open. Choose **Check changed assets →
Update SceneLight**, then restart the game. Detection alone does not prepare new
assets or reload the game. Before distributing, check movement, expressions,
transitions, custom shaders, and save/load with your own assets.

The full [API reference](MOD_AUTHOR_API.md) covers configuration, selection rules,
groups, colors and shaders. A searchable copy is in **Settings → Advanced → Developer guide**.
