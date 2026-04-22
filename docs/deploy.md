# Deployment

## Overview

The app runs as a systemd service behind a Caddy reverse proxy on a VPS.

## First-time setup

### 1. Create user and directories

```bash
useradd -r -s /usr/sbin/nologin pedalbuild
mkdir -p /opt/pedal-build-manager
mkdir -p /etc/pedal-build-manager
mkdir -p /var/lib/pedal-build-manager/boards
chown -R pedalbuild:pedalbuild /opt/pedal-build-manager /var/lib/pedal-build-manager
```

### 2. Deploy application

```bash
cd /opt/pedal-build-manager
git clone <repo-url> .
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install ".[dev]"
```

### 3. Configure environment

Create `/etc/pedal-build-manager/env`:

```
ADMIN_PASSWORD=<strong-password>
BUILDER_DATA_DIR=/var/lib/pedal-build-manager/boards
BUILDER_DB_PATH=/var/lib/pedal-build-manager/builder.db
```

```bash
chmod 600 /etc/pedal-build-manager/env
chown root:root /etc/pedal-build-manager/env
```

### 4. Install and start the service

```bash
cp deploy/pedal-build-manager.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pedal-build-manager
```

### 5. Configure Caddy

Edit `deploy/Caddyfile`, replacing `your-domain.com` with your actual domain. Then:

```bash
cp deploy/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy
```

Caddy handles TLS automatically via Let's Encrypt.

## Monitoring

```bash
systemctl status pedal-build-manager
journalctl -u pedal-build-manager -f
```

## Backup

### Setup

Clone a private GitHub repo for backups:

```bash
git clone git@github.com:youruser/pedal-build-backups.git /var/backups/pedal-build
chown pedalbuild:pedalbuild /var/backups/pedal-build
```

Ensure the `pedalbuild` user has an SSH key authorized to push to that repo.

Set `BACKUP_REPO=/var/backups/pedal-build` in `/etc/pedal-build-manager/env`.

### Schedule (cron)

Add to `pedalbuild`'s crontab (`crontab -u pedalbuild -e`):

```
0 3 * * * /opt/pedal-build-manager/deploy/backup.sh >> /var/log/pedal-build-backup.log 2>&1
```

Or use a systemd timer — copy `deploy/backup.sh` into a `.service` + `.timer` unit pair.

### Restore

To restore from backup:

```bash
# Stop the app
systemctl stop pedal-build-manager

# Restore sqlite DB
sqlite3 /var/lib/pedal-build-manager/builder.db ".restore /path/to/builder-YYYYMMDD-HHMMSS.db"

# Restore boards directory
tar -xzf /path/to/boards-YYYYMMDD-HHMMSS.tar.gz -C /var/lib/pedal-build-manager/

systemctl start pedal-build-manager
```

## Updates

```bash
cd /opt/pedal-build-manager
git pull
venv/bin/pip install --upgrade pip
venv/bin/pip install ".[dev]"
systemctl restart pedal-build-manager
```

## Uploading boards

Use `manifest-creator` with `--upload-to` pointing at the **base URL** of the
server (no path). The CLI appends `/admin/upload` automatically:

```bash
python3 -m manifest_creator \
    --board fx-bloodyg.kicad_pcb \
    --out fx-bloodyg-1.0.0.manifest.zip \
    --version 1.0.0 \
    --upload-to https://your-domain.com \
    --password <admin-password>
```

Or set `MANIFEST_ADMIN_PASSWORD` in your environment and omit `--password`.
