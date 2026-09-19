"""SceneLight command-line installer and verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .builder import RUNTIME_MANIFEST_VERSION, TRANSPORT_GRID_SIZE, build_project
from .calibration import profile_path
from .capture import (
    CaptureInstanceConflict,
    capture_runtime_assets,
    capture_runtime_review,
    capture_source,
    merge_capture,
    needs_runtime_capture,
    preflight_runtime,
)
from .compatibility import cached_renpy_executable
from .developer import (
    developer_status,
    embed_from_managed,
    preflight_embed_destination,
    preflight_refresh_destination,
    refresh_embedded_from_managed,
    remove_embedded,
)
from .form_maps import FORM_MAP_VERSION
from .launch_safety import install_native_launcher, snapshot_saves
from .project import discover_project
from .release import release_record
from .sidecar import (
    analysis_cache_root,
    find_native_executable,
    managed_project_root,
    remove_analysis_cache,
    remove_managed_project,
    renpy_runtime_command,
    renpy_runtime_major,
    sync_project,
    visual_sources_changed,
)


def _configure_utf8_output(stream: object | None) -> None:
    """Make redirected Windows CLI progress safe for international asset names."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass


def _grid(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("grid must look like 16x9") from error
    if width < 2 or height < 2:
        raise argparse.ArgumentTypeError("grid must be at least 2x2")
    return width, height


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenelight",
        description="Attach live GPU 2D scene relighting to a local Ren'Py project.",
    )
    parser.add_argument("--version", action="version", version=f"SceneLight {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "scan",
        "attach",
        "install",
        "verify",
        "launch",
        "remove",
        "embed",
        "refresh",
        "unembed",
        "embed-status",
    ):
        command = subcommands.add_parser(name)
        command.add_argument("--project", required=True, type=Path)
        command.add_argument("--config", type=Path)
        if name == "scan":
            command.add_argument(
                "--runtime-review",
                action="store_true",
                help=(
                    "Preflight the renderer and inventory archive-backed image families in "
                    "an isolated copy for the setup review."
                ),
            )
            command.add_argument(
                "--renpy-sdk",
                type=Path,
                help="Optional compatible Ren'Py SDK fallback for isolated review.",
            )
        if name in {"attach", "install", "embed", "refresh"}:
            command.add_argument(
                "--grid",
                type=_grid,
                default=TRANSPORT_GRID_SIZE,
                help="Position-transport resolution (default: 16x9).",
            )
            command.add_argument("--workers", type=int)
            command.add_argument(
                "--analyzer",
                choices=("auto", "cuda", "cpu"),
                default="auto",
                help="Background analyzer (default: auto; CUDA with exact CPU fallback).",
            )
            command.add_argument(
                "--renpy-sdk",
                type=Path,
                help=(
                    "Optional compatible Ren'Py SDK fallback for isolated asset analysis; "
                    "the mod's native runtime is preferred when available."
                ),
            )
            command.add_argument(
                "--no-backup",
                action="store_true",
                help="Deprecated compatibility flag; installs are transactional and reversible.",
            )
    return parser


def _runtime_source() -> Path:
    source = Path(__file__).resolve().parent / "runtime" / "scenelight_runtime.rpy"
    if not source.is_file():
        raise FileNotFoundError(f"Bundled Ren'Py runtime is missing: {source}")
    return source


def _effective_config(project_root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    external_profile = profile_path(project_root)
    return external_profile if external_profile.is_file() else None


def _config_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _launch_config(project_root: Path, install: dict[str, object]) -> tuple[Path | None, bool]:
    recorded = install.get("config")
    config = Path(str(recorded)).expanduser().resolve() if recorded else None
    if config is None:
        candidate = profile_path(project_root)
        if candidate.is_file():
            config = candidate
    current_digest = _config_sha256(config)
    changed = current_digest != install.get("config_sha256")
    return config, changed


def _install_runtime_files(game_root: Path) -> None:
    shutil.copy2(_runtime_source(), game_root / "scenelight_runtime.rpy")
    data_root = game_root / "scenelight_runtime"
    data_root.mkdir(parents=True, exist_ok=True)
    for name in (
        "live_gpu",
        "live_renpy",
        "live_opencl",
        "prepared",
        "prepared_renpy",
        "shader_stages",
        "shader_renpy",
    ):
        shutil.copy2(_runtime_source().with_name(name + ".py"), data_root / (name + ".txt"))


def _resolve_renpy_executable(project_root: Path, explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        requested = explicit.expanduser().resolve()
        candidates.append(requested if requested.is_file() else requested / "renpy.exe")

    environment_sdk = os.environ.get("RENPY_SDK")
    if environment_sdk:
        requested = Path(environment_sdk).expanduser().resolve()
        candidates.append(requested if requested.is_file() else requested / "renpy.exe")

    compatibility_runtime = os.environ.get("SCENELIGHT_COMPAT_RENPY")
    if compatibility_runtime:
        requested = Path(compatibility_runtime).expanduser().resolve()
        candidates.append(requested if requested.is_file() else requested / "renpy.exe")

    source_root = Path(__file__).resolve().parents[2]
    cached_compatibility = cached_renpy_executable()
    candidates.extend(
        (
            source_root / "compatibility-runtime" / "renpy.exe",
            Path(sys.executable).resolve().parent / "compatibility-runtime" / "renpy.exe",
        )
    )
    if cached_compatibility is not None:
        candidates.append(cached_compatibility)

    search_roots = [project_root, *list(project_root.parents)[:3], Path.cwd().resolve()]
    for root in search_roots:
        candidates.extend(
            candidate / "renpy.exe" for candidate in sorted(root.glob("renpy-*-sdk"), reverse=True)
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _runtime_capture_launchers(
    managed_root: Path,
    sdk_executable: Path | None,
) -> list[tuple[Path, bool, str]]:
    """Return compatible capture runtimes in safest-first order."""

    launchers: list[tuple[Path, bool, str]] = []
    native = find_native_executable(managed_root)
    native_major = renpy_runtime_major(native)
    sdk_major = renpy_runtime_major(sdk_executable)

    # Ren'Py 6 can resolve its own archives, but it cannot register the GPU
    # shaders SceneLight needs for playback. A Ren'Py 7 compatibility runtime
    # preserves Python 2 game compatibility while providing the shader API.
    if native_major is not None and native_major < 7:
        if sdk_executable is not None and sdk_major == 7:
            launchers.append((sdk_executable, False, "SceneLight's Ren'Py 7 compatibility runtime"))
        return launchers

    if native is not None:
        launchers.append((native, True, "the mod's native Ren'Py runtime"))
    if (
        sdk_executable is not None
        and (native is None or sdk_executable.resolve() != native.resolve())
        and (
            native is None
            or (native_major is not None and sdk_major is not None and native_major == sdk_major)
        )
    ):
        launchers.append((sdk_executable, False, "the selected Ren'Py SDK"))
    return launchers


def _renderer_attempts(
    launchers: list[tuple[Path, bool, str]],
) -> list[tuple[Path, bool, str, str | None]]:
    """Expand runtimes into ordered renderer attempts they actually bundle."""

    attempts: list[tuple[Path, bool, str, str | None]] = []
    for executable, native_runtime, label in launchers:
        runtime_root = executable.parent
        renderers: list[str | None] = [None]
        renpy_root = runtime_root / "renpy"
        if (renpy_root / "gl2").is_dir():
            renderers.extend(("angle2", "gl2"))
        elif (renpy_root / "angle").is_dir():
            renderers.extend(("angle", "gl"))
        for renderer in renderers:
            name = "automatic renderer" if renderer is None else f"{renderer} renderer"
            attempts.append((executable, native_runtime, f"{label} ({name})", renderer))
    return attempts


def _batch_quote(value: str | os.PathLike[str]) -> str:
    """Quote a Windows batch argument without allowing percent expansion."""

    text = str(value)
    if '"' in text or any(ord(character) < 32 for character in text):
        raise ValueError("A launcher path contains an unsupported character.")
    return '"' + text.replace("%", "%%") + '"'


def _playback_command(executable: Path, project_root: Path, *, native_runtime: bool) -> list[str]:
    return renpy_runtime_command(
        executable,
        project_root,
        native_runtime=native_runtime,
    )


def _write_launcher(
    project_root: Path, managed_root: Path, playback_executable: Path | None
) -> Path | None:
    if playback_executable is None:
        return None
    launcher = managed_root / "Launch with SceneLight.bat"
    source_launcher = Path(__file__).resolve().parents[2] / "scenelight_sdk.py"
    if source_launcher.is_file():
        command = (
            f"{_batch_quote(sys.executable)} {_batch_quote(source_launcher)} "
            f"launch --project {_batch_quote(project_root)}"
        )
    else:
        command = (
            f"{_batch_quote(sys.executable)} -m scenelight.cli "
            f"launch --project {_batch_quote(project_root)}"
        )
    launcher.write_text(
        "\n".join(
            (
                "@echo off",
                "setlocal",
                command,
                "if errorlevel 1 pause",
                "endlocal",
                "",
            )
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    return launcher


def _verify(project_root: Path) -> dict[str, object]:
    managed_root = managed_project_root(project_root)
    developer_manifest = project_root / ".scenelight_developer_install.json"
    verification_root = project_root if developer_manifest.is_file() else managed_root
    install_location = "in-place" if verification_root == project_root else "separate-copy"
    game_root = verification_root / "game"
    runtime_script = (
        game_root / "scenelight_runtime" / "bootstrap.rpy"
        if install_location == "in-place"
        else game_root / "scenelight_runtime.rpy"
    )
    required = [
        runtime_script,
        game_root / "scenelight_runtime" / "manifest.json",
        game_root / "scenelight_runtime" / "sprite_form_manifest.json",
        game_root / "scenelight_runtime" / "effect_packs.json",
        game_root / "scenelight_runtime" / "irradiance_atlas.png",
        game_root / "scenelight_runtime" / "emitter_atlas.png",
        game_root / "scenelight_runtime" / "wrap_atlas.png",
        game_root / "scenelight_runtime" / "transport_atlas.png",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    manifest: dict[str, object] = {}
    form_manifest: dict[str, object] = {}
    if not missing:
        runtime_text = required[0].read_text(encoding="utf-8")
        manifest = json.loads(required[1].read_text(encoding="utf-8"))
        form_manifest = json.loads(required[2].read_text(encoding="utf-8"))
        if "scenelight.dynamic_sprite" not in runtime_text:
            missing.append("full hybrid GPU runtime")
        if manifest.get("version") != RUNTIME_MANIFEST_VERSION:
            missing.append(f"manifest version {RUNTIME_MANIFEST_VERSION}")
        if manifest.get("transport_atlas", {}).get("planes") != 26:
            missing.append("26-plane position transport")
        if not manifest.get("scenes"):
            missing.append("at least one mapped scene")
        # Projects whose registered forms are all placeholders or unsupported
        # still have a valid generic fallback surface. Individual failures are
        # reported in the form manifest instead of invalidating the install.
    native_launcher = find_native_executable(verification_root)
    return {
        "ok": not missing,
        "missing_or_invalid": missing,
        "mode": "hybrid-gpu" if not missing else None,
        "scene_count": len(manifest.get("scenes", {})),
        "sprite_count": len(form_manifest.get("sprites", {})),
        "character_tags": manifest.get("character_tags", []),
        "source_project": str(project_root),
        "managed_project": str(managed_root),
        "verified_project": str(verification_root),
        "install_location": install_location,
        "source_untouched": verification_root != project_root,
        "launcher": str(native_launcher) if native_launcher else None,
        "skipped_sprites": form_manifest.get("skipped", []),
    }


def _mapped_config(project_root: Path, managed_root: Path, config: Path | None) -> Path | None:
    if config is None:
        return None
    resolved = config.expanduser().resolve()
    try:
        return managed_root / resolved.relative_to(project_root)
    except ValueError:
        return resolved


def _remove_capture_bootstrap(game_root: Path) -> None:
    for name in ("scenelight_capture.rpy", "scenelight_capture.rpyc"):
        path = game_root / name
        if path.is_file():
            path.unlink()


def _clear_runtime_script_cache(game_root: Path) -> None:
    """Drop generated Ren'Py script caches after changing helper/runtime files."""

    cache_root = game_root / "cache"
    if not cache_root.is_dir():
        return
    for path in cache_root.glob("*.rpyb"):
        if path.is_file():
            path.unlink()


@contextmanager
def _capture_without_installed_runtime(game_root: Path) -> Iterator[None]:
    """Temporarily remove only SceneLight's wrapper during raw recapture.

    An update reuses the managed copy, where the installed wrapper would turn
    otherwise-static images into dynamic displayables and defeat exact surface
    capture. The prior runtime is moved into the isolated cache and restored even
    when preflight or capture fails. Generated Ren'Py bytecode is invalidated so
    neither the suspended wrapper nor the disposable helper survives by cache.
    """

    backup_root = game_root.parent / ".scenelight_cache" / "suspended-runtime"
    names = (
        "scenelight_runtime",
        "scenelight_runtime.rpy",
        "scenelight_runtime.rpyc",
    )

    _restore_suspended_runtime(game_root)

    for name in names:
        source = game_root / name
        if not source.exists():
            continue
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / name
        os.replace(source, backup)

    _clear_runtime_script_cache(game_root)
    try:
        yield
    finally:
        _remove_capture_bootstrap(game_root)
        _clear_runtime_script_cache(game_root)
        _restore_suspended_runtime(game_root)


def _restore_suspended_runtime(game_root: Path) -> None:
    """Recover a killed capture BEFORE reseeding forms on the next attempt."""
    backup_root = game_root.parent / ".scenelight_cache" / "suspended-runtime"
    names = ("scenelight_runtime", "scenelight_runtime.rpy", "scenelight_runtime.rpyc")
    conflict_root = backup_root.parent / "recovered-runtime-conflicts" / uuid.uuid4().hex
    for name in names:
        backup = backup_root / name
        destination = game_root / name
        if not backup.exists():
            continue
        if destination.exists():
            # A previous retry may have reseeded form files before recovery.
            # Preserve all conflicting bytes instead of deleting or merging
            # them with the known runtime that was suspended for capture.
            conflict_root.mkdir(parents=True, exist_ok=True)
            os.replace(destination, conflict_root / name)
            print(f"Interrupted update files preserved: {conflict_root / name}", flush=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup, destination)

    try:
        backup_root.rmdir()
    except OSError:
        pass


def _scan_runtime_review(
    project_root: Path,
    *,
    config: Path | None,
    renpy_sdk: Path | None,
) -> dict[str, object]:
    """Preflight a managed copy and enrich static discovery with runtime candidates."""

    print("SceneLight scan 1/4: inspecting project structure and configuration", flush=True)
    discover_project(project_root, config)
    print("SceneLight scan 2/4: preparing the isolated inspection copy", flush=True)

    def report_sync_progress(current: int, total: int, relative: str) -> None:
        print(f"SceneLight scan files {current}/{total}: {relative}", flush=True)

    synced = sync_project(project_root, progress=report_sync_progress)
    managed_root = synced.managed
    source_native = find_native_executable(project_root)
    sdk_executable = _resolve_renpy_executable(project_root, renpy_sdk)
    native_major = renpy_runtime_major(source_native)
    if native_major is not None and native_major < 7:
        sdk_major = renpy_runtime_major(sdk_executable)
        if sdk_executable is None or sdk_major != 7:
            raise RuntimeError(
                "This game uses Ren'Py 6, whose renderer cannot run SceneLight's live GPU "
                "shader. SceneLight's Ren'Py 7 compatibility runtime is missing or invalid. "
                "Reinstall SceneLight with the compatibility runtime included."
            )

    print("SceneLight scan 3/4: testing the game runtime and registered images", flush=True)
    with _capture_without_installed_runtime(managed_root / "game"):
        discovery = discover_project(
            managed_root,
            _mapped_config(project_root, managed_root, config),
        )
        shutil.copy2(capture_source(), discovery.game_root / "scenelight_capture.rpy")
        attempts = _renderer_attempts(_runtime_capture_launchers(managed_root, sdk_executable))
        selected_attempt: tuple[Path, bool, str, str | None] | None = None
        review = None
        failures: list[str] = []
        for index, attempt in enumerate(attempts, start=1):
            executable, native_runtime, label, renderer = attempt
            print(f"SceneLight renderer {index}/{len(attempts)}: trying {label}", flush=True)
            try:
                preflight_runtime(
                    discovery,
                    executable,
                    native_runtime=native_runtime,
                    renderer=renderer,
                )
                # Mixed source/archive games can gain registered characters
                # that static parsing cannot see. The review cache is keyed by
                # authored content, so unchanged projects remain inexpensive.
                review = capture_runtime_review(
                    discovery,
                    executable,
                    native_runtime=native_runtime,
                    renderer=renderer,
                )
            except CaptureInstanceConflict:
                raise
            except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
                failures.append(f"{label}: {error}")
                continue
            selected_attempt = attempt
            print(f"SceneLight preflight 1/1: {label} initialized successfully", flush=True)
            break

    if attempts and selected_attempt is None:
        detail = "\n\n".join(failures)
        raise RuntimeError(
            "SceneLight tried every compatible graphics backend bundled with the game "
            f"and any selected SDK, but none initialized.\n\n{detail}"
        )
    if not attempts and discovery.requires_runtime_inventory:
        raise FileNotFoundError(
            "This project needs archive/LayeredImage review but has no native Ren'Py "
            "executable. Choose a compatible Ren'Py SDK for isolated inspection."
        )

    if review is not None:
        discovery.character_candidates.update(
            {
                tag: str(path) if path is not None else None
                for tag, path in review.character_candidates.items()
            }
        )
        suggestions = set(discovery.suggested_character_tags) | set(review.character_tags)
        discovery.suggested_character_tags = sorted(suggestions)
        if discovery.character_selection == "automatic":
            discovery.character_tags = sorted(
                (set(discovery.character_tags) | suggestions)
                - set(discovery.excluded_character_tags)
            )
        for tag in discovery.explicit_character_tags:
            discovery.character_candidates.setdefault(tag, None)

    print("SceneLight scan 4/4: finalizing backgrounds and character candidates", flush=True)
    payload = discovery.summary()
    payload["project"] = str(project_root)
    payload["runtime_preflight"] = selected_attempt is not None
    payload["runtime_renderer"] = selected_attempt[3] if selected_attempt else None
    payload["runtime_renderer_label"] = selected_attempt[2] if selected_attempt else None
    return payload


def _write_install_config(
    managed_root: Path,
    *,
    project_root: Path,
    config: Path | None,
    grid: tuple[int, int],
    workers: int | None,
    analyzer: str,
    renpy_sdk: Path | None,
    playback_executable: Path | None,
    playback_native: bool,
    native_launcher: dict[str, object] | None,
    save_backup: dict[str, object],
) -> None:
    payload = {
        "version": 1,
        "scenelight_version": __version__,
        "release": release_record(),
        "source": str(project_root),
        "config": str(config) if config else None,
        "config_sha256": _config_sha256(config),
        "grid": list(grid),
        "workers": workers,
        "analyzer": analyzer,
        "renpy_sdk": str(renpy_sdk) if renpy_sdk else None,
        "playback_executable": str(playback_executable) if playback_executable else None,
        "playback_native": playback_native,
        "playback_runtime_major": renpy_runtime_major(playback_executable),
        "native_launcher": native_launcher,
        "save_backup": save_backup,
    }
    path = managed_root / ".scenelight_install.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _restore_analysis_cache(project_root: Path, managed_root: Path) -> bool:
    """Hydrate a disposable managed build with the last verified analysis cache."""

    source = analysis_cache_root(project_root)
    destination = managed_root / ".scenelight_cache"
    if destination.exists() or not source.is_dir():
        return False
    try:
        shutil.copytree(source, destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    print(f"Reusable analysis cache restored: {source}", flush=True)
    return True


def _preserve_analysis_cache(project_root: Path, managed_root: Path) -> Path | None:
    """Atomically retain capture/transport caches after a managed build is discarded."""

    source = managed_root / ".scenelight_cache"
    if not source.is_dir():
        return None
    destination = analysis_cache_root(project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Do not repeat the user-controlled project name in transactional paths.
    # Sprite capture filenames can already be close to legacy Windows MAX_PATH;
    # the old ``.<project>-<uuid>.tmp`` staging name made otherwise valid cache
    # entries impossible to copy.
    transaction = uuid.uuid4().hex[:16]
    stage = destination.parent / f".slc-{transaction}.tmp"
    backup = destination.parent / f".slc-{transaction}.bak"
    moved_existing = False
    completed_capture = False
    try:
        capture_state = json.loads((source / "capture_state.json").read_text(encoding="utf-8"))
        capture_result = json.loads((source / "capture_result.json").read_text(encoding="utf-8"))
        completed_capture = (
            isinstance(capture_state, dict)
            and isinstance(capture_result, dict)
            and capture_state.get("version") == capture_result.get("version")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        completed_capture = False
    ignore = (
        shutil.ignore_patterns(
            "*.surface-checkpoint",
            "*.surface-normalized",
            "*.scene-checkpoint",
            "*.source-copy.*",
            "*.tmp",
        )
        if completed_capture
        else None
    )
    try:
        shutil.copytree(source, stage, ignore=ignore)
        if destination.exists():
            os.replace(destination, backup)
            moved_existing = True
        os.replace(stage, destination)
        if backup.is_dir():
            shutil.rmtree(backup)
    except Exception:
        if stage.is_dir():
            shutil.rmtree(stage, ignore_errors=True)
        if moved_existing and backup.is_dir() and not destination.exists():
            os.replace(backup, destination)
        raise
    print(f"Reusable analysis cache preserved: {destination}", flush=True)
    return destination


def _seed_embedded_form_cache(project_root: Path, managed_root: Path) -> int:
    """Reuse exact compatible form maps from a verified direct installation."""

    source_data = project_root / "game" / "scenelight_runtime"
    source_manifest = source_data / "sprite_form_manifest.json"
    source_forms = source_data / "sprite_form"
    destination_data = managed_root / "game" / "scenelight_runtime"
    destination_manifest = destination_data / "sprite_form_manifest.json"
    destination_forms = destination_data / "sprite_form"
    if destination_manifest.is_file() or not source_manifest.is_file() or not source_forms.is_dir():
        return 0
    try:
        payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    sprites = payload.get("sprites")
    if payload.get("version") != FORM_MAP_VERSION or not isinstance(sprites, dict):
        return 0
    destination_data.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source_forms, destination_forms)
        shutil.copy2(source_manifest, destination_manifest)
    except Exception:
        destination_manifest.unlink(missing_ok=True)
        shutil.rmtree(destination_forms, ignore_errors=True)
        raise
    print(f"Compatible embedded form cache restored: {len(sprites)} forms", flush=True)
    return len(sprites)


def _install_managed(
    project_root: Path,
    *,
    config: Path | None,
    grid: tuple[int, int],
    workers: int | None,
    analyzer: str,
    renpy_sdk: Path | None,
    reuse_embedded_cache: bool = False,
) -> dict[str, object]:
    # Finish the read-only compatibility checks before taking a save snapshot
    # or starting expensive background/sprite analysis.
    discover_project(project_root, config)
    source_native = find_native_executable(project_root)
    sdk_executable = _resolve_renpy_executable(project_root, renpy_sdk)
    native_major = renpy_runtime_major(source_native)
    if native_major is not None and native_major < 7:
        sdk_major = renpy_runtime_major(sdk_executable)
        if sdk_executable is None or sdk_major != 7:
            raise RuntimeError(
                "This game uses Ren'Py 6, whose renderer cannot run SceneLight's live GPU "
                "shader. SceneLight's Ren'Py 7 compatibility runtime is missing or invalid. "
                "Reinstall SceneLight with the compatibility runtime included."
            )
    existing_install_path = managed_project_root(project_root) / ".scenelight_install.json"
    try:
        existing_install = json.loads(existing_install_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing_install = {}
    existing_save_backup = existing_install.get("save_backup")
    save_backup: dict[str, object] | None = (
        existing_save_backup if isinstance(existing_save_backup, dict) else None
    )

    synced = sync_project(project_root)
    managed_root = synced.managed
    analysis_cache_reused = _restore_analysis_cache(project_root, managed_root)
    _restore_suspended_runtime(managed_root / "game")
    embedded_form_cache_count = (
        _seed_embedded_form_cache(project_root, managed_root) if reuse_embedded_cache else 0
    )
    with _capture_without_installed_runtime(managed_root / "game"):
        discovery = discover_project(
            managed_root,
            _mapped_config(project_root, managed_root, config),
        )
        native_executable = find_native_executable(managed_root)
        native_major = renpy_runtime_major(native_executable)
        shutil.copy2(capture_source(), discovery.game_root / "scenelight_capture.rpy")
        launchers = _runtime_capture_launchers(managed_root, sdk_executable)
        attempts = _renderer_attempts(launchers)
        preflight_completed = False
        runtime_save_directory: str | None = None
        selected_attempt: tuple[Path, bool, str, str | None] | None = None
        preflight_failures: list[str] = []
        if attempts:
            for index, attempt in enumerate(attempts, start=1):
                executable, native_runtime, label, renderer = attempt
                print(f"SceneLight renderer {index}/{len(attempts)}: trying {label}", flush=True)
                try:
                    runtime_save_directory = preflight_runtime(
                        discovery,
                        executable,
                        native_runtime=native_runtime,
                        renderer=renderer,
                    )
                except CaptureInstanceConflict:
                    raise
                except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
                    preflight_failures.append(f"{label}: {error}")
                    continue
                selected_attempt = attempt
                preflight_completed = True
                print(f"SceneLight preflight 1/1: {label} initialized successfully", flush=True)
                break
            if selected_attempt is None:
                detail = "\n\n".join(preflight_failures)
                raise RuntimeError(
                    "SceneLight tried every compatible graphics backend bundled with the game "
                    f"and any selected SDK, but none initialized.\n\n{detail}"
                )
        else:
            print(
                "SceneLight preflight unavailable: no native executable or compatible SDK was "
                "found.",
                flush=True,
            )

        # Compatibility is now known. Preserve both project-local and Ren'Py
        # roaming saves before any install/build output is committed.
        if save_backup is None:
            save_backup = snapshot_saves(
                project_root,
                save_directory=runtime_save_directory,
            )
            if save_backup["created"]:
                print(f"Save safety snapshot: {save_backup['path']}", flush=True)
        if selected_attempt is not None:
            playback_executable = selected_attempt[0]
            playback_native = selected_attempt[1]
        elif native_executable is not None and (native_major is None or native_major >= 7):
            playback_executable = native_executable
            playback_native = True
        elif sdk_executable is not None:
            playback_executable = sdk_executable
            playback_native = False
        else:
            playback_executable = None
            playback_native = False
        capture = None
        if needs_runtime_capture(discovery):
            if not launchers:
                raise FileNotFoundError(
                    "This project contains LayeredImage/archive-backed assets but has no native "
                    "Ren'Py executable. Choose a compatible Ren'Py SDK for isolated analysis."
                )
            failures: list[str] = []
            ordered_attempts = [selected_attempt] if selected_attempt is not None else []
            ordered_attempts.extend(attempt for attempt in attempts if attempt != selected_attempt)
            total_capture_attempts = len(ordered_attempts)
            for capture_index, (executable, native_runtime, label, renderer) in enumerate(
                ordered_attempts, start=1
            ):
                print(
                    f"SceneLight capture {capture_index}/{total_capture_attempts}: trying {label}",
                    flush=True,
                )
                try:
                    capture = capture_runtime_assets(
                        discovery,
                        executable,
                        native_runtime=native_runtime,
                        renderer=renderer,
                    )
                    break
                except CaptureInstanceConflict:
                    raise
                except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
                    failures.append(f"{label}: {error}")
                    print(
                        f"SceneLight capture {capture_index}/{total_capture_attempts} could not "
                        f"continue: {error}",
                        flush=True,
                    )
            if capture is None:
                detail = "\n\n".join(failures)
                raise RuntimeError(
                    "SceneLight could not resolve this mod's dynamic assets with any compatible "
                    f"Ren'Py runtime.\n\n{detail}"
                )
            merge_capture(discovery, capture)

    # The analyzer may compile the copied project with a newer Ren'Py. Restore
    # every project-owned file from the source copy before native playback.
    sync_project(project_root)
    result = build_project(
        discovery,
        grid_size=grid,
        workers=workers,
        analyzer_backend=analyzer,
    )
    if discovery.scene_media and discovery.scene_analysis == "live":
        from .prepared import prepare_project_movies

        prepare_project_movies(discovery)
    preserved_cache = _preserve_analysis_cache(project_root, managed_root)
    _install_runtime_files(discovery.game_root)
    _remove_capture_bootstrap(discovery.game_root)
    legacy_live_config = discovery.game_root / "scenelight_live.json"
    if legacy_live_config.is_file():
        legacy_live_config.unlink()
    native_launcher = None
    if (
        playback_executable is not None
        and not playback_native
        and find_native_executable(managed_root) is not None
    ):
        native_launcher = install_native_launcher(managed_root, playback_executable)
    _write_install_config(
        managed_root,
        project_root=project_root,
        config=config,
        grid=grid,
        workers=workers,
        analyzer=analyzer,
        renpy_sdk=sdk_executable,
        playback_executable=playback_executable,
        playback_native=playback_native,
        native_launcher=native_launcher,
        save_backup=save_backup,
    )
    _write_launcher(project_root, managed_root, playback_executable)
    launcher = find_native_executable(managed_root)
    verification = _verify(project_root)
    attach_report = {
        "mode": "hybrid-gpu",
        "runtime_capture": bool(capture),
        "runtime_capture_cached": capture.cached if capture else None,
        "runtime_capture_errors": capture.errors if capture else [],
        "runtime_preflight": preflight_completed,
        "runtime_renderer": selected_attempt[3] if selected_attempt else None,
        "runtime_renderer_label": selected_attempt[2] if selected_attempt else None,
        "final_sprite_prebake": False,
        "source_untouched": True,
        "native_executable": str(find_native_executable(managed_root) or ""),
        "playback_executable": str(playback_executable) if playback_executable else "",
        "playback_native": playback_native,
        "playback_runtime_major": renpy_runtime_major(playback_executable),
        "native_launcher": native_launcher,
        "save_backup": save_backup,
        "skipped_sprites": verification["skipped_sprites"],
        "analysis_cache_reused": analysis_cache_reused,
        "embedded_form_cache_count": embedded_form_cache_count,
        "analysis_cache": str(preserved_cache) if preserved_cache is not None else None,
    }
    report_payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    report_payload.update(attach_report)
    result.report_path.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": verification["ok"],
        "project": str(project_root),
        "managed_project": str(managed_root),
        "source_untouched": True,
        "backup": None,
        "mode": "hybrid-gpu",
        "character_tags": discovery.character_tags,
        "launcher": str(launcher) if launcher else None,
        "scene_count": result.scene_count,
        "sprite_count": result.sprite_count,
        **attach_report,
    }


def _launch_managed(project_root: Path) -> dict[str, object]:
    managed_root = managed_project_root(project_root)
    install_path = managed_root / ".scenelight_install.json"
    if not install_path.is_file():
        raise FileNotFoundError("SceneLight is not installed for this project yet.")
    install = json.loads(install_path.read_text(encoding="utf-8"))
    synced = sync_project(project_root)
    config, config_changed = _launch_config(project_root, install)
    rebuilt = False
    if visual_sources_changed(synced) or config_changed:
        grid_value = install.get("grid", TRANSPORT_GRID_SIZE)
        grid = (int(grid_value[0]), int(grid_value[1]))
        _install_managed(
            project_root,
            config=config,
            grid=grid,
            workers=install.get("workers"),
            analyzer=str(install.get("analyzer", "auto")),
            renpy_sdk=Path(install["renpy_sdk"]) if install.get("renpy_sdk") else None,
        )
        rebuilt = True
    verification = _verify(project_root)
    if not verification["ok"]:
        raise RuntimeError(
            "The managed SceneLight copy is incomplete: "
            + ", ".join(str(item) for item in verification["missing_or_invalid"])
        )
    playback_value = install.get("playback_executable")
    playback_native = bool(install.get("playback_native", True))
    playback_executable = (
        Path(str(playback_value)).expanduser().resolve() if playback_value else None
    )
    executable = find_native_executable(managed_root)
    if not playback_native and playback_executable is not None and executable is not None:
        install_native_launcher(managed_root, playback_executable)
        executable = find_native_executable(managed_root)
    if executable is not None:
        command = [str(executable)]
        launched_executable = executable
        launched_native = True
    elif playback_executable is not None and playback_executable.is_file():
        command = renpy_runtime_command(
            playback_executable,
            managed_root,
            native_runtime=playback_native,
        )
        launched_executable = playback_executable
        launched_native = playback_native
    else:
        raise FileNotFoundError(
            "This project has no bundled Windows executable and its recorded Ren'Py playback "
            "runtime is unavailable. Install a native distribution or select its matching SDK."
        )
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=managed_root, creationflags=flags)
    return {
        "ok": True,
        "project": str(project_root),
        "managed_project": str(managed_root),
        "source_untouched": True,
        "native_executable": str(launched_executable),
        "playback_native": launched_native,
        "pid": process.pid,
        "updated_before_launch": rebuilt,
        "launcher": verification["launcher"],
    }


def main(argv: list[str] | None = None) -> int:
    from . import diagnostics

    own_session = not os.environ.get("SCENELIGHT_LOG_SESSION")
    session = (
        diagnostics.start_session("cli", command=argv or sys.argv[1:])
        if own_session
        else diagnostics.current_session()
    )
    try:
        code = _main(argv)
        if session is not None:
            session.event("cli", "Operation finished", exit_code=code)
            if own_session:
                session.update(status="succeeded" if code == 0 else "failed", exit_code=code)
        return code
    except Exception as error:
        if session is not None:
            session.exception("cli", error)
            if own_session:
                session.update(status="failed", failure=str(error))
        raise


def _main(argv: list[str] | None = None) -> int:
    _configure_utf8_output(sys.stdout)
    _configure_utf8_output(sys.stderr)
    args = _parser().parse_args(argv)
    project_root = args.project.expanduser().resolve()
    if args.command == "verify":
        result = _verify(project_root)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "launch":
        result = _launch_managed(project_root)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "remove":
        removed = remove_managed_project(project_root)
        cache_removed = False
        cache_warning: str | None = None
        try:
            cache_removed = remove_analysis_cache(project_root)
        except (OSError, ValueError) as error:
            cache_warning = str(error)
        print(
            json.dumps(
                {
                    "ok": True,
                    "project": str(project_root),
                    "removed": removed,
                    "analysis_cache_removed": cache_removed,
                    "analysis_cache_warning": cache_warning,
                    "source_untouched": True,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "unembed":
        print(json.dumps(remove_embedded(project_root), indent=2))
        return 0

    if args.command == "embed-status":
        status = developer_status(project_root)
        print(
            json.dumps(
                {
                    "ok": status.clean,
                    "project": str(project_root),
                    "installed": status.installed,
                    "clean": status.clean,
                    "files": status.files,
                    "missing": status.missing,
                    "modified": status.modified,
                    "unowned": status.unowned,
                    "refresh_required": status.refresh_required,
                    "changed_sources": status.changed_sources,
                    "installed_version": status.installed_version,
                },
                indent=2,
            )
        )
        return 0 if status.clean else 1

    config = _effective_config(project_root, args.config)
    if args.command in {"attach", "embed"}:
        preflight_embed_destination(project_root)
    elif args.command == "refresh":
        preflight_refresh_destination(project_root)
    if args.command == "scan":
        if args.runtime_review:
            payload = _scan_runtime_review(
                project_root,
                config=config,
                renpy_sdk=args.renpy_sdk,
            )
        else:
            print("SceneLight scan 1/1: inspecting project files", flush=True)
            payload = discover_project(project_root, config).summary()
        print(json.dumps(payload, indent=2))
        return 0

    result = _install_managed(
        project_root,
        config=config,
        grid=args.grid,
        workers=args.workers,
        analyzer=args.analyzer,
        renpy_sdk=args.renpy_sdk,
        reuse_embedded_cache=args.command == "refresh",
    )
    if args.command in {"attach", "embed"}:
        embedded = embed_from_managed(project_root, Path(str(result["managed_project"])))
        result = {
            **result,
            **embedded,
            "installation": "in-place",
            "source_untouched": False,
        }
        remove_managed_project(project_root)
        result["managed_project"] = None
        result["launcher"] = str(
            embedded.get("launcher") or find_native_executable(project_root) or ""
        )
    elif args.command == "refresh":
        refreshed = refresh_embedded_from_managed(
            project_root, Path(str(result["managed_project"]))
        )
        result = {
            **result,
            **refreshed,
            "installation": "in-place",
            "source_untouched": False,
        }
        remove_managed_project(project_root)
        result["managed_project"] = None
        result["launcher"] = str(
            refreshed.get("launcher") or find_native_executable(project_root) or ""
        )
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
