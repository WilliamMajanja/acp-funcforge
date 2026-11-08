from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Optional

from .acp_client import ACPClient
from .decomposer import DecompositionResult


@dataclass
class BuildStep:
    name: str
    status: str
    detail: str = ""
    artifacts: list[str] = None  # type: ignore

    def __post_init__(self):
        if self.artifacts is None:
            self.artifacts = []


@dataclass
class BuildResult:
    goal: str
    language: str
    output_dir: str
    steps: list[BuildStep]
    success: bool
    summary: str
    raw_responses: list[str]


BUILD_PROMPT = """You are implementing software based on a functional decomposition.
Output directory (write files here): {output_dir}
Target language: {language}
Original goal:
{goal}

Functional decomposition (JSON):
{decomposition}

Existing code/context (may be in any programming language; read, refactor, or extend it as needed):
{context}

Instructions:
- Read and understand any provided existing code/context before writing.
- Create or update the necessary source files in the output directory (any programming language as requested).
- Implement the functions/modules described in the decomposition.
- Keep code clear, minimal, and runnable where possible.
- Add a short README.md describing how to run/use it.
- Do not use ML tools or MCP servers.

When finished, respond with a JSON summary:
{{"files_created": ["..."], "files_updated": ["..."], "notes": "...", "run_instructions": "..."}}
"""


class SoftwareBuilder:
    def __init__(self, client: Optional[ACPClient] = None, cwd: Optional[str] = None):
        self.client = client
        self.cwd = cwd or os.getcwd()
        self._owns_client = client is None

    def _get_client(self) -> ACPClient:
        if self.client is None:
            self.client = ACPClient(cwd=self.cwd)
        return self.client

    def close(self) -> None:
        if self._owns_client and self.client:
            self.client.close()

    def build(
        self,
        goal: str,
        decomposition: DecompositionResult,
        output_dir: str,
        language: str = "any",
        timeout: float = 900.0,
        context: str = "",
        context_paths: Optional[list[str]] = None,
        context_globs: Optional[list[str]] = None,
        context_max_chars: int = 120_000,
    ) -> BuildResult:
        os.makedirs(output_dir, exist_ok=True)
        steps: list[BuildStep] = []
        raws: list[str] = []
        try:
            client = self._get_client()
            client.start()
            client.initialize()
            steps.append(BuildStep("initialize", "ok", f"agent={getattr(client,'agent_info',None)}"))
            sid = client.new_session(cwd=output_dir)
            steps.append(BuildStep("session", "ok", f"session={sid}"))
            ctx = self._build_context(context=context, context_paths=context_paths, context_globs=context_globs, max_chars=context_max_chars)
            prompt = BUILD_PROMPT.format(
                output_dir=os.path.abspath(output_dir),
                language=language,
                goal=goal,
                decomposition=json.dumps(asdict(decomposition), ensure_ascii=False, indent=2),
                context=ctx or "(none provided)",
            )
            resp = client.prompt(sid, prompt, timeout=timeout)
            raw = (resp.get("updates_text") or "") or json.dumps(resp.get("result"), ensure_ascii=False)
            raws.append(raw)
            artifacts = []
            try:
                for root, _, files in os.walk(output_dir):
                    for f in files:
                        artifacts.append(os.path.relpath(os.path.join(root, f), output_dir))
            except Exception:
                pass
            steps.append(BuildStep("build", "ok", "ACP prompt completed", artifacts=artifacts[:200]))
            return BuildResult(goal, language, os.path.abspath(output_dir), steps, True, raw[:2000], raws)
        except Exception as e:
            steps.append(BuildStep("error", "failed", str(e)))
            return BuildResult(goal, language, os.path.abspath(output_dir), steps, False, str(e), raws)
        finally:
            pass

    def _build_context(
        self,
        context: str = "",
        context_paths: Optional[list[str]] = None,
        context_globs: Optional[list[str]] = None,
        max_chars: int = 120_000,
    ) -> str:
        from .filesystem import format_code_context, read_text_file, scan_code_files
        parts: list[str] = []
        base = self.cwd
        if context:
            parts.append(context)
        files = []
        for p in (context_paths or []):
            try:
                target = p if os.path.isabs(p) else os.path.join(base, p)
                if os.path.isdir(target):
                    files.extend(scan_code_files(target, include_globs=context_globs, max_files=80, max_bytes_per_file=200_000))
                else:
                    files.append(read_text_file(p, base_dir=base, max_bytes=400_000))
            except Exception:
                pass
        if context_globs and not context_paths:
            try:
                files.extend(scan_code_files(base, include_globs=context_globs, max_files=80, max_bytes_per_file=200_000))
            except Exception:
                pass
        if files:
            parts.append(format_code_context(files, max_chars=max_chars))
        return "\n\n".join([p for p in parts if p]).strip()[:max_chars]
