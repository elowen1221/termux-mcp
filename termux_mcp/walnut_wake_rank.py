"""Pure candidate ranking helper for short Walnut Wake activity selection.

This module only ranks candidates. It does not mutate the Board or turn it into
an obligation queue.
"""
from __future__ import annotations

from typing import Any

_EFFORT_SCORE = {"tiny": 3, "normal": 2, "deep": 0}


def _capability(candidate: dict[str, Any]) -> str:
    """Return the activity capability used for cooldown, not its transport.

    ``capability`` is deliberately semantic (weather, island, walnut_board...).
    A connector such as termux-mcp1.5 may transport many unrelated activities
    and would make cooldown far too broad if used as the identity itself.
    ``tool`` remains a compatibility fallback for older callers/tests.
    """
    return str(candidate.get("capability") or candidate.get("tool") or "")


def rank_candidates(
    candidates: list[dict[str, Any]],
    wake_state: dict[str, Any] | None = None,
    short_run: bool = True,
) -> list[dict[str, Any]]:
    """Return ranked copies with ``rank_score`` and ``rank_reasons``.

    Deep work is excluded from short runs. Recently touched tasks and recently
    used capabilities receive cooldown penalties. A small novelty bonus only
    breaks otherwise-close choices; it is not an urgency or obligation signal.
    """
    state = wake_state or {}
    recent_tasks = {str(x) for x in state.get("recently_touched_tasks", [])}
    # The state field keeps its old name for compatibility, but values should be
    # semantic capability IDs rather than transport/connector names.
    recent_capabilities = {str(x) for x in state.get("recently_used_tools", [])}
    ranked: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        item = dict(candidate)
        effort = str(item.get("effort", "normal"))
        if short_run and effort == "deep":
            continue

        score = _EFFORT_SCORE.get(effort, 1)
        reasons = [f"effort:{effort}"]
        task_id = str(item.get("id", ""))
        capability = _capability(item)

        if task_id and task_id in recent_tasks:
            score -= 4
            reasons.append("cooldown:task")
        if capability and capability in recent_capabilities:
            score -= 2
            reasons.append("cooldown:tool")
        if task_id not in recent_tasks and (not capability or capability not in recent_capabilities):
            score += 1
            reasons.append("novelty")

        item["rank_score"] = score
        item["rank_reasons"] = reasons
        item["_input_order"] = index
        ranked.append(item)

    ranked.sort(key=lambda x: (-x["rank_score"], x["_input_order"]))
    for item in ranked:
        item.pop("_input_order", None)
    return ranked
