import asyncio

import pytest

from termux_mcp.step_runner import MAX_STEPS, StepRunnerError, run_steps


def test_run_steps_collects_results_without_intermediate_return():
    calls = []

    async def dispatch(tool, arguments):
        calls.append((tool, arguments))
        return {"value": arguments["value"]}

    result = asyncio.run(run_steps([
        {"tool": "one", "arguments": {"value": 1}},
        {"tool": "two", "arguments": {"value": 2}},
    ], dispatch, output_mode="full"))

    assert calls == [("one", {"value": 1}), ("two", {"value": 2})]
    assert result["ok"] is True
    assert result["executed_steps"] == 2
    assert [item["result"]["value"] for item in result["results"]] == [1, 2]


def test_run_steps_stops_on_error_by_default():
    async def dispatch(tool, arguments):
        if tool == "bad":
            return {"error": "boom"}
        return {"ok": True}

    result = asyncio.run(run_steps([
        {"tool": "ok"},
        {"tool": "bad"},
        {"tool": "never"},
    ], dispatch))

    assert result["ok"] is False
    assert result["executed_steps"] == 2
    assert result["stopped_early"] is True


def test_run_steps_can_continue_after_error():
    async def dispatch(tool, arguments):
        return {"exit_code": 1} if tool == "bad" else {"exit_code": 0}

    result = asyncio.run(run_steps([
        {"tool": "bad"},
        {"tool": "ok"},
    ], dispatch, stop_on_error=False))

    assert result["executed_steps"] == 2
    assert result["failed"] == 1
    assert result["succeeded"] == 1


def test_run_steps_treats_confirmation_as_stop():
    async def dispatch(tool, arguments):
        return {"confirmation_required": True}

    result = asyncio.run(run_steps([
        {"tool": "danger"},
        {"tool": "after"},
    ], dispatch))
    assert result["executed_steps"] == 1
    assert result["results"][0]["ok"] is False


def test_run_steps_validates_limits_and_output_mode():
    async def dispatch(tool, arguments):
        return {}

    with pytest.raises(StepRunnerError):
        asyncio.run(run_steps([], dispatch))
    with pytest.raises(StepRunnerError):
        asyncio.run(run_steps([{"tool": "x"}] * (MAX_STEPS + 1), dispatch))
    with pytest.raises(StepRunnerError):
        asyncio.run(run_steps([{"tool": "x"}], dispatch, output_mode="giant"))


def test_compact_output_trims_large_intermediate_text():
    async def dispatch(tool, arguments):
        return {"stdout": "x" * 5000, "exit_code": 0}

    result = asyncio.run(run_steps([{"tool": "shell"}], dispatch))
    stdout = result["results"][0]["result"]["stdout"]
    assert len(stdout) < 1000
    assert "chars omitted" in stdout
    assert result["output_mode"] == "compact"


def test_full_output_preserves_large_intermediate_text():
    async def dispatch(tool, arguments):
        return {"stdout": "x" * 5000, "exit_code": 0}

    result = asyncio.run(run_steps([{"tool": "shell"}], dispatch, output_mode="full"))
    assert len(result["results"][0]["result"]["stdout"]) == 5000


def test_conditional_step_can_skip_from_previous_result():
    calls = []

    async def dispatch(tool, arguments):
        calls.append(tool)
        return {"exit_code": 0, "value": tool}

    result = asyncio.run(run_steps([
        {"tool": "check"},
        {"tool": "repair", "when": {"step": 1, "path": "result.exit_code", "equals": 1}},
        {"tool": "verify", "when": {"step": 1, "path": "ok", "equals": True}},
    ], dispatch, output_mode="full"))

    assert calls == ["check", "verify"]
    assert result["skipped_steps"] == 1
    assert result["results"][1]["skipped"] is True
    assert result["ok"] is True
