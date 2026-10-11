# Prepared movie lighting

SceneLight prepares lighting for every supported movie frame during installation
or Preview import. With the default live-analysis setting and compatible graphics,
preparation uses the production GPU analyzer in source order, including light
continuity. Resolution, light count, transport, calibration and shadows are unchanged.

## Storage and playback

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

Game caches include separate exact results for OpenCV's conversion and FFmpeg's
tag-aware conversion. This covers the different RGB output observed in legacy
and current Ren'Py decoders. Each variant is analyzed in source order. This adds
preparation time and disk storage; playback still retains only two lighting frames.
Decoder variants use exact signatures, with the same ambiguity checks.

## Cache validity

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

## Components

The package includes Qt Essentials, PyOpenGL and FFmpeg. Movie preparation uses
these components without opening Preview. If components are missing, Setup
reports how to repair them before preparing movies.

The sprite shader also skips unused form-lighting work on transparent canvas
pixels. The alpha threshold is unchanged, and later shader parts still execute.
This optimization was checked against the previous shader with complete rendered-pixel comparisons on NVIDIA and the
2011 iMac's AMD graphics hardware.
