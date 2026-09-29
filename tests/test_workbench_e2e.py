"""A stranger-AI lifecycle test over the real MCP transport."""
import asyncio, json, socket, threading, time
import httpx, uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from termux_mcp import config, workbench
from termux_mcp.mcp_server import _build_mcp_app


def _free_port():
    s=socket.socket(); s.bind(("127.0.0.1",0)); p=s.getsockname()[1]; s.close(); return p


def _payload(result):
    return json.loads(result.content[0].text)


def test_stranger_ai_can_complete_workbench_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "DEFAULT_ROOT", tmp_path / "workbench")
    port=_free_port(); app=_build_mcp_app()
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="error"))
    thread=threading.Thread(target=server.run,daemon=True); thread.start()
    url=f"http://127.0.0.1:{port}/mcp"
    for _ in range(100):
        try: httpx.get(url,timeout=.2); break
        except Exception: time.sleep(.03)

    async def session_one():
        async with streamablehttp_client(url,headers={"Authorization":f"Bearer {config.AUTH_TOKEN}"}) as (read,write,_):
            async with ClientSession(read,write) as session:
                init=await session.initialize()
                assert "call workbench_context" in init.instructions
                first=_payload(await session.call_tool("workbench_context",{}))
                assert first["boxes"] == []
                made=_payload(await session.call_tool("workbench_new_box",{"name":"stranger-demo"}))
                assert made["created"] is True
                # Simulate deliberate project-truth maintenance through the normal filesystem.
                readme=workbench.DEFAULT_ROOT/"boxes"/"stranger-demo"/"README.md"
                readme.write_text("# stranger-demo\n\n## Current state\nfirst session verified\n")
                saved=_payload(await session.call_tool("workbench_checkpoint",{
                    "box":"stranger-demo","goal":"prove lifecycle","state":"first session verified",
                    "next_action":"resume from handoff","log":"first session completed"
                }))
                assert saved["saved"] is True

    async def session_two():
        async with streamablehttp_client(url,headers={"Authorization":f"Bearer {config.AUTH_TOKEN}"}) as (read,write,_):
            async with ClientSession(read,write) as session:
                await session.initialize()
                ctx=_payload(await session.call_tool("workbench_context",{}))
                assert ctx["boxes"][0]["name"] == "stranger-demo"
                assert ctx["boxes"][0]["contract_ok"] is True
                assert "resume from handoff" in ctx["notes"]["handoff"]
                assert "first session verified" in ctx["boxes"][0]["summary"]
                assert _payload(await session.call_tool("workbench_doctor",{}))["ok"] is True

    try:
        asyncio.run(session_one()); asyncio.run(session_two())
    finally:
        server.should_exit=True; thread.join(timeout=5)
