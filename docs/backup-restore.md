# CBA IMS — Backup and Restore Guide

> **Critical:** A backup is not considered verified until restoration has been successfully tested on a separate environment.

---

## 1. What to Back Up

| Component | Why | Backup Method |
|-----------|-----|---------------|
| **PostgreSQL database** | All application data: assets, assignments, transfers, borrowings, maintenance, disposals, audit logs, users | `pg_dump` |
| **`media/` directory** | Uploaded asset photographs, QR code images, maintenance attachments | `rsync` or `tar` |
| **`.env` file** | Database credentials, SECRET_KEY, production settings | Copy separately, **encrypted** |
| `staticfiles/` | ❌ **Not needed** — regenerated at any time with `python manage.py collectstatic --noinput` | — |
| `venv/` | ❌ **Not needed** — rebuilt from `requirements.txt` | — |

---

## 2. Database Backup

### Manual Backup (pg_dump)

**Plain SQL format** (human-readable, easy to inspect):
```bash
pg_dump -U cba_ims_user -h localhost cba_ims \
    > /opt/backups/cba_ims_$(date +%Y%m%d_%H%M%S).sql
```

**Custom binary format** (compressed, faster restore with `pg_restore`):
```bash
pg_dump -Fc -U cba_ims_user -h localhost cba_ims \
    > /opt/backups/cba_ims_$(date +%Y%m%d_%H%M%S).dump
```

### Automated Daily Backup Script

Create `/opt/scripts/backup_cba_ims.sh`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/opt/backups/db"
RETAIN_DAYS=30
DB_USER="cba_ims_user"
DB_NAME="cba_ims"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="${BACKUP_DIR}/cba_ims_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting database backup..."
pg_dump -Fc -U "$DB_USER" -h localhost "$DB_NAME" > "$FILENAME"
echo "[$(date)] Backup written: $FILENAME ($(du -sh "$FILENAME" | cut -f1))"

# Remove backups older than RETAIN_DAYS
find "$BACKUP_DIR" -name "*.dump" -mtime +${RETAIN_DAYS} -delete
echo "[$(date)] Old backups pruned (>${RETAIN_DAYS} days)"
```

```bash
sudo chmod +x /opt/scripts/backup_cba_ims.sh
```

### Schedule with Cron

```bash
sudo crontab -e
```

Add (runs daily at 02:00):
```cron
0 2 * * * /opt/scripts/backup_cba_ims.sh >> /var/log/cba_ims_backup.log 2>&1
```

### Retention Policy (Recommended)

| Frequency | Count | Retention Period |
|-----------|-------|-----------------|
| Daily | 30 | ~1 month |
| Weekly | 12 | ~3 months |
| Monthly | 3 | ~3 months |

Implement weekly/monthly retention by adding logic to the backup script, or use a tool like `restic` or `pgbackrest`.

---

## 3. Media File Backup

### Using rsync (incremental — preferred)

```bash
rsync -avz --delete \
    /opt/cba_ims/media/ \
    /opt/backups/media/
```

For remote backup (to another server or NAS):
```bash
rsync -avz --delete \
    /opt/cba_ims/media/ \
    backupuser@backup-server:/opt/backups/cba_ims/media/
```

### Using tar (snapshot archive)

```bash
tar -czf /opt/backups/media/media_$(date +%Y%m%d).tar.gz \
    -C /opt/cba_ims media/
```

### Schedule Media Backup with Cron

```cron
30 2 * * * rsync -az --delete /opt/cba_ims/media/ /opt/backups/media/ >> /var/log/cba_ims_media_backup.log 2>&1
```

---

## 4. Database Restore Procedure

> **Always restore to a test environment first. Verify data integrity before restoring to production.**

### Step 1: Stop the Application

```bash
sudo systemctl stop cba_ims
```

### Step 2: Drop and Recreate the Database

```bash
sudo -u postgres psql -c "DROP DATABASE IF EXISTS cba_ims;"
sudo -u postgres psql -c "CREATE DATABASE cba_ims OWNER cba_ims_user;"
```

### Step 3: Restore the Backup

**From custom binary format (`.dump`):**
```bash
pg_restore -U cba_ims_user -h localhost -d cba_ims \
    /opt/backups/db/cba_ims_20260930_020000.dump
```

**From plain SQL format (`.sql`):**
```bash
psql -U cba_ims_user -h localhost -d cba_ims \
    < /opt/backups/db/cba_ims_20260930_020000.sql
```

### Step 4: Apply Any Pending Migrations

```bash
sudo -u cba_ims /opt/cba_ims/venv/bin/python /opt/cba_ims/manage.py migrate
```

This is safe to run; Django tracks applied migrations and will only apply new ones.

### Step 5: Restart the Application

```bash
sudo systemctl start cba_ims
sudo systemctl status cba_ims
```

### Step 6: Verify Restore

- [ ] Login works (Admin, Dean, Chair, Faculty roles)
- [ ] Asset list shows expected assets
- [ ] Recent audit log entries are present
- [ ] Asset images display correctly (confirms media restore)
- [ ] Dashboard statistics appear plausible

---

## 5. Media File Restore

### From rsync backup directory:

```bash
sudo systemctl stop cba_ims
sudo rsync -avz /opt/backups/media/ /opt/cba_ims/media/
sudo chown -R cba_ims:www-data /opt/cba_ims/media/
sudo chmod -R 750 /opt/cba_ims/media/
sudo systemctl start cba_ims
```

### From tar archive:

```bash
sudo systemctl stop cba_ims
sudo tar -xzf /opt/backups/media/media_20260930.tar.gz -C /opt/cba_ims/
sudo chown -R cba_ims:www-data /opt/cba_ims/media/
sudo chmod -R 750 /opt/cba_ims/media/
sudo systemctl start cba_ims
```

---

## 6. Verification — Critical

> **A backup is not considered verified until restoration has been tested.**

**Monthly drill checklist:**

- [ ] Restore the most recent database backup to a separate test environment
- [ ] Restore the most recent media backup alongside it
- [ ] Run `python manage.py check` — no errors
- [ ] Log in as admin, dean, chair, and faculty — all succeed
- [ ] Verify that assets, assignments, borrowings, and audit logs are present and correct
- [ ] Verify that at least one asset image loads (confirms media integrity)
- [ ] Record the drill date and result in an operations log

---

## 7. Backup Security

> **Backups contain all application data including user information. Treat them with the same security level as production.**

- **Store backups off-server.** A server failure should not also destroy your backups. Use:
  - A separate VPS or cloud storage bucket (e.g., S3-compatible object storage)
  - A NAS on a different network segment
  - An encrypted offsite location

- **Encrypt sensitive backup files:**
  ```bash
  gpg --symmetric --cipher-algo AES256 /opt/backups/db/cba_ims_20260930.dump
  # Produces: cba_ims_20260930.dump.gpg
  ```

- **Restrict access to backup storage:**
  - Backup directories: `chmod 700 /opt/backups/`; owned by `root` or a dedicated `backup` user
  - Remote backup credentials: use SSH keys, not passwords

- **`.env` file backups:**
  - Store **separately** from database backups (different location, different encryption key)
  - Never include `.env` in the same archive as database dumps
  - If the `.env` is compromised, rotate `SECRET_KEY` immediately (invalidates all sessions), rotate the database password, and redeploy

- **Audit backup access:** Log who accesses backup storage and when.
