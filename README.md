# SceneLight for Ren’Py

SceneLight adjusts character lighting to match the background in a Ren’Py game.
A warm lamp can catch one side of a sprite, a blue light can reach the other,
and the lighting follows the character as they move.

![The same Eileen sprite before and after SceneLight, with warm light on the left and blue light on the right](docs/media/lighting-comparison.png)

You can add it to an existing game through Setup, or use the author API in your
own project. The Preview & Calibrator lets you try backgrounds, sprites and
videos before installing or writing a scene.

**Status:** private testing. There is no public release yet. See
[what has been tested](docs/BETA_VALIDATION.md) for compatibility and known limits.

## Try it

Testers with repository access can get the Windows ZIP from a successful
[Build release ZIP run](https://github.com/RageAdo-dev/SceneLight/actions/workflows/release.yml).
Open the run, download the **SceneLight-Windows** artifact, then extract
`SceneLight-v1.0.0-Windows.zip` from it.

1. Extract the ZIP and open **SceneLight.bat**.
2. Choose the folder containing the game’s executable and `game` folder.
3. Scan the game, then review which image groups are characters.
4. Choose **Add to this game** or **Create separate copy**.
5. Let preparation finish, then launch the game normally.

The first setup takes time, especially with videos. SceneLight prepares reusable
character maps and lighting for each supported movie frame. Later playback reads
that cache. Backgrounds that change through code or visual effects use live
analysis when a prepared result cannot represent what is on screen.

[Installation, updates and removal →](docs/INSTALL.md)

## Where the lighting comes from

SceneLight reads the background’s brightness, colors and visible light sources.
It also estimates a shallow surface from each sprite’s outline and painted
shading. These are the maps for the character above:

![Source artwork alongside SceneLight’s estimated height, surface normals and occlusion](docs/media/surface-maps.png)

- **Height** describes the estimated relief. Brighter areas sit higher.
- **Normals** describe which way each part of that surface faces.
- **Occlusion** adds shading in estimated recesses. It is subtle in this example.

The renderer uses those maps to shade the original artwork at its current
position. The source image and its transparency are preserved. This is an
estimate from a flat drawing; it cannot recover the character’s actual 3D shape.

[How the maps and lighting work →](docs/HOW_IT_WORKS.md)

## Lighting follows movement

Here the background stays fixed while Eileen moves between the two lights.
The image is rendered by SceneLight with its default settings.

![Eileen moving between a warm light and a blue light, with the lighting changing across her sprite](docs/media/moving-light.webp)

Preview uses the same lighting shader as the game. You can drag a character,
change the lighting strength, compare the original and relit image, then save a
profile or export the settings for your project.

## For game creators

Open **SceneLight.bat → For mod developers**, select your project, review its
character tags, and choose **Install developer API**. Your normal Ren’Py syntax
continues to work:

```renpy
scene bg station
show hero happy at left
with dissolve
```

Set project defaults during initialization, or change the look for a sequence:

```renpy
init python:
    scenelight_register_tag("hero")
    scenelight.configure(strength=1.0, light_mode="physical")

label evening:
    $ scenelight.scene(exposure_bias=-0.2, key_strength=0.7)
    scene bg station_night
    show hero happy
    "The last train has gone."
    $ scenelight.clear_scene()
    return
```

There are also per-character controls, image overrides and optional effects.
Start with the [author quickstart](docs/AUTHOR_QUICKSTART.md), then use the
[API reference](docs/MOD_AUTHOR_API.md) when you need a specific control.

## Compatibility

Windows is the supported Setup platform. SceneLight has been tested with
Ren’Py 7 and 8; some older Ren’Py 6 games use the supplied 7.7.1 compatibility
runtime. Automatic discovery does not recognize every project.

A dedicated graphics card is not required. Compatible integrated graphics can
run the shaders, but working graphics acceleration is needed. Live analysis
requires OpenGL 3.3 or OpenGL ES 3.0 with the supported floating-point operations.
Performance depends on resolution, the number of characters and whether the
background can use prepared lighting. See the
[hardware results and limitations](docs/BETA_VALIDATION.md#playback-and-hardware).

## More information

- [Install and update](docs/INSTALL.md)
- [Author quickstart](docs/AUTHOR_QUICKSTART.md) · [API reference](docs/MOD_AUTHOR_API.md)
- [Compatibility and validation](docs/BETA_VALIDATION.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

SceneLight is licensed under the [MIT license](LICENSE). Eileen’s artwork is by
**Piroshki**, from the Ren’Py tutorial; see the [example credits](docs/media/CREDITS.md)
and [third-party notices](THIRD_PARTY_NOTICES.md). SceneLight is an independent
project and is not affiliated with Ren’Py.
