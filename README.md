# Termux-MCP

> **Fork notice**: This repository is a fork of [termuxgpt/termux-mcp](https://github.com/termuxgpt/termux-mcp) (upstream, AGPL-3.0). All original code, copyright, and attribution belong to the upstream authors. This fork keeps the original REST API intact and adds a standards-compliant MCP layer on top of it.

## 快速安装（从空 Termux 开始）

已经安装好 Termux 后，可用一条命令完成环境检测、源码下载或安全更新、依赖安装与最终自检：

```bash
curl -fsSL https://raw.githubusercontent.com/lxy426329/Termux-MCP/main/scripts/bootstrap.sh | bash
```

第一次安装会自动进入萌系引导：选择 ChatGPT / Claude / Grok、选择权限，
然后启动服务并把唯一需要复制的 MCP URL 交给你。以后直接在 AI 对话框里操作即可。

如果希望逐步检查每条命令，继续阅读下面的零基础教程。

## Changes in this fork

This fork adds a minimal, standards-compliant **MCP (Model Context Protocol)** layer without removing the existing REST API:

- **MCP Streamable HTTP endpoint** at `/mcp` (port `8765` by default), built on the official `mcp` Python SDK (`mcp>=1.28,<2`) + `uvicorn`.
- **14 MCP tools**: 8 built-in device/file tools plus permission visibility and
  managed-MCP control (`mcp_install`, `mcp_list`, `mcp_inspect`, `mcp_call`, `mcp_remove`).
- **One-time friendly onboarding**: `termux-mcp setup` asks only for the target AI
  and permission level, starts the gateway, then prints one copy-ready URL.
- **Owner-selected permissions**: `read-only`, `standard`, or `full`; full mode is
  an explicit choice that lets the attached AI use Termux without repeated risk prompts.
- **MCP compatibility layer**: import an existing remote MCP URL, or clone and
  prepare common Python/Node.js MCP repositories from GitHub. Unusual projects can
  supply their documented stdio launch command. Remote imports try Streamable HTTP
  first and automatically fall back to legacy SSE during connection setup.
- **Bearer authentication** on the MCP endpoint via `Authorization: Bearer` header only — tokens in URL query parameters are **not** supported. All REST informational endpoints except `/ping` now require auth as well.
- **Shared operations layer** (`termux_mcp/operations.py`): REST and MCP call the same Python functions directly — the MCP layer does **not** proxy through the REST API over localhost.
- **Workspace / symlink protection**: optional `TERMUX_MCP_WORKSPACE` root restriction for the MCP filesystem tools; paths are resolved with `realpath` before boundary checks, so symlink escapes are rejected.
- **Preserved upstream security behavior**: risk classification (`get_risk_assessment()`), dangerous commands blocked, warning commands require confirmation, snapshot-before-write, trash-on-delete.
- **Structured tool responses**: `run_command` returns `stdout`, `stderr`, `exit_code`, `truncated`, `risk_level`, `snapshots`; `read_file` supports `offset`/`limit`.
- **One-command launcher**: `termux-mcp start` starts the server, waits for health, opens a public tunnel, and prints the final MCP URL. Also `stop` / `restart` / `status` / `logs` / `doctor` / `token`.
- **Server/tunnel lifecycle decoupling**: `termux-mcp restart` is **server-only by default** — the running tunnel, its PID and the verified public URL are preserved, so ChatGPT's saved MCP URL stays valid even though anonymous tunnel hostnames change between rebuilds. `restart --tunnel <mode>` rebuilds the tunnel; `restart --no-tunnel` stops it.
- **OAuth state persistence**: registered clients and refresh/access tokens survive server restarts (`~/.config/termux-mcp/oauth_state.json`, chmod 600, atomic writes). Authorization codes are never persisted. A server-only restart does not force ChatGPT to re-authorize.
- **Profile isolation**: `TERMUX_MCP_PROFILE=<name>` runs a fully separate instance (config dir, state dir, default ports) so a stable and a dev/test instance can coexist on one device without clobbering each other's PID / log / public_url / token / OAuth state.
- **Multi-tunnel support**: pinggy / cloudflare / localhost.run with automatic fallback (`--tunnel auto`).
- **Persistent config**: `~/.config/termux-mcp/config.env` (chmod 600), token auto-generated on first start.
- **Tests**: MCP authentication, workspace path traversal / symlink escape, dangerous & warning shell commands, REST/MCP shared-logic proof, launcher/tunnel/config unit tests, and a `tools/list` + `tools/call` smoke test.
- **Live smoke script**: `scripts/mcp_smoke.py` validates the running server end-to-end.
- **Bundled stdio example**: `examples/cute_demo_mcp.py` is a real three-tool MCP
  server exercised end-to-end through the managed-MCP gateway in CI.
- **Removed the stale upstream `.deb`** (`termux-mcp_1.0_all.deb`): it hardcoded `/usr/lib/python3.13/` and shipped the old upstream code without this fork's MCP layer. The supported install path is `bash scripts/install.sh` (pip-based, Python-version agnostic). `add-repo.sh` (upstream package repo) is kept for reference only.

---

# 从零开始：把 Termux-MCP 跑起来（零基础教程）

> 本教程假设你**完全不懂** Linux、Python、MCP、命令行。跟着做就行，每一步都告诉你复制什么、会看到什么、出红字怎么办。

## 第 1 步：安装 Termux

1. 打开手机上的 **F-Droid**（一个应用商店）。如果没有，先装 F-Droid。
2. 在 F-Droid 里搜索 **Termux**，安装它。
   - ⚠️ 不要从 Google Play 装 Termux（版本太旧）。
   - 也可以从 Termux 官网 https://termux.dev 下载。
3. 打开 Termux，你会看到一个黑色窗口，底部有光标在闪。这就是"终端"。

## 第 2 步：第一次打开 Termux

1. 第一次打开会下载一些基础文件，等它完成（出现 `$` 提示符）。
2. 如果提示要装什么插件，先不管。
3. 输入下面这条命令，按回车，给 Termux 访问手机存储的权限（后面备份要用）：

```
termux-setup-storage
```

- 手机会弹窗问是否允许，选**允许**。
- 看到 `$` 提示符就说明成功了。

## 第 3 步：更新软件包

复制下面这条命令，按回车：

```
pkg update -y && pkg upgrade -y
```

- **正常情况下会看到**：一堆 `Hit:...` / `Reading package lists...`，最后回到 `$`。
- **如果看到红字**：多半是网络问题。关掉 VPN 再试，或换 Wi-Fi 再试。多试几次。

## 第 4 步：安装 git

```
pkg install -y git
```

- 看到 `$` 提示符就成功了。

## 第 5 步：下载本仓库

```
git clone https://github.com/lxy426329/Termux-MCP.git
```

- **正常情况下会看到**：`Cloning into 'Termux-MCP'...` 然后回到 `$`。
- **如果看到红字**：网络问题，重试或换网络。

## 第 6 步：进入目录

```
cd Termux-MCP
```

- 输入 `pwd` 按回车，应该显示 `/data/data/com.termux/files/home/Termux-MCP`。

## 第 7 步：安装

```
bash scripts/install.sh
```

- 这个脚本会自动：更新软件包 → 装 python/git/openssh → 安装本项目（含 MCP SDK 和 uvicorn）→ 生成一个随机的访问令牌（token）→ 自检。
- **正常情况下会看到**：一堆 `==> ...` 和 `OK: ...`，最后是 `安装完成！`。
- **如果看到红字**：脚本会告诉你失败在哪一步。常见原因：
  - `pkg update 失败` → 网络问题，重试。
  - `pip install . 失败` → 网络问题，重试。
  - 其他 → 把错误信息发给维护者。

## 第 8 步：第一次启动

```
termux-mcp start
```

- 这个命令会：确认 token → 启动服务器 → 检查本地端口 → 自动开一个公网隧道 → 打印出你的 **MCP public URL**。
- **正常情况下会看到**：
  ```
  Auth token: configured (length 43)
  Server started (pid 12345)
  REST http://127.0.0.1:8080: OK
  MCP  http://127.0.0.1:8765/mcp: OK
  Tunnel (pinggy): https://xxxx.a.free.pinggy.link
  Public endpoint: reachable
  MCP public: https://xxxx.a.free.pinggy.link/mcp
  ```
- **如果只看到本地 OK 但隧道失败**：没关系，服务器已经在本地跑起来了。可以 `termux-mcp start --no-tunnel` 只跑本地，或者换隧道：`termux-mcp restart --tunnel cloudflare`。

## 第 9 步：token 是什么？

- **token（令牌）** 是一串随机字符，相当于"密码"。只有带着正确 token 的请求才能操作你的手机。
- 第一次启动时系统自动生成，保存在 `~/.config/termux-mcp/config.env`（权限 600，只有你能读）。
- 查看你的 token：

```
termux-mcp token --show
```

- 换一个新 token（旧 token 立即失效，需要重启服务）：

```
termux-mcp token --rotate
termux-mcp restart
```

- ⚠️ **不要把 token 发给别人**。如果怀疑泄露，立刻 `token --rotate`。

## 第 10 步：tunnel 是什么？

- **tunnel（隧道）** 把你的手机上的服务"搬到"公网上，让外面的 AI 客户端能连上。
- 你的手机在局域网/运营商网络里，别人直接连不上。隧道给一个公网 `https://...` 地址。
- 支持的隧道：**pinggy**（默认，最稳）、**cloudflare**、**localhost.run**。
- 指定隧道：

```
termux-mcp restart --tunnel pinggy
termux-mcp restart --tunnel cloudflare
termux-mcp restart --tunnel localhost-run
```

- `start` 的 `--tunnel auto`（默认）会自动按顺序尝试可用的隧道，卡住就换下一个。
- **`restart` 默认只重启服务器，不会动隧道**：正在运行的隧道、它的 PID 和已验证的公网 URL 都会保留，所以 ChatGPT 里保存的 MCP URL 不会失效。只有显式加 `--tunnel`（重建隧道）或 `--no-tunnel`（停止隧道）才会动隧道。

## 第 11 步：如何连接 MCP 客户端

1. 拿到 `termux-mcp start` 输出的 **MCP public URL**（形如 `https://xxxx.a.free.pinggy.link/mcp`）。
2. 打开你的 MCP 客户端（如 ChatGPT、Claude、Cursor 等支持 MCP 的工具）。
3. 添加一个 MCP server，类型选 **Streamable HTTP**（或 SSE/HTTP），地址填上面的 URL。
4. 认证方式选 **Bearer token**（或自定义 Header），填 `Authorization: Bearer <你的token>`。
   - 有些客户端只让填 token 本身，那就只填 token 那串字符。
5. 连接成功后，客户端就能看到 8 个工具：`run_command`、`read_file`、`write_file`、`list_files`、`make_directory`、`get_location`、`get_battery`、`send_notification`。

## 第 12 步：如何停止

```
termux-mcp stop
```

- 会同时停掉服务器和隧道。

## 第 13 步：第二天如何再次启动

```
termux-mcp start
```

- 就这么简单。token 已经存在，不会重新生成。

## 第 14 步：如何更新项目

```
cd ~/Termux-MCP
git pull
pip install . --upgrade
termux-mcp restart
```

## 第 15 步：常见错误怎么办

见下方 [Troubleshooting](#troubleshooting)。

---

# 日常使用命令速查

| 命令 | 作用 |
|---|---|
| `termux-mcp start` | 启动服务器 + 自动隧道，打印 MCP URL |
| `termux-mcp start --no-tunnel` | 只启动本地服务器 |
| `termux-mcp start --tunnel cloudflare` | 指定隧道启动 |
| `termux-mcp domain list` | 查看 Cloudflare 命名 Tunnel 的固定域名路由 |
| `termux-mcp domain add mcp.example.com --port 8765 --tunnel my-tunnel` | 备份并校验配置后添加固定子域名，DNS 失败会自动重试 |
| `termux-mcp stop` | 停止服务器和隧道 |
| `termux-mcp restart` | 只重启服务器（**保留**正在运行的隧道和公网 URL） |
| `termux-mcp restart --tunnel auto` | 重启服务器并**重建**隧道（旧行为） |
| `termux-mcp restart --no-tunnel` | 重启服务器并停止隧道 |
| `termux-mcp status` | 查看运行状态 |
| `termux-mcp logs` | 查看日志（`-n 100` 看更多） |
| `termux-mcp doctor` | 自检（PASS/WARN/FAIL） |
| `termux-mcp doctor --json` | 输出适合脚本与监控读取的结构化诊断结果 |
| `termux-mcp setup` | 重新运行首次连接向导 |
| `termux-mcp permissions` | 查看当前 AI 权限 |
| `termux-mcp permissions set full` | 将权限切换为完全控制（重启生效） |
| `termux-mcp token --show` | 显示 token |
| `termux-mcp token --rotate` | 更换 token |

# 配置

配置文件：`~/.config/termux-mcp/config.env`（自动创建，权限 600）。环境变量 `TERMUX_MCP_*` 优先级更高。

| 变量 | 默认 | 说明 |
|---|---|---|
| `TERMUX_MCP_AUTH_TOKEN` | 自动生成 | Bearer token |
| `TERMUX_MCP_PORT` | `8080` | REST 端口 |
| `TERMUX_MCP_HOST` | `127.0.0.1` | REST 绑定地址 |
| `TERMUX_MCP_MCP_PORT` | `8765` | MCP 端口 |
| `TERMUX_MCP_MCP_HOST` | `127.0.0.1` | MCP 绑定地址 |
| `TERMUX_MCP_WORKSPACE` | 空 | MCP 文件工具的工作区根目录（realpath 边界检查） |
| `TERMUX_MCP_CLIENT` | `chatgpt` | 首选客户端：`chatgpt` / `claude` / `grok` |
| `TERMUX_MCP_PERMISSIONS` | `standard` | 权限：`read-only` / `standard` / `full` |
| `TERMUX_MCP_TIMEOUT` | `0` | 命令超时秒数（0=不超时） |
| `TERMUX_MCP_MAX_OUTPUT` | `20000` | 输出上限字节 |
| `TERMUX_MCP_TUNNEL_PROVIDERS` | `pinggy,cloudflare,localhost-run` | auto 模式的隧道顺序 |
| `TERMUX_MCP_TUNNEL_TIMEOUT` | `45` | 单个隧道超时秒数 |
| `TERMUX_MCP_PROFILE` | 空 | 实例隔离：`dev`/`test` 等名字会使用独立的 config/state 目录和默认端口（REST `18080`、MCP `18765`），与 stable 实例互不干扰 |

### 多实例隔离（profile）

同一台 Termux 上可以同时跑 stable 和 dev/test 实例，互不抢端口、PID、日志、public_url 和配置：

```bash
# stable 实例（默认）
termux-mcp start

# dev 实例：独立目录 + 独立默认端口
TERMUX_MCP_PROFILE=dev termux-mcp start --no-tunnel
TERMUX_MCP_PROFILE=dev termux-mcp status
```

- 带 profile 的实例使用 `~/.config/termux-mcp-<name>/` 和 `~/.local/state/termux-mcp-<name>/`，默认端口偏移到 `18080` / `18765`。
- 显式设置 `TERMUX_MCP_PORT` / `TERMUX_MCP_MCP_PORT`（环境变量或该 profile 的 config.env）仍然优先。

# Security & Deployment

- **Never expose the raw MCP port 8765 (or REST 8080) directly to the public Internet.** Both execute shell commands on the device.
- Put the MCP endpoint behind **HTTPS** using a reverse proxy or secure tunnel.
- Keep **`Authorization: Bearer` required end-to-end** — TLS termination does **not** replace Bearer authentication; the proxy must forward the `Authorization` header.
- **Never put the token in a URL query parameter** (`?token=...`) — it leaks into access logs and browser/terminal history.
- **Bind to localhost by default** when using a local reverse proxy: `TERMUX_MCP_HOST=127.0.0.1`, `TERMUX_MCP_MCP_HOST=127.0.0.1`.
- Recommended topology:

  ```
  ChatGPT / custom MCP client
          |  HTTPS (TLS)
          v
  HTTPS endpoint (reverse proxy / secure tunnel)
          |  plain HTTP, loopback only
          v
  127.0.0.1:8765/mcp  (termux-mcp, bound to localhost)
  ```

- **Rotate the token if it is ever exposed**: `termux-mcp token --rotate && termux-mcp restart`.
- Tunnel URLs are deployment-sensitive — they are printed to your terminal only, never uploaded anywhere.

# OAuth

Static Bearer token is the default auth mode. A standards-compliant **OAuth 2.0 (authorization-code + PKCE)** flow is also implemented and verified end-to-end on a real device (ChatGPT → OAuth → tunnel → Termux-MCP): set `TERMUX_MCP_OAUTH_ISSUER=auto` (or a concrete URL) to enable it. The server self-hosts the authorization server (RFC 6749 + RFC 7636 + RFC 7591 + RFC 7009) and serves RFC 9728 protected-resource metadata + RFC 8414 AS metadata. Registered clients and refresh/access tokens are persisted (`~/.config/termux-mcp/oauth_state.json`, chmod 600) so a server-only `restart` does **not** force ChatGPT to re-authorize. See [docs/oauth.md](docs/oauth.md) for details.

# Troubleshooting

| 现象 | 原因 | 解决 |
|---|---|---|
| `command not found: termux-mcp` | 没安装成功 | 重跑 `bash scripts/install.sh` |
| `python3.13 not found` | 有人硬编码了版本 | 本项目不硬编码 Python 版本，用 `python`/`python3`/`sys.executable`。装 `pkg install python` 即可 |
| `uvicorn not installed` | 依赖没装上 | `pip install uvicorn` 或重跑 install.sh（pyproject.toml 已声明） |
| `No module named mcp` | MCP SDK 没装上 | `pip install "mcp>=1.28,<2"` 或重跑 install.sh |
| `No module named 'mcp.server.fastmcp'` | 装了 MCP 2.x（不兼容） | `pip install "mcp>=1.28,<2"` 强制降级 |
| `port already in use` / 端口被占用 | 已有实例在跑 | `termux-mcp status` 看是否在跑；`termux-mcp stop` 后重启 |
| `401 Unauthorized` | 请求没带 token 或 token 错 | **这是认证在正常工作**。带上 `Authorization: Bearer <token>` 再试 |
| `400 Bad Request / Missing session` | MCP 协议握手问题，**不代表服务挂了** | 用官方 MCP 客户端重试；检查 URL 是否以 `/mcp` 结尾 |
| `406 Not Acceptable` | 客户端请求头不兼容，**不代表服务挂了** | 换支持 Streamable HTTP 的客户端 |
| tunnel timeout | 网络/VPN 问题 | `termux-mcp restart --tunnel pinggy` 换隧道；关 VPN 重试 |
| cloudflared precheck 卡住 | cloudflared 在部分网络卡住 | 用 `--tunnel pinggy` 或 `--tunnel localhost-run` |
| SSH password prompt | 隧道需要交互认证 | 换 pinggy（`--tunnel pinggy`） |
| Pinggy URL 变化 | 免费隧道每次**重建** URL 会变 | 普通 `termux-mcp restart` 会保留隧道和 URL，不用重新复制；只有 `restart --tunnel ...` 重建后才需要更新客户端 |
| Android 杀后台 | 系统回收了 Termux 进程 | 用 `termux-wake-lock` 保持唤醒；或 Termux 设置里允许后台运行 |
| 网络/VPN 导致 tunnel 失败 | 运营商/VPN 限制 | 换网络、关 VPN、换隧道 |

# Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q          # unit tests
python scripts/mcp_smoke.py         # live-server smoke test
```

# License

AGPL-3.0 — see [LICENSE](LICENSE). Original project by [termuxgpt/termux-mcp](https://github.com/termuxgpt/termux-mcp).
