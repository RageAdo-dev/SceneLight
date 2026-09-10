import json
import shutil
from pathlib import Path

from scenelight.effects import compile_effect_packs
from scenelight.source_types import is_effect_source

ROOT = Path(__file__).resolve().parents[1]


def test_included_effect_pack_templates_compile_into_isolated_shader_parts(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "game" / "scenelight_effects"
    pack_root.mkdir(parents=True)
    for source in (ROOT / "examples" / "effect-packs").glob("*.json"):
        shutil.copy2(source, pack_root / source.name)

    build = compile_effect_packs(tmp_path / "game")

    assert build.warnings == ()
    assert build.effect_count == 16
    effects = build.manifest["effects"]
    assert isinstance(effects, dict)
    spectral = effects["horror_signals.spectral_presence"]
    assert spectral["shader"] == "scenelight.fx.horror_signals.spectral_presence"
    assert spectral["fragment_priority"] == 600
    assert spectral["animated"] is True
    assert "u__intensity" in spectral["variables"]
    assert spectral["parameters"]["intensity"]["uniform"] == (
        "u_scenelight_fx_horror_signals_spectral_presence_intensity"
    )
    lightning = effects["divine_power.lightning_god"]
    assert lightning["preset"] == "lightning_god"
    assert "slfx_divine_power_lightning_god_fbm21" in lightning["fragment_functions"]
    assert lightning["parameters"]["intensity"]["default"] == 0.0
    fire = effects["divine_power.inferno_incarnate"]
    assert "lightning_path" not in fire["fragment_functions"]
    eyes = effects["nightmare_transfigurations.eyes_everywhere"]
    assert "u__eye_center" in eyes["fragment"]
    assert "texture2D(tex0" in eyes["fragment"]


def test_trusted_vfx_preset_contract_cannot_be_replaced(tmp_path: Path) -> None:
    pack_root = tmp_path / "game" / "scenelight_effects"
    pack_root.mkdir(parents=True)
    payload = {
        "format": "scenelight-effect-pack",
        "version": 1,
        "id": "spoof",
        "effects": [
            {
                "id": "fake_lightning",
                "preset": "lightning_god",
                "fragment": "gl_FragColor = vec4(1.0);",
            }
        ],
    }
    (pack_root / "spoof.json").write_text(json.dumps(payload), encoding="utf-8")

    build = compile_effect_packs(tmp_path / "game")

    assert build.effect_count == 0
    assert "cannot replace" in build.warnings[0]


def test_unsafe_effect_pack_is_skipped_and_reported(tmp_path: Path) -> None:
    pack_root = tmp_path / "game" / "scenelight_effects"
    pack_root.mkdir(parents=True)
    (pack_root / "unsafe.json").write_text(
        json.dumps(
            {
                "format": "scenelight-effect-pack",
                "version": 1,
                "id": "unsafe",
                "effects": [
                    {
                        "id": "hang",
                        "parameters": {
                            "intensity": {
                                "type": "float",
                                "default": 0.0,
                                "min": 0.0,
                                "max": 1.0,
                            }
                        },
                        "fragment": "while (true) { gl_FragColor.rgb *= u__intensity; }",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    build = compile_effect_packs(tmp_path / "game")

    assert build.effect_count == 0
    assert len(build.warnings) == 1
    assert "loops" in build.warnings[0]


def test_effect_pack_cannot_reference_lighting_transport_or_unknown_uniforms(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "game" / "scenelight_effects"
    pack_root.mkdir(parents=True)
    base = {
        "format": "scenelight-effect-pack",
        "version": 1,
        "id": "bad_reference",
        "effects": [
            {
                "id": "bad",
                "parameters": {
                    "intensity": {
                        "type": "float",
                        "default": 0.0,
                        "min": 0.0,
                        "max": 1.0,
                    }
                },
                "fragment": "gl_FragColor.rgb *= u_sc_strength + u__missing;",
            }
        ],
    }
    (pack_root / "bad.json").write_text(json.dumps(base), encoding="utf-8")

    build = compile_effect_packs(tmp_path / "game")

    assert build.effect_count == 0
    assert "SceneLight internals" in build.warnings[0]


def test_source_texture_sampling_requires_opt_in_and_only_allows_tex0(tmp_path: Path) -> None:
    pack_root = tmp_path / "game" / "scenelight_effects"
    pack_root.mkdir(parents=True)

    def payload(fragment: str, *, enabled: object = False) -> dict[str, object]:
        return {
            "format": "scenelight-effect-pack",
            "version": 1,
            "id": "spatial",
            "effects": [
                {
                    "id": "fold",
                    "source_texture": enabled,
                    "parameters": {
                        "intensity": {
                            "type": "float",
                            "default": 0.0,
                            "min": 0.0,
                            "max": 1.0,
                        }
                    },
                    "fragment": fragment,
                }
            ],
        }

    path = pack_root / "spatial.json"
    path.write_text(
        json.dumps(payload("gl_FragColor = texture2D(tex0, v_tex_coord);")),
        encoding="utf-8",
    )
    assert "must declare source_texture" in compile_effect_packs(tmp_path / "game").warnings[0]

    path.write_text(
        json.dumps(
            payload(
                "gl_FragColor = texture2D(tex1, v_tex_coord);",
                enabled=True,
            )
        ),
        encoding="utf-8",
    )
    assert "SceneLight internals" in compile_effect_packs(tmp_path / "game").warnings[0]

    path.write_text(
        json.dumps(
            payload(
                "gl_FragColor = texture2D(tex0, clamp(v_tex_coord, 0.0, 1.0));",
                enabled=True,
            )
        ),
        encoding="utf-8",
    )
    build = compile_effect_packs(tmp_path / "game")
    assert build.warnings == ()
    assert build.manifest["effects"]["spatial.fold"]["source_texture"] is True


def test_effect_pack_path_is_tracked_without_treating_every_json_as_visual() -> None:
    assert is_effect_source(Path("game/scenelight_effects/horror.json"))
    assert not is_effect_source(Path("game/data/dialogue.json"))


def test_runtime_composes_custom_effects_after_the_lighting_shader() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    lighting = 'result.add_shader("scenelight.dynamic_sprite")'
    custom = "return _scenelight_custom_effect_render("

    render_start = runtime.index("        def render(self, width, height, st, at):")
    lighting_index = runtime.index(lighting, render_start)
    assert lighting_index < runtime.index(custom, lighting_index)
    assert "SCENELIGHT_EFFECT_PACK_MANIFEST_PATH" in runtime
    assert "def _scenelight_custom_effect_render(source_render, active_effects):" in runtime
    assert "result.blit(current, (0, 0))" in runtime
    assert "renpy.register_shader(" in runtime
    assert 'result.add_shader("scenelight.fx.alpha_guard")' in runtime
    assert "fragment_900=" in runtime
    assert 'result.add_uniform("u_sc_strength", strength if enabled else 0.0)' in runtime


def test_custom_effects_do_not_require_a_recognized_lighting_scene() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )

    assert "if not scene:" in runtime
    assert "return _scenelight_custom_effect_render(" in runtime
    assert "_scenelight_apply_custom_effects(result, active_effects)" in runtime
