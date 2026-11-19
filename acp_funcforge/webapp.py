from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .builder import SoftwareBuilder
from .decomposer import FunctionalDecomposer
from .filesystem import format_code_context, read_text_file, scan_code_files, write_text_file

app = FastAPI(
    title="ACP FuncForge",
    description=(
        "Functional decomposition and software building via local OpenCode ACP servers "
        "(Agent Client Protocol, `opencode acp`). No ML tools or MCP servers are used by this app. "
        "Reads and writes code in any programming language."
    ),
    version="0.1.0",
)


class DecomposeRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    language: str = "any"
    cwd: Optional[str] = None
    context: Optional[str] = None
    context_paths: Optional[list[str]] = None
    context_globs: Optional[list[str]] = None
    context_max_chars: int = 120_000
    timeout: float = 600.0


class BuildRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    language: str = "any"
    output_dir: Optional[str] = None
    cwd: Optional[str] = None
    context: Optional[str] = None
    context_paths: Optional[list[str]] = None
    context_globs: Optional[list[str]] = None
    context_max_chars: int = 120_000
    timeout: float = 900.0


class ReadCodeRequest(BaseModel):
    path: str
    cwd: Optional[str] = None
    max_bytes: int = 2_000_000


class WriteCodeRequest(BaseModel):
    path: str
    content: str
    cwd: Optional[str] = None


class ScanCodeRequest(BaseModel):
    root: str = "."
    cwd: Optional[str] = None
    include_globs: Optional[list[str]] = None
    exclude_globs: Optional[list[str]] = None
    max_files: int = 200
    max_chars: int = 120_000
    include_context: bool = False


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>ACP FuncForge</title>
  <style>
    body{font-family:system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.4}
    textarea,input{width:100%;box-sizing:border-box;padding:.6rem;margin:.25rem 0 .75rem}
    textarea{min-height:110px}
    button{padding:.6rem 1rem;cursor:pointer}
    pre{background:#111;color:#eee;padding:1rem;overflow:auto;border-radius:8px;white-space:pre-wrap}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
    .card{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}
    small{color:#555}
  </style>
</head>
<body>
  <h1>ACP FuncForge</h1>
  <p>Functional decomposition and software building using <strong>local OpenCode ACP servers</strong> (<code>opencode acp</code>). No ML tools or MCP servers are used by this app. Reads/writes code in any programming language.</p>

  <div class="card">
    <h2>Read / Write / Scan Code (any language)</h2>
    <div class="row">
      <div><label>Path</label><input id="f-path" placeholder="src/main.py, app.go, lib.rs, index.ts ..."/></div>
      <div><label>Base cwd (optional)</label><input id="f-cwd" placeholder="/path/to/project"/></div>
    </div>
    <button onclick="runRead()">Read file</button>
    <label>Content (for write)</label><textarea id="f-content" placeholder="Code content to write"></textarea>
    <button onclick="runWrite()">Write file</button>
    <div class="row">
      <div><label>Scan root</label><input id="s-root" value="."/></div>
      <div><label>Include globs (comma)</label><input id="s-globs" placeholder="*.py,src/**/*.ts"/></div>
    </div>
    <button onclick="runScan()">Scan code</button>
    <pre id="f-out">Result will appear here.</pre>
  </div>

  <div class="card">
    <h2>Functional Decomposition</h2>
    <label>Goal / specification</label>
    <textarea id="d-goal" placeholder="Describe what to build or decompose..."></textarea>
    <div class="row">
      <div><label>Target language</label><input id="d-lang" value="any"/></div>
      <div><label>Working directory (optional)</label><input id="d-cwd" placeholder="/path/to/project"/></div>
    </div>
    <label>Context paths (comma-separated files/dirs, optional)</label><input id="d-ctx" placeholder="src/,main.py"/>
    <label>Context globs (comma, optional)</label><input id="d-globs" placeholder="*.py,src/**/*.rs"/>
    <button onclick="runDecompose()">Decompose</button>
    <pre id="d-out">Result will appear here.</pre>
  </div>

  <div class="card">
    <h2>Build Software</h2>
    <label>Goal / specification</label>
    <textarea id="b-goal" placeholder="Describe the software to build..."></textarea>
    <div class="row">
      <div><label>Target language</label><input id="b-lang" value="python"/></div>
      <div><label>Output directory (optional)</label><input id="b-outdir" placeholder="Defaults to a temp folder"/></div>
    </div>
    <label>Working directory (optional)</label><input id="b-cwd" placeholder="/path/to/project"/>
    <label>Context paths (comma-separated files/dirs, optional)</label><input id="b-ctx" placeholder="existing/src"/>
    <label>Context globs (comma, optional)</label><input id="b-globs" placeholder="**/*.go"/>
    <button onclick="runBuild()">Decompose + Build</button>
    <small>Build can take several minutes while the local ACP/OpenCode agent works.</small>
    <pre id="b-out">Result will appear here.</pre>
  </div>

<script>
async function post(url, body, outId){
  const out = document.getElementById(outId);
  out.textContent = 'Working...';
  try {
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const t = await r.text();
    let v; try{v=JSON.parse(t)}catch{v=t}
    out.textContent = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  } catch(e){ out.textContent = String(e); }
}
function split(v){ return (v||'').split(',').map(s=>s.trim()).filter(Boolean); }
function runRead(){ post('/api/read-code', {path: fpath(), cwd: fcwd()}, 'f-out'); }
function runWrite(){ post('/api/write-code', {path: fpath(), cwd: fcwd(), content: document.getElementById('f-content').value}, 'f-out'); }
function runScan(){ post('/api/scan-code', {root: document.getElementById('s-root').value||'.', include_globs: split(document.getElementById('s-globs').value), cwd: fcwd()}, 'f-out'); }
function fpath(){ return document.getElementById('f-path').value; }
function fcwd(){ return document.getElementById('f-cwd').value || null; }
function runDecompose(){
  post('/api/decompose', {
    goal: document.getElementById('d-goal').value,
    language: document.getElementById('d-lang').value || 'any',
    cwd: document.getElementById('d-cwd').value || null,
    context_paths: split(document.getElementById('d-ctx').value),
    context_globs: split(document.getElementById('d-globs').value)
  }, 'd-out');
}
function runBuild(){
  post('/api/build', {
    goal: document.getElementById('b-goal').value,
    language: document.getElementById('b-lang').value || 'any',
    output_dir: document.getElementById('b-outdir').value || null,
    cwd: document.getElementById('b-cwd').value || null,
    context_paths: split(document.getElementById('b-ctx').value),
    context_globs: split(document.getElementById('b-globs').value)
  }, 'b-out');
}
</script>
</body>
</html>"""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "acp-funcforge", "transport": "opencode acp (local ACP server)", "code_io": "any language (read/write/scan)"}


@app.get("/api/doctor")
def doctor(cwd: Optional[str] = None) -> dict[str, Any]:
    from .acp_client import ACPClient
    cwd = cwd or os.getcwd()
    client = ACPClient(cwd=cwd)
    try:
        client.start()
        init = client.initialize()
        sid = client.new_session(cwd=cwd)
        return {"ok": True, "agentInfo": init.get("agentInfo") if isinstance(init, dict) else None, "sessionId": sid}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    finally:
        client.close()


@app.post("/api/read-code")
def api_read_code(req: ReadCodeRequest) -> dict[str, Any]:
    try:
        cf = read_text_file(req.path, base_dir=req.cwd or os.getcwd(), max_bytes=req.max_bytes)
        return {"path": cf.path, "relpath": cf.relpath, "language": cf.language_hint, "size": cf.size, "content": cf.content}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/write-code")
def api_write_code(req: WriteCodeRequest) -> dict[str, Any]:
    try:
        saved = write_text_file(req.path, req.content, base_dir=req.cwd or os.getcwd())
        return {"ok": True, "path": saved}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/scan-code")
def api_scan_code(req: ScanCodeRequest) -> dict[str, Any]:
    try:
        cwd = req.cwd or os.getcwd()
        root = req.root if os.path.isabs(req.root) else os.path.join(cwd, req.root)
        files = scan_code_files(root, include_globs=req.include_globs, exclude_globs=req.exclude_globs, max_files=req.max_files)
        payload: dict[str, Any] = {"files": [{"path": f.path, "relpath": f.relpath, "language": f.language_hint, "size": f.size} for f in files]}
        if req.include_context:
            payload["context"] = format_code_context(files, max_chars=req.max_chars)
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/decompose")
def api_decompose(req: DecomposeRequest) -> dict[str, Any]:
    cwd = req.cwd or os.getcwd()
    dec = FunctionalDecomposer(cwd=cwd)
    try:
        result = dec.decompose(goal=req.goal, language=req.language, timeout=req.timeout, context=req.context or "", context_paths=req.context_paths, context_globs=req.context_globs, context_max_chars=req.context_max_chars)
        return dec.to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        dec.close()


@app.post("/api/build")
def api_build(req: BuildRequest) -> dict[str, Any]:
    cwd = req.cwd or os.getcwd()
    output_dir = req.output_dir or os.path.join(tempfile.gettempdir(), "acp-funcforge-build")
    output_dir = os.path.abspath(output_dir)
    dec = FunctionalDecomposer(cwd=cwd)
    builder = SoftwareBuilder(cwd=output_dir)
    try:
        decomposition = dec.decompose(goal=req.goal, language=req.language, timeout=min(req.timeout, 600), context=req.context or "", context_paths=req.context_paths, context_globs=req.context_globs, context_max_chars=req.context_max_chars)
        # Release the decomposer's ACP server before the builder starts its own,
        # so two OpenCode servers don't run concurrently (causes session/new failures).
        dec.close()
        result = builder.build(goal=req.goal, decomposition=decomposition, output_dir=output_dir, language=req.language, timeout=req.timeout, context=req.context or "", context_paths=req.context_paths, context_globs=req.context_globs, context_max_chars=req.context_max_chars)
        return {
            "success": result.success,
            "output_dir": result.output_dir,
            "steps": [s.__dict__ for s in result.steps],
            "summary": result.summary,
            "decomposition": dec.to_dict(decomposition),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        dec.close()
        builder.close()
