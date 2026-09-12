"""Bounded multi-step execution for Termux-MCP.

The runner deliberately does not invent plans or replay failed side-effecting
steps. It executes an explicit list supplied by the caller and returns once at
the end. Output can be compacted so deterministic intermediate stdout does not
consume the chat model's context budget.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable

MAX_STEPS = 20
DEFAULT_STEP_TIMEOUT = 30.0
OUTPUT_MODES = {"compact", "normal", "full"}


class StepRunnerError(ValueError):
    pass


def _failed(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("blocked") or result.get("confirmation_required"):
        return True
    if result.get("error"):
        return True
    exit_code = result.get("exit_code")
    return isinstance(exit_code, int) and exit_code != 0


def _lookup_path(value: Any, path: str) -> Any:
    """Resolve a dotted path through dict/list values for simple conditions."""
    current = value
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _condition_met(condition: Any, results: list[dict[str, Any]]) -> bool:
    """Evaluate a deliberately small, non-executable step condition.

    Format: {"step": 1, "path": "result.exit_code", "equals": 0}.
    `exists` can be used instead of `equals`. Conditions only inspect already
    completed steps and never evaluate Python/shell expressions.
    """
    if condition in (None, {}, True):
        return True
    if condition is False or not isinstance(condition, dict):
        return False
    step_number = condition.get("step")
    if not isinstance(step_number, int) or step_number < 1 or step_number > len(results):
        return False
    value = _lookup_path(results[step_number - 1], str(condition.get("path", "result")))
    if "exists" in condition:
        return (value is not None) is bool(condition["exists"])
    if "equals" in condition:
        return value == condition["equals"]
    if "not_equals" in condition:
        return value != condition["not_equals"]
    return bool(value)


def _trim_string(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    head = max(1, limit // 2)
    tail = max(1, limit - head - 34)
    return value[:head] + f"\n...[{len(value) - head - tail} chars omitted]...\n" + value[-tail:]


def _compact_value(value: Any, *, string_limit: int, list_limit: int, depth: int = 0) -> Any:
    """Bound result payload size without hiding status/error metadata."""
    if depth >= 4:
        if isinstance(value, (dict, list)):
            return "...[nested value omitted]..."
        return _trim_string(value, string_limit) if isinstance(value, str) else value
    if isinstance(value, str):
        return _trim_string(value, string_limit)
    if isinstance(value, list):
        items = [
            _compact_value(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1)
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            items.append(f"...[{len(value) - list_limit} items omitted]...")
        return items
    if isinstance(value, dict):
        return {
            key: _compact_value(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1)
            for key, item in value.items()
        }
    return value


def _render_result(item: dict[str, Any], output_mode: str) -> dict[str, Any]:
    if output_mode == "full":
        return item
    limits = (1200, 12) if output_mode == "normal" else (400, 6)
    return _compact_value(item, string_limit=limits[0], list_limit=limits[1])


async def run_steps(
    steps: list[dict[str, Any]],
    dispatcher: Callable[[str, dict[str, Any]], Awaitable[Any]],
    *,
    stop_on_error: bool = True,
    step_timeout: float = DEFAULT_STEP_TIMEOUT,
    output_mode: str = "compact",
) -> dict[str, Any]:
    """Execute explicit steps sequentially and return one aggregate response."""
    if not isinstance(steps, list) or not steps:
        raise StepRunnerError("steps must be a non-empty list")
    if len(steps) > MAX_STEPS:
        raise StepRunnerError(f"too many steps: maximum is {MAX_STEPS}")
    if step_timeout <= 0 or step_timeout > 300:
        raise StepRunnerError("step_timeout must be > 0 and <= 300 seconds")
    output_mode = str(output_mode).strip().lower()
    if output_mode not in OUTPUT_MODES:
        raise StepRunnerError("output_mode must be compact, normal, or full")

    started = time.monotonic()
    results: list[dict[str, Any]] = []
    stopped = False
    skipped = 0

    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            raise StepRunnerError(f"step {index} must be an object")
        tool = str(raw.get("tool", "")).strip()
        arguments = raw.get("arguments", {})
        if not tool:
            raise StepRunnerError(f"step {index} is missing tool")
        if not isinstance(arguments, dict):
            raise StepRunnerError(f"step {index} arguments must be an object")

        if not _condition_met(raw.get("when"), results):
            results.append({"step": index, "tool": tool, "ok": True, "skipped": True, "duration_ms": 0})
            skipped += 1
            continue

        step_started = time.monotonic()
        try:
            value = await asyncio.wait_for(dispatcher(tool, arguments), timeout=step_timeout)
            failed = _failed(value)
            item = {
                "step": index,
                "tool": tool,
                "ok": not failed,
                "duration_ms": round((time.monotonic() - step_started) * 1000),
                "result": value,
            }
        except asyncio.TimeoutError:
            failed = True
            item = {
                "step": index,
                "tool": tool,
                "ok": False,
                "duration_ms": round((time.monotonic() - step_started) * 1000),
                "error": f"step timed out after {step_timeout:g}s",
            }
        except Exception as exc:
            failed = True
            item = {
                "step": index,
                "tool": tool,
                "ok": False,
                "duration_ms": round((time.monotonic() - step_started) * 1000),
                "error": str(exc),
            }

        results.append(item)
        if failed and stop_on_error:
            stopped = index < len(steps)
            break

    executed = [item for item in results if not item.get("skipped")]
    succeeded = sum(1 for item in executed if item["ok"])
    failed_count = len(executed) - succeeded
    return {
        "ok": failed_count == 0 and not stopped,
        "requested_steps": len(steps),
        "executed_steps": len(executed),
        "skipped_steps": skipped,
        "succeeded": succeeded,
        "failed": failed_count,
        "stopped_early": stopped,
        "output_mode": output_mode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "results": [_render_result(item, output_mode) for item in results],
    }
