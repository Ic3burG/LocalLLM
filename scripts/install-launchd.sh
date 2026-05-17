#!/usr/bin/env bash
# Install / refresh launchd agents for the LocalLLM Python bridge and Node
# server. Templates absolute paths from the current project directory so the
# plists cannot drift if the repo is ever moved or renamed.
#
# Usage:
#   bash scripts/install-launchd.sh           # install + reload
#   bash scripts/install-launchd.sh --uninstall  # unload + remove
#   bash scripts/install-launchd.sh --print      # print would-be plists, no writes
#
# Exits non-zero if either service fails to come up on its expected port.

set -euo pipefail

# ── Resolve project paths from script location ──────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PY_VENV="$REPO_ROOT/.venv/bin/python3"
BRIDGE_SCRIPT="$REPO_ROOT/gemma_bridge.py"
SERVER_SCRIPT="$REPO_ROOT/gemma-web/server.js"
NODE_BIN="$(command -v node || true)"

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LITERT_PLIST="$LAUNCH_AGENTS/com.gemini.litert.plist"
BRIDGE_PLIST="$LAUNCH_AGENTS/com.gemini.gemma-bridge.plist"

LOG_DIR="$HOME/.gemini"
LITERT_STDOUT="$LOG_DIR/litert-stdout.log"
LITERT_STDERR="$LOG_DIR/litert-stderr.log"
BRIDGE_STDOUT="$LOG_DIR/bridge-stdout.log"
BRIDGE_STDERR="$LOG_DIR/bridge-stderr.log"

PYTHON_PORT=9379
NODE_PORT=3001

MODE="install"
case "${1:-}" in
  --uninstall) MODE="uninstall" ;;
  --print) MODE="print" ;;
  "") ;;
  *) echo "unknown arg: $1" >&2; exit 2 ;;
esac

# ── Validate prerequisites ──────────────────────────────────────────────────
err() { echo "✗ $1" >&2; exit 1; }
[ "$MODE" = "uninstall" ] || [ -x "$PY_VENV" ] || err "missing venv python: $PY_VENV (run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"
[ "$MODE" = "uninstall" ] || [ -f "$BRIDGE_SCRIPT" ] || err "missing bridge script: $BRIDGE_SCRIPT"
[ "$MODE" = "uninstall" ] || [ -f "$SERVER_SCRIPT" ] || err "missing server script: $SERVER_SCRIPT"
[ "$MODE" = "uninstall" ] || [ -n "$NODE_BIN" ] || err "node not on PATH (install Node.js or symlink to /usr/local/bin/node)"

# ── Plist templates ─────────────────────────────────────────────────────────
emit_litert_plist() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gemini.litert</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY_VENV</string>
        <string>$BRIDGE_SCRIPT</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>
    <key>StandardOutPath</key>
    <string>$LITERT_STDOUT</string>
    <key>StandardErrorPath</key>
    <string>$LITERT_STDERR</string>
</dict>
</plist>
EOF
}

emit_bridge_plist() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gemini.gemma-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$NODE_BIN</string>
        <string>$SERVER_SCRIPT</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT/gemma-web</string>
    <key>StandardOutPath</key>
    <string>$BRIDGE_STDOUT</string>
    <key>StandardErrorPath</key>
    <string>$BRIDGE_STDERR</string>
</dict>
</plist>
EOF
}

# ── Print mode: dump templated plists and exit ──────────────────────────────
if [ "$MODE" = "print" ]; then
  echo "# --- com.gemini.litert.plist ---"
  emit_litert_plist
  echo
  echo "# --- com.gemini.gemma-bridge.plist ---"
  emit_bridge_plist
  exit 0
fi

# ── Uninstall mode: unload + remove plists ──────────────────────────────────
if [ "$MODE" = "uninstall" ]; then
  for plist in "$LITERT_PLIST" "$BRIDGE_PLIST"; do
    if [ -f "$plist" ]; then
      launchctl unload "$plist" 2>/dev/null || true
      rm -f "$plist"
      echo "✓ removed $plist"
    fi
  done
  exit 0
fi

# ── Install mode ────────────────────────────────────────────────────────────
mkdir -p "$LAUNCH_AGENTS" "$LOG_DIR"

# Unload any existing versions before overwriting (ignore failures — they may
# not be loaded, or may be pointing at a stale path).
for plist in "$LITERT_PLIST" "$BRIDGE_PLIST"; do
  if [ -f "$plist" ]; then
    launchctl unload "$plist" 2>/dev/null || true
  fi
done

emit_litert_plist > "$LITERT_PLIST"
emit_bridge_plist > "$BRIDGE_PLIST"
echo "✓ wrote $LITERT_PLIST"
echo "✓ wrote $BRIDGE_PLIST"

launchctl load "$LITERT_PLIST"
launchctl load "$BRIDGE_PLIST"
echo "✓ loaded both agents"

# ── Verify both ports come up ───────────────────────────────────────────────
wait_for_port() {
  local port=$1 label=$2 attempts=30
  for _ in $(seq 1 $attempts); do
    if curl -sf -o /dev/null --max-time 2 "http://localhost:$port/" \
        || curl -s -o /dev/null --max-time 2 "http://localhost:$port/" 2>/dev/null; then
      # any response (even 404) means the port is listening
      if nc -z localhost "$port" 2>/dev/null; then
        echo "✓ $label listening on :$port"
        return 0
      fi
    fi
    if nc -z localhost "$port" 2>/dev/null; then
      echo "✓ $label listening on :$port"
      return 0
    fi
    sleep 1
  done
  echo "✗ $label did NOT come up on :$port within $attempts s" >&2
  echo "  check: tail -n 50 $LOG_DIR/${label}-stderr.log" >&2
  return 1
}

# Node is fast; Python bridge takes ~5–15s to import mlx_vlm on cold start.
fail=0
wait_for_port "$NODE_PORT" bridge || fail=1
wait_for_port "$PYTHON_PORT" litert || fail=1

if [ "$fail" -ne 0 ]; then
  echo
  echo "One or more services failed to start. The plists are in place but" >&2
  echo "launchd's KeepAlive will keep retrying. Inspect logs in $LOG_DIR." >&2
  exit 1
fi

echo
echo "✅ launchd install complete. Both services running."
echo "   project root: $REPO_ROOT"
echo "   python:        $PY_VENV"
echo "   node:          $NODE_BIN"
