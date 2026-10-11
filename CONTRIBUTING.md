# Contributing

Fixes, compatibility work, tests and documentation improvements are welcome.
Renderer changes should work across characters and projects without rules tied
to a particular game's names or artwork.

## Development setup

Use Python 3.10 or newer in a virtual environment:

```text
python -m pip install -e ".[dev,preview]"
```

Minimal Ubuntu installations also need `libegl1` for Qt/OpenGL imports.

## Before submitting a change

```text
ruff check .
ruff format --check .
pytest
bandit -r src -ll
python -m pip_audit -r requirements-preview.txt --progress-spinner off
python -m build
```

Add focused regression coverage and explain what changed, why, and how it was
verified. Renderer changes also need the relevant [Ren'Py and image comparisons](docs/TESTING.md).
Keep useful assertions and security checks intact; record any check that could
not run.

Keep game archives, extracted user art, saves, caches, private captures and local
machine paths out of commits. Documentation artwork must permit redistribution
and include its source, license and credits. See [the example credits](docs/media/CREDITS.md).

## Comments and documentation

Describe what the code does and why a reader needs to know. Keep explanations of
compatibility constraints, numerical choices and failure recovery; omit praise
and repeated assurances. For performance claims, give the workload, hardware and
measured scope. Keep historical results dated and separate from current behavior.

[Documentation index](docs/README.md) · [Security reports](SECURITY.md)
