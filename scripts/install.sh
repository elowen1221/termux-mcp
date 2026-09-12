#!/usr/bin/env bash
#
# termux-mcp 一键安装脚本（面向零基础用户）
#
# 用法（在 Termux 中）：
#   方法 A（推荐，先看内容再执行）：
#     curl -L -o install.sh https://raw.githubusercontent.com/lxy426329/Termux-MCP/main/scripts/install.sh
#     bash install.sh
#   方法 B（一行命令）：
#     curl -fsSL https://raw.githubusercontent.com/lxy426329/Termux-MCP/main/scripts/install.sh | bash
#
# 脚本是幂等的：重复运行不会破坏已有配置。
# 不会把 token 打印到日志，不会上传任何 secret。
#
set -euo pipefail

STEP="初始化"
INSTALL_LOG=""
FIRST_INSTALL=0
fail() {
  echo ""
  echo "=================================================="
  echo " 安装失败于步骤: $STEP"
  echo " 错误信息: $1"
  if [ -n "$INSTALL_LOG" ]; then
    echo " 安装日志: $INSTALL_LOG"
  fi
  echo "=================================================="
  echo ""
  echo "请把上面的错误信息发给维护者，或查看 README 的 Troubleshooting 章节。"
  exit 1
}

log() { echo "==> $1"; }
ok()  { echo "    OK: $1"; }

run_logged() {
  if "$@" >>"$INSTALL_LOG" 2>&1; then
    return 0
  else
    local exit_code=$?
  fi
  echo ""
  echo "---- 最近 40 行安装日志 ----" >&2
  tail -n 40 "$INSTALL_LOG" >&2 || true
  echo "----------------------------" >&2
  return "$exit_code"
}

# ── 1. 检查 Termux 环境 ─────────────────────────────────────────────────────
STEP="检查 Termux 环境"
if [ -z "${PREFIX:-}" ] || [[ "$PREFIX" != /data/data/com.termux* ]]; then
  fail "看起来不是在 Termux 中运行。请在 Android 手机的 Termux 应用里运行本脚本。"
fi
ok "Termux 环境 ($PREFIX)"

INSTALL_LOG="${TERMUX_MCP_INSTALL_LOG:-$HOME/.local/state/termux-mcp/install.log}"
mkdir -p "$(dirname "$INSTALL_LOG")"
: >"$INSTALL_LOG"
chmod 600 "$INSTALL_LOG"
ok "安装日志 ($INSTALL_LOG)"

# ── 2. 更新软件包列表 ───────────────────────────────────────────────────────
STEP="更新软件包列表 (pkg update)"
log "更新软件包列表..."
run_logged pkg update -y || fail "pkg update 失败，请检查网络或软件源后重试"
ok "pkg update"

# ── 3. 安装系统依赖 ─────────────────────────────────────────────────────────
STEP="安装系统依赖"
log "安装 python / git / openssh ..."
run_logged pkg install -y python git openssh || fail "pkg install 失败"
ok "python git openssh"

# ── 4. 检查 Python / pip ────────────────────────────────────────────────────
STEP="检查 Python"
command -v python >/dev/null 2>&1 || fail "python 未安装"
PY_VER="$(python --version 2>&1)"
ok "$PY_VER"
command -v pip >/dev/null 2>&1 || fail "pip 未安装"
ok "pip"

# ── 5. 定位并安装项目（含 mcp SDK + uvicorn）──────────────────────────────
STEP="安装项目"
is_project_checkout() {
  [ -f pyproject.toml ] && [ -d termux_mcp ] &&
    grep -Eq '^[[:space:]]*name[[:space:]]*=[[:space:]]*"termux-mcp"' pyproject.toml
}

if is_project_checkout; then
  log "在当前目录安装项目..."
  run_logged pip install . || fail "pip install . 失败"
  ok "pip install ."
else
  SOURCE_DIR="${TERMUX_MCP_SOURCE_DIR:-$HOME/Termux-MCP}"
  if [ -d "$SOURCE_DIR/.git" ]; then
    log "使用已有源码目录 $SOURCE_DIR"
    cd "$SOURCE_DIR"
    is_project_checkout || fail "$SOURCE_DIR 不是有效的 Termux-MCP 仓库"
  elif [ -e "$SOURCE_DIR" ]; then
    fail "$SOURCE_DIR 已存在但不是 Git 仓库，请移走该目录后重试"
  else
    log "未找到项目文件，从 GitHub 克隆到 $SOURCE_DIR ..."
    run_logged git clone --depth 1 https://github.com/lxy426329/Termux-MCP.git "$SOURCE_DIR" || fail "git clone 失败"
    cd "$SOURCE_DIR"
  fi
  run_logged pip install . || fail "pip install . 失败"
  ok "pip install ."
fi

# ── 6. 验证 MCP SDK（必须 >=1.28 且 <2）────────────────────────────────────
STEP="检查 MCP SDK"
MCP_VER="$(python -c 'import importlib.metadata as m; print(m.version("mcp"))' 2>/dev/null || true)"
if [ -z "$MCP_VER" ]; then
  fail "MCP SDK 未安装（pip install . 应已自动安装）"
fi
if [[ "$MCP_VER" == 2.* ]]; then
  fail "检测到 MCP SDK $MCP_VER（2.x 不兼容）。请运行: pip install 'mcp>=1.28,<2'"
fi
ok "mcp $MCP_VER"

# ── 7. 验证 uvicorn ─────────────────────────────────────────────────────────
STEP="检查 uvicorn"
UVI_VER="$(python -c 'import importlib.metadata as m; print(m.version("uvicorn"))' 2>/dev/null || true)"
if [ -z "$UVI_VER" ]; then
  fail "uvicorn 未安装（pip install . 应已自动安装）"
fi
ok "uvicorn $UVI_VER"

# ── 8. 检查可选 tunnel 依赖 ─────────────────────────────────────────────────
STEP="检查 tunnel 依赖"
if command -v ssh >/dev/null 2>&1; then
  ok "ssh（pinggy / localhost.run 可用）"
else
  echo "    WARN: ssh 未安装（可选）— 需要公网隧道时运行: pkg install openssh"
fi
if command -v cloudflared >/dev/null 2>&1; then
  ok "cloudflared（cloudflare 隧道可用）"
else
  echo "    WARN: cloudflared 未安装（可选）— 需要时运行: pkg install cloudflared"
fi

# ── 9. 创建必要目录 ─────────────────────────────────────────────────────────
STEP="创建目录"
mkdir -p ~/.config/termux-mcp
mkdir -p ~/.local/state/termux-mcp
ok "~/.config/termux-mcp  ~/.local/state/termux-mcp"

# ── 10/11. 配置 + 首次生成随机 AUTH TOKEN ──────────────────────────────────
STEP="生成配置"
CONFIG="$HOME/.config/termux-mcp/config.env"
if [ ! -f "$CONFIG" ]; then
  FIRST_INSTALL=1
  log "首次运行：生成随机 AUTH TOKEN ..."
  TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  {
    echo "# termux-mcp configuration (auto-generated)"
    echo "# 此文件包含密钥，权限已设为 600。"
    echo "TERMUX_MCP_AUTH_TOKEN=$TOKEN"
  } > "$CONFIG"
  chmod 600 "$CONFIG"
  ok "已生成 token 并保存到 $CONFIG（权限 600）"
else
  ok "配置文件已存在，跳过生成"
fi

# ── 12. 文件权限 ────────────────────────────────────────────────────────────
STEP="设置权限"
chmod 600 "$CONFIG" 2>/dev/null || true
ok "config.env 权限 600"

# ── 13. 自检 ────────────────────────────────────────────────────────────────
STEP="自检"
log "运行自检 (termux-mcp doctor) ..."
termux-mcp doctor || true

# ── 14. 首次连接 ────────────────────────────────────────────────────────────
if [ "$FIRST_INSTALL" -eq 1 ] && [ "${TERMUX_MCP_SKIP_SETUP:-0}" != "1" ]; then
  STEP="首次连接向导"
  termux-mcp setup || fail "首次连接没有完成；稍后可运行 termux-mcp setup"
fi

# ── 15. 成功信息 ────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo " 安装完成！( Ꙭ)"
echo "=================================================="
echo ""
if [ "$FIRST_INSTALL" -eq 0 ]; then
  echo "已有配置保持不变。运行 termux-mcp status 查看状态。"
fi
echo ""
