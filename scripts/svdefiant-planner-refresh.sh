#!/usr/bin/env bash
# svdefiant-planner-refresh.sh — daily rebuild of data/planner.json on ironclaw.
#
# The "Today" / "Tomorrow" labels in planner.json are baked at publish time
# (see bin/defiant cmd_planner_publish). Without this timer the public page
# shows yesterday-as-Today until Stub gets around to running coordinate.
#
# Run nightly via a systemd --user timer on ironclaw. Install once:
#
#   cat > ~/.config/systemd/user/svdefiant-planner-refresh.service <<'EOF'
#   [Unit]
#   Description=svdefiant: refresh planner.json so Today/Tomorrow stay current
#   [Service]
#   Type=oneshot
#   ExecStart=%h/app/svdefiant/scripts/svdefiant-planner-refresh.sh
#   EOF
#
#   cat > ~/.config/systemd/user/svdefiant-planner-refresh.timer <<'EOF'
#   [Unit]
#   Description=svdefiant planner refresh (daily just after local midnight)
#   [Timer]
#   # Local time. The CLI now anchors "today" on local wall-clock; matching the
#   # timer to local midnight keeps the rollover aligned with how a human reads
#   # the calendar. If you ever want UTC instead, append " UTC" to OnCalendar.
#   OnCalendar=*-*-* 00:10:00
#   Persistent=true
#   Unit=svdefiant-planner-refresh.service
#   [Install]
#   WantedBy=timers.target
#   EOF
#
#   systemctl --user daemon-reload
#   systemctl --user enable --now svdefiant-planner-refresh.timer
#
# Logs: journalctl --user-unit=svdefiant-planner-refresh.service -f
# Requires loginctl enable-linger on the running user (already set on ironclaw).

set -euo pipefail

# Self-locate so the script works regardless of where the repo is cloned.
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"

# Pull latest so we don't republish on top of a stale checkout (the deploy
# timer runs every 2min but races are cheap to avoid here).
git pull --ff-only --quiet

# publish --push: regenerate JSON, commit if changed, push. No-ops cleanly.
exec "${REPO}/bin/defiant" planner publish --push
