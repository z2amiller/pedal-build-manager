# Pedal Build Manager

A server-rendered web app for guided pedal assembly. Displays interactive PCB board views alongside synchronized Bill of Materials (BOM) panels, helping builders place components correctly.

## System Overview

Three repositories work together to take a KiCad board file through to a shareable build guide:

| Repo | Role |
|------|------|
| [manifest-creator](https://github.com/z2amiller/manifest-creator) | KiCad plugin + headless CLI — exports SVG layers, BOM, and per-footprint overlay SVGs into a `.manifest.zip` |
| [kicad-pedal-common](https://github.com/z2amiller/kicad-pedal-common) | Shared Python library (board adapters, BOM utilities, geometry helpers) vendored into manifest-creator |
| [pedal-build-manager](https://github.com/z2amiller/pedal-build-manager) | FastAPI webapp — accepts `.manifest.zip` uploads and serves the interactive builder experience |

### Workflow

```
Designer:
  KiCad board (.kicad_pcb)
      → manifest-creator plugin (inside KiCad) or CLI (headless)
      → .manifest.zip
      → pedal-build-manager admin upload (browser or --upload-to flag)
      → share /board/{slug}/{version} URL

Builder:
  open URL
      → check off components on the BOM panel
      → click a footprint on the board SVG to highlight it in the BOM
      → progress saved in localStorage
```

## The .manifest.zip Format

A `.manifest.zip` contains everything the webapp needs to render a build guide with no external dependencies:

```
manifest.json                        # board metadata and component list
layers/F.Cu.svg                      # full-board SVG layers exported by kicad-cli
layers/B.Cu.svg
layers/F.Silkscreen.svg
layers/Edge.Cuts.svg
layers/...                           # any other layers present on the board
footprints/{ref}/overlay.svg         # per-footprint highlight overlay
footprints/{ref}/fab.svg             # fabrication outline
footprints/{ref}/courtyard.svg       # courtyard outline
```

`manifest.json` structure:

```json
{
  "schema_version": "1.0",
  "board_name": "my-pedal",
  "display_name": "My Pedal",
  "version": "1.0.0",
  "created_at": "2024-01-01T00:00:00Z",
  "board_bounds": { "x": 12.3, "y": 8.7, "width": 60.96, "height": 76.2 },
  "layers": { "f_cu": "layers/F.Cu.svg", "edge_cuts": "layers/Edge.Cuts.svg" },
  "components": [
    {
      "reference": "R1",
      "value": "10k",
      "footprint": "Resistor_THT:R_Axial_DIN0207",
      "pos_x": 30.5,
      "pos_y": 22.1,
      "outline": { "type": "svg", "overlay_svg": "footprints/R1/overlay.svg", ... }
    }
  ]
}
```

Component positions are board-relative millimetres (0, 0 = top-left of the board outline). All layer SVG viewBoxes are cropped to the board area so the renderer can use them without knowing the KiCad page layout.

## Generating a Manifest

### KiCad plugin (recommended — full BOM + footprint geometry)

Install the manifest-creator plugin via KiCad's Plugin and Content Manager or manually. It runs inside KiCad's embedded Python 3.9 environment and has access to the live board object via IPC.

### Headless CLI (CI / scripting)

```bash
pip install manifest-creator kiutils

python -m manifest_creator \
  --board path/to/board.kicad_pcb \
  --out board-v1.0.0.manifest.zip \
  --version 1.0.0 \
  --display-name "My Pedal"
```

When `kiutils` is installed, the CLI exports a full BOM and footprint geometry without a running KiCad session. Without `kiutils`, only SVG layers are exported.

### Upload directly from the CLI

```bash
python -m manifest_creator \
  --board path/to/board.kicad_pcb \
  --out board-v1.0.0.manifest.zip \
  --version 1.0.0 \
  --upload-to https://builds.example.com \
  --password your-admin-password
```

The password can also be supplied via the `MANIFEST_ADMIN_PASSWORD` environment variable, which is convenient for CI:

```yaml
# GitHub Actions example
- run: |
    python -m manifest_creator \
      --board hardware/board.kicad_pcb \
      --out dist/board-${{ github.ref_name }}.manifest.zip \
      --version ${{ github.ref_name }} \
      --upload-to ${{ vars.BUILD_MANAGER_URL }}
  env:
    MANIFEST_ADMIN_PASSWORD: ${{ secrets.BUILD_MANAGER_PASSWORD }}
```

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
- `POST /admin/set-default/{slug}/{version}` — set the default version shown at `/board/{slug}`

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ADMIN_PASSWORD` | yes | — | Password for `/admin/*` (any username) |
| `BUILDER_DB_PATH` | no | `./data/builder.db` | SQLite database path |

## Admin UI

The admin page at `/admin/` lets you:

- Upload new `.manifest.zip` files
- See all uploaded boards and their versions
- Set the default version shown when a builder visits `/board/{slug}` without a version in the URL

Uploading a manifest with the same `board_name` and `version` as an existing entry overwrites it.

## Deploying with Docker

**Requirements:** Docker + Docker Compose, a domain pointing at your server.

```bash
git clone https://github.com/z2amiller/pedal-build-manager
cd pedal-build-manager

cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and DOMAIN

docker compose up -d
```

Caddy automatically provisions a Let's Encrypt TLS certificate for your domain. Board manifests are stored in the `board_data` named Docker volume and survive container restarts and redeploys.

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
