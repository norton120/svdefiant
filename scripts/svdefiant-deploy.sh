#!/usr/bin/env bash
# svdefiant-deploy.sh — pull main, restart ironclaw on MCP changes.
#
# Run periodically by a systemd --user timer on ironclaw. Install once:
#
#   cat > ~/.config/systemd/user/svdefiant-deploy.service <<'EOF'
#   [Unit]
#   Description=svdefiant: pull main + restart ironclaw on MCP changes
#   [Service]
#   Type=oneshot
#   ExecStart=%h/app/svdefiant/scripts/svdefiant-deploy.sh
#   EOF
#
#   cat > ~/.config/systemd/user/svdefiant-deploy.timer <<'EOF'
#   [Unit]
#   Description=svdefiant deploy check (every 2 min)
#   [Timer]
#   OnBootSec=1min
#   OnUnitActiveSec=2min
#   Unit=svdefiant-deploy.service
#   [Install]
#   WantedBy=timers.target
#   EOF
#
#   systemctl --user daemon-reload
#   systemctl --user enable --now svdefiant-deploy.timer
#
# Logs: journalctl --user-unit=svdefiant-deploy.service -f
# Requires loginctl enable-linger on the running user (already set on ironclaw).

set -euo pipefail

REPO="${SVDEFIANT_REPO:-$HOME/app/svdefiant}"
WATCH="scripts/defiant_mcp.py"
UNIT="${SVDEFIANT_UNIT:-ironclaw.service}"

cd "$REPO"

# Local changes would block --ff-only pull; refuse rather than auto-stash.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "deploy: aborting — uncommitted changes in $REPO" >&2
  exit 1
fi

# `HEAD:<path>` is the blob sha — content hash, ignores no-op commits.
before="$(git rev-parse "HEAD:$WATCH" 2>/dev/null || echo missing)"

if ! git pull --ff-only --quiet origin main; then
  echo "deploy: git pull failed" >&2
  exit 1
fi

after="$(git rev-parse "HEAD:$WATCH" 2>/dev/null || echo missing)"

if [[ "$before" == "$after" ]]; then
  exit 0
fi

echo "deploy: $WATCH changed ($before → $after); restarting $UNIT"
systemctl --user restart "$UNIT"
