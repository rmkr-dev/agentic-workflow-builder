# Contributing to AgentForge

Thanks for contributing.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# optional: pip install -e ".[microsoft]"
agentforge doctor --full
pytest -q
```

See [docs/setup.md](docs/setup.md) and [docs/updating.md](docs/updating.md).

## Guidelines

- Prefer small, focused changes with tests
- Do not add web UI / SaaS surface area
- Runtime adapters must fail clearly on unsupported capabilities — never silent downgrade
- No hardcoded API keys; use env var *names* only
- Generated projects must run without an AgentForge runtime dependency
- Keep `CHANGELOG.md` and version bumps in sync (`pyproject.toml` + `agentforge/__init__.py`)

## Commit style

Use conventional commits, e.g. `feat:`, `fix:`, `docs:`.

## CI

Push/PR to `main` runs `.github/workflows/ci.yml` (lint, pytest, doctor, examples).
Pushes to `main` / tags also run `.github/workflows/build-package.yml` (sdist/wheel artifacts).

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
