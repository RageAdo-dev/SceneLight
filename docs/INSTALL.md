# Installation

| Download | Details |
| --- | --- |
| [Online setup](https://github.com/RageAdo-dev/SceneLight/releases/latest/download/SceneLight-v1.1.0-Windows-online.zip) | Small download; installs the app on first launch (230 MB). |
| [Offline package](https://github.com/RageAdo-dev/SceneLight/releases/latest/download/SceneLight-v1.1.0-Windows.zip) | 230 MB. Includes the app and required components. |

Extract the ZIP and open **SceneLight.exe**. No administrator access or separate
Python installation is needed.

Keep a backup of your game and saves before installing.
[System requirements](COMPATIBILITY.md).

## Add lighting to a game

1. Select the folder containing your game.
2. Scan and review the character checklist.
3. Choose **Add to this game** or **Create separate copy**.
4. Wait for the completion message. With **Add to this game**, choose **Play installed game** or use the game’s usual executable. With **Create separate copy**, choose **Launch existing SceneLight copy**; your original shortcut still opens the unmodified game.

If Setup shows **Open game folder** for a source project without an executable,
open that project through the matching Ren’Py SDK. Use Ren’Py 7 for Python 2
projects and Ren’Py 8 for Python 3.

For your own mod, choose **For mod developers** and follow the
[author quickstart](AUTHOR_QUICKSTART.md).

During preparation, the stage headings show completed and remaining steps. Select
a heading to see its details. The percentage applies to the current task; wait for
the completion message before launching. Setup also shows elapsed time, asset
counts and an estimate of the time remaining when enough information is available.
**Cancel** stops the operation. **Settings → Activity** contains the full log.

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

For a manual project update, choose **Check changed assets → Update SceneLight**
and restart the game after it completes. Unchanged artwork and compatible prepared
data are reused. New or replaced artwork is checked again.

Mod developers can leave Setup open and use [live updates](AUTHOR_QUICKSTART.md#live-updates-while-editing)
while editing and playtesting. Live updates are enabled by default for developer installations.

Use the same steps after saving Preview settings to the project. If they still
do not appear, [check which rules the game is applying](TROUBLESHOOTING.md#preview-changes-do-not-appear-in-the-game).

If an update was interrupted, reopen SceneLight and select the same game. Let it
finish checking and recovering the installation before starting another update.
[Recovery help](TROUBLESHOOTING.md#an-update-was-interrupted).

## Remove

Use **Settings** to remove the selected installation. SceneLight checks its files
and backs up saves before removing an in-place install. Some older games retain
a small compatibility script needed by their saves.

[Troubleshooting](TROUBLESHOOTING.md) · [Installing from source](../CONTRIBUTING.md#development-setup)
