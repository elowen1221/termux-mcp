#!/data/data/com.termux/files/usr/bin/bash
set -u

CFG="${TERMUX_MCP_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/config.yml}"
NAME="${TERMUX_MCP_TUNNEL_NAME:-termux-mcp}"
LOG="$HOME/.local/state/termux-mcp/tunnel.log"
TMPBASE="${TMPDIR:-$PREFIX/tmp}"
STATUS_FILE="$TMPBASE/termux-mcp-heal.status"
RESTART_FILE="$TMPBASE/termux-mcp-heal.restart"

ok(){ printf '🌱 %s\n' "$*"; }
fix(){ printf '🛠  %s\n' "$*"; }
fail(){ printf '🥲 %s\n' "$*"; }
info(){ printf '   ↳ %s\n' "$*"; }

printf 'ฅ( ̳• · • ̳ฅ) Termux-MCP 小医生出诊啦\n'
printf '%s\n' '--------------------------------'

# 1) Local MCP
if termux-mcp status >"$STATUS_FILE" 2>&1; then
  if grep -q 'REST .*: OK' "$STATUS_FILE" && grep -q 'MCP port .*: LISTENING' "$STATUS_FILE"; then
    ok '本地 MCP 乖乖在线'
  else
    fix '本地服务有点迷糊，正在重新叫醒它…'
    termux-mcp restart --no-tunnel >"$RESTART_FILE" 2>&1 || true
    sleep 2
  fi
else
  fix '状态检查失败，先重启本地服务试试看…'
  termux-mcp restart --no-tunnel >"$RESTART_FILE" 2>&1 || true
  sleep 2
fi

if ! termux-mcp status >"$STATUS_FILE" 2>&1 || \
   ! grep -q 'REST .*: OK' "$STATUS_FILE" || \
   ! grep -q 'MCP port .*: LISTENING' "$STATUS_FILE"; then
  fail '本地 MCP 还是没醒，这次需要人工看看了'
  cat "$STATUS_FILE" 2>/dev/null || true
  printf '\n重启输出：\n'
  cat "$RESTART_FILE" 2>/dev/null || true
  exit 1
fi
ok 'REST + MCP 端口都正常'

# 2) Named Cloudflare tunnel config
if [ ! -f "$CFG" ]; then
  fail "没找到 Cloudflare 配置：$CFG"
  exit 1
fi

TUNNEL_ID="$(sed -n 's/^[[:space:]]*tunnel:[[:space:]]*//p' "$CFG" | head -n1 | tr -d '"'"'"' ')"
if [ -z "$TUNNEL_ID" ]; then
  fail '配置里没找到 tunnel id'
  exit 1
fi

connector_ok(){
  cloudflared tunnel info "$TUNNEL_ID" 2>&1 | grep -q 'CONNECTOR ID'
}

if connector_ok; then
  ok 'Cloudflare connector 也在线'
else
  fix 'Cloudflare connector 掉线了，像是 1033 那只坏猫在捣乱'

  PIDS="$(ps -ef | awk -v cfg="$CFG" -v name="$NAME" '$0 ~ /cloudflared/ && index($0,"--config " cfg) && index($0,"run " name) {print $2}')"
  if [ -n "$PIDS" ]; then
    info "先清掉装死的 cloudflared：$PIDS"
    for p in $PIDS; do kill "$p" 2>/dev/null || true; done
    sleep 2
    for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done
  fi

  mkdir -p "$(dirname "$LOG")"
  : > "$LOG"
  info '重新拉起一个干净的 connector…'
  nohup cloudflared tunnel --config "$CFG" run "$NAME" >>"$LOG" 2>&1 </dev/null &
  NEWPID=$!
  info "新 PID：$NEWPID"

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if connector_ok; then
      ok 'Cloudflare connector 抢救成功'
      break
    fi
  done

  if ! connector_ok; then
    fail '自动修复没救回来，把下面这段日志发给维护者/ChatGPT 就好'
    printf '\n最近的 tunnel 日志：\n'
    tail -n 30 "$LOG" 2>/dev/null || true
    exit 2
  fi
fi

# 3) Public endpoint sanity check
PUBLIC_URL="$(termux-mcp status 2>/dev/null | sed -n 's/^Public MCP URL: .* — //p' | head -n1)"
if [ -n "$PUBLIC_URL" ]; then
  CODE="$(curl -L -sS -o /dev/null -w '%{http_code}' --max-time 10 "$PUBLIC_URL" 2>/dev/null || true)"
  case "$CODE" in
    200|400|401|403|405) ok "公网入口有回应（HTTP $CODE）" ;;
    530) fail '公网入口返回 Cloudflare 530，自动修复先停在这里'; exit 3 ;;
    000|'') info '手机自己访问自己的公网地址没测通（HTTP 000），但 connector 在线，所以先不算故障' ;;
    *) info "公网入口返回 HTTP $CODE；connector 本身是健康的" ;;
  esac
fi

printf '\n૮₍˶ᵔ ᵕ ᵔ˶₎ა 检查结束：重要链路都好好的。\n'
