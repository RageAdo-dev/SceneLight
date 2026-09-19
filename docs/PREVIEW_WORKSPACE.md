# Preview workspace

## Characters and lighting

Use **Add character** to keep multiple sprites in the same scene. Select a character
in the list, or click its visible artwork, before changing placement or lighting.
The selected character's strength, calibration, glow, and emitted light are independent
of the others. **Exact lighting strength** accepts a number from 0 to 2.

**Duplicate**, **Remove**, **Back**, **Front**, and the visibility checkbox control
the composition. Up to 16 characters can be present. A glowing character can cast
light onto other visible characters; up to four emitting sources affect each receiver,
using the same source selection and falloff as the game renderer.

Open **Calibrate → Glow & emitted light** and choose a custom color. The
**Artwork → color** slider blends from the original colors (0%) to the chosen color
(100%). Intermediate values tint the glowing sprite and halo. Sprite glow must be
above zero. Cast-light color remains separate and controls illumination of neighbors.

Use **Calibrate → Color glow** when only particular colors in the selected artwork
should glow. Add a color rule, choose its color, and adjust **Color range** to match
nearby shades. **Soft edges** feathers the selection; **Glow strength** and **Halo
spread** control the result. Duplicate or add rules for more colors, or disable a
rule without deleting it. Matching uses the original artwork, not a tint created by
scene lighting. Rules affect their character only and are saved with scenes,
library entries, profiles, and exported sprite rules. More active rules take more
rendering time. Existing whole-sprite glow and emitted light are independent.

To use a character's values in a mod, enter its Ren'Py image name, such as `hero happy`,
then choose **Export sprite rules**. Export the selected character or all characters.
Put the resulting `.rpy` file under `game/` after installing the SceneLight developer
API, and include those tags in SceneLight's character selection. The exported rules
use `scenelight.image(...)`; other expressions retain their own settings.

**Export defaults** retains the existing project-wide configuration workflow. Use
sprite rules when only a particular sprite should change.

## Saved assets and layered sprites

**Asset library** stores reusable backgrounds, sprites, and sprite lighting presets.
Use **Save sprite** or **Save background** for the currently loaded asset, or import
files through the library. Assets are copied into SceneLight's private local library
so moving the original file does not break the saved entry.

For sprites made of separate body, clothing, eyes, or expression images, choose
**Build layered sprite**:

1. Add the pieces. Rows draw from back to front.
2. Use X/Y offsets in source pixels, opacity, and visibility to align the pieces.
3. Leave the canvas on Auto, or set both width and height. Transparent pieces that
   already share a canvas usually work at X=0, Y=0.
4. Check the preview and save. The assembled pixels receive one surface analysis.

The saved recipe retains the pieces, offsets, order, and canvas. Select it and use
**Edit layers** to save a revised variant. This editor handles still-image pieces;
add GIF/APNG/WebP animations directly as characters. It does not interpret a mod's
Ren'Py `layeredimage` conditions or automatically guess where cropped pieces belong.

Removing a library entry removes its listing; shared media is retained so saved scenes
and other recipes remain usable.

## Scenes and exports

**Save scene** stores the background, ordered characters, individual lighting, image
names, and placements. Its media is retained in the local library. **Open scene**
restores the composition. Scene JSON references local media; it is not a portable
asset bundle for another computer.

PNG, GIF, and video exports include every visible character. Animated sprites retain
their own frame timings. GIF exports combine their change times into a complete loop;
combined loops longer than ten minutes are rejected rather than producing an
unexpectedly huge export. GIF timing is rounded to its 10 ms resolution, merging
closer frame boundaries. Video exports follow the background video's duration.

## Bug reports

Open **Logs & report** in Preview or **Settings → Activity** in Setup. Select the
session, search messages, or filter to errors/warnings. Choose **raw console** for
retained command output. Sessions remain available after restarting the app.

Use **Include game logs** and select the game's main folder when reporting an
in-game problem. **Export report** saves a ZIP containing:

- A short summary and searchable `report.html`.
- Timestamped stages, worker/process IDs, exit codes, and exception tracebacks.
- Program/runtime fingerprints, component versions, renderer details, and relevant
  Preview settings.
- Retained capture failure evidence and selected game logs.

The game also records `scenelight-runtime.jsonl` beside its executable. It records
sprite/form bindings, actual canvas sizes, selected lighting, exposure ownership,
and transition state when those change. It does not log dialogue or sprite pixels.

Reports never include artwork or save files. Personal home paths and common credential
patterns are redacted; review the ZIP before sharing because project/image names and
user-supplied error text remain. Nothing is uploaded automatically.

Logs are bounded and rotate. The summary and structured events are separate from noisy
console output; older console content can be omitted. A session marked running without
a completion event may still be active or may have been interrupted. Add the steps to
reproduce, what you expected, and the affected scene when sending a report.
