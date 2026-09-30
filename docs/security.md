# CBA IMS — Security Reference

This document describes the security controls implemented in the CBA Asset & Inventory Management System.

---

## 1. Authentication

### User Model and Roles

The system uses a **custom User model** (`apps.accounts.models.User`) with four roles:

| Role | Constant | Description |
|------|----------|-------------|
| Administrator | `ADMIN` | Full system access |
| Dean | `DEAN` | College-wide read access and reports |
| Department Chair | `DEPT_CHAIR` | Full operations scoped to own department |
| Faculty/Staff | `FACULTY` | Personal accountability and borrowing only |

### Password Hashing

Django's default PBKDF2 with SHA-256 hashing is used. All passwords are stored as salted hashes. Plaintext passwords are never stored.

### Password Validation

`AUTH_PASSWORD_VALIDATORS` enforces:
- **UserAttributeSimilarityValidator** — rejects passwords similar to username, name, or email
- **MinimumLengthValidator** — minimum 8 characters (Django default)
- **CommonPasswordValidator** — rejects passwords from a list of 20,000+ common passwords
- **NumericPasswordValidator** — rejects all-numeric passwords

### Brute-Force Protection (django-axes)

- **Library:** `django-axes`
- **Failure threshold:** 5 failed login attempts
- **Lockout duration:** 1 hour
- **Lockout scope:** Locked by IP address and username combination
- **Effect:** After 5 failures, even valid credentials are rejected until the lockout expires
- **Admin action:** Admins can unlock accounts in the Django admin or via `python manage.py axes_reset`
- **Log:** All failures and lockouts are logged via the standard Django logging system

### Session Security

| Setting | Value | Effect |
|---------|-------|--------|
| `SESSION_COOKIE_HTTPONLY` | `True` | JavaScript cannot read the session cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` | Mitigates cross-site request forgery via cookie |
| `SESSION_COOKIE_SECURE` | `True` (when `DEBUG=False`) | Session cookie only sent over HTTPS |

---

## 2. Role-Based Access Control (RBAC)

### Access Matrix

| Feature | Admin | Dean | Dept Chair | Faculty |
|---------|-------|------|------------|---------|
| User management | ✅ Full | ❌ | ❌ | ❌ |
| Department/Location management | ✅ Full | ❌ | ❌ | ❌ |
| Asset CRUD | ✅ Full | 🔍 Read-only | ✅ Own dept | ❌ |
| Assignments | ✅ Full | 🔍 Read-only | ✅ Own dept | 🔒 Own only |
| Transfers | ✅ Full | 🔍 Read-only | 🔍 Own dept | ❌ |
| Supplies | ✅ Full | 🔍 Read-only | 🔍 Own dept | ❌ |
| Borrowing | ✅ Full | 🔍 Read-only | 🔍 Own dept | ✅ Request own |
| Maintenance | ✅ Full | 🔍 Read-only | 🔍 Own dept | ✅ Report own |
| Disposals | ✅ Full | 🔍 Read-only | 🔍 Own dept | ❌ |
| Reports (all) | ✅ Full | ✅ All depts | ✅ Own dept | ❌ |
| Audit log | ✅ Full | ✅ Full | ❌ | ❌ |
| QR scan | ✅ All | ✅ All | ✅ Own dept | 🔒 Own assets |

### Implementation

Every view uses **`LoginRequiredMixin`** (redirects unauthenticated users to login) combined with **`UserPassesTestMixin`** (returns `403 Forbidden` for authenticated users without the required role).

**Department Chair scope neutralization:** Report QuerySets are filtered at the **service layer** using `get_user_department_scope(user)`. URL parameter manipulation (e.g. `?department=<OTHER_ID>`) is ignored — the service layer applies the user's own department regardless of query parameters.

---

## 3. CSRF Protection

- Django's `CsrfViewMiddleware` is active on all views
- CSRF tokens are required on all POST, PUT, PATCH, DELETE requests
- Forms that omit the CSRF token return **HTTP 403 Forbidden**
- `CSRF_COOKIE_SECURE=True` in production — CSRF cookie only sent over HTTPS
- `CSRF_COOKIE_HTTPONLY=True` — JavaScript cannot read the CSRF cookie
- `DJANGO_CSRF_TRUSTED_ORIGINS` must be set to production HTTPS domain(s) to work correctly behind Nginx reverse proxy

---

## 4. HTTPS and Transport Security

| Setting | Recommended Value | Notes |
|---------|-------------------|-------|
| `SECURE_SSL_REDIRECT` | `True` | Redirects HTTP to HTTPS at Django level (Nginx also redirects) |
| `SESSION_COOKIE_SECURE` | `True` | Automatic when `DEBUG=False` |
| `CSRF_COOKIE_SECURE` | `True` | Automatic when `DEBUG=False` |
| `SECURE_HSTS_SECONDS` | Start at `0`, increase gradually | Do NOT enable HSTS preload until HTTPS has been stable for months. Incorrect HSTS can lock users out of the site |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` (after HSTS confirmed) | Applies HSTS to all subdomains |

**HSTS rollout strategy:**
1. Start with `SECURE_HSTS_SECONDS=0` (disabled)
2. After weeks of stable HTTPS: set to `3600` (1 hour)
3. After months of stable HTTPS: set to `86400` (1 day), then `31536000` (1 year)
4. Only submit to HSTS preload list after 1 year is stable

---

## 5. Upload Security

Asset image uploads are validated at multiple layers:

| Check | Implementation | Rejects |
|-------|---------------|---------|
| File size | `MAX_UPLOAD_SIZE = 5 * 1024 * 1024` (5 MB) | Files larger than 5 MB |
| Extension | Whitelist: `.jpg`, `.jpeg`, `.png`, `.webp` | Any file with an unlisted extension |
| Content type | `PIL.Image.open().verify()` | Files that are not valid images despite having correct extension |

**Extension spoofing prevention:** A file renamed from `.exe` to `.jpg` will fail PIL's `verify()` call because the file header does not match image format — it is rejected before the file is saved.

**Upload storage:** Files are stored under `MEDIA_ROOT/assets/YYYY/MM/` — never inside `STATIC_ROOT`, never directly under web root without Nginx path control.

**File serving:** Nginx serves media files with `X-Content-Type-Options: nosniff` to prevent MIME sniffing.

---

## 6. QR Code Security

QR codes encode the URL `/q/assets/<asset_code>/` — no sensitive data is embedded in the QR image.

| Role | Scanning Unassigned Asset | Scanning Own Assigned Asset | Scanning Other's Asset |
|------|--------------------------|----------------------------|------------------------|
| Admin / Dean | ✅ Full detail | ✅ Full detail | ✅ Full detail |
| Dept Chair | ✅ Own dept only | ✅ | ❌ 403 |
| Faculty | ❌ 403 | ✅ Assignment detail | ❌ 403 |
| Anonymous | Redirect to login | Redirect to login | Redirect to login |

- Invalid asset codes return **404 Not Found** (no information disclosure)
- Disposed assets: return 404 for Faculty; show historical record banner for Admin/Dean
- No open redirect: the scanner (`/inventory/scan/`) validates decoded URLs and only accepts internal `/q/assets/<code>/` paths or raw asset codes starting with `CBA-`

---

## 7. Export Security

**CSV formula injection prevention:**
- Exported CSV files use **UTF-8 with BOM** (`\xef\xbb\xbf`) for Excel compatibility
- `sanitize_for_spreadsheet()` inspects all string cell values
- Cells beginning with `=`, `+`, `-`, `@`, `\t`, `\r` are prefixed with `'` (apostrophe) to prevent spreadsheet formula execution

**XLSX security:**
- Same `sanitize_for_spreadsheet()` applied to all cell values
- openpyxl writes `.xlsx` directly — no external process involved

**Access control:** Only Admin, Dean, and Dept Chair roles can generate exports. Faculty cannot access any report or export endpoint (`/reports/*` returns **403 Forbidden**).

---

## 8. PWA and Service Worker

The application includes a Progressive Web App service worker (`static/sw.js`).

**What is cached:**
- Static assets only: CSS, JavaScript, PWA icons

**What is NEVER cached:**
- HTML navigation requests
- Authenticated pages (dashboard, reports, audit log, accountability)
- Any response requiring authentication

**Offline behavior:** If the network is unavailable, the service worker serves a static `offline.html` page. This page contains no user data and no cached authenticated content.

**True offline sync is NOT supported:** The application requires a network connection to read or write data. No transactions are queued for sync.

---

## 9. Seed Command Safeguards

All demo seed commands (`seed_phase1` through `seed_phase9`) include a production guard:

```python
# Guard in every seed command
if not settings.DEBUG and not options.get('force_demo_data'):
    raise CommandError(
        "Seed commands are disabled in production (DEBUG=False). "
        "Pass --force-demo-data to override. This creates accounts with "
        "known passwords and is NOT safe for production use."
    )
```

**Demo credentials created by seed commands (DEVELOPMENT ONLY):**

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | Admin |
| `dean_cruz` | `dean123` | Dean |
| `chair_santos` | `chair123` | Dept Chair |
| `prof_maria` | `faculty123` | Faculty |

> **These credentials must never exist on a production server.** Create production accounts with `python manage.py createsuperuser` and strong unique passwords.

---

## 10. Audit Logging

The `AuditLog` model (`apps.audit.models.AuditLog`) is **immutable**:

```python
def save(self, *args, **kwargs):
    if self.pk:
        raise PermissionError("AuditLog records cannot be modified.")
    super().save(*args, **kwargs)

def delete(self, *args, **kwargs):
    raise PermissionError("AuditLog records cannot be deleted.")
```

**Logged events include:** asset create/update/delete, assign, return, transfer (all lifecycle stages), borrowing (all lifecycle stages), maintenance (all lifecycle stages), disposal (all lifecycle stages), supply transactions, user login failures.

**Each log entry records:**
- `user` — who performed the action
- `action` — action type constant (e.g. `ASSET_ASSIGNED`)
- `model_name` and `object_id` — what was affected
- `changes` — JSON before/after diff
- `ip_address` — requester's IP (from `X-Forwarded-For` if behind proxy)
- `timestamp` — UTC datetime

**Audit log access:**
- Admin: full log
- Dean: full log
- Dept Chair: scoped to own department
- Faculty: no access

---

## 11. Logging Policy

**What is logged (Django `WARNING`+ to stdout → systemd journal):**
- Authentication failures and lockouts
- Permission denied events (403)
- Application errors and exceptions
- `django.security` events at ERROR level

**What is NEVER logged:**
- Passwords (in any form)
- `SECRET_KEY`
- Session cookies or tokens
- Authorization header values
- Database connection credentials

---

## 12. Security Headers

| Header | Value | Protection |
|--------|-------|------------|
| `X-Frame-Options` | `DENY` | Prevents clickjacking via iframe embedding |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME type sniffing |
| `Referrer-Policy` | `same-origin` | Limits referrer information to same-origin requests |
| `X-XSS-Protection` | `1; mode=block` | Legacy XSS filter for older browsers |
| `Content-Security-Policy` | ⚠️ Not yet configured | **Recommended future hardening** — CSP would restrict script/style sources |

**Recommended future hardening:**
- Add a `Content-Security-Policy` header to restrict inline scripts and external resource loading
- Add `Permissions-Policy` to disable unused browser features (camera, microphone — except where QR scanning requires them)
- Review `Strict-Transport-Security` parameters before enabling preload
