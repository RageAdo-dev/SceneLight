import ast
import sys
import textwrap
from types import ModuleType, SimpleNamespace

import pytest

from scenelight.preview.shader_source import (
    _extract,
    fragment_source,
    runtime_source_path,
    vertex_source,
)
from scenelight.runtime import shader_renpy, shader_stages


def test_vertex_samples_use_original_helpers_and_leave_spatial_samples_in_fragment():
    functions, original = _extract("fragment_functions"), _extract("fragment_350")
    declarations, helpers, vertex, fragment = shader_stages.build(functions, original)
    assert declarations.count("varying ") == 24
    assert vertex.count("scenelight_transport_at(") == 26
    assert "scenelight_transport_at(" not in fragment
    assert "scenelight_scene_at(tex1, v_sc_center)" not in fragment
    assert "scenelight_ray_shadow(" in fragment
    assert "scenelight_wrap_at(v_sc_screen)" in fragment
    for name in ("field_uv", "atlas_uv", "scene_at", "wrap_at", "transport_at"):
        assert "scenelight_" + name in helpers
    assert original == _extract("fragment_350")
    # The final transport RGB crosses a packed-vector boundary; no channel may
    # be lost or replaced by the two padding values.
    assert "vec3(v_sc_pack_18.w, v_sc_pack_19.x, v_sc_pack_19.y)" in fragment
    assert "sc_vertex_transport_25.b, 0.0, 0.0)" in vertex


def test_shader_layout_changes_fail_closed():
    with pytest.raises(ValueError, match="layout changed"):
        shader_stages.build(
            _extract("fragment_functions"),
            _extract("fragment_350").replace(
                "scenelight_transport_at(0.0, v_sc_center)", "vec4(0.0)"
            ),
        )
    with pytest.raises(ValueError, match="Missing production helper"):
        shader_stages.build("", _extract("fragment_350"))


def test_vertex_samplers_do_not_change_renpy7_texture_unit_numbering():
    vertex = vertex_source(center_samples=True)
    fragment = fragment_source(center_samples=True)
    # Ren'Py 7 scans each stage separately, and duplicate sampler declarations
    # consume another unit. GLSL expands the vertex-only macro after that scan.
    for index in (1, 2, 6, 7):
        assert "SC_VERTEX_SAMPLER tex%d;" % index in vertex
        assert "uniform sampler2D tex%d;" % index not in vertex
        assert "uniform sampler2D tex%d;" % index in fragment
    assert "#define SC_VERTEX_SAMPLER uniform sampler2D" in vertex
    assert "v_sc_pack_19" in vertex and "v_sc_pack_19" in fragment
    _, helpers, body, _ = shader_stages.build(
        _extract("fragment_functions"), _extract("fragment_350")
    )
    preamble, _ = shader_stages.vertex_preamble(_extract("variables"), helpers, body)
    assert (preamble + "attribute vec2 a_tex_coord;").splitlines()[
        -1
    ] == "attribute vec2 a_tex_coord;"


@pytest.mark.parametrize(
    "components,samplers,expected",
    [(112, 4, True), (124, 4, True), (111, 4, False), (112, 3, False)],
)
def test_limits(components, samplers, expected):
    assert shader_stages.supported(components, samplers) is expected


class Driver:
    def __init__(self, failure=None):
        self.failure = failure
        self.shaders, self.deleted_shaders, self.deleted_programs = [], [], []

    def CreateShader(self, kind):
        self.shaders.append(kind)
        return len(self.shaders)

    def ShaderSource(self, *args):
        if self.failure == "exception":
            raise RuntimeError("driver failure")

    def CompileShader(self, *args):
        pass

    def GetShaderiv(self, shader, key, value):
        value._obj.value = self.failure != ("vertex" if shader == 1 else "fragment")

    def CreateProgram(self):
        return 3

    def AttachShader(self, *args):
        pass

    def LinkProgram(self, *args):
        pass

    def GetProgramiv(self, program, key, value):
        value._obj.value = self.failure != "link"

    def DeleteShader(self, shader):
        self.deleted_shaders.append(shader)

    def DeleteProgram(self, program):
        self.deleted_programs.append(program)


@pytest.mark.parametrize("failure", [None, "vertex", "fragment", "link", "exception"])
def test_optional_link_check_releases_every_object_including_failures(failure):
    gl = Driver(failure)
    if failure == "exception":
        with pytest.raises(RuntimeError, match="driver failure"):
            shader_renpy.validate_program(gl, "vertex", "fragment")
    else:
        assert shader_renpy.validate_program(gl, "vertex", "fragment") is (failure is None)
    assert gl.deleted_shaders == list(range(1, len(gl.shaders) + 1))
    assert gl.deleted_programs == ([3] if failure in (None, "link") else [])


@pytest.mark.parametrize("capable,links", [(True, True), (True, False), (False, False)])
def test_policy_isolated_to_scenelight_cached_and_rechecked_for_new_context(
    monkeypatch, capable, links
):
    calls, checks, logs, assembled = [], [], [], []

    class Cache:
        def __init__(self):
            self.cache, self.gles = {}, False

        def get(self, names):
            if names not in self.cache:
                calls.append(names)
                self.cache[names] = object()
            return self.cache[names]

    module = SimpleNamespace(ShaderCache=Cache)
    gpu = SimpleNamespace(Driver=lambda: SimpleNamespace(integer=lambda key: 128 if capable else 0))
    monkeypatch.setattr(
        shader_renpy,
        "assembled_sources",
        lambda *args: assembled.append(args) or ("vertex", "fragment"),
    )
    monkeypatch.setattr(
        shader_renpy, "validate_program", lambda *args: checks.append(args) or links
    )
    config = SimpleNamespace(default_shader="base")
    shader_renpy.install(module, gpu, shader_stages, config, logs.append)
    wrapper = Cache.get
    shader_renpy.install(module, gpu, shader_stages, config, logs.append)
    assert Cache.get is wrapper
    # Games can change the default shader after SceneLight's early init block.
    config.default_shader = "game.late_default"
    cache = Cache()
    names = ("renpy.texture", shader_stages.OPTIMIZED, "game.custom")
    first = cache.get(names)
    assert cache.get(names) is first
    assert len(checks) == int(capable)
    assert [args[2] for args in assembled] == (["game.late_default"] if capable else [])
    assert sum("this renderer/shader combination" in entry for entry in logs) == 1
    selected = shader_stages.OPTIMIZED if capable and links else shader_stages.ORIGINAL
    assert calls == [("renpy.texture", selected, "game.custom")]
    cache.get(("game.unrelated",))
    assert len(checks) == int(capable)
    assert Cache().get(names) is not first
    assert len(checks) == 2 * int(capable)


def test_preflight_uses_engine_assembler_and_respects_removed_parts():
    used = []
    part = SimpleNamespace(
        vertex_variables={"v"},
        vertex_parts=[(150, "body")],
        vertex_functions="helpers",
        fragment_variables={"f"},
        fragment_parts=[(350, "pixels")],
        fragment_functions="lighting",
    )
    module = SimpleNamespace(
        shader_part={"base": part}, source=lambda *args: used.append(args) or str(len(used))
    )
    assert shader_renpy.assembled_sources(module, ("unknown", "-unknown"), "base", False) == (
        "1",
        "2",
    )
    assert used == [
        ({"v"}, [(150, "body")], ["helpers"], False, False),
        ({"f"}, [(350, "pixels")], ["lighting"], True, False),
    ]


@pytest.mark.parametrize("excluded", [shader_stages.ORIGINAL, shader_stages.OPTIMIZED])
def test_game_can_exclude_lighting_before_any_optional_gl_check(excluded):
    calls = []

    class Cache:
        cache = {}

        def get(self, names):
            calls.append(names)
            return "unlit"

    shader_renpy.install(SimpleNamespace(ShaderCache=Cache), None, shader_stages, None, None)
    names = ("renpy.texture", shader_stages.OPTIMIZED, "-" + excluded)
    assert Cache().get(names) == "unlit"
    assert calls == [("renpy.texture", "-" + excluded)]


def test_gles_keeps_original_shader_without_loading_desktop_apis():
    calls = []

    class Cache:
        cache, gles = {}, True

        def get(self, names):
            calls.append(names)
            return "gles-program"

    shader_renpy.install(
        SimpleNamespace(ShaderCache=Cache), None, shader_stages, None, lambda *args: None
    )
    assert Cache().get((shader_stages.OPTIMIZED,)) == "gles-program"
    assert calls == [(shader_stages.ORIGINAL,)]


def test_game_shader_filter_receives_original_part_and_is_only_called_by_engine():
    calls = []
    config = SimpleNamespace(shader_part_filter=lambda names: calls.append(names) or names)

    class Cache:
        cache = {}

        def get(self, names):
            return config.shader_part_filter(names)

    shader_renpy.install(SimpleNamespace(ShaderCache=Cache), None, shader_stages, config, None)
    assert Cache().get((shader_stages.OPTIMIZED, "game.custom")) == (
        shader_stages.ORIGINAL,
        "game.custom",
    )
    assert calls == [(shader_stages.ORIGINAL, "game.custom")]


def test_bootstrap_uses_real_config_module_when_legacy_store_proxy_rejects_unknown_options(
    monkeypatch,
):
    class ConfigProxy:
        def __getattr__(self, name):
            raise RuntimeError("config.%s is not a known configuration variable" % name)

    api, gl2, cache = (
        ModuleType("renpy"),
        ModuleType("renpy.gl2"),
        ModuleType("renpy.gl2.gl2shadercache"),
    )
    api.gl2, gl2.gl2shadercache = gl2, cache
    api.config = ModuleType("renpy.config")
    api.config.default_shader = "renpy.geometry"
    logs, installed = [], []
    api.display = SimpleNamespace(log=SimpleNamespace(write=logs.append))
    api.loadable = lambda path: True
    api.register_shader = lambda *args, **kwargs: None
    for module in (api, gl2, cache):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    def install(cache_module, gpu, stages, config, log):
        # This is the optional query that raised a non-AttributeError in 7.7.1.
        assert getattr(config, "shader_part_filter", None) is None
        installed.append(config)

    modules = {
        "shader_stages": shader_stages,
        "shader_renpy": SimpleNamespace(install=install),
        "live_gpu": None,
    }
    namespace = {
        "renpy": api,
        "config": ConfigProxy(),
        "_SCENELIGHT_SHADER_AVAILABLE": True,
        "_SCENELIGHT_FRAGMENT_FUNCTION_ALIASES": (),
        "_scenelight_fragment_source": lambda source: source,
        "_scenelight_runtime_module": modules.__getitem__,
    }
    for name in ("variables", "vertex_150", "fragment_functions", "fragment_350"):
        namespace["_scenelight_shader_" + name] = _extract(name)
    source = runtime_source_path().read_text(encoding="utf-8")
    start = source.index('    _scenelight_sprite_shader = "scenelight.dynamic_sprite"')
    end = source.index("    class SceneLightSprite", start)
    node = ast.parse(textwrap.dedent(source[start:end]))
    exec(compile(node, str(runtime_source_path()), "exec"), namespace)
    assert not logs
    assert installed == [api.config]
    assert namespace["_scenelight_sprite_shader"] == shader_stages.OPTIMIZED
