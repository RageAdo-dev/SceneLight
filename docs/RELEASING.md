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

Windows shows "Unknown Publisher" and a SmartScreen warning for an unsigned
executable, and that warning gets worse as more people download a new file.
Signing removes it, so treat a certificate as a release prerequisite rather
than a nicety.

Public-trust code signing keys have to live in validated hardware or a cloud
HSM, so a plain `.pfx` file is no longer accepted by CAs for new certificates.
That leaves three realistic options, priced as of September 2026:

| Option | Cost | Notes |
| --- | --- | --- |
| Azure Artifact Signing (formerly Trusted Signing), Basic | **$9.99/month**, 5,000 signatures | Cloud signing, no token. Organizations need a US/Canada/EU/UK/AU/NZ/JP/KR/SG/CH/NO/IL address and three years of verifiable history; individual developers must be in the US or Canada and validate against the Azure billing account identity. |
| Azure Artifact Signing, Premium | $99.99/month, 100,000 signatures | Same service, more signatures and certificate profiles. Additional signatures cost $0.005. |
| OV certificate plus cloud signing | **$129/year** for the certificate, plus a signing subscription from **$15/month** (SSL.com eSigner, 240 signatures) | SmartScreen reputation builds over the first weeks of downloads. A YubiKey token costs extra and cannot be used from CI. |
| EV certificate | **$349/year** (SSL.com, list price) | Immediate SmartScreen trust, hardware token or cloud HSM required. EV sole-proprietor listings start around $359/year. |

For a small private beta, Azure Artifact Signing Basic is the cheapest path at
about **$120/year**. An OV certificate with cloud signing works out around
**$310/year**. Buy EV only if you need trust on the very first download.

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

### Free signing for an open-source release

[SignPath Foundation](https://signpath.org/) signs open-source projects at no
cost. They check that the binary was built from a public repository and vouch
for that with their own certificate, which also means the signature names them
rather than you. It is the only genuinely free route to a signed Windows build,
and it requires the project to be public and built through their signing step.

## Going public

Releasing publicly changes what users can verify, so walk this list once:

1. **Decide on the source.** A public repository is required for free signing,
   community bug reports and free unlimited CI minutes. Private repositories
   spend Actions minutes and cannot use SignPath Foundation.
2. **Shrink the history first.** Demo media was committed several times while it
   was being re-rendered, which leaves roughly 800 MB in `.git`. Rewrite the
   large paths out of history before the repository is public, while a rewrite
   costs nothing and no outside clone exists. Keep a `git bundle` backup.
3. **Re-check what becomes visible.** Commit messages, `docs/history/`, test
   fixtures and issue templates all become public. Search for local paths,
   personal names and credentials before flipping the switch.
4. **Confirm the licence bundle.** MIT for SceneLight, LGPL v3 notices for
   Qt/PySide6, GPL v3 text plus the source pointer for the bundled FFmpeg, and
   the CPython, Tcl/Tk and Ren'Py notices. See `THIRD_PARTY_NOTICES.md`.
5. **Check the artwork.** The rendered examples use DDLC characters. Team
   Salvato's IP guidelines cover non-commercial fan work; if that is not the
   footing you want, replace the examples with the Ren'Py tutorial artwork.
6. **Publish the release, not just the tag.** Move the release from prerelease to
   latest once a build has survived real use, and keep the checksum asset next
   to the ZIP.

Shipping without a signature is a legitimate choice, especially for the first
public builds. Windows will warn until the file hash accumulates reputation, and
an unsigned file starts from zero again on every version. Publishing the SHA-256
next to the download lets users confirm they have the file you built.

Create the base64 text with:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('SceneLight.pfx')) |
    Set-Clipboard
```

Signing happens before hashing. Record the signed binary's SHA-256 in the
release notes, and never modify an executable after signing it.

[Compatibility results](BETA_VALIDATION.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md)
