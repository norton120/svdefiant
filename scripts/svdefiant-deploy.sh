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

# Uncommitted changes are the only state we refuse to auto-resolve — they
# almost certainly mean a human SSH'd in and is editing. Diverged HEADs
# (agent committed without pushing) are recovered automatically below.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "deploy: aborting — uncommitted changes in $REPO" >&2
  exit 1
fi

# `HEAD:<path>` is the blob sha — content hash, ignores no-op commits.
before="$(git rev-parse "HEAD:$WATCH" 2>/dev/null || echo missing)"

git fetch --quiet origin main

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"

if [[ "$local_head" == "$remote_head" ]]; then
  exit 0
fi

if git merge-base --is-ancestor "$local_head" "$remote_head"; then
  # Fast-forward: the safe, expected path.
  git merge --ff-only --quiet origin/main
else
  # Diverged: this clone has commits origin doesn't. The Pi is a deploy
  # target — anything important is supposed to be pushed. Resetting keeps
  # the deploy pipeline unblocked; the lost commits are logged loudly so
  # they show up in `journalctl --user-unit=svdefiant-deploy.service`.
  echo "deploy: WARNING — local HEAD $local_head diverged from origin/main $remote_head; resetting. Lost commits:" >&2
  git log --oneline --no-decorate "$remote_head..$local_head" >&2 || true
  git reset --hard --quiet origin/main
fi

after="$(git rev-parse "HEAD:$WATCH" 2>/dev/null || echo missing)"

if [[ "$before" == "$after" ]]; then
  exit 0
fi

echo "deploy: $WATCH changed ($before → $after); restarting $UNIT"
systemctl --user restart "$UNIT"
