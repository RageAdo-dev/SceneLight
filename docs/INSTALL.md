# Installation

[Download SceneLight for Windows](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.1.0).
Extract **SceneLight-v1.1.0-Windows.zip** and open **SceneLight.exe**.
You do not need administrator access or a separate Python installation.
Private downloads require repository access or a copy from the maintainer.

Keep a backup of your game and saves before installing.
Check [compatibility](COMPATIBILITY.md) if you are unsure about your game or graphics hardware.

## Add lighting to a game

1. Select the folder containing your game.
2. Scan and review the character checklist.
3. Choose **Add to this game** or **Create separate copy**.
4. Wait for the completion message, then launch the game normally.

For your own mod, choose **For mod developers** and follow the
[author quickstart](AUTHOR_QUICKSTART.md).

Preparing a large game can take time. The percentage applies to the current stage;
100% does not mean the whole installation has finished. **Cancel** stops the
operation. **Settings → Activity** shows progress and any errors.

CUDA acceleration is optional. Declining it keeps CPU preparation available;
the game still needs working graphics acceleration.

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
