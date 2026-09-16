# Installation

Back up your game or project folder and saves before installing. It gives you an
easy way back if setup is interrupted or your game isn’t compatible.

[Download the Windows package](https://github.com/RageAdo-dev/SceneLight/releases/download/v1.0.0-beta/SceneLight-v1.0.0-Windows.zip).
Extract `SceneLight-v1.0.0-Windows.zip`, then open **SceneLight.exe** in the
extracted folder.

## Install without the Windows app

The packaged app is a convenience, not a requirement. If you already have
Python 3.10 or newer, install SceneLight as a package and Windows never shows a
download warning, because the launcher is created on your own machine instead of
being downloaded as an executable:

```text
pip install git+https://github.com/RageAdo-dev/SceneLight
scenelight-setup
```

`scenelight --help` lists the command-line equivalents, including
`scenelight install --project <game folder>`, and
`python -m scenelight.preview` opens Preview on its own. Everything else in this
guide works the same way.

If you do download the Windows package and would rather not see the one-time
"Windows protected your PC" prompt, right-click the ZIP, open **Properties**,
tick **Unblock**, then extract it. Unblocking removes the marker Windows added
when the file was downloaded.

## Add SceneLight to a game

1. Open **SceneLight.exe** and select your game folder.
2. Scan the game and review the detected characters.
3. Choose **Add to this game** or **Create separate copy**.
4. Let setup finish, then launch the game normally.

The Windows package includes the components needed for Setup and Preview.
Video preparation can take a while; completed work is reused on later launches.
Optional components are installed only with your permission.

## Open Preview

Choose **Settings → Tools → Open Preview & Calibrator**. Load a background and
sprite, then drag to move the character or scroll to resize it. Use **Calibrate**
to adjust the lighting and **Save profile** to keep your settings.

Export at 720p, 1080p or 4K. A small JSON file beside the export records its
settings for reproduction. Videos retain their frame rate; GIFs retain their
frame timings within the format's 10 ms precision.

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
