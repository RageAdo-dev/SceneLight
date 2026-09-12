# SceneLight for Ren’Py

Automatic character lighting for Ren’Py. Sprites respond to the background’s
light and color as they move through a scene.

**[Download for Windows](https://github.com/RageAdo-dev/SceneLight/actions/runs/34672742068/artifacts/10290799496)** · [Installation guide](docs/INSTALL.md) · [Author guide](docs/AUTHOR_QUICKSTART.md)

![Character lighting before and after SceneLight](docs/media/lighting-comparison.png)

## Installation

1. Extract `SceneLight-v1.0.0-Windows.zip` and open **SceneLight.bat**.
2. Select your game folder and review the detected characters.
3. Choose **Add to this game** or **Create separate copy**, then let setup finish.

Launch the game normally. Videos are prepared once during setup for faster playback.

## Preview & Calibrator

Load a background and sprite, move the character, and adjust the lighting.
Open it from **Settings → Tools → Open Preview & Calibrator**.

![Character lighting changing between warm and blue lamps](docs/media/moving-light.webp)

## Surface maps

SceneLight generates height, normal and occlusion maps from your sprites to give
the lighting shape and detail.

![Sprite, height map, normal map and ambient occlusion](docs/media/surface-maps.png)

[How it works →](docs/HOW_IT_WORKS.md)

## For game creators

Choose **For mod developers → Install developer API** in Setup. Your existing
`scene`, `show`, ATL and transitions continue to work.

[Author guide](docs/AUTHOR_QUICKSTART.md) · [API reference](docs/MOD_AUTHOR_API.md)

## Requirements

Windows and compatible graphics. A dedicated GPU is not required. Supports
Ren’Py 7 and 8, with a compatibility runtime for some older games.
[Compatibility details](docs/BETA_VALIDATION.md).

[Documentation](docs/README.md) · [MIT license](LICENSE) · [Contributing](CONTRIBUTING.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

Example artwork: **Eileen by Piroshki**, from the Ren’Py tutorial. [Credits](docs/media/CREDITS.md).
