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

The desktop entry point and the launcher installed into games are separate
binaries. Rebuild both checked-in binaries with MinGW-w64:

```text
python tools/build_desktop_launcher.py
```

The script writes `tools/desktop_launcher.rc` and `tools/native_launcher.rc` from
the packaged version, compiles them with `windres` and links them into
`src/scenelight/assets/scenelight-desktop.exe` and
`src/scenelight/assets/scenelight-launcher.exe`. Windows file properties then
report the product name, version, copyright holder and project URL for both.
Keep `windres` and `gcc` on `PATH`, or pass their paths as arguments.

Run `SceneLight.exe --diagnostics <report.json>` from a complete package to check
the bundled interpreter, GUI imports, Tcl/Tk and dependency routing. Test Setup
and Preview interactively as well.

Review warnings, run `tests/test_launch_safety.py` and `tests/test_desktop.py`,
and record the binary hashes. The link step omits the PE timestamp, so the same
sources reproduce the same bytes and a recorded hash still matches after a
rebuild.
If signing is used, sign before hashing and do not modify the binary afterward.
Never instruct users to disable SmartScreen or antivirus.

## Code signing

Unsigned builds can show an unknown publisher warning. Signing identifies the
publisher; it does not guarantee that Windows will suppress reputation warnings.
Choose a signing provider and verify its current requirements before purchasing.
Sign before producing the final checksums.

To sign in CI, add two repository secrets and the workflow signs both launchers
before the ZIP is assembled and fails the build if the signature is not valid:

- `WINDOWS_CERT_PFX` — the `.pfx` file, base64 encoded.
- `WINDOWS_CERT_PASSWORD` — its password.

That path only applies to certificates you can import as a `.pfx`. For Azure
Artifact Signing, set these instead and the workflow shells out to `signtool`
with the Artifact Signing dlib:

- `TRUSTED_SIGNING_ACCOUNT` — the Artifact Signing account name.
- `TRUSTED_SIGNING_CERT_PROFILE` — the certificate profile name.
- `TRUSTED_SIGNING_ENDPOINT` — optional; defaults to
  `https://eus.codesigning.azure.net/`.
- `TRUSTED_SIGNING_DLIB` — optional path to `Azure.CodeSigning.Dlib.dll` when it
  is not installed under `Program Files`.
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — a service
  principal with the Trusted Signing Certificate Profile Signer role.

Install the Trusted Signing client tools on the runner before the signing step;
the workflow searches for the dlib and stops with an explanation if it is
missing. Microsoft documents the client tools and the required Windows SDK
version in [Sign files with Artifact Signing](https://learn.microsoft.com/en-us/azure/trusted-signing/how-to-signing-integrations).

## Going public

Keep the repository private until the owner authorizes changing visibility.
Before publication, review current files and Git history for credentials, private
assets and local diagnostic data. Keep the artwork credits and third-party
licenses with the package. Documentation examples use the credited Ren’Py tutorial
artwork; tester game assets must not be included.

Publish the tested ZIP and its SHA-256 together. A tag alone is not a downloadable
Windows package. Keep prerelease status until the intended release checks and
tester runs are complete. History rewrites are a separate maintenance operation
and require an explicit request and a recoverable backup.

[Compatibility results](BETA_VALIDATION.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md)
