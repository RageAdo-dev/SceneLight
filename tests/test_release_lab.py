import runpy
import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest
from PIL import Image, ImageSequence


@pytest.mark.parametrize("ddlc", [False, True])
def test_generated_lab_has_native_video_and_correct_game_entry(tmp_path, ddlc):
    generator = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "examples/synthetic/make_release_lab.py")
    )
    project = tmp_path / "Animation Lab"
    generator["create"](project, ddlc=ddlc)
    script = (project / "game/scenelight_lab.rpy").read_text()
    assert ("label start:" in script) is not ddlc
    assert ('renpy.has_image("sayori 1a")' in script) is ddlc
    assert "lights.webm" in script and "lights.mp4" not in script
    assets = project / "game/scenelight_lab"
    with Image.open(assets / "lights.gif") as gif:
        assert [frame.info["duration"] for frame in ImageSequence.Iterator(gif)] == [
            200,
            400,
            600,
            800,
        ]
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(assets / "lights.webm")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # H.264 decodes in Preview's FFmpeg but not desktop Ren'Py.
    assert "Video: vp9" in probe.stderr
