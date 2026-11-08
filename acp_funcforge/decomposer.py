from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Optional

from .acp_client import ACPClient


@dataclass
class FunctionSpec:
    name: str
    purpose: str
    inputs: list[dict[str, str]]
    outputs: list[dict[str, str]]
    dependencies: list[str]
    language_hints: list[str]
    notes: str = ""


@dataclass
class DecompositionResult:
    goal: str
    language: str
    assumptions: list[str]
    modules: list[dict[str, Any]]
    functions: list[FunctionSpec]
    data_flow: list[dict[str, str]]
    risks: list[str]
    raw_response: str = ""


DECOMPOSE_PROMPT = """You are a software architect performing FUNCTIONAL DECOMPOSITION.
Target implementation language (if specified): {language}
Goal/specification:
{goal}

Existing code/context (may be in any programming language; use it when relevant):
{context}

Return ONLY valid JSON (no markdown fences) with this schema:
{{
  "assumptions": ["..."],
  "modules": [{{"name": "...", "responsibility": "...", "functions": ["..."]}}],
  "functions": [
    {{
      "name": "...",
      "purpose": "...",
      "inputs": [{{"name": "...", "type": "...", "description": "..."}}],
      "outputs": [{{"name": "...", "type": "...", "description": "..."}}],
      "dependencies": ["other_function_name"],
      "language_hints": ["..."],
      "notes": "..."
    }}
  ],
  "data_flow": [{{"from": "...", "to": "...", "data": "..."}}],
  "risks": ["..."]
}}

Rules:
- Decompose into small, testable, single-responsibility functions.
- Include clear inputs/outputs and dependencies.
- Be language-aware when a target language is given; otherwise stay language-neutral.
- If existing code is provided, respect its language, style, and interfaces unless the goal requires changes.
- Do not use ML tools or MCP servers; produce the decomposition directly.
"""


class FunctionalDecomposer:
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

    def decompose(
        self,
        goal: str,
        language: str = "any",
        timeout: float = 600.0,
        context: str = "",
        context_paths: Optional[list[str]] = None,
        context_globs: Optional[list[str]] = None,
        context_max_chars: int = 120_000,
    ) -> DecompositionResult:
        client = self._get_client()
        client.start()
        client.initialize()
        sid = client.new_session(cwd=self.cwd)
        ctx = self._build_context(context=context, context_paths=context_paths, context_globs=context_globs, max_chars=context_max_chars)
        prompt = DECOMPOSE_PROMPT.format(language=language, goal=goal, context=ctx or "(none provided)")
        resp = client.prompt(sid, prompt, timeout=timeout)
        raw = (resp.get("updates_text") or "") or json.dumps(resp.get("result"), ensure_ascii=False)
        data = self._parse_json(raw)
        funcs = [FunctionSpec(**self._normalize_func(f)) for f in data.get("functions", [])]
        return DecompositionResult(
            goal=goal,
            language=language,
            assumptions=data.get("assumptions", []),
            modules=data.get("modules", []),
            functions=funcs,
            data_flow=data.get("data_flow", []),
            risks=data.get("risks", []),
            raw_response=raw,
        )

    def _build_context(
        self,
        context: str = "",
        context_paths: Optional[list[str]] = None,
        context_globs: Optional[list[str]] = None,
        max_chars: int = 120_000,
    ) -> str:
        from .filesystem import format_code_context, read_text_file, scan_code_files
        parts: list[str] = []
        if context:
            parts.append(context)
        files = []
        for p in (context_paths or []):
            try:
                target = p if os.path.isabs(p) else os.path.join(self.cwd, p)
                if os.path.isdir(target):
                    files.extend(scan_code_files(target, include_globs=context_globs, max_files=80, max_bytes_per_file=200_000))
                else:
                    files.append(read_text_file(p, base_dir=self.cwd, max_bytes=400_000))
            except Exception:
                pass
        if context_globs and not context_paths:
            try:
                files.extend(scan_code_files(self.cwd, include_globs=context_globs, max_files=80, max_bytes_per_file=200_000))
            except Exception:
                pass
        if files:
            parts.append(format_code_context(files, max_chars=max_chars))
        out = "\n\n".join([p for p in parts if p]).strip()
        return out[:max_chars]

    @staticmethod
    def _normalize_func(f: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": f.get("name", "unnamed"),
            "purpose": f.get("purpose", ""),
            "inputs": f.get("inputs") or [],
            "outputs": f.get("outputs") or [],
            "dependencies": f.get("dependencies") or [],
            "language_hints": f.get("language_hints") or [],
            "notes": f.get("notes", ""),
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        text = text.strip()
        # strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except Exception:
            # try to find object
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return {"assumptions": [], "modules": [], "functions": [], "data_flow": [], "risks": [f"Could not parse JSON: {text[:200]}"]}

    @staticmethod
    def to_dict(result: DecompositionResult) -> dict[str, Any]:
        d = asdict(result)
        return d
