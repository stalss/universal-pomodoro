#!/usr/bin/env bash
# Install site-blocker + the passwordless sudo rule the Pomodoro reward needs.
# Must be run as root:  sudo ./install-site-blocker.sh [username]
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo ./install-site-blocker.sh [username]" >&2
  exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USERNAME="${1:-${SUDO_USER:-}}"
if [[ -z "$USERNAME" ]]; then
  echo "Usage: sudo ./install-site-blocker.sh <username>" >&2
  exit 2
fi
if ! id "$USERNAME" >/dev/null 2>&1; then
  echo "No such user: $USERNAME" >&2
  exit 2
fi

echo "==> Installing site-blocker binary"
install -m 755 "$DIR/site-blocker" /usr/local/bin/site-blocker

echo "==> Installing sudoers rule for $USERNAME"
SUDOERS_TMP="$(mktemp)"
sed "s/^USERNAME /$USERNAME /" "$DIR/sudoers.d/site-blocker" > "$SUDOERS_TMP"
if ! visudo -cf "$SUDOERS_TMP"; then
  echo "Generated sudoers rule failed validation; nothing installed." >&2
  rm -f "$SUDOERS_TMP"
  exit 1
fi
install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/site-blocker
rm -f "$SUDOERS_TMP"

echo "==> Installing heal watchdog units"
install -m 644 "$DIR/systemd/site-blocker-heal.service" /etc/systemd/system/
install -m 644 "$DIR/systemd/site-blocker-heal.timer" /etc/systemd/system/

echo "==> Downloading lists and configuring DNS (site-blocker update)"
/usr/local/bin/site-blocker update

echo "==> Enabling heal timer"
systemctl daemon-reload
systemctl enable --now site-blocker-heal.timer

echo
echo "==> Done. Verify with:"
echo "    sudo -n -u $USERNAME /usr/local/bin/site-blocker paused"
echo "    sudo -n -u $USERNAME /usr/local/bin/site-blocker status"
