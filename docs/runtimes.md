# Runtime Adapters

## LangGraph (primary)

Status: **working** for all IR node types used in examples.

Capabilities: compile, validate, run, resume, stream, cancel, inspect, serialize/deserialize, checkpoints, HITL, parallel, conditional, loops, subworkflows, MCP (granted stub), evaluation, guardrails.

## Microsoft Agent Framework

Status: **partial / honest matrix**.

| Capability | Status |
|------------|--------|
| sequential / handoff / parallel fan-in-out / conditional | supported when `agent-framework` installed |
| run / inspect / serialize | supported (deterministic bridge if AF API differs) |
| resume / stream / HITL / checkpoints | partial |
| loops / subworkflows / MCP grants | **unsupported** — raises `UnsupportedCapabilityError` |
| package missing | all capabilities **unsupported** with install hint |

Install optional extra:

```bash
pip install 'agentforge[microsoft]'
```

## LLM providers

AgentForge resolves LLM settings from environment variables only (see `.env.example`).

| Mode | When |
|------|------|
| `mock` (default) | `AGENTFORGE_LLM_MOCK=1` (default) **or** no API key |
| `live` | `AGENTFORGE_LLM_MOCK=0` **and** `AGENTFORGE_LLM_API_KEY` (or `OPENAI_API_KEY`) set |

Live calls use an OpenAI-compatible `/chat/completions` endpoint (`AGENTFORGE_LLM_BASE_URL` optional).

AgentForge **never** silently downgrades an unsupported Microsoft feature to LangGraph.

