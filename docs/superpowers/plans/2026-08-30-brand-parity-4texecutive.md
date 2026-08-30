# Brand & UI Parity — 4tExecutive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring 4tExecutive's login page, top navigation chrome, and admin area to visual and structural parity with 4thealth-plus (the reference implementation), while keeping every existing test passing and adding new coverage for the merged admin page and host-metrics API.

**Architecture:** Adopt 4thealth-plus's `app/static/css/style.css` as the base of 4tExecutive's stylesheet, extending its two theme-token blocks with 4tExecutive's dashboard-only custom properties and appending 4tExecutive's dashboard-only selectors (widget grid, RAG borders, posture strip, charts) so the existing dashboard keeps working unchanged. Rebuild `base.html`'s topbar with a new inline SVG brand mark. Rebuild `login.html` as a standalone document matching 4thealth-plus's login markup, keeping 4tExecutive's existing cookie-based theme toggle (it already works standalone — no client-side JS needed). Merge the four admin pages into one template (`admin/index.html`) with tab-switching, keeping all four routes alive (each pre-activates its own tab) so every existing admin route test keeps passing untouched. Host CPU/Memory/Disk graphs move to a client-rendered, range-selectable chart fed by a new small JSON endpoint that reuses the existing `get_widget_series` function — no new collector.

**Tech Stack:** Flask, Jinja2, vanilla JS (no framework, matching 4thealth-plus), SQLite (`metrics.db`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-brand-parity-4texecutive-design.md`

## Global Constraints

- No changes to 4thealth-plus — it is the read-only reference model for this work.
- No new dashboard widgets, RAG logic, or data collectors. The only new backend surface is a read-only JSON endpoint reusing already-collected `poll_self()` data.
- Every existing test must still pass; only tests whose assertions target markup this plan intentionally changes (`class="auth-card"`) get updated.
- 4tExecutive's own working mechanisms (cookie-based theme persistence, Flask-WTF's `csrf_token()` call syntax, `tab_required` decorator) are kept as-is — this plan changes visual structure and CSS classes, not working infrastructure.

## Corrections to the design spec (found while planning)

The design spec (section 3) said to "copy `style.css` ... entirely, replacing the current 239-line file." Copying it verbatim would delete the CSS classes 4tExecutive's dashboard depends on (`.widget-grid`, `.rag-*`, `.posture-strip`, `.range-selector`, `.chart-svg`, etc.) and the custom properties they reference (`--surface-border`, `--accent-fg`, `--status-ok/-amber/-failed/-pending`), which have no equivalent in 4thealth-plus's token set — that would break the dashboard. This plan instead **extends** 4thealth-plus's stylesheet: its two theme-token blocks gain 4tExecutive's extra tokens, and 4tExecutive's dashboard-only rules are appended at the end, unchanged. See Task 1.

The design spec (section 4) said to collapse the four admin routes into one `GET /admin` view. Doing that would 404 every existing test that calls `client.get("/admin/sources")` / `/admin/users` / `/admin/settings` / `/admin/system` directly. This plan keeps all four routes; each renders the same shared `admin/index.html` template with a different tab pre-activated server-side (a strict improvement — deep-linking to a specific tab keeps working, and no existing test needs to change). See Task 4.

The design spec (section 5) said the login page's theme toggle would need 4thealth-plus's `localStorage`-based JS because a standalone document "can't use the cookie-based `/theme/set` route... before the page has rendered." That reasoning doesn't hold: the login page can render a `<form method="post">` to the existing `/theme` route as its own toggle button, the same way the old `base.html` did — no JS required, and the existing `data-theme` cookie tests (`tests/test_theme_routes.py`) keep passing untouched. See Task 3.

The design spec's host-metrics range buttons implicitly assumed 4thealth-plus's range set (`1h/4h/12h/1d/7d/14d`). 4tExecutive's `RANGES` dict (`app/widgets.py:354`) has no `1h` key and includes `30d`. This plan uses 4tExecutive's actual range keys (`4h/12h/1d/7d/14d/30d`) for the host-metrics range row, matching the dashboard's own range selector. See Task 5.

The design spec (section 3) implied every per-template `error` variable would be replaced by `flash()`, matching the login page's treatment. Task 4's admin merge kept panel-scoped `sources_error`/`users_error`/`settings_error` template variables instead, because the merged admin page has four tabs and a single top-of-page flash region can't express which panel an error belongs to — and the POST-error paths re-render in place rather than redirecting, which is exactly where session-based flash is weakest. This was confirmed correct by the final whole-branch review; recorded here so a future pass doesn't "fix" it back to a shared flash.

---

## File Structure

- **Modify** `app/static/css/app.css` — replaced with 4thealth-plus's stylesheet, extended per Task 1. (Filename kept so no `url_for` references change.)
- **Create** `app/static/img/` — not needed; the brand mark is inline SVG in `base.html`, matching 4thealth-plus's approach.
- **Modify** `app/templates/base.html` — topbar rebuild with the new brand mark.
- **Modify** `app/templates/login.html` — rebuilt as a standalone document.
- **Modify** `app/routes/auth_routes.py` — login failure uses `flash()` instead of a template variable.
- **Delete** `app/templates/admin/sources.html`, `app/templates/admin/users.html`, `app/templates/admin/settings.html`, `app/templates/admin/system.html`.
- **Create** `app/templates/admin/index.html` — the merged, tabbed admin page.
- **Modify** `app/routes/admin_routes.py` — routes render the shared template; new `/admin/api/host-metrics` endpoint.
- **Create** `app/static/js/admin.js` — tab switching + host-metrics chart rendering (ported from 4thealth-plus, trimmed to what 4tExecutive needs).
- **Modify** `tests/test_auth_routes.py` — update the one markup-class assertion.
- **Modify** `tests/test_admin_routes.py` — add coverage for the new host-metrics API endpoint and the merged template's tab markup.
- **Modify** `docs/integrations.md` — not needed (no payload change).

---

## Task 1: Merge the stylesheet

**Files:**
- Create (copy source): reads `/Users/alanw/code/github/ai/4thealth-plus/app/static/css/style.css` (read-only reference, different repo)
- Modify: `app/static/css/app.css` (full replacement)
- Test: none (CSS has no unit tests in this repo) — verified via the full existing test suite (no template/route test depends on `app.css`'s content) and a manual smoke check at the end of this plan.

**Interfaces:**
- Produces: every CSS class and custom property used by Tasks 2-5 (`.topbar`, `.btn`, `.btn-primary`, `.btn-sm`, `.btn-ghost`, `.btn-secondary`, `.btn-block`, `.form-group`, `.form-control`, `.alert`, `.alert-danger`, `.login-page`, `.login-card`, `.login-title`, `.login-theme-row`, `.admin-tabs`, `.admin-tab`, `.admin-panel`, `.admin-panel-header`, `.table-wrapper`, `.data-table`, `.hm-header`, `.hm-range-row`, `.hm-range-btn`, `.hm-cards`, `.hm-card`, `.hm-card-title`, `.hm-chart`, `.hm-svg-wrap`, `.hm-svg`, `.hm-area`, `.hm-line`, `.hm-dot`, `.hm-axis`, `.hm-tick`) plus every existing 4tExecutive dashboard class kept working (`.widget-grid`, `.widget`, `.widget-1x1/2x1/2x2`, `.rag-green/amber/red`, `.widget-stale`, `.widget-value`, `.widget-source`, `.widget-updated`, `.widget-empty`, `.widget-table`, `.widget-breakdown`, `.range-selector`, `.range-btn`, `.chart-svg`, `.chart-range-label`, `.chart-bar-count/label`, `.widget-extra`, `.widget-delta`, `.posture-strip`, `.posture-pill`, `.posture-ok/attention/critical`, `.posture-counts`, `.posture-freshness`, `.posture-stale`, `.status-ok/failed/pending`).

- [ ] **Step 1: Copy 4thealth-plus's stylesheet as the new base**

```bash
cp /Users/alanw/code/github/ai/4thealth-plus/app/static/css/style.css /Users/alanw/code/github/web/4tExecutive/app/static/css/app.css
```

- [ ] **Step 2: Run the full test suite to confirm nothing depends on the old file's contents yet**

Run: `pytest -q`
Expected: same failures as before this change (there should be none yet — this step exists to establish a clean baseline before editing the copied file).

- [ ] **Step 3: Extend the light-theme token block with 4tExecutive's dashboard-only custom properties**

In `app/static/css/app.css`, find the block starting `:root,\n[data-theme="light"] {` (copied from 4thealth-plus, ends with `--topbar-active:#60a5fa;\n}`). Add these lines immediately before that block's closing `}`:

```css
  /* 4tExecutive dashboard-only tokens (no 4thealth-plus equivalent) */
  --surface-border: #dfe3ea;
  --accent-fg:      #ffffff;
  --status-ok:      #1a7f37;
  --status-amber:   #b98900;
  --status-failed:  #b00020;
  --status-pending: #8a939c;
```

- [ ] **Step 4: Extend the dark-theme token block the same way**

Find the `[data-theme="dark"] { ... }` block (ends with `--topbar-active:#93c5fd;\n}`). Add before its closing `}`:

```css
  /* 4tExecutive dashboard-only tokens (no 4thealth-plus equivalent) */
  --surface-border: #262f45;
  --accent-fg:      #0d1626;
  --status-ok:      #3fca6c;
  --status-amber:   #e0a940;
  --status-failed:  #ff6b6b;
  --status-pending: #9aa3b8;
```

- [ ] **Step 5: Append 4tExecutive's dashboard-only rules to the end of the file**

Append this block at the very end of `app/static/css/app.css` (copied verbatim from the pre-Task-1 version of the file, with the now-redundant rules dropped: `.error`, `.text-muted`, bare `table/th/td`, `nav`/`.nav-*`, `.theme-toggle`, `.auth-page`/`.auth-card`, `.form-field`/`.form-input`, `.btn-primary`/`.btn-secondary` — all superseded by 4thealth-plus's equivalents already in the file):

```css

/* ── 4tExecutive dashboard (no 4thealth-plus equivalent) ─────────────── */
main { padding: 1.5rem; max-width: 1100px; margin: 0 auto; }

.widget-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-auto-rows: 120px;
  gap: 1rem;
}

.widget {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
}

.widget h3 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.widget-1x1 { grid-column: span 1; grid-row: span 1; }
.widget-2x1 { grid-column: span 2; grid-row: span 1; }
.widget-2x2 { grid-column: span 2; grid-row: span 2; }

.rag-green { border-left: 4px solid var(--status-ok); }
.rag-amber { border-left: 4px solid var(--status-amber); }
.rag-red { border-left: 4px solid var(--status-failed); }

.widget-stale { opacity: 0.85; }
.widget-stale .widget-updated { color: var(--status-amber); }

.widget-value {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--text);
}

.widget-2x2 .widget-value,
.widget-2x1 .widget-value {
  font-size: 1.15rem;
  font-weight: 500;
}

.widget-source { margin: 0; font-size: 0.72rem; color: var(--text-muted); }
.widget-updated { margin: 0; font-size: 0.7rem; color: var(--text-muted); }
.widget-empty { margin: 0; font-size: 0.9rem; color: var(--text-muted); font-style: italic; }

.widget-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.widget-table td { padding: 0.15rem 0; border: none; color: var(--text); }
.widget-table td:last-child { text-align: right; font-weight: 600; }

.widget-breakdown { margin: 0.3rem 0 0; padding-left: 1.1rem; font-size: 0.75rem; color: var(--text-muted); }
.widget-breakdown li { margin: 0.1rem 0; }

.status-ok { color: var(--status-ok); }
.status-failed { color: var(--status-failed); }
.status-pending { color: var(--status-pending); }

@media (max-width: 720px) {
  .widget-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .widget-2x1, .widget-2x2 { grid-column: span 2; }
}

.range-selector { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }

.range-btn {
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
  font-size: 0.8rem;
}

.range-btn:hover { opacity: 0.85; }
.range-btn.active { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }

.chart-svg { width: 100%; height: auto; display: block; }
.chart-range-label { margin: 0.2rem 0 0; font-size: 0.7rem; color: var(--text-muted); }
.chart-bar-count, .chart-bar-label { font-size: 6px; fill: var(--text-muted); }
.widget-extra { margin: 0.2rem 0 0; font-size: 0.72rem; color: var(--text-muted); }
.widget-delta { margin: 0.2rem 0 0; font-size: 0.72rem; color: var(--text-muted); }

.posture-strip { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; padding: 0.6rem 0.9rem; border-radius: 8px; background: var(--surface); border: 1px solid var(--surface-border); font-size: 0.85rem; }
.posture-pill { font-weight: 700; padding: 0.15rem 0.6rem; border-radius: 999px; color: var(--accent-fg); }
.posture-ok .posture-pill { background: var(--status-ok); }
.posture-attention .posture-pill { background: var(--status-amber); }
.posture-critical .posture-pill { background: var(--status-failed); }
.posture-counts { color: var(--text); text-decoration: none; }
.posture-counts:hover { text-decoration: underline; }
.posture-freshness { margin-left: auto; color: var(--text-muted); font-size: 0.78rem; }
.posture-stale { color: var(--status-amber); }
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS, identical results to Step 2 (this task only changes CSS; no Python or template test reads `app.css`'s content, so nothing here should change behavior yet — Tasks 2-5 are what exercise the new classes).

- [ ] **Step 7: Commit**

```bash
git add app/static/css/app.css
git commit -m "Adopt 4thealth-plus's stylesheet as 4tExecutive's chrome, keep dashboard CSS"
```

---

## Task 2: Brand mark and topbar

**Files:**
- Modify: `app/templates/base.html` (full rewrite)
- Test: `tests/test_dashboard_routes.py`, `tests/test_admin_routes.py` (verify existing nav-dependent assertions, if any, still pass — see Step 4)

**Interfaces:**
- Consumes: `.topbar`, `.topbar-brand`, `.brand-mark`, `.topbar-nav`, `.nav-link`, `.topbar-right`, `.nav-user`, `.btn.btn-sm.btn-ghost`, `.alert`, `.alert-{{ category }}`, `.main-content` (Task 1).
- Produces: `{% block content %}` unchanged (all child templates keep extending `base.html` the same way); flashed messages now render centrally, so any route that wants to show an error can call Flask's `flash(message, category)` and it will appear above `{% block content %}` automatically.

- [ ] **Step 1: Check current nav/topbar test coverage**

Run: `grep -rn "nav-brand\|<nav>\|theme-toggle" tests/*.py`
Expected: no matches (confirmed during planning — no test asserts on the old `<nav>` markup). If this now finds matches, read them before continuing and adjust Step 3 below to keep them passing (e.g. adjust the assertion to the new markup) rather than skipping them.

- [ ] **Step 2: Rewrite base.html**

Replace the full contents of `app/templates/base.html` with:

```html
<!doctype html>
<html data-theme="{{ request.cookies.get('theme', 'light') }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <title>4tExecutive</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
</head>
<body>
{% if session.username %}
<header class="topbar">
  <div class="topbar-brand">
    <svg class="brand-mark" width="28" height="28" viewBox="0 0 96 96" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M48 6 L86 26 V70 L48 90 L10 70 V26 Z" fill="#f4f6f8"/>
      <path d="M48 6 L48 46 L10 26 Z" fill="#7c5cbf"/>
      <path d="M48 6 L86 26 L48 46 Z" fill="#9b81d4"/>
      <line x1="48" y1="48" x2="30" y2="30" stroke="#141a24" stroke-width="3.4" stroke-linecap="round"/>
      <line x1="48" y1="48" x2="66" y2="30" stroke="#141a24" stroke-width="3.4" stroke-linecap="round"/>
      <line x1="48" y1="48" x2="48" y2="66" stroke="#141a24" stroke-width="3.4" stroke-linecap="round"/>
      <circle cx="48" cy="48" r="7" fill="#141a24"/>
    </svg>
    4tExecutive
  </div>
  <nav class="topbar-nav">
    <a href="{{ url_for('dashboard.index') }}" class="nav-link {% if request.endpoint == 'dashboard.index' %}active{% endif %}">Dashboard</a>
    {% if user_has_tab(session.username, 'admin') %}
    <a href="{{ url_for('admin.sources') }}" class="nav-link {% if request.blueprint == 'admin' %}active{% endif %}">Admin</a>
    {% endif %}
  </nav>
  <div class="topbar-right">
    <span class="nav-user">{{ session.username }}</span>
    <form method="post" action="{{ url_for('theme.set_theme') }}" style="display:inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="hidden" name="next" value="{{ request.path }}">
      {% if request.cookies.get('theme', 'light') == 'dark' %}
        <input type="hidden" name="theme" value="light">
        <button type="submit" class="btn btn-sm btn-ghost" aria-label="Switch to light mode">&#9728;</button>
      {% else %}
        <input type="hidden" name="theme" value="dark">
        <button type="submit" class="btn btn-sm btn-ghost" aria-label="Switch to dark mode">&#9789;</button>
      {% endif %}
    </form>
    <form method="post" action="{{ url_for('auth.logout') }}" style="display:inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="btn btn-sm btn-ghost">Logout</button>
    </form>
  </div>
</header>
{% endif %}

<main class="main-content">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</main>

{% block scripts %}{% endblock %}
</body>
</html>
```

Note: `user_has_tab` is already registered as a Jinja global in `app/__init__.py` (`flask_app.jinja_env.globals["user_has_tab"] = user_has_tab`) — no change needed there; the template call above already works with it.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -q`
Expected: failures only in `tests/test_auth_routes.py::test_login_page_uses_auth_card_layout` (login.html still extends the old markup at this point — fixed in Task 3) and any test asserting the removed `<nav>`/`.nav-brand` markup found in Step 1. All dashboard/admin route tests should still PASS since `{% block content %}` and every route/template downstream is unchanged.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "Rebuild topbar chrome with new 4tExecutive brand mark, matching 4thealth-plus layout"
```

---

## Task 3: Login page

**Files:**
- Modify: `app/templates/login.html` (full rewrite, no longer extends `base.html`)
- Modify: `app/routes/auth_routes.py:1-24`
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `.login-page`, `.login-card`, `.login-title`, `.login-theme-row`, `.form-group`, `.form-control`, `.btn.btn-primary.btn-block`, `.btn.btn-sm.btn-ghost`, `.alert.alert-danger` (Task 1). `theme.set_theme` route (existing, unchanged).
- Produces: nothing new consumed elsewhere — this is a leaf template.

- [ ] **Step 1: Write the failing test for the new markup**

In `tests/test_auth_routes.py`, replace:

```python
def test_login_page_uses_auth_card_layout(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'class="auth-card"' in response.data
```

with:

```python
def test_login_page_uses_login_card_layout(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'class="login-card"' in response.data
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auth_routes.py::test_login_page_uses_login_card_layout -v`
Expected: FAIL (old template still renders `class="auth-card"`)

- [ ] **Step 3: Rewrite login.html as a standalone document**

Replace the full contents of `app/templates/login.html` with:

```html
<!doctype html>
<html data-theme="{{ request.cookies.get('theme', 'light') }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <title>Login — 4tExecutive</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
</head>
<body class="login-page">
<div class="login-card">
  <h1 class="login-title">4tExecutive</h1>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  <form method="post" action="{{ url_for('auth.login') }}" autocomplete="off">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-group">
      <label for="username">Username</label>
      <input type="text" id="username" name="username" class="form-control"
             autocomplete="username" required autofocus>
    </div>
    <div class="form-group">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" class="form-control"
             autocomplete="current-password" required>
    </div>
    <button type="submit" class="btn btn-primary btn-block">Log In</button>
  </form>

  <div class="login-theme-row">
    <form method="post" action="{{ url_for('theme.set_theme') }}" style="display:inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="hidden" name="next" value="{{ request.path }}">
      {% if request.cookies.get('theme', 'light') == 'dark' %}
        <input type="hidden" name="theme" value="light">
        <button type="submit" class="btn btn-sm btn-ghost">Light Mode</button>
      {% else %}
        <input type="hidden" name="theme" value="dark">
        <button type="submit" class="btn btn-sm btn-ghost">Dark Mode</button>
      {% endif %}
    </form>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 4: Switch the login failure path to flash()**

The current full contents of `app/routes/auth_routes.py` are:

```python
"""Login and logout routes."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from app import limiter
from app.auth import verify_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session["username"] = username
            return redirect(url_for("dashboard.index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("auth.login"))
```

Replace only the `flask` import line and the `login()` function body, keeping everything else (the `limiter` import, the `@limiter.limit("10 per minute")` decorator, `logout()`) exactly as-is:

```python
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
```

```python
@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session["username"] = username
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_auth_routes.py -v`
Expected: all PASS, including `test_login_with_invalid_credentials_shows_error` (checks for `b"Invalid"` — still present via the flashed `.alert-danger` message) and the new `test_login_page_uses_login_card_layout`.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS (Task 2's topbar failures should now also be resolved — login and base chrome are both updated).

- [ ] **Step 7: Commit**

```bash
git add app/templates/login.html app/routes/auth_routes.py tests/test_auth_routes.py
git commit -m "Rebuild login page to match 4thealth-plus's standalone login layout"
```

---

## Task 4: Merge the admin pages into one tabbed template

**Files:**
- Create: `app/templates/admin/index.html`
- Delete: `app/templates/admin/sources.html`, `app/templates/admin/users.html`, `app/templates/admin/settings.html`, `app/templates/admin/system.html`
- Modify: `app/routes/admin_routes.py` (routing logic; host-metrics gathering removed here, added in Task 5)
- Create: `app/static/js/admin.js` (tab-switching only in this task; host-metrics rendering added in Task 5)
- Test: `tests/test_admin_routes.py`, `tests/test_admin_users_routes.py` (both should pass unchanged — see Step 6)

**Interfaces:**
- Consumes: `.admin-tabs`, `.admin-tab`, `.admin-panel`, `.admin-panel-header`, `.table-wrapper`, `.data-table`, `.btn.btn-primary`, `.btn.btn-secondary`, `.form-group`, `.form-control`, `.alert.alert-danger` (Task 1).
- Produces: `admin.sources` / `admin.users` / `admin.settings` / `admin.system` endpoint names (unchanged from before — every `url_for(...)` call elsewhere in the app keeps working). `_render_admin(active_panel, sources_error=None, users_error=None, settings_error=None)` — the shared render helper Task 5 also calls (with all error args `None`) for the new host-metrics-panel-adjacent code path (Task 5 doesn't touch this helper's signature).

- [ ] **Step 1: Read the current admin_routes.py in full before editing**

Run: `cat app/routes/admin_routes.py`

(Already reviewed during planning — reproduced here for reference. The four `_render_*` helper functions and their POST handlers keep their validation logic byte-for-byte identical; only what they render changes.)

- [ ] **Step 2: Write the merged template**

Create `app/templates/admin/index.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="page-header">
  <h2>Administration</h2>
</div>

<div class="admin-tabs" id="adminTabs">
  <button class="admin-tab{% if active_panel == 'sources' %} active{% endif %}" data-panel="sources">Sources</button>
  <button class="admin-tab{% if active_panel == 'users' %} active{% endif %}" data-panel="users">Users</button>
  <button class="admin-tab{% if active_panel == 'settings' %} active{% endif %}" data-panel="settings">Settings</button>
  <button class="admin-tab{% if active_panel == 'system' %} active{% endif %}" data-panel="system">System</button>
</div>

<!-- ═══════════════════════  SOURCES PANEL  ═══════════════════════ -->
<div class="admin-panel{% if active_panel == 'sources' %} active{% endif %}" id="panel-sources">
  <div class="admin-panel-header">
    <h3>Sources</h3>
  </div>

  {% if sources_error %}<div class="alert alert-danger">{{ sources_error }}</div>{% endif %}

  <div class="table-wrapper">
    <table class="data-table">
      <thead><tr><th>ID</th><th>System</th><th>Name</th><th>Enabled</th><th>TLS</th><th>Status</th><th></th></tr></thead>
      <tbody>
        {% for source in sources %}
        {% set status = statuses.get(source.id, {}) %}
        <tr>
          <td>{{ source.id }}</td>
          <td>{{ source.system }}</td>
          <td>{{ source.name }}</td>
          <td>{{ source.enabled }}</td>
          <td>{{ "Unverified (self-signed)" if not source.get("verify_tls", True) else "Verified" }}</td>
          <td>
            {% if status.status == "ok" %}
              <span class="status-ok" title="Last successful poll: {{ status.at | local_time }}">&#9679; OK</span>
            {% elif status.status == "failed" %}
              <span class="status-failed" title="{{ status.at | local_time }}">&#9679; Failed — {{ status.detail }}</span>
            {% else %}
              <span class="status-pending">&#9679; Not yet polled</span>
            {% endif %}
          </td>
          <td>
            <form method="post" action="{{ url_for('admin.refresh_source_route', source_id=source.id) }}" style="display:inline">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <button class="btn btn-secondary btn-sm" type="submit">Refresh now</button>
            </form>
            <form method="post" action="{{ url_for('admin.delete_source_route', source_id=source.id) }}" style="display:inline">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <button class="btn btn-secondary btn-sm" type="submit">Delete</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <h3 class="mt-1">Add source</h3>
  <form method="post" action="{{ url_for('admin.add_source_route') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-group"><label for="src-id">ID</label><input class="form-control" id="src-id" name="id"></div>
    <div class="form-group"><label for="src-system">System</label><input class="form-control" id="src-system" name="system" placeholder="4thealth / 4tlog"></div>
    <div class="form-group"><label for="src-name">Name</label><input class="form-control" id="src-name" name="name"></div>
    <div class="form-group"><label for="src-url">Base URL</label><input class="form-control" id="src-url" name="base_url"></div>
    <div class="form-group"><label for="src-token">Token</label><input class="form-control" id="src-token" name="token" type="password"></div>
    <div class="form-group"><label for="src-interval">Poll interval (minutes)</label><input class="form-control" id="src-interval" name="poll_interval_minutes" value="15"></div>
    <div class="form-group">
      <label><input type="checkbox" name="skip_tls_verify"> This source uses a self-signed/internal certificate (skip TLS verification)</label>
      <p class="text-muted" style="font-size:.85rem">
        Only check this for a source you trust on a private network — it disables
        protection against a machine-in-the-middle impersonating the source.
      </p>
    </div>
    <button class="btn btn-primary" type="submit">Add</button>
  </form>
</div>

<!-- ═══════════════════════  USERS PANEL  ═══════════════════════ -->
<div class="admin-panel{% if active_panel == 'users' %} active{% endif %}" id="panel-users">
  <div class="admin-panel-header">
    <h3>Users</h3>
  </div>

  {% if users_error %}<div class="alert alert-danger">{{ users_error }}</div>{% endif %}

  <div class="table-wrapper">
    <table class="data-table">
      <thead><tr><th>Username</th><th>Groups</th><th></th></tr></thead>
      <tbody>
        {% for user in users %}
        <tr>
          <td>{{ user.username }}</td>
          <td>{{ user.groups | join(', ') }}</td>
          <td>
            {% if user.username != session.username %}
            <form method="post" action="{{ url_for('admin.delete_user_route', username=user.username) }}" style="display:inline">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <button class="btn btn-secondary btn-sm" type="submit">Delete</button>
            </form>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <h3 class="mt-1">Add user</h3>
  <form method="post" action="{{ url_for('admin.add_user_route') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-group"><label for="usr-username">Username</label><input class="form-control" id="usr-username" name="username"></div>
    <div class="form-group"><label for="usr-password">Password</label><input class="form-control" id="usr-password" type="password" name="password"></div>
    <div class="form-group">
      <label>Groups</label>
      {% for group in all_groups %}
        <label><input type="checkbox" name="groups" value="{{ group }}"> {{ group }}</label>
      {% endfor %}
    </div>
    <button class="btn btn-primary" type="submit">Add</button>
  </form>
</div>

<!-- ═══════════════════════  SETTINGS PANEL  ═══════════════════════ -->
<div class="admin-panel{% if active_panel == 'settings' %} active{% endif %}" id="panel-settings">
  <div class="admin-panel-header">
    <h3>Settings</h3>
  </div>

  {% if settings_error %}<div class="alert alert-danger">{{ settings_error }}</div>{% endif %}

  <h3>Display timezone</h3>
  <p class="text-muted" style="font-size:.85rem">
    Every "as of" timestamp on the dashboard is stored in UTC and converted to
    this timezone for display only — it doesn't change how or when data is
    collected.
  </p>
  <form method="post" action="{{ url_for('admin.update_settings_route') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-group">
      <label for="tz">Timezone (IANA name)</label>
      <input class="form-control" id="tz" name="timezone" value="{{ timezone }}" placeholder="America/Chicago">
    </div>
    <p class="text-muted" style="font-size:.85rem">
      Use an IANA timezone identifier, e.g. <code>UTC</code>,
      <code>America/Chicago</code>, <code>America/New_York</code>,
      <code>Europe/London</code>. The full list is the
      <a href="https://en.wikipedia.org/wiki/List_of_tz_database_time_zones" target="_blank" rel="noopener">tz database</a>.
    </p>
    <button class="btn btn-primary" type="submit">Save</button>
  </form>
</div>

<!-- ═══════════════════════  SYSTEM PANEL  ═══════════════════════ -->
<div class="admin-panel{% if active_panel == 'system' %} active{% endif %}" id="panel-system">
  <div class="hm-header">
    <div class="hm-range-row">
      <button type="button" class="btn btn-sm hm-range-btn" data-range="4h">4 hours</button>
      <button type="button" class="btn btn-sm hm-range-btn" data-range="12h">12 hours</button>
      <button type="button" class="btn btn-sm hm-range-btn active" data-range="1d">1 day</button>
      <button type="button" class="btn btn-sm hm-range-btn" data-range="7d">7 days</button>
      <button type="button" class="btn btn-sm hm-range-btn" data-range="14d">14 days</button>
      <button type="button" class="btn btn-sm hm-range-btn" data-range="30d">30 days</button>
    </div>
    <div class="hm-cards">
      <div class="hm-card">
        <div class="hm-card-title">Host CPU</div>
        <div id="hmCpuChart" class="hm-chart"></div>
      </div>
      <div class="hm-card">
        <div class="hm-card-title">Host Memory</div>
        <div id="hmMemChart" class="hm-chart"></div>
      </div>
      <div class="hm-card">
        <div class="hm-card-title">Host Disk</div>
        <div id="hmDiskChart" class="hm-chart"></div>
      </div>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/admin.js') }}"></script>
{% endblock %}
```

- [ ] **Step 3: Delete the four standalone admin templates**

```bash
git rm app/templates/admin/sources.html app/templates/admin/users.html app/templates/admin/settings.html app/templates/admin/system.html
```

- [ ] **Step 4: Rewrite admin_routes.py's rendering to use the shared template**

Replace the four `_render_sources` / `_render_users` / `_render_settings` functions and the `system` route with:

```python
def _render_admin(active_panel, sources_error=None, users_error=None, settings_error=None):
    from app.atomic_io import read_json
    from app.auth import USERS_PATH

    sources = list_sources()
    statuses = {source["id"]: poll_status(source["id"]) for source in sources}
    usernames = [u["username"] for u in read_json(USERS_PATH, default={"users": []})["users"]]
    users = [{"username": name, "groups": get_user_groups(name)} for name in usernames]

    return render_template(
        "admin/index.html",
        active_panel=active_panel,
        sources=sources,
        statuses=statuses,
        sources_error=sources_error,
        users=users,
        all_groups=list_group_names(),
        users_error=users_error,
        timezone=get_setting("timezone", DEFAULT_TIMEZONE),
        settings_error=settings_error,
    )


@bp.route("/sources", methods=["GET"])
@tab_required("admin")
def sources():
    return _render_admin("sources")


@bp.route("/sources", methods=["POST"])
@tab_required("admin")
def add_source_route():
    base_url = request.form["base_url"]
    if not base_url.startswith("https://"):
        return _render_admin(
            "sources",
            sources_error="Base URL must start with https:// (bearer token would otherwise be sent in cleartext).",
        )

    try:
        poll_interval_minutes = int(request.form.get("poll_interval_minutes", 15))
    except ValueError:
        return _render_admin("sources", sources_error="Poll interval (minutes) must be a whole number.")

    try:
        add_source(
            id=request.form["id"],
            system=request.form["system"],
            name=request.form["name"],
            base_url=base_url,
            token=request.form["token"],
            poll_interval_minutes=poll_interval_minutes,
            verify_tls=request.form.get("skip_tls_verify") != "on",
        )
    except ValueError as exc:
        return _render_admin("sources", sources_error=str(exc))

    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/delete", methods=["POST"])
@tab_required("admin")
def delete_source_route(source_id):
    delete_source(source_id)
    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/refresh", methods=["POST"])
@tab_required("admin")
def refresh_source_route(source_id):
    poll_now(source_id)
    return redirect(url_for("admin.sources"))


@bp.route("/users", methods=["GET"])
@tab_required("admin")
def users():
    return _render_admin("users")


@bp.route("/users", methods=["POST"])
@tab_required("admin")
def add_user_route():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    groups = request.form.getlist("groups")

    if not username:
        return _render_admin("users", users_error="Username is required.")
    if get_user(username) is not None:
        return _render_admin("users", users_error=f"user already exists: {username}")

    try:
        create_user(username, password)
    except ValueError as exc:
        return _render_admin("users", users_error=str(exc))

    set_user_groups(username, groups)
    return redirect(url_for("admin.users"))


@bp.route("/users/<username>/delete", methods=["POST"])
@tab_required("admin")
def delete_user_route(username):
    if username == session["username"]:
        abort(400)
    delete_user(username)
    set_user_groups(username, [])
    return redirect(url_for("admin.users"))


@bp.route("/settings", methods=["GET"])
@tab_required("admin")
def settings():
    return _render_admin("settings")


@bp.route("/settings", methods=["POST"])
@tab_required("admin")
def update_settings_route():
    tz = request.form.get("timezone", "").strip()
    if not is_valid_timezone(tz):
        return _render_admin(
            "settings",
            settings_error=f'"{tz}" is not a recognized IANA timezone name (e.g. "America/Chicago", "UTC").',
        )
    set_setting("timezone", tz)
    return redirect(url_for("admin.settings"))


@bp.route("/system", methods=["GET"])
@tab_required("admin")
def system():
    return _render_admin("system")
```

Remove the now-unused `annotate`, `WIDGET_CATALOG`, `DEFAULT_RANGE`, and `_HOST_WIDGET_TYPES` from this file — Task 5 reintroduces the two of these it actually needs (`get_widget_series`, `RANGES`) for the new API endpoint.

- [ ] **Step 5: Write the tab-switching JS**

Create `app/static/js/admin.js`:

```javascript
(function () {
  'use strict';

  document.querySelectorAll('.admin-tab').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.admin-tab').forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.admin-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.panel).classList.add('active');
    });
  });
})();
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS. `tests/test_admin_routes.py` and `tests/test_admin_users_routes.py` should pass unmodified — every route (`/admin/sources`, `/admin/users`, `/admin/settings`, `/admin/system`) still exists and returns 200/403/302 exactly as before; content assertions (`b"East DC"`, `b"dave"`, `b"Host CPU"`, etc.) still find their text since it's still rendered in the page, just inside a named panel div. `test_admin_system_page_renders_host_metrics` should still pass — the `.hm-card-title` divs render "Host CPU"/"Host Memory"/"Host Disk" as static text regardless of whether the chart itself has data yet.

If anything fails, read the failure carefully before changing test expectations — Task 4 is designed to be a pure refactor of routing internals with no behavior change visible to these tests.

- [ ] **Step 7: Commit**

```bash
git add app/templates/admin/index.html app/routes/admin_routes.py app/static/js/admin.js
git rm app/templates/admin/sources.html app/templates/admin/users.html app/templates/admin/settings.html app/templates/admin/system.html
git commit -m "Merge admin pages into one tabbed page matching 4thealth-plus's admin layout"
```

---

## Task 5: Client-rendered host-metrics charts

**Files:**
- Modify: `app/routes/admin_routes.py` (add `/admin/api/host-metrics`)
- Modify: `app/static/js/admin.js` (add chart rendering, ported from 4thealth-plus)
- Test: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `app.widgets.get_widget_series(widget_instance, range_key)` (existing, `app/widgets.py:382`) — returns `{"points": [(iso_ts, value), ...], ...}` or `None`. `app.widgets.RANGES` (existing, `app/widgets.py:354`) — dict of valid range keys.
- Produces: `GET /admin/api/host-metrics?range=<key>` → `{"cpu": [{"ts": <epoch_seconds>, "v": <float>}, ...], "mem": [...], "disk": [...]}`.

- [ ] **Step 1: Write the failing test for the new endpoint**

Add to `tests/test_admin_routes.py`:

```python
def test_host_metrics_api_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/api/host-metrics?range=1d")
    assert response.status_code == 403


def test_host_metrics_api_returns_series_for_all_three_metrics(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    from app import metrics_db

    metrics_db.init_db()
    metrics_db.write_snapshot(
        "_self", "summary", {"cpu_percent": 12.5, "memory_percent": 40, "disk_percent": 55}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/admin/api/host-metrics?range=1d")

    assert response.status_code == 200
    data = response.get_json()
    assert data["cpu"] == [{"ts": 1787824800, "v": 12.5}]
    assert data["mem"] == [{"ts": 1787824800, "v": 40}]
    assert data["disk"] == [{"ts": 1787824800, "v": 55}]


def test_host_metrics_api_defaults_invalid_range_to_default(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    from app import metrics_db

    metrics_db.init_db()
    metrics_db.write_snapshot(
        "_self", "summary", {"cpu_percent": 5, "memory_percent": 10, "disk_percent": 15}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/admin/api/host-metrics?range=not-a-real-range")

    assert response.status_code == 200
    assert response.get_json()["cpu"] == [{"ts": 1787824800, "v": 5}]
```

(The epoch value `1787824800` is `2026-08-27T10:00:00Z` — verify with `python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('2026-08-27T10:00:00Z').timestamp()))"` before relying on it; adjust the literal if your machine's Python version computes a different value due to timezone handling — it should not, since the string carries explicit UTC (`Z`), but confirm rather than assume.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_routes.py -k host_metrics_api -v`
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add the endpoint**

In `app/routes/admin_routes.py`, add to the imports:

```python
from datetime import datetime

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from app.widgets import DEFAULT_RANGE, RANGES, get_widget_series
```

(Merge with the existing import lines rather than duplicating — `Blueprint`, `abort`, `redirect`, `render_template`, `request`, `session`, `url_for` are already imported from `flask`; add `jsonify` to that line. `DEFAULT_RANGE`, `RANGES`, `get_widget_series` replace the `annotate`, `WIDGET_CATALOG` import removed in Task 4.)

Add the route:

```python
_HOST_METRICS_KEYS = {
    "4texecutive.cpu_percent": "cpu",
    "4texecutive.memory_percent": "mem",
    "4texecutive.disk_percent": "disk",
}


@bp.route("/api/host-metrics", methods=["GET"])
@tab_required("admin")
def host_metrics_api():
    range_key = request.args.get("range", DEFAULT_RANGE)
    if range_key not in RANGES:
        range_key = DEFAULT_RANGE

    result = {}
    for widget_type, short_key in _HOST_METRICS_KEYS.items():
        series = get_widget_series({"type": widget_type, "source_instance": "_self"}, range_key)
        points = (series or {}).get("points") or []
        result[short_key] = [
            {"ts": int(datetime.fromisoformat(ts).timestamp()), "v": v}
            for ts, v in points
        ]
    return jsonify(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_routes.py -k host_metrics_api -v`
Expected: PASS

- [ ] **Step 5: Port the host-metrics chart renderer into admin.js**

Append to `app/static/js/admin.js` (before the final `})();`):

```javascript
  var HM_CHARTS = [
    { key: 'cpu', el: 'hmCpuChart' },
    { key: 'mem', el: 'hmMemChart' },
    { key: 'disk', el: 'hmDiskChart' },
  ];

  function hmEsc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function hmAxisLabel(ts, showDate) {
    var d = new Date(ts * 1000);
    return showDate
      ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  var HM_VB_W = 300;
  var HM_VB_H = 100;

  function renderHmChart(el, series, showDate) {
    if (!series.length) {
      el.innerHTML = '<div class="text-muted" style="padding:1rem 0">No data yet.</div>';
      return;
    }
    var n = series.length;
    var vals = series.map(function (p) { return p.v == null ? null : Math.max(0, Math.min(100, p.v)); });
    var xAt = function (i) { return n === 1 ? HM_VB_W / 2 : (i / (n - 1)) * HM_VB_W; };
    var yAt = function (v) { return HM_VB_H - (v / 100) * HM_VB_H; };

    var pts = vals.map(function (v, i) { return v == null ? null : xAt(i).toFixed(2) + ',' + yAt(v).toFixed(2); });
    var linePts = pts.filter(function (p) { return p !== null; }).join(' ');
    var areaPts = linePts ? '0,' + HM_VB_H + ' ' + linePts + ' ' + HM_VB_W + ',' + HM_VB_H : '';

    var dots = vals.map(function (v, i) {
      if (v == null) return '';
      var title = hmAxisLabel(series[i].ts, true) + ': ' + v.toFixed(1) + '%';
      return '<circle class="hm-dot" cx="' + xAt(i).toFixed(2) + '" cy="' + yAt(v).toFixed(2) + '" r="1.6"><title>' + hmEsc(title) + '</title></circle>';
    }).join('');

    var svg = '<svg class="hm-svg" viewBox="0 0 ' + HM_VB_W + ' ' + HM_VB_H + '" preserveAspectRatio="none">'
      + (areaPts ? '<polygon class="hm-area" points="' + areaPts + '"></polygon>' : '')
      + (linePts ? '<polyline class="hm-line" points="' + linePts + '"></polyline>' : '')
      + dots
      + '</svg>';

    var tickIdxs = [0, 0.25, 0.5, 0.75, 1].map(function (f) { return Math.min(n - 1, Math.round(f * (n - 1))); });
    var seen = {};
    var axis = series.map(function (p, i) {
      var show = tickIdxs.indexOf(i) !== -1 && !seen[i];
      seen[i] = true;
      return '<div class="hm-tick">' + (show ? hmEsc(hmAxisLabel(p.ts, showDate)) : '') + '</div>';
    }).join('');

    el.innerHTML = '<div class="hm-svg-wrap">' + svg + '</div><div class="hm-axis">' + axis + '</div>';
  }

  function loadHostMetrics(range) {
    document.querySelectorAll('.hm-range-btn').forEach(function (b) {
      b.classList.toggle('active', b.dataset.range === range);
    });

    fetch('/admin/api/host-metrics?range=' + encodeURIComponent(range))
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data) return;
        var showDate = range === '7d' || range === '14d' || range === '30d';
        HM_CHARTS.forEach(function (c) {
          var el = document.getElementById(c.el);
          if (el) renderHmChart(el, data[c.key] || [], showDate);
        });
      });
  }

  var hmRangeBtns = document.querySelectorAll('.hm-range-btn');
  if (hmRangeBtns.length) {
    hmRangeBtns.forEach(function (btn) {
      btn.addEventListener('click', function () { loadHostMetrics(btn.dataset.range); });
    });
    var initialBtn = document.querySelector('.hm-range-btn.active');
    loadHostMetrics(initialBtn ? initialBtn.dataset.range : '1d');
  }
```

- [ ] **Step 6: Manual smoke check in a browser**

This step needs a running server and a browser, not `pytest` — run it once here rather than deferring everything to the plan's final checklist, since this is the one piece of behavior (client-side chart rendering) no automated test in this repo covers.

Run: `python3 -m flask --app app run` (or however this repo's README says to start it locally), log in as an admin user, go to Admin → System, and confirm:
- The three chart cards show real line charts once at least one `poll_self()` snapshot exists (wait up to a minute, or seed one via the Python shell using `app.metrics_db.write_snapshot`).
- Clicking each range button re-fetches and redraws without a page reload (watch the Network tab for `/admin/api/host-metrics?range=...` requests).

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/routes/admin_routes.py app/static/js/admin.js tests/test_admin_routes.py
git commit -m "Add client-rendered, range-selectable host-metrics charts to the System panel"
```

---

## Task 6: Finish

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS, 0 failures.

- [ ] **Step 2: Run lint**

Run: `ruff check .` (and `ruff format --check .` if this repo enforces formatting in CI — check `pyproject.toml` / `.github/workflows/` for the exact commands this repo's CI runs, and use those verbatim).
Expected: no errors.

- [ ] **Step 3: Manual smoke check**

With the dev server running:
- Log in — confirm the new login card renders in both light and dark mode (toggle from the login page itself).
- Confirm the topbar renders the new violet brand mark and "4tExecutive" text, with Dashboard/Admin nav links working and the active link highlighted.
- Click through all four Admin tabs (Sources, Users, Settings, System) and confirm each one's existing functionality (add/delete a source, add/delete a user, save a timezone) still works.
- On the System tab, change the host-metrics range and confirm the charts redraw without a page reload.
- Log out via the new chrome and confirm you land back on the standalone login page.
- Toggle dark mode from inside the app (not just the login page) and confirm the whole chrome (topbar, cards, tables, admin tabs) re-themes correctly.

- [ ] **Step 4: Report results to the user**

Summarize: test suite status, lint status, and a plain-language description of what the manual smoke check confirmed (or any issue found and how it was resolved).
