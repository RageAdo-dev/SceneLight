"""Render the README examples from Ren'Py's redistributable tutorial artwork.

Requires the Preview dependencies, an OpenGL 3.3 context and a Ren'Py SDK.
All lighting is produced by SceneLight; map panels unpack the real form textures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneLightGPUView
from scenelight.preview.hardware import detect_hardware_profile
from scenelight.preview.shader_source import production_shader_sha256

PAPER = (244, 246, 249)
INK = (26, 35, 47)
ANIMATION_FPS = 60
ANIMATION_SECONDS = 4


def font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def lighting_stage():
    """An original two-light test scene; no third-party background is needed."""
    y, x = np.mgrid[:720, :1280].astype(np.float32)
    image = np.zeros((720, 1280, 3), np.float32) + (12, 20, 31)
    for cx, cy, color in ((185, 310, (180, 76, 20)), (1095, 290, (15, 98, 184))):
        glow = np.exp(-(((x - cx) / 340) ** 2) - ((y - cy) / 480) ** 2)
        image += glow[..., None] * color
    floor = y > 587
    image[floor] *= 0.68
    result = Image.fromarray(np.uint8(np.clip(image, 0, 255)), "RGB")
    draw = ImageDraw.Draw(result)
    draw.line((0, 587, 1280, 587), fill=(45, 54, 67), width=2)
    for x0, color in ((157, (255, 190, 106)), (1094, (105, 205, 255))):
        draw.rounded_rectangle((x0 - 12, 72, x0 + 41, 560), radius=12, fill=(12, 17, 24))
        draw.rounded_rectangle((x0, 86, x0 + 29, 544), radius=8, fill=color)
    return result


def comparison(before, after):
    result = Image.new("RGB", (1440, 708), PAPER)
    draw = ImageDraw.Draw(result)
    for index, (title, pixels) in enumerate(
        (("Without SceneLight", before), ("With SceneLight", after))
    ):
        left = 24 + 708 * index
        draw.text((left, 22), title, fill=INK, font=font(25))
        # Both views use the same crop and scale, after the real renderer runs.
        crop = (
            Image.fromarray(pixels)
            .crop((240, 0, 1040, 720))
            .resize((684, 616), Image.Resampling.LANCZOS)
        )
        result.paste(crop.convert("RGB"), (left, 68))
    return result


def map_figure(source, artifacts):
    packed_normal = np.asarray(Image.open(artifacts.image("normal_noise")).convert("RGB"))
    packed_height = np.asarray(Image.open(artifacts.image("height_ao_edge")).convert("RGB"))
    nx = packed_normal[..., 0].astype(np.float32) / 255 * 2 - 1
    ny = packed_normal[..., 1].astype(np.float32) / 255 * 2 - 1
    nz = np.sqrt(np.maximum(1 - nx * nx - ny * ny, 0.0001))
    normal = np.stack((nx, ny, nz), axis=2)
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    normals = np.rint((normal * 0.5 + 0.5) * 255).astype(np.uint8)
    height = Image.fromarray(packed_height[..., 0], "L").convert("RGB")
    ao = Image.fromarray(255 - packed_height[..., 1], "L").convert("RGB")
    # Only the display mask is resized. Map values retain their stored range.
    alpha = source.getchannel("A").resize(height.size, Image.Resampling.LANCZOS)
    maps = [
        source,
        height.convert("RGBA"),
        Image.fromarray(normals).convert("RGBA"),
        ao.convert("RGBA"),
    ]
    for item in maps[1:]:
        item.putalpha(alpha)
    result = Image.new("RGB", (1440, 722), PAPER)
    draw = ImageDraw.Draw(result)
    titles = ("Sprite", "Height map", "Normal map", "Ambient occlusion")
    for index, (title, item) in enumerate(zip(titles, maps, strict=True)):
        left = 20 + index * 355
        draw.text((left, 23), title, fill=INK, font=font(23))
        draw.rounded_rectangle((left, 70, left + 335, 701), radius=8, fill=(225, 230, 237))
        item = item.copy()
        item.thumbnail((309, 599), Image.Resampling.LANCZOS)
        result.paste(item, (left + (335 - item.width) // 2, 86 + (599 - item.height) // 2), item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path)
    parser.add_argument("work", type=Path, help="Scratch directory outside the repository")
    parser.add_argument("--output", type=Path, default=Path("docs/media"))
    args = parser.parse_args()
    sprite = args.sdk / "tutorial/game/images/eileen happy.png"
    if not sprite.is_file() or not (args.sdk / "LICENSE.txt").is_file():
        parser.error("Expected a Ren'Py SDK with the Eileen tutorial artwork and LICENSE.txt")
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    background = args.work / "lighting-stage.png"
    lighting_stage().save(background)

    app = QApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("Could not create the documentation renderer")

    class View(SceneLightGPUView):
        def makeCurrent(self):
            if not context.makeCurrent(surface):
                raise RuntimeError("Lost the documentation OpenGL context")

        def doneCurrent(self):
            context.doneCurrent()

        def context(self):
            return context

        def defaultFramebufferObject(self):
            return 0

        def update(self, *args):
            pass

    cache = ArtifactCache(args.work / "cache", hardware_profile=detect_hardware_profile(cuda=False))
    view = View()
    try:
        view.initializeGL()
        form = cache.form(sprite)
        view.set_sprite(sprite, form)
        view.set_scene(background, cache.scene(background))
        view.set_calibration(Calibration())
        view.set_placement(0.5, 1.01, 0.97)
        view.set_compare_mode(1)
        before = view.render_rgba()
        view.set_compare_mode(0)
        after = view.render_rgba()
        comparison(before, after).save(args.output / "lighting-comparison.png", optimize=True)
        with Image.open(sprite) as opened:
            map_figure(opened.convert("RGBA"), form).save(
                args.output / "surface-maps.png", optimize=True
            )

        frames = []
        frame_count = ANIMATION_FPS * ANIMATION_SECONDS
        for index in range(frame_count):
            horizontal = 0.5 - 0.27 * math.cos(2 * math.pi * index / frame_count)
            view.set_placement(horizontal, 1.01, 0.97)
            frame = Image.fromarray(view.render_rgba((768, 432))).convert("RGB")
            frames.append(frame)
        durations = [
            round((i + 1) * 1000 / ANIMATION_FPS) - round(i * 1000 / ANIMATION_FPS)
            for i in range(frame_count)
        ]
        frames[0].save(
            args.output / "moving-light.webp",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            lossless=True,
            method=6,
        )
        with Image.open(args.output / "moving-light.webp") as encoded:
            if encoded.n_frames != len(frames):
                raise RuntimeError("The animation lost frames during export")
            for index, expected in enumerate(frames):
                encoded.seek(index)
                if not np.array_equal(np.asarray(encoded.convert("RGB")), np.asarray(expected)):
                    raise RuntimeError(f"Animation frame {index} changed colors during export")
                if encoded.info.get("duration") != durations[index]:
                    raise RuntimeError(f"Animation frame {index} changed timing during export")
        metadata = {
            "source": "Ren'Py tutorial/game/images/eileen happy.png",
            "source_sha256": hashlib.sha256(sprite.read_bytes()).hexdigest(),
            "shader_sha256": production_shader_sha256(),
            "form": form.metadata,
            "comparison_changed_pixels": int(np.any(before != after, axis=2).sum()),
            "animation_frames": len(frames),
            "animation_fps": ANIMATION_FPS,
            "animation_duration_ms": sum(durations),
            "normal_display": "X/Y from stored channels; Z reconstructed from unit length",
            "height_display": "Stored height channel, without contrast stretching",
            "occlusion_display": "Inverted stored amount: white is open, dark is occluded",
            "animation_encoding": "Animated WebP, lossless RGB",
        }
        (args.output / "examples.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "images": ["lighting-comparison.png", "surface-maps.png", "moving-light.webp"],
                    "changed_pixels": metadata["comparison_changed_pixels"],
                }
            )
        )
    finally:
        view.makeCurrent()
        view.close()
        cache.shutdown()
        app.processEvents()


if __name__ == "__main__":
    main()
