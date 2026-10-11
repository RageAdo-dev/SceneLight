# Security and privacy

SceneLight processes the selected project locally. It does not upload game art
or collect telemetry. Its game runtime makes no network requests.

## Downloads and storage

Setup asks before downloading required components. It can download Python from
`python.org`, packages through `pip`, and the compatibility runtime from
`renpy.org`. Python and Ren'Py downloads have pinned SHA-256 checks; the Python
installer must also have a valid Python Software Foundation signature.

Components stay under `%LOCALAPPDATA%\SceneLight`. Setup does not require
administrator access, add Python to PATH, claim file associations, or install a
service, driver or startup task. Dependency commands and their output are visible
in the activity log. Offline packages use a local wheelhouse without a package index.

## Game files and removal

**Create separate copy** leaves the selected source folder unchanged. SceneLight
tracks the copy's ownership and checks its storage boundary before removing it.

**Add to this game** and the developer integration write a reserved runtime
folder and ownership manifest. Updates and removal check paths, hashes and
unexpected files first. Legacy launcher replacement preserves the original
executable and recovery data. Save backups are kept for in-place changes.

The shared dependency environment can be removed after closing SceneLight by
deleting `%LOCALAPPDATA%\SceneLight\python-env`. Installed game runtimes do not
import from that environment.

## Using games and sharing logs

Only use games you trust: preparing lighting can run the game's code.
Keep your security software enabled, and review logs for personal paths before sharing.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature when available. Do not put
sensitive details in a public issue. Include the SceneLight and Ren'Py versions,
OS, affected operation and a minimal reproduction using original assets.
Ordinary non-sensitive hardening issues can use the normal issue tracker.

[Validation process](docs/TESTING.md) · [Dependency and artwork notices](THIRD_PARTY_NOTICES.md)
