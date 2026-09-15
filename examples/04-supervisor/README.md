# Example: 04-supervisor

Supervisor routes to workers before finishing. In mock mode, workers run in a
bounded loop until each has produced output (or hop limit), then `route=done`.

```bash
agentforge validate workflow.yaml
agentforge run workflow.yaml --input "research then write"
agentforge generate workflow.yaml --out ../../../generated/04-supervisor
```

Expect `node_outputs` to include `worker_research` and `worker_write`.
