# Live light identity continuity

Two similarly strong fixtures could exchange the primary-light slot when their
scores crossed by less than one percent. Because the primary light also controls
key shadows and rim direction, that slot swap produced a large visible change
even with analysis running on every decoded frame.

The shared live analyzer now matches physical emitters against the previous
frame by position and color. For near-tied scores it retains their ordering.
The matching intensity threshold is 0.95; intensities are square roots of
normalized detection scores, so this gives about a ten-percent score margin.
Stronger challengers take precedence immediately. Every returned light still
uses its current position, color, confidence, and intensity; this is not a
low-pass filter over the scene's brightness.

A small background comparison rejects history after substantial visual changes.
Ren'Py keeps history separately for each showing's binding, outside save data;
a new binding starts fresh. Preview resets history on a new source, graphics
context replacement, and export timeline restarts. Two small RGBA8 history
textures require 2,448 bytes per retained frame, plus bounded analyzer scratch.
There is no CPU pixel readback in production.

`Analysis.evaluate(previous=None)` retains the stateless reference behavior.
Pass `previous=()` to begin a live sequence, then pass the returned
`(_history_lights, _history_image)` texture IDs to continue it. The caller must
retain valid textures in the same graphics context. Ren'Py copies these into
engine-owned textures so concurrent backgrounds cannot share mutable history.

The reproduced yellow-room clip had two large transport-field jumps at frames
40 and 58 (24 fps). Its worst adjacent-frame byte delta dropped from 206 to 8.
Native Ren'Py 7.7.1 and 8.5.2 tests covered the two-character yellow scene and
the station's AnimatedAberate effect. After the initial start-image handoff,
sampled key-light position deltas stayed at most 2 and 1 byte levels respectively.
The authored start-image/movie handoff is a separate actual input transition;
the audit retains that event rather than describing it as a steady-video jump.

Regression tests cover near ties, immediate stronger-light selection, immediate
cut reset, unchanged static fields, and separate histories for separate bindings.
These checks complement per-frame numerical parity and performance tests.
