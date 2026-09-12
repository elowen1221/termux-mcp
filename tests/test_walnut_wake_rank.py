from termux_mcp.walnut_wake_rank import rank_candidates


def test_short_run_filters_deep_and_prefers_tiny():
    ranked = rank_candidates([
        {"id": "normal", "effort": "normal"},
        {"id": "deep", "effort": "deep"},
        {"id": "tiny", "effort": "tiny"},
    ])
    assert [x["id"] for x in ranked] == ["tiny", "normal"]


def test_recent_task_and_tool_are_cooled_down():
    ranked = rank_candidates([
        {"id": "fresh", "effort": "normal", "tool": "game"},
        {"id": "recent", "effort": "normal", "tool": "weather"},
    ], {"recently_touched_tasks": ["recent"], "recently_used_tools": ["weather"]})
    assert ranked[0]["id"] == "fresh"
    assert "cooldown:task" in ranked[1]["rank_reasons"]
    assert "cooldown:tool" in ranked[1]["rank_reasons"]


def test_input_is_not_mutated_and_ties_are_stable():
    candidates = [{"id": "a", "effort": "normal"}, {"id": "b", "effort": "normal"}]
    ranked = rank_candidates(candidates)
    assert [x["id"] for x in ranked] == ["a", "b"]
    assert "rank_score" not in candidates[0]


def test_capability_identity_is_distinct_from_transport():
    ranked = rank_candidates([
        {"id": "weather-task", "effort": "tiny", "capability": "weather", "tool": "termux-mcp1.5"},
        {"id": "board-task", "effort": "tiny", "capability": "walnut_board", "tool": "termux-mcp1.5"},
    ], {"recently_used_tools": ["weather"]})
    assert ranked[0]["id"] == "board-task"
    assert "cooldown:tool" in ranked[1]["rank_reasons"]
    assert "cooldown:tool" not in ranked[0]["rank_reasons"]
