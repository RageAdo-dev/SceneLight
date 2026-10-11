# Find and report a problem

[Install and update](INSTALL.md) · [Inspector reference](MOD_AUTHOR_API.md#inspect-an-actual-game-scene) · [Known issues](COMPATIBILITY.md)

## Lighting looks wrong in a game

1. While the affected sprite is still visible, press **Shift+F9**.
2. Select that sprite. **Applied settings** shows the effective values;
   **All sources** shows which profile, script rule or player setting supplied them.
3. Use the sliders or **Edit** to try a value. Use **Reset** to undo one edit or
   **Clear all test edits** to undo the whole experiment.
4. Open **Checks** to add a short description, then choose **Export report**.

The inspector saves a `scenelight-support-*.zip` beside `game/` with a readable
report, settings and logs, with an optional screenshot. Story rules and save files
are not included. Review the ZIP before sharing: project names and user-supplied
error text may remain.

Inspector edits are temporary. New game, loading and restarting clear them;
closing the panel alone keeps them active. To keep a lighting choice permanently,
put it in the project config or [mod API](MOD_AUTHOR_API.md).

If **Shift+F9** does nothing, select the project in Setup and open **Settings →
Advanced → Include in-game inspector → Apply to project**. Restart the game.
An older installed runtime may need **Update SceneLight** first.

### Flicker, shimmer or transition artifacts

Capture a short recording that includes what happens immediately before the issue
and several seconds afterward. Export the inspector report before restarting.
Include:

- Whether the sprite keeps shimmering while standing still.
- Whether switching SceneLight off stops it, and whether restarting clears it.
- The nearby `scene`, `show` and `hide` statements, plus the definitions of any
  transforms used there, if you can share them.
- Whether it began after a pose change, transition, resize, fullscreen switch,
  save load, or a longer play session.

If this begins after adding scenes or assets, apply pending updates in Setup and
restart the game. If it persists, send the recording and report.

## Preview changes do not appear in the game

1. Open **Save / export** and review **Current values**, the destination and **File preview**.
2. Choose **Write reviewed config** for the intended project, or save its profile.
3. Select that project in Setup, run **Update SceneLight**, then restart the game.
4. Check **All sources** in the inspector for background, scene, character, image
   or player overrides that take precedence over the exported defaults.

Compare the same sprite, background, placement and settings. A Preview strength
of 78% corresponds to `strength=0.78`. The inspector shows the final value, including
the player master multiplier. Inspector test edits do not automatically become
Preview defaults or permanent project rules.

## Installation or update is taking a long time

The progress percentage belongs to the named stage. Reaching 100% for sprite maps
can be followed by cache saving, runtime transfer, verification and cleanup.
Wait for the final completion message. The Cancel button stops the operation;
it does not finish the update.

Open **Settings → Activity** and select the active session. The stage, elapsed
time, counts and current item help distinguish ongoing work from an error.
Use **raw console** for the retained command output. Search or filter the session,
then choose the report export. Include game logs when reporting gameplay issues.

A compatible runtime/settings-only update keeps prepared asset maps. New artwork,
changed discovery settings or incompatible caches still require preparation.

## A missing sprite or background is reported

Missing or individually unsupported assets are skipped while usable assets
continue. Activity and the report retain the asset names and reasons. Repair the
source artwork and run Scan/Update to reconsider it. A write failure or a renderer
that cannot initialize needs attention; it is not treated as missing artwork.

## Useful details for an issue

Include the SceneLight package/build, Ren’Py version, GPU/driver, steps to reproduce,
and whether the problem affects Preview or the game. For a slow update, include
how many assets changed and whether the project/cache are on an SSD, hard drive
or different drives. Share the complete Activity export where possible, since a
log ending may omit the expensive earlier phases.

[Open a bug report](https://github.com/RageAdo-dev/SceneLight/issues/new?template=bug_report.yml).
Reports are saved locally; nothing is uploaded automatically.
