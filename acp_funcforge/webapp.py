from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
from typing import Any, Generator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
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
    :root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950;--bad:#f85149}
    *{box-sizing:border-box}
    body{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}
    header{padding:1rem 1.5rem;border-bottom:1px solid var(--border);display:flex;gap:1rem;align-items:baseline}
    header h1{margin:0;font-size:1.2rem}
    header span{color:var(--muted);font-size:.85rem}
    main{max-width:1100px;margin:0 auto;padding:1.5rem;display:grid;grid-template-columns:340px 1fr;gap:1.25rem}
    .panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:1rem}
    .panel h2{margin:.2rem 0 .8rem;font-size:.95rem}
    label{display:block;font-size:.78rem;color:var(--muted);margin:.5rem 0 .2rem}
    textarea,input{width:100%;padding:.5rem;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font:inherit}
    textarea{min-height:80px;resize:vertical}
    button{padding:.55rem .9rem;margin-top:.7rem;cursor:pointer;background:var(--accent);color:#04121f;border:0;border-radius:6px;font-weight:600}
    button:disabled{opacity:.5;cursor:wait}
    button.secondary{background:var(--border);color:var(--text)}
    .phase{display:flex;gap:.4rem;margin:.4rem 0}
    .phase div{flex:1;text-align:center;padding:.4rem;border-radius:6px;background:var(--bg);border:1px solid var(--border);font-size:.8rem;color:var(--muted)}
    .phase div.active{border-color:var(--accent);color:var(--accent)}
    .phase div.ok{border-color:var(--ok);color:var(--ok)}
    .phase div.bad{border-color:var(--bad);color:var(--bad)}
    pre{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:.8rem;min-height:220px;max-height:480px;overflow:auto;white-space:pre-wrap;font-size:.82rem;margin:.6rem 0 0}
    .steps{margin-top:.6rem;font-size:.8rem}
    .steps div{padding:.3rem .5rem;border-bottom:1px solid var(--border)}
    .badge{padding:.05rem .4rem;border-radius:4px;font-size:.72rem}
    .badge.ok{background:rgba(63,185,80,.15);color:var(--ok)}
    .badge.bad{background:rgba(248,81,73,.15);color:var(--bad)}
    small{color:var(--muted)}
    @media(max-width:800px){main{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <header><h1>ACP FuncForge</h1><span>plan &rarr; decompose &rarr; build, streamed live from local OpenCode ACP agents</span></header>
  <main>
    <section class="panel" id="left">
      <h2>Goal</h2>
      <textarea id="goal" placeholder="Describe what to build..."></textarea>
      <div class="phase">
        <div id="ph-plan">Plan</div><div id="ph-decompose">Decompose</div><div id="ph-build">Build</div><div id="ph-verify">Verify</div>
      </div>
      <div class="row" style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem">
        <div><label>Language</label><input id="lang" value="python"/></div>
        <div><label>Output dir</label><input id="outdir" placeholder="temp folder"/></div>
      </div>
      <label>Context paths (comma)</label><input id="ctx" placeholder="src/, main.py"/>
      <button id="run" onclick="runPipeline()">Decompose + Build &#9654;</button>
      <button class="secondary" onclick="runPipeline(true)">Decompose only</button>
      <button class="secondary" onclick="reset()">Reset</button>
      <small>Streams agent output live via SSE.</small>
    </section>
    <section class="panel">
      <h2>Agent output</h2>
      <pre id="out">Ready.</pre>
      <div id="steps" class="steps"></div>
    </section>
  </main>
<script>
let phase = null;
function setPhase(name, state){
  for (const p of ['plan','decompose','build','verify']){
    const el = document.getElementById('ph-'+p);
    el.className = p===name ? (state||'active') : '';
  }
}
function appendOut(t){ const o=document.getElementById('out'); o.textContent+=t; o.scrollTop=o.scrollHeight; }
function addStep(s){
  const d=document.createElement('div');
  const cls = s.status==='ok'||s.status==='passing' ? 'ok' : (s.status==='failed' ? 'bad' : '');
  d.innerHTML = '<span class="badge '+cls+'">'+s.status+'</span> <b>'+s.name+'</b> &mdash; '+String(s.detail||'').replace(/</g,'&lt;');
  document.getElementById('steps').appendChild(d);
}
async function runPipeline(decomposeOnly){
  reset(false);
  document.getElementById('run').disabled = true;
  const body = {
    goal: document.getElementById('goal').value,
    language: document.getElementById('lang').value || 'python',
    output_dir: document.getElementById('outdir').value || null,
    context_paths: (document.getElementById('ctx').value||'').split(',').map(s=>s.trim()).filter(Boolean)
  };
  const url = decomposeOnly ? '/api/decompose/stream' : '/api/build/stream';
  setPhase('plan');
  try{
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf='';
    while(true){
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf('\n\n')) >= 0){
        const block = buf.slice(0, idx); buf = buf.slice(idx+2);
        const ev = (block.match(/event: (.*)/)||[])[1];
        const data = block.replace(/event: .*\n/, '').replace('data: ', '');
        if (ev === 'text'){
          setPhase('decompose');
          appendOut(JSON.parse(data));
        } else if (ev === 'done'){
          const v = JSON.parse(data);
          document.getElementById('out').textContent += '\n\n=== RESULT ===\n' + JSON.stringify(v, null, 2);
          setPhase('verify', v.success ? 'ok' : 'bad');
          if (v.steps) v.steps.forEach(addStep);
        } else if (ev === 'error'){
          document.getElementById('out').textContent += '\n\n=== ERROR ===\n' + (JSON.parse(data).detail||'');
          setPhase(phase, 'bad');
        }
      }
    }
  } catch(e){ appendOut('\n[connection error] '+e); setPhase(phase,'bad'); }
  document.getElementById('run').disabled = false;
}
function reset(clearOut){
  if (clearOut !== false){ document.getElementById('out').textContent=''; document.getElementById('steps').innerHTML=''; }
  setPhase(null);
}
</script>
</body>
</html>"""


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_streaming(work: Any, req: Any) -> Generator[str, None, None]:
    """Run `work(on_text)` in a thread; stream text/step/done/error events as SSE."""
    q: queue.Queue[tuple[str, Any]] = queue.Queue()

    def on_text(chunk: str) -> None:
        q.put(("text", chunk))

    def runner() -> None:
        try:
            result = work(on_text)
            q.put(("done", result))
        except Exception as e:
            q.put(("error", {"detail": str(e)}))

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    while True:
        try:
            kind, payload = q.get(timeout=1800.0)
        except queue.Empty:
            yield _sse("error", {"detail": "stream timed out"})
            return
        if kind == "text":
            yield _sse("text", payload)
        elif kind == "done":
            yield _sse("done", payload)
            return
        else:
            yield _sse("error", payload)
            return


@app.post("/api/decompose/stream")
def api_decompose_stream(req: DecomposeRequest) -> StreamingResponse:
    cwd = req.cwd or os.getcwd()

    def work(on_text: Any) -> dict[str, Any]:
        dec = FunctionalDecomposer(cwd=cwd)
        try:
            result = dec.decompose(
                goal=req.goal, language=req.language, timeout=req.timeout,
                context=req.context or "", context_paths=req.context_paths,
                context_globs=req.context_globs, context_max_chars=req.context_max_chars,
                on_text=on_text,
            )
            return dec.to_dict(result)
        finally:
            dec.close()

    return StreamingResponse(_run_streaming(work, req), media_type="text/event-stream")


@app.post("/api/build/stream")
def api_build_stream(req: BuildRequest) -> StreamingResponse:
    cwd = req.cwd or os.getcwd()
    output_dir = os.path.abspath(req.output_dir or os.path.join(tempfile.gettempdir(), "acp-funcforge-build"))

    def work(on_text: Any) -> dict[str, Any]:
        dec = FunctionalDecomposer(cwd=cwd)
        try:
            decomposition = dec.decompose(
                goal=req.goal, language=req.language, timeout=min(req.timeout, 600),
                context=req.context or "", context_paths=req.context_paths,
                context_globs=req.context_globs, context_max_chars=req.context_max_chars,
                on_text=on_text,
            )
            decomposition_data = dec.to_dict(decomposition)
        finally:
            dec.close()
        builder = SoftwareBuilder(cwd=output_dir)
        try:
            result = builder.build(
                goal=req.goal, decomposition=decomposition, output_dir=output_dir,
                language=req.language, timeout=req.timeout, context=req.context or "",
                context_paths=req.context_paths, context_globs=req.context_globs,
                context_max_chars=req.context_max_chars, on_text=on_text,
            )
            return {
                "success": result.success,
                "output_dir": result.output_dir,
                "steps": [s.__dict__ for s in result.steps],
                "summary": result.summary,
                "decomposition": decomposition_data,
            }
        finally:
            builder.close()

    return StreamingResponse(_run_streaming(work, req), media_type="text/event-stream")


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
