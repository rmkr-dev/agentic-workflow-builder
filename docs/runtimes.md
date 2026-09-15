# Runtime Adapters

## LangGraph (primary)

Status: **working** for all IR node types used in examples.

Capabilities: compile, validate, run, resume, stream, cancel, inspect, serialize/deserialize, **durable HITL checkpoints** (`.agentforge/checkpoints.pkl`), parallel, conditional, loops, subworkflows, MCP (live stdio/SSE via `mcp` package + grants), evaluation, guardrails.

`agentforge compile workflow.yaml` prints the required-capability matrix for the chosen runtime.

## Microsoft Agent Framework

Status: **partial / honest matrix**.

Install optional extra:

```bash
pip install 'agentforge[microsoft]'
```

| Capability | Status |
|------------|--------|
| sequential / single / handoff | **supported** — real `WorkflowBuilder` chain |
| parallel fan-out/fan-in | **supported** — `add_fan_out_edges` / `add_fan_in_edges` |
| run / inspect / serialize | supported |
| resume / stream / checkpoints | partial |
| HITL / conditional / loops / subworkflows / MCP | **unsupported** — raises `UnsupportedCapabilityError` |
| package missing | all capabilities **unsupported** with install hint |

AgentForge **never** silently downgrades an unsupported Microsoft feature to LangGraph.

## LLM providers

AgentForge resolves LLM settings from environment variables only (see `.env.example`).

| Mode | When |
|------|------|
| `mock` (default) | `AGENTFORGE_LLM_MOCK=1` (default) **or** no API key |
| `live` | `AGENTFORGE_LLM_MOCK=0` **and** `AGENTFORGE_LLM_API_KEY` (or `OPENAI_API_KEY`) set |

Live calls use an OpenAI-compatible `/chat/completions` endpoint (`AGENTFORGE_LLM_BASE_URL` optional).

## Evaluation

```bash
agentforge evaluate workflow.yaml --golden tests/fixtures/golden_pass.json
agentforge evaluate workflow.yaml --llm-judge   # mock-safe unless live LLM configured
agentforge test workflow.yaml --golden path/to/golden.json
```

## Observability

```bash
agentforge run workflow.yaml --input "hi"
agentforge trace <thread_id>                 # ASCII tree (default)
agentforge trace <thread_id> --format jsonl  # OpenTelemetry-shaped JSONL spans
```
