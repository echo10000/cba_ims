# Frontend Interactivity Foundation, Phase 2 Alpine.js & Phase 3A/3B HTMX — AI Handoff

## 1. Executive Summary

The frontend interactivity stack combines **HTMX** (v1.9.12) and **Alpine.js** (v3.14.8) vendored locally as infrastructure:
- **Phase 1**: Infrastructure vendored, global CSRF configured, HX-Request cache bypass in Service Worker, no hx-boost on navigation.
- **Phase 2**: Low-risk Alpine.js UI state implemented across collapsible filter panels, bulk QR checkbox selection, and inline safe action confirmations.
- **Phase 3A**: HTMX read-only search, filtering, and scoped pagination for the **Inventory Asset List** (`AssetListView`).
- **Phase 3B (CURRENT COMPLETED)**: HTMX read-only search, filtering, and scoped pagination for the **Consumable Supply List** (`SupplyListView`).

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

### Code Cleanup & Duplication Removal
- In `static/js/custom.js`: Removed the obsolete `.filter-collapse-btn` vanilla event listener to prevent duplicate event triggers.
- Retained global `.confirm-action` and `form[data-confirm]` handlers in `custom.js` for all non-migrated complex workflows.

---

## 4. Phase 3A Implementation: HTMX Inventory Asset List

1. **Partial Extraction (`templates/inventory/partials/_asset_results.html`)**:
   - Contains result counter (`Showing X–Y of Z assets`), desktop table view, mobile card view, scoped pagination controls, and institutional empty state.
   - When 0 assets match, displays a clean institutional empty state with a "Clear Filters" button if filters are active; no empty table or dead headers are rendered.
   - Includes asset thumbnails, property numbers, serials, and institutional condition/status badges.

2. **Full Page Wrapper (`templates/inventory/asset_list.html`)**:
   - Hosts the Alpine-driven filter toggle panel and top toolbar.
   - All search inputs and filter selects are wrapped in a unified form `#assetFilterForm` with `action="{% url 'inventory:asset_list' %}"`.
   - Live Search: `hx-trigger="keyup changed delay:350ms, search"`, `hx-target="#asset-results-container"`, `hx-push-url="true"`, `hx-indicator="#asset-loading-indicator"`, `hx-include="#assetFilterForm"`.
   - Dropdown Filters (Category, Brand, Department, Location, Condition, Status): `hx-trigger="change"`, `hx-target="#asset-results-container"`, `hx-push-url="true"`, `hx-indicator="#asset-loading-indicator"`, `hx-include="#assetFilterForm"`.
   - Restrained Loading Indicator: `#asset-loading-indicator` is an inline 0.85rem spinner tucked inside the search input group using `.htmx-indicator`. No full-screen overlays, table grayouts, or jarring skeleton layouts.
   - Dynamic Results Container: `<div id="asset-results-container">{% include 'inventory/partials/_asset_results.html' %}</div>`.

3. **Backend View Enhancement (`AssetListView` in `apps/inventory/views.py`)**:
   - Implements `get_template_names()` to return `_asset_results.html` for HTMX requests while bypassing history restore and boosted navigation.
   - Zero duplication of queryset filtering, role-based scoping, or pagination context logic.

4. **Scoped Pagination & Progressive Fallback**:
   - Pagination targets `#asset-results-container` with URL push and loading indicator.
   - Full standard GET fallback for non-JS clients.

---

## 5. Phase 3B Implementation: HTMX Consumable Supply List

1. **Partial Extraction (`templates/supplies/partials/_supply_results.html`)**:
   - Wraps catalog card container with dynamic count badge (`{{ page_obj.paginator.count }}`).
   - Contains desktop table view (`.desktop-table`), mobile card list (`.mobile-card-list`), scoped pagination, and institutional empty state.
   - When 0 supplies match: renders institutional empty state with `bi-archive`, "No Supplies Found", and "Clear Filters" button if filters are active; no empty table or dead headers are rendered.
   - Displays real-time on-hand stock balances, reorder level thresholds, stock health badges (Out of Stock, Low Stock, In Stock), and role-checked action buttons.

2. **Full Page Wrapper (`templates/supplies/supply_list.html`)**:
   - Hosts page header with live Low Stock alert badge and action links (`Stock In`, `Stock Out`, `New Supply Item`).
   - Hosts Alpine-driven mobile filter collapse panel (`open: <has_filters>`).
   - Form `#supplyFilterForm` with `hx-get="{% url 'supplies:supply_list' %}"`, `hx-target="#supply-results-container"`, `hx-push-url="true"`, `hx-indicator="#supply-loading-indicator"`.
   - Live Search: `#supplySearchInput` with `hx-trigger="keyup changed delay:350ms, search"`, `hx-include="#supplyFilterForm"`, `hx-target="#supply-results-container"`, `hx-push-url="true"`.
   - Dropdown Filters (Category, Brand, Stock Status, State): `hx-trigger="change"`, `hx-include="#supplyFilterForm"`, `hx-target="#supply-results-container"`, `hx-push-url="true"`.
   - Restrained Loading Indicator: `#supply-loading-indicator` is an inline 0.85rem spinner inside the search input group (`.htmx-indicator`).
   - Dynamic Results Container: `<div id="supply-results-container">{% include 'supplies/partials/_supply_results.html' %}</div>`.

3. **Backend View Enhancement (`SupplyListView` in `apps/supplies/views.py`)**:
   - Implements `get_template_names()`:
     ```python
     def get_template_names(self):
         if (
             self.request.headers.get('HX-Request') == 'true'
             and self.request.headers.get('HX-History-Restore-Request') != 'true'
             and self.request.headers.get('HX-Boosted') != 'true'
         ):
             return ['supplies/partials/_supply_results.html']
         return [self.template_name]
     ```
   - Zero duplication of `get_queryset()` stock calculations, multi-field search (`supply_code`, `item_name`, `brand__name`, `category__name`), filter parameters, or context data.
   - Back/Forward history navigation (`HX-History-Restore-Request: true`) cleanly returns the full page shell `supplies/supply_list.html`.
   - Purely read-only: no changes to transaction calculations, ledger models, or stock operation forms.

4. **Scoped HTMX Pagination**:
   - Scoped pagination in `_supply_results.html` targets `#supply-results-container` with `hx-push-url="true"` and `hx-indicator="#supply-loading-indicator"`.
   - Preserves search and filter parameters across page changes via `query_string` context variable.
   - Standard `href` fallback on all page links.

5. **Security & Role-Based Access Control**:
   - Strictly enforced via `SupplyViewAccessMixin`. Admin, Dean, and Department Chair access verified with HTMX headers (HTTP 200).
   - Faculty accounts blocked and redirected to `assignments:my_accountability`.

---

## 6. Verification & Testing Matrix

| Verification Check | Method | Result | Notes |
| :--- | :--- | :--- | :--- |
| **AssetViewTests (Inventory)** | Automated Django tests | **PASSED (14/14)** | Inventory Asset List partial, history restore, search, dropdown filters, empty state, chair scoping, faculty 403, and pagination verified |
| **Full Inventory Test Suite** | `python manage.py test apps.inventory` | **PASSED (58/58)** | All inventory tests passing cleanly |
| **SupplyViewTests (Supplies)** | Automated Django tests | **PASSED (18/18)** | Supplies List partial, history restore, debounced search, dropdown filters, combined filters, empty state, scoped pagination, and RBAC verified |
| **Full Supplies Test Suite** | `python manage.py test apps.supplies` | **PASSED (47/47)** | All supplies model, calculation, concurrency, audit, and view tests passing cleanly |
| **History Restore Request** | `HTTP_HX_HISTORY_RESTORE_REQUEST` test | **PASSED** | Correctly yields full page wrapper `supply_list.html` |
| **Debounced Search Trigger** | Template & test inspection | **PASSED** | `keyup changed delay:350ms, search` with `hx-include="#supplyFilterForm"` |
| **Dropdown Filter Trigger** | Template & test inspection | **PASSED** | `change` trigger combines active search query and select values |
| **Empty State Rendering** | Automated test (`q=NON_EXISTENT_QUERY_XYZ`) | **PASSED** | Displays "No Supplies Found" + "Clear Filters"; no `<table>` or `<thead>` rendered |
| **RBAC Scoping under HTMX** | Automated test | **PASSED** | Admin, Dean, and Chair receive HTTP 200; Faculty is redirected to `my_accountability` |
| **Non-targeted Modules** | Git diff inspection | **PASSED** | Assignments, Audit Log, Disposals, QR Printing untouched |

---

## 7. Architectural Guardrails & Next Steps

### Guardrails (Strictly Preserved)
- No modifications made to `StockInView`, `StockOutView`, `StockAdjustmentView`, `services.py`, transaction models, stock balances, or transaction forms.
- Server remains the single authoritative source of truth for stock calculations.
- No unscoped backend endpoints created.
- Progressive enhancement guaranteed for non-JS/fallback clients.

### Next Pending Task
- **Phase 3C**: Assignments & Audit Log read-only HTMX search/filtering (`CurrentAssignmentListView`, `AuditLogListView`, etc.).
