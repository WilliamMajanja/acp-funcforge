from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from .acp_client import ACPClient
from .builder import SoftwareBuilder
from .decomposer import FunctionalDecomposer
from .filesystem import format_code_context, read_text_file, scan_code_files, write_text_file


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option("0.1.0", prog_name="acp-funcforge")
def main():
    """ACP FuncForge: functional decomposition + software building via local OpenCode ACP.

    \b
    Constraints:
      - Uses local ACP servers via `opencode acp` (Agent Client Protocol).
      - No ML tools and no MCP servers are used by this application.
      - Reads/writes code in any programming language (UTF text).

    \b
    Examples:
      acp-funcforge doctor
      acp-funcforge scan-code ./src --glob '*.py,*.ts'
      acp-funcforge decompose "Build a CLI todo app" --language rust
      acp-funcforge build "Build a CLI todo app" -l rust -o ./out
      acp-funcforge serve --port 8765
    """


def _split_csv(values: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


@main.command("read-code")
@click.argument("path")
@click.option("--cwd", default=".", help="Base directory for relative paths.")
@click.option("--max-bytes", default=2_000_000, type=int, show_default=True)
def read_code(path: str, cwd: str, max_bytes: int):
    """Read a source code/text file in any language."""
    cf = read_text_file(path, base_dir=os.path.abspath(cwd), max_bytes=max_bytes)
    click.echo(json.dumps({"path": cf.path, "relpath": cf.relpath, "language": cf.language_hint, "size": cf.size, "content": cf.content}, ensure_ascii=False, indent=2))


@main.command("write-code")
@click.argument("path")
@click.option("--cwd", default=".", help="Base directory for relative paths.")
@click.option("--content", default=None, help="Content to write. If omitted, reads stdin.")
@click.option("--from-file", "from_file", default=None, help="Read content from this file.")
def write_code(path: str, cwd: str, content: str | None, from_file: str | None):
    """Write a source code/text file in any language."""
    if from_file:
        content = Path(from_file).read_text(encoding="utf-8", errors="replace")
    if content is None:
        content = sys.stdin.read()
    saved = write_text_file(path, content, base_dir=os.path.abspath(cwd))
    click.echo(json.dumps({"ok": True, "path": saved}, ensure_ascii=False))


@main.command("scan-code")
@click.argument("root", default=".")
@click.option("--glob", "globs", multiple=True, help="Include glob(s), e.g. '*.py' or 'src/**/*.ts'. May be repeated/comma-separated.")
@click.option("--exclude", "excludes", multiple=True, help="Exclude glob(s).")
@click.option("--max-files", default=200, type=int, show_default=True)
@click.option("--max-chars", default=120_000, type=int, show_default=True, help="Max chars in packed context output.")
@click.option("--format", "fmt", type=click.Choice(["json", "context"]), default="json", show_default=True)
def scan_code(root: str, globs: tuple[str, ...], excludes: tuple[str, ...], max_files: int, max_chars: int, fmt: str):
    """Scan a directory for source code files in any language."""
    files = scan_code_files(os.path.abspath(root), include_globs=_split_csv(globs) or None, exclude_globs=_split_csv(excludes) or None, max_files=max_files)
    if fmt == "context":
        click.echo(format_code_context(files, max_chars=max_chars))
        return
    payload = [{"path": f.path, "relpath": f.relpath, "language": f.language_hint, "size": f.size} for f in files]
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@main.command()
@click.argument("goal")
@click.option("--language", "-l", default="any", help="Target implementation language (or 'any').")
@click.option("--cwd", default=".", help="Working directory / project context.")
@click.option("--context", "context_paths", multiple=True, help="Existing code file/dir to read as context (any language). Repeatable.")
@click.option("--context-glob", "context_globs", multiple=True, help="Glob(s) to select context files when scanning.")
@click.option("--context-max-chars", default=120_000, type=int, show_default=True)
@click.option("--json-out", "json_out", default=None, help="Write decomposition JSON to this path.")
@click.option("--timeout", default=600, type=float, help="ACP prompt timeout in seconds.")
def decompose(goal: str, language: str, cwd: str, context_paths: tuple[str, ...], context_globs: tuple[str, ...], context_max_chars: int, json_out: str | None, timeout: float):
    """Decompose GOAL into functions/modules using a local ACP server."""
    cwd = os.path.abspath(cwd)
    dec = FunctionalDecomposer(cwd=cwd)
    try:
        result = dec.decompose(
            goal=goal,
            language=language,
            timeout=timeout,
            context_paths=list(context_paths) or None,
            context_globs=_split_csv(context_globs) or None,
            context_max_chars=context_max_chars,
        )
        data = dec.to_dict(result)
        out = json.dumps(data, ensure_ascii=False, indent=2)
        if json_out:
            with open(json_out, "w", encoding="utf-8") as f:
                f.write(out)
            click.echo(f"Wrote decomposition to {json_out}")
        click.echo(out)
    finally:
        dec.close()


@main.command()
@click.argument("goal")
@click.option("--language", "-l", default="any", help="Target implementation language.")
@click.option("--output", "-o", "output_dir", required=True, help="Directory to generate code into.")
@click.option("--cwd", default=".", help="Working directory / project context.")
@click.option("--context", "context_paths", multiple=True, help="Existing code file/dir to read as context (any language). Repeatable.")
@click.option("--context-glob", "context_globs", multiple=True, help="Glob(s) to select context files when scanning.")
@click.option("--context-max-chars", default=120_000, type=int, show_default=True)
@click.option("--timeout", default=900, type=float, help="ACP prompt timeout in seconds.")
def build(goal: str, language: str, output_dir: str, cwd: str, context_paths: tuple[str, ...], context_globs: tuple[str, ...], context_max_chars: int, timeout: float):
    """Decompose GOAL and build software into OUTPUT using a local ACP server."""
    cwd = os.path.abspath(cwd)
    output_dir = os.path.abspath(output_dir)
    dec = FunctionalDecomposer(cwd=cwd)
    builder = SoftwareBuilder(cwd=output_dir)
    try:
        click.echo("Decomposing...")
        decomposition = dec.decompose(
            goal=goal,
            language=language,
            timeout=min(timeout, 600),
            context_paths=list(context_paths) or None,
            context_globs=_split_csv(context_globs) or None,
            context_max_chars=context_max_chars,
        )
        click.echo(f"Decomposed into {len(decomposition.functions)} function(s). Building...")
        result = builder.build(
            goal=goal,
            decomposition=decomposition,
            output_dir=output_dir,
            language=language,
            timeout=timeout,
            context_paths=list(context_paths) or None,
            context_globs=_split_csv(context_globs) or None,
            context_max_chars=context_max_chars,
        )
        payload = {
            "success": result.success,
            "output_dir": result.output_dir,
            "steps": [s.__dict__ for s in result.steps],
            "summary": result.summary,
        }
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(0 if result.success else 1)
    finally:
        dec.close()
        builder.close()


@main.command()
@click.option("--cwd", default=".", help="Working directory.")
@click.option("--opencode-bin", default=None, help="Path to opencode binary (default: $OPENCODE_BIN or 'opencode').")
@click.option("--print-logs", is_flag=True, help="Pass --print-logs to `opencode acp` (ACP logs to stderr).")
def doctor(cwd: str, opencode_bin: str | None, print_logs: bool):
    """Check local OpenCode/ACP availability."""
    cwd = os.path.abspath(cwd)
    if opencode_bin:
        os.environ["OPENCODE_BIN"] = opencode_bin
    info = {"cwd": cwd, "opencode_bin": os.environ.get("OPENCODE_BIN", "opencode")}
    try:
        import shutil
        info["opencode_path"] = shutil.which(info["opencode_bin"])
    except Exception as e:
        info["which_error"] = str(e)
    client = ACPClient(cwd=cwd, print_logs=print_logs)
    try:
        client.start()
        init = client.initialize()
        info["initialize"] = "ok"
        info["agentInfo"] = init.get("agentInfo") if isinstance(init, dict) else None
        info["agentCapabilities"] = init.get("agentCapabilities") if isinstance(init, dict) else None
        sid = client.new_session(cwd=cwd)
        info["session_new"] = "ok"
        info["sessionId"] = sid
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
    except Exception as e:
        info["error"] = str(e)
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
        sys.exit(1)
    finally:
        client.close()


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--reload", is_flag=True, help="Enable auto-reload (development).")
def serve(host: str, port: int, reload: bool):
    """Run the local web app."""
    import uvicorn
    uvicorn.run("acp_funcforge.webapp:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
