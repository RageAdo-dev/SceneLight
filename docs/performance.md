# Performance

## Installation and updates

The first installation prepares lighting data for the selected sprites and
backgrounds. Preparation time depends on the number and size of the assets,
available memory, processor and storage speed.

Updates reuse compatible prepared data. Adding artwork prepares the new assets;
changes to the analysis settings or algorithms can require rebuilding existing
maps. Runtime or lighting-rule changes can often be applied without preparing
all the artwork again.

Completed captures are saved so interrupted preparation can resume. Keep the
project's cache if you plan to update it again. **Settings → Activity** shows
which stage is running and how much work has finished.

For large projects, use an SSD if available and keep enough free space for the
game copy, prepared maps and temporary files. CUDA can accelerate preparation on
supported NVIDIA hardware; it is optional.

## In-game lighting

Sprite maps are prepared at the source image's resolution. Moving a character
reuses its maps and samples lighting at the new position.

Supported movies use [prepared lighting](prepared-playback.md), with two decoded
lighting frames held in memory. Procedural or transformed backgrounds may need
live analysis. Their performance depends on the scene and graphics hardware.

More characters, large sprites, multiple glow rules and custom shaders can
increase rendering cost. Compare the same scene and settings when measuring
performance. GPU usage alone does not tell you whether frames are arriving smoothly.

See [compatibility](COMPATIBILITY.md) for graphics requirements and
[troubleshooting](TROUBLESHOOTING.md#installation-or-update-is-taking-a-long-time)
for slow installation or update reports.

## Profiling tools

For contributors:

- `tools/profile_live_analysis.py`: analysis time, GPU passes and texture memory.
- `tools/compare_live_analysis.py`: compare analyzer outputs on the same frames.
- `tools/audit_preview_playback.py`: presentation rate and memory use.
- `tools/fixtures/live_memory_audit.rpy`: native memory checks in a disposable game copy.

Record the hardware, scene, settings and measured stage alongside any timings.
