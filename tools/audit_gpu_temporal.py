"""Compare GPU field interpolation with the existing CPU interpolation reference."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scenelight.calibration import lighting_mode_preset  # noqa: E402
from scenelight.preview.artifacts import FormArtifacts, SceneArtifacts  # noqa: E402
from scenelight.preview.gpu_view import SceneLightGPUView  # noqa: E402
from scenelight.preview.media import environment_wrap  # noqa: E402
from scenelight.preview.temporal import (  # noqa: E402
    TemporalSceneFrame,
    interpolated_scene,
    scene_blend,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("background", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.runtime / "manifest.json").read_text())
    forms = json.loads((args.runtime / "sprite_form_manifest.json").read_text())
    atlas = {
        name: Image.open(args.runtime / Path(path).name)
        for name, path in (
            ("irradiance", manifest["atlas"]["irradiance"]),
            ("emitter", manifest["atlas"]["emitter"]),
            ("wrap", manifest["atlas"]["wrap"]),
            ("transport", manifest["transport_atlas"]["texture"]),
        )
    }

    def frame(name):
        data = manifest["scenes"][name]
        x, y = data["tile"]
        arrays = {}
        folder = args.output / name.replace(":", "_")
        folder.mkdir(exist_ok=True)
        for kind, image in atlas.items():
            width, height = (416, 9) if kind == "transport" else (160, 90)
            tile = image.crop((x * width, y * height, (x + 1) * width, (y + 1) * height))
            tile.save(folder / (kind + ".png"))
            arrays[kind] = np.asarray(tile.convert("RGBA"), dtype=np.uint8)
        return TemporalSceneFrame(
            arrays["irradiance"], arrays["emitter"], arrays["transport"], data
        ), folder

    form = forms["sprites"]["monika 1a"]
    form_folder = args.output / "form"
    form_folder.mkdir(exist_ok=True)
    for name in ("normal_noise", "height_ao_edge", "response"):
        shutil.copy2(args.runtime.parent / form[name], form_folder / (name + ".png"))

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
        raise RuntimeError("Could not create the validation OpenGL context")

    class OffscreenView(SceneLightGPUView):
        def makeCurrent(self):
            if not context.makeCurrent(surface):
                raise RuntimeError("Validation context was lost")

        def doneCurrent(self):
            context.doneCurrent()

    view = OffscreenView()
    view.initializeGL()
    view.set_sprite(args.sprite, FormArtifacts(form_folder, form, True, 0))
    background = np.asarray(Image.open(args.background).convert("RGBA"))
    physical = next(
        k
        for k, v in manifest["scenes"].items()
        if v["light_transport_layout"] == "physical-components-v1"
    )
    colored = next(
        k
        for k, v in manifest["scenes"].items()
        if v["light_transport_layout"] == "physical-rgb-families-v1"
    )
    pairs = [
        ("br_yellow_movie", "br_yellow_movie::v000003"),
        ("br_red", "br_pool"),
        (physical, colored),
    ]
    results = []
    for pair_index, (left_name, right_name) in enumerate(pairs):
        left, folder = frame(left_name)
        right, _ = frame(right_name)
        anchors = {0: left, 100: right}
        view.set_scene(args.background, SceneArtifacts(folder, left.metadata, True, 0))
        view.set_background_frame(background, environment_wrap(background))
        view.set_live_background(True)
        for mode in ("physical", "cinematic", "separate"):
            strength, calibration = lighting_mode_preset(mode)
            view.set_strength(strength)
            view.set_calibration(calibration)
            for phase in (0, 1, 25, 49, 50, 51, 75, 99, 100):
                view.set_live_scene_frame(interpolated_scene(anchors, phase))
                expected = view.render_rgba()
                view.set_live_scene_blend(scene_blend(anchors, phase))
                actual = view.render_rgba()
                error = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
                results.append(
                    {
                        "pair": pair_index,
                        "mode": mode,
                        "phase": phase,
                        "mean_channel_error": float(error.mean()),
                        "max_channel_error": int(error.max()),
                        "pixels_over_3": int(np.count_nonzero(error.max(axis=-1) > 3)),
                    }
                )
                if phase == 50:
                    Image.fromarray(expected).save(args.output / f"{pair_index}-{mode}-cpu.png")
                    Image.fromarray(actual).save(args.output / f"{pair_index}-{mode}-gpu.png")
    payload = {
        "cases": len(results),
        "worst_mean_channel_error": max(row["mean_channel_error"] for row in results),
        "worst_channel_error": max(row["max_channel_error"] for row in results),
        "results": results,
    }
    (args.output / "comparison.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items() if k != "results"}))
    view.close()
    app.processEvents()


if __name__ == "__main__":
    main()
