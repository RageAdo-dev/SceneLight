from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy"


def runtime_source() -> str:
    return RUNTIME.read_text(encoding="utf-8")


def test_temporal_scene_fields_advance_and_redraw_without_affecting_static_scenes() -> None:
    runtime = runtime_source()

    assert 'SCENELIGHT_SCENE_SEQUENCES = SCENELIGHT_MANIFEST.get("scene_sequences", {})' in runtime
    assert 'sequence.get("mode") == "visible-source"' in runtime
    assert "position = _scenelight_movie_position(current.channel)" in runtime
    assert "elapsed_ms %= duration_ms" not in runtime
    assert "SCENELIGHT_STABLE_SCENE_KEY in SCENELIGHT_SCENE_SEQUENCES" in runtime
    assert "renpy.redraw(self, 0.125)" not in runtime


def test_author_api_is_save_and_rollback_aware() -> None:
    runtime = runtime_source()

    assert "default scenelight_control_state = {" in runtime
    assert "renpy.store.scenelight_control_state = state" in runtime
    assert "class _SceneLightAPI(object):" in runtime
    assert "scenelight = _SceneLightAPI()" in runtime
    assert "def configure(self, **settings):" in runtime
    assert "def scene(self, **settings):" in runtime
    assert "def background(self, name, **settings):" in runtime
    assert "def character(self, tag, **settings):" in runtime
    assert "def image(self, name, **settings):" in runtime
    assert "def clear_scene(self):" in runtime


def test_author_api_uses_documented_precedence() -> None:
    runtime = runtime_source()
    layers = runtime.index("layers = (")
    defaults = runtime.index('state.get("defaults", {})', layers)
    background = runtime.index('state.get("backgrounds", {}).get(background_key, {})')
    scene = runtime.index("scene_layer,", background)
    character = runtime.index('state.get("characters", {}).get(character_key, {})')
    image = runtime.index('state.get("images", {}).get(image_key, {})')

    assert defaults < background < scene < character < image


def test_cinematic_mode_is_a_deliberate_overridable_preset() -> None:
    runtime = runtime_source()

    assert '"cinematic": _scenelight_light_mode_values(' in runtime
    assert "strength=0.72" in runtime
    assert "SCENELIGHT_PROFILE_STRENGTH" in runtime
    assert "exposure_bias=-0.22" in runtime
    assert "color_adaptation=0.92" in runtime
    assert "individual_light_colors=1.0" in runtime
    preset = runtime.index("normalized.update(mode_values)")
    explicit_values = runtime.index("for raw_name, raw_value in settings.items():", preset)
    assignment = runtime.index("normalized[name] = value", explicit_values)
    assert preset < explicit_values < assignment
    assert 'values["strength"] = 1.0' in runtime


def test_authored_strength_overrides_instead_of_compounding_saved_profile() -> None:
    runtime = runtime_source()

    assert 'result["strength_override"] = True' in runtime
    assert 'if controls.get("strength_override")' in runtime
    assert "else SCENELIGHT_PROFILE_STRENGTH" in runtime


def test_scene_off_is_a_hard_bypass_over_named_rules() -> None:
    runtime = runtime_source()

    assert 'scene_layer = state.get("scene", {})' in runtime
    assert 'scene_layer.get("enabled") is False' in runtime
    assert 'result["enabled"] = False' in runtime


def test_author_controls_reach_the_live_shader_and_freeze_with_transitions() -> None:
    runtime = runtime_source()

    assert "controls = _scenelight_control_snapshot(" in runtime
    assert 'controls["enabled"]' in runtime
    assert 'controls["strength"]' in runtime
    assert '_scenelight_calibration_blocks(scene, controls.get("calibration", {}))' in runtime
    assert "rv._sc_frozen_controls = copy.deepcopy(frozen_controls)" in runtime


def test_author_api_documents_whole_mod_scene_and_named_controls() -> None:
    guide = (ROOT / "docs" / "MOD_AUTHOR_API.md").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "renpy" / "scenelight_author_example.rpy").read_text(
        encoding="utf-8"
    )

    for call in (
        "scenelight.configure",
        "scenelight.scene",
        "scenelight.off",
        "scenelight.clear_scene",
        "scenelight.background",
        "scenelight.character",
    ):
        assert call in guide
        assert call in example


def test_author_api_uses_the_canonical_packaged_runtime() -> None:
    assert RUNTIME.is_file()
    assert not (ROOT / "runtime" / "scenelight_runtime.rpy").exists()
