# Security and privacy

SceneLight analyzes only the Ren'Py project a user selects. It does not request
administrator privileges, install a service or startup item, add telemetry, or
upload game art. Dependency installation requires explicit confirmation, and
the exact `pip` command and output remain visible in the setup log. When a
compatible Python is unavailable, the online release downloads the pinned
Python installer from `python.org`; an optional offline release may bundle the
same installer. Both paths verify its exact SHA-256 checksum and its valid
Python Software Foundation Authenticode signature before installing the
SceneLight runtime under `%LOCALAPPDATA%\SceneLight\bootstrap-python` for the
current user. It is not added to PATH and does not claim file associations.

Dependencies are installed into `%LOCALAPPDATA%\SceneLight\python-env`, not the
global Python package set. Packaging tools and direct runtime dependencies are
version-pinned and checked during release validation against published
vulnerability data. The Python source also passes a medium-and-high-severity
static security scan; any narrowly scoped suppression must be reviewed with its
documented input restrictions.

An optional offline release contains a pinned `wheelhouse`; a source checkout
can use an adjacent `wheelhouse` for the same behavior. Both switch dependency
installation to pip's `--no-index --find-links` mode. Users should verify the
release checksum supplied by the publisher before running any package.

The game runtime and renderer contain no network client. Setup exposes three
network-capable workflows: the confirmed pinned Python download described
above, a confirmed `python -m pip install ...` operation for published
dependencies, and the pinned, SHA-256-verified Ren'Py compatibility download from
`renpy.org` when it is not already bundled. SceneLight has no advertising, automatic updater, service,
driver, or startup persistence. It passes subprocess arguments as lists and
never executes game-supplied text through a command shell. Video decoding and
encoding likewise use an argument list for the locally installed FFmpeg
executable. SceneLight never asks a user to disable antivirus, SmartScreen, a
firewall, or another operating-system protection.

The default separate-copy workflow treats the selected game/mod as read-only
and writes runtime, analysis, cache, and launcher files into a path-keyed
managed copy under the user's local application data. Removal validates the
copy's ownership marker and managed-root boundary before deletion. Release ZIPs
include a SHA-256 checksum. The shared dependency environment can be removed by
closing SceneLight and deleting `%LOCALAPPDATA%\SceneLight\python-env`; installed
game runtimes do not import from it. The release workflow and all installer/runtime
source are included in this private repository for review. Public availability
requires a separate owner decision.

**Add to this game** and the separately labeled mod-author integration are the
explicit in-place exceptions to the read-only source rule. They refuse to
install over an unowned reserved namespace or ownership manifest and record
every added file by SHA-256. Removal validates all paths, hashes, and unexpected
files before the first deletion; any ambiguity causes a refusal. SceneLight does
not claim ownership of or remove a file that existed before integration.
Compiler-produced `.rpyc` siblings of its own `.rpy` files are the only
recognized derived files. When legacy normal-executable support requires a
launcher replacement, SceneLight first records and preserves the exact original
executable and provides a verified recovery path.

## Trust boundary

SceneLight cannot certify the safety of a third-party Ren'Py game. A game can
contain Python code and its bundled executable can do anything allowed to that
user account. The read-only scan does not execute game code. Archive-backed or
runtime-only image discovery can evaluate project declarations only inside the
isolated managed copy under a separately selected Ren'Py analysis SDK. **Launch
game** then deliberately starts the mod's own copied executable. Users should
obtain mods from trusted publishers and inspect unfamiliar projects before
running them.

The selected source folder is not a sandbox. SceneLight's safety property is
that its normal player workflow does not write to it: files are copied into a
path-keyed managed directory first, and removal is limited to a verified child
of SceneLight's application-data root. Developer embedding is visibly separate
because it intentionally adds a reserved, hash-tracked namespace to source.

## Reporting a vulnerability

For a sensitive report, use the repository's GitHub private vulnerability
reporting feature when available. For a non-sensitive hardening issue, open a
normal GitHub issue with reproduction steps. Do not attach proprietary game
archives or character/background art; a minimal original fixture is enough.

Only the latest release receives security fixes. A report should include the
SceneLight version, operating system, Ren'Py version, the operation being run,
and the smallest log excerpt needed to reproduce the problem.
