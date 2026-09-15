# Setup

## Prerequisites

- Python **3.11+** (3.11–3.13 tested)
- `pip` and a virtual environment recommended
- Optional: [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) for the secondary runtime
- Optional: [MCP Python SDK](https://pypi.org/project/mcp/) for live MCP stdio/SSE (included in `[dev]`)

No live LLM API key is required for local development or CI. AgentForge defaults to **mock** mode.

## Install (editable / from source)

```bash
git clone https://github.com/rmkr-dev/agentic-workflow-builder.git
cd agentic-workflow-builder
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
```

### Optional extras

```bash
pip install -e ".[microsoft]"   # Microsoft AF sequential/parallel
pip install -e ".[mcp]"         # MCP SDK only (already in [dev])
pip install -e ".[otel]"        # OpenTelemetry API (optional span bridge)
pip install -e ".[all]"         # microsoft + mcp + otel + dev
```

### Install from a built wheel

```bash
pip install dist/agentforge-*.whl
# or with extras:
pip install 'agentforge[microsoft,mcp]'
```

## Environment variables

Copy `.env.example` and export only what you need. **Never commit secrets.**

| Variable | Purpose | Default |
|----------|---------|---------|
| `AGENTFORGE_LLM_MOCK` | `1` = mock responses (CI/local) | `1` |
| `AGENTFORGE_LLM_API_KEY` | API key for live mode | unset |
| `OPENAI_API_KEY` | Fallback key if AgentForge key unset | unset |
| `AGENTFORGE_LLM_PROVIDER` | Logical provider name | `openai` |
| `AGENTFORGE_LLM_MODEL` | Model id | `gpt-4o-mini` |
| `AGENTFORGE_LLM_BASE_URL` | OpenAI-compatible base URL | provider default |
| `AGENTFORGE_EVAL_LLM_JUDGE` | Enable LLM-as-judge in evaluate | `0` |
| `AGENTFORGE_EVAL_GOLDEN` | Default golden-file path | unset |
| `AGENTFORGE_DATA_DIR` | SQLite runs + durable HITL checkpoints | `.agentforge` |
| `AGENTFORGE_NVD_HTTP` | `1` = try live NVD REST in `nvd_lookup` | unset |
| `AGENTFORGE_NVD_FIXTURE` | Extra CVE JSON catalog path | unset |

Live mode requires `AGENTFORGE_LLM_MOCK=0` **and** an API key.

## Verify installation

```bash
agentforge doctor --full
agentforge validate examples/01-single/workflow.yaml
agentforge run examples/01-single/workflow.yaml --input "Hello" --non-interactive
agentforge validate examples/12-security-incident/workflow.yaml
pytest -q
```

Expected: doctor reports `ok`, validate prints no errors, run completes in mock mode, pytest is green.

## Troubleshooting

- **`microsoft-agent-framework` missing** — optional; install with `pip install 'agentforge[microsoft]'` or keep using `runtime: langgraph`.
- **MCP live calls fail** — install `mcp` (`pip install 'agentforge[mcp]'` or `[dev]`) and run from the repo root so `examples/mcp_echo_server.py` resolves.
- **Unicode / encoding on Windows** — the CLI reconfigures stdout to UTF-8; prefer a modern terminal.
