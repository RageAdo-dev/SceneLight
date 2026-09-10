# SceneLight author quick start

This guide is for a Ren'Py mod author who wants SceneLight active throughout a
project while retaining direct control from `.rpy` scripts.

## 1. Install the author integration

1. Extract the SceneLight release.
2. Run **SceneLight.bat** and choose **For mod developers**.
3. Select the project folder that contains `game/`.
4. Run the compatibility check.
5. In **Which image families are characters?**, check only actual character
   image tags. For example:

   - `sayori`
   - `zack`
   - `monika`

   Do not check effect, overlay, or interface families such as `magic`,
   `console_bg`, `console_caret`, or `console_text`.
6. Add any missing character tag in the text field. This is useful for
   archive-backed images and custom characters that static source discovery
   cannot preview.
7. Save the selection and choose **Install developer API**.

The installation adds SceneLight under `game/scenelight_runtime`. It does not
rewrite `story.rpy`, transforms, or other authored scripts.

For a selection that should travel with the project, place `scenelight.json`
beside the `game/` folder:

```json
{
  "character_selection": "manual",
  "character_tags": ["sayori", "zack", "monika"]
}
```

Preview's **Export config** can also write its complete lighting look here.
For example, the Cinematic look stores both its calibration and its 0.72
strength; installing the project reproduces the Preview result exactly.

## 2. Ordinary story code does not change

Existing Ren'Py statements keep their normal syntax:

```renpy
scene bg hallway
show zack dp
show sayori teeth at wf21
z "I'm not going to take all of it away."
```

SceneLight recognizes the selected image tags at runtime. Pose and expression
attributes remain part of the same family, so selecting `sayori` covers
`sayori teeth`, `sayori ep l`, and other Sayori images.

## 3. Existing custom transforms and shaders

SceneLight is inserted inside an existing character transform. The authored
transform then operates on the relit sprite. For example:

```renpy
transform IntenseAberate:
    mesh True
    shader "MakeVisualNovels.StillAberration"
    u_aberrationAmount 50.0

show sayori at IntenseAberate
```

The order is:

1. SceneLight relights Sayori using the current background and final placement.
2. `IntenseAberate` applies its chromatic-aberration shader to that result.
3. Ren'Py composites the transformed character into the scene.

ATL movement, entrances, exits, replacements, hides, dissolves, and transforms
on the `master` layer remain owned by Ren'Py. SceneLight forwards the complete
transform lifecycle rather than replacing it.

Effect and interface images remain unchanged as long as their first image tag
was not selected as a character:

```renpy
show console_bg zorder 100
show console_caret zorder 100
show console_text "Scan bg current" as ctext zorder 100
show magic balls at t21
```

## 4. Whole-mod and per-scene control

No API call is required for automatic whole-mod lighting. An optional baseline
can be set once near the beginning of the story:

```renpy
label start:
    $ scenelight.configure(strength=1.0, color_adaptation=0.78)
    jump chapter_one
```

Adjust one scene before showing its characters:

```renpy
label red_emergency_room:
    scene bg red_room
    $ scenelight.scene(
        exposure_bias=-0.20,
        color_adaptation=0.92,
        rim_strength=0.80,
        light_mode="physical",
    )
    show sayori worried at t11
    s "Something feels wrong."

    # A restrained midpoint between physical and fully exaggerated colors.
    $ scenelight.scene(light_mode="cinematic")
    s "Colored sources remain distinct without the full separate-light look."

    $ scenelight.clear_scene()
    return
```

`clear_scene()` is important. It removes only the current scene override and
returns to the analyzed automatic lighting.

## 5. Deliberately unlit sequences

Disable SceneLight for flat UI, special composites, or an effect that should
retain its authored colors:

```renpy
$ scenelight.off()
show special_fullscreen_effect
pause 0.5
hide special_fullscreen_effect
$ scenelight.clear_scene()
```

For a reusable exception, disable one tag or exact image during init:

```renpy
init python:
    scenelight.character("sayori_sticker", enabled=False)
    scenelight.image("sayori special_flat_cutin", enabled=False)
```

## 6. Reusable rules

Rules can target a background, character family, or exact image:

```renpy
init python:
    scenelight.background(
        "bg red_room",
        exposure_bias=-0.20,
        color_adaptation=0.92,
    )
    scenelight.character("zack", strength=0.94)
    scenelight.image("sayori teeth", rim_strength=0.90)
```

The order from broadest to most specific is whole-mod defaults, background,
current scene, character tag, then exact image name.

## 7. Add backgrounds, poses, or characters later

SceneLight managed copies detect changed scripts, images, videos, and profiles
before launch and reuse every unchanged cache automatically.

For a direct developer installation, reopen SceneLight in **For mod developers**.
It compares the project against the source inventory recorded at installation:

1. Choose **Check new assets**.
2. If a new semantic `Character` or `LayeredImage` family appears, check its tag
   in the character review. Unknown UI/effect families remain unchecked; a fully
   custom tag can be typed into **Add image tag**.
3. Choose **Update SceneLight**.

SceneLight checks the current installation before analysis and keeps it working
until the update is complete. If an installed file was edited, the update stops
and leaves the project unchanged. Story files, artwork, and saves are never
rewritten.

An added pose under an already selected tag can use SceneLight's generic form
fallback immediately, but refresh is what gives that pose an exact reconstructed
surface map. A new background must be refreshed so SceneLight can measure its
own transport; it is never assigned another scene's lighting data.

## 8. Verify the integration

Test at least these cases before shipping the mod:

1. A character enters and leaves with ATL or a dissolve.
2. A character moves from the left side to the right side.
3. The expression changes without changing the background.
4. The background changes with and without a transition.
5. A custom transform such as `IntenseAberate` is applied.
6. A `master`-layer transform is applied.
7. Stickers, console overlays, and full-screen effects remain unlit.
8. Save, load, and rollback preserve the current SceneLight rules.

Use **Settings → Review character families** in the setup app whenever the mod
adds a new character tag. The updated selection is enforced during the next
analysis and installation.

## Compatibility boundary

Normal ATL transforms and model-based Ren'Py shaders compose with SceneLight as
described above. A project still needs a specific compatibility test if it
replaces Ren'Py's scene-list internals, manually rewrites registered character
displayables after SceneLight initializes, or uses a custom shader that ignores
or replaces its child texture. Those behaviors are outside ordinary transform
composition and cannot be proven from script screenshots alone.
