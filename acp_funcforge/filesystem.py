from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

# Common code/text extensions across languages; we still allow any extension.
CODE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".jsonc",
    ".java", ".kt", ".kts", ".scala", ".groovy", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    ".cs", ".fs", ".vb", ".go", ".rs", ".rb", ".php", ".pl", ".pm", ".lua", ".r", ".R",
    ".swift", ".m", ".mm", ".dart", ".ex", ".exs", ".erl", ".hrl", ".hs", ".ml", ".mli",
    ".clj", ".cljs", ".edn", ".elm", ".nim", ".zig", ".v", ".sv", ".vhd", ".vhdl",
    ".sql", ".graphql", ".gql", ".proto", ".thrift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bat", ".cmd",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env.example",
    ".md", ".rst", ".txt", ".dockerfile", "dockerfile", "makefile", ".mk", ".cmake",
    ".gradle", ".properties", ".tf", ".hcl",
}

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", "target", ".idea", ".vscode", ".cache", "coverage",
}
DEFAULT_EXCLUDE_GLOBS = {"*.pyc", "*.pyo", "*.so", "*.dll", "*.dylib", "*.exe", "*.bin", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.pdf", "*.zip", "*.gz", "*.tar", "*.db", "*.sqlite", "*.sqlite3"}


@dataclass
class CodeFile:
    path: str
    relpath: str
    language_hint: str
    size: int
    content: str


def detect_language(path: str) -> str:
    name = os.path.basename(path).lower()
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    ext = os.path.splitext(name)[1]
    mapping = {
        ".py": "python", ".pyi": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescriptreact", ".jsx": "javascriptreact", ".json": "json",
        ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala", ".go": "go", ".rs": "rust",
        ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
        ".cs": "csharp", ".swift": "swift", ".sh": "shell", ".bash": "shell", ".sql": "sql",
        ".html": "html", ".css": "css", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".xml": "xml", ".proto": "protobuf", ".tf": "terraform", ".lua": "lua", ".r": "r", ".dart": "dart",
        ".ex": "elixir", ".exs": "elixir", ".hs": "haskell", ".zig": "zig", ".vue": "vue", ".svelte": "svelte",
    }
    return mapping.get(ext, ext.lstrip(".") or "text")


def read_text_file(path: str, base_dir: Optional[str] = None, max_bytes: int = 2_000_000) -> CodeFile:
    p = resolve_path(path, base_dir)
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    size = os.path.getsize(p)
    if size > max_bytes:
        raise ValueError(f"File too large ({size} bytes): {p}")
    raw = Path(p).read_bytes()
    content = _decode_text(raw)
    base = os.path.abspath(base_dir) if base_dir else os.getcwd()
    try:
        rel = os.path.relpath(p, base)
    except Exception:
        rel = p
    return CodeFile(path=p, relpath=rel, language_hint=detect_language(p), size=size, content=content)


def write_text_file(path: str, content: str, base_dir: Optional[str] = None, make_dirs: bool = True) -> str:
    p = resolve_path(path, base_dir)
    if make_dirs:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    Path(p).write_text(content, encoding="utf-8", newline="")
    return p


def resolve_path(path: str, base_dir: Optional[str] = None) -> str:
    if path is None:
        raise ValueError("path is required")
    path = str(path)
    if path.startswith("file://"):
        path = path[7:]
    if os.path.isabs(path):
        return os.path.abspath(path)
    base = os.path.abspath(base_dir) if base_dir else os.getcwd()
    return os.path.abspath(os.path.join(base, path))


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def scan_code_files(
    root: str,
    include_globs: Optional[list[str]] = None,
    exclude_globs: Optional[list[str]] = None,
    max_files: int = 200,
    max_bytes_per_file: int = 200_000,
    only_known_code: bool = False,
) -> list[CodeFile]:
    root = os.path.abspath(root)
    include_globs = include_globs or ["*"]
    exclude_globs = list(DEFAULT_EXCLUDE_GLOBS) + (exclude_globs or [])
    results: list[CodeFile] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS and not any(fnmatch.fnmatch(d, g) for g in exclude_globs)]
        for name in sorted(filenames):
            if len(results) >= max_files:
                return results
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in exclude_globs):
                continue
            if not any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in include_globs):
                continue
            if only_known_code:
                ext = os.path.splitext(name)[1].lower()
                if ext not in CODE_EXTENSIONS and name.lower() not in ("dockerfile", "makefile"):
                    continue
            try:
                results.append(read_text_file(full, base_dir=root, max_bytes=max_bytes_per_file))
            except Exception:
                continue
    return results


def format_code_context(files: Iterable[CodeFile], max_chars: int = 120_000) -> str:
    parts: list[str] = []
    total = 0
    for f in files:
        block = f"\n\n--- FILE: {f.relpath} ({f.language_hint}) ---\n{f.content}\n"
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                parts.append(block[:remaining] + "\n...[truncated]...")
            break
        parts.append(block)
        total += len(block)
    return "".join(parts).strip()
