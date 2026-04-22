#!/usr/bin/env bash
# Add a new per-user pedal-build-manager instance.
#
# Usage:
#   ./deploy/add-user.sh <username> <subdomain> [--port PORT] [--password PASSWORD]
#
# Example:
#   ./deploy/add-user.sh alice alice.pedalfx.z2amiller.com
#   ./deploy/add-user.sh alice alice.pedalfx.z2amiller.com --port 8002 --password s3cr3t
#
# If --password is omitted, a random one is generated and printed.
# If --port is omitted, the next free port above 8000 is used.
# Must be run as root.

set -euo pipefail

# ── defaults ────────────────────────────────────────────────────────────────
APP_DIR="/opt/pedal-build-manager"
DATA_ROOT="/var/lib/pedal-build-manager"
ENV_DIR="/etc/pedal-build-manager"
CADDYFILE="/etc/caddy/Caddyfile"
SERVICE_USER="pedalbuild"
BASE_PORT=8001   # ports are assigned starting here; 8000 is the main instance

# ── arg parsing ─────────────────────────────────────────────────────────────
USERNAME=""
SUBDOMAIN=""
PORT=""
PASSWORD=""

usage() {
    echo "Usage: $0 <username> <subdomain> [--port PORT] [--password PASSWORD]" >&2
    exit 1
}

[[ $# -lt 2 ]] && usage
USERNAME="$1"; shift
SUBDOMAIN="$1"; shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)     PORT="$2";     shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# ── validate username ────────────────────────────────────────────────────────
if [[ ! "$USERNAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "ERROR: username must be lowercase alphanumeric/hyphens/underscores" >&2
    exit 1
fi

SERVICE="pedal-build-${USERNAME}"
ENV_FILE="${ENV_DIR}/${USERNAME}.env"
DATA_DIR="${DATA_ROOT}/${USERNAME}"

# ── check for conflicts ──────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    echo "ERROR: ${ENV_FILE} already exists — user '${USERNAME}' already set up?" >&2
    exit 1
fi
if systemctl list-unit-files "${SERVICE}.service" &>/dev/null && \
   systemctl list-unit-files "${SERVICE}.service" | grep -q "${SERVICE}"; then
    echo "ERROR: systemd service ${SERVICE}.service already exists" >&2
    exit 1
fi

# ── auto-assign port if not given ────────────────────────────────────────────
if [[ -z "$PORT" ]]; then
    PORT=$BASE_PORT
    while ss -tlnp | grep -q ":${PORT} " || \
          grep -r "port ${PORT}" /etc/systemd/system/pedal-build-*.service 2>/dev/null | grep -q .; do
        PORT=$((PORT + 1))
    done
fi

# ── generate password if not given ───────────────────────────────────────────
GENERATED_PASSWORD=false
if [[ -z "$PASSWORD" ]]; then
    PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 24)"
    GENERATED_PASSWORD=true
fi

# ── create data directories ──────────────────────────────────────────────────
echo "Creating data directories at ${DATA_DIR}…"
mkdir -p "${DATA_DIR}/boards"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}"

# ── write env file ────────────────────────────────────────────────────────────
echo "Writing env file at ${ENV_FILE}…"
cat > "${ENV_FILE}" <<EOF
ADMIN_PASSWORD=${PASSWORD}
BUILDER_DATA_DIR=${DATA_DIR}/boards
BUILDER_DB_PATH=${DATA_DIR}/builder.db
EOF
chmod 600 "${ENV_FILE}"
chown root:root "${ENV_FILE}"

# ── write systemd service ────────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
echo "Writing systemd service at ${SERVICE_FILE}…"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Pedal Build Manager (${USERNAME})
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/uvicorn app.main:app \\
    --host 127.0.0.1 \\
    --port ${PORT} \\
    --workers 1
Restart=on-failure
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# ── append to Caddyfile ───────────────────────────────────────────────────────
echo "Appending to ${CADDYFILE}…"
cat >> "${CADDYFILE}" <<EOF

${SUBDOMAIN} {
    reverse_proxy localhost:${PORT}
}
EOF

# ── enable and start ─────────────────────────────────────────────────────────
echo "Enabling and starting ${SERVICE}…"
systemctl daemon-reload
systemctl enable --now "${SERVICE}"
systemctl reload caddy

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "✓ User '${USERNAME}' is ready."
echo "  URL:      https://${SUBDOMAIN}"
echo "  Port:     ${PORT}"
echo "  Data:     ${DATA_DIR}"
echo "  Service:  ${SERVICE}.service"
if $GENERATED_PASSWORD; then
    echo "  Password: ${PASSWORD}   ← save this now, it won't be shown again"
fi
echo ""
echo "To monitor: journalctl -u ${SERVICE} -f"
echo "To remove:  systemctl disable --now ${SERVICE} && rm ${SERVICE_FILE} ${ENV_FILE}"
