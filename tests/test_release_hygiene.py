from pathlib import Path

from scenelight.capture import CAPTURE_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_save_compatibility_asset_is_in_python_packages() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    asset = ROOT / "src" / "scenelight" / "assets" / "scenelight-save-compat.rpy"

    assert asset.is_file()
    assert '"assets/scenelight-save-compat.rpy"' in pyproject


def test_release_uses_one_launcher_for_players_and_mod_authors() -> None:
    launcher = (ROOT / "SceneLight.bat").read_text(encoding="utf-8")
    shell_launcher = (ROOT / "scenelight.sh").read_text(encoding="utf-8")
    setup = (ROOT / "src" / "scenelight" / "setup_gui.py").read_text(encoding="utf-8")
    build_script = (ROOT / "tools" / "build_release_zip.ps1").read_text(encoding="utf-8")

    assert "scenelight_setup.pyw" in launcher
    assert "_scenelight" in launcher
    assert "%*" not in launcher
    assert 'launcher="$script_dir/_scenelight/scenelight_sdk.py"' in shell_launcher
    assert 'exec python3 "$launcher" "$@"' in shell_launcher
    assert not (ROOT / "install-scenelight.sh").exists()
    assert "For mod developers" in setup
    assert "Remove developer API" in setup
    assert "Embed in development copy" not in setup
    assert "Remove embedded files" not in setup
    assert "_toggle_developer_mode" in setup
    assert '"SceneLight.bat", "scenelight.sh", "README.md", "LICENSE"' in build_script
    assert '$payloadRoot = Join-Path $packageRoot "_scenelight"' in build_script
    assert 'Join-Path $payloadRoot "effect-packs"' not in build_script
    assert '"CONTRIBUTING.md"' in build_script
    assert '"scenelight.sh"' in build_script
    assert 'Get-ChildItem -LiteralPath $packageRoot -Filter "*.bat"' in build_script
    assert '$batchText -replace "`r?`n", "`r`n"' in build_script
    for obsolete in (
        "Install SceneLight.bat",
        "SceneLight Setup.bat",
        "SceneLight Preview.bat",
        "SceneLight for Mod Developers.bat",
    ):
        assert not (ROOT / obsolete).exists()


def test_fresh_machine_bootstrap_uses_clear_consumer_language() -> None:
    bootstrap = (ROOT / "tools" / "bootstrap_python.ps1").read_text(encoding="utf-8")
    compatibility = (ROOT / "src" / "scenelight" / "compatibility.py").read_text(encoding="utf-8")
    launcher = (ROOT / "SceneLight.bat").read_text(encoding="utf-8")

    assert "Downloading Python 3.11.9 runtime..." in bootstrap
    assert "Installing SceneLight runtime under" in bootstrap
    assert "Repairing SceneLight runtime..." in bootstrap
    assert '"/repair"' in bootstrap
    assert "PythonCore\\3.11\\InstallPath" in bootstrap
    assert "[StringComparison]::OrdinalIgnoreCase" in bootstrap
    assert '-InstallerPath "%SCENELIGHT_INSTALLER%"' in launcher
    assert "official Python 3.11.9 runtime" not in bootstrap
    assert "private SceneLight runtime" not in bootstrap
    assert "Downloading official Ren'Py" not in compatibility
    assert "private compatibility runtime" not in compatibility
    assert "verified private runtime" not in launcher


def test_public_docs_use_current_launcher_dependencies_and_runtime() -> None:
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/AUTHOR_QUICKSTART.md",
            "docs/MOD_AUTHOR_API.md",
        )
    )
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    for obsolete in (
        "Install SceneLight.bat",
        "SceneLight Setup.bat",
        "SceneLight Preview.bat",
        "SceneLight for Mod Developers.bat",
    ):
        assert obsolete not in docs
    assert "makevisualnovels.itch.io/make-visual-novels-rspv1" in docs
    from scenelight.compatibility import RENPY_VERSION

    assert f"Ren'Py {RENPY_VERSION}" in notices
    assert "Ren'Py 7.5.3" not in notices
    assert "scikit-image" not in notices


def test_runtime_has_no_character_specific_defaults() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "SCENELIGHT_CHARACTER_TAGS = set()" in runtime
    for name in ("sayori", "natsuki", "yuri", "monika", "demonika"):
        assert f'"{name}"' not in runtime.lower()


def test_runtime_has_one_canonical_source_copy() -> None:
    packaged = ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy"
    assert packaged.is_file()
    assert not (ROOT / "runtime" / "scenelight_runtime.rpy").exists()


def test_shader_registration_fits_legacy_renpy_logical_line_limit() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    registration_start = runtime.index(
        '        renpy.register_shader(\n            "scenelight.dynamic_sprite"'
    )
    registration_end = runtime.index("\n    class SceneLightSprite", registration_start)
    registration = runtime[registration_start:registration_end]

    # Ren'Py 6.99 rejects a Python statement whose complete logical line is
    # about 64 KiB. Shader sources must be assigned before this small call.
    assert len(registration.encode("utf-8")) < 4096
    for source_name in (
        "_scenelight_shader_variables",
        "_scenelight_shader_vertex_150",
        "_scenelight_shader_fragment_functions",
        "_scenelight_shader_fragment_350",
    ):
        assert f"{source_name} =" in runtime[:registration_start]
        assert f"={source_name}" in registration


def test_runtime_isolates_and_composes_third_party_mesh_shaders() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )

    # Image-declared shaders finish in child_render and become tex0. SceneLight
    # deliberately creates a new model without importing foreign shader state.
    boundary = runtime.index("            result = renpy.Render(*child_render.get_size())")
    shader_add = runtime.index('            result.add_shader("renpy.texture")', boundary)
    assert "result.blit(child_render, (0, 0))" in runtime[boundary:shader_add]
    assert "child_render.shaders" not in runtime
    assert "child_render.uniforms" not in runtime
    assert "child_render.properties" not in runtime

    # If Ren'Py deliberately combines shader parts on one model, SceneLight
    # consumes the lower-priority result instead of discarding and resampling it.
    fragment = runtime.index("    _scenelight_shader_fragment_350 =")
    registration = runtime.index("        renpy.register_shader(", fragment)
    assert "vec4 source = gl_FragColor;" in runtime[fragment:registration]
    assert "fragment_350=_scenelight_shader_fragment_350" in runtime[registration:]


def test_native_renpy_6_skips_unavailable_shader_features() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert (
        '_SCENELIGHT_SHADER_AVAILABLE = callable(getattr(renpy, "register_shader", None))'
        in runtime
    )
    assert (
        "if _SCENELIGHT_SHADER_AVAILABLE:\n        _scenelight_with_callback._scenelight_callback"
        in runtime
    )
    assert "if _SCENELIGHT_SHADER_AVAILABLE:\n        renpy.register_shader(" in runtime
    assert "if not enabled and not effects_active:" in runtime
    assert 'result.add_uniform("u_sc_strength", strength if enabled else 0.0)' in runtime
    assert "if not _SCENELIGHT_SHADER_AVAILABLE:\n            return" in runtime
    assert (
        "if _SCENELIGHT_SHADER_AVAILABLE and _SCENELIGHT_PLAYER_EFFECT_UI_ENABLED:\n"
        '        config.keymap.setdefault("scenelight_effects", [])' in runtime
    )


def test_runtime_routes_expression_sprites_at_scene_boundary() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "def _scenelight_install_scene_router():" in runtime
    assert 'for module_name in ("scenelists", "core")' in runtime
    assert 'layer == "master"' in runtime
    assert "tag in SCENELIGHT_CHARACTER_TAGS" in runtime
    assert "SceneLightSprite(child, image_name)" in runtime
    assert "child._change_transform_child(" in runtime
    assert "authored_grade_strength=authored_grade_strength" in runtime
    assert 'getattr(transform_state, "matrixcolor", None) is not None' in runtime
    assert 'result.add_uniform("u_sc_authored_grade", self.authored_grade_strength)' in runtime
    assert "def _scenelight_authored_grade_strength(displayable):" in runtime
    assert "authored_grade_strength=_scenelight_authored_grade_strength(child)" in runtime
    assert "_scenelight_install_scene_router()" in runtime


def test_runtime_wrapper_preserves_renpy_transform_lifecycle() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    sprite_start = runtime.index("    class SceneLightSprite")
    sprite_end = runtime.index("\n    class SceneLightImageLike", sprite_start)
    sprite = runtime[sprite_start:sprite_end]

    assert "def set_transform_event(self, event):" in sprite
    assert "self.child.set_transform_event(event)" in sprite
    assert "def _handles_event(self, event):" in sprite
    assert "def _hide(self, st, at, kind):" in sprite
    assert "new_child = self.child._hide(st, at, kind)" in sprite
    assert "def _show(self):" in sprite
    assert "def _change_transform_child(self, child):" in sprite


def test_runtime_does_not_double_wrap_registered_character_images() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    route_start = runtime.index("    def _scenelight_route_scene_add")
    route_end = runtime.index("\n    def _scenelight_install_scene_router", route_start)
    route = runtime[route_start:route_end]

    assert "registered = _scenelight_get_registered_image(image_name)" in route
    assert "not isinstance(registered, (SceneLightSprite, SceneLightImageLike))" in route


def test_runtime_retains_stable_scene_during_character_show_hide_mutations() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    lookup_start = runtime.index("    def _scenelight_live_scene_entry")
    lookup_end = runtime.index("\n    def _scenelight_live_scene", lookup_start + 10)
    lookup = runtime[lookup_start:lookup_end]

    assert "SCENELIGHT_STABLE_SCENE_KEY = key" in lookup
    assert "if not explicit_background and SCENELIGHT_STABLE_SCENE is not None:" in lookup
    assert "return SCENELIGHT_STABLE_SCENE_KEY, SCENELIGHT_STABLE_SCENE" in lookup
    assert "SCENELIGHT_STABLE_SCENE = None" in lookup


def test_runtime_has_renpy_7_texture_compatibility_fallback() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert 'getattr(renpy.display.im, "unoptimized_texture", None)' in runtime
    assert 'getattr(renpy.display.im, "render_for_texture", None)' in runtime


def test_runtime_has_early_renpy_asset_loader_and_fragment_function_fallbacks() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert 'getattr(renpy, "open_file", None)' in runtime
    assert "opener = renpy.loader.load" in runtime
    assert "stream.close()" in runtime
    assert "renpy.display.im.Image(path, optimize_bounds=False)" in runtime
    assert "return renpy.render(displayable, width, height, st, at)" in runtime
    assert "_SCENELIGHT_FRAGMENT_FUNCTION_PREAMBLE" in runtime
    fragment_helper = runtime[runtime.index("    def _scenelight_fragment_source") :]
    assert (
        "if renpy.version_tuple[0] >= 8:"
        not in fragment_helper.split("    SCENELIGHT_MANIFEST =", 1)[0]
    )
    for helper_dependency in (
        "u_sc_atlas_texel",
        "u_sc_scene_uv",
        "u_sc_transport_grid",
        "u_sc_transport_uv",
        "tex1",
        "tex2",
        "tex7",
    ):
        assert f'("{helper_dependency}", "sc7_' in runtime


def test_hybrid_runtime_resolves_image_like_definitions_before_wrapping() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "class SceneLightImageLike(object):" in runtime
    assert "child = self.original._duplicate(args)" in runtime
    assert "return getattr(self.original, name)" in runtime
    assert "if isinstance(original, renpy.Displayable):" in runtime
    assert "wrapped = SceneLightImageLike(original, image_tuple)" in runtime


def test_capture_helper_resolves_layeredimage_attributes_without_final_prebake() -> None:
    helper = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy").read_text(
        encoding="utf-8"
    )
    capture = (ROOT / "src" / "scenelight" / "capture.py").read_text(encoding="utf-8")
    assert "for prefix_length in range(len(parts), 0, -1):" in helper
    assert "DisplayableArguments()" in helper
    assert "_scenelight_require_resolved_capture(duplicate(args), name)" in helper
    assert "ShownImageInfo()" in helper
    assert "shown.apply_attributes" in helper
    assert f'"version": {CAPTURE_VERSION}' in helper
    assert 'getattr(renpy, "render_to_file", None)' in helper
    assert 'renpy.loader.load(source_name, directory="images")' in helper
    assert 'source_name.lower().endswith(".png")' in helper
    assert "surface = screenshot(rendered)" in helper
    assert "surface = screenshot(rendered, False)" in helper
    assert "renpy.display.render.free_memory()" in helper
    assert '"background capture failed for all %d registered scenes"' in helper
    assert 'current_filename.endswith("/00gltest.rpy")' in helper
    assert "time.time() - _scenelight_inventory_wait_started[0] < 5.0" in helper
    assert "renpy.timeout(0.10)" in helper
    assert "config.start_interact_callbacks.append(_scenelight_capture_assets)" in helper
    assert "Final relit sprites are\nnever baked" in capture


def test_runtime_image_discovery_supports_legacy_renpy_699() -> None:
    helper = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy").read_text(
        encoding="utf-8"
    )
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )

    for source in (helper, runtime):
        assert 'getattr(renpy, "list_images", None)' in source
        assert 'getattr(image_module, "images", {}).keys()' in source
        assert 'getattr(renpy, "get_registered_image", None)' in source
        assert 'getattr(image_module, "images", {}).get(tuple(name))' in source
        assert "renpy.list_images()" not in source
        assert "renpy.get_registered_image(" not in source


def test_capture_progress_checkpoint_retries_transient_windows_reader_handles() -> None:
    helper = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy").read_text(
        encoding="utf-8"
    )

    assert 'getattr(error, "winerror", None) not in (5, 32)' in helper
    assert "for attempt in range(80):" in helper
    assert "time.sleep(0.01)" in helper


def test_production_runtime_contains_the_full_hybrid_transport_pipeline() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    # Four lights occupy transport planes 3..14; eight probes occupy 15..25.
    assert "transport_light3_position = scenelight_transport_at(12.0" in runtime
    assert "transport_probe7 = scenelight_transport_at(22.0" in runtime
    assert "transport_probe_scalar2 = scenelight_transport_at(25.0" in runtime
    assert "scenelight_ray_shadow" in runtime
    assert "float occlusion = clamp(" in runtime
    assert "vec3 ground_chroma" in runtime
    assert "vec3 specular_field" in runtime
    assert "float rim =" in runtime
    assert 'result.add_uniform("u_sc_compare_mode", 0.0)' in runtime


def test_optional_effects_are_modular_post_relight_gpu_branches() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    shoulder = runtime.index("float peak_excess = max(peak - 0.82")
    optional = runtime.index("if (u_sc_rain_data.x > 0.0001")
    output = runtime.index("gl_FragColor = vec4(output_srgb * output_alpha, output_alpha)")
    assert shoulder < optional < output
    assert "scenelight_fx_rain_streak" in runtime
    assert "sc_glitch_offset" in runtime
    assert "default scenelight_fx_state =" in runtime
    assert "class _SceneLightEffectsAPI(object):" in runtime
    assert "effect_time = float(renpy.get_game_runtime())" in runtime
    assert "rv._sc_frozen_effects = copy.deepcopy(frozen_effects)" in runtime


def test_disabled_effect_defaults_are_exact_shader_identities() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert runtime.count('"intensity": 0.0') >= 2
    assert "if (u_sc_rain_data.x > 0.0001" in runtime
    assert "if (sc_glitch_intensity > 0.0001" in runtime
    assert "uniform sampler2D tex8;" not in runtime


def test_individual_light_color_mode_is_default_off_and_uses_all_sources() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert '"individual_light_colors": 0.0' in runtime
    assert '"adaptive_light_colors": 1.0' in runtime
    assert "max(u_sc_calibration4.y, sc_adaptive_light_colors) * u_sc_strength" in runtime
    assert "if (sc_individual_light_colors > 0.0001)" in runtime
    assert "scenelight_creative_light_weight" in runtime
    assert "scenelight_separation_pair_evidence" in runtime
    assert "sc_creative_source_count" in runtime
    assert "sc_multiple_creative_sources" in runtime
    assert "sc_separated_source_chroma" in runtime
    assert "sc_creative_surface" in runtime


def test_failed_eye_glow_experiment_is_absent_from_the_public_runtime() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    for token in (
        "eye_glow",
        "eye_detection",
        "eye_overrides",
        "u_sc_eye",
        "scenelight_fx_eye",
        "def eyes(",
        "def clear_eyes(",
        "Automatic eye glow",
    ):
        assert token not in runtime
    effects = (ROOT / "src" / "scenelight" / "effects.py").read_text(encoding="utf-8")
    assert "eye_glow" not in effects
    assert "eye_detection" not in effects
    assert not (ROOT / "tools" / "validate_eye_detection.py").exists()


def test_player_effect_panel_is_dormant_in_the_1_0_release() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "screen scenelight_effect_controls():\n    modal True" in runtime
    assert "use scenelight_effect_controls_panel" in runtime
    assert 'key "scenelight_effects" action Hide("scenelight_effect_controls")' in runtime
    assert "_SCENELIGHT_PLAYER_EFFECT_UI_ENABLED = False" in runtime
    assert "if _SCENELIGHT_SHADER_AVAILABLE and _SCENELIGHT_PLAYER_EFFECT_UI_ENABLED:" in runtime
    assert 'config.keymap.setdefault("scenelight_effects", [])' in runtime
    assert '"shift_K_F8"' in runtime
    assert 'ToggleScreen("scenelight_effect_controls")' in runtime


def test_production_runtime_uses_final_transform_for_live_spatial_updates() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "uniform mat4 u_transform;" in runtime
    assert "vec2 sc_live_center = vec2(" in runtime
    assert "v_sc_center = mix(" in runtime
    assert "scenelight_transport_at(0.0, v_sc_center)" in runtime
    assert "renpy.redraw(self, 0.0)" in runtime


def test_runtime_resolves_hide_snapshot_before_a_new_sprite_has_rendered() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    sprite_start = runtime.index("    class SceneLightSprite")
    sprite_end = runtime.index("\n    class SceneLightImageLike", sprite_start)
    sprite = runtime[sprite_start:sprite_end]

    assert "def _live_lighting_state(self):" in sprite
    assert "if self._sc_last_rendered_scene is None:" in sprite
    assert ") = self._live_lighting_state()" in sprite
    assert "rv._sc_frozen_scene = frozen_scene" in sprite
    assert "rv._sc_frozen_effects = copy.deepcopy(frozen_effects)" in sprite
    assert "before hide/replaced/cancel" in sprite
    assert "new_child = self.child._hide(st, at, kind)" in sprite
    assert "rv.child = new_child" in sprite


def test_production_runtime_stabilizes_background_and_character_transitions() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert "_scenelight_existing_with_callback = config.with_callback" in runtime
    assert "def _scenelight_contains_lit_sprite(displayable):" in runtime
    assert "def _scenelight_flatten_lit_side(displayable):" in runtime
    assert "class _SceneLightFrozenSide(renpy.Displayable):" in runtime
    assert "texture = renderer.snapshot(rendered) if renderer is not None else None" in runtime
    assert "rv.blit(self.texture, (0, 0))" in runtime
    assert "def _scenelight_screen_rect(self):" in runtime
    assert "rv._sc_frozen_screen_rect = self._scenelight_screen_rect()" in runtime
    assert 'result.add_uniform(\n                "u_sc_snapshot_rect"' in runtime
    assert '"u_sc_use_snapshot_rect"' in runtime
    assert "sc_snapshot_screen = u_sc_snapshot_rect.xy" in runtime
    assert "sc_snapshot_center = u_sc_snapshot_rect.xy" in runtime
    assert "sprite._sc_transition_screen_rect = None" in runtime
    assert 'getattr(getattr(renpy.display, "layout", None), "Flatten", None)' in runtime
    transition_start = runtime.index("    def _scenelight_with_callback")
    transition_end = runtime.index("\n    if _SCENELIGHT_SHADER_AVAILABLE:", transition_start)
    transition_callback = runtime[transition_start:transition_end]
    assert "screenshot_to_bytes" not in transition_callback
    assert "renpy.display.im.Data" not in transition_callback
    assert "old_side = _scenelight_flatten_lit_side(old_widget)" in runtime
    assert "_SceneLightLiveTransitionSide(new_widget)" in transition_callback
    assert "_scenelight_flatten_lit_side(new_widget)" not in transition_callback
    assert "config.with_callback = _scenelight_with_callback" in runtime


def test_transition_callback_does_not_chain_to_itself_after_reload() -> None:
    runtime = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_runtime.rpy").read_text(
        encoding="utf-8"
    )
    assert 'getattr(_scenelight_existing_with_callback, "_scenelight_callback", False)' in runtime
    assert 'getattr(_scenelight_existing_with_callback, "__name__", "")' in runtime
    assert '== "_scenelight_with_callback"' in runtime
    assert '"_scenelight_previous"' in runtime
    assert "_scenelight_with_callback._scenelight_callback = True" in runtime
    assert (
        "_scenelight_with_callback._scenelight_previous = _SCENELIGHT_PREVIOUS_WITH_CALLBACK"
    ) in runtime


def test_public_tree_contains_no_game_archives_or_generated_atlases() -> None:
    forbidden_names = {
        "manifest.json",
        "sprite_form_manifest.json",
        "irradiance_atlas.png",
        "emitter_atlas.png",
        "transport_atlas.png",
        "wrap_atlas.png",
    }
    offenders = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and (path.suffix.lower() == ".rpa" or path.name in forbidden_names)
    ]
    assert offenders == []


def test_setup_window_delegates_without_shell_or_administrator_escalation() -> None:
    setup = (ROOT / "src" / "scenelight" / "setup_gui.py").read_text(encoding="utf-8")
    assert "shell=True" not in setup
    assert "runas" not in setup.lower()
    assert '"--cli"' in setup
    assert "scenelight_sdk.py" in setup


def test_source_checkout_retains_a_direct_cli_entry_point() -> None:
    launcher = (ROOT / "scenelight_sdk.py").read_text(encoding="utf-8")
    assert 'import_module("scenelight.cli").main' in launcher


def test_setup_bootstraps_only_a_verified_scenelight_runtime() -> None:
    launcher = (ROOT / "SceneLight.bat").read_text(encoding="utf-8")
    bootstrap = (ROOT / "tools" / "bootstrap_python.ps1").read_text(encoding="utf-8")
    assert "%LOCALAPPDATA%\\SceneLight\\bootstrap-python" in launcher
    assert "Get-AuthenticodeSignature" in launcher
    assert "Python Software Foundation" in launcher
    assert "InstallAllUsers=0" in bootstrap
    assert "PrependPath=0" in bootstrap
    assert "AssociateFiles=0" in bootstrap
    assert "runas" not in launcher.lower()


def test_online_setup_downloads_only_the_pinned_verified_python_runtime() -> None:
    bootstrap = (ROOT / "tools" / "bootstrap_python.ps1").read_text(encoding="utf-8")
    assert "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" in bootstrap
    assert "5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde" in bootstrap
    assert "Get-AuthenticodeSignature" in bootstrap
    assert "Python Software Foundation" in bootstrap
    assert "InstallAllUsers=0" in bootstrap
    assert "PrependPath=0" in bootstrap


def test_installed_setup_entry_point_is_a_windowed_gui_script() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.gui-scripts]" in metadata
    assert 'scenelight-setup = "scenelight.setup_gui:main"' in metadata
    assert 'scenelight-preview = "scenelight.preview.__main__:main"' in metadata


def test_direct_preview_launcher_reports_missing_components() -> None:
    launcher = (ROOT / "scenelight_preview.pyw").read_text(encoding="utf-8")
    assert "REQUIRED_MODULES" in launcher
    assert "Preview components are not installed" in launcher
    assert "Open SceneLight" in launcher
    assert "skimage" not in launcher
    assert "scikit-image" not in launcher


def test_runtime_capture_exits_without_running_mod_quit_labels() -> None:
    supervisor = (ROOT / "src" / "scenelight" / "capture.py").read_text(encoding="utf-8")
    capture = (ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy").read_text(
        encoding="utf-8"
    )
    assert "process = subprocess.Popen(" in supervisor
    assert "if result_path.is_file():" in supervisor
    assert "process.terminate()" in supervisor
    assert "os._exit(0)" in capture
    assert "_scenelight_atomic_replace(temporary_result_path, result_path)" in capture
    assert "flush=True" not in capture
    assert "_scenelight_string_types = (basestring,)" in capture


def test_release_builder_removes_local_python_build_metadata() -> None:
    builder = (ROOT / "tools" / "build_release_zip.ps1").read_text(encoding="utf-8")
    assert '"*.egg-info"' in builder
    assert '"__pycache__"' in builder
    assert '-notmatch "Python Software Foundation"' in builder
    assert '"-offline"' in builder
    assert "finally {" in builder
    assert "Remove-VerifiedStagingTree -Path $staging" in builder


def test_release_builder_validates_and_bundles_legacy_compatibility_runtime() -> None:
    builder = (ROOT / "tools" / "build_release_zip.ps1").read_text(encoding="utf-8")
    assert "[string]$CompatibilityRuntime" in builder
    assert 'Join-Path $resolvedCompatibilityRuntime "renpy.exe"' in builder
    assert 'Join-Path $resolvedCompatibilityRuntime "LICENSE.txt"' in builder
    assert "version_tuple\\s*=\\s*\\(\\s*7\\s*," in builder
    assert 'Join-Path $payloadRoot "compatibility-runtime"' in builder
    assert "Offline releases require -CompatibilityRuntime" in builder
    assert "$packagedCompatibilityPrefix" in builder
    assert "-not $_.FullName.StartsWith(" in builder


def test_windows_launchers_do_not_reenter_during_cuda_worker_spawn() -> None:
    launchers = (
        ROOT / "scenelight_sdk.py",
        ROOT / "scenelight_setup.pyw",
        ROOT / "src" / "scenelight" / "__main__.py",
    )
    for launcher in launchers:
        source = launcher.read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":' in source
        assert "freeze_support()" in source
