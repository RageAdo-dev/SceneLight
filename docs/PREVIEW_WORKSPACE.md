# Preview & Calibrator

Open **Settings → Tools → Open Preview & Calibrator** in SceneLight.

![Preview with lighting controls beside the canvas](media/preview-workspace.png)

## Place and compare

Use **Open background** and **Open sprite / animation**. Preview shows one sprite;
opening another replaces it and keeps your lighting settings.

Drag the character to move it and scroll over the canvas to resize it. The
right-side placement controls allow finer adjustments. Choose a lighting preset
and strength, then use **Original** or **Split comparison** to compare the result.

At 0% strength, scene lighting leaves the artwork unchanged. Glow is controlled
separately. **Exposure bias** brightens or darkens the result.

## Lighting, glow and color

Open **Adjust** or press **Calibrate**. The controls stay beside the canvas so you
can keep moving the sprite.

| Page | Controls |
| --- | --- |
| Lighting | Strength, exposure, shadows and highlights |
| Sprite glow | Whole-sprite glow, halo spread and artwork-to-color tint |
| Color glow | Glow only selected artwork colors; add, duplicate or remove rules |
| Light color | Increase or reduce a selected background color’s influence |
| Advanced | Additional lighting adjustments |
| Cast light | Configure light emitted onto other characters; test it in-game |

Glow strength ranges from 0 to 10. For color glow, widen **Color range** to include
nearby shades and use **Soft edges** to smooth the selection. Leave transparent
padding around a sprite so its halo has room. More active color rules cost more
rendering time.

## Save settings to a game

1. Choose **Save profile** or **Export config** to open **Save / export**.
2. Review **Current values**, the destination and **File preview**.
3. Choose **Save profile** or **Export config**.
4. In Setup, select the project, run **Update SceneLight**, and restart the game.

Preview and Setup load the project’s `scenelight.json`, then its saved calibration
profile. An explicitly selected config overrides both. **Save / export** lists
the files in that order; the last file wins for matching settings.

**Save profile** stores calibration for that project. Exporting to the project’s
`scenelight.json` also updates its existing calibration profile so old defaults
cannot override the export. Both files appear for review before you save. Existing
discovery and per-background/per-sprite rules remain intact. Exporting elsewhere
creates a portable config; select or copy it into the intended project before updating.
Strength uses the same scale: **78% is 0.78**.

The game may apply additional background, character or player overrides. Press
**Shift+F9 → All sources** to see them. Inspector test edits do not automatically
become saved rules or Preview defaults.

## Export an image or video

Choose **Export PNG / GIF / video** for the rendered result, including animations.
Exports support 720p, 1080p and 4K; a JSON file beside the output records the settings.
Video keeps its frame rate; GIF timing is limited to the format’s 10 ms increments.

[API reference](MOD_AUTHOR_API.md) · [Troubleshooting and reports](TROUBLESHOOTING.md)
