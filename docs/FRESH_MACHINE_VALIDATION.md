# Fresh Windows validation plan

This procedure validates the public release in a clean Windows environment
without changing the development machine. Run it only with disposable test
projects and non-proprietary fixtures.

## Recommended two-stage test

Use two independent checks because a disposable guest and the host GPU answer
different questions.

1. **Windows Sandbox: clean-user and containment check.** Start from a new
   Sandbox instance, install normal public prerequisites, extract the release,
   attach a small original Ren'Py fixture and one trusted public mod, play each,
   remove each managed copy, and close the Sandbox. This proves that no local
   development packages, caches, environment variables, or registry state are
   required.
2. **Supported physical GPU: renderer check.** Repeat the visual comparison and
   performance checks on the Windows host or another clean physical Windows
   machine with a supported GPU. A virtual GPU is useful for compatibility
   testing but is not evidence that the CUDA analyzer or a particular vendor's
   native driver path works.

For a reusable compatibility matrix, a generation-2 Hyper-V VM with a clean
Windows installation and a production checkpoint is an alternative to Windows
Sandbox. Revert to the checkpoint before each release candidate. Keep GPU
validation separate unless that VM has a documented, supported GPU assignment.

## Sandbox configuration policy

For the containment run:

- map only one dedicated input folder from the host and mark it read-only;
- place the selected release ZIP, its checksum, and test projects in that
  folder;
- for the normal online ZIP, retain networking only for the pinned Python and
  dependency bootstrap; for an optional offline ZIP, disable networking and
  confirm it visibly uses `--no-index --find-links`;
- confirm SceneLight validates the Python SHA-256 and Python Software Foundation
  signature before asking to install the SceneLight runtime;
- disable clipboard, audio input, video input, and printer redirection;
- leave no writable host folder mapped into the guest;
- enable the virtual GPU only for the compatibility run, and repeat once with
  it disabled to prove the CPU fallback remains usable; and
- copy and extract every input inside the Sandbox before running it.

The offline input set should be assembled from known sources on the host and
scanned before the test. Its release ZIP must match the published SHA-256 file.
The bundled Python installer and dependency wheelhouse must also have recorded
hashes.
Do not use an unknown mod as a security test: Ren'Py games can execute arbitrary
Python, and SceneLight does not sandbox third-party game code.

## Acceptance checklist

Record the Windows build, Python version, SceneLight version, Ren'Py version,
graphics renderer string, and whether CUDA was available. Then verify:

- SceneLight opens from the extracted release with no development checkout and
  no preinstalled Python present, explains its runtime/components, and
  asks before installing them.
- The exact dependency command is shown before installation and packages land
  only in `%LOCALAPPDATA%\SceneLight\python-env`.
- No administrator prompt, firewall prompt, service, startup item, scheduled
  task, driver, browser extension, or registry setup is requested.
- Scan performs no game-code execution and makes no change to the selected
  project.
- Before expensive analysis, the managed native Ren'Py executable completes an
  empty-request renderer preflight. A deliberately broken fixture stops at this
  point instead of wasting time on analysis.
- Every expensive background, transport, inventory, and form phase shows its
  current/total count, percentage, elapsed time, and ETA; a 1,517-form fixture
  never presents an unexplained indeterminate wait.
- The setup screen offers both **Add to this game** and **Create separate copy**.
  The first adds only the reserved, hash-owned namespace; the second creates a
  path-keyed copy under `%LOCALAPPDATA%\SceneLight\projects`.
- The Preview & Calibrator opens, reports its renderer, and displays Relit,
  Original, and Split views using the packaged production shader.
- A static background, an instant scene cut, ATL motion, multiple characters,
  an animated sprite, and a video background all work.
- The managed game launches with its own copied executable and matching Ren'Py
  engine.
- Removing the attachment deletes only its managed directory; a complete hash
  of the selected project is identical before attachment and after removal.
- Closing the Sandbox discards its Python environment, caches, managed games,
  logs, and test saves; the host input folder remains byte-identical.

Developer embedding is a separate test. Run it only against a disposable copy
of an original fixture, verify the ownership manifest, exercise refusal after
tampering with an owned file and after adding an unknown file, then confirm a
clean unembed restores the fixture's original tree hash.

## Evidence to retain

Keep only non-proprietary evidence: command output, the release checksum,
dependency audit output, before/after fixture hashes, renderer information,
timings, and screenshots of the SceneLight windows. Do not publish third-party
game art, archives, save files, usernames, absolute local paths, or environment
variables.
