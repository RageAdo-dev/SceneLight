"""Build Windows icon sizes from the approved SceneLight artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "src" / "scenelight" / "assets"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(ASSET_DIR / "scenelight.png") as source:
        source.convert("RGBA").save(
            ASSET_DIR / "scenelight.ico",
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


if __name__ == "__main__":
    main()
