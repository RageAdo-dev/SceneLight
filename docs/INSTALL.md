# Installing SceneLight

SceneLight is currently being tested privately. Repository access is needed to
download the test packages. There is no public release yet.

## Get the Windows package

Open a successful [Build release ZIP run](https://github.com/RageAdo-dev/SceneLight/actions/workflows/release.yml)
and download its **SceneLight-Windows** artifact. Inside that download, extract
`SceneLight-v1.0.0-Windows.zip` to a folder you can write to. The `-source.zip`
variant is for working on SceneLight itself.

Double-click **SceneLight.bat**. Setup lists any required components before
installing them into SceneLight’s folder under `%LOCALAPPDATA%\SceneLight`.
It does not need administrator access or change your system Python installation.
The normal package needs an internet connection for its first dependency setup.

## Add it to a game

1. Choose the folder containing the game’s executable and `game` folder.
2. Scan the game. Review the detected character groups and exclude stickers,
   interface art, props and anything else that should not receive character lighting.
3. Choose **Add to this game** to install in place, or **Create separate copy**
   to make a SceneLight-enabled copy and leave the selected folder untouched.
4. Wait for preparation to finish, then launch the normal game executable.

Preparation builds character surfaces, background data and full lighting for
every frame of supported movies. Longer videos need more preparation time and
disk space. Setup reports progress and skipped assets in its activity log.
Later launches reuse completed data.

Games with archived scripts or images may need an isolated copy of their Ren’Py
runtime for discovery. Only install games you trust: discovery can execute the
game’s code. Automatic suggestions still need review, and some games cannot be
mapped automatically. See [compatibility](BETA_VALIDATION.md).

## Open Preview

Use **Settings → Tools → Preview & Calibrator**. You can open it before selecting
a game. Setup offers to install the optional Preview components if needed.

Choose a background and a transparent sprite. Drag the character to change its
position; use the mouse wheel to change its size. The comparison selector shows
the original image, the relit result or a split view. **Calibrate** opens the
lighting controls. **Save profile** stores your settings locally; **Export config**
writes settings for a project. PNG, GIF and video exports are also available.

## Update an installation

An installed game contains its own SceneLight runtime. Updating this repository
or downloading a newer package does not update that game automatically.

Open the newer Setup, select the existing game and use its update action.
Compatible preparation is reused; changed art or a new surface-map version
requires rebuilding the affected maps. The smooth-surface correction in form-map
version 4 needs that rebuild to remove the old height ridges.

For a developer installation, open **For mod developers → Check new assets**,
review any new character families, then choose **Update SceneLight**. An added
pose under a selected character tag can use the generic form fallback until its
own maps are ready. [Author setup details](AUTHOR_QUICKSTART.md).

## Remove SceneLight

Use **Settings** to verify or remove the selected installation. SceneLight checks
its installed files first and stops if they were changed. In-place removal also
backs up current saves.

Some legacy Ren’Py 6 games need a small save-compatibility script after removal
to load saves written by the Ren’Py 7 compatibility runtime. That script contains
no lighting code. Removing a managed copy does not change the original game.

## Graphics and performance

Compatible integrated graphics are supported; a dedicated GPU or NVIDIA CUDA is
not required. This is still a graphics-accelerated renderer, not a CPU-only
software renderer. Prepared movie lighting avoids repeating the analysis while
the video plays, but Ren’Py still draws the scene using its graphics renderer.

Live analysis requires OpenGL 3.3 or OpenGL ES 3.0 and the required floating-point
rendering operations. For older renderers, a project can use
`"scene_analysis": "cached"` for offline scene preparation. Check the
[tested hardware and limits](BETA_VALIDATION.md#playback-and-hardware) before
assuming a particular frame rate on a low-end laptop.
