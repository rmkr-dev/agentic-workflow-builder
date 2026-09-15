# AgentForge

**Compile agentic intent into executable workflows.**

AgentForge is a Python-first developer tool: declarative YAML/JSON specs are parsed, validated, lowered to a canonical Workflow IR, compiled onto runtime adapters, and optionally code-generated into standalone agent repositories.

Repository: [rmkr-dev/agentic-workflow-builder](https://github.com/rmkr-dev/agentic-workflow-builder)

## What it is

- CLI + SDK + declarative workflow compiler + project generator
- Primary runtime: **LangGraph** (fully working)
- Secondary runtime: **Microsoft Agent Framework** (honest capability matrix — never silent downgrade)
- Live **MCP** client (stdio/SSE) with explicit tool grants
- Golden-file / schema evaluation + optional LLM-as-judge
- Local SQLite checkpoints / events + JSONL / OTel-shaped traces
- Provider-neutral LLM config via environment variables only

## What it is not

- Not a web UI / SaaS / visual editor
- Not Cursor-dependent
- Not a hosted multi-tenant platform

## Install

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Optional extras:

```bash
pip install 'agentforge[microsoft]'   # Microsoft AF sequential/parallel
pip install 'agentforge[mcp]'         # MCP SDK (also in [dev])
pip install 'agentforge[otel]'        # optional OpenTelemetry API
```

See [docs/setup.md](docs/setup.md) for prerequisites, env vars, and verification.

## Quick start

```bash
agentforge doctor --full
agentforge validate examples/12-security-incident/workflow.yaml
agentforge run examples/12-security-incident/workflow.yaml \
  --input-file examples/12-security-incident/input.json --auto-approve --non-interactive
agentforge generate examples/01-single/workflow.yaml --out ./generated/single-agent
```

### LLM mode (mock vs live)

By default AgentForge runs in **mock** mode (`AGENTFORGE_LLM_MOCK=1`) so CI and local
examples stay deterministic. To use a live OpenAI-compatible provider:

```bash
export AGENTFORGE_LLM_MOCK=0
export AGENTFORGE_LLM_API_KEY=sk-...
# optional: AGENTFORGE_LLM_BASE_URL, AGENTFORGE_LLM_MODEL, AGENTFORGE_LLM_PROVIDER
agentforge run examples/01-single/workflow.yaml --input "Hello"
```

`run` and `doctor` always print `mode=mock|live` (and include it in `--json` output).
See `.env.example` for the full variable list. `OPENAI_API_KEY` is accepted as a fallback.

### SDK

```python
from agentforge import WorkflowCompiler

compiler = WorkflowCompiler()
project = compiler.generate("workflow.yaml")
print(project.path)
```

### Design from natural language

Multi-intent tasks compose patterns (research + write + approval keep all implied agents).
CVE / incident wording seeds planner + parallel specialists + critic + approval:

```bash
agentforge design --task "Analyze a CVE with parallel vulnerability, cloud, and IAM specialists, critic review, quality evaluation, and human approval before remediation" --out workflow.yaml
agentforge validate workflow.yaml
```

The worked example is [`examples/12-security-incident`](examples/12-security-incident/README.md).

## CLI

```
agentforge init | validate | lint | compile | generate | test | run | resume
agentforge inspect | trace | evaluate | export | design | doctor | publish
```

Global flags: `--json` `--quiet` `--verbose` `--non-interactive`

These may appear **before or after** the subcommand:

```bash
agentforge --non-interactive run examples/01-single/workflow.yaml
agentforge run examples/01-single/workflow.yaml --non-interactive
agentforge --json doctor
```

Full workflows: [docs/usage.md](docs/usage.md).

### Evaluate / trace

```bash
agentforge evaluate examples/01-single/workflow.yaml --golden tests/fixtures/golden_pass.json
agentforge run examples/01-single/workflow.yaml --input "hi"
agentforge inspect examples/01-single/workflow.yaml
agentforge trace <thread_id> --format jsonl
```

## Workflow patterns

single · sequential · parallel / fan-out-fan-in · supervisor · hierarchical · handoff · reflection · conditional · bounded loops · subworkflows · agent-as-tool · HITL · evaluator

## Examples

| Example | Focus |
|---------|--------|
| `01`–`09` | Core patterns (single → HITL/evaluator) |
| `10-mcp` | Live MCP stdio echo + explicit grants |
| `11-security` | Fail-closed `default_deny` / ungated CLI |
| **`12-security-incident`** | **Full-flow CVE pipeline** (parallel specialists, critic, HITL resume, evaluate, generate) |

## Documentation

- [Setup](docs/setup.md)
- [Usage](docs/usage.md)
- [Updating](docs/updating.md)
- [Architecture](docs/architecture.md)
- [DSL reference](docs/dsl.md)
- [Runtimes](docs/runtimes.md)
- [Security](docs/security.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

Apache-2.0 — see [LICENSE](LICENSE).
