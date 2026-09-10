"""Create an original, asset-free Ren'Py demo used for compatibility tests."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SCRIPT = """define config.screen_width = 1280
define config.screen_height = 720
define n = Character("Nova", image="nova")
image bg light_lab = "images/light_lab.png"

# This is intentionally a real LayeredImage rather than a flat PNG image.
# It exercises the same target-Ren'Py raw-form resolver used by mods with
# composited/custom characters, without depending on any DDLC assets.
layeredimage nova:
    always "images/nova_base.png"
    group mood:
        attribute idle default:
            "images/nova_idle_face.png"

transform nova_walk:
    yalign 1.0
    xalign 0.15
    linear 2.0 xalign 0.85
    linear 2.0 xalign 0.15
    repeat

label start:
    scene bg light_lab
    show nova idle at nova_walk
    n "SceneLight is following my final screen position."
    pause
    return
"""


def create(project: Path) -> None:
    images = project / "game" / "images"
    images.mkdir(parents=True, exist_ok=True)
    background = Image.new("RGB", (1280, 720), (10, 22, 42))
    glow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-180, 40, 380, 600), fill=(255, 102, 35, 190))
    draw.ellipse((860, -120, 1420, 500), fill=(30, 130, 255, 210))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    background = Image.alpha_composite(background.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(background)
    draw.rectangle((0, 570, 1280, 720), fill=(15, 25, 34))
    background.save(images / "light_lab.png")

    sprite = Image.new("RGBA", (360, 640), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    draw.ellipse((100, 25, 260, 190), fill=(238, 188, 162, 255), outline=(45, 28, 38, 255), width=8)
    draw.polygon(((90, 195), (270, 195), (325, 610), (35, 610)), fill=(205, 62, 112, 255))
    draw.rectangle((125, 185, 235, 455), fill=(238, 230, 215, 255))
    sprite.save(images / "nova_base.png")

    face = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(face)
    draw.ellipse((135, 90, 155, 115), fill=(35, 80, 150, 255))
    draw.ellipse((205, 90, 225, 115), fill=(35, 80, 150, 255))
    draw.arc((158, 118, 202, 150), 8, 172, fill=(105, 38, 55, 255), width=4)
    face.save(images / "nova_idle_face.png")
    (project / "game" / "script.rpy").write_text(SCRIPT, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    create(parser.parse_args().project.resolve())
