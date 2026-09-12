import pytest

from termux_mcp import walnut_journal


def _isolated_journal(tmp_path, monkeypatch):
    state = tmp_path / "walnut-journal"
    monkeypatch.setattr(walnut_journal, "STATE_DIR", state)
    monkeypatch.setattr(walnut_journal, "DB", state / "journal.sqlite3")


def test_append_and_recent_entries(tmp_path, monkeypatch):
    _isolated_journal(tmp_path, monkeypatch)
    first = walnut_journal.append_entry(
        "implemented the minimal journal store",
        related_task_ids=["task_1"],
        source_refs=["wake"],
        note="bounded test note",
    )
    second = walnut_journal.append_entry("noticed a useful invariant", kind="observation")

    recent = walnut_journal.recent_entries(limit=10)
    assert [entry["id"] for entry in recent["entries"]] == [second["id"], first["id"]]
    assert recent["entries"][1]["related_task_ids"] == ["task_1"]
    assert recent["entries"][1]["source_refs"] == ["wake"]


def test_recent_entries_filters_kind(tmp_path, monkeypatch):
    _isolated_journal(tmp_path, monkeypatch)
    walnut_journal.append_entry("did a thing", kind="activity")
    reflection = walnut_journal.append_entry("thought about it", kind="reflection")

    result = walnut_journal.recent_entries(kind="reflection")
    assert [entry["id"] for entry in result["entries"]] == [reflection["id"]]


def test_validation_and_limit_bounds(tmp_path, monkeypatch):
    _isolated_journal(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        walnut_journal.append_entry("   ")
    with pytest.raises(ValueError):
        walnut_journal.append_entry("x", kind="dream")
    with pytest.raises(ValueError):
        walnut_journal.recent_entries(kind="dream")

    for i in range(3):
        walnut_journal.append_entry(f"entry {i}")
    assert len(walnut_journal.recent_entries(limit=2)["entries"]) == 2
