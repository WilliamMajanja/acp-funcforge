from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ACPEvent:
    kind: str  # "notification" | "response" | "error" | "stderr" | "exit"
    method: str = ""
    params: Any = None
    result: Any = None
    error: Any = None
    raw: Any = None


class ACPClient:
    """Minimal ACP (Agent Client Protocol) client over stdio JSON-RPC.

    Spawns `opencode acp` locally and communicates via newline-delimited JSON-RPC.
    """

    def __init__(
        self,
        command: Optional[list[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        print_logs: bool = False,
        event_handler: Optional[Callable[[ACPEvent], None]] = None,
    ) -> None:
        self.command = command or self._default_command(print_logs=print_logs)
        self.cwd = cwd or os.getcwd()
        self.env = {**os.environ, **(env or {})}
        self.event_handler = event_handler
        self.proc: Optional[subprocess.Popen[str]] = None
        self._id = 0
        self._lock = threading.Lock()
        self._pending: dict[Any, queue.Queue[dict[str, Any]]] = {}
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._updates: queue.Queue[dict[str, Any]] = queue.Queue()
        self._closed = False
        self.agent_info: Any = None
        self.agent_capabilities: Any = None

    @staticmethod
    def _default_command(print_logs: bool = False) -> list[str]:
        opencode = os.environ.get("OPENCODE_BIN", "opencode")
        cmd = [opencode]
        if print_logs:
            cmd.append("--print-logs")
        cmd.append("acp")
        return cmd

    def start(self) -> "ACPClient":
        if self.proc:
            return self
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()
        return self

    def close(self) -> None:
        self._closed = True
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def __enter__(self) -> "ACPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _emit(self, event: ACPEvent) -> None:
        if event.method in ("session/update", "session/notification", "notifications/message"):
            self._updates.put(event.raw or {"method": event.method, "params": event.params})
        if self.event_handler:
            try:
                self.event_handler(event)
            except Exception:
                pass

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            if self._closed:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._emit(ACPEvent(kind="error", error=f"non-json: {line[:200]}", raw=line))
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                q = self._pending.get(msg["id"])
                if q:
                    q.put(msg)
                else:
                    self._emit(ACPEvent(kind="response", result=msg.get("result"), error=msg.get("error"), raw=msg))
            elif "method" in msg:
                self._emit(ACPEvent(kind="notification", method=msg.get("method", ""), params=msg.get("params"), raw=msg))
                # JSON-RPC request from agent (e.g. permission prompts) - auto-reject/ack minimally
                if "id" in msg:
                    self._handle_agent_request(msg)
            else:
                self._emit(ACPEvent(kind="response", raw=msg))
        self._emit(ACPEvent(kind="exit"))

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            if self._closed:
                break
            self._emit(ACPEvent(kind="stderr", raw=line.rstrip()))

    def _handle_agent_request(self, msg: dict[str, Any]) -> None:
        # Minimal auto-handling so the agent isn't blocked on client capabilities we don't implement.
        # Supports reading/writing code in any language as UTF text (with safe decoding fallbacks).
        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        result: Any = {}
        if method == "session/request_permission":
            # ACP permission request shape varies; try common deny/allow-safe defaults.
            result = {"outcome": {"outcome": "selected", "optionId": "reject"}}
            opts = params.get("options") or []
            for o in opts:
                oid = (o.get("optionId") or o.get("id") or "").lower()
                if "allow" in oid or "once" in oid:
                    result = {"outcome": {"outcome": "selected", "optionId": o.get("optionId") or o.get("id")}}
                    break
        elif method in ("fs/read_text_file", "fs/readTextFile", "read_text_file", "readTextFile"):
            path = params.get("path") or params.get("uri") or params.get("file")
            try:
                from .filesystem import read_text_file
                cf = read_text_file(path, base_dir=self.cwd)
                result = {"content": cf.content, "path": cf.path}
            except Exception as e:
                self._send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}})
                return
        elif method in ("fs/write_text_file", "fs/writeTextFile", "write_text_file", "writeTextFile"):
            path = params.get("path") or params.get("uri") or params.get("file")
            content = params.get("content")
            if content is None:
                content = params.get("text", "")
            try:
                from .filesystem import write_text_file
                saved = write_text_file(path, content, base_dir=self.cwd)
                result = {"path": saved}
            except Exception as e:
                self._send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}})
                return
        self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send(self, obj: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("ACP process not started")
        data = json.dumps(obj, ensure_ascii=False)
        with self._lock:
            self.proc.stdin.write(data + "\n")
            self.proc.stdin.flush()

    def request(self, method: str, params: Optional[dict[str, Any]] = None, timeout: float = 120.0) -> Any:
        self.start()
        self._id += 1
        req_id = self._id
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending[req_id] = q
        try:
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
            msg = q.get(timeout=timeout)
        finally:
            self._pending.pop(req_id, None)
        if "error" in msg:
            raise RuntimeError(f"ACP {method} error: {msg['error']}")
        return msg.get("result")

    def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        self.start()
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self, protocol_version: int = 1) -> Any:
        params = {
            "protocolVersion": protocol_version,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": False,
            },
            "clientInfo": {"name": "acp-funcforge", "title": "ACP FuncForge", "version": "0.1.0"},
        }
        result = self.request("initialize", params, timeout=60.0)
        self.agent_info = (result or {}).get("agentInfo")
        self.agent_capabilities = (result or {}).get("agentCapabilities")
        try:
            self.notify("initialized", {})
        except Exception:
            pass
        return result

    def new_session(self, cwd: Optional[str] = None, mcp_servers: Optional[list[Any]] = None) -> str:
        params: dict[str, Any] = {"cwd": os.path.abspath(cwd or self.cwd), "mcpServers": mcp_servers or []}
        result = self.request("session/new", params, timeout=120.0)
        sid = (result or {}).get("sessionId") or (result or {}).get("session", {}).get("id")
        if not sid:
            raise RuntimeError(f"session/new returned no sessionId: {result}")
        return sid

    def prompt(self, session_id: str, text: str, timeout: float = 600.0) -> dict[str, Any]:
        # Drain old updates
        while True:
            try:
                self._updates.get_nowait()
            except queue.Empty:
                break
        params = {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": text}],
        }
        # ACP session/prompt: result is returned when the turn completes; text often streams via session/update.
        result = self.request("session/prompt", params, timeout=timeout)
        chunks: list[str] = []
        # Collect updates that arrived during/just after the request.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                upd = self._updates.get(timeout=0.1)
                t = self._extract_text(upd)
                if t:
                    chunks.append(t)
            except queue.Empty:
                # if we've already collected some text and queue stays empty, stop early
                if chunks:
                    break
        collected = "".join(chunks).strip()
        # Some agents may include text in the result payload.
        if not collected:
            collected = self._extract_text({"params": result} if isinstance(result, dict) else {"result": result})
        return {"result": result, "updates_text": collected}

    @staticmethod
    def _extract_text(update: dict[str, Any]) -> str:
        if update is None:
            return ""
        if isinstance(update, str):
            return update
        p = update.get("params") if isinstance(update, dict) else {}
        if not isinstance(p, dict):
            p = {}
        # ACP session/update variants: params.update.{sessionUpdate,content}, agent message chunks, deltas, etc.
        candidates: list[Any] = [
            p,
            p.get("update"),
            p.get("message"),
            p.get("delta"),
            p.get("result"),
            update.get("result") if isinstance(update, dict) else None,
            update,
        ]
        for c in candidates:
            if not c:
                continue
            if isinstance(c, str):
                return c
            if isinstance(c, dict):
                # direct text/content
                for key in ("text", "message", "output", "outputText"):
                    v = c.get(key)
                    if isinstance(v, str) and v:
                        return v
                # ACP chunk shapes: {sessionUpdate:"agent_message_chunk", content:{type:"text",text:"..."}}
                content = c.get("content")
                txt = ACPClient._extract_content(content)
                if txt:
                    return txt
                # nested update
                if isinstance(c.get("update"), dict):
                    txt = ACPClient._extract_text({"params": c.get("update")})
                    if txt:
                        return txt
                # content list on candidate
                if isinstance(c.get("parts"), list):
                    txt = ACPClient._extract_content(c.get("parts"))
                    if txt:
                        return txt
        return ""

    @staticmethod
    def _extract_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if content.get("type") == "text" and isinstance(content.get("text"), str):
                return content["text"]
            if isinstance(content.get("text"), str):
                return content["text"]
            if "content" in content:
                return ACPClient._extract_content(content.get("content"))
            if "parts" in content:
                return ACPClient._extract_content(content.get("parts"))
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                t = ACPClient._extract_content(item)
                if t:
                    parts.append(t)
            return "".join(parts)
        return ""
