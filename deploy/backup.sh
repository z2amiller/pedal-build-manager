#!/usr/bin/env bash
# Daily backup: sqlite snapshot + boards tar, committed and pushed to git remote.
# Run via cron or systemd timer (see docs/deploy.md).
set -euo pipefail

# CONFIGURE: set these in /etc/pedal-build-manager/env or export before running
: "${BUILDER_DATA_DIR:?BUILDER_DATA_DIR must be set}"
: "${BUILDER_DB_PATH:?BUILDER_DB_PATH must be set}"
: "${BACKUP_REPO:?BACKUP_REPO must be set (path to local git clone for backups)}"

DATE=$(date -u +"%Y%m%d-%H%M%S")
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# sqlite consistent snapshot via .backup (safe under concurrent writes)
sqlite3 "$BUILDER_DB_PATH" ".backup $STAGING/builder-$DATE.db"

# Board files archive
tar -czf "$STAGING/boards-$DATE.tar.gz" -C "$(dirname "$BUILDER_DATA_DIR")" \
    "$(basename "$BUILDER_DATA_DIR")"

# Copy into backup repo, commit, push
cp "$STAGING"/*.db "$STAGING"/*.tar.gz "$BACKUP_REPO/"
cd "$BACKUP_REPO"
git add .
git commit -m "backup $DATE"
git push

echo "Backup $DATE complete."
