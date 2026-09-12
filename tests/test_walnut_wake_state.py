import json

import pytest

from termux_mcp import walnut_wake_state as wake_state


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "walnut-wake"
    monkeypatch.setattr(wake_state, "STATE_DIR", state_dir)
    monkeypatch.setattr(wake_state, "STATE_FILE", state_dir / "state.json")
    return state_dir


def test_read_state_missing_returns_empty(isolated_state):
    assert wake_state.read_state() == {}


def test_update_state_round_trip_and_bounds(isolated_state):
    state = wake_state.update_state(
        activity="checked board",
        tools=[f"tool-{i}" for i in range(12)],
        touched_tasks=[f"task-{i}" for i in range(12)],
        note="small wake",
    )

    assert state["last_activity"] == "checked board"
    assert state["recently_used_tools"] == [f"tool-{i}" for i in range(2, 12)]
    assert state["recently_touched_tasks"] == [f"task-{i}" for i in range(2, 12)]
    assert wake_state.read_state() == state
    assert wake_state.STATE_FILE.stat().st_mode & 0o777 == 0o600


def test_update_preserves_unspecified_fields(isolated_state):
    first = wake_state.update_state(activity="first", tools=["inbox"], note="keep me")
    second = wake_state.update_state(activity="second")

    assert second["last_activity"] == "second"
    assert second["recently_used_tools"] == ["inbox"]
    assert second["note"] == "keep me"
    assert second["last_wake"] >= first["last_wake"]


def test_invalid_json_recovers_as_empty(isolated_state):
    isolated_state.mkdir(parents=True)
    wake_state.STATE_FILE.write_text("not json")
    assert wake_state.read_state() == {}
