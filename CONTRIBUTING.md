# Contributing to AgentForge

Thanks for contributing.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make verify
```

## Guidelines

- Prefer small, focused changes with tests
- Do not add web UI / SaaS surface area
- Runtime adapters must fail clearly on unsupported capabilities — never silent downgrade
- No hardcoded API keys; use env var *names* only
- Generated projects must run without an AgentForge runtime dependency

## Commit style

Use conventional commits, e.g. `feat:`, `fix:`, `docs:`.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
