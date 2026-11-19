from __future__ import annotations

import json

from acp_funcforge.builder import SoftwareBuilder, BuildStep


def test_parse_summary_json_extracts_object():
    text = 'blah {"status": "passing", "ran": "pytest", "notes": "ok"} trailing'
    d = SoftwareBuilder._parse_summary_json(text)
    assert d["status"] == "passing"
    assert d["ran"] == "pytest"


def test_parse_summary_json_garbage_returns_empty():
    assert SoftwareBuilder._parse_summary_json("no json here") == {}


def test_list_artifacts_excludes_state_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.py").write_text("x = 1")
    (out / ".funcforge").mkdir()
    (out / ".funcforge" / "state.json").write_text("{}")
    arts = SoftwareBuilder._list_artifacts(str(out))
    assert "a.py" in arts
    assert not any(".funcforge" in a for a in arts)


def test_build_step_defaults():
    s = BuildStep(name="x", status="ok")
    assert s.artifacts == []
