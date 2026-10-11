# Lighting continuity

Moving backgrounds should change the lighting smoothly while preserving real
flashes, fades and scene cuts.

## Stable lighting regions

The analyzer combines four overlapping regions of the background. Those regions
stay fixed when bright patches split, merge or change brightness, preventing a
small change in the background from abruptly replacing the main light.

Colored lights contribute together instead of switching to a single winning
color. Brightness and color use the current frame; the analyzer does not delay
flashes or blur lighting changes over time.

## Preview and game playback

Preview and the game use the same exposure calculation. Prepared movies retain
the lighting for each frame, while live backgrounds are analyzed as they render.
Transitions keep separate lighting for their outgoing and incoming backgrounds.

If lighting flickers while the scene is still, or jumps during an otherwise
smooth transition, [capture a recording and inspector report](TROUBLESHOOTING.md#flicker-shimmer-or-transition-artifacts).

[Prepared playback](prepared-playback.md) · [Architecture](ARCHITECTURE.md) · [Contributor checks](TESTING.md)
