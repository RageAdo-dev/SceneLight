"""Build a transparent title-bar icon for the unbranded setup window."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "src" / "scenelight" / "assets"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    blank = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    blank.save(
        ASSET_DIR / "blank.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
