# Third-party notices

SceneLight uses NumPy, Pillow, OpenCV, psutil, PySide6-Essentials and imageio-ffmpeg.
Preview also uses PyOpenGL; optional NVIDIA acceleration uses CuPy.
Their licenses are separate from SceneLight's MIT license. Binary distributions
must retain the applicable notices, including those for FFmpeg.

Windows packages also include CPython and Tcl/Tk. Their notices remain under
`_scenelight/python`, including `LICENSE.txt` and the Tcl/Tk license files.
Python dependency notices remain in their installed package and `.dist-info`
directories under `_scenelight/python/Lib/site-packages`.

## Ren'Py

Windows packages include the official **Ren'Py 7.7.1** compatibility runtime for
legacy games. Its MIT license and other dependency notices remain in
`compatibility-runtime/LICENSE.txt`. The SDK may include Ren'Py's own launcher
and samples; no user game or mod content is bundled.

## Documentation artwork

The examples use **Eileen by Piroshki**, from the Ren'Py tutorial, under the demo
artwork's MIT terms. See [credits and source details](docs/media/CREDITS.md) and
[the retained notice](docs/media/RENPY_ART_LICENSE.txt).

The forest and waterfall examples also show **Monika from Doki Doki Literature
Club!**, © Team Salvato. The forest photograph is by **Joyce G** on Unsplash;
the waterfall footage is by **Lana Kravchenko** on Pexels. Their respective
terms apply to that artwork, independently of SceneLight's MIT license.

## Independent project

SceneLight is not affiliated with or endorsed by Ren'Py, Team Salvato or Dan
Salvato. DDLC artwork appears only in the rendered documentation examples.
Original DDLC assets, game files and reusable character maps are not bundled.

SceneLight reads the user's project and generates its runtime data locally.
Users and authors are responsible for the rights to their project content.
DDLC projects must follow [Team Salvato's IP Guidelines](https://teamsalvato.com/ip-guidelines).
