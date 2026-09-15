# Release checklist

For maintainers. Keep the repository and artifacts private until the owner
approves public distribution.

## Validate

- Run [the development checks](../CONTRIBUTING.md) and [integration matrix](../VALIDATION.md).
- Complete the [fresh Windows procedure](FRESH_MACHINE_VALIDATION.md) from the built archive.
- Exercise updates from a versionless installation and a current installation.
  Verify recovery and reuse of unchanged analysis.
- Compare Preview and native rendering with the intended calibration. Record
  numerical differences, hardware, frame pacing and memory limits.
- Check archives for private game assets, generated runtime maps, saves, caches,
  local paths and debug files. Keep documentation artwork's licenses and credits.
- Confirm the SceneLight version in package metadata, the module, archive names
  and installation records agrees. Schema and surface-map versions are separate.
  Confirm behavior changes update the shipped-content fingerprint.

## Build packages

Run on Windows from the repository root:

```powershell
.\tools\build_release_zip.ps1 -CompatibilityRuntime <verified-renpy-runtime>
.\tools\build_release_zip.ps1 -Source
```

Build with Python 3.11 including Tcl/Tk. The Windows package contains
`SceneLight.exe` and a private interpreter with pinned dependencies. The source
archive retains the Python and batch entry points. `-DesktopRuntime <directory>`
can reuse a runtime built by `tools/bundle_runtime.py`; its requirements must match.

For an offline package, also provide `-PythonInstaller <installer>` and
`-Wheelhouse <pinned-wheels>`. The builder must reject incomplete bundles, invalid
Python signatures and incompatible runtime versions. Distribute the ZIP checksums
alongside the packages, wheel and source distribution.

The current compatibility runtime is **Ren'Py 7.7.1**. Its SDK ZIP SHA-256 is:

```text
767fb21aed2e689bfba04e2a7db0e30003f0b6825538cca5ab66a1ab4dbb8d2e
```

Keep the version and digest aligned with `src/scenelight/compatibility.py`.
Do not substitute 7.8.7: its texture-finalizer leak was reproduced. Preserve the
runtime executables, `lib/`, `module/`, `renpy/` and original `LICENSE.txt`.

## GitHub distribution

**Build release ZIP** can be run manually without creating a release. A pushed
`vX.Y.Z` tag runs the same build and creates a **draft prerelease**. Review its
checksums, CI and validation record before publishing.

GitHub Actions downloads expire. Keep the current download link pointed at a
valid package; use a permanent release asset for public distribution. Public
visibility and publication remain separate owner decisions.

## Native launcher

The desktop entry point is separate from the installed-game launcher. Rebuild
its checked-in binary with MinGW-w64:

```text
gcc -O2 -Wall -Wextra -Werror -municode -mwindows -static-libgcc -s tools/desktop_launcher.c -o src/scenelight/assets/scenelight-desktop.exe -luser32
```

Run `SceneLight.exe --diagnostics <report.json>` from a complete package to check
the bundled interpreter, GUI imports, Tcl/Tk and dependency routing. Test Setup
and Preview interactively as well.

Build from a Visual C++ Developer Command Prompt:

```text
cl /nologo /O2 /W4 /DUNICODE /D_UNICODE tools\native_launcher.c /Fe:src\scenelight\assets\scenelight-launcher.exe /link /SUBSYSTEM:WINDOWS user32.lib /Brepro
```

Review warnings, run `tests/test_launch_safety.py` and record the binary hash.
If signing is used, sign before hashing and do not modify the binary afterward.
Never instruct users to disable SmartScreen or antivirus.

[Compatibility results](BETA_VALIDATION.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md)
