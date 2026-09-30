# CBA Asset and Inventory Management System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Django](https://img.shields.io/badge/Django-4.2-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-blue)
![Tests](https://img.shields.io/badge/Tests-274%20Passing-brightgreen)
![Status](https://img.shields.io/badge/Status-Deployment--Ready%20Engineering%20Baseline-blue)

A web-based asset tracking, accountability, and consumable inventory system designed specifically for the College of Business Administration (CBA).


---

## 1. Overview

The CBA Asset and Inventory Management System (CBA IMS) provides comprehensive lifecycle tracking for college-owned equipment, furniture, and consumable office/classroom supplies. It enforces strict physical custody through row-level locking, maintains an immutable audit trail for institutional accountability, and offers responsive, touch-friendly interfaces for desktop, tablet, and mobile devices.

The system replaces manual logbooks and fragmented spreadsheets with a single, verifiable database for administrators, academic deans, department chairs, and faculty members.

---

## 2. Key Features

- **Durable Asset Inventory:** Sequential category-based asset codes (`CBA-{CAT}-{NUM}`), institutional property numbers, decodable photo uploads (max 5MB), and multi-criteria filtering.
- **Faculty Accountability:** Atomic row-locked equipment assignments and returns with condition tracking and printable accountability certificates.
- **Physical Transfers:** Multi-step inter-departmental and inter-location equipment transfers with stale-origin conflict detection.
- **Consumable Supplies:** Ledger-derived inventory balance (never cached or vulnerable to drift), Stock In, Stock Out, adjustments, and reorder warnings.
- **QR Asset Tracking:** Auto-generated QR codes, printable label sheets, and browser camera scanning via WebRTC for physical inventory audits.
- **Temporary Borrowing:** Short-term asset reservations, approvals, checkout/checkin lifecycle, and automated overdue tracking.
- **Equipment Maintenance:** Defect reporting, repair lifecycle tracking, repair cost auditing, and replacement recommendations.
- **Asset Disposal:** Disposal workflows for damaged, retired, or transferred-out property with mandatory administrative sign-off.
- **Operational Reporting:** 14 domain reports with service-layer department scoping, print views, and sanitized CSV and Excel (`.xlsx`) exports.

---

## 3. Technology Stack

- **Backend:** Python 3.10+, Django 4.2 LTS
- **Database:** PostgreSQL 14+ (production); SQLite (local testing only)
- **WSGI / Web:** Gunicorn 22+, Nginx reverse proxy
- **Static Assets:** WhiteNoise 6.7 with compressed manifest caching
- **Security & Throttling:** `django-axes` (5 failed logins = 1-hour lockout)
- **Frontend:** Bootstrap 5.3, Bootstrap Icons 1.10, Chart.js 4.4, HTML5 WebRTC
- **Export & Documents:** openpyxl 3.1, Pillow 10.0, qrcode 7.4

---

## 4. System Architecture

```
Internet (HTTPS :443) ──► Nginx (TLS Termination, Reverse Proxy)
                               │
                       Unix Domain Socket
                               │
                          Gunicorn WSGI
                               │
                     Django 4.2 Application (WhiteNoise Static)
                               │
                      PostgreSQL Database
```

---

## 5. User Roles and Permissions

| Role | Access Scope | Inventory & Operations | Reports & Exports | Audit Log |
|---|---|---|---|---|
| **Admin** (`ADMIN`) | Global | Full Create, Read, Update, Delete | All 14 reports (All Departments) | Full Access |
| **Dean** (`DEAN`) | Global | Read-only across all departments | All 14 reports (All Departments) | Read-only |
| **Chair** (`DEPT_CHAIR`) | Department | Manage equipment within own department | Scoped strictly to own department | No Access |
| **Faculty** (`FACULTY`) | Personal | View assigned assets, request borrowing | No Access (403 Forbidden) | No Access |

*Note: Department Chair report access is enforced at the service query layer; query parameter manipulation (`?department=...`) is ignored.*

---

## 6. Local Development Setup

```bash
# 1. Clone or extract project
cd cba_ims

# 2. Create and activate virtual environment
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure local environment
cp .env.example .env
# Edit .env and ensure DEBUG=True for local development

# 5. Apply database migrations
python manage.py migrate

# 6. (Optional) Populate development test data
python manage.py seed_phase1
# Run seed_phase2 through seed_phase9 as needed

# 7. Start local development server
python manage.py runserver
```

> **WARNING:** `runserver` is single-threaded and for development use only. Never use `runserver` in production.

---

## 7. PostgreSQL Setup

PostgreSQL is required for production because CBA IMS relies on database-level row locking (`select_for_update()`), conditional unique constraints, and transaction atomicity (`transaction.atomic()`).

```sql
-- In PostgreSQL terminal (psql as superuser):
CREATE USER cba_ims_user WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE cba_ims OWNER cba_ims_user;
GRANT ALL PRIVILEGES ON DATABASE cba_ims TO cba_ims_user;
```

In `.env`, configure:
```env
DATABASE_URL=postgres://cba_ims_user:your_secure_password_here@localhost:5432/cba_ims
```

---

## 8. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — | Cryptographically strong secret key |
| `DEBUG` | **Yes** | `False` | Must be `False` in production |
| `ALLOWED_HOSTS` | **Yes** | `localhost` | Comma-separated domain names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | In Prod | `""` | Comma-separated trusted origins (`https://domain.edu.ph`) |
| `DATABASE_URL` | In Prod | — | PostgreSQL connection URI |
| `SECURE_SSL_REDIRECT` | In Prod | `True` | Redirect HTTP requests to HTTPS |
| `SECURE_PROXY_SSL_HEADER` | Proxy | — | Set `True` if behind reverse proxy terminating SSL |
| `SECURE_HSTS_SECONDS` | In Prod | `0` | HSTS max-age seconds (tune gradually) |
| `TIME_ZONE` | No | `UTC` | Target timezone (e.g. `Asia/Manila`) |

---

## 9. Development Seed Data

Seed commands populate realistic scenario data for demonstration and testing:

```bash
python manage.py seed_phase1  # Foundation, departments, locations, users
python manage.py seed_phase2  # Asset inventory
python manage.py seed_phase3  # Active & historical assignments
python manage.py seed_phase4  # Asset transfers
python manage.py seed_phase5  # Consumable stock ledger
python manage.py seed_phase6  # QR stickers & verifications
python manage.py seed_phase7  # Borrowing requests & reservations
python manage.py seed_phase8  # Defect reports & repair cases
python manage.py seed_phase9  # Asset disposal records
```

> **CRITICAL SECURITY SAFEGUARD:**
> Seed commands create demo accounts with publicly known development passwords (`admin123`, `dean123`, `chair123`, `faculty123`).
> When `DEBUG=False`, all seed commands **refuse to execute** unless explicitly overridden with `--force-demo-data`. Demo accounts must never exist in a production database.

---

## 10. Automated Tests

```bash
python manage.py test
```

**Test Baseline:**
- **274 automated tests** across all 11 phases
- **0 failures, 0 errors**
- Verified test modules: `accounts`, `organizations`, `inventory`, `assignments`, `transfers`, `supplies`, `borrowing`, `maintenance`, `disposals`, `reports`, `audit`, and `accounts.tests_phase11` (security, upload validation, axes lockout, error handlers, and health checks)

---

## 11. QR Code and Camera Requirements

- **Scanner:** Uses the browser `navigator.mediaDevices.getUserMedia` API.
- **HTTPS Requirement:** Modern mobile browsers (iOS Safari, Android Chrome) block camera access over plain HTTP. HTTPS is strictly required for camera scanning in production.
- **Printable Labels:** Printable QR code stickers can be generated individually or in batch from the asset detail and inventory list pages.
- **Physical Device Testing:** Automated responsive layout and media constraint tests pass. Physical camera barcode scanning and mobile orientation behavior require manual User Acceptance Testing (UAT) on target physical handheld devices (iOS Safari, Android Chrome) prior to final rollout.


---

## 12. Reports and Exports

- **14 Standard Reports:** Covering asset distribution, faculty accountability, transfer audits, supply burn rates, reorder shortfalls, borrowing overdue status, maintenance expenses, and disposal archives.
- **Exports:** High-speed streaming CSV and Microsoft Excel (`.xlsx`) via openpyxl. Formula injection protection automatically escapes leading `=`, `+`, `-`, and `@` characters.
- **Print Views:** Formatted browser print styles with neutral system verification blocks.

---

## 13. Production Deployment

For complete, step-by-step production setup on Ubuntu Linux with Nginx and Gunicorn:
👉 **See [docs/deployment.md](docs/deployment.md)**
👉 **See [docs/deployment-checklist.md](docs/deployment-checklist.md)**

```bash
# Pre-deployment configuration check
python manage.py check --deploy
# Collect static assets
python manage.py collectstatic --noinput
```

---

## 14. Static and Media Files

- **Static Files (`STATIC_ROOT`):** Collected via `python manage.py collectstatic --noinput` and served via WhiteNoise with compression and cache-busting hashes.
- **Media Files (`MEDIA_ROOT`):** Uploaded asset images and generated QR codes are stored under `media/`.
- **Storage Warning:** Media files are stored on the local filesystem and are **not** stored in PostgreSQL. Media files must be backed up separately (see [docs/backup-restore.md](docs/backup-restore.md)).

---

## 15. Backup and Restore

- **Database:** Nightly automated `pg_dump` backups.
- **Media Directory:** Daily incremental `rsync` or tarball backup of `media/`.
- **Verification:** Regular restoration drills on staging instances.
👉 **See [docs/backup-restore.md](docs/backup-restore.md)**

---

## 16. Security Summary

- **Session Security:** `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `CSRF_COOKIE_HTTPONLY=True`.
- **Frame & Content Protection:** `X_FRAME_OPTIONS='DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF=True`.
- **Cache Restriction:** `NoCachePrivateMiddleware` applies `Cache-Control: private, no-store` to authenticated data views.
- **Brute Force:** `django-axes` blocks IPs after 5 consecutive failed login attempts.
- **Upload Validation:** Asset images require PIL decodability check, extension verification, and 5MB limit.
- **Audit Immutability:** `AuditLog` rows cannot be updated or deleted via ORM.
👉 **See [docs/security.md](docs/security.md)**

---

## 17. Known Limitations

- **No Offline Transaction Sync:** While the PWA service worker provides an offline fallback shell and caches static assets, creating or modifying records offline is not supported.
- **PostgreSQL Dependency:** Local development on SQLite does not support PostgreSQL `select_for_update()` concurrency locking.
- **Email Notifications:** The system does not dispatch external SMTP emails for borrowing or maintenance events; all notifications are in-app.

---

## 18. Troubleshooting

- **Static assets return 404:** Run `python manage.py collectstatic --noinput`.
- **Camera scanner will not launch:** Ensure the site is served over HTTPS; mobile browsers block camera hardware on insecure origins.
- **Account locked out:** Reset via CLI: `python manage.py axes_reset` or wait 1 hour.
- **CSRF 403 on form submit:** Verify `DJANGO_CSRF_TRUSTED_ORIGINS` in `.env` includes the protocol and host (`https://cba-ims.yourdomain.edu.ph`).

---

## 19. Quality Assurance & Manual Testing

For comprehensive test cases across Admin, Dean, Department Chair, and Faculty roles:
👉 **See [docs/uat-checklist.md](docs/uat-checklist.md)**

---

## 20. Development History

For historical notes on Phases 1 through 11:
👉 **See [docs/development-history.md](docs/development-history.md)**
