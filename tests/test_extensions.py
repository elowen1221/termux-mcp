from termux_mcp import config, extensions


class FakeMCP:
    def __init__(self):
        self.tools = {}
    def tool(self, name):
        def deco(fn):
            self.tools[name] = fn
            return fn
        return deco


def test_local_extension_loader(tmp_path, monkeypatch):
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        "def register(mcp, step_tools):\n"
        "    def hello(name: str = 'world'): return {'hello': name}\n"
        "    mcp.tool(name='hello')(hello)\n"
        "    step_tools['hello'] = hello\n"
    )
    monkeypatch.setattr(config, "_FILE_VALUES", {extensions.ENV_NAME: str(plugin)})
    mcp = FakeMCP(); steps = {}
    loaded = extensions.register_local_extensions(mcp, steps)
    assert loaded == [str(plugin.resolve())]
    assert mcp.tools['hello']('x') == {'hello': 'x'}
    assert steps['hello']('y') == {'hello': 'y'}


def test_missing_local_extension_is_ignored(monkeypatch):
    monkeypatch.setattr(config, "_FILE_VALUES", {extensions.ENV_NAME: "/missing/plugin.py"})
    assert extensions.register_local_extensions(FakeMCP(), {}) == []
