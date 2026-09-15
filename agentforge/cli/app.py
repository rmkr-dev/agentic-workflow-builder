"""AgentForge CLI - Typer + Rich."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from agentforge import __version__
from agentforge.architect import Architect
from agentforge.compiler.capabilities import describe_compatibility
from agentforge.evaluation import EvaluationEngine
from agentforge.generator.project import ProjectGenerator
from agentforge.linter import Linter
from agentforge.observability import format_trace_jsonl, format_trace_tree
from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import RunRequest, UnsupportedCapabilityError
from agentforge.runtimes.base.helpers import detect_llm_mode, resolve_llm_config
from agentforge.sdk import WorkflowCompiler
from agentforge.tools.fixtures import nvd_lookup
from agentforge.validator.engine import ValidationEngine

GLOBAL_FLAGS = frozenset({"--json", "--quiet", "--verbose", "--non-interactive"})
KNOWN_COMMANDS = frozenset(
    {
        "version",
        "init",
        "validate",
        "lint",
        "compile",
        "generate",
        "test",
        "run",
        "resume",
        "inspect",
        "trace",
        "evaluate",
        "export",
        "design",
        "doctor",
        "publish",
    }
)


def _configure_stdio() -> None:
    """Avoid UnicodeEncodeError on Windows cp1252 consoles (e.g. help arrows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def normalize_cli_argv(argv: list[str]) -> list[str]:
    """Move global flags that appear after a subcommand to before it.

    Typer/Click only bind callback options before the subcommand. Users often
    write ``agentforge run ... --non-interactive``; rewrite that to
    ``agentforge --non-interactive run ...``.
    """
    if not argv:
        return argv
    cmd_idx = next((i for i, tok in enumerate(argv) if tok in KNOWN_COMMANDS), None)
    if cmd_idx is None:
        return argv
    before = argv[:cmd_idx]
    cmd = argv[cmd_idx]
    rest = argv[cmd_idx + 1 :]
    moved: list[str] = []
    kept: list[str] = []
    for tok in rest:
        name = tok.split("=", 1)[0] if tok.startswith("--") and "=" in tok else tok
        if name in GLOBAL_FLAGS:
            moved.append(tok)
        else:
            kept.append(tok)
    # Preserve already-present globals in ``before``; append newly moved ones
    return before + moved + [cmd] + kept


_configure_stdio()

app = typer.Typer(
    name="agentforge",
    help=(
        "Compile agentic intent into executable workflows.\n\n"
        "Global flags (--json, --quiet, --verbose, --non-interactive) may appear "
        "before or after the subcommand."
    ),
    add_completion=False,
    no_args_is_help=True,
)
console = Console(legacy_windows=False)
err_console = Console(stderr=True, legacy_windows=False)


def _opts(
    json_out: bool,
    quiet: bool,
    verbose: bool,
) -> dict[str, bool]:
    return {"json": json_out, "quiet": quiet, "verbose": verbose}


def _print(data: Any, *, json_out: bool, quiet: bool) -> None:
    if quiet and not json_out:
        return
    if json_out:
        console.print_json(data=data if not isinstance(data, str) else {"message": data})
    elif isinstance(data, str):
        console.print(data)
    else:
        console.print(data)


def _load_ir(path: Path):
    return SpecLoader().load(path)


def _mode_banner() -> dict[str, Any]:
    mode = detect_llm_mode()
    cfg = resolve_llm_config()
    return {
        "mode": mode,
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "mock": mode == "mock",
    }


def _emit_mode(*, json_out: bool, quiet: bool) -> dict[str, Any]:
    info = _mode_banner()
    if quiet:
        return info
    if json_out:
        return info
    console.print(f"mode={info['mode']} provider={info['provider']} model={info['model']}")
    return info


def _load_run_payload(
    *,
    input_text: str | None,
    input_file: Path | None,
    input_json: str | None,
    auto_approve: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if input_file is not None:
        if not input_file.exists():
            raise typer.BadParameter(f"input file not found: {input_file}")
        text = input_file.read_text(encoding="utf-8")
        try:
            if input_file.suffix.lower() in {".yaml", ".yml"}:
                loaded = yaml.safe_load(text)
            else:
                loaded = json.loads(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"Invalid input file {input_file}: {exc}") from exc
        if isinstance(loaded, dict):
            payload.update(loaded)
        else:
            payload["input"] = loaded
    if input_json:
        try:
            extra = json.loads(input_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"Invalid --input-json: {exc}") from exc
        if isinstance(extra, dict):
            payload.update(extra)
        else:
            payload["input"] = extra
    if input_text is not None:
        payload["input"] = input_text
    elif "input" not in payload and "query" not in payload and "cve_id" not in payload:
        payload["input"] = "hello"
    payload["auto_approve"] = auto_approve
    return payload


def _validate_state_input(ir: Any, payload: dict[str, Any]) -> None:
    schema = getattr(ir, "state_schema", None) or {}
    if not isinstance(schema, dict):
        return
    props = schema.get("properties")
    looks_jsonschema = bool(schema.get("$schema")) or (
        schema.get("type") == "object" and isinstance(props, dict)
    )
    if not looks_jsonschema:
        return
    try:
        import jsonschema
    except ImportError:
        return
    instance = {k: v for k, v in payload.items() if k not in {"auto_approve", "input", "query"}}
    if "cve_id" not in instance and isinstance(payload.get("input"), str):
        instance.setdefault("input", payload.get("input"))
    # Allow either structured keys or wrapping under input
    try:
        jsonschema.validate(instance=payload, schema=schema)
        return
    except Exception:
        pass
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except Exception as exc:
        msg = getattr(exc, "message", str(exc))
        raise typer.BadParameter(
            f"Input does not match spec.state_schema: {msg}. "
            "Pass --input-file with JSON matching the declared properties."
        ) from exc


def _hitl_resume_hint(path: Path, thread_id: str, *, approve: bool = True) -> str:
    flag = "--approve" if approve else "--reject"
    return f"agentforge resume {path} --thread-id {thread_id} {flag}"


def _spec_inspect_payload(ir: Any, *, runtime: str | None = None) -> dict[str, Any]:
    adapter = get_adapter(runtime or ir.runtime)
    compat = describe_compatibility(ir, adapter)
    return {
        "name": ir.name,
        "description": ir.description,
        "pattern": ir.pattern.value,
        "runtime": ir.runtime,
        "agents": [
            {"id": a.id, "role": a.role, "tools": list(a.tools)} for a in ir.agents.values()
        ],
        "tools": [
            {
                "id": t.id,
                "kind": t.kind.value if hasattr(t.kind, "value") else str(t.kind),
                "deterministic_fn": t.deterministic_fn,
                "entrypoint": t.entrypoint,
            }
            for t in ir.tools.values()
        ],
        "nodes": [{"id": n.id, "type": n.type.value} for n in ir.nodes],
        "policies": {
            "default_deny": ir.policies.tool.default_deny,
            "allowed_tools": list(ir.policies.tool.allowed_tools),
            "max_steps": ir.policies.budget.max_steps,
            "timeout_seconds": ir.policies.budget.timeout_seconds,
        },
        "evaluation": {
            "enabled": ir.evaluation.enabled,
            "golden_path": ir.evaluation.golden_path,
            "has_output_schema": bool(ir.evaluation.output_schema),
        },
        "compatibility": compat,
        "mermaid": ir.to_mermaid(),
    }


@app.callback()
def main_callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit JSON"),
    quiet: bool = typer.Option(False, "--quiet", help="Minimal output"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose output"),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Never prompt (accepted before or after the subcommand)",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "json": json_output,
            "quiet": quiet,
            "verbose": verbose,
            "non_interactive": non_interactive,
        }
    )


@app.command()
def version() -> None:
    """Show AgentForge version."""
    console.print(__version__)


@app.command("init")
def init_cmd(
    ctx: typer.Context,
    name: str = typer.Argument("my-workflow"),
    pattern: str = typer.Option("sequential", "--pattern"),
    directory: Path = typer.Option(Path("."), "--dir"),
) -> None:
    """Scaffold a new workflow spec."""
    architect = Architect()
    doc = architect.design(f"Initialize {name}", pattern=pattern, name=name.replace(" ", "-"))
    target = directory / "workflow.yaml"
    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    readme = directory / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {name}\n\nGenerated with AgentForge.\n\n```bash\nagentforge validate workflow.yaml\nagentforge run workflow.yaml\n```\n",
            encoding="utf-8",
        )
    payload = {"created": str(target), "pattern": pattern}
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(f"[green]Created[/green] {target} (pattern={pattern})")


@app.command()
def validate(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
) -> None:
    """Validate a workflow spec."""
    ir = _load_ir(path)
    report = ValidationEngine().validate(ir)
    if ctx.obj["json"]:
        _print(report.to_dict(), json_out=True, quiet=False)
    else:
        console.print(report.format())
    if report.has_errors:
        raise typer.Exit(1)


@app.command()
def lint(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
) -> None:
    """Lint a workflow for best practices."""
    ir = _load_ir(path)
    # Include validation errors as well
    report = ValidationEngine().validate(ir)
    report.extend(Linter().lint(ir).diagnostics)
    if ctx.obj["json"]:
        _print(report.to_dict(), json_out=True, quiet=False)
    else:
        console.print(report.format())
    if report.has_errors:
        raise typer.Exit(1)


@app.command()
def compile(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    runtime: str | None = typer.Option(None, "--runtime"),
    out: Path = typer.Option(Path(".agentforge/ir.json"), "--out"),
) -> None:
    """Compile spec to Workflow IR and bind a runtime."""
    try:
        compiler = WorkflowCompiler(runtime=runtime or "langgraph")
        ir = compiler.compile(path)
        if runtime:
            ir = ir.model_copy(update={"runtime": runtime})
            get_adapter(ir.runtime).compile(ir)
    except (ValueError, UnsupportedCapabilityError) as exc:
        err_console.print(f"[red]compile failed[/red] {exc}")
        raise typer.Exit(1) from exc
    adapter = get_adapter(runtime or ir.runtime)
    compat = describe_compatibility(ir, adapter)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ir.model_dump_json(indent=2), encoding="utf-8")
    payload = {
        "runtime": ir.runtime,
        "ir": str(out),
        "nodes": len(ir.nodes),
        "pattern": ir.pattern.value,
        "compatibility": compat,
    }
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(
            f"[green]Compiled[/green] {path} -> {out} ({ir.runtime}, {len(ir.nodes)} nodes)"
        )
        ok = "ok" if compat.get("ok") else "UNSUPPORTED"
        console.print(
            f"runtime compatibility: {compat['runtime']} "
            f"{compat['supported']}/{compat['total']} required supported ({ok})"
        )
        for row in compat.get("rows") or []:
            console.print(f"  {row['capability']}: {row['status']}")


@app.command()
def generate(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    output_dir: Path | None = typer.Option(None, "--out"),
    runtime: str = typer.Option("langgraph", "--runtime"),
) -> None:
    """Generate a standalone agent project."""
    compiler = WorkflowCompiler(runtime=runtime)
    project = compiler.generate(path, output_dir=output_dir, runtime=runtime)
    payload = {"path": str(project.path), "files": project.files, "name": project.name}
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(f"[green]Generated[/green] project at {project.path} ({len(project.files)} files)")


@app.command("test")
def test_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    generate_first: bool = typer.Option(True, "--generate/--no-generate"),
    golden: Path | None = typer.Option(None, "--golden", help="Golden-file evaluation"),
    eval_outputs: bool = typer.Option(True, "--eval/--no-eval"),
) -> None:
    """Validate, optionally generate, evaluate, and run project tests."""
    ir = _load_ir(path)
    report = ValidationEngine().validate(ir)
    if report.has_errors:
        console.print(report.format())
        raise typer.Exit(1)
    adapter = get_adapter(ir.runtime)
    result = adapter.run(ir, RunRequest(input={"input": "test", "auto_approve": True}))
    ok = result.status.value in {"COMPLETED", "WAITING_FOR_APPROVAL", "WAITING_FOR_INPUT"}
    eval_report = None
    if eval_outputs or golden or ir.evaluation.enabled:
        golden_path = golden
        if golden_path is None and ir.evaluation.golden_path:
            golden_path = Path(ir.evaluation.golden_path)
        eval_report = EvaluationEngine().evaluate(
            ir,
            result.output if isinstance(result.output, dict) else {"output": result.output},
            golden=golden_path,
            use_llm_judge=ir.evaluation.llm_judge or None,
        )
        if golden_path or ir.evaluation.enabled:
            ok = ok and eval_report.passed
    if generate_first:
        out = Path(".agentforge/test_gen") / ir.name
        ProjectGenerator().generate(ir, output_dir=out, runtime=ir.runtime)
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(out), "-q"], check=False)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", str(out / "tests")], check=False)
        ok = ok and proc.returncode == 0
    payload: dict[str, Any] = {"ok": ok, "run_status": result.status.value, "output": result.output}
    if eval_report is not None:
        payload["evaluation"] = eval_report.to_dict()
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(f"[green]test ok[/green] status={result.status.value}" if ok else "[red]test failed[/red]")
        if eval_report is not None:
            console.print(f"evaluation passed={eval_report.passed} overall={eval_report.overall:.2f}")
    raise typer.Exit(0 if ok else 1)


@app.command()
def run(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    input_text: str | None = typer.Option(None, "--input", "-i", help="Free-text query (optional)"),
    input_file: Path | None = typer.Option(None, "--input-file", help="JSON/YAML object merged into run state"),
    input_json: str | None = typer.Option(None, "--input-json", help="Inline JSON object merged into run state"),
    runtime: str | None = typer.Option(None, "--runtime"),
    thread_id: str | None = typer.Option(None, "--thread-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        help="Skip HITL gates (CI / non-interactive full run). Default pauses for resume.",
    ),
) -> None:
    """Execute a workflow."""
    mode_info = _emit_mode(json_out=ctx.obj["json"], quiet=ctx.obj["quiet"])
    ir = _load_ir(path)
    payload = _load_run_payload(
        input_text=input_text,
        input_file=input_file,
        input_json=input_json,
        auto_approve=auto_approve,
    )
    _validate_state_input(ir, payload)
    rt = runtime or ir.runtime
    adapter = get_adapter(rt)
    adapter.compile(ir)
    result = adapter.run(
        ir,
        RunRequest(
            input=payload,
            thread_id=thread_id,
            dry_run=dry_run,
        ),
    )
    out_payload = result.model_dump()
    out_payload["mode"] = mode_info["mode"]
    out_payload["llm"] = mode_info
    if result.status.value == "WAITING_FOR_APPROVAL":
        out_payload["resume"] = _hitl_resume_hint(path, result.thread_id)
    if ctx.obj["json"]:
        _print(out_payload, json_out=True, quiet=False)
    else:
        console.print(f"status={result.status.value} thread={result.thread_id}")
        console.print(result.output)
        if result.status.value == "WAITING_FOR_APPROVAL":
            console.print("[yellow]HITL paused[/yellow]. Resume with:")
            console.print(f"  {_hitl_resume_hint(path, result.thread_id)}")
            if result.interrupt:
                console.print(f"interrupt={result.interrupt}")
    if result.status.value == "FAILED":
        raise typer.Exit(1)


@app.command()
def resume(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    thread_id: str = typer.Option(..., "--thread-id"),
    approve: bool = typer.Option(True, "--approve/--reject"),
    value: str | None = typer.Option(None, "--value"),
    runtime: str | None = typer.Option(None, "--runtime"),
) -> None:
    """Resume a paused / waiting workflow."""
    ir = _load_ir(path)
    adapter = get_adapter(runtime or ir.runtime)
    adapter.compile(ir)
    result = adapter.resume(
        ir,
        RunRequest(thread_id=thread_id, approval=approve, resume_value=value or {"approved": approve}),
    )
    if ctx.obj["json"]:
        _print(result.model_dump(), json_out=True, quiet=False)
    else:
        console.print(f"status={result.status.value} thread={result.thread_id}")
        console.print(result.output)
        if result.error:
            err_console.print(f"[red]{result.error}[/red]")
    if result.status.value == "FAILED":
        raise typer.Exit(1)


@app.command()
def inspect(
    ctx: typer.Context,
    target: str | None = typer.Argument(
        None,
        help="workflow.yaml path or thread_id (default: workflow.yaml if present)",
    ),
    runtime: str = typer.Option("langgraph", "--runtime"),
    thread_id: str | None = typer.Option(None, "--thread-id", help="Inspect a run by thread id"),
) -> None:
    """Inspect a workflow spec or a persisted run."""
    adapter = get_adapter(runtime)
    tid = thread_id
    spec_path: Path | None = None
    if target:
        as_path = Path(target)
        if as_path.exists() and as_path.is_file():
            spec_path = as_path
        elif target.endswith((".yaml", ".yml", ".json")):
            spec_path = as_path
        else:
            tid = tid or target
    elif Path("workflow.yaml").exists():
        spec_path = Path("workflow.yaml")

    payload: dict[str, Any] = {}
    if spec_path is not None:
        if not spec_path.exists():
            err_console.print(f"[red]spec not found[/red] {spec_path}")
            raise typer.Exit(1)
        ir = _load_ir(spec_path)
        payload["spec"] = _spec_inspect_payload(ir, runtime=runtime)
    if tid:
        payload["run"] = adapter.inspect(tid).model_dump()
    if not spec_path and not tid:
        recent = []
        list_runs = getattr(adapter.store, "list_runs", None)
        if callable(list_runs):
            recent = list_runs(10)
        payload["recent_runs"] = recent
        payload["hint"] = "Pass workflow.yaml or a thread_id (from --json run)."

    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
        return
    if "spec" in payload:
        spec = payload["spec"]
        console.print(f"[bold]{spec['name']}[/bold] pattern={spec['pattern']} runtime={spec['runtime']}")
        console.print(spec.get("description") or "")
        console.print("agents: " + ", ".join(a["id"] for a in spec["agents"]))
        console.print("tools: " + ", ".join(t["id"] for t in spec["tools"]))
        compat = spec.get("compatibility") or {}
        console.print(
            f"compatibility: {compat.get('runtime')} "
            f"{compat.get('supported')}/{compat.get('total')} required supported"
        )
        console.print(spec.get("mermaid") or "", markup=False)
    if "run" in payload:
        console.print(payload["run"])
    if "recent_runs" in payload:
        console.print("recent runs:")
        for row in payload["recent_runs"]:
            console.print(f"  {row.get('thread_id')} {row.get('status')}")
        if payload.get("hint"):
            console.print(payload["hint"])


@app.command()
def trace(
    ctx: typer.Context,
    thread_id: str = typer.Argument(...),
    runtime: str = typer.Option("langgraph", "--runtime"),
    fmt: str = typer.Option("ascii", "--format", help="ascii|jsonl|json"),
) -> None:
    """Show an event trace for a run (ASCII tree or JSONL spans)."""
    adapter = get_adapter(runtime)
    events = adapter.store.list_events(thread_id)  # type: ignore[attr-defined]
    if fmt == "jsonl":
        text = format_trace_jsonl(events, thread_id=thread_id)
        if ctx.obj["json"]:
            _print({"thread_id": thread_id, "format": "jsonl", "content": text}, json_out=True, quiet=False)
        else:
            console.print(text, end="" if text.endswith("\n") else "\n")
        return
    if fmt == "json" or ctx.obj["json"]:
        _print({"thread_id": thread_id, "events": events}, json_out=True, quiet=False)
        return
    tree_text = format_trace_tree(events)
    tree = Tree(f"trace:{thread_id}")
    for ev in events:
        tree.add(f"{ev.get('type')} @ {ev.get('at')}")
    console.print(tree)
    console.print(tree_text)


@app.command()
def evaluate(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    input_text: str | None = typer.Option(None, "--input", "-i"),
    input_file: Path | None = typer.Option(None, "--input-file"),
    input_json: str | None = typer.Option(None, "--input-json"),
    golden: Path | None = typer.Option(None, "--golden", help="Golden JSON/YAML expectations"),
    llm_judge: bool = typer.Option(False, "--llm-judge", help="Enable LLM-as-judge (mock-safe)"),
    auto_approve: bool = typer.Option(
        True,
        "--auto-approve/--no-auto-approve",
        help="Evaluate needs a complete run; default skips HITL.",
    ),
) -> None:
    """Run workflow and evaluate outputs (heuristics, golden, optional LLM judge)."""
    ir = _load_ir(path)
    payload = _load_run_payload(
        input_text=input_text,
        input_file=input_file,
        input_json=input_json,
        auto_approve=auto_approve,
    )
    _validate_state_input(ir, payload)
    adapter = get_adapter(ir.runtime)
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input=payload))
    golden_path = golden or (Path(ir.evaluation.golden_path) if ir.evaluation.golden_path else None)
    eval_output = result.output if isinstance(result.output, dict) else {"output": result.output}
    report = EvaluationEngine().evaluate(
        ir,
        eval_output,
        golden=golden_path,
        use_llm_judge=llm_judge or ir.evaluation.llm_judge,
    )
    if ctx.obj["json"]:
        _print(report.to_dict(), json_out=True, quiet=False)
    else:
        console.print(report)
    if result.status.value == "FAILED" or not report.passed:
        raise typer.Exit(1)


@app.command()
def export(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    format: str = typer.Option("mermaid", "--format", help="mermaid|json|yaml"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Export IR / diagrams."""
    ir = _load_ir(path)
    if format == "mermaid":
        content = ir.to_mermaid()
    elif format == "json":
        content = ir.model_dump_json(indent=2)
    elif format == "yaml":
        content = yaml.safe_dump(ir.model_dump(mode="json"), sort_keys=False)
    else:
        raise typer.BadParameter("format must be mermaid|json|yaml")
    if out:
        out.write_text(content, encoding="utf-8")
    if ctx.obj["json"]:
        _print({"format": format, "content": content, "out": str(out) if out else None}, json_out=True, quiet=False)
    else:
        console.print(content)


@app.command()
def design(
    ctx: typer.Context,
    task: str = typer.Option(..., "--task", help="Natural language task"),
    pattern: str | None = typer.Option(None, "--pattern"),
    out: Path = typer.Option(Path("workflow.yaml"), "--out"),
) -> None:
    """Design a validated workflow YAML from a task description."""
    text = Architect().design_yaml(task, pattern=pattern)
    out.write_text(text, encoding="utf-8")
    # validate
    report = ValidationEngine().validate(SpecLoader().load(out))
    if report.has_errors:
        console.print(report.format())
        raise typer.Exit(1)
    if ctx.obj["json"]:
        _print({"out": str(out), "ok": True}, json_out=True, quiet=False)
    else:
        console.print(f"[green]Wrote[/green] {out}")
        console.print(text)


@app.command()
def doctor(
    ctx: typer.Context,
    full: bool = typer.Option(False, "--full", help="Run extended checks"),
) -> None:
    """Environment and installation diagnostics."""
    mode_info = _emit_mode(json_out=ctx.obj["json"], quiet=ctx.obj["quiet"])
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("python", sys.version_info >= (3, 11), sys.version.split()[0])
    add("llm_mode", True, mode_info["mode"])
    try:
        import pydantic

        add("pydantic", True, pydantic.__version__)
    except Exception as exc:
        add("pydantic", False, str(exc))
    try:
        import langgraph

        add("langgraph", True, getattr(langgraph, "__version__", "present"))
    except Exception as exc:
        add("langgraph", False, str(exc))
    try:
        import agent_framework  # noqa: F401

        add("microsoft-agent-framework", True, "installed")
    except Exception:
        add("microsoft-agent-framework", False, "optional - pip install agentforge[microsoft]")

    add("templates", (Path(__file__).resolve().parents[2] / "templates" / "generated-project").exists())
    if full:
        # compile + run a tiny inline workflow
        tiny = {
            "apiVersion": "agentforge/v1",
            "kind": "Workflow",
            "metadata": {"name": "doctor-check"},
            "spec": {
                "pattern": "single",
                "runtime": "langgraph",
                "agents": [{"id": "a", "system_prompt": "hi"}],
                "nodes": [
                    {"id": "start", "type": "START"},
                    {"id": "a", "type": "AGENT", "agent": "a"},
                    {"id": "end", "type": "END"},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "end"},
                ],
            },
        }
        try:
            ir = SpecLoader().load(tiny)
            adapter = get_adapter("langgraph")
            adapter.compile(ir)
            result = adapter.run(ir, RunRequest(input={"input": "doctor"}))
            add("langgraph-run", result.status.value == "COMPLETED", result.status.value)
        except Exception as exc:
            add("langgraph-run", False, str(exc))

        try:
            rec = nvd_lookup({"cve_id": "CVE-2024-3094"})
            add("fixture-nvd_lookup", rec.get("cve_id") == "CVE-2024-3094", rec.get("title", "")[:60])
        except Exception as exc:
            add("fixture-nvd_lookup", False, str(exc))

        try:
            import mcp  # noqa: F401

            add("mcp", True, getattr(mcp, "__version__", "present"))
        except Exception:
            add("mcp", False, "optional - pip install agentforge[mcp]")

        data_dir = Path(".agentforge")
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            probe = data_dir / ".doctor-write"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            add("data-dir", True, str(data_dir.resolve()))
        except Exception as exc:
            add("data-dir", False, str(exc))

        # HITL pause + resume against a durable checkpointer (same process)
        hitl_doc = {
            "apiVersion": "agentforge/v1",
            "kind": "Workflow",
            "metadata": {"name": "doctor-hitl"},
            "spec": {
                "pattern": "hitl",
                "runtime": "langgraph",
                "agents": [{"id": "a", "system_prompt": "draft"}],
                "nodes": [
                    {"id": "start", "type": "START"},
                    {"id": "a", "type": "AGENT", "agent": "a"},
                    {"id": "approve", "type": "HUMAN_APPROVAL", "approval_message": "ok?"},
                    {"id": "end", "type": "END"},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "approve"},
                    {"source": "approve", "target": "end"},
                ],
                "policies": {"approval": {"auto_approve_in_tests": True}},
            },
        }
        try:
            from agentforge.runtimes.base.helpers import SQLiteRunStore
            from agentforge.runtimes.langgraph import LangGraphAdapter
            from agentforge.runtimes.langgraph.checkpointer import DurableMemorySaver

            tmp_store = SQLiteRunStore(data_dir / "doctor-runs.db")
            tmp_ckpt = DurableMemorySaver(data_dir / "doctor-ckpt.pkl")
            hitl_adapter = LangGraphAdapter(store=tmp_store, checkpointer=tmp_ckpt)
            hitl_ir = SpecLoader().load(hitl_doc)
            hitl_adapter.compile(hitl_ir)
            paused = hitl_adapter.run(hitl_ir, RunRequest(input={"input": "doctor-hitl", "auto_approve": False}))
            if paused.status.value != "WAITING_FOR_APPROVAL":
                add("hitl-pause", False, paused.status.value)
            else:
                resumed = hitl_adapter.resume(
                    hitl_ir,
                    RunRequest(thread_id=paused.thread_id, approval=True),
                )
                add(
                    "hitl-resume",
                    resumed.status.value == "COMPLETED",
                    f"pause={paused.status.value} resume={resumed.status.value}",
                )
                add("hitl-pause", True, paused.thread_id)
        except Exception as exc:
            add("hitl-pause", False, str(exc))
            add("hitl-resume", False, str(exc))

        # capability matrices
        for rt in ("langgraph", "microsoft"):
            matrix = get_adapter(rt).capability_matrix()
            supported = sum(1 for v in matrix.values() if v["status"] == "supported")
            add(f"capabilities:{rt}", True, f"{supported}/{len(matrix)} supported")

    ok = all(c["ok"] or c["name"].startswith("microsoft") or c["name"].startswith("capabilities") for c in checks)
    # microsoft optional shouldn't fail doctor
    hard = [
        c
        for c in checks
        if c["name"]
        in {
            "python",
            "pydantic",
            "langgraph",
            "langgraph-run",
            "templates",
            "fixture-nvd_lookup",
            "data-dir",
            "hitl-pause",
            "hitl-resume",
        }
    ]
    ok = all(c["ok"] for c in hard if c["name"] not in {"langgraph-run", "hitl-pause", "hitl-resume"} or full)

    if ctx.obj["json"]:
        _print(
            {"ok": ok, "checks": checks, "version": __version__, "mode": mode_info["mode"], "llm": mode_info},
            json_out=True,
            quiet=False,
        )
    else:
        table = Table(title=f"AgentForge doctor v{__version__}")
        table.add_column("Check")
        table.add_column("OK")
        table.add_column("Detail")
        for c in checks:
            table.add_row(c["name"], "yes" if c["ok"] else "no", c["detail"])
        console.print(table)
    raise typer.Exit(0 if ok else 1)


@app.command()
def publish(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("workflow.yaml")),
    out: Path = typer.Option(Path("dist"), "--out"),
) -> None:
    """Package generated project artifacts for distribution (local tarball)."""
    import tarfile

    ir = _load_ir(path)
    gen_dir = out / ir.name
    ProjectGenerator().generate(ir, output_dir=gen_dir, runtime=ir.runtime)
    tarball = out / f"{ir.name}.tar.gz"
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(gen_dir, arcname=ir.name)
    if ctx.obj["json"]:
        _print({"tarball": str(tarball), "project": str(gen_dir)}, json_out=True, quiet=False)
    else:
        console.print(f"[green]Published[/green] {tarball}")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    normalized = normalize_cli_argv(args)
    app(args=normalized, prog_name="agentforge")


if __name__ == "__main__":
    main()
