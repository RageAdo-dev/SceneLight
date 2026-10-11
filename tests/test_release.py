import json
from pathlib import Path
from types import SimpleNamespace

import scenelight.builder as builder
import scenelight.cli as cli_module
import scenelight.release as release_module
from scenelight import __version__
from scenelight.capture import CAPTURE_VERSION
from scenelight.cli import (
    _preserve_analysis_cache,
    _restore_analysis_cache,
    _seed_embedded_form_cache,
    _write_install_config,
)
from scenelight.form_maps import FORM_MAP_VERSION
from scenelight.release import (
    FIRST_PUBLIC_VERSION,
    classify_release,
    release_content_sha256,
    release_record,
    release_version_from_manifest,
)


def test_100_is_the_first_public_release() -> None:
    assert FIRST_PUBLIC_VERSION == "1.0.0"


def test_versionless_install_is_explicitly_pre_release() -> None:
    relation = classify_release(None)

    assert relation.kind == "pre_release"
    assert relation.replacement_available
    assert relation.installed_label == "pre-1.0 internal build"


def test_release_relation_handles_rc_upgrade_and_newer_downgrade() -> None:
    assert classify_release("1.0.0-rc.2").kind == "upgrade"
    assert classify_release("1.0.0").kind == "upgrade"
    assert classify_release(__version__).kind == "current"
    assert classify_release("1.1.0").kind == "downgrade"
    assert classify_release("1.1.1").kind == "downgrade"
    assert classify_release("1.2.0").kind == "downgrade"
    assert classify_release("old-local-build").kind == "unrecognized"


def test_same_version_with_different_recorded_build_is_replaceable() -> None:
    relation = classify_release(
        __version__,
        installed_content_sha256="0" * 64,
        current_content_sha256="f" * 64,
    )

    assert relation.kind == "different_build"
    assert relation.replacement_available


def test_release_record_names_every_cache_contract() -> None:
    record = release_record()

    fingerprint = release_content_sha256()
    assert len(fingerprint) == 64
    assert record == {
        "version": 1,
        "product_version": __version__,
        "first_public_version": "1.0.0",
        "runtime_api_version": 1,
        "runtime_manifest_version": 8,
        "transport_algorithm": "14-spatial-radiance-basis",
        "sprite_form_version": 9,
        "capture_version": 42,
        "capture_plan_version": 3,
        "capture_pixel_version": 2,
        "content_sha256": fingerprint,
    }


def test_wheel_fingerprint_tracks_installed_package_bytes(tmp_path, monkeypatch):
    import hashlib

    package = tmp_path / "site-packages" / "scenelight"
    package.mkdir(parents=True)
    module = package / "release.py"
    module.write_text("first build", encoding="utf-8")
    monkeypatch.setattr(release_module, "__file__", str(module))
    release_content_sha256.cache_clear()
    try:
        first = release_content_sha256()
        assert first != hashlib.sha256(b"").hexdigest()
        module.write_text("other build", encoding="utf-8")
        release_content_sha256.cache_clear()
        assert release_content_sha256() != first
    finally:
        release_content_sha256.cache_clear()


def test_release_version_reads_public_and_nested_manifest_fields() -> None:
    assert release_version_from_manifest({}) is None
    assert release_version_from_manifest({"scenelight_version": "1.0.0"}) == "1.0.0"
    assert release_version_from_manifest({"release": {"product_version": "1.1.0"}}) == "1.1.0"


def test_managed_install_manifest_records_release_identity(tmp_path: Path) -> None:
    project = tmp_path / "source"
    managed = tmp_path / "managed"
    project.mkdir()
    managed.mkdir()

    _write_install_config(
        managed,
        project_root=project,
        config=None,
        grid=(16, 9),
        workers=None,
        analyzer="cpu",
        renpy_sdk=None,
        playback_executable=None,
        playback_native=True,
        native_launcher=None,
        save_backup={},
    )

    payload = json.loads((managed / ".scenelight_install.json").read_text(encoding="utf-8"))
    assert payload["scenelight_version"] == __version__
    assert payload["release"] == release_record()


def test_transport_algorithm_version_is_part_of_the_cache_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "background.png"
    source.write_bytes(b"same background bytes")
    original = builder._transport_cache_path(tmp_path, "room", source, (16, 9))

    monkeypatch.setattr(builder, "TRANSPORT_CACHE_VERSION", "8-new-lighting-math")
    changed = builder._transport_cache_path(tmp_path, "room", source, (16, 9))

    assert original != changed


def test_analysis_cache_survives_disposable_managed_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-projects"))
    project = tmp_path / "source-game"
    managed = tmp_path / "working-copy"
    cache = managed / ".scenelight_cache"
    cache.mkdir(parents=True)
    (cache / "capture_state.json").write_text(
        json.dumps({"version": CAPTURE_VERSION}),
        encoding="utf-8",
    )

    preserved = _preserve_analysis_cache(project, managed)
    assert preserved is not None
    assert (preserved / "capture_state.json").is_file()

    (managed / ".scenelight_cache").rename(managed / "discarded-cache")
    assert _restore_analysis_cache(project, managed)
    assert (managed / ".scenelight_cache" / "capture_state.json").is_file()


def test_completed_analysis_cache_omits_transient_capture_markers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-projects"))
    project = tmp_path / "source-game"
    managed = tmp_path / "working-copy"
    cache = managed / ".scenelight_cache"
    captured = cache / "captured" / "one"
    captured.mkdir(parents=True)
    (cache / "capture_state.json").write_text(
        json.dumps({"version": CAPTURE_VERSION}),
        encoding="utf-8",
    )
    (cache / "capture_result.json").write_text(
        json.dumps({"version": CAPTURE_VERSION}),
        encoding="utf-8",
    )
    (captured / "sprite.png").write_bytes(b"png")
    (captured / "sprite.png.surface-normalized").write_text(
        "normalized\n",
        encoding="utf-8",
    )

    preserved = _preserve_analysis_cache(project, managed)

    assert preserved is not None
    assert (preserved / "captured" / "one" / "sprite.png").is_file()
    assert not (preserved / "captured" / "one" / "sprite.png.surface-normalized").exists()


def test_analysis_cache_transaction_does_not_repeat_a_long_project_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-projects"))
    project = tmp_path / ("very-long-project-name-" * 2)
    managed = tmp_path / "working-copy"
    cache = managed / ".scenelight_cache"
    nested = cache / "captured" / "signature" / "parallel" / "worker-1"
    nested.mkdir(parents=True)
    long_capture = nested / ("sprite_yuri_" + "long_form_" * 2 + ".png")
    long_capture.write_bytes(b"png")
    copied_to: list[Path] = []
    original_copytree = cli_module.shutil.copytree

    def record_copytree(source, destination, *args, **kwargs):
        copied_to.append(Path(destination))
        return original_copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(cli_module.shutil, "copytree", record_copytree)
    monkeypatch.setattr(
        cli_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="0" * 32),
    )

    preserved = _preserve_analysis_cache(project, managed)

    assert preserved is not None
    assert (preserved / long_capture.relative_to(cache)).read_bytes() == b"png"
    assert copied_to[0].name == ".slc-0000000000000000.tmp"
    assert preserved.name not in copied_to[0].name


def test_direct_refresh_seeds_only_compatible_sprite_form_maps(tmp_path: Path) -> None:
    project = tmp_path / "source-game"
    source = project / "game" / "scenelight_runtime"
    forms = source / "sprite_form"
    forms.mkdir(parents=True)
    (forms / "hero_response.png").write_bytes(b"map")
    manifest = source / "sprite_form_manifest.json"
    manifest.write_text(
        json.dumps({"version": FORM_MAP_VERSION, "sprites": {"hero idle": {"response": "map"}}}),
        encoding="utf-8",
    )
    managed = tmp_path / "working-copy"
    (managed / "game").mkdir(parents=True)

    assert _seed_embedded_form_cache(project, managed) == 1
    assert (managed / "game" / "scenelight_runtime" / "sprite_form" / "hero_response.png").is_file()

    incompatible = tmp_path / "incompatible"
    incompatible_source = incompatible / "game" / "scenelight_runtime"
    incompatible_forms = incompatible_source / "sprite_form"
    incompatible_forms.mkdir(parents=True)
    (incompatible_forms / "hero_response.png").write_bytes(b"old map")
    (incompatible_source / "sprite_form_manifest.json").write_text(
        json.dumps({"version": FORM_MAP_VERSION - 1, "sprites": {"hero idle": {}}}),
        encoding="utf-8",
    )
    other_managed = tmp_path / "other-working-copy"
    (other_managed / "game").mkdir(parents=True)

    assert _seed_embedded_form_cache(incompatible, other_managed) == 0
    assert not (other_managed / "game" / "scenelight_runtime").exists()
