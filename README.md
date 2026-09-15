# AgentForge

**Compile agentic intent into executable workflows.**

AgentForge is a Python-first developer tool: declarative YAML/JSON specs are parsed, validated, lowered to a canonical Workflow IR, compiled onto runtime adapters, and optionally code-generated into standalone agent repositories.

## What it is

- CLI + SDK + declarative workflow compiler + project generator
- Primary runtime: **LangGraph** (fully working)
- Secondary runtime: **Microsoft Agent Framework** (honest capability matrix — never silent downgrade)
- Local SQLite checkpoints / events
- Provider-neutral LLM config via environment variables only

## What it is not

- Not a web UI / SaaS / visual editor
- Not Cursor-dependent
- Not a hosted multi-tenant platform

## Quick start

```bash
pip install -e ".[dev]"
agentforge doctor --full
agentforge validate examples/01-single/workflow.yaml
agentforge run examples/01-single/workflow.yaml --input "Hello"
agentforge generate examples/01-single/workflow.yaml --out ./generated/single-agent
```

### SDK

```python
from agentforge import WorkflowCompiler

compiler = WorkflowCompiler()
project = compiler.generate("workflow.yaml")
print(project.path)
```

### Design from natural language

```bash
agentforge design --task "Research then write a summary with human approval" --out workflow.yaml
```

## CLI

```
agentforge init | validate | lint | compile | generate | test | run | resume
agentforge inspect | trace | evaluate | export | design | doctor | publish
```

Global flags: `--json` `--quiet` `--verbose` `--non-interactive`

## Workflow patterns

single · sequential · parallel / fan-out-fan-in · supervisor · hierarchical · handoff · reflection · conditional · bounded loops · subworkflows · agent-as-tool · HITL · evaluator

## Examples

See `examples/01-single` through `examples/09-hitl-evaluator`.

## Documentation

- [Architecture](docs/architecture.md)
- [DSL reference](docs/dsl.md)
- [Runtimes](docs/runtimes.md)
- [Security](docs/security.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache-2.0 — see [LICENSE](LICENSE).
