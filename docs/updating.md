# Updating

## Versioning

AgentForge follows **SemVer** (`MAJOR.MINOR.PATCH`) as declared in `pyproject.toml`
and `agentforge.__version__`.

- **PATCH** — bug fixes, docs, CI, no IR/CLI breaking changes
- **MINOR** — new features (new CLI flags, patterns, adapters) that stay backward compatible
- **MAJOR** — breaking DSL / IR / CLI changes

See [CHANGELOG.md](../CHANGELOG.md) for release notes.

## Upgrading from source

```bash
git pull
pip install -e ".[dev]"
agentforge doctor --full
pytest -q
```

If you use optional extras, reinstall them after upgrades:

```bash
pip install -e ".[microsoft,mcp]"
```

## Upgrading a wheel / PyPI install

```bash
pip install -U 'agentforge[dev]'
# pin if needed:
pip install 'agentforge==0.1.2'
```

## Changelog process

1. Land changes on the default branch with conventional commits (`feat:`, `fix:`, `docs:`).
2. Update `CHANGELOG.md` under an `## Unreleased` or dated `## X.Y.Z` section.
3. Bump `version` in `pyproject.toml` and `agentforge/__init__.py` together.
4. Tag releases optionally: `git tag v0.1.1 && git push origin v0.1.1`.
5. GitHub Actions `build-package.yml` builds sdist/wheel on pushes to the default branch
   (and tags). Publishing to TestPyPI happens only when `TEST_PYPI_API_TOKEN` is configured
   as a repository secret — CI remains green without it.

## Migration notes (0.1.2)

- **HITL** — `agentforge run` no longer auto-approves. Pass `--auto-approve` for a
  complete CI run, or resume with `agentforge resume ... --approve/--reject`.
  Checkpoints persist under `.agentforge/checkpoints.pkl`.
- **Inputs** — `--input-file` / `--input-json` merge a JSON object into run state
  (`payload`). Use this for CVE id + cloud/IAM context.
- **inspect** — `agentforge inspect workflow.yaml` inspects the spec;
  a `run-*` thread id still inspects a run.
- **compile** — prints required-capability compatibility; unsupported runtimes raise.
- **Architect** — CVE/incident tasks compose planner + parallel specialists +
  critic + evaluator + HITL + finalizer.

## Migration notes (0.1.x)

- **MCP** — live transport requires the `mcp` package; grants remain mandatory (`granted_tools`).
- **Architect** — multi-intent design now composes HITL/evaluator onto sequential pipelines
  (writer is no longer dropped when approval keywords win).
- **Evaluate** — supports `--golden` and `--llm-judge`; `agentforge test` can take `--golden`.
- **Trace** — add `--format jsonl` for span-shaped export (ASCII remains default).
- **Microsoft adapter** — sequential/parallel run on real `WorkflowBuilder` when
  `agent-framework` is installed; unsupported features still raise clearly.
- **CLI globals** — `--json` / `--non-interactive` may appear before or after the subcommand.

## Generated projects

Regenerate after upgrading if you need IR-faithful codegen improvements
(tools, HITL gates, pattern-specific tests):

```bash
agentforge generate workflow.yaml --out ./generated/app
```

Standalone generated apps do **not** depend on the AgentForge runtime package.
