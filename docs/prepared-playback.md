# Prepared movie lighting

On supported GL renderers, SceneLight prepares every video frame when an animated
background is imported in the Preview. Normal player installations also prepare
movies when live analysis is selected. The required Qt Essentials and FFmpeg
components are included in player setup; opening Preview is not required.
Preparation uses the production GPU analyzer, in source order,
with the existing light-continuity history. Lighting resolution, light count,
transport, form reconstruction, calibration, and contact shadows are unchanged.

The resulting `.slframes` archive stores losslessly compressed copies of the
four shader inputs, including the transport metadata row. It costs 189,440 bytes
per frame before compression. A tested five-second, 24 fps Backrooms movie used
about 5 MiB on disk. Playback retains two decoded lighting frames and a bounded
pool of graphics textures; it does not load the whole movie's lighting into RAM.

The Preview pairs lighting with the decoder's exact frame index. Ren'Py's movie
clock can disagree with the displayed frame, so the native runtime identifies the
existing decoded surface using a small pixel sample. Preparation checks those
signatures across every frame. A signature shared by different lighting results
is ambiguous and cannot select cached lighting. The sample identifies a frame;
it does not reduce the resolution or quality of the lighting calculation.

Caches include the source content hash and analyzer identity. Changed media or
analyzer code requires preparation again. Incomplete archives are never published,
and reopening a valid Preview cache requires no analysis. Cancelling preparation
stops its worker process tree and removes its partial archive.

Native caches currently apply to full-canvas movies at their prepared dimensions,
including neutral engine placement wrappers. Authored transforms, masks,
procedural backgrounds, incompatible decoders, and ambiguous frame matches use
live analysis of the actual rendered background. This preserves their appearance;
it does not guarantee that procedural effects will reach movie playback speed on
old hardware. Rendering still uses Ren'Py's normal graphics renderer.

The default Python package includes the preparation components. The `preview`
extra adds the full Preview interface. If required playback components were
removed or installation used `--no-deps`, movie installation reports how to repair
them instead of silently selecting a more expensive playback path.

The sprite shader also skips unused form-lighting work on transparent canvas
pixels. The original alpha threshold and contact-shadow calculation remain in
place, and later shader parts still execute. This optimization was checked against
the previous shader with complete rendered-pixel comparisons on NVIDIA and the
2011 iMac's AMD graphics hardware.
