# Pedal Build Manager

A server-rendered web app for guided pedal assembly. Displays interactive PCB board views alongside synchronized Bill of Materials (BOM) panels, helping builders place components correctly.

## Stack

- **FastAPI** — Python web framework
- **Jinja2** — server-side HTML templating
- **HTMX** — dynamic updates without a JS framework
- Vanilla JS modules for SVG interactivity

## Installation

```bash
pip install -e ".[dev]"
```

## Running the Dev Server

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 in your browser.

## Routes

- `GET /` — index page listing available boards
- `GET /board/{slug}/{version}` — two-panel board view (BOM left, SVG right)
- `GET /admin/` — upload interface (HTTP Basic auth, requires `ADMIN_PASSWORD`)
- `POST /admin/upload` — upload a `.manifest.zip`

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ADMIN_PASSWORD` | yes | — | Password for `/admin/*` (any username) |
| `BUILDER_DB_PATH` | no | `./data/builder.db` | SQLite database path |

## Deploying with Docker

**Requirements:** Docker + Docker Compose, a domain pointing at your server.

```bash
git clone https://github.com/z2amiller/pedal-build-manager
cd pedal-build-manager

cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and DOMAIN

docker compose up -d
```

Caddy automatically provisions a Let's Encrypt TLS certificate for your domain. Board manifests are stored in the `board_data` named volume and survive container restarts and redeploys.

To redeploy after a code update:

```bash
git pull
docker compose build
docker compose up -d
```

## Deploying without Docker (systemd)

```bash
# Create user and directories
sudo useradd -r -s /bin/false pedalbuild
sudo mkdir -p /opt/pedal-build-manager /etc/pedal-build-manager /data/pedal-build-manager
sudo chown pedalbuild:pedalbuild /data/pedal-build-manager

# Install app
sudo git clone https://github.com/z2amiller/pedal-build-manager /opt/pedal-build-manager
cd /opt/pedal-build-manager
sudo -u pedalbuild python3 -m venv venv
sudo -u pedalbuild venv/bin/pip install . \
    "git+https://github.com/z2amiller/kicad-pedal-common.git"

# Configure
sudo tee /etc/pedal-build-manager/env <<EOF
ADMIN_PASSWORD=changeme
BUILDER_DB_PATH=/data/pedal-build-manager/builder.db
EOF
sudo chmod 600 /etc/pedal-build-manager/env

# Install and start service
sudo cp deploy/pedal-build-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pedal-build-manager
```

Then configure Caddy (or nginx) to reverse-proxy to `localhost:8000`. A Caddyfile template is in `deploy/Caddyfile.example`.
