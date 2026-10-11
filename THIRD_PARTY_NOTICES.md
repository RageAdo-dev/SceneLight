# Third-party notices

SceneLight uses NumPy, Pillow, OpenCV, psutil, PySide6-Essentials and imageio-ffmpeg.
Preview also uses PyOpenGL; optional NVIDIA acceleration uses CuPy.
Their licenses are separate from SceneLight's MIT license. Binary distributions
must retain the applicable notices, including those for FFmpeg.

Windows packages also include CPython and Tcl/Tk. Their notices remain under
`_scenelight/python`, including `LICENSE.txt` and the Tcl/Tk license files.
Python dependency notices remain in their installed package and `.dist-info`
directories under `_scenelight/python/Lib/site-packages`.

## Qt and PySide6

Preview uses **PySide6-Essentials 6.11.2**, **Shiboken6 6.11.2** and their bundled
Qt libraries. These are included unmodified as separate dynamic libraries.
The open-source license options and component notices are documented in
[Qt for Python's licenses](https://doc.qt.io/qtforpython-6.11/licenses.html).
License texts: [LGPL v3](docs/licenses/LGPL-3.0-only.txt) and
[GPL v3](docs/licenses/GPL-3.0-only.txt).

Upstream package notices remain in the `pyside6_essentials-6.11.2.dist-info`
and `shiboken6-6.11.2.dist-info` directories under
`_scenelight/python/Lib/site-packages`. Source code is available from
[Qt for Python](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.11.2)
and the [Qt 6.11.2 source archive](https://download.qt.io/archive/qt/6.11/6.11.2/single/).
The license texts above are retained from Qt for Python's `v6.11.2` source.

## FFmpeg

Video export and movie preparation call a bundled **FFmpeg 7.1** binary from
imageio-ffmpeg (`gyan.dev` essentials build) as a separate process. That build
enables GPL components, so it is distributed under the **GPL v3**; the full text
is at [docs/licenses/FFMPEG-GPL-3.0.txt](docs/licenses/FFMPEG-GPL-3.0.txt), and
the source for that exact build is published at <https://www.gyan.dev/ffmpeg/builds/>.
Because SceneLight invokes FFmpeg as a separate program rather than linking
against it, SceneLight itself remains MIT licensed.

## Ren'Py

Windows packages include the official **Ren'Py 7.7.1** compatibility runtime for
legacy games. Its MIT license and other dependency notices remain in
`_scenelight/compatibility-runtime/LICENSE.txt`. No user game or mod content is bundled.

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
