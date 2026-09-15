from __future__ import annotations

from scenelight.preview.core import runtime_source_path
from scenelight.preview.shader_source import fragment_source, production_shader_sha256


def test_gpu_wrapper_uses_production_runtime_source() -> None:
    source = fragment_source()
    runtime = runtime_source_path().read_text(encoding="utf-8")
    assert len(production_shader_sha256()) == 64
    assert "vec4 source = texture(tex0, v_tex_coord, u_lod_bias);" in source
    assert "vec4 source = fragColor;" not in source
    assert "scenelight_ray_shadow" in source
    assert "scenelight_accumulate_probe" in source
    assert "u_sc_probe7_data" in source
    assert "u_sc_transport_grid" in source
    assert "environment wrap" in source
    assert "sc_chroma_guard" in source
    assert "sc_chroma_preservation" in source
    assert "sc_scene_chroma_span" in source
    assert "sc_extreme_scene_chroma" in source
    assert "u_sc_authored_grade" in source
    assert "sc_environment_adaptation" in source
    assert "mix(1.0, 0.25, sc_extreme_scene_chroma)" in source
    assert "u_sc_live_background" in source
    assert "u_sc_compare_mode" in source
    assert "mix(output_srgb, base_srgb, original_view)" in source
    assert "fragment_350" in runtime


def test_bright_scene_guard_has_no_character_or_scene_identity_rules() -> None:
    source = fragment_source().lower()
    guard_region = source[source.index("float sc_broad_radius") : source.index("float base_luma")]
    for forbidden in (
        "sayori",
        "natsuki",
        "yuri",
        "monika",
        "skin",
        "collegefront",
        "background_name",
        "image_name",
    ):
        assert forbidden not in guard_region


def test_extreme_chroma_guard_leaves_normal_scene_transport_untouched() -> None:
    source = fragment_source().lower()
    guard_region = source[
        source.index("float sc_scene_chroma_span") : source.index("float sc_preserved_luma")
    ]
    guard_code = "\n".join(line.split("//", 1)[0] for line in guard_region.splitlines())
    assert "ambient_chroma" in guard_region
    assert "smoothstep(\n                0.55,\n                1.15" in guard_region
    assert "sc_extreme_chroma_preservation" not in guard_region
    assert "mix(1.0, 0.25, sc_extreme_scene_chroma)" in guard_region
    for forbidden in (
        "sayori",
        "natsuki",
        "yuri",
        "monika",
        "dusk",
        "night",
        "background_name",
        "image_name",
    ):
        assert forbidden not in guard_code


def test_authored_matrix_grade_suppresses_only_duplicate_environment_adaptation() -> None:
    source = fragment_source().lower()
    assert "float sc_authored_grade = clamp(u_sc_authored_grade" in source
    assert "float sc_environment_adaptation = 1.0 - sc_authored_grade" in source
    assert "auto_amount * sc_environment_adaptation" in source
    assert "vec3(u_sc_calibration0.w * auto_amount * sc_environment_adaptation)" in source
    assert "probe_tint = mix(vec3(1.0), probe_tint, sc_environment_adaptation)" in source
    assert "ground_chroma = mix(vec3(1.0), ground_chroma, sc_environment_adaptation)" in source
    assert "form_light = mix(1.0, clamp(form_light" in source
    assert "occlusion *= 0.36 + 0.64 * material_response" in source


def test_generated_specular_requires_source_detail_receiver_confidence() -> None:
    source = fragment_source().lower()
    detail_region = source[
        source.index("float form_detail_left") : source.index("vec3 source_color_field")
    ]
    detail_code = "\n".join(line.split("//", 1)[0] for line in detail_region.splitlines())
    assert "float form_detail_span" in detail_region
    assert "smoothstep(0.018, 0.110, form_detail_span)" in detail_region
    assert "step(0.5, u_sc_has_form)" in detail_region
    assert "float form_light = diffuse_fill + lambert * diffuse_span" in source
    assert "* form_detail_visibility * u_sc_strength" in source
    assert "lighting_lambert" not in source
    assert "(form_light - 1.0) * form_detail_visibility" not in source
    for forbidden in ("sayori", "natsuki", "yuri", "monika", "skin", "face"):
        assert forbidden not in detail_code


def test_adaptive_separation_uses_real_source_positions_and_conservative_evidence() -> None:
    source = fragment_source().lower()
    assert "float scenelight_separation_pair_evidence" in source
    assert "float sc_adaptive_light_colors = u_sc_calibration4.z" in source
    assert "float scenelight_primary_creative_evidence" in source
    assert "length(primary_color.rgb - creative_color.rgb)" in source
    assert "distance(primary_data.xy, creative_data.xy)" in source
    assert "float sc_creative_source_count" in source
    assert "float sc_multiple_creative_sources" in source
    assert "max(u_sc_calibration4.y, sc_adaptive_light_colors)" in source
    assert "distance(data_a.xy, data_b.xy)" in source
    assert "length(color_a.rgb - color_b.rgb)" in source
    assert "vec2 sc_creative_direction2 = normalize(light2.xy)" in source
    assert "vec2 sc_creative_direction3 = normalize(light3.xy)" in source
    assert "-0.5 * light2.x" not in source


def test_gpu_wrapper_keeps_all_eight_texture_inputs() -> None:
    source = fragment_source()
    for index in range(8):
        assert f"sampler2D tex{index}" in source


def test_color_separation_retains_forward_normal_component():
    source = fragment_source()
    surface = source.split("vec2 sc_creative_surface =", 1)[1].split(";", 1)[0]
    assert "normalize(vec3(" in surface
    assert "normal.z" in surface
    assert ")).xy" in surface
