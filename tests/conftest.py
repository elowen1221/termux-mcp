"""Shared pytest fixtures and environment setup.

Environment variables MUST be set before termux_mcp is imported — config.py
reads them at import time. HOME is redirected to a temp dir so snapshot /
trash behavior never touches the real user home.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="termux-mcp-test-")
os.environ["HOME"] = _TMP
os.environ["TERMUX_MCP_AUTH_TOKEN"] = "test-token-0123456789abcdef"
os.environ["TERMUX_MCP_MCP_PORT"] = "18765"
os.environ["TERMUX_MCP_WORKSPACE"] = ""
# Loopback integration tests must never use a developer or CI machine's
# outbound proxy.
for _proxy_name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                    "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_proxy_name, None)
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
