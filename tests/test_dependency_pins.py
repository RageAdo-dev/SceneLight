import re
from pathlib import Path

from scenelight.setup_gui import BASE_REQUIREMENTS, CUDA_REQUIREMENT, PREVIEW_DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]


def test_installer_and_package_dependencies_agree():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = re.search(r"^dependencies = \[(.*?)\]", metadata, re.M | re.S)
    assert dependencies is not None
    package_pins = set(re.findall(r'"([^"]+)"', dependencies.group(1)))
    preview_pins = set((ROOT / "requirements-preview.txt").read_text().splitlines())
    base_pins = set((ROOT / "requirements.txt").read_text().splitlines())

    assert package_pins == preview_pins == set(PREVIEW_DEPENDENCIES.values())
    assert base_pins == set(BASE_REQUIREMENTS)
    assert base_pins <= package_pins
    cuda = re.search(r"^cuda = \[(.*?)\]", metadata, re.M | re.S)
    assert cuda is not None
    assert re.findall(r'"([^"]+)"', cuda.group(1)) == [CUDA_REQUIREMENT]
