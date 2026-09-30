# CBA IMS — Production Deployment Checklist

Use this checklist before and after every production deployment. Check items off only when verified, not assumed.

---

## Pre-Deployment

- [ ] Generated a strong, unique `SECRET_KEY` (use `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- [ ] `DEBUG=False` in production `.env`
- [ ] `ALLOWED_HOSTS` set to exact production domain(s) — no wildcards
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` set to HTTPS production domain(s) (e.g. `https://yourdomain.edu.ph`)
- [ ] `DB_*` variables (or `DATABASE_URL`) pointing to production PostgreSQL instance
- [ ] PostgreSQL database and user created; connection verified
- [ ] `python manage.py check --deploy` reports **0 issues**
- [ ] All 274 automated tests passing: `python manage.py test` (0 failures, 0 errors)
- [ ] `requirements.txt` fully installed in production virtualenv


- [ ] `python manage.py migrate` completed successfully
- [ ] `python manage.py collectstatic --noinput` completed successfully
- [ ] `STATIC_ROOT` directory populated with static files
- [ ] `MEDIA_ROOT` directory exists on persistent storage with correct permissions
- [ ] Production admin account created via `python manage.py createsuperuser` (not seed commands)

---

## Security

- [ ] `SECURE_SSL_REDIRECT=True` — set **after** HTTPS is confirmed working
- [ ] `SECURE_HSTS_SECONDS` set to a positive value — set **after** weeks of stable HTTPS operation. Do NOT enable HSTS preload until HTTPS has been stable for months
- [ ] `SESSION_COOKIE_SECURE=True` — automatic when `DEBUG=False`; verify it is not overridden in settings
- [ ] `CSRF_COOKIE_SECURE=True` — automatic when `DEBUG=False`; verify it is not overridden
- [ ] Firewall configured: external access allowed only on ports **80** (HTTP redirect) and **443** (HTTPS); admin SSH on port **22** (restrict to known IPs if possible)
- [ ] PostgreSQL **not** exposed to the public internet (bind to `localhost` or private network only)
- [ ] Demo seed commands (`seed_phase1`–`seed_phase9`) **NOT** run without explicit `--force-demo-data` flag and full understanding of consequences
- [ ] **No demo accounts exist** with known passwords (`admin123`, `dean123`, `chair123`, `faculty123`)
- [ ] Production admin accounts created via `createsuperuser` with strong, unique passwords
- [ ] `.env` file permissions restricted: `chmod 600 /opt/cba_ims/.env`; owned by `cba_ims` user
- [ ] Django `SECRET_KEY` is unique to this deployment (not shared with dev or staging)

---

## Nginx / Gunicorn

- [ ] Gunicorn systemd service created at `/etc/systemd/system/cba_ims.service`
- [ ] Gunicorn service enabled and running: `sudo systemctl is-enabled cba_ims` → `enabled`; `sudo systemctl is-active cba_ims` → `active`
- [ ] Nginx site configuration created and symlinked to `sites-enabled/`
- [ ] Nginx configuration syntax tested: `sudo nginx -t` → `syntax is ok`
- [ ] SSL/TLS certificate installed and valid (check expiry: `sudo certbot certificates`)
- [ ] HTTP to HTTPS redirect working: `curl -I http://yourdomain.edu.ph` returns `301`
- [ ] HTTPS site loading: `curl -I https://yourdomain.edu.ph` returns `200`
- [ ] Certbot auto-renewal verified: `sudo certbot renew --dry-run`
- [ ] Health endpoint reachable: `curl https://yourdomain.edu.ph/health/` returns `200 OK`
- [ ] Static files loading (CSS and icons visible in browser — no 404s in browser DevTools)
- [ ] Media uploads working (upload a test asset image; verify it displays)

---

## Backup

- [ ] `pg_dump` backup scheduled (cron or systemd timer) — see [backup-restore.md](backup-restore.md)
- [ ] `media/` directory backup scheduled separately from database backup
- [ ] Backup destination is **off-server** (separate storage, object storage, or remote host)
- [ ] Backup restore tested: restored a backup to a separate test environment and verified data integrity
- [ ] Backup retention policy defined and documented (suggested: 30 daily, 12 weekly, 3 monthly)
- [ ] `.env` file backed up separately, encrypted, and stored securely (not alongside database backups)

---

## Monitoring

- [ ] Gunicorn logs reviewable: `sudo journalctl -u cba_ims` shows startup and request logs
- [ ] Nginx access log and error log paths confirmed and readable
- [ ] Django `WARNING`-level and above logs reaching systemd journal (no logs silently dropped)
- [ ] No sensitive data (passwords, SECRET_KEY, session cookies) appearing in logs

---

## Post-Go-Live Verification

- [ ] Login works for **Admin** role with production credentials
- [ ] Login works for **Dean** role
- [ ] Login works for **Dept Chair** role
- [ ] Login works for **Faculty** role
- [ ] Dashboard loads and displays correct system-wide stats (Admin view)
- [ ] Asset creation with image upload succeeds
- [ ] Asset image validation: uploading a file > 5 MB is rejected with a clear error
- [ ] Asset image validation: uploading a non-image file (e.g. `.exe` renamed `.jpg`) is rejected
- [ ] QR label generation and print view loads correctly
- [ ] QR code scan (camera or manual code entry) resolves to correct asset
- [ ] Asset assignment workflow completes successfully (assign → return)
- [ ] Report export: CSV download works and opens in Excel without encoding errors
- [ ] Report export: XLSX download works with formatted headers
- [ ] Print view renders correctly in browser print preview
- [ ] Django-axes brute-force protection active: 5 failed logins within 1 hour triggers lockout
- [ ] After lockout: even valid credentials are rejected until lockout expires
- [ ] Logout clears session: back button after logout does not show authenticated pages
- [ ] Custom 404 page displays (no Django debug traceback visible)
- [ ] Custom 500 page displays on simulated error (no traceback visible)
