"""Persistent per-project state: resumable ACP session ids and last run info.

State is stored in ``<project>/.funcforge/state.json`` so decompose/build can
resume the previous ACP session instead of starting from scratch.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

_STATE_DIR = ".funcforge"
_STATE_FILE = "state.json"
_lock = threading.Lock()


def _state_path(cwd: str) -> str:
    return os.path.join(os.path.abspath(cwd), _STATE_DIR, _STATE_FILE)


def load_state(cwd: str) -> dict[str, Any]:
    try:
        with open(_state_path(cwd), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(cwd: str, state: dict[str, Any]) -> None:
    with _lock:
        os.makedirs(os.path.dirname(_state_path(cwd)), exist_ok=True)
        with open(_state_path(cwd), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


def update_state(cwd: str, **updates: Any) -> dict[str, Any]:
    state = load_state(cwd)
    state.update(updates)
    save_state(cwd, state)
    return state


def get_session(cwd: str, key: str) -> Optional[str]:
    return load_state(cwd).get(key)


def clear(cwd: str) -> None:
    try:
        os.remove(_state_path(cwd))
    except FileNotFoundError:
        pass
    except Exception:
        pass
