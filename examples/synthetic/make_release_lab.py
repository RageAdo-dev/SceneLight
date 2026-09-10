"""Generate an original animated regression mod; never bundles commercial assets.

Run against a NEW directory. Copy its game/scenelight_lab files into a disposable
DDLC copy to use the same lab with stock Sayori, or run standalone with a SDK.
Raw GIF is animated in SceneLight Preview, not in Ren'Py; the native ATL uses
frames decoded from that exact GIF.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageSequence

SCRIPT = """define config.screen_width = 1280
define config.screen_height = 720
define config.name = "SceneLight Animation Lab"

init 999 python:
    import os as _lab_os
    import json as _lab_json
    config.save_directory = "SceneLight-Release-Lab-Private"
    config.label_overrides["start"] = "sl_lab_start"
    _lab_output = _lab_os.environ.get("SCENELIGHT_LAB_OUTPUT")
    if _lab_output:
        config.savedir = _lab_os.path.join(_lab_output, "saves")
        # Automated native runs may be hidden while collecting engine captures.
        # Ren'Py pauses its movie/audio decoder when minimized by default.
        preferences.audio_when_minimized = True
        preferences.audio_when_unfocused = True
    renpy.display._sl_lab_records = []
    def _lab_capture(name):
        if not _lab_output:
            return
        renderer = getattr(renpy.display, "_scenelight_live_renderer", None)
        renpy.display._sl_lab_records.append({"name": name, "renderer": renderer is not None,
            "disabled": renderer.disabled if renderer else None,
            "evaluations": renderer.evaluations if renderer else 0,
            "prepared_frames": getattr(renderer, "prepared_frames", 0),
            "lighting_enabled": getattr(persistent, "scenelight_enabled", None),
            "runtime_error": getattr(renpy.display, "_scenelight_live_error", None),
            "savedir": config.savedir,
            "prepared_opened": list(renderer.prepared.opened) if renderer and renderer.prepared else [],
            "prepared_failed": list(renderer.prepared.failed) if renderer and renderer.prepared else [],
            "decoded_movies": dict(renderer.prepared.decoded) if renderer and renderer.prepared else {},
            "renpy": renpy.version_string,
            "can_load": renpy.can_load("lab-regression")})
        with open(_lab_os.path.join(_lab_output, name + ".png"), "wb") as stream:
            stream.write(renpy.screenshot_to_bytes((1280, 720)))
        with open(_lab_os.path.join(_lab_output, "runtime.json"), "w") as stream:
            _lab_json.dump(renpy.display._sl_lab_records, stream, indent=2, default=str)

screen sl_lab_advance():
    timer 0.4 action Return()

label start:
    jump sl_lab_start

image bg lab_warm = "scenelight_lab/warm.png"
image bg lab_cool = "scenelight_lab/cool.png"
image bg lab_movie = Movie(play="scenelight_lab/lights.webm", size=(1280, 720))
image bg lab_gif_frames:
    "scenelight_lab/gif_0.png"
    0.20
    "scenelight_lab/gif_1.png"
    0.40
    "scenelight_lab/gif_2.png"
    0.60
    "scenelight_lab/gif_3.png"
    0.80
    repeat
image nova idle = "scenelight_lab/nova.png"
image nova happy = "scenelight_lab/nova_happy.png"
define nova = Character("Nova", image="nova")
transform lab_left:
    xalign 0.24
    yalign 1.0
transform lab_right:
    xalign 0.78
    yalign 1.0
    zoom 0.85
transform lab_sayori:
    xalign 0.24
    yalign 1.0
    zoom 0.65
transform lab_move:
    yalign 1.0
    xalign 0.1
    linear 1.2 xalign 0.85
    linear 1.2 xalign 0.1
    repeat

label sl_lab_start:
    window hide
    if "scenelight_set_enabled" in globals():
        $ scenelight_set_enabled(True)
    scene bg lab_warm
    show nova idle at lab_left
    $ renpy.pause(0.8, hard=True)
    if "scenelight" in globals():
        $ scenelight.off()
    $ renpy.pause(0.4, hard=True)
    $ _lab_capture("01-disabled")
    if "scenelight" in globals():
        $ scenelight.clear_scene()
    $ renpy.pause(0.8, hard=True)
    $ _lab_capture("02-enabled")
    show nova happy at lab_right
    if renpy.has_image("sayori 1a"):
        show sayori 1a at lab_sayori
    else:
        show nova idle as second at lab_left
    $ renpy.pause(0.6, hard=True)
    $ _lab_capture("03-two-characters")
    scene bg lab_cool
    show nova idle at lab_left
    with Dissolve(0.5)
    $ renpy.pause(0.6, hard=True)
    $ _lab_capture("04-cool-dissolve")
    scene bg lab_gif_frames
    show nova idle at lab_left
    $ renpy.pause(0.08, hard=True)
    $ _lab_capture("05-gif-atl-a")
    $ renpy.pause(0.70, hard=True)
    $ _lab_capture("06-gif-atl-b")
    scene bg lab_movie
    show nova happy at lab_move
    with Fade(0.2, 0.0, 0.2)
    $ renpy.pause(0.8, hard=True)
    $ _lab_capture("07-movie-a")
    $ renpy.pause(0.7, hard=True)
    $ _lab_capture("08-movie-b")
    scene bg lab_warm
    show nova idle at lab_left
    $ renpy.pause(0.5, hard=True)
    if _lab_output:
        show screen sl_lab_advance
        "Animation lab save checkpoint."
        hide screen sl_lab_advance
        $ renpy.save("lab-regression")
        $ renpy.pause(0.2, hard=True)
        if not _lab_os.path.exists(_lab_os.path.join(_lab_output, "load-requested")):
            python:
                with open(_lab_os.path.join(_lab_output, "load-requested"), "w") as stream:
                    stream.write("Load only this lab's isolated save slot.")
                renpy.load("lab-regression")
        show screen sl_lab_advance
        "Animation lab resumed after load."
        hide screen sl_lab_advance
        $ renpy.pause(0.4, hard=True)
        $ _lab_capture("09-after-load")
        $ renpy.quit(relaunch=False, status=0)
    nova "This lab exercises lighting, animation, movement, transitions and character replacement."
    nova "Open scenelight_lab/lights.gif in SceneLight Preview for the actual GIF. Ren'Py uses its decoded ATL frames."
    menu:
        "Run again":
            jump sl_lab_start
        "Quit":
            $ renpy.quit()
"""


def create(project: Path, *, ddlc: bool = False) -> None:
    if project.exists():
        raise FileExistsError(f"Use a new directory, not an existing game: {project}")
    assets = project / "game" / "scenelight_lab"
    assets.mkdir(parents=True)
    frames = []
    yy, xx = np.mgrid[:720, :1280]
    for index in range(4):
        warm = np.exp(-((xx - (150 + index * 300)) ** 2 + (yy - 220) ** 2) / 110000)
        cool = np.exp(-((xx - (1100 - index * 240)) ** 2 + (yy - 380) ** 2) / 140000)
        pixels = np.stack([18 + warm * 210, 22 + warm * 90 + cool * 50, 32 + cool * 215], -1)
        frame = Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))
        ImageDraw.Draw(frame).rectangle((0, 660, 1279, 719), fill=(25, 26, 28))
        frames.append(frame)
    frames[0].save(assets / "warm.png")
    frames[3].save(assets / "cool.png")
    frames[0].save(
        assets / "lights.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[200, 400, 600, 800],
        loop=0,
    )
    with Image.open(assets / "lights.gif") as gif:
        for index, frame in enumerate(ImageSequence.Iterator(gif)):
            frame.convert("RGB").save(assets / f"gif_{index}.png")
    for happy in (False, True):
        sprite = Image.new("RGBA", (300, 600))
        draw = ImageDraw.Draw(sprite)
        draw.ellipse((70, 15, 230, 190), fill=(230, 195, 169), outline=(40, 35, 45), width=5)
        draw.polygon([(60, 195), (240, 195), (275, 599), (25, 599)], fill=(192, 193, 201))
        draw.rectangle((120, 195, 180, 430), fill=(235, 225, 212))
        draw.ellipse((110, 90, 122, 108), fill=(40, 65, 95))
        draw.ellipse((178, 90, 190, 108), fill=(40, 65, 95))
        draw.arc((128, 122, 174, 153), 0, 180 if happy else 50, fill=(110, 40, 40), width=4)
        sprite.save(assets / ("nova_happy.png" if happy else "nova.png"))
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        "1280x720",
        "-pix_fmt",
        "rgb24",
        "-r",
        "12",
        "-i",
        "-",
        "-an",
        "-vcodec",
        "libvpx-vp9",
        "-lossless",
        "1",
        "-deadline",
        "realtime",
        "-cpu-used",
        "8",
        "-pix_fmt",
        "yuv420p",
        str(assets / "lights.webm"),
    ]
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        for index in range(48):
            first, second = frames[index // 12], frames[(index // 12 + 1) % 4]
            process.stdin.write(Image.blend(first, second, (index % 12) / 12).tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("ffmpeg could not create the lab movie")
    script = SCRIPT
    if ddlc:
        script = script.replace("label start:\n    jump sl_lab_start\n\n", "")
    else:
        script = script.replace(
            '    if renpy.has_image("sayori 1a"):\n        show sayori 1a at lab_sayori\n    else:\n        show nova idle as second at lab_left',
            "    show nova idle as second at lab_left",
        )
    (project / "game" / "scenelight_lab.rpy").write_text(script, encoding="utf-8")
    (project / "scenelight.json").write_text(
        json.dumps(
            {
                "character_selection": "manual",
                "character_tags": ["nova", "sayori"] if ddlc else ["nova"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--ddlc",
        action="store_true",
        help="Include the optional stock Sayori test in a private DDLC copy",
    )
    args = parser.parse_args()
    create(args.project.resolve(), ddlc=args.ddlc)
