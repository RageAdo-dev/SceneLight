# Installation

[Download the Windows package](https://github.com/RageAdo-dev/SceneLight/actions/runs/34663594727/artifacts/10288048051).
Extract the download, then extract `SceneLight-v1.0.0-Windows.zip` inside it.

## Add SceneLight to a game

1. Open **SceneLight.bat** and select your game folder.
2. Scan the game and review the detected characters.
3. Choose **Add to this game** or **Create separate copy**.
4. Let setup finish, then launch the game normally.

Setup installs any required components with your permission. An internet
connection is needed the first time. Video preparation can take a while;
completed work is reused on later launches.

## Open Preview

Choose **Settings → Tools → Open Preview & Calibrator**. Load a background and
sprite, then drag to move the character or scroll to resize it. Use **Calibrate**
to adjust the lighting and **Save profile** to keep your settings.

## Update

Open the newer SceneLight, select your installed game and choose **Update
SceneLight**. Downloading a new package alone does not update a game’s installed
runtime or surface maps.

For developer projects, use **For mod developers → Check new assets → Update
SceneLight**. [Author guide](AUTHOR_QUICKSTART.md).

## Remove

Use **Settings** to remove the selected installation. SceneLight checks its
files and backs up saves before removing an in-place install. Some older games
keep a small compatibility script so their saves still load.

## Requirements

Windows with compatible graphics. Live analysis requires OpenGL 3.3 or OpenGL
ES 3.0 with supported floating-point rendering. A dedicated GPU is not required.
[Compatibility and hardware details](BETA_VALIDATION.md).
