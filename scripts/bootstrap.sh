#!/usr/bin/env bash
# Termux-MCP zero-to-running bootstrap.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/lxy426329/Termux-MCP/main/scripts/bootstrap.sh | bash
set -Eeuo pipefail

REPOSITORY="${TERMUX_MCP_REPOSITORY:-https://github.com/lxy426329/Termux-MCP.git}"
BRANCH="${TERMUX_MCP_BRANCH:-main}"
TARGET_DIR="${TERMUX_MCP_SOURCE_DIR:-${HOME}/Termux-MCP}"
SKIP_SOURCE_UPDATE=false
STEP="initialize"

fail() {
  printf '\n[FAILED] %s\nReason: %s\n' "$STEP" "$1" >&2
  exit 1
}

log() { printf '\n==> %s\n' "$1"; }
ok() { printf '    OK: %s\n' "$1"; }

on_error() {
  local exit_code=$?
  printf '\n[FAILED] %s (exit %s)\n' "$STEP" "$exit_code" >&2
  exit "$exit_code"
}
trap on_error ERR

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || fail "--dir requires a path"
      TARGET_DIR="$2"
      shift 2
      ;;
    --branch)
      [[ $# -ge 2 ]] || fail "--branch requires a name"
      BRANCH="$2"
      shift 2
      ;;
    --skip-source-update)
      SKIP_SOURCE_UPDATE=true
      shift
      ;;
    --help|-h)
      cat <<'EOF'
Termux-MCP bootstrap

Options:
  --dir PATH             Source checkout path (default: ~/Termux-MCP)
  --branch NAME          Git branch (default: main)
  --skip-source-update   Reuse an existing checkout without fetching
EOF
      exit 0
      ;;
    *) fail "unknown option: $1" ;;
  esac
done

STEP="check Termux environment"
if [[ -z "${PREFIX:-}" || "$PREFIX" != /data/data/com.termux* ]]; then
  fail "run this command inside the Termux Android app"
fi
command -v pkg >/dev/null 2>&1 || fail "the Termux pkg command is unavailable"
ok "Termux detected at $PREFIX"

STEP="prepare Git"
if ! command -v git >/dev/null 2>&1; then
  log "Installing Git"
  pkg update -y || fail "pkg update failed; check the network or repository mirror"
  pkg install -y git || fail "Git installation failed"
fi
ok "$(git --version)"

STEP="prepare source checkout"
if [[ -d "$TARGET_DIR/.git" ]]; then
  CURRENT_ORIGIN="$(git -C "$TARGET_DIR" remote get-url origin 2>/dev/null || true)"
  case "$CURRENT_ORIGIN" in
    "$REPOSITORY"|https://github.com/lxy426329/Termux-MCP|git@github.com:lxy426329/Termux-MCP.git) ;;
    *) fail "$TARGET_DIR is a different Git repository (origin: ${CURRENT_ORIGIN:-missing})" ;;
  esac

  if [[ "$SKIP_SOURCE_UPDATE" == false ]]; then
    if [[ -n "$(git -C "$TARGET_DIR" status --porcelain)" ]]; then
      fail "$TARGET_DIR has local changes; commit/stash them or use --skip-source-update"
    fi
    log "Updating the existing checkout"
    git -C "$TARGET_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$TARGET_DIR" checkout "$BRANCH"
    git -C "$TARGET_DIR" merge --ff-only FETCH_HEAD
  fi
elif [[ -e "$TARGET_DIR" ]]; then
  if [[ ! -d "$TARGET_DIR" || -n "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    fail "$TARGET_DIR exists and is not an empty directory"
  fi
  log "Cloning Termux-MCP"
  git clone --depth 1 --branch "$BRANCH" "$REPOSITORY" "$TARGET_DIR"
else
  log "Cloning Termux-MCP"
  git clone --depth 1 --branch "$BRANCH" "$REPOSITORY" "$TARGET_DIR"
fi
ok "source ready at $TARGET_DIR"

STEP="run project installer"
[[ -f "$TARGET_DIR/scripts/install.sh" ]] || fail "scripts/install.sh is missing from the checkout"
cd -- "$TARGET_DIR"
bash scripts/install.sh

STEP="final verification"
if command -v termux-mcp >/dev/null 2>&1; then
  termux-mcp doctor || true
  ok "Termux-MCP is installed"
else
  fail "installation finished but the termux-mcp command is not on PATH"
fi

printf '\nTermux-MCP 已经准备好啦 ( Ꙭ)\n'
