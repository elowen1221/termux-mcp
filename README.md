# Termux-MCP

> **Fork & thanks**: This project is built on [termuxgpt/termux-mcp](https://github.com/termuxgpt/termux-mcp), the original upstream project. Many core ideas and the original REST/device-control foundation come from its authors and contributors. Thank you for making the project open source. This fork remains AGPL-3.0, preserves upstream attribution, and focuses on a friendlier Agent/MCP gateway, onboarding, permissions, managed MCPs, workflows, OAuth, tunnels, and operational safety.

## 第一次来？从这里开始 ( Ꙭ)

> [!IMPORTANT]
> **先看设备：当前版本只支持 Android + Termux。**
>
> - **Android**：✓ 当前主要支持平台，可以继续下面的安装步骤。
> - **iPhone / iPad (iOS / iPadOS)**：✗ 当前不能按本教程在设备本机安装；iOS 没有 Termux，也不具备本项目目前依赖的 Termux 运行环境。
> - **HarmonyOS NEXT / 原生鸿蒙**：✗ 当前不支持本机安装。仍兼容 Android APK 的旧版 HarmonyOS 设备可能可以运行 Termux，但尚未作为正式支持平台测试。
>
> 如果你用的是 iPhone、iPad 或原生鸿蒙，**不用继续复制下面的 Termux 安装命令**。未来可以考虑远程节点或独立的 iOS / HarmonyOS backend；当前仓库先把 Android 版本做好。

你不需要先学 Linux、Python、端口或 MCP。第一次使用只做四件事：

1. 在 Android 上安装 **Termux**（推荐 [F-Droid](https://f-droid.org/packages/com.termux/)；也可以用 [Termux 官方 GitHub Releases](https://github.com/termux/termux-app/releases)）。
2. 打开 Termux，等黑色窗口里出现 `$`。
3. 复制下面 **这一条命令**，粘贴后按回车：

```bash
curl -fsSL https://raw.githubusercontent.com/elowen1221/termux-mcp/main/scripts/bootstrap.sh | bash
```

4. 后面跟着 `( Ꙭ)` 新手向导选就好。**不知道选什么就一路按 Enter**：默认是 ChatGPT + 日常权限 + 免费公网地址。

安装器会自己准备 Git/Python/SSH、下载项目、安装依赖、生成本机密钥、运行自检并进入首次连接向导。普通功能不要求 root。需要通知、电池、定位等 Android 能力时，再安装与 Termux **同一来源**的 Termux:API。

### 先截一张“救命小抄”

安装完成后随时运行：

```bash
termux-mcp guide
```

它会根据你现在的连接方式显示下一步，并把最常用的命令排成适合截图的样子。真正需要记住的只有这些：

```text
termux-mcp status    看 MCP / tunnel 还活着没有
termux-mcp url       看现在应该填给 AI 的 MCP 地址
termux-mcp guide     忘记下一步时重新叫出新手小抄
termux-mcp doctor    出问题先自检，不要急着重装
termux-mcp restart   普通重启尽量保留现有免费 tunnel URL
```

> **不要截图或分享 `termux-mcp token --show` 的输出。** token 相当于设备访问密钥；只有客户端明确要求 Bearer token 时才在自己的手机上查看。

### 向导会问什么？

首次安装只有三类选择：

- **AI 客户端**：ChatGPT（默认）/ Claude / Grok。
- **权限**：🌿 日常活动（默认）/ 🌱 只看看 / 🌳 完全开放。
- **AI 怎么找到手机**：
  1. 免费地址（默认，不需要域名；重建 tunnel 后地址可能变化）；
  2. 自己的域名（例如 `termux.example.com`，向导会保存目标地址，但不会未经确认修改 DNS）；
  3. 已有公网入口（VPS / 反代 / 其他 HTTPS 地址）；
  4. 暂时只在手机本机使用。

自有域名模式和免费地址是两条不同路线：**基础使用完全不要求购买域名**。如果你有自己的域名，可以后续使用 Cloudflare Named Tunnel 配成固定地址。

## Changes in this fork

This fork adds a minimal, standards-compliant **MCP (Model Context Protocol)** layer without removing the existing REST API:

- **MCP Streamable HTTP endpoint** at `/mcp` (port `8765` by default), built on the official `mcp` Python SDK (`mcp>=1.28,<2`) + `uvicorn`.
- **Public core MCP tools** for shell/files/device access, permission visibility, managed-MCP lifecycle and bounded workflows; private device-specific extensions can be mounted locally without being committed to this repository.
- **Beginner-first onboarding**: `termux-mcp setup` guides the target AI, permission level, and one of four connection routes (free URL / own domain / existing HTTPS entry / local only). `termux-mcp guide` is a screenshot-friendly, state-aware pocket guide for returning users.
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

1. 如果手机还没有 **F-Droid**，可以先安装 F-Droid；然后打开 [Termux 的 F-Droid 页面](https://f-droid.org/packages/com.termux/) 安装。
2. 也可以直接从 [Termux 官方 GitHub Releases](https://github.com/termux/termux-app/releases) 获取官方 APK。
3. Termux 与 Termux:API 等插件必须保持同一安装来源/签名，不要混装。
4. 打开 Termux，你会看到黑色终端窗口和 `$` 提示符。

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
- **如果看到红字**：先别反复重装。运行 `termux-mcp doctor`（如果还没安装到这一步，就把当前终端最后一屏截图保存），优先检查网络/软件源提示。VPN 在部分网络下可能有帮助，也可能造成连接问题，不建议一律关闭。

## 第 4 步：安装 git

```
pkg install -y git
```

- 看到 `$` 提示符就成功了。

## 第 5 步：下载本仓库

```
git clone https://github.com/elowen1221/termux-mcp.git
```

- **正常情况下会看到**：`Cloning into 'Termux-MCP'...` 然后回到 `$`。
- **如果看到红字**：先看错误里是否明确写着网络、DNS 或 GitHub 连接失败；可以换网络后重试。不要看到红字就直接删除整个 Termux。

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
- 支持的免费隧道：**pinggy**（默认优先）、**cloudflare quick tunnel**、**localhost.run**。这些地址不需要购买域名，但属于服务商分配的临时公网地址。
- 指定隧道：

```
termux-mcp restart --tunnel pinggy
termux-mcp restart --tunnel cloudflare
termux-mcp restart --tunnel localhost-run
```

- `start` 的 `--tunnel auto`（默认）会自动按顺序尝试可用的隧道，卡住就换下一个。
- **`restart` 默认只重启服务器，不会动隧道**：正在运行的隧道、它的 PID 和已验证的公网 URL 都会保留，所以 ChatGPT 里保存的 MCP URL 不会失效。
- **`start` 现在也会保护免费 URL**：如果服务器意外退出、但原来的免费隧道进程仍然活着，再运行普通 `termux-mcp start` 会复用旧隧道，而不是重新申请一个地址。
- 只有显式加 `--tunnel <provider>`、执行 `stop` 后重新启动、手机重启/系统杀掉隧道进程，或者隧道服务商主动断开时，免费地址才可能变化。地址变化时 CLI 会明确打印旧地址和新地址，提醒你更新客户端。
- 随时运行 `termux-mcp url` 可以查看当前 MCP 公网地址，以及这条免费隧道是否仍在被保留。

## 第 11 步：如何连接 MCP 客户端

1. 拿到 `termux-mcp start` 输出的 **MCP public URL**（形如 `https://xxxx.a.free.pinggy.link/mcp`）。
2. 打开你的 MCP 客户端（如 ChatGPT、Claude、Cursor 等支持 MCP 的工具）。
3. 添加一个 MCP server，类型选 **Streamable HTTP**（或 SSE/HTTP），地址填上面的 URL。
4. 认证方式选 **Bearer token**（或自定义 Header），填 `Authorization: Bearer <你的token>`。
   - 有些客户端只让填 token 本身，那就只填 token 那串字符。
5. 连接成功后，公开核心当前提供 **17 个 MCP 工具**，包括 shell/文件/设备能力、权限状态、managed MCP 管理以及 `run_steps` 多步骤工作流。设备自己的私有扩展可以通过本地扩展接口额外挂载，不需要提交进公共仓库。实际可执行能力仍受你选择的权限模式和 Android/Termux 权限限制。

## 第 12 步：如何停止

```
termux-mcp stop
```

- 会同时停掉服务器和隧道。

## 第 13 步：第二天如何再次使用

如果 Termux-MCP 和免费隧道还在后台运行，不需要重新 `start`，直接继续用即可。先看：

```
termux-mcp status
termux-mcp url
```

如果只是 MCP 服务器退出、免费隧道仍然存活：

```
termux-mcp start
```

普通 `start` 会优先复用现有免费隧道，尽量保持原 URL。若你之前执行了 `termux-mcp stop`、手机重启，或免费隧道本身已经断开，则下一次启动可能得到新 URL；CLI 会把变化明确打印出来。token 已经存在，不会重新生成。

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
| `termux-mcp guide` | 打开适合截图的新手小抄，并根据当前状态提示下一步 |
| `termux-mcp domain guide` | 自有域名路线检查：cloudflared / 登录 / Named Tunnel / config / 下一步 |
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

## 自有域名：固定 MCP 地址

如果你在首次向导里选择了“我有自己的域名”，先运行：

```bash
termux-mcp domain guide
```

它**只检查、不改 DNS**，会根据当前状态一次只告诉你一个动作：安装 `cloudflared` → Cloudflare 登录 → 创建 Named Tunnel → 准备配置 → 最后才给出真正添加 ingress / DNS 的命令。这样不会因为复制一长串命令把已有 Cloudflare 配置弄乱。

如果这是全新 Cloudflare Tunnel，最小的 `~/.cloudflared/config.yml` 结构如下（把 `<TUNNEL-ID>` 和凭据路径换成 `cloudflared tunnel create termux-mcp` 实际生成的值）：

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /data/data/com.termux/files/home/.cloudflared/<TUNNEL-ID>.json

ingress:
  - service: http_status:404
```

然后再次运行 `termux-mcp domain guide`。当基础条件齐全后，它会打印类似：

```bash
termux-mcp domain add termux.example.com --port 8765 --tunnel termux-mcp
```

这个最终命令才会修改 ingress / 创建 Cloudflare DNS route；修改前会备份配置，并调用 `cloudflared tunnel ingress validate` 校验。项目不会使用维护者的私人域名作为公共 relay。

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
| `TERMUX_MCP_TIMEOUT` | `120` | 普通命令超时秒数（防止断线后孤儿任务长期占住 MCP；长任务应使用后台任务/会话能力） |
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

# 同类项目怎么选

Termux/Android MCP 项目侧重点不同，没有一个方案在所有维度都最好：

| 项目 | 更适合 | 主要特点 | 相比本 fork 的取舍 |
|---|---|---|---|
| **本 fork (`elowen1221/termux-mcp`)** | 想把远程 AI 长期接入 Termux，并继续管理其他 MCP/工作流 | REST + Streamable HTTP MCP、OAuth/Bearer、三档权限、managed MCP、`run_steps`、多 tunnel、doctor/onboarding | 功能面更大，因此安全边界和兼容性需要持续测试 |
| **上游 `termuxgpt/termux-mcp`** | 想要更接近原始项目、较简单的 Termux shell/device bridge | REST + native MCP，安全检查、文件快照/回收站等基础扎实 | 本 fork 在它之上增加了 Agent 工作台和部署层；同步上游时需要处理分叉 |
| **`TecnicalBot/termux-mcp`** | 安全默认值优先、愿意显式开启敏感工具 | Go 实现、default-deny、shell allowlist、JSONL audit、后台任务、termux-services | 它的默认拒绝和审计设计更严格；本 fork 的 raw-shell/工作流自由度更高 |
| **`shizzgar/shizuku-mcp`** | 需要通过 Shizuku 获得更强 Android 控制 | Termux + Shizuku/rish、统一 shell、持久 session | Android 控制更深入，但部署/权限模型不同；本 fork 更聚焦 Termux + MCP gateway |

如果目标是“让可信 AI 在自己的手机 Termux 里持续做工程任务”，本 fork 的优势是**连接、运维、MCP 编排和长工作流整合在一起**；如果目标是给陌生/不完全可信 Agent 最小权限，优先参考 default-deny/allowlist 类型方案。

# Acknowledgements / 致谢

特别感谢 **[termuxgpt/termux-mcp](https://github.com/termuxgpt/termux-mcp)** 的作者与贡献者。本仓库是它的 fork；原项目提供了 Termux HTTP/设备控制、安全检查、文件操作等重要基础，也是这个增强版本能够继续发展的起点。

同时感谢 [Termux](https://github.com/termux/termux-app) 及其生态、[Model Context Protocol](https://modelcontextprotocol.io/) 社区和本项目使用的开源依赖。所有上游版权与许可证声明均应继续保留；本 fork 按 AGPL-3.0 发布。

# Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q          # unit tests
python scripts/mcp_smoke.py         # live-server smoke test
```

# License

AGPL-3.0 — see [LICENSE](LICENSE). Original project by [termuxgpt/termux-mcp](https://github.com/termuxgpt/termux-mcp).

### Permanent URL without buying a domain (Stable Relay)

For users who want a permanent URL, Termux-MCP includes an optional **self-hosted** stable relay. Each installation keeps a random device identity and can use a permanent URL such as `https://relay.example.com/d/<device-id>/mcp`. The phone connects outward to the relay, so no inbound phone port is required. The project does **not** depend on or provide a maintainer-hosted relay: set `TERMUX_MCP_RELAY_BASE` to infrastructure you control. Anonymous tunnels remain the zero-infrastructure default, while named tunnels/custom domains remain available. See `docs/STABLE_RELAY.md` for architecture and security boundaries.
