from __future__ import annotations

import pytest

from acp_funcforge import state as state_store


def test_state_roundtrip(tmp_path):
    cwd = str(tmp_path)
    assert state_store.load_state(cwd) == {}
    state_store.update_state(cwd, decompose_session="ses_1", last_goal="g")
    assert state_store.get_session(cwd, "decompose_session") == "ses_1"
    assert state_store.load_state(cwd)["last_goal"] == "g"
    state_store.clear(cwd)
    assert state_store.load_state(cwd) == {}


def test_state_corrupt_file_is_ignored(tmp_path):
    cwd = str(tmp_path)
    d = tmp_path / ".funcforge"
    d.mkdir()
    (d / "state.json").write_text("not json{")
    assert state_store.load_state(cwd) == {}
