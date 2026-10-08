# Frontend Interactivity Foundation, Phase 2 Alpine.js & Phase 3A/3B/3C HTMX — AI Handoff

## 1. Executive Summary

The frontend interactivity stack combines **HTMX** (v1.9.12) and **Alpine.js** (v3.14.8) vendored locally as infrastructure:
- **Phase 1**: Infrastructure vendored, global CSRF configured, HX-Request cache bypass in Service Worker, no hx-boost on navigation.
- **Phase 2**: Low-risk Alpine.js UI state implemented across collapsible filter panels, bulk QR checkbox selection, and inline safe action confirmations.
- **Phase 3A**: HTMX read-only search, filtering, and scoped pagination for the **Inventory Asset List** (`AssetListView`).
- **Phase 3B**: HTMX read-only search, filtering, and scoped pagination for the **Consumable Supply List** (`SupplyListView`).
- **Phase 3C**: HTMX read-only search, filtering, and scoped pagination for **Current Assignments** (`CurrentAssignmentListView`).
- **Phase 4 (CURRENT COMPLETED)**: Visual Migration of Global Shell & Shared Design Foundation to **DESIGN.md v2.0 (Modern Workspace Direction)**.

All backend business logic, Django permissions, queryset scoping (Admin full access, Dean read-only catalog/transactions, Chair read-only catalog + department-scoped transactions, Faculty redirect to `assignments:my_accountability`), models, forms, CSRF protections, print layouts, and ledger/disposal workflows remain strictly preserved.

---

## 2. Vendored Libraries & Assets

All dependencies are hosted locally under `static/vendor/` to satisfy offline/PWA requirements and avoid third-party CDN latency or downtime:

- **HTMX v1.9.12**:
  - File: `static/vendor/htmx/htmx.min.js` (48,101 bytes)
  - Role: Declarative AJAX, targeted DOM swaps, live search/filtering and scoped pagination for list views.
- **Alpine.js v3.14.8**:
  - File: `static/vendor/alpine/alpine.min.js` (44,758 bytes)
  - Role: Lightweight client-side reactive state (collapsible filter panels, bulk selection, inline confirmations).

---

## 3. Phase 2 Implementations

### Scope 1: Collapsible Filter Panels
Replaced obsolete Bootstrap collapse / custom JavaScript handlers with accessible Alpine.js components:
1. **Asset List (`templates/inventory/asset_list.html`)**:
   - `x-data="{ open: <true if any filter param in GET else false> }"`
   - Accessible toggle button: `@click="open = !open"`, `:aria-expanded="open"`, dynamic funnel icon (`bi-funnel` / `bi-funnel-fill`).
   - `#filterPanel` with `x-show="open" x-cloak` (removed Bootstrap `collapse` class to eliminate layout jump).
   - Preserves standard Django GET submission, query parameters, and active filter counter badge.
2. **Supply List (`templates/supplies/supply_list.html`)**:
   - Mobile filter collapse: `x-data="{ open: <has_filters> }"`.
   - Toggle button for mobile (`d-md-none filter-collapse-btn`) with `:aria-expanded="open"`.
   - Reactive `#supplyFilterControls` container using `:class="{ 'd-none': !open, 'd-flex': open }"` while maintaining desktop visibility (`d-md-flex`).
3. **Current Assignments List (`templates/assignments/current_assignment_list.html`)**:
   - Mobile filter collapse with `x-data="{ open: <has_filters> }"`.
   - `#assignmentFilterControls` collapses on mobile until toggled, always visible on desktop (`d-md-flex`).

### Scope 2: Bulk QR Selection State
Refactored `templates/inventory/bulk_qr_labels.html` from vanilla DOM listeners to a clean Alpine component:
- Root state: `selected: []`, `allCodes: [...]`, `allSelected` getter, `toggleAll()`, `clearSelection()`, `submitPrint()`.
- Table checkboxes: `name="selected" value="{{ item.asset.asset_code }}" x-model="selected"`.
- Select All checkbox: `:checked="allSelected" @change="toggleAll()"`.
- Live counter: `x-text="selected.length + ' selected'"`.
- "Clear Selection" button: appears reactively via `x-show="selected.length > 0" x-cloak`.
- "Print Selected Labels" header button: bound to `@click="submitPrint()" :disabled="selected.length === 0"`, shows live count badge.
- Form submission, print stylesheet dimensions, QR data URIs, and backend GET parameters strictly preserved.
- Removed obsolete vanilla event listener script from `{% block extra_js %}`.

### Scope 3: Inline Confirmation UI (Safe Targets Only)
Replaced disruptive browser `window.confirm()` popups with inline, accessible Alpine confirmation widgets on safe, low-risk actions:
- Targets converted:
  1. `templates/organizations/department_list.html`: `department_toggle` (desktop table + mobile card)
  2. `templates/organizations/location_list.html`: `location_toggle` (desktop table + mobile card)
  3. `templates/organizations/employee_list.html`: `employee_toggle` (desktop table + mobile card)
  4. `templates/supplies/supply_detail.html`: `supply_toggle`
- Confirmation widget pattern:
  - Form wrapped with `x-data="{ confirming: false }" @keydown.escape.window="confirming = false"`.
  - Initial toggle button: `x-show="!confirming" @click="confirming = true"`.
  - In-place popover: `x-show="confirming" x-cloak @click.outside="confirming = false"`.
  - Direct actions: "Yes" triggers native form POST submission, cancel button / Escape / click-outside closes without action.
- Excluded high-risk workflows (strictly untouched):
  - Disposal completion, stock in/out, physical inventory verification, borrowing release/return, maintenance state transitions, transfer approvals.

---

## 4. Phase 3A Implementation: HTMX Inventory Asset List

1. **Partial Extraction (`templates/inventory/partials/_asset_results.html`)**:
   - Contains result counter (`Showing X–Y of Z assets`), desktop table view, mobile card view, scoped pagination controls, and institutional empty state.
   - When 0 assets match, displays a clean institutional empty state with a "Clear Filters" button if filters are active; no empty table or dead headers are rendered.
2. **Full Page Wrapper (`templates/inventory/asset_list.html`)**:
   - Live Search: `hx-trigger="keyup changed delay:350ms, search"`, `hx-target="#asset-results-container"`, `hx-push-url="true"`, `hx-indicator="#asset-loading-indicator"`, `hx-include="#assetFilterForm"`.
   - Dropdown Filters (Category, Brand, Department, Location, Condition, Status): `hx-trigger="change"`, `hx-target="#asset-results-container"`.
   - Restrained Loading Indicator: `#asset-loading-indicator` inline 0.85rem spinner.
3. **Backend View Enhancement (`AssetListView` in `apps/inventory/views.py`)**:
   - Implements `get_template_names()` returning `_asset_results.html` for HTMX requests while bypassing history restore and boosted navigation.

---

## 5. Phase 3B Implementation: HTMX Consumable Supply List

1. **Partial Extraction (`templates/supplies/partials/_supply_results.html`)**:
   - Dynamic count badge, desktop table view, mobile card list, scoped pagination, and institutional empty state.
2. **Full Page Wrapper (`templates/supplies/supply_list.html`)**:
   - Live Search: `#supplySearchInput` with `hx-trigger="keyup changed delay:350ms, search"`, `hx-include="#supplyFilterForm"`, `hx-target="#supply-results-container"`, `hx-push-url="true"`.
   - Dropdown Filters (Category, Brand, Stock Status, State): `hx-trigger="change"`, `hx-include="#supplyFilterForm"`, `hx-target="#supply-results-container"`.
   - Restrained Loading Indicator: `#supply-loading-indicator` inline spinner.
3. **Backend View Enhancement (`SupplyListView` in `apps/supplies/views.py`)**:
   - Implements `get_template_names()` returning `_supply_results.html` for HTMX requests.

---

## 6. Phase 3C Implementation: HTMX Current Assignments

1. **Partial Extraction (`templates/assignments/partials/_assignment_results.html`)**:
   - Contains result counter, desktop table view, mobile card list, scoped pagination, and institutional empty state.
   - Displays accountability tags, property numbers, employee assignment metadata, and action buttons.
2. **Full Page Wrapper (`templates/assignments/current_assignment_list.html`)**:
   - Live Search: `#assignmentSearchInput` with debounced trigger.
   - Dropdown Filters: Department and Employee with `change` trigger.
   - Loading indicator: `#assignment-loading-indicator`.
3. **Backend View Enhancement (`CurrentAssignmentListView` in `apps/assignments/views.py`)**:
   - Implements `get_template_names()` returning `_assignment_results.html` for HTMX requests.
   - Preserved full RBAC scoping: Admin & Dean unrestricted, Department Chair scoped to department, Faculty redirected to `my_accountability`.

---

## 7. Approved Modern Workspace Visual Direction (DESIGN.md v2.0)

On October 7, 2026, the project design contract was officially upgraded from **DESIGN.md v1.0** to **DESIGN.md v2.0**, establishing the **Modern Workspace Direction** as the canonical visual contract for all future UI work.

### Core Architectural Decisions & Adjustments
1. **Retirement of Dark Heavy Sidebar:** The legacy dark slate shell (`#0f172a` / `#0b1120`) and ice-blue indicator stripe (`#38bdf8`) are officially superseded and no longer authoritative. The new navigation standard is a light neutral sidebar canvas (`#f8fafc`) with a hairline 1px divider (`#e2e8f0`) and soft blue active pill tint (`#eff6ff` / `#1d4ed8`).
2. **Modern Institutional Blue (`#1d4ed8`):** Replaces deep navy `#1e3a8a` as the primary interactive accent, providing a lighter, contemporary feel with high contrast (7.3:1 vs white, passing WCAG AAA Large / AA Body).
3. **CRM / Database Table Grid:** Replaces traditional Bootstrap zebra striping and 2px table header borders with clean white rows (`#ffffff`), hairline dividers (`#f1f5f9`), soft hover rows (`#f8fafc`), and soft blue active row selection (`#eff6ff`).
4. **Scale & Radii Harmonization:** Standardized to 8px panel/card radius, 6px input/button radius, and 4px micro tags/badges.
5. **Dashboard Operational Metrics:** Dashboard metric display is decoupled from arbitrary 4-metric lock-ins. Preserves all operational indicators via either an integrated horizontal summary strip or compact white metric cells/cards.
6. **Optional Global Search:** A `Ctrl+K` / global-search input is not mandatory in the topbar unless a genuine global search backend service is implemented.
7. **Restrained HTMX Loading State Standard:** Inline spinner indicators (`.htmx-indicator`) inside search input groups remain the default loading pattern. Shimmer/skeleton loading is not a default pattern and is restricted to proven UX needs.
8. **Comprehensive RBAC Preservation:** All authorization mechanisms must be preserved across future UI styling passes, including `request.user.role`, `request.user.is_admin`, custom permission mixins (`AssignmentViewAccessMixin`, `RoleRequiredMixin`), role-specific template conditionals, and department queryset scoping.
9. **Scanner & Print View Safeguards:** Barcode/QR scanner viewports (`scanner.html`) and `@media print` high-contrast black ink rules remain strictly protected.

---

## 8. Phase 4: Global Shell & Shared Design Foundation Migration (DESIGN.md v2.0)

Completed the foundational migration to align the shared global shell and design tokens with **DESIGN.md v2.0 (Modern Workspace Direction)**. Individual application modules were intentionally not redesigned in this phase.

### Target Files Updated
1. `templates/base.html`:
   - Updated `:root` CSS variables to v2.0 tokens (`--cba-primary: #1d4ed8`, `--cba-canvas-bg: #f8fafc`, `--sidebar-bg: #f8fafc`, `--sidebar-border: #e2e8f0`).
   - Converted `#desktop-sidebar` and `.offcanvas.sidebar-offcanvas` to light workspace design with 1px right border (`#e2e8f0`), Slate text (`#475569`), soft blue active pill (`#eff6ff` / `#1d4ed8`), and removed the legacy bright-blue left stripe.
   - Refined `.navbar-top` into a compact 54px header with white surface, subtle bottom border (`#e2e8f0`), restrained typography, and accessible 44px min tap targets for mobile drawer toggle.
   - Set `<meta name="theme-color" content="#ffffff">` and updated stylesheet versioning to `?v=3.0`.
   - Applied full v2.0 typography scale across `h1`-`h4` and responsive containers.
2. `static/css/custom.css`:
   - Updated all design tokens: Primary Blue (`#1d4ed8`), Hover (`#1e40af`), Danger (`#dc2626`), Focus ring (`0 0 0 3px rgba(37,99,235,0.18)`).
   - Standardized component radii: Panels & Cards (8px), Buttons & Form Controls (6px), Badges & Chips (4px).
   - Replaced old badge styling with subtle tint + 1px border + dark semantic text across all asset statuses and conditions.
   - Configured CRM / database-style data tables with quiet headers (`#f8fafc`), hairline separators (`#f1f5f9`), and soft hover states.
   - Modernized `.btn-primary-cba`, `.btn-secondary-cba`, `.btn-danger-cba`, and `.btn-outline-cba`.
   - Updated system alerts (`.cba-alert`) and pagination controls (`.cba-pagination`).
3. `templates/includes/messages.html`:
   - Polished alert spacing and modern dismissible button alignment.
4. `templates/includes/pagination.html`:
   - Validated semantic markup compatibility with the 6px radius, neutral border pagination styling.

### Visual Verification Across Viewports
Verified live rendered pages using MCP collaborative preview tools across 1920px desktop, 1366px laptop, tablet (`ipad-air`), and mobile (`iphone-12-pro`):
- **Dashboard (`/dashboard/`)**: Clean light neutral shell, KPI cards with tabular-nums metric values, responsive grid reflow.
- **Asset List (`/inventory/`)**: CRM-style table with quiet headers and 4px status badges.
- **Supply List (`/supplies/`)**: Clean table grid and restrained action buttons.
- **Add Asset Form (`/inventory/assets/add/`)**: 6px form controls, standard focus rings, natural action buttons.
- **Faculty Portal & My Borrowings (`/borrowing/my-borrowings/`)**: Scoped sidebar navigation, zero dark-shell remnants, 0 horizontal overflow.

---

## 9. Verification & Testing Matrix

| Verification Check | Method | Result | Notes |
| :--- | :--- | :--- | :--- |
| **AssetViewTests (Inventory)** | Automated Django tests | **PASSED (14/14)** | Inventory Asset List partial, history restore, search, dropdown filters, empty state, chair scoping, faculty 403, and pagination verified |
| **Full Inventory Test Suite** | `python manage.py test apps.inventory` | **PASSED (58/58)** | All inventory tests passing cleanly |
| **SupplyViewTests (Supplies)** | Automated Django tests | **PASSED (18/18)** | Supplies List partial, history restore, debounced search, dropdown filters, combined filters, empty state, scoped pagination, and RBAC verified |
| **Full Supplies Test Suite** | `python manage.py test apps.supplies` | **PASSED (47/47)** | All supplies model, calculation, concurrency, audit, and view tests passing cleanly |
| **CurrentAssignmentHTMXTests** | Automated Django tests | **PASSED (9/9)** | Current Assignment partial, history restore, boosted request, multi-field search, dropdown filters, combined filters, empty states, scoped pagination, and RBAC scoping verified |
| **Full Assignments Test Suite** | `python manage.py test apps.assignments` | **PASSED (27/27)** | All assignments model, service, form, view, RBAC, and HTMX tests passing cleanly |
| **Full Borrowing Test Suite** | `python manage.py test apps.borrowing` | **PASSED (19/19)** | Borrowing requests, approvals, returns, and role access verified |
| **Live Browser Render Verification** | MCP preview tools | **PASSED** | Inspected Dashboard, Asset List, Supply List, Add Asset Form, and Faculty Portal across 1920px, 1366px, tablet, and mobile |
| **Horizontal Overflow Check** | JS evaluate `scrollWidth <= clientWidth` | **PASSED (0 overflow)** | Evaluated across mobile and desktop pages; zero overflow |
| **Mobile Tap Targets** | Computed dimension check | **PASSED (>= 44px)** | Hamburger menu, touch targets, buttons, and form controls meet WCAG criteria |
| **RBAC & Mixins Protection** | Automated tests + UI checks | **PASSED** | Faculty cannot view admin links; Admin/Dean/Chair access preserved |
