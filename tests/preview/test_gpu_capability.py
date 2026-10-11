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


@pytest.mark.parametrize("capable,link_fails", [(True, False), (True, True), (False, False)])
def test_sprite_shader_falls_back_without_losing_the_preview(monkeypatch, capable, link_fails):
    calls = []
    monkeypatch.setattr(gpu_view.GL, "glGetIntegerv", lambda key: 128 if capable else 0)

    def link(vertex, fragment):
        optimized = "v_sc_pack_19" in vertex
        calls.append(optimized)
        assert ("v_sc_pack_19" in fragment) is optimized
        if optimized and link_fails:
            raise RuntimeError("driver rejects varying layout")
        return 19

    monkeypatch.setattr(gpu_view, "_link_program", link)
    assert gpu_view._sprite_program() == 19
    assert calls == ([True, False] if link_fails else [capable])


def test_failed_fragment_compile_releases_the_completed_vertex_shader(monkeypatch):
    deleted = []

    def compile_shader(kind, source):
        if kind == gpu_view.GL.GL_FRAGMENT_SHADER:
            raise RuntimeError("fragment rejected")
        return 7

    monkeypatch.setattr(gpu_view, "_compile_shader", compile_shader)
    monkeypatch.setattr(gpu_view.GL, "glDeleteShader", deleted.append)
    with pytest.raises(RuntimeError, match="fragment rejected"):
        gpu_view._link_program("vertex", "fragment")
    assert deleted == [7]
