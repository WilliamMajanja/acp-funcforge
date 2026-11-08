# ACP FuncForge

**Local-first functional decomposition and software building over OpenCode ACP** — a Python CLI + web app that can read/write code in **any programming language**.

ACP FuncForge turns a goal/spec into a structured functional decomposition and can orchestrate implementation by talking to **local [OpenCode](https://opencode.ai/) ACP servers** (`opencode acp`, Agent Client Protocol over stdio JSON-RPC).

## Why it’s “sticker worthy”

- **Clear constraints**: no ML libraries in-app, no MCP servers in-app; orchestration uses **local ACP only** (`opencode acp`).
- **Any-language code I/O**: read, write, and scan source files across languages (Python, Go, Rust, TS/JS, Java, C/C++, Ruby, SQL, etc.).
- **Context-aware**: feed existing code/files/globs into decomposition and build prompts.
- **Two interfaces**: ergonomic CLI + local FastAPI web UI/API.
- **Tested**: stdlib `unittest` suite for filesystem, parsing, ACP text extraction, and CLI smoke.
- **Packaged**: `pyproject.toml`, console script, MIT license.

> ACP FuncForge is an **ACP client**. The OpenCode agent you connect to may use its own configured models/tools per your OpenCode setup.

## Requirements

- Python **3.10+**
- **OpenCode** installed locally (`opencode`, or set `OPENCODE_BIN`)
- OpenCode configured with a working provider/model for prompts (run `opencode auth login` / configure as needed)

## Quick start

```bash
cd /home/minima/Documents/Projects/acp-funcforge
python3 -m pip install -e .

# 1) Verify local ACP connectivity (spawns `opencode acp`)
acp-funcforge doctor

# 2) Read / write / scan code in any language
acp-funcforge write-code /tmp/opencode/demo/main.go --content $'package main\nfunc main(){}\n'
acp-funcforge read-code /tmp/opencode/demo/main.go
acp-funcforge scan-code . --glob '*.py,*.ts,*.go,*.rs'

# 3) Functional decomposition (any target language)
acp-funcforge decompose "Build a rate-limited URL shortener API" --language python
acp-funcforge decompose "Refactor this module for testability" --context src/ --context-glob '*.py'

# 4) Decompose + build into an output directory
acp-funcforge build "Build a rate-limited URL shortener API" -l python -o ./generated/url-shortener

# 5) Web UI
acp-funcforge serve --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

## CLI commands

| Command | Purpose |
|---|---|
| `doctor` | Check OpenCode/ACP availability; initialize and create a session |
| `read-code PATH` | Read a source/text file (any language) |
| `write-code PATH` | Write a source/text file (`--content` or stdin / `--from-file`) |
| `scan-code ROOT` | Scan code files (`--glob`, `--exclude`, `--format json\|context`) |
| `decompose GOAL` | Produce structured JSON decomposition (modules/functions/I/O/deps/data flow/risks) |
| `build GOAL -o DIR` | Decompose, then ask the ACP agent to generate/update code in `DIR` |
| `serve` | Run local FastAPI web app |

Useful options: `--language/-l`, `--context` (repeatable file/dir), `--context-glob`, `--cwd`, `--json-out`, `--timeout`, `--opencode-bin`, `--print-logs` (doctor).

## Web API

- `GET /api/health`
- `GET /api/doctor`
- `POST /api/read-code` — `{path, cwd?, max_bytes?}`
- `POST /api/write-code` — `{path, content, cwd?}`
- `POST /api/scan-code` — `{root, cwd?, include_globs?, exclude_globs?, max_files?, include_context?}`
- `POST /api/decompose` — `{goal, language?, cwd?, context?, context_paths?, context_globs?, timeout?}`
- `POST /api/build` — `{goal, language?, output_dir?, cwd?, context?, context_paths?, context_globs?, timeout?}`

## Architecture

```text
CLI / FastAPI web app
        │
        ├─ filesystem.py ── local read/write/scan for any language + context packing
        │
        ├─ decomposer.py ── goal (+ existing code context) → structured functional decomposition
        │
        ├─ builder.py ───── decomposition (+ context) → code generation/update in output dir
        │
        └─ acp_client.py ── stdio JSON-RPC to local `opencode acp`
                              initialize → session/new → session/prompt
                              auto-handles basic fs read/write + permission requests
```

## Development

```bash
python3 -m py_compile acp_funcforge/*.py tests/*.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 -m acp_funcforge.cli --help
```

## Troubleshooting

- **`doctor` fails**: ensure `opencode` is on `PATH` (or `--opencode-bin`/`OPENCODE_BIN`) and configured with a provider. Try `opencode --version` and `opencode acp` behavior from an ACP client context; use `--print-logs` for ACP stderr.
- **Prompts time out**: increase `--timeout`; response time depends on your OpenCode model/provider.
- **Generated code needs review**: this tool orchestrates generation; always review, test, and secure outputs before running.

## License

MIT — see [`LICENSE`](./LICENSE).
