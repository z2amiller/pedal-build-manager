#!/usr/bin/env bash
# Pull latest code and restart all pedal-build-manager instances.
# Safe to run from cron — only restarts services if something changed.
#
# Suggested crontab (as root):
#   0 3 * * * /opt/pedal-build-manager/deploy/update.sh >> /var/log/pedal-build-update.log 2>&1

set -euo pipefail

APP_DIR="/opt/pedal-build-manager"
TIMESTAMP="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo "=== ${TIMESTAMP} ==="

cd "${APP_DIR}"

# Pull latest — capture output to detect whether anything changed
PULL_OUT="$(git pull 2>&1)"
echo "${PULL_OUT}"

if echo "${PULL_OUT}" | grep -q "Already up to date"; then
    echo "No changes — skipping reinstall and restart."
    exit 0
fi

echo "Changes detected ($(git rev-parse --short HEAD)) — updating dependencies…"
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet ".[dev]"

# Restart all pedal-build-* services that are currently active
RESTARTED=0
for svc in $(systemctl list-units 'pedal-build-*.service' --state=active --no-legend | awk '{print $1}'); do
    echo "Restarting ${svc}…"
    systemctl restart "${svc}"
    RESTARTED=$((RESTARTED + 1))
done

echo "Done — ${RESTARTED} service(s) restarted."
