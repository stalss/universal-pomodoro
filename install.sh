#!/usr/bin/env bash
# Universal installer. No root required. Works on any Linux distro with
# Python 3; uses systemd --user when available, otherwise prints manual steps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
SYSTEMD_USER="$CONFIG_HOME/systemd/user"

echo "==> Checking dependencies"
command -v python3 >/dev/null 2>&1 || { echo "python3 is required." >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 9)' || {
  echo "Python 3.9 or newer is required." >&2; exit 1;
}

echo "==> Installing to $BIN_DIR"
mkdir -p "$BIN_DIR"
install -m 755 "$SCRIPT_DIR/pomodoro.py" "$BIN_DIR/pomodoro"

LIMITER="$SCRIPT_DIR/daily-screen-limit"
if [[ ! -f "$LIMITER" ]]; then
  LIMITER="$REPO_DIR/daily-screen-limit"
fi
if [[ -f "$LIMITER" ]]; then
  install -m 755 "$LIMITER" "$BIN_DIR/daily-screen-limit"
  echo "    installed daily-screen-limit"
fi

if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  echo "==> Installing systemd --user units"
  mkdir -p "$SYSTEMD_USER"
  install -m 644 "$SCRIPT_DIR/pomodoro.service" "$SYSTEMD_USER/"
  if [[ -f "$LIMITER" ]]; then
    install -m 644 "$SCRIPT_DIR/daily-screen-limit.service" "$SYSTEMD_USER/"
    install -m 644 "$SCRIPT_DIR/daily-screen-limit.timer" "$SYSTEMD_USER/"
  fi
  systemctl --user daemon-reload
  systemctl --user enable --now pomodoro.service
  if [[ -f "$LIMITER" ]]; then
    systemctl --user enable --now daily-screen-limit.timer
  fi
  echo "    enabled pomodoro.service"
else
  echo "==> systemd --user not available"
  echo "    Start the daemon manually:  nohup pomodoro daemon >/dev/null 2>&1 &"
  echo "    For the screen-time counter, run daily-screen-limit once a minute"
  echo "    from cron or your desktop's autostart."
fi

echo
echo "==> Done. Try:"
echo "    pomodoro status"
echo "    pomodoro start"
echo "    pomodoro config"
echo
echo "Config: ${XDG_CONFIG_HOME:-~/.config}/pomodoro/config.json"
echo "State:  ${XDG_STATE_HOME:-~/.local/state}/pomodoro/state.json"
