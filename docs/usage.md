# Usage

Global flags (`--json`, `--quiet`, `--verbose`, `--non-interactive`) may appear
**before or after** the subcommand.

## Validate & lint

```bash
agentforge validate examples/02-sequential/workflow.yaml
agentforge lint examples/02-sequential/workflow.yaml
agentforge --json validate examples/02-sequential/workflow.yaml
```

## Compile & export

```bash
agentforge compile examples/01-single/workflow.yaml --out .agentforge/ir.json
agentforge export examples/01-single/workflow.yaml --format mermaid
agentforge export examples/01-single/workflow.yaml --format json --out ir.json
```

## Run / resume / inspect

```bash
agentforge run examples/01-single/workflow.yaml --input "Hello" --non-interactive
# Capture thread_id from JSON for inspect/trace/resume:
agentforge --json run examples/09-hitl-evaluator/workflow.yaml --input "draft" --non-interactive
agentforge inspect <thread_id>
agentforge resume examples/09-hitl-evaluator/workflow.yaml --thread-id <id> --approve
```

## Trace (ASCII or JSONL)

```bash
agentforge trace <thread_id>                 # ASCII tree (default)
agentforge trace <thread_id> --format jsonl  # OpenTelemetry-shaped JSONL spans
agentforge --json trace <thread_id>          # raw events JSON
```

## Design from natural language

Multi-intent tasks compose (research + write + approval keep all implied agents):

```bash
agentforge design --task "Research then write a summary with human approval" --out workflow.yaml
agentforge validate workflow.yaml
```

## Evaluate

Heuristics always run. Golden files and optional LLM-as-judge:

```bash
agentforge evaluate examples/01-single/workflow.yaml \
  --golden tests/fixtures/golden_pass.json
agentforge evaluate examples/01-single/workflow.yaml --llm-judge
agentforge test examples/01-single/workflow.yaml --golden tests/fixtures/golden_pass.json
```

Exit code is non-zero when evaluation fails.

## Generate standalone projects

```bash
agentforge generate examples/03-parallel/workflow.yaml --out ./generated/parallel
cd ./generated/parallel
pip install -e ".[dev]"
pytest -q
python -m workflow_app.main "hello"
```

Generated projects mention the workflow’s agents/tools in docs and ship pattern-specific tests.

## Doctor

```bash
agentforge doctor
agentforge doctor --full
agentforge --json doctor --full
```

## MCP example

```bash
pip install -e ".[dev]"   # includes mcp
agentforge validate examples/10-mcp/workflow.yaml
agentforge run examples/10-mcp/workflow.yaml --input "hello mcp" --non-interactive
```

## Security fail-closed demo

```bash
agentforge run examples/11-security/workflow.yaml --input "probe" --non-interactive
# expect FAILED / non-zero exit — ungated CLI blocked by default_deny
```

## Microsoft Agent Framework

```bash
pip install 'agentforge[microsoft]'
agentforge run examples/02-sequential/workflow.yaml --runtime microsoft --input "hi"
agentforge run examples/03-parallel/workflow.yaml --runtime microsoft --input "fan"
```

Unsupported patterns (e.g. reflection, HITL) raise `UnsupportedCapabilityError` — never silent downgrade.

## SDK

```python
from agentforge import WorkflowCompiler

compiler = WorkflowCompiler()
ir = compiler.compile("workflow.yaml")
project = compiler.generate(ir, output_dir="./generated/my-wf")
print(project.path)
```
