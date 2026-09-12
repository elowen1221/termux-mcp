import asyncio

from termux_mcp import managed_resilience


def test_cache_remember_search_and_forget(tmp_path, monkeypatch):
    cache = tmp_path / "tools.json"
    monkeypatch.setattr(managed_resilience, "CACHE_FILE", cache)

    managed_resilience.remember(
        "walnut-weather",
        "http",
        [{"name": "get_weather", "description": "Get current weather forecast"}],
    )
    snapshot = managed_resilience.cached("walnut-weather")
    assert snapshot["count"] == 1

    result = managed_resilience.search("weather", [
        {"name": "walnut-weather", "source": "https://example.test/mcp", "transport": "http"}
    ])
    assert result["count"] >= 1
    assert any(item["server"] == "walnut-weather" for item in result["matches"])
    assert any(item.get("tool") == "get_weather" for item in result["matches"])

    managed_resilience.forget("walnut-weather")
    assert managed_resilience.cached("walnut-weather") is None


def test_retry_recovers_after_transient_failures():
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    result, error, count = asyncio.run(
        managed_resilience.retry(flaky, timeout=1, retries=2)
    )
    assert result == "ok"
    assert error is None
    assert count == 3


def test_retry_returns_last_error_when_exhausted():
    async def broken():
        raise RuntimeError("still broken")

    result, error, count = asyncio.run(
        managed_resilience.retry(broken, timeout=1, retries=1)
    )
    assert result is None
    assert isinstance(error, RuntimeError)
    assert count == 2
