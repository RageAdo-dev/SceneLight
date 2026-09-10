"""Source-tree launcher used by release ZIPs; no package install required."""

import sys
from importlib import import_module
from multiprocessing import freeze_support
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

main = import_module("scenelight.cli").main


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
