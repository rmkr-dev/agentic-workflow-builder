"""AgentForge CLI - Typer + Rich."""

from __future__ import annotations

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
from agentforge.evaluation import EvaluationEngine
from agentforge.generator.project import ProjectGenerator
from agentforge.linter import Linter
from agentforge.observability import format_trace_jsonl, format_trace_tree
from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import RunRequest
from agentforge.runtimes.base.helpers import detect_llm_mode, resolve_llm_config
from agentforge.sdk import WorkflowCompiler
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
    compiler = WorkflowCompiler(runtime=runtime or "langgraph")
    ir = compiler.compile(path)
    if runtime:
        ir = ir.model_copy(update={"runtime": runtime})
        get_adapter(ir.runtime).compile(ir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ir.model_dump_json(indent=2), encoding="utf-8")
    payload = {"runtime": ir.runtime, "ir": str(out), "nodes": len(ir.nodes), "pattern": ir.pattern.value}
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(f"[green]Compiled[/green] {path} -> {out} ({ir.runtime}, {len(ir.nodes)} nodes)")


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
    input_text: str = typer.Option("hello", "--input", "-i"),
    runtime: str | None = typer.Option(None, "--runtime"),
    thread_id: str | None = typer.Option(None, "--thread-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Execute a workflow."""
    mode_info = _emit_mode(json_out=ctx.obj["json"], quiet=ctx.obj["quiet"])
    ir = _load_ir(path)
    rt = runtime or ir.runtime
    adapter = get_adapter(rt)
    adapter.compile(ir)
    result = adapter.run(
        ir,
        RunRequest(
            input={"input": input_text, "auto_approve": True},
            thread_id=thread_id,
            dry_run=dry_run,
        ),
    )
    payload = result.model_dump()
    payload["mode"] = mode_info["mode"]
    payload["llm"] = mode_info
    if ctx.obj["json"]:
        _print(payload, json_out=True, quiet=False)
    else:
        console.print(f"status={result.status.value} thread={result.thread_id}")
        console.print(result.output)
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
        console.print(f"status={result.status.value}")
        console.print(result.output)


@app.command()
def inspect(
    ctx: typer.Context,
    thread_id: str = typer.Argument(...),
    runtime: str = typer.Option("langgraph", "--runtime"),
) -> None:
    """Inspect run state."""
    view = get_adapter(runtime).inspect(thread_id)
    if ctx.obj["json"]:
        _print(view.model_dump(), json_out=True, quiet=False)
    else:
        console.print(view)


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
    input_text: str = typer.Option("evaluate me", "--input", "-i"),
    golden: Path | None = typer.Option(None, "--golden", help="Golden JSON/YAML expectations"),
    llm_judge: bool = typer.Option(False, "--llm-judge", help="Enable LLM-as-judge (mock-safe)"),
) -> None:
    """Run workflow and evaluate outputs (heuristics, golden, optional LLM judge)."""
    ir = _load_ir(path)
    adapter = get_adapter(ir.runtime)
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input={"input": input_text, "auto_approve": True}))
    golden_path = golden or (Path(ir.evaluation.golden_path) if ir.evaluation.golden_path else None)
    report = EvaluationEngine().evaluate(
        ir,
        result.output if isinstance(result.output, dict) else {"output": result.output},
        golden=golden_path,
        use_llm_judge=llm_judge or ir.evaluation.llm_judge,
    )
    if ctx.obj["json"]:
        _print(report.to_dict(), json_out=True, quiet=False)
    else:
        console.print(report)
    if not report.passed:
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

        # capability matrices
        for rt in ("langgraph", "microsoft"):
            matrix = get_adapter(rt).capability_matrix()
            supported = sum(1 for v in matrix.values() if v["status"] == "supported")
            add(f"capabilities:{rt}", True, f"{supported}/{len(matrix)} supported")

    ok = all(c["ok"] or c["name"].startswith("microsoft") or c["name"].startswith("capabilities") for c in checks)
    # microsoft optional shouldn't fail doctor
    hard = [c for c in checks if c["name"] in {"python", "pydantic", "langgraph", "langgraph-run", "templates"}]
    ok = all(c["ok"] for c in hard if c["name"] != "langgraph-run" or full)

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
