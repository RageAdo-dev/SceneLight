# Artwork credits

## Eileen

Eileen is by **Piroshki**, from the Ren’Py tutorial, under the MIT terms in
[Ren’Py’s artwork notice](RENPY_ART_LICENSE.txt). See [Ren’Py’s license](https://www.renpy.org/doc/html/license.html).
The examples use `tutorial/game/images/eileen happy.png` from the Ren’Py SDK.

The warm and blue lamp background is original SceneLight documentation artwork.
The comparison, surface maps and animation were rendered with
[`tools/build_docs_media.py`](../../tools/build_docs_media.py).
The Preview and inspector screenshots were captured on 4 October 2026 using
Ren’Py 8.5.2. The shared-lighting example uses two Eileen sprites with one group anchor.

## Forest and waterfall

**Monika** is from *Doki Doki Literature Club!*, © Team Salvato. These are unofficial
SceneLight demonstrations, with no affiliation or endorsement. DDLC artwork is not
covered by SceneLight’s MIT license. See [Team Salvato’s IP Guidelines](https://teamsalvato.com/ip-guidelines).
The examples use the base game’s `monika 1a` sprite.

- Forest photograph: **Joyce G**, [Unsplash source](https://unsplash.com/photos/green-trees-on-brown-grass-field-during-daytime-HjUxMTsq4GM), under the [Unsplash License](https://unsplash.com/license).
- Waterfall footage: **Lana Kravchenko**, [Pexels source](https://www.pexels.com/video/tranquil-waterfall-in-lush-green-forest-32728606/), under the [Pexels License](https://www.pexels.com/license/).

[`tools/build_scene_examples.py`](../../tools/build_scene_examples.py) renders the
forest and waterfall scenes with Preview’s default calibration.

## Render records

[examples.json](examples.json), [workspace-captures.json](workspace-captures.json)
and the records beside each scene contain source hashes, framing and settings.
The README uses 720p WebP animation; the downloadable GIFs and MP4s are 1080p.
WebP and MP4 use 60 fps, while GIF uses 50 fps and a reduced color palette.

To rebuild the examples with Preview dependencies installed:

```text
python tools/build_docs_media.py /path/to/renpy-sdk /path/to/scratch
python tools/build_scene_examples.py /path/to/forest.png /path/to/sprite.png /path/to/scratch --name forest-example --crop-y 0.47
python tools/build_scene_examples.py /path/to/waterfall.mp4 /path/to/sprite.png /path/to/scratch --name waterfall-example --horizontal 0.73 --seconds 2
```

An OpenGL 3.3 context is required. Keep source game assets and scratch files outside the repository.
