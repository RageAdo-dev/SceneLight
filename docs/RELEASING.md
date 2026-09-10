# Releasing

The current repository and its artifacts must remain private. Run CI and build
draft candidates there; public availability requires a separate owner decision.

1. Run `ruff check .`, `ruff format --check .`, `pytest`, `bandit -r src -ll`, the dependency
   vulnerability audit, and `python -m build`.
   Also upgrade one clean versionless/pre-1.0 direct installation and one current
   separate copy. Confirm the explicit prompt, rollback/source safety, and a
   second unchanged run that reuses compatible analysis.
2. Run the Ren'Py validation matrix documented in `VALIDATION.md`.
3. Run the Preview & Calibrator with the default profile and confirm that
   Relit matches the game capture, Original is unchanged, and split comparison
   compiles with the production shader hash.
4. Inspect the archive; it must contain no game assets, generated atlases,
   form maps, `.rpa` files, validation captures, or backups. A Windows offline
   release may contain only the audited Ren'Py 7 compatibility runtime passed
   explicitly to the release builder, including its original `LICENSE.txt`.
5. Search the release tree for developer-machine paths, private assets,
   temporary captures, and development-only wording.
   Confirm `pyproject.toml`, `scenelight.__version__`, the archive name, and both
   generated install manifests report the same public version.
6. Exercise the online ZIP with `SCENELIGHT_COMPONENT_ROOT` redirected to a
   temporary folder; install dependencies there, then prove the folder can be
   removed without changing the selected test project or global Python.
7. Run a vulnerability audit against the fully resolved private environment
   and a medium/high static source scan with no inline suppressions; update any
   affected pin or code and repeat the complete matrix before release.
8. Create an annotated `vX.Y.Z` tag.
9. On Windows, run `.\tools\build_release_zip.ps1 -CompatibilityRuntime <audited-renpy-7-runtime>`
   for the normal Windows ZIP. It includes the verified runtime; Python and player
   dependencies are downloaded on first setup when needed.
   Build the optional offline ZIP with
   `.\tools\build_release_zip.ps1 -PythonInstaller <official-installer> -Wheelhouse <pinned-wheels> -CompatibilityRuntime <audited-renpy-7-runtime>`.
   The builder must reject a partial bundle, an invalid Authenticode signature,
   a signer other than the Python Software Foundation, or a compatibility
   runtime that is incomplete or not Ren'Py 7. Upload each readable, versioned
   ZIP and `.sha256` file alongside the Python wheel/sdist. Use `-Source` only
   when a separately labeled source snapshot is needed.
10. State supported Ren'Py versions and link Team Salvato's current guidelines
   when describing DDLC use.

The tag workflow downloads and verifies the pinned runtime, builds the same
Windows ZIP plus a source ZIP, and creates a draft prerelease. Review its CI,
artifact hashes and validation notes before publishing the beta. Keep the
workflow visible and reproducible. If a native Windows
executable is introduced, state plainly that unsigned/new binaries can show an
"unrecognized app" warning; never instruct users to disable SmartScreen or
antivirus. Once signing is configured, sign before hashing and do not alter the
signed executable afterward.

The compatibility launcher binary is built from `tools/native_launcher.c` with
the Visual C++ toolchain. From a Developer Command Prompt, use:

```text
cl /nologo /O2 /W4 /DUNICODE /D_UNICODE tools\native_launcher.c /Fe:src\scenelight\assets\scenelight-launcher.exe /link /SUBSYSTEM:WINDOWS user32.lib /Brepro
```

Review the compiler warnings, rerun `tests/test_launch_safety.py`, and record the
resulting binary hash before packaging.

GitHub rejects individual Git objects larger than 100 MiB. SceneLight's public
source should be far below that limit; generated project data belongs only in
the user's local project.

Before signing a release candidate, also verify that:

- every expensive scan phase presents current/total progress, percentage,
  elapsed time, and ETA rather than an indeterminate wait;
- player attachment completes the native Ren'Py empty-request preflight before
  any long background or sprite analysis;
- Intel, AMD, and NVIDIA systems use Ren'Py's supported GPU renderer for live
  gameplay, while optional first-time CUDA analysis remains clearly labeled as
  NVIDIA-only; and
- the exact CPU fallback remains available and output-equivalent when optional
  acceleration is unavailable;
- the release fingerprint changes when shipped runtime behavior changes, while
  unchanged input and matching capture/transport/form contracts reuse the
  external analysis cache; and
- scene transitions never call `renpy.screenshot_to_bytes`; before/after sides
  containing lit sprites are flattened on the GPU and replayed through a real
  dissolve or wipe without a story-advance hitch.

The pinned compatibility runtime for the current release is the official Ren'Py 7.7.1 SDK
from <https://www.renpy.org/release/7.7.1>. The downloaded SDK ZIP must have
SHA-256 `767fb21aed2e689bfba04e2a7db0e30003f0b6825538cca5ab66a1ab4dbb8d2e`.
Do not substitute 7.8.7: the lifecycle audit reproduced a texture-finalizer leak
on that runtime. Keep this version and digest aligned with `compatibility.py`.
The release copy may omit launcher samples, templates, documentation, and the
SDK UI, but it must preserve `renpy.exe`, `renpy-32.exe`, `renpy.py`, `lib/`,
`module/`, `renpy/`, and `LICENSE.txt` without modifying their contents.
