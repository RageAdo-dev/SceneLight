# Installation

| Download | Details |
| --- | --- |
| [Online setup](https://github.com/RageAdo-dev/SceneLight/releases/download/v1.0.0/SceneLight-v1.0.0-Windows-online.zip) | Downloads the app on first launch (230 MB). |
| [Offline package](https://github.com/RageAdo-dev/SceneLight/releases/download/v1.0.0/SceneLight-v1.0.0-Windows.zip) | 230 MB. App and required components included. |

Extract the ZIP and open **SceneLight.exe**. No administrator access or separate
Python installation is needed.

Keep a backup of your game and saves before installing.
[System requirements](COMPATIBILITY.md).

## Add lighting to a game

1. Select the folder containing your game.
2. Scan and review the character checklist.
3. Choose **Add to this game** or **Create separate copy**.
4. Wait for the completion message. With **Add to this game**, use the game’s usual executable. With **Create separate copy**, use **Open game folder** on the completion screen and launch that copy; your original shortcut still opens the unmodified game.

For a source project without a game executable, open the prepared project through
the matching Ren’Py SDK. Use Ren’Py 7 for Python 2 projects and Ren’Py 8 for Python 3.

For your own mod, choose **For mod developers** and follow the
[author quickstart](AUTHOR_QUICKSTART.md).

Preparing a large game can take time. The percentage applies to the current stage;
100% does not mean the whole installation has finished. **Cancel** stops the
operation. **Settings → Activity** shows progress and any errors.

CUDA acceleration is optional and may need a separate download. Declining it
keeps CPU preparation available; the game still needs working graphics acceleration.

## Change character choices

Choose **Characters…** beside the game folder. Selecting a character includes its
poses and expressions. For an installed game, use **Apply selection & update**.

**Automatically include new characters on scan / update** is enabled for new
projects. Characters you uncheck stay excluded. Turn it off if you want to choose
every new character yourself.

## Preview and in-game controls

Open **Settings → Tools → Open Preview & Calibrator** to adjust lighting beside
the canvas. [Preview and saving settings](PREVIEW_WORKSPACE.md).

Press **Shift+F9** during a game scene to open the lighting inspector. Its edits
are temporary. Include or remove it through **Settings → Advanced → Include
in-game inspector → Apply to project**, then restart the game.
[Inspector walkthrough](TROUBLESHOOTING.md#lighting-looks-wrong-in-a-game).

## Update

Open the newer SceneLight, select the installed game and choose **Update SceneLight**.
Downloading a package alone does not update an installed game.

When Setup detects project edits, choose **Check changed assets → Update SceneLight**.
Restart the game after the update completes. Compatible prepared data is reused;
new or changed artwork may need preparation.

Use the same steps after saving Preview settings to the project. If they still
do not appear, [check which rules the game is applying](TROUBLESHOOTING.md#preview-changes-do-not-appear-in-the-game).

## Remove

Use **Settings** to remove the selected installation. SceneLight checks its files
and backs up saves before removing an in-place install. Some older games retain
a small compatibility script needed by their saves.

[Troubleshooting](TROUBLESHOOTING.md) · [Installing from source](../CONTRIBUTING.md#development-setup)
