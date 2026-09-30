# CBA IMS — User Acceptance Testing (UAT) Checklist

Complete this checklist manually before go-live. All items must pass. Document the tester name and date for each section.

**Tester:** ___________________________  
**Date:** ___________________________  
**Environment URL:** ___________________________  
**Application version / commit:** ___________________________

---

## Environment Setup

- [ ] Test environment has production-like configuration (`DEBUG=False`, PostgreSQL, Nginx + Gunicorn)
- [ ] Database has representative data (not demo seed data if possible, or seed data with passwords changed)
- [ ] All 274 automated tests passing: `python manage.py test` (0 failures, 0 errors)
- [ ] `python manage.py check --deploy` reports 0 issues


- [ ] django-axes lockout configured and active (5 failures → 1 hour lockout)
- [ ] Health endpoint reachable: `GET /health/` returns HTTP `200 OK`
- [ ] SSL certificate valid and HTTPS enforced

---

## UAT-01: Admin Role

**Login:** Admin account (created via `createsuperuser`)

- [ ] Can log in with admin credentials
- [ ] Dashboard displays system-wide statistics (total assets, active assignments, pending requests, recent alerts)
- [ ] Dashboard Chart.js charts render (condition doughnut, category bar, department bar)
- [ ] Can create a new user (all four roles: Admin, Dean, Dept Chair, Faculty)
- [ ] Can edit an existing user's role and profile
- [ ] Can deactivate a user account
- [ ] Can create a new department and location
- [ ] Can create an asset with all required fields filled
- [ ] Asset image upload accepted for valid JPEG file under 5 MB
- [ ] Asset image upload rejected for file > 5 MB — clear error message displayed
- [ ] Asset image upload rejected for non-image file (e.g. PDF or EXE renamed to `.jpg`) — clear error
- [ ] Asset code is auto-generated and immutable after creation
- [ ] Can generate a QR label for an asset (single label view)
- [ ] Can view and print bulk QR label sheet
- [ ] Can assign an asset to an employee
- [ ] Asset status changes to `ASSIGNED` after assignment
- [ ] Can process an asset return; return condition recorded in history
- [ ] Asset returns to `AVAILABLE` after return (or `DAMAGED` if returned unserviceable)
- [ ] Can request, approve, and complete an asset transfer
- [ ] Asset department and location updated after transfer completed
- [ ] Can issue supplies (Stock In, Stock Out, Adjustment)
- [ ] Stock balance updates correctly after each transaction
- [ ] Can process a maintenance workflow: report → assess → start repair → complete
- [ ] Asset status changes to `Under Maintenance` when repair starts
- [ ] Asset restored to correct status after repair completion
- [ ] Can approve a borrowing request and release the asset
- [ ] Can process borrowing return
- [ ] Can initiate and complete an asset disposal
- [ ] Asset status becomes `DISPOSED` after completion
- [ ] Can view the full audit log with all action types present
- [ ] Can run all 14 reports without errors
- [ ] Can export a report as CSV — file downloads and opens in Excel without encoding errors
- [ ] Can export a report as XLSX — file downloads with formatted navy headers
- [ ] Can print a report — print view shows university header and clean layout
- [ ] Can download the Executive Summary multi-sheet XLSX
- [ ] Logout clears session — browser back button after logout does not display dashboard content

---

## UAT-02: Dean Role

**Login:** Dean account

- [ ] Can log in
- [ ] Dashboard shows system-wide statistics (same scope as Admin)
- [ ] Can view assets from all departments
- [ ] Can view all active assignments across all departments
- [ ] Can view transfer history across all departments
- [ ] Can view all reports (all 14, college-wide scope)
- [ ] Can export reports as CSV and XLSX
- [ ] **Cannot** create or edit users — user management links absent or return 403
- [ ] **Cannot** create or edit departments or locations
- [ ] **Cannot** create assets — asset creation button absent or returns 403
- [ ] **Cannot** assign, return, approve, or process any operational workflow (all mutation POSTs return 403)
- [ ] **Cannot** access System Audit Trail (`/reports/audit-log/` returns 403)
- [ ] Can view the audit log via `/audit/` if directly accessible? _(verify per application config)_

---

## UAT-03: Dept Chair Role

**Login:** Dept Chair account assigned to a specific department (e.g. Accountancy)

- [ ] Can log in
- [ ] Dashboard shows only own department's assets and statistics
- [ ] Can view assets belonging to own department only
- [ ] Attempting to access an asset from another department returns 403
- [ ] Can create and manage assets within own department
- [ ] Can process assignments within own department
- [ ] Can view transfers involving own department (as origin or destination)
- [ ] **Cannot** view transfers exclusively between other departments
- [ ] Reports are scoped to own department — URL manipulation (`?department=<OTHER_ID>`) is neutralized
- [ ] Asset report shows only own department's assets even after URL manipulation attempt
- [ ] Can export department-scoped reports as CSV and XLSX
- [ ] **Cannot** view the audit log — access returns 403
- [ ] **Cannot** manage users or departments
- [ ] Can report a maintenance issue for a departmental asset
- [ ] **Cannot** approve, reject, or complete transfers (mutation returns 403)

---

## UAT-04: Faculty Role

**Login:** Faculty account with active asset assignments

- [ ] Can log in
- [ ] Dashboard shows personal statistics only (no system-wide data)
- [ ] "My Accountability" page (`/assignments/my-accountability/`) shows own assigned assets
- [ ] Can view asset detail page for an asset assigned to them
- [ ] **Cannot** view asset detail page for an asset assigned to someone else — returns 403
- [ ] "My Borrowings" page shows own active loans, approved reservations, and history
- [ ] Can submit a borrowing request for an available asset
- [ ] Can cancel own pending borrowing request
- [ ] Can file a maintenance defect report for own assigned asset
- [ ] **Cannot** access the general asset inventory list (`/inventory/assets/` returns 403 or redirects)
- [ ] **Cannot** access any reports (`/reports/*` returns 403)
- [ ] **Cannot** access the audit log
- [ ] **Cannot** access other employees' accountability pages (returns 403)
- [ ] **Cannot** access the Django admin panel (`/admin/` redirects to login; logging in with faculty credentials does not grant admin access)
- [ ] Navigation sidebar does not show links to restricted areas (Inventory, Reports, Assignments, Admin)

---

## UAT-05: Security Tests

Perform with a browser in private/incognito mode and with browser developer tools open to observe response codes.

- [ ] **Brute force — lockout trigger:** Attempt 5 failed logins with an invalid password for a valid username. Verify the lockout message appears after the 5th failure
- [ ] **Brute force — lockout enforced:** After lockout, attempt login with the correct password. Verify it is also rejected (lockout active)
- [ ] **Brute force — lockout duration:** After 1 hour, verify that valid credentials are accepted again (or admin resets the lockout)
- [ ] **Anonymous QR scan:** Visit `/q/assets/<valid_asset_code>/` while not logged in. Verify redirect to login page (no asset data exposed)
- [ ] **CSRF protection:** Attempt to submit a form (e.g. assign form) without the CSRF token (using curl or browser dev tools to remove the token). Verify HTTP 403 response
- [ ] **Faculty QR — own assigned asset:** Log in as faculty; scan a QR code for an asset assigned to them. Verify assignment detail is shown
- [ ] **Faculty QR — unassigned asset:** Log in as faculty; visit `/q/assets/<unassigned_asset_code>/`. Verify 403 response
- [ ] **Faculty QR — another faculty's asset:** Log in as faculty A; visit `/q/assets/<asset_assigned_to_faculty_B>/`. Verify 403 response
- [ ] **Custom 404 page:** Visit a non-existent URL (e.g. `/does-not-exist-xyz/`). Verify a branded 404 page appears with no Django traceback
- [ ] **Custom 403 page:** Access a restricted URL as an unprivileged user. Verify a branded 403 page with no traceback
- [ ] **Custom 500 page:** _(Test in staging only — do not simulate errors in production.)_ Verify a generic error page without traceback is shown
- [ ] **Back button after logout:** Log in, visit the dashboard, log out, then press the browser back button. Verify the dashboard does not display cached authenticated content

---

## UAT-06: Mobile and PWA Tests

Test on a real device or using browser developer tools mobile emulation. For camera tests, use a real device.

- [ ] Application loads correctly on iOS Safari (iPhone)
- [ ] Application loads correctly on Android Chrome
- [ ] Navigation sidebar collapses to offcanvas on mobile screen width
- [ ] Touch targets (buttons, links) are comfortably tappable (≥ 44px)
- [ ] Asset list cards display correctly on mobile (no horizontal overflow)
- [ ] Camera QR scanner launches at `/inventory/scan/` on a mobile device — camera permission prompt appears
- [ ] Camera can scan a printed QR label and resolves to the correct asset
- [ ] Service worker registers successfully (visible in browser DevTools → Application → Service Workers)
- [ ] **Offline — authenticated page:** Disconnect from network; attempt to load `/dashboard/`. Verify the page does NOT load from cache as an authenticated page (browser shows network error or service worker serves `offline.html`)
- [ ] **Offline — static assets:** Disconnect from network; if a cached page is already loaded, verify CSS and icons still appear (static cache working)
- [ ] After logout: browser back button does not show a cached authenticated dashboard page

---

## UAT-07: Performance and Edge Cases

- [ ] Asset list with 100+ assets loads in under 3 seconds (no N+1 query slowness; verify with browser Network tab)
- [ ] Concurrent assignment test: _(Requires two browser sessions simultaneously)_ Two users simultaneously attempt to assign the same asset. Verify only one assignment succeeds; the second receives a validation error ("asset is not available")
- [ ] **Double-click submit:** Click a form submit button twice rapidly. Verify the form is not submitted twice (no duplicate records)
- [ ] **Large image upload rejected:** Attempt to upload an image file > 5 MB. Verify clear validation error message; no partial upload saved
- [ ] **Wrong file extension rejected:** Upload a non-image file (e.g. a `.txt` or `.exe` file renamed to `.jpg`). Verify the upload is rejected with a clear error
- [ ] **Supplied stock over-issuance blocked:** Attempt to issue more supply units than currently in stock. Verify `Insufficient stock` validation error
- [ ] **Pagination:** Verify asset list, assignment list, and report results paginate correctly with `?page=2`, `?page=3`, etc. Query filters are preserved across pages
- [ ] **Search and filter persistence:** Apply a search filter on the asset list; navigate to page 2; verify filter still applies
- [ ] **Report date range filter:** Apply a date range filter in a report; verify results are correctly scoped to the date range
- [ ] **Empty state:** Navigate to borrowing history with no records. Verify an appropriate "No records found" message displays instead of a broken layout
