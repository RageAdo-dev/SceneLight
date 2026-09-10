# Third-party notices

SceneLight depends on NumPy, Pillow, OpenCV, and psutil. The optional Preview &
Calibrator also uses PySide6, PyOpenGL, and imageio-ffmpeg.
Optional NVIDIA acceleration uses CuPy. Their licenses are not replaced by
SceneLight's MIT license. Binary distributions must reproduce the applicable
notices, including the license information for the FFmpeg executable supplied
by imageio-ffmpeg.

The optional Windows offline release can include an unmodified, trimmed copy of
the official Ren'Py 7.7.1 runtime solely as a compatibility layer for legacy Ren'Py
6/Python 2 games. Ren'Py is licensed under the MIT license. Its original
`LICENSE.txt` is retained inside `compatibility-runtime/`; no Ren'Py sample
project, launcher UI, tutorial, or third-party game content is included.

SceneLight does not download or bundle third-party game or mod content. Its
setup window can invoke Python's package manager only after a user accepts the
shown dependency list. Package provenance and license details remain available
from the configured Python package index and each dependency's upstream
project. The source ZIP keeps those packages in a dedicated per-user virtual
environment instead of changing the global Python package set.

SceneLight is an independent, unofficial project. It is not affiliated with
Ren'Py, Team Salvato, or Dan Salvato.

No *Doki Doki Literature Club!* image, audio, script, font, archive, or derived
runtime texture is included in this repository or its release archives. The
installer reads the user's local project and generates non-portable derived
maps locally. Users and mod authors remain responsible for the rights to all
content in their projects.

DDLC projects must separately follow Team Salvato's current IP Guidelines:
<https://teamsalvato.com/ip-guidelines>
