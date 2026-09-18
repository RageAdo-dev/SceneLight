# Installation

Back up your game or project folder and saves before installing. It gives you an
easy way back if setup is interrupted or your game isn’t compatible.

[Open Windows downloads](https://github.com/RageAdo-dev/SceneLight/releases).
Choose the small **Windows-online.zip** for online setup, or **Windows.zip** for
the complete offline app. Extract the entire ZIP, then open **SceneLight.exe**.

The online installer displays the download size, downloads the same tested payload
as the offline ZIP, and checks its pinned SHA-256 before installing. It keeps the
app and runtime under `%LOCALAPPDATA%\SceneLight\installed` and reuses them on later
launches. No administrator access or system Python installation is needed. Close
the download window to cancel; reopen the installer to retry a failed download.

The offline ZIP runs directly from its extracted folder. Setup, Preview and the
legacy compatibility runtime are included; optional CUDA acceleration may still
need a download. Choosing online setup changes when the main payload is downloaded,
not the total size of its required components.

Private beta releases use the complete Windows ZIP. Download it while signed in
to an account with repository access, or receive it directly from the maintainer.
The current small online installer does not authenticate to private GitHub assets;
publish it only when its matching payload is publicly downloadable.

For release builders: build the complete ZIP first, then run
`python tools/build_online_installer.py dist/SceneLight-v1.0.0-Windows.zip --release-tag <tag>`.
Publish both ZIPs under that exact tag. The online ZIP pins the complete ZIP's hash;
rebuild it whenever the payload changes. Local candidate installers cannot download
their payload until that matching release asset is published. The release workflow
builds and includes both variants automatically.

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

You can select the outer folder created by extracting a game ZIP. Setup looks
inside a few levels and uses the game folder when it finds exactly one. If there
are several games, it asks you to choose the intended one.

Setup detects optional CUDA acceleration in the background and shows the NVIDIA
GPU it found. It verifies an installed CUDA backend or checks for compatible
CUDA 12 tools before recommending the download. Choosing **No** on the optional
CUDA prompt continues with CPU analysis; live lighting still uses compatible
graphics hardware. Settings → Advanced shows the detection result.

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
