# Preview

Use **Open background** and **Open sprite / animation** to preview one sprite.
Opening another sprite replaces the current one and retains the lighting settings.
Drag to position it, use the mouse wheel to scale it, or use the right-side
Horizontal, Baseline, and Character height controls. Dragging keeps precise
coordinates even though the percentage labels are rounded for display.

Choose a Lighting preset and adjust Lighting strength. The right-side **Adjust**
page opens by default; **Calibrate** returns to it. Its visible buttons open
**Lighting**, **Sprite glow**, **Color glow**, **Light color**, **Advanced**, and
**Cast light**. These buttons stay above the scrollable controls. Controls update the
preview live without a dialog blocking the canvas. Placement, preset, and
strength remain above the pages, and you can continue dragging/scaling the sprite.
**Original** and **Split comparison** compare against the unchanged artwork.

At 0% Lighting strength, scene lighting leaves the source artwork unchanged;
explicit sprite glow remains independent. Bright scenes use a restrained automatic
exposure boost, and highlight protection retains existing painted detail. Use
Exposure bias when you deliberately want a stronger brightening effect.

## Glow

**Sprite glow** ranges from 0 to 10, with both a slider and a numeric input.
The **Artwork → color** slider blends from
artwork colors to a custom glow color. Halo spread controls the reach; leave
transparent padding around the sprite so its halo has room.

**Color glow** adds any number of rules for selected colors in the artwork.
Choose a color, widen Color range to include nearby shades, and adjust Soft edges,
Glow strength (0–10), and Halo spread. Each rule can be enabled, duplicated, or
removed. Choose **+ Add color** to create the first rule. Scrolling the settings
panel does not change slider or numeric values. Matching uses the original artwork
before lighting and tint. More active
rules require more rendering time.

**Cast light** controls remain available for configuration. They illuminate other
characters in-game; check their result in the mod because Preview shows one sprite.

## Profiles, exports, and the mod API

**Save profile** and **Export config** open the **Save / export** page. They do
not immediately write a file. **Current values** shows every Preview calibration
value and each color glow rule; bold values differ from defaults. Strength shows
both units (78% is 0.78). Use **Edit lighting values** to adjust them.

Choose the destination and inspect **File preview**, which shows the exact JSON
that will be written. **Save reviewed profile** or **Write reviewed config** is
the final write action. Closing or switching pages does not save. A file changed
outside Preview must be reviewed again before it can be overwritten. Failed
writes leave the prior file intact.

Profiles preserve Preview defaults for subsequent builds. Config export updates
global lighting defaults while retaining existing discovery settings and
per-background/per-sprite rules, including scene calibration overrides. Use
Setup's project update to apply the saved settings to an installed game. Preview
values describe its loaded sprite; use the in-game inspector (Shift+F9) to see
the game's effective values and any additional overrides.

**Export PNG / GIF / video** exports the rendered preview, including animated
sprites and backgrounds.

Per-character and per-image settings remain in the [mod API](MOD_AUTHOR_API.md).
Use an exact image rule when only that sprite should change:

```renpy
init python:
    scenelight.image("fire burning", strength=0.7, glow_strength=6.0,
        glow_rules=[{"color": [1.0, 0.1, 0.02], "strength": 8.0,
                     "tolerance": 0.2, "softness": 0.1, "radius": 1.0}])
```

The searchable **Settings → Advanced → Developer guide** includes the commands,
ranges, scope precedence, tint, emitted light, and selective color glow examples.

## Bug reports

Open **Settings → Activity** in Setup, then select the Preview session. Select the
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
