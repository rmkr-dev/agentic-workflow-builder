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

AgentForge **never** silently downgrades an unsupported Microsoft feature to LangGraph.
