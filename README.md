<div align="center">

![SceneLight — character lighting for Ren’Py](docs/media/scenelight-banner.svg)

**Character lighting for Ren’Py games and mods.**

Match sprites to the light in a background, add glow, and adjust the result in Preview or in-game.

[![CI](https://img.shields.io/badge/CI-Windows_%2B_Linux-233c51?style=flat-square)](https://github.com/RageAdo-dev/SceneLight/actions/workflows/ci.yml) [![Tester build: 1.1.0](https://img.shields.io/badge/tester_build-1.1.0-57c7dc?style=flat-square)](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.1.0) [![Ren’Py 7 and 8](https://img.shields.io/badge/Ren%27Py-7_%26_8-233c51?style=flat-square)](docs/BETA_VALIDATION.md) [![License: MIT](https://img.shields.io/badge/code-MIT-233c51?style=flat-square)](LICENSE)

**[Download for Windows](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.1.0)** · **[Player setup](docs/INSTALL.md)** · **[Mod developer guide](docs/AUTHOR_QUICKSTART.md)** · **[All documentation](docs/README.md)**

</div>

![The same character without and with SceneLight’s warm and cool lighting](docs/media/lighting-comparison.png)

*Rendered through SceneLight’s production shader with the same sprite and placement. [How it works](docs/HOW_IT_WORKS.md) · [Artwork credits](docs/media/CREDITS.md)*

## Start with your game

| For players | For mod developers |
| --- | --- |
| Add lighting to a compatible game, or create a separate SceneLight copy. | Install the API in your project and tune backgrounds, characters or individual expressions. |
| Choose which characters receive lighting. Keep exclusions when new assets arrive. | Keep your existing `scene`, `show`, ATL and transitions; add rules where you need them. |
| [Install, update and remove →](docs/INSTALL.md) | [Start building →](docs/AUTHOR_QUICKSTART.md) |

1. Download **SceneLight-v1.1.0-Windows.zip**, extract it, and open **SceneLight.exe**.
2. Select the folder containing your game, scan, and review the character choices.
3. Install, wait for the completion message, and launch the game normally.

The complete Windows package includes Setup, Preview and the compatibility runtime. No system Python installation is needed. Keep a backup of your project and saves before installing. Private tester downloads require repository access or a copy from the maintainer.

## Shape the lighting while you work

**Preview & Calibrator** keeps the canvas beside the controls. Drag or scale a single sprite, compare it with the original, and adjust lighting without closing a dialog.

![Current Preview with the sprite canvas and right-side lighting controls](docs/media/preview-workspace.png)

| Lighting | Glow and color | Save and export |
| --- | --- | --- |
| Presets, strength, exposure, shadows, bounce and highlights. | Sprite glow up to **10**, artwork-to-color tint, and multiple rules that make selected color ranges glow. | Review current values and the exact config before saving. Export PNG, GIF or video. |

Open **Settings → Tools → Open Preview & Calibrator**. [Preview guide →](docs/PREVIEW_WORKSPACE.md)

<details>
<summary><strong>See the glow controls and reviewed settings export</strong></summary>

![Sprite glow controls with strength, halo and color settings](docs/media/preview-glow.png)

![Review lighting values and the destination before exporting a config](docs/media/preview-export.png)

Saving a profile or config does not immediately change an installed game. Apply it with **Update SceneLight**, then restart the game. Cast-light settings illuminate other characters in-game; Preview keeps its simple single-sprite canvas.

</details>

## See what the game is actually applying

Press **Shift+F9** during a scene to open the **Lighting inspector**. Select a sprite, see its effective values and their sources, and try changes with sliders or exact numeric edits.

![SceneLight’s inspector running in a Ren’Py scene with Eileen](docs/media/ingame-inspector.png)

- Trace background, scene, character, image and player overrides.
- Adjust a chosen background-light color to reduce or increase its influence.
- Export a diagnostic report with settings, runtime fingerprints and relevant logs.
- Include or remove the inspector through **Settings → Advanced → Include in-game inspector**.

Inspector edits are temporary; loading, starting a new game or restarting clears them. Export a report before clearing a useful reproduction. [Inspector and API reference →](docs/MOD_AUTHOR_API.md#inspect-an-actual-game-scene)

## A little code when you need it

Automatic lighting works without script calls. Add precise rules for exceptions:

```renpy
init python:
    scenelight.background("street_night", strength=0.25)
    scenelight.character("hero", strength=0.8)
    scenelight.image("hero happy", rim_strength=0.6)
    scenelight.image("fire burning", glow_strength=4.0, emission_strength=0.5)
```

You can target one background, apply rules to several backgrounds, override a whole character, or tune one expression. Glow, selective-color rules and emitted light are available in the mod API. The searchable **Developer guide** is also built into Setup. [Command reference →](docs/MOD_AUTHOR_API.md)

## Light sprite pieces together

Use a lighting group for a character assembled from several sprites, or a shared pose such as a hug. Members sample the same lighting position and use common settings.

![Two separately positioned sprites sharing group lighting in Ren’Py](docs/media/lighting-groups.png)

```renpy
$ scenelight.group("hug", ["hero", "companion"], anchor="hero", strength=0.8)
# After the shared pose:
$ scenelight.clear_group("hug")
```

The default anchor follows the center of the visible group. Choose a member or a fixed screen point when needed. Each sprite keeps its surface detail and individual glow. [Groups and precedence →](docs/MOD_AUTHOR_API.md#lighting-groups)

## Updates that reuse your work

Compatible code-only and lighting-settings updates retain the existing asset maps. When artwork changes, SceneLight checks the inventory and reuses compatible capture and analysis results. Missing or unsupported assets are reported individually while usable assets continue.

On the same volume, Setup can move the prepared runtime into place without a second full copy. It also reuses verified checksums when the filesystem confirms a file is unchanged.

| Update | What happens |
| --- | --- |
| Compatible code or lighting settings | Keep prepared asset maps; update the relevant files and values. |
| New artwork | Refresh the inventory and reuse compatible capture/analysis results. |
| Missing or incompatible preparation | Check and rebuild the affected data. |

Windows checksum reuse requires a file-journal sequence and an exclusive read;
if those are unavailable, verification reads the bytes again. [Performance and
verification details →](docs/performance.md#installation-and-update-finalization)

While Setup is open, it checks the selected folder for changes and offers **Check changed assets → Update SceneLight**. Newly discovered characters follow your saved inclusion policy. Restart the game after updating. **Settings → Activity** shows the current stage, retained logs and report exports.

## Lighting in motion

![Eileen moving between warm and cool light sources](docs/media/moving-light-preview.webp)

[Watch the video](docs/media/moving-light.mp4) · [More scenes and surface maps](docs/GALLERY.md)

## Compatibility and testing

Windows with compatible graphics; Ren’Py 7 and 8, plus a bundled compatibility runtime for some older games. CUDA is optional preparation acceleration. Live lighting still needs a supported graphics renderer.

The build passed **1,026 automated tests** and native Ren’Py 7/8 player/developer update and save-loading checks. Lighting groups also passed native movement, hidden-anchor and save/load checks. GPU coverage varies by device. A tester traced an intermittent shimmer to new scenes that had not been updated; the new change indicator addresses stale setup state. The affected mod still needs a confirmation run.

[Compatibility and known issues](docs/BETA_VALIDATION.md) · [Report a problem](docs/TROUBLESHOOTING.md) · [Changelog](CHANGELOG.md)

---

[Contributing](CONTRIBUTING.md) · [MIT code license](LICENSE) · [Security](SECURITY.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

Eileen by Piroshki, from the Ren’Py tutorial. Demonstration artwork has its own credits and licensing; it is not covered by SceneLight’s code license. [Artwork and media credits](docs/media/CREDITS.md)
