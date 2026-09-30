# CBA IMS — Production Deployment Guide

This guide covers deploying the CBA Asset & Inventory Management System on Ubuntu 22.04 LTS with Nginx, Gunicorn, and PostgreSQL.

---

## 1. Architecture Overview

```
Internet (HTTPS :443)
        │
  ┌─────▼──────┐
  │   Nginx    │  TLS termination, static file serving, reverse proxy
  └─────┬──────┘
        │ HTTP (Unix socket)
  ┌─────▼──────┐
  │  Gunicorn  │  WSGI server — multiple worker processes
  └─────┬──────┘
        │ WSGI
  ┌─────▼──────┐
  │   Django   │  Application logic, ORM, auth, RBAC
  └─────┬──────┘
        │ psycopg2
  ┌─────▼──────┐
  │ PostgreSQL │  Persistent relational storage
  └────────────┘
```

**Why each component:**

| Component | Role |
|-----------|------|
| **Nginx** | Terminates TLS, serves static/media files directly (bypassing Python), acts as reverse proxy to Gunicorn socket, applies security headers |
| **Gunicorn** | Production WSGI server; runs multiple workers to handle concurrent requests; `runserver` is single-threaded and not safe for production |
| **Django** | Application framework; handles routing, authentication, RBAC, ORM queries, template rendering |
| **PostgreSQL** | Required for production; `select_for_update()` row locking used by assignment, borrowing, transfer, and disposal services requires a real RDBMS |
| **WhiteNoise** | Serves compressed, cache-busted static files from the same Gunicorn process; used as fallback and during Nginx-less setups |

---

## 2. Prerequisites

- **OS:** Ubuntu 22.04 LTS (recommended)
- **Python:** 3.10 or newer
- **PostgreSQL:** 14 or newer
- **Nginx:** latest stable
- **Domain name** with DNS A record pointing to the server's public IP
- **SSL certificate** — [Let's Encrypt](https://letsencrypt.org/) via certbot (free)
- **Firewall:** UFW or equivalent; allow ports 22, 80, 443 only

---

## 3. Step-by-Step Deployment

### 3a. System Setup

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install system dependencies
sudo apt install -y python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib nginx certbot python3-certbot-nginx \
    git curl

# Create a dedicated deploy user (no login shell for security)
sudo useradd --system --shell /usr/sbin/nologin --home /opt/cba_ims cba_ims
```

### 3b. Copy Application to /opt/cba_ims/

```bash
# Create application directory
sudo mkdir -p /opt/cba_ims
sudo chown cba_ims:cba_ims /opt/cba_ims

# Copy application files (from your local machine or CI/CD pipeline)
# Example using rsync from your workstation:
rsync -avz --exclude='venv/' --exclude='*.pyc' --exclude='db.sqlite3' \
    ./cba_ims/ deploy@your-server:/opt/cba_ims/

# Or extract a release archive:
sudo -u cba_ims tar -xzf cba_ims_release.tar.gz -C /opt/cba_ims/
```

### 3c. Create Virtualenv and Install Requirements

```bash
sudo -u cba_ims bash -c "
    cd /opt/cba_ims
    python3.11 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
```

### 3d. Set Up PostgreSQL

```bash
# Switch to postgres superuser
sudo -u postgres psql

-- Inside psql:
CREATE USER cba_ims_user WITH PASSWORD 'CHANGE_THIS_TO_A_STRONG_PASSWORD';
CREATE DATABASE cba_ims OWNER cba_ims_user;
GRANT ALL PRIVILEGES ON DATABASE cba_ims TO cba_ims_user;
\q
```

### 3e. Create the .env File

> **Never commit `.env` to version control.** Store it separately and encrypted.

```bash
sudo -u cba_ims nano /opt/cba_ims/.env
```

Paste and fill in the following:

```dotenv
# Django Core
SECRET_KEY=replace-with-a-50-character-random-string-generated-securely
DEBUG=False
ALLOWED_HOSTS=yourdomain.edu.ph,www.yourdomain.edu.ph

# CSRF — must match ALLOWED_HOSTS with https:// scheme
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.edu.ph,https://www.yourdomain.edu.ph

# Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=cba_ims
DB_USER=cba_ims_user
DB_PASSWORD=CHANGE_THIS_TO_A_STRONG_PASSWORD
DB_HOST=localhost
DB_PORT=5432

# Static & Media
STATIC_ROOT=/opt/cba_ims/staticfiles
MEDIA_ROOT=/opt/cba_ims/media

# Security (enable after HTTPS is confirmed working)
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=0

# Reverse Proxy SSL Header (enable ONLY when behind trusted Nginx terminating SSL)
SECURE_PROXY_SSL_HEADER=True
```

**Variable reference:**

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django cryptographic signing key. Must be unique per deployment. Generate with: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | Must be `False` in production. Exposes tracebacks and disables security features if `True` |
| `ALLOWED_HOSTS` | Comma-separated list of valid hostnames. Prevents HTTP Host header attacks |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Full HTTPS origin(s) for CSRF (e.g. `https://yourdomain.edu.ph`). Required when using a reverse proxy |
| `DATABASE_URL` | Optional PostgreSQL URI (`postgres://user:pass@host:5432/dbname`). Overrides individual `DB_*` settings |
| `DB_*` | Individual PostgreSQL connection credentials (`DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`) |
| `STATIC_ROOT` | Absolute path where `collectstatic` writes files |
| `MEDIA_ROOT` | Absolute path for uploaded asset images. Must be on persistent storage |
| `SECURE_SSL_REDIRECT` | Redirects all HTTP traffic to HTTPS at the Django level |
| `SECURE_PROXY_SSL_HEADER` | Set to `True` **only** when Django is behind a trusted reverse proxy (e.g. Nginx). Assumes Nginx sets `proxy_set_header X-Forwarded-Proto $scheme;` and strips any client-supplied `X-Forwarded-Proto`. Never enable if Django is directly reachable without the proxy |
| `SECURE_HSTS_SECONDS` | HSTS max-age in seconds. Start at `0`, increase gradually after HTTPS is stable |


### 3f. Run Database Migrations

```bash
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py migrate
```

### 3g. Collect Static Files

```bash
sudo mkdir -p /opt/cba_ims/staticfiles
sudo chown cba_ims:cba_ims /opt/cba_ims/staticfiles

sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py collectstatic --noinput
```

### 3h. (Optional) Load Demo Data — DEVELOPMENT USE ONLY

> **WARNING:** Demo seed commands create accounts with well-known passwords (`admin123`, `dean123`, etc.). **Never run these on a production server with real data.** If you must run them for testing, pass `--force-demo-data` and immediately change all passwords afterward.

```bash
# Only run on a clean development/staging database
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py seed_phase1 --force-demo-data
# ... seed_phase2 through seed_phase9 --force-demo-data
```

### 3i. Create Production Admin Account

```bash
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py createsuperuser
```

Follow the prompts. Use a strong, unique password. **Do not use `admin123` or any demo password.**

### 3j. Configure Gunicorn Systemd Service

Create the service file (see Section 4 below), then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cba_ims
sudo systemctl start cba_ims
sudo systemctl status cba_ims
```

### 3k. Configure Nginx

Create the Nginx site configuration (see Section 5 below), then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/cba_ims /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 3l. Obtain SSL Certificate with Certbot

```bash
sudo certbot --nginx -d yourdomain.edu.ph -d www.yourdomain.edu.ph
```

Certbot will automatically modify the Nginx config to add SSL and set up auto-renewal.

Verify auto-renewal:

```bash
sudo certbot renew --dry-run
```

### 3m. Final Deployment Check

```bash
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py check --deploy
```

This should report **0 issues**. Address any issues before going live.

---

## 4. Gunicorn Systemd Service File

Create `/etc/systemd/system/cba_ims.service`:

```ini
[Unit]
Description=CBA IMS Gunicorn WSGI Server
After=network.target postgresql.service

[Service]
Type=notify
User=cba_ims
Group=cba_ims
WorkingDirectory=/opt/cba_ims
EnvironmentFile=/opt/cba_ims/.env
ExecStart=/opt/cba_ims/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/run/cba_ims/cba_ims.sock \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    --log-level warning \
    config.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
RuntimeDirectory=cba_ims
RuntimeDirectoryMode=0755
Restart=on-failure
RestartSec=5s
SyslogIdentifier=cba_ims

[Install]
WantedBy=multi-user.target
```

**Worker count guidance:** A common starting formula is `(2 × CPU cores) + 1`. For a 1-CPU VPS: 3 workers. For a 2-CPU server: 5 workers. Adjust based on memory and load testing.

---

## 5. Nginx Site Configuration

Create `/etc/nginx/sites-available/cba_ims`:

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name yourdomain.edu.ph www.yourdomain.edu.ph;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name yourdomain.edu.ph www.yourdomain.edu.ph;

    # SSL — paths set by certbot
    ssl_certificate     /etc/letsencrypt/live/yourdomain.edu.ph/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.edu.ph/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header X-Frame-Options           "DENY"            always;
    add_header X-Content-Type-Options    "nosniff"         always;
    add_header Referrer-Policy           "same-origin"     always;
    add_header X-XSS-Protection          "1; mode=block"   always;

    # Static files (served directly by Nginx — no Django overhead)
    location /static/ {
        alias /opt/cba_ims/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Media files (uploaded asset images, QR codes, attachments)
    location /media/ {
        alias /opt/cba_ims/media/;
        expires 7d;
        add_header X-Content-Type-Options "nosniff" always;
    }

    # All other requests → Gunicorn
    location / {
        proxy_pass         http://unix:/run/cba_ims/cba_ims.sock;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;

        # Upload size limit (asset images: 5MB + form overhead)
        client_max_body_size 10M;
    }

    # Health check (no auth required)
    location /health/ {
        proxy_pass http://unix:/run/cba_ims/cba_ims.sock;
        proxy_set_header Host $host;
        access_log off;
    }
}
```

---

## 6. Media Files Persistence

> **IMPORTANT:** Media files (uploaded asset photos, QR code images, maintenance attachments) are stored in `MEDIA_ROOT` on the server filesystem.

- **PostgreSQL backups do NOT include media files.** Database dumps only contain database rows.
- Back up the `media/` directory separately using rsync, tar, or object storage sync.
- If you migrate servers, copy `media/` to the new server before pointing DNS.
- Set correct ownership: `sudo chown -R cba_ims:www-data /opt/cba_ims/media/`
- Set correct permissions: `sudo chmod -R 750 /opt/cba_ims/media/`

Refer to [docs/backup-restore.md](backup-restore.md) for full backup procedures.

---

## 7. Production Server Warning

> **NEVER use `python manage.py runserver` in production.**

`runserver` is a single-threaded development server that:
- Does not handle concurrent requests properly
- Does not serve static/media files efficiently
- Has no process management or restart capability
- Is not hardened against malicious input

Use Gunicorn behind Nginx as described in this guide.

---

## 8. Useful Commands

```bash
# Check service status
sudo systemctl status cba_ims

# View live logs
sudo journalctl -u cba_ims -f

# Restart application after code update
sudo systemctl restart cba_ims

# Reload Nginx after config change
sudo nginx -t && sudo systemctl reload nginx

# Run deployment check
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py check --deploy

# Apply new migrations
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py migrate

# Re-collect static files after frontend changes
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py collectstatic --noinput
```
