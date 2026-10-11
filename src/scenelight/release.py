"""Release identity and backward-compatible installation classification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from . import __version__

FIRST_PUBLIC_VERSION = "1.0.0"
RELEASE_RECORD_VERSION = 1
RUNTIME_API_VERSION = 1

ReleaseKind = Literal[
    "current",
    "upgrade",
    "downgrade",
    "different_build",
    "pre_release",
    "unrecognized",
]

_SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


@dataclass(frozen=True, slots=True)
class ReleaseRelation:
    """Describe how an installed release relates to the running package."""

    installed_version: str | None
    current_version: str
    kind: ReleaseKind
    installed_content_sha256: str | None = None
    current_content_sha256: str | None = None

    @property
    def replacement_available(self) -> bool:
        return self.kind != "current"

    @property
    def installed_label(self) -> str:
        if self.kind == "pre_release":
            return "pre-1.0 internal build"
        if self.kind == "unrecognized":
            return f"unrecognized build {self.installed_version!r}"
        return f"SceneLight {self.installed_version}"


def _semver(value: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...] | None] | None:
    match = _SEMVER.fullmatch(value.strip())
    if match is None:
        return None
    prerelease = match.group("prerelease")
    identifiers: tuple[tuple[int, int | str], ...] | None = None
    if prerelease is not None:
        identifiers = tuple(
            (0, int(token)) if token.isdigit() else (1, token.lower())
            for token in prerelease.split(".")
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        identifiers,
    )


def _compare_semver(left: str, right: str) -> int | None:
    parsed_left = _semver(left)
    parsed_right = _semver(right)
    if parsed_left is None or parsed_right is None:
        return None
    left_core = parsed_left[:3]
    right_core = parsed_right[:3]
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    left_pre = parsed_left[3]
    right_pre = parsed_right[3]
    if left_pre == right_pre:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    for left_item, right_item in zip(left_pre, right_pre, strict=False):
        if left_item == right_item:
            continue
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def classify_release(
    installed_version: object,
    *,
    current_version: str = __version__,
    installed_content_sha256: object = None,
    current_content_sha256: str | None = None,
) -> ReleaseRelation:
    """Treat manifests without product identity as explicitly pre-1.0."""

    if not isinstance(installed_version, str) or not installed_version.strip():
        return ReleaseRelation(None, current_version, "pre_release")
    installed = installed_version.strip()
    installed_fingerprint = (
        installed_content_sha256.strip().lower()
        if isinstance(installed_content_sha256, str) and installed_content_sha256.strip()
        else None
    )
    current_fingerprint = (current_content_sha256 or release_content_sha256()).lower()
    comparison = _compare_semver(installed, current_version)
    if comparison is None:
        return ReleaseRelation(
            installed,
            current_version,
            "unrecognized",
            installed_fingerprint,
            current_fingerprint,
        )
    if comparison == 0:
        kind: ReleaseKind = (
            "different_build"
            if installed_fingerprint is not None and installed_fingerprint != current_fingerprint
            else "current"
        )
        return ReleaseRelation(
            installed,
            current_version,
            kind,
            installed_fingerprint,
            current_fingerprint,
        )
    return ReleaseRelation(
        installed,
        current_version,
        "upgrade" if comparison < 0 else "downgrade",
        installed_fingerprint,
        current_fingerprint,
    )


def release_version_from_manifest(payload: object) -> str | None:
    """Read both the public field and the nested release record."""

    if not isinstance(payload, dict):
        return None
    value = payload.get("scenelight_version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    release = payload.get("release")
    if isinstance(release, dict):
        value = release.get("product_version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def release_content_sha256_from_manifest(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    release = payload.get("release")
    if not isinstance(release, dict):
        return None
    value = release.get("content_sha256")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


@lru_cache(maxsize=1)
def release_content_sha256() -> str:
    """Fingerprint the shipped executable/source content without self-reference."""

    package = Path(__file__).resolve().parent
    root = package.parents[1]
    if package != root / "src" / "scenelight":
        # A wheel lives directly in site-packages, without the checkout's src
        # directory or desktop launchers. Fingerprint its actual shipped files.
        root = package.parent
    files: list[Path] = []
    if package.is_dir():
        files.extend(
            path
            for path in package.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() in {".py", ".rpy", ".exe", ".ico"}
        )
    for name in (
        "requirements.txt",
        "requirements-preview.txt",
        "scenelight_setup.pyw",
        "scenelight_preview.pyw",
        "scenelight_sdk.py",
        "tools/bootstrap_python.ps1",
    ):
        path = root / name
        if path.is_file():
            files.append(path)
    digest = hashlib.sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def release_record() -> dict[str, object]:
    """Return the exact product and cache contracts written by new installs."""

    # Delayed imports keep this small identity module free of analyzer startup
    # cost and avoid circular imports during command-line initialization.
    from .builder import RUNTIME_MANIFEST_VERSION, TRANSPORT_CACHE_VERSION
    from .capture import CAPTURE_PIXEL_VERSION, CAPTURE_PLAN_VERSION, CAPTURE_VERSION
    from .form_maps import FORM_MAP_VERSION

    return {
        "version": RELEASE_RECORD_VERSION,
        "product_version": __version__,
        "first_public_version": FIRST_PUBLIC_VERSION,
        "runtime_api_version": RUNTIME_API_VERSION,
        "runtime_manifest_version": RUNTIME_MANIFEST_VERSION,
        "transport_algorithm": TRANSPORT_CACHE_VERSION,
        "sprite_form_version": FORM_MAP_VERSION,
        "capture_version": CAPTURE_VERSION,
        "capture_plan_version": CAPTURE_PLAN_VERSION,
        "capture_pixel_version": CAPTURE_PIXEL_VERSION,
        "content_sha256": release_content_sha256(),
    }
