# Brand & UI Parity — 4tExecutive — Design

Date: 2026-08-30
Repos: `4tExecutive` (this repo). Reference/model: `4thealth-plus` (`/Users/alanw/code/github/ai/4thealth-plus`) — unmodified by this work.
Related: sub-project 2 (4tlog) follows this one as a separate spec; not started yet.

## 1. Scope

Bring 4tExecutive's login page, top navigation chrome, and admin area to visual and structural
parity with 4thealth-plus, which is the reference implementation for the product family's shared
CSS system (`app/static/css/style.css`, ~2860 lines: topbar, buttons, cards, tables, tabs,
host-metric charts, light/dark theming via `data-theme`).

4thealth-plus's own UI accent colors (`--primary`/`--accent`/`--topbar-active`, all blue) are
**not** brand-specific — the brand guide's per-product colors (green/blue/orange) only appear in
each product's topbar logo mark, not in the shared chrome. So "same look" means: adopt
4thealth-plus's CSS file and page structure verbatim, and give 4tExecutive its own logo mark in
its own accent color in the one slot where products differ.

In scope:
- Site-wide chrome: `base.html` topbar, nav, buttons, cards, tables — copy 4thealth-plus's CSS
  and page skeleton.
- A new 4tExecutive brand mark (SVG, inline in `base.html`, light/dark aware).
- Login page rebuilt as a standalone document matching 4thealth-plus's `login.html`.
- Admin area restructured from four separate routed pages into one tabbed page, with host
  CPU/Memory/Disk graphs (range-selectable, client-rendered) at the top — matching
  4thealth-plus's admin layout exactly.

Out of scope (explicitly deferred):
- 4tlog (separate spec, sub-project 2).
- Any change to 4thealth-plus.
- A shared/published CSS package — per prior decision, 4tExecutive gets its own copy of the
  stylesheet, kept in sync manually going forward (matching how 4thealth-plus and 4tlog already
  relate).
- Any new dashboard widget content, RAG logic, or data collection — this is presentation/chrome
  only. The one exception is a small new read-only API endpoint (section 4) needed to reproduce
  the host-metrics chart's interactivity; it reuses existing collected data, no new collector.

## 2. Brand mark

4tExecutive is not covered by the Gatecrest Labs brand guide's four-product list (4tHealth,
4tLog, 4tAnalyst, 4tHealth+). Per your direction, it gets its own place in the family:

- **Accent color:** `#7C5CBF` (violet) — distinct from 4tHealth green (`#2F9E6E`), 4tLog blue
  (`#3F7FD1`), 4tAnalyst orange (`#E08A2C`), and Gatecrest Labs' reserved beacon copper
  (`#C76B2C`).
- **Glyph:** concentric signal-rings core (matching the family's mark geometry) with several
  thin lines converging into the core from different angles — reads as "signals from the fleet
  rolling up into one view," fitting 4tExecutive's role as the cross-product executive rollup.
- **Construction:** inline `<svg>` in `base.html`'s topbar-brand slot, sized and positioned the
  same as 4thealth-plus's `.brand-mark` (28×28, `margin-right: .4rem`), built from the same
  `viewBox="0 0 96 96"` frame so it drops into the existing CSS class untouched. One SVG, no
  separate dark variant needed — the ink/paper tones it uses already come from the shared
  `--text`/`--surface` design tokens via `currentColor` where sensible, with the violet accent
  as a hard-coded fill (accent color doesn't change between themes, consistent with how
  4thealth-plus's green/orange mark fills are also hard-coded).

## 3. Site-wide chrome

- Copy `app/static/css/style.css` from 4thealth-plus into 4tExecutive at
  `app/static/css/app.css` (keep the existing filename/`url_for` reference so no template
  link changes), replacing the current 239-line file entirely. No color-token edits — the file
  is adopted as-is, including its blue `--primary`/`--accent`/`--topbar-active` variables.
- Rebuild `app/templates/base.html` to match 4thealth-plus's structure:
  - `<html data-theme="...">` — 4tExecutive already sets this from a cookie; keep that
    mechanism (4thealth-plus uses `localStorage` + a client toggle button; 4tExecutive's
    existing cookie-based `/theme/set` POST route stays, since it already works and avoids a
    behavior change to an unrelated feature).
  - `<header class="topbar">` with `.topbar-brand` (new SVG mark + "4tExecutive" text),
    `.topbar-nav` (existing nav links: Dashboard, Admin — gated by `user_has_tab`, same as
    today, just re-classed as `.nav-link`), and `.topbar-right` (username, theme toggle,
    logout — restyled to match 4thealth-plus's button/icon treatment, keeping 4tExecutive's
    existing routes).
  - `<main class="main-content">` wrapping `{% block content %}`, with flashed messages
    rendered above it using the shared `.alert`/`.alert-{{ cat }}` classes (4tExecutive's flash
    messages currently render ad hoc per-template as `{% if error %}`; this centralizes them
    in `base.html` the way 4thealth-plus does — existing per-template `error` variables keep
    working via `flash()` calls added where routes currently pass `error=`).
  - Theme-toggle button becomes `<button class="btn btn-sm btn-ghost">` with the same emoji
    glyphs 4tExecutive already uses (☀️/🌙), submitting its existing POST form — no JS is
    added here since the cookie round-trip already works.
- Every page extending `base.html` (dashboard, admin) inherits the new chrome automatically.

## 4. Admin restructuring

Four routed pages (`admin/sources.html`, `users.html`, `settings.html`, `system.html`) merge
into one `admin/index.html`, following 4thealth-plus's `admin-tabs`/`admin-panel` pattern.

**Routing:** `admin_routes.py`'s four GET routes (`/admin/sources`, `/admin/users`,
`/admin/settings`, `/admin/system`) collapse into one `GET /admin` view (`admin.admin_page`)
that gathers all four panels' data in one render call and returns `admin/index.html`. The four
POST routes (add/delete source, add/delete user, update settings) are unchanged — they still
redirect back to `url_for("admin.admin_page")` instead of their old per-panel endpoints. This
keeps each panel's existing server-side logic (validation, error messages) intact; only the
routing surface and template shrink. Old URLs (`/admin/sources` etc.) are dropped — no saved
bookmarks or links depend on them outside the nav, which is being rebuilt anyway.

**Panel markup:** four panels — Sources, Users, Settings, System — as `.admin-panel` divs
inside `#panel-sources`, `#panel-users`, `#panel-settings`, `#panel-system`, switched by
`.admin-tab` buttons and the same vanilla-JS click handler pattern 4thealth-plus uses (a new
`app/static/js/admin.js`, since 4tExecutive has none today — this project's forms currently
work via full-page POST/redirect, which continues to work inside a panel div unchanged).

**Host metrics (System panel):** matches 4thealth-plus's `hm-header`/`hm-range-row`/`hm-cards`
exactly — three `.hm-card` blocks (CPU/Memory/Disk) with a shared range-selector
(1h/4h/12h/1d/7d/14d) above them, client-rendered as SVG line charts on range change, no page
reload. This requires:
- A new `GET /admin/api/host-metrics?range=<key>` JSON endpoint in `admin_routes.py`, reusing
  the existing `get_widget_series` logic (already used by `_HOST_WIDGET_TYPES` today) for
  `4texecutive.cpu_percent`/`memory_percent`/`disk_percent`, returning
  `{"cpu": [{"ts": ..., "v": ...}, ...], "mem": [...], "disk": [...]}`. No new collector — same
  `poll_self()` data 4tExecutive already gathers every minute.
- The System panel's static markup (`.hm-card` divs with empty `#hmCpuChart` etc.) plus a
  ported version of 4thealth-plus's `renderHmChart`/`loadHostMetrics` JS (the self-contained
  SVG polyline/area/dot renderer in `admin.js`, lines ~868-935) — copied essentially verbatim
  since it has no 4thealth-plus-specific dependencies (pure fetch + SVG string building).
- The old server-rendered `_charts.html` line-chart approach in `system.html` is retired for
  this panel; `_charts.html` itself is untouched (still used elsewhere, e.g. dashboard widgets).
- The AI-trend-summary box above the charts in 4thealth-plus's admin page is **not** ported —
  4tExecutive has no equivalent AI feature; the System panel starts directly with the range row.

## 5. Login page

Rebuilt as a standalone HTML document (own `<head>`, `<link>` to `app.css`, no topbar/nav),
matching 4thealth-plus's `login.html` structure:
- `.login-page` body, `.login-card` container, `.login-title` (🔒 4tExecutive), no subtitle
  (4tExecutive has no tagline; omit that line rather than inventing one).
- Flash messages via `get_flashed_messages(with_categories=true)` rendered as `.alert` divs —
  4tExecutive's current `{% if error %}<p class="error">{{ error }}</p>{% endif %}` becomes a
  real `flash()` call from `auth_routes.py`'s login view on failure, matching the centralized
  flash pattern adopted in section 3.
- Form fields keep 4tExecutive's existing field names/ids (`username`/`password`) and its
  current CSRF pattern (`{{ csrf_token() }}` as a function call — Flask-WTF's default, already
  working; 4thealth-plus's `{{ csrf_token }}` bare-value pattern is a difference in how each
  app's context processor exposes it, not something to unify here).
  - `.form-group`/`.form-control`/`.btn.btn-primary.btn-block` classes replace the current
    `.form-field`/`.form-input`/`.btn-primary` classes to match 4thealth-plus's markup.
- Theme toggle: same inline `<script>` 4thealth-plus uses (`localStorage` read/write +
  `data-theme` attribute toggle) — the login page is pre-session, so it can't use 4tExecutive's
  cookie-based `/theme/set` route (that requires CSRF + a POST round trip before the page has
  rendered). This is the one place 4tExecutive's theme mechanism diverges from the rest of the
  app; acceptable since it's exactly what 4thealth-plus itself does on its own login page.

## 6. Testing

- `tests/test_admin_routes.py`: update route assertions for the collapsed `/admin` URL and
  panel-based template; add coverage for the new `/admin/api/host-metrics` endpoint (valid
  range keys, malformed range, empty-data shape).
- `tests/test_auth_routes.py`: update login-page assertions for new markup/classes and the
  `flash()`-based error path.
- `tests/test_charts_template.py`: audit for `system.html`-specific assertions that no longer
  apply once that template's chart rendering moves to the client-side JS path; keep/adjust
  whatever still exercises `_charts.html` for dashboard widgets.
- No new Python test file for `admin.js`'s ported chart renderer — 4thealth-plus has no JS unit
  tests for it either; parity here means matching that (no test gap introduced, none removed).
- Manual smoke check (per this repo's standard finishing checklist): log in, confirm topbar/mark
  render in both themes, click through all four admin tabs, change host-metrics range and
  confirm charts redraw without a page reload, log out via the new chrome, confirm login page
  renders standalone with working theme toggle.
