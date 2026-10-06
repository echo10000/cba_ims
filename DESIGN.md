# DESIGN.md — Visual Contract & Design System
**Project:** CBA Asset & Inventory Management System (CBA IMS)  
**Institution:** College of Business Administration  
**Audience:** University administrators, department chairs, property custodians, faculty, and administrative staff  
**Version:** 1.0  
**Status:** Canonical Visual Contract  

---

## 1. Design Philosophy & Aesthetic Identity

The CBA Asset & Inventory Management System is an internal institutional administrative platform. It is a workhorse tool engineered for high-frequency inventory tracking, accountability audits, asset transfers, and equipment borrowing.

### Core Tenets
1. **Institutional, Not Startup/SaaS:** The interface must convey academic authority, institutional permanence, and operational reliability. It must avoid consumer-SaaS trends, rainbow color schemes, floating glass cards, and empty marketing aesthetics.
2. **Dense, Legible, and Purposeful:** University property officers handle large datasets. Density and clarity take precedence over excessive whitespace and oversized decorative components.
3. **Restrained Color Architecture:** Color is exclusively functional. Saturated colors are never used as background fills for large layout blocks or stat cards. Color communicates state, urgency, and category only.
4. **Resilient Across Viewports:** Full operational parity across desktop (1280px+), laptop/tablet (768px–1024px), and mobile devices (360px–480px), particularly for barcode/QR scanning and floor verification workflows.

---

## 2. Color Palette & Functional Token System

All color tokens adhere strictly to WCAG 2.1 AA standards (minimum contrast ratio of 4.5:1 for body text, 3:1 for large text and interface components).

### 2.1 Primary & Neutral Tokens
| Token Name | Hex Code | Purpose & Usage | Contrast vs White |
| :--- | :--- | :--- | :--- |
| `--cba-primary` | `#1e3a8a` | Institutional Navy Blue: Key brand accent, primary buttons, active navigation, selected table rows | 9.4:1 |
| `--cba-primary-hover` | `#172554` | Darker Navy: Primary button hover/active states | 13.5:1 |
| `--cba-primary-light` | `#eff6ff` | Tinted Ice Blue: Highlighted rows, selected item backgrounds, active nav pill tints | N/A (Surface) |
| `--cba-surface-bg` | `#f8fafc` | Slate 50: Global application background | Base canvas |
| `--cba-surface-card` | `#ffffff` | Pure White: Card surfaces, table containers, modal bodies, form panels | Base surface |
| `--cba-surface-subtle` | `#f1f5f9` | Slate 100: Table header backgrounds, zebra striping, read-only field fills | 1.15:1 |
| `--cba-border-subtle` | `#e2e8f0` | Slate 200: Default component borders, table dividers, card outlines | 1.3:1 |
| `--cba-border-medium` | `#cbd5e1` | Slate 300: Form field borders, active tab outlines, interactive borders | 1.6:1 |

### 2.2 Text & Typography Tokens
| Token Name | Hex Code | Purpose & Usage | Contrast vs White |
| :--- | :--- | :--- | :--- |
| `--cba-text-primary` | `#0f172a` | Slate 900: Primary headings, body copy, data values, table cell text | 15.6:1 |
| `--cba-text-secondary` | `#475569` | Slate 600: Secondary text, table headers, breadcrumbs, helper descriptions | 5.8:1 |
| `--cba-text-muted` | `#64748b` | Slate 500: Metadata timestamps, footnote annotations, placeholder text | 4.6:1 |
| `--cba-text-inverted` | `#ffffff` | Pure White: Text on solid primary buttons and dark badges | 21:1 |

### 2.3 Semantic & Status Tokens
> Saturated colors are reserved exclusively for status indicators, badges, and feedback alerts. Never use them as full card background fills.

| State | Background Tint | Border Accent | Text / Icon Color | Semantic Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **Available / Success** | `#f0fdf4` (Emerald 50) | `#bbf7d0` (Emerald 200) | `#166534` (Emerald 800) | Asset available for deployment, approved request, stock healthy |
| **Warning / Maintenance** | `#fffbeb` (Amber 50) | `#fde68a` (Amber 200) | `#92400e` (Amber 800) | Low supply threshold, pending approval, scheduled maintenance |
| **Critical / Damaged / Error**| `#fef2f2` (Red 50) | `#fecaca` (Red 200) | `#991b1b` (Red 800) | Damaged asset, overdue loan, rejected transfer, missing item |
| **Assigned / Neutral Action**| `#eff6ff` (Blue 50) | `#bfdbfe` (Blue 200) | `#1e40af` (Blue 800) | Asset deployed to faculty/staff, active borrowing, active transfer |
| **Archived / Disposed** | `#f8fafc` (Slate 50) | `#e2e8f0` (Slate 200) | `#475569` (Slate 600) | Written-off, retired, or historical record |

---

## 3. Typography Architecture

System typography prioritizes rapid vertical scanning, numeric alignment, and compact data density.

### 3.1 Typeface Stack
- **Primary Interface Font:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- **Tabular / Monospace Font:** `"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace` (mandatory for Asset Tags, Serial Numbers, Barcodes, and Timestamps)

### 3.2 Scale & Hierarchy
| Level | Font Size | Line Height | Font Weight | Letter Spacing | Context / Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `H1` | `1.5rem` (24px) | `1.3` | `700` | `-0.015em` | Top-level section titles, primary page headers |
| `H2` | `1.25rem` (20px) | `1.35` | `600` | `-0.01em` | Panel titles, modal headers, major section groupings |
| `H3` | `1.1rem` (17.6px) | `1.4` | `600` | `0` | Sub-panel headers, card group titles |
| `Body` | `0.9rem` (14.4px) | `1.5` | `400` | `0` | Standard body text, table cell data, form labels |
| `Body Small` | `0.8rem` (12.8px) | `1.4` | `400` | `0` | Metadata, helper text, breadcrumbs, table footers |
| `Micro / Badge` | `0.72rem` (11.5px)| `1.2` | `600` | `0.025em` | Status badges, category pills, table header labels (uppercase) |
| `Metric Value` | `1.75rem` (28px) | `1.2` | `700` | `-0.02em` | Metric / KPI stat numbers (never exceed 28px) |

---

## 4. Spacing, Layout Grid & Elevation

### 4.1 Spacing Scale
Based on an 8-point base grid with 4-point micro-adjustments:
- `space-1`: `4px` (tight button padding, icon-text gap)
- `space-2`: `8px` (badge padding, table cell vertical padding, compact form gaps)
- `space-3`: `12px` (standard container internal padding on mobile, form field spacing)
- `space-4`: `16px` (card internal padding, desktop table cell horizontal padding)
- `space-5`: `20px` (standard main layout padding on desktop)
- `space-6`: `24px` (grid column gaps, section dividers)
- `space-8`: `32px` (page section separation)

### 4.2 Borders & Radii (Restrained Rule)
No bubble corners, oversized pills, or extreme border radii.
- **Card & Panel Radius:** `6px` (`0.375rem`)
- **Buttons & Form Inputs:** `4px` (`0.25rem`)
- **Badges & Tags:** `4px` (`0.25rem`) with 1px border.
- **Table Outlines:** `1px solid var(--cba-border-subtle)`
- **Rule:** Never use `border-radius: 9999px` (pill shapes) for operational dashboard cards or standard buttons.

### 4.3 Shadows (Restrained Elevation)
Elevation is strictly controlled to avoid floating/dreamy SaaS aesthetics.
- **Resting Card:** `0 1px 2px 0 rgba(0, 0, 0, 0.05)`
- **Hover / Interactive Card:** `0 2px 4px -1px rgba(0, 0, 0, 0.08)`
- **Dropdown & Popover:** `0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)`
- **Modal Dialog:** `0 10px 15px -3px rgba(0, 0, 0, 0.15)`
- **Banned:** Colored glowing shadows, diffused multi-layer blur drops (`0 20px 25px...`).

---

## 5. Component Patterns & Rules

### 5.1 Dashboard Stat & Metric Cards
- **No Rainbow Cards:** Never paint stat card backgrounds in saturated primary, green, orange, yellow, or red.
- **Structure:** All stat cards share a crisp white surface (`var(--cba-surface-card)`), a subtle 1px border (`var(--cba-border-subtle)`), and an understated top or left 3px indicator accent only when signaling state.
- **Information Hierarchy:**
  1. Stat label (Slate 600, uppercase, `0.75rem`, weight 600).
  2. Large primary metric (Slate 900, `1.75rem`, weight 700).
  3. Context / Subtext (e.g., "12 needing inspection", `0.8rem`, Slate 500).
- **Interactivity Affordance:** If a stat card links to a filtered view, it must include an explicit subtle text link or icon indicating drilldown, rather than relying on an invisible stretched link.

### 5.2 Buttons & Action Controls
- **Primary Action:** Solid Institutional Navy (`#1e3a8a`), white text, weight 500, `4px` radius. Focus ring: `2px solid #93c5fd` with `2px` offset.
- **Secondary Action:** White background, 1px Slate 300 border, Slate 800 text. Hover: Slate 50 background.
- **Danger Action:** Subdued crimson border or fill (`#dc2626`). Used only for destructive actions (Delete, Write-off, Deactivate).
- **Size Standards:**
  - Desktop: Height `36px` to `38px`, padding `6px 14px`.
  - Mobile: Height `44px` minimum for tap targets, padding `10px 16px`.
- **Button Clutter Rule:** Avoid placing more than 3 visible primary/secondary action buttons in a page header. Group secondary options into an institutional "Actions" dropdown menu.

### 5.3 Data Tables
Tables are the operational core of the CBA inventory application.
- **Header:** Sticky on scroll, Slate 100 background (`#f1f5f9`), uppercase 0.75rem text, weight 600, Slate 600 color, border-bottom 2px Slate 200.
- **Rows:** Alternating subtle zebra striping (`#ffffff` and `#f8fafc`), height 44px, vertical alignment middle.
- **Numeric Alignment:** Quantities, prices, dates, and asset tags right-aligned or monospace-aligned.
- **Action Columns:** Pinned or grouped at the far right. Use compact text buttons or clear icon buttons with explicit `aria-label` tooltips.
- **Empty States:** When a table has 0 rows, display an institutional message explaining why the list is empty and providing a clear path to populate it.

### 5.4 Form Elements
- **Inputs & Selects:** Height `38px` (`44px` on mobile), border 1px Slate 300, background white, text Slate 900.
- **Focus State:** 1px border `#1e3a8a`, crisp focus ring `0 0 0 3px rgba(30, 58, 138, 0.15)`. No default browser fuzzy blue halos.
- **Labels:** Crisp 0.85rem, Slate 700, weight 600, positioned directly above input. Mandatory fields marked with red asterisk `*`.
- **Help Text:** Compact 0.78rem Slate 500 directly below input. Error messages in crimson text (`#b91c1c`) with 1px red border on input.

### 5.5 Status Badges & Pills
- Badges must use the subtle background tint + 1px border + dark text formula (defined in Section 2.3).
- **Format:** `padding: 2px 8px`, `border-radius: 4px`, `font-size: 0.75rem`, `font-weight: 600`.
- **Never:** Never render unbordered dark background pills with white text for routine inventory states.

### 5.6 Navigation & Layout Shell
- **Desktop Sidebar:** Width `250px`, dark institutional slate (`#0f172a`), fixed left.
  - Section headers: Slate 400, uppercase, `0.7rem`, weight 700, tracking 0.05em.
  - Active item: `#1e293b` background with left 3px indicator line in `#38bdf8` (Ice Blue) and white text.
  - Hover item: `#1e293b` background, Slate 200 text.
- **Top Header Bar:** Crisp white background (`#ffffff`), height `56px`, 1px bottom border (`#e2e8f0`). Contains breadcrumb/page title, global search access, and user role profile.
- **Mobile Offcanvas:** Drawer width `280px`, identical navigation structure, trigger button minimum 44x44px.

---

## 6. Responsive Reflow & Viewport Rules

### Breakpoints
- **Mobile:** `< 768px` (`xs` and `sm`)
- **Tablet:** `768px – 1024px` (`md`)
- **Desktop:** `> 1024px` (`lg` and `xl`)

### Layout Behavior Rules
1. **Zero Horizontal Scroll:** The body and main containers must never produce horizontal overflow. Tables must be wrapped in responsive scroll containers (`.table-responsive`) with fade indicators or reflow into structured card lists on small mobile screens.
2. **Touch Targets:** All interactive controls (buttons, links, select inputs, pagination items, tab triggers) must have a minimum bounding box of `44px x 44px` on mobile viewports.
3. **Stat Card Stacking:**
   - Desktop (`> 1200px`): 6-column or 4-column balanced grid.
   - Tablet (`768px – 1199px`): 3-column grid.
   - Mobile (`< 768px`): 2-column grid with compact padding (`12px`) and reduced metric font size (`1.4rem`), never squishing content into unreadable ribbons.
4. **Header Action Reflow:** Long horizontal button clusters in headers must collapse into a primary CTA + "More Actions" dropdown on viewports under 768px.

---

## 7. Accessibility Standards (WCAG 2.1 AA)

1. **Color Independence:** Status is never communicated by color alone. Every badge, indicator, or alert must pair color with unambiguous text or a descriptive icon.
2. **Focus Visibility:** All interactive elements must exhibit a high-contrast visible focus ring (`:focus-visible`) when navigated via keyboard.
3. **Screen Reader Semantic Support:**
   - Icon-only buttons must have `aria-label` or visually hidden `.sr-only` text.
   - Charts must provide accessible data tables or summary aria descriptions.
   - Modals and offcanvas drawers must trap keyboard focus and restore focus on close.
4. **Form Association:** Every input must be programmatically paired with a `<label for="...">` attribute.

---

## 8. Anti-Slop Checkpoints & Delivery Gate

Before approving any UI enhancement, the page must be tested against these five hard gates:
1. **No AI Cliché Styles:** No purple/cyan gradients, no frosted glassmorphism, no bubble pills, no generic hero banners.
2. **No Rainbow Cards:** Metric cards must use clean white surfaces with disciplined typographic hierarchy.
3. **Institutional Tone:** Microcopy must use precise administrative language ("Property Custodian", "Asset Tag", "Verification Queue") rather than generic SaaS copy ("Explore", "Supercharge", "Seamless").
4. **No Scaffolding or Developer Slop:** Never leave phase numbers ("Phase 1 Foundation", "Phase 10 Analytics"), raw model names (`AssetCategory`, `app_name`), or placeholder comments visible to the end user.
5. **No Broken Mobile Elements:** Layout tested and verified on 375px mobile viewport without horizontal scroll, overlapping text, or squished touch targets.
