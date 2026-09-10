# Contributing to SceneLight

SceneLight accepts focused fixes, compatibility improvements, documentation,
tests, and renderer work that remains general across characters and projects.
Do not submit copyrighted game archives, extracted art, generated maps, save
files, usernames, absolute local paths, or proprietary validation captures.

## Development setup

Use Python 3.10 or newer in an isolated environment:

```text
python -m pip install -e ".[dev,preview]"
```

Before opening a pull request, run:

```text
ruff check .
ruff format --check .
pytest
bandit -r src -ll
python -m pip_audit -r requirements-preview.txt --progress-spinner off
python -m build
```

Renderer or runtime changes also require the relevant Ren'Py validation from
`VALIDATION.md`. Preserve the established SceneLight Studio output and test both
legacy and current Ren'Py generations when the change can affect either path.
Do not make a regression pass by weakening an assertion, suppressing a security
finding, or replacing the transport/form pipeline with fixed tinting.

## Pull requests

Keep a pull request scoped to one coherent problem. Explain the user-visible
behavior, the root cause, the validation performed, and any compatibility or
performance tradeoff. Add focused tests for fixes and new behavior. Generated
release archives, dependency environments, caches, and test-game copies belong
outside Git; the repository's `.gitignore` covers the standard locations.

For security-sensitive reports, follow `SECURITY.md` instead of opening a public
issue.
