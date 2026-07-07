import json
import pytest


@pytest.fixture(autouse=True)
def carryover_home(tmp_path, monkeypatch):
    """Every test gets an isolated CARRYOVER_HOME."""
    home = tmp_path / "carryover-home"
    monkeypatch.setenv("CARRYOVER_HOME", str(home))
    return home


def make_event(**kw):
    base = {
        "session_id": "s1",
        "cwd": "/tmp",
        "hook_event_name": "PostToolUse",
        "transcript_path": "",
    }
    base.update(kw)
    return base


def write_transcript(path, lines):
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
