# Example 12 — Real-world CVE / security-incident pipeline

This is the **full flow** for using AgentForge as a developer tool to build a
complicated multi-agent system: not a toy chatbot, a security-team workflow.

**Intent (English):** given a CVE ID plus optional cloud inventory and IAM
context, research the vulnerability, analyze exposure and identity impact in
parallel, critique the draft, score it, pause for a human, then emit a
structured risk report. Remediation actions are empty until approval.

Target audience: a human or a coding agent following copy-paste commands.

Run commands from the **repository root** unless noted. Mock LLM is the default
(`AGENTFORGE_LLM_MOCK=1`); no API keys required.

## What this spec demonstrates

1. Planner agent — decompose the CVE task
2. Parallel specialists: NVD-like lookup, cloud exposure, IAM impact
3. Join / fan-in
4. Bounded critic / reflection loop
5. Evaluator / quality gate (JSON Schema of the report)
6. Human approval before remediation actions are finalized
7. Finalizer + structured JSON report
8. Policies: budget, timeout, `default_deny`, explicit tool grants
9. Observability: SQLite events + `trace --format jsonl`
10. Optional MCP tool grant (in-repo echo server declared; live stdio is
    `examples/10-mcp`. This graph uses deterministic `ticket_note` so Windows
    pytest/CI without a real stderr fileno still complete. Swap the
    `ticket_note` node to `tool: mcp_echo` to exercise live MCP here.)

## 1. Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
agentforge doctor --full
```

Credentials (only if you later switch off mock mode): copy `.env.example` and
export `AGENTFORGE_LLM_API_KEY`. Never commit secrets.

## 2. Optional: seed a spec from English (`init` / `design`)

`init` scaffolds a named folder. `design` composes a CVE-shaped graph when the
task includes **CVE / incident / vulnerability** plus approval / parallel /
critic language.

```bash
agentforge init cve-seed --pattern hitl --dir /tmp/cve-seed

agentforge design --task "Analyze a CVE with parallel vulnerability, cloud, and IAM specialists, critic review, quality evaluation, and human approval before remediation" --out /tmp/cve-designed.yaml
agentforge validate /tmp/cve-designed.yaml
```

Keywords that trigger the incident composer: `cve`, `incident`, `vulnerability`,
`security analysis`, `cloud exposure`, `iam analyst` / `iam impact`, plus the
usual `approval` / `parallel` / `critic` / `evaluat` terms.

Then **edit YAML** (this directory is the edited, production-shaped spec):
agents, explicit TOOL nodes, MCP grant, policies, HITL message, `state_schema`,
`evaluation.output_schema`.

## 3. Inspect / validate / lint

```bash
agentforge inspect examples/12-security-incident/workflow.yaml
agentforge validate examples/12-security-incident/workflow.yaml
agentforge lint examples/12-security-incident/workflow.yaml
agentforge --json inspect examples/12-security-incident/workflow.yaml
```

From this folder you can omit the path (`workflow.yaml` is the default for
validate/lint/compile/run; `inspect` also defaults to `./workflow.yaml`).

## 4. Compile (runtime compatibility)

LangGraph is required for HITL + loops + MCP. Compile prints the capability
matrix. Microsoft AF must **fail closed** (no silent downgrade):

```bash
agentforge compile examples/12-security-incident/workflow.yaml --out .agentforge/cve-ir.json
# expect: runtime compatibility: langgraph N/N required supported

# This should error (HITL/loops/MCP unsupported on microsoft):
agentforge compile examples/12-security-incident/workflow.yaml --runtime microsoft --out /tmp/cve-ms.json
```

## 5. Run with mock LLM (CI / default)

**Full run (skips HITL)** — use this in CI or when you only need the report:

```bash
agentforge run examples/12-security-incident/workflow.yaml \
  --input-file examples/12-security-incident/input.json \
  --auto-approve --non-interactive
```

`--input-file` is the input contract (`cve_id`, `cloud`, `identity`). `--input`
alone is only a string; structured jobs should use `--input-file` or
`--input-json`.

## 6. HITL pause + resume (the real approval path)

Default **does not** auto-approve. Capture `thread_id` from JSON:

```bash
agentforge --json run examples/12-security-incident/workflow.yaml \
  --input-file examples/12-security-incident/input.json \
  --non-interactive
# status=WAITING_FOR_APPROVAL  thread=run-........

agentforge inspect <thread_id>
agentforge resume examples/12-security-incident/workflow.yaml --thread-id <thread_id> --approve
# or:  --reject   → report.remediation_actions stays empty
```

Checkpoints live under `.agentforge/` (`runs.db` + `checkpoints.pkl`) so resume
works in a **new process**. Keep `AGENTFORGE_DATA_DIR` if you override it.

## 7. Trace (ASCII + JSONL)

```bash
agentforge trace <thread_id>
agentforge trace <thread_id> --format jsonl
agentforge --json trace <thread_id>
```

## 8. Evaluate (schema + golden)

Evaluate auto-approves by default so it can score a complete report:

```bash
agentforge evaluate examples/12-security-incident/workflow.yaml \
  --input-file examples/12-security-incident/input.json \
  --golden examples/12-security-incident/expected.json
```

`spec.evaluation.golden_path` is `expected.json` (resolved next to this
workflow). `report.schema.json` documents the structured output shape.

Expected report keys: `cve_id`, `severity`, `summary`, `specialists`,
`cloud_exposure`, `iam_impact`, `approval`, `remediation_actions` (populated
only after `--approve` / `--auto-approve`).

## 9. Generate a standalone project

```bash
agentforge generate examples/12-security-incident/workflow.yaml --out ./generated/cve-incident
cd ./generated/cve-incident
pip install -e ".[dev]"
pytest -q
python -m workflow_app.main --input-file ../../examples/12-security-incident/input.json --auto-approve
```

### What the generated repo contains (what a team would own)

| Path | Role |
|------|------|
| `src/workflow_app/graph.py` | LangGraph compiled from the IR (HITL `interrupt` + resume) |
| `src/workflow_app/agents.py` | Agent prompts / mock-or-live LLM |
| `src/workflow_app/tools.py` | Allowlisted tools including copied NVD/cloud/IAM fixtures |
| `src/workflow_app/state.py` | Typed state (`payload`, `artifacts`, `report`) |
| `docs/` | Architecture, agents, tools, security, evaluation |
| `tests/test_workflow.py` | Pattern-specific tests |
| `workflow_ir.json` | Frozen IR snapshot |

The generated app does **not** depend on the AgentForge package at runtime.
Own it like any Python service: pin deps, replace fixture tools with your
NVD/cloud APIs (`kind: python` `entrypoint: module:function` or REST with
host allowlists), and keep credentials in env vars.

## 10. Doctor

```bash
agentforge doctor --full
```

`--full` checks LangGraph run, fixture `nvd_lookup`, MCP import, writable
`.agentforge/`, and a HITL pause/resume round-trip.

## Plugging real tools

| Kind | When to use |
|------|-------------|
| `deterministic` | Offline fixtures (`nvd_lookup`, `cloud_exposure`, …) |
| `python` | `entrypoint: my_pkg.nvd:lookup` — function `(state) -> Any` |
| `rest` | `permissions.allow_network` + `allowed_hosts` |
| `mcp` | `mcp_servers[].granted_tools` must list the tool (no auto-grant) |
| `cli` | `allow_shell: true` **and** `allowed_commands` |

Optional live NVD for the built-in fixture: `AGENTFORGE_NVD_HTTP=1` (still
falls back to the catalog; `source` is `nvd_http` or `fixture_catalog`).

## Copy-paste sequence (authoring → export)

```bash
pip install -e ".[dev]"
agentforge doctor --full
agentforge design --task "Analyze a CVE with parallel vulnerability, cloud, and IAM specialists, critic review, quality evaluation, and human approval before remediation" --out /tmp/cve-designed.yaml
agentforge validate /tmp/cve-designed.yaml
# edit examples/12-security-incident/workflow.yaml (this folder is the edited spec)
agentforge inspect examples/12-security-incident/workflow.yaml
agentforge validate examples/12-security-incident/workflow.yaml
agentforge lint examples/12-security-incident/workflow.yaml
agentforge compile examples/12-security-incident/workflow.yaml
agentforge --json run examples/12-security-incident/workflow.yaml --input-file examples/12-security-incident/input.json --non-interactive
# resume with thread_id from JSON:
# agentforge resume examples/12-security-incident/workflow.yaml --thread-id <id> --approve
agentforge run examples/12-security-incident/workflow.yaml --input-file examples/12-security-incident/input.json --auto-approve --non-interactive
agentforge evaluate examples/12-security-incident/workflow.yaml --input-file examples/12-security-incident/input.json
agentforge generate examples/12-security-incident/workflow.yaml --out ./generated/cve-incident
pytest -q ./generated/cve-incident/tests
```
