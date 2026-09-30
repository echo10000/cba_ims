# CBA IMS — Development History

This document records the development phases of the CBA Asset and Inventory Management System.

---

## Phase 1 — Foundation

Django/PostgreSQL project setup. Custom User model with four RBAC roles (Admin, Dean, Dept Chair, Faculty). Organizational structure: Departments, Locations, Employees (linked to User accounts). Mobile-first responsive layout with Bootstrap 5 (desktop sidebar, mobile offcanvas drawer, touch-friendly tap targets). Progressive Web App (PWA) support: `manifest.json`, service worker (`sw.js`), 8 icon sizes, offline fallback (`offline.html`). Immutable `AuditLog` model (overridden `save()` and `delete()` raise `PermissionError`).

## Phase 2 — Durable Asset Inventory

`Asset` model with auto-generated collision-safe asset codes (`CBA-{CATEGORY_CODE}-{NUMBER:05d}`), optional institutional property numbers (database-level uniqueness), acquisition details, condition and status choices (Available → Assigned → Borrowed → Under Maintenance → Damaged → Lost → Transferred → Disposed). Asset image upload with validation (JPEG/PNG/WebP, max 5 MB, PIL verify). `AssetCategory`, `Brand` models. Asset CRUD views with grouped form layout. Search across 6 fields; multi-filter panel (Category, Brand, Department, Location, Condition, Status). Asset codes are strictly immutable after creation.

## Phase 3 — Faculty/Staff Assignments

`AssetAssignment` model with full relational history (asset, employee, dates, condition snapshots, status: ACTIVE/RETURNED). Single-active-assignment database constraint (`UniqueConstraint` with `condition=Q(status='ACTIVE')`). `on_delete=PROTECT` prevents cascading deletes on assets with history. Atomic service layer (`assign_asset`, `return_asset`) using `select_for_update()`. My Accountability view for faculty (restricted to own assigned assets). Printable Property Acknowledgement Receipt (PAR).

## Phase 4 — Asset Transfers

`AssetTransfer` model with origin snapshots frozen at creation time (`from_department`, `from_location`). Single-active-transfer constraint (`PENDING` or `APPROVED`). Accountability decoupling: physical relocation does not alter `AssetAssignment` records. Atomic service layer: `request_transfer`, `approve_transfer`, `reject_transfer`, `complete_transfer` (stale-origin conflict detection), `cancel_transfer`. Conservative RBAC: only Admin can execute transfer workflows; Dean and Chair are read-only.

## Phase 5 — Consumable Supplies

`SupplyCategory`, `Supply`, `SupplyTransaction` models. Ledger-derived stock balance: authoritative on-hand quantity computed from transaction history (`STOCK_IN + ADJUSTMENT_IN - STOCK_OUT - ADJUSTMENT_OUT`) — no stored stock integer column. Stock status derivation: `OUT_OF_STOCK`, `LOW_STOCK`, `IN_STOCK`. `SupplyTransaction` immutability (overridden `save()`/`delete()`). Concurrency and negative-stock prevention via `select_for_update()`. Low-stock monitoring dashboard and alert banner.

## Phase 6 — QR Asset Tracking

QR code generation per asset (Base64 data URIs, in-memory, no disk I/O). Canonical URL payload: `/q/assets/<asset_code>/`. `AssetVerification` model with outcome classification (VERIFIED, LOCATION_MISMATCH, CONDITION_MISMATCH, LOCATION_AND_CONDITION_MISMATCH). Non-mutation decoupling invariant: verification audits never silently alter canonical asset location or condition. Mobile HTML5 camera scanner with anti-open-redirect validation. Single and bulk printable QR label views. Physical inventory verification dashboard with KPI cards.

## Phase 7 — Temporary Borrowing

`AssetBorrowing` model with full lifecycle (PENDING → APPROVED → RELEASED → RETURNED; REJECTED, CANCELLED, OVERDUE). Single-active-release database constraint. Datetime interval overlap conflict detection (`start_a < end_b and end_a > start_b`). Atomic service layer: `request_borrowing`, `approve_borrowing`, `reject_borrowing`, `cancel_borrowing`, `release_asset`, `return_borrowed_asset`, `refresh_overdue_status`. My Borrowings view for faculty. Integration with QR gateway (on-loan banner and return shortcut).

## Phase 8 — Maintenance

`AssetMaintenance` model with sequential case identifier (`MNT-{YEAR}-{SEQ:05d}`). Lifecycle: REPORTED → ASSESSED → IN_REPAIR → COMPLETED / FOR_REPLACEMENT / CANCELLED. Single-active-report invariant. Atomic service layer: `report_issue` (no premature status change), `assess_issue`, `start_repair` (blocks if asset BORROWED), `complete_repair` (restores to AVAILABLE, ASSIGNED, or DAMAGED based on condition and active assignments), `mark_for_replacement` (sets asset to DAMAGED/UNSERVICEABLE), `cancel_maintenance`. Integration with borrowing, disposal, and QR gateway. `FOR_REPLACEMENT` cases display a "Begin Disposal Process" button.

## Phase 9 — Disposals

`AssetDisposal` model with sequential identifier (`DSP-{YEAR}-{SEQ:05d}`). Lifecycle: PENDING → APPROVED → COMPLETED; REJECTED, CANCELLED. Non-destructive retirement: never hard-deletes assets; transitions `Asset.status` to `DISPOSED`. Atomic `complete_disposal` with `select_for_update()` re-validates that no active assignments, loans, or transfers remain. Cross-module DISPOSED status blocking in all service layers (assign, transfer, borrow, release, report, start_repair). QR gateway shows historical-record banner and suppresses all operational actions for disposed assets.

## Phase 10 — Reports

Reporting layer with no new database models (zero migrations). 14 specialized report types across assets, assignments, transfers, borrowings, maintenance, supplies, and disposals. CSV export (UTF-8 BOM) and styled XLSX export (openpyxl, navy headers, auto column widths, freeze panes, AutoFilter). Multi-sheet Executive Summary workbook (6 sheets). Formula injection sanitization (`sanitize_for_spreadsheet()`). Universal print view with university/college identification header. Interactive Chart.js dashboard charts (condition doughnut, category bar, department bar). Department Chair QuerySet scoping at service layer; URL manipulation neutralized.

## Phase 11 — Production Hardening

Settings hardened for production deployment: all secrets loaded from environment variables, no insecure defaults. `django-axes` brute-force protection (5 failures → 1 hour lockout). WhiteNoise static file serving with compression and cache-busting. Enhanced image upload validation (size limit, extension whitelist, PIL `verify()`). Seed command safeguards (`DEBUG=False` guard + `--force-demo-data` flag). Custom error pages (400, 403, 404, 500) — no traceback exposure. Health endpoint (`/health/` → 200 OK). `Cache-Control: no-store` headers on authenticated pages. Service worker security hardening (HTML navigation requests served network-only; no authenticated page caching). Database performance indexes added. Comprehensive deployment, security, backup, and UAT documentation created (`docs/`).
