# Installation

Back up your game or project folder and saves before installing. It gives you an
easy way back if setup is interrupted or your game isn’t compatible.

[Download the current tester build](https://github.com/RageAdo-dev/SceneLight/releases/tag/v1.1.0).
Choose **SceneLight-v1.1.0-Windows.zip**, extract the entire archive, and open
**SceneLight.exe**. The complete package includes Setup, Preview and the legacy
compatibility runtime. No administrator access or system Python installation is
needed. Optional CUDA preparation acceleration may still need a download.

Private beta downloads require an account with repository access, or a copy from
the maintainer. The small online installer does not authenticate to private GitHub
assets, so it is not the download to use for this tester release. For a public
release it downloads the same complete payload and verifies its pinned SHA-256;
it changes when the payload is downloaded, not its total required size.

For release builders: build the complete ZIP first, then run
`python tools/build_online_installer.py dist/SceneLight-v1.1.0-Windows.zip --release-tag <tag>`.
Publish both ZIPs under that exact tag. The online ZIP pins the complete ZIP's hash;
rebuild it whenever the payload changes. Local candidate installers cannot download
their payload until that matching release asset is published. The release workflow
builds and includes both variants automatically.

## Install without the Windows app

The packaged app is a convenience, not a requirement. If you already have
Python 3.10 or newer, install from the repository:

```text
pip install git+https://github.com/RageAdo-dev/SceneLight
scenelight-setup
```

`scenelight --help` lists the command-line equivalents, including
`scenelight install --project <game folder>`, and
`python -m scenelight.preview` opens Preview on its own. Everything else in this
guide works the same way.

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
to open the right-side **Adjust** page. **Save profile** and **Export config** open
a review page; inspect the current values, destination and exact file contents
before choosing the final save/write action. [Preview guide](PREVIEW_WORKSPACE.md).

Export at 720p, 1080p or 4K. A small JSON file beside the export records its
settings for reproduction. Videos retain their frame rate; GIFs retain their
frame timings within the format's 10 ms precision.

## Update

Open the newer SceneLight, select your installed game and choose **Update
SceneLight**. Downloading a new package alone does not update a game’s installed
runtime or surface maps.

For developer projects, use **For mod developers → Check new assets → Update
SceneLight**. [Author guide](AUTHOR_QUICKSTART.md).

Compatible code-only and lighting-settings updates keep existing asset maps.
Asset changes trigger inventory checks and reuse compatible capture/analysis work.
The final transfer and verification steps are also faster on large installs.
The [benchmark](performance.md#installation-and-update-finalization) measures those
steps separately from capture and image analysis.

### In-game inspector

Press **Shift+F9** during a scene to inspect and temporarily adjust the applied
lighting. Include or remove the tool through **Settings → Advanced → Include
in-game inspector → Apply to project**, then restart the game. This setting is
available for either installation mode. [Diagnostic walkthrough](TROUBLESHOOTING.md).

### Change which characters receive lighting

Choose **Characters…** beside the game folder in either mode. It rescans the
project and reopens the character checklist, including newly found tags. Each tag
covers that character's poses and expressions. On an installed project, **Apply
selection & update** saves the choices and prepares the changed installation.

**Automatically include new characters on scan / update** starts on for new
projects. Unchecked families stay excluded even with this on. Turn it off to add
characters only when you explicitly select them. Existing manual choices remain
manual after upgrading. Settings are saved per project.

While Setup stays open, it checks the selected project every five seconds and
waits for two matching file snapshots before checking the installation again.
Changed files clear the cached scan and show **Check changed assets**. Apply
**Update SceneLight**, then restart the game. New characters need discovery and
prepared lighting maps before they can use the full effect. Player-copy updates synchronize authored game files
while preserving saves and your lighting choices. Developer updates refresh the
embedded runtime and generated maps without replacing story scripts.

## Remove

Use **Settings** to remove the selected installation. SceneLight checks its
files and backs up saves before removing an in-place install. Some older games
keep a small compatibility script so their saves still load.

## Requirements

Windows with compatible graphics. Live analysis requires OpenGL 3.3 or OpenGL
ES 3.0 with supported floating-point rendering. A dedicated GPU is not required.
[Compatibility and hardware details](BETA_VALIDATION.md).

### Missing or incompatible assets

If a mod references missing artwork or an individual image cannot be prepared,
SceneLight skips that asset and continues with the usable backgrounds and sprites.
Setup shows the skipped sprite count. Open **Settings > Activity** to search the
asset names and reasons; **Export support report** includes those details.
After the mod supplies or repairs the artwork, run Scan/Update again to include it.
A renderer that cannot start or an output folder that cannot be written still
requires attention; those failures do not get labeled as missing artwork.

### Progress after sprite maps reach 100%

The percentage applies to the named stage. Setup next shows the saving, copying,
verification, and cleanup steps before announcing completion. File counts update
as work completes. Steps without a known count use an activity indicator and an
elapsed timer. The current filename is shown during copying and verification.
Background-video preparation shows the current video and its processed frame count.
Settings > Activity records the same stages and includes them in exported reports.
An existing installation is not proof that an update has finished. Wait for the
update-completed message and for the Cancel button to disappear. Cancel stops the
current operation; it does not finish the installation.
