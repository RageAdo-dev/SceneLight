from __future__ import annotations

import pytest

from scenelight.preview import gpu_view


class _UnavailableFunction:
    def __bool__(self) -> bool:
        return False


def test_shader_capability_check_explains_legacy_vm_renderer(monkeypatch) -> None:
    monkeypatch.setattr(gpu_view.GL, "glCreateShader", _UnavailableFunction())

    with pytest.raises(RuntimeError, match="legacy OpenGL") as caught:
        gpu_view._require_shader_api()

    assert "glCreateShader" not in str(caught.value)
    assert "full virtual machine with working 3D acceleration" in str(caught.value)


def test_shader_capability_check_accepts_complete_api(monkeypatch) -> None:
    for name in gpu_view.REQUIRED_SHADER_FUNCTIONS:
        monkeypatch.setattr(gpu_view.GL, name, lambda: None)

    gpu_view._require_shader_api()
