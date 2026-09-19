# Preview

Use **Open background** and **Open sprite / animation** to preview one sprite.
Opening another sprite replaces the current one and retains the lighting settings.
Drag to position it, use the mouse wheel to scale it, or use the right-side
Horizontal, Baseline, and Character height controls. Dragging keeps precise
coordinates even though the percentage labels are rounded for display.

Choose a Lighting preset, adjust Lighting strength, and open **Calibrate** for
the Basic, Advanced, Glow & emitted light, and Color glow tabs. **Original** and
**Split comparison** let you compare against the unchanged artwork.

## Glow

**Sprite glow** ranges from 0 to 10. The **Artwork → color** slider blends from
artwork colors to a custom glow color. Halo spread controls the reach; leave
transparent padding around the sprite so its halo has room.

**Color glow** adds any number of rules for selected colors in the artwork.
Choose a color, widen Color range to include nearby shades, and adjust Soft edges,
Glow strength (0–10), and Halo spread. Each rule can be enabled, duplicated, or
removed. Matching uses the original artwork before lighting and tint. More active
rules require more rendering time.

Cast-light controls remain available for configuration. They illuminate other
characters in-game; check their result in the mod because Preview shows one sprite.

## Profiles, exports, and the mod API

**Save profile** preserves calibration, color glow rules, and lighting strength.
**Export config** writes project-wide lighting values while retaining existing
asset-discovery settings. **Export PNG / GIF / video** exports the preview, including
animated sprites and backgrounds.

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
