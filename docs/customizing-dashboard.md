# Customizing the dashboard

## Reading the dashboard: badges, colors, and indicators

This section is for anyone looking at the dashboard, not just developers
extending it.

**Posture strip** (top of the dashboard): a single-glance summary across
every widget that has a color state.

- **OK** (green pill) — every colored widget is green.
- **Attention** (amber pill) — at least one widget is amber, none are red.
- **Critical** (red pill) — at least one widget is red. Click the "N
  critical · M attention" link to jump straight to the first offending
  widget.
- **oldest data: N min ago** — how stale the *freshest-required* data on
  the page is. Turns amber if the oldest widget's data is more than twice
  as old as its source's poll interval — a sign a source may not be
  reporting reliably, not necessarily that anything is actually wrong.

**Colored left border on a widget card** (red / amber / green): this is the
widget's own status against a threshold specific to that metric (e.g.
Hygiene Score ≥90 is green, ≥75 is amber, below that is red). Not every
widget has one — informational widgets like Rule Hygiene or Total Rules
intentionally have no color, because a rising or falling number isn't
inherently good or bad on its own; only the widgets where a specific value
range means "fine" vs. "needs attention" get a color.

**Delta annotation** (▲/▼/— under a trend chart): how much the value has
changed over the selected time range (the 4h/12h/1d/... buttons above the
widgets), e.g. "▲ +30 (30d)" means it rose by 30 over the last 30 days.
"— no change (4h)" means the value hasn't moved in the last 4 hours — that's
normal for a metric that only changes occasionally (like ADOM count), not a
sign of a stuck widget.

Every widget's data also now carries a second, independent baseline
comparison computed from the `metric_points` time series (see
[architecture.md](architecture.md#derived-metric-time-series)):
`now`/`baseline_delta`/`better`/`series`, compared against a `compare_to`
baseline (`yesterday`/`7d`/`30d`/`quarter_start`) and charted over a
`sparkline` window (`30d`/`90d`/`1y`) — both selected by cookie, replacing
the old single `range` cookie for that purpose (`?range=` still works and,
when its value is itself a valid sparkline window, also sets `sparkline`).
No dashboard template renders these fields yet — they're the data layer a
future scorecard/trend-board UI reads from.

**Dimmed widget with an amber "as of" line**: the widget's *underlying*
data (not just when 4tExecutive last polled) is stale — e.g. Configuration
Posture is dimmed when its device-review rollup hasn't refreshed in the
last 48 hours, even if 4tExecutive polled the source five minutes ago. This
tells you the number on screen may not reflect recent changes, distinct
from "No data yet" (which means the metric has never been reported at
all).

**"No data yet"**: the source hasn't sent this field, either because it's
on an older release that doesn't compute it, or because the underlying job
(e.g. a scheduled Device Review) hasn't run yet.

**"as of" timestamps**: every widget shows when its data was collected, in
UTC by default. Set a display timezone in Admin → Settings (any IANA name,
e.g. `America/Chicago`) to have every "as of" line — including source poll
status on Admin → Sources — render in that timezone instead. This only
changes display; data is always collected and stored in UTC.

## Adding a widget type

Widgets come from a predefined catalog in [`app/widgets.py`](../app/widgets.py)
— not a generic query builder. To add one:

1. Add an entry to `WIDGET_CATALOG` keyed by a unique `"system.metric_name"`
   string:

   ```python
   "4thealth.hygiene_score": {
       "label": "Hygiene Score",
       "source_system": "4thealth",
       "metric_type": "summary",
       "field": "hygiene_score",
       "direction": "higher",
       "default_size": "1x1",
   },
   ```

   - `source_system` must match a `system` value used in
     `config/sources.json` source records.
   - `metric_type` and `field` must match what the collector writes for that
     source into `metrics.db` (see `write_snapshot` in
     [`app/metrics_db.py`](../app/metrics_db.py) and the collector's poll
     logic in [`app/collector.py`](../app/collector.py)).
   - `direction` is required: `"higher"` or `"lower"` if a rising/falling
     value is respectively better/worse, `"none"` if neither (e.g. a
     fleet-size count). Drives `data["better"]` — see
     [architecture.md](architecture.md#derived-metric-time-series).
   - `default_size` is one of `1x1`, `2x1`, `2x2`.
   - Optional `metric_key`: only needed when `field` is a composite dict
     with no single scalar (e.g. `device_review`) — points at the dotted
     nested-scalar key the extractor registry actually produces (see below)
     for `now`/`baseline_delta`/`series` purposes. Defaults to `field`.

2. If this widget pulls from a source system that isn't polled yet, the
   collector needs to know how to fetch and store that metric — see
   [Adding a source system](#adding-a-source-system) below.

3. Add an extractor for the new field to `EXTRACTORS` in
   [`app/metric_extract.py`](../app/metric_extract.py) — a
   `metric_key -> callable(payload) -> float | None`. A test asserts every
   catalog `field` has one (`tests/test_metric_extract.py`), so a missing
   extractor fails CI, not just at runtime. Use `_nested(*path)` for a plain
   (possibly nested) numeric field, or a custom function for anything that
   needs encoding (see `_last_backup_status`, `_fleet_availability_pct`).

4. No route or template change is required — the Dashboard's "Edit" mode
   lists everything in `WIDGET_CATALOG` automatically, and
   `get_widget_value()` looks up the latest cached value generically from
   `field`.

## Adding a source system

If you just need to connect a running `4thealth`/`4tlog` instance that
already exposes the executive-summary endpoint, see
[integrations.md](integrations.md) instead — this section is about adding
support for a source *system type* that isn't wired up at all yet.

A "source system" (e.g. `4thealth`, `4tlog`) is just a string tag on source
registry entries and widget catalog entries — there's no central list to
register it in. To add a new one:

1. In Admin, add a source instance with `system` set to your new tag (e.g.
   `4tanalyst`) and its `base_url` + bearer token.
2. In `app/collector.py`, make sure the poll logic knows how to call that
   system's API and shape the response into whatever `write_snapshot`
   expects.
3. Add widget catalog entries for its metrics as described above.

## Changing tab/group permissions

Tab access is entirely driven by `config/groups.json`:

```json
{
  "executives": {
    "members": ["admin"],
    "allowed_tabs": ["dashboard"]
  },
  "administrators": {
    "members": ["admin"],
    "allowed_tabs": ["dashboard", "admin"]
  }
}
```

A user sees a tab if they belong to any group whose `allowed_tabs` includes
it (`app/groups.py`). Routes enforce this with the `@tab_required("admin")`
decorator (`app/decorators.py`) — add that decorator to any new route that
should be gated the same way. There's currently no sub-permission system
within a tab (e.g. "can manage sources" vs. "can manage users" are both just
`admin`); see [architecture.md](architecture.md) if you need to split that
out.

`allowed_tabs` is an open-ended list of plain strings, not a fixed enum —
there is no admin UI anywhere in this app for editing a group's
`allowed_tabs` (confirmed by grep; every existing tab, including
`dashboard` and `admin`, is granted by hand-editing `config/groups.json`,
not through a checkbox in the UI). Granting the two tabs the Weekly
Executive Brief introduces — `brief` (view `/brief`) and `brief_edit` (edit
the "asks for leadership" list via `POST /brief/asks`) — works exactly the
same way: add the string to a group's `allowed_tabs` array and save the
file (the app reads it fresh on each request, no restart needed). For
example, to let an "executives" group view the brief, and let a separate
smaller "leadership" group also edit its asks list:

```json
{
  "executives": {
    "members": ["admin", "cfo"],
    "allowed_tabs": ["dashboard", "brief"]
  },
  "leadership": {
    "members": ["cfo"],
    "allowed_tabs": ["dashboard", "brief", "brief_edit"]
  }
}
```

A user only needs `brief` to view the page; `brief_edit` is checked
separately (`user_has_tab(username, "brief_edit")`) to decide whether
`brief.html` shows the asks list read-only or with an edit form — a user
can have `brief_edit` without `brief`, but since `/brief` itself is gated on
`brief`, grant both together in practice.

## Admin > Reports (SMTP + weekly brief schedule)

Admin's Reports panel (gated by the existing `admin` tab, same as every
other Admin panel — no new tab for this one) configures the Weekly
Executive Brief's delivery: an SMTP settings form (`config/smtp.json`, saved
via `app/smtp_client.py`; the password field never round-trips the
decrypted secret back into the rendered `<input>` — it shows a blank field
with a `placeholder="(unchanged)"`, the same convention `app/sources.py`'s
token field already uses, and only overwrites the stored password when you
submit a non-empty value), a schedule form (weekday/hour/recipients/enabled,
`config/brief_schedule.json` via `app/brief_schedule.py`), a "Send test"
button (builds today's brief for real and emails it to one address), and a
history table of past sends (`brief_sends`) with HTML/PDF download links.

The schedule config is read once at scheduler startup (see
[architecture.md](architecture.md#weekly-executive-brief)) — like the
collector's other fixed-interval jobs, changing weekday/hour/enabled here
takes effect on the app's next restart, not immediately.

## The Trend Board's row universe

`GET /board` (`app/board.py`) is a **fixed, comprehensive** board, not a
per-user layout: it shows one row per `WIDGET_CATALOG` entry × each
*enabled* source whose `system` matches, via `app/widgets.py:default_layout()`
— the same selection `default_layout()` has always used as the personalized
dashboard's fallback (see below). Sort/filter/domain-filter/source-filter
are the customization mechanism instead of manually placing widgets.

A few entries are skipped from this universe: host metrics (`4texecutive.*`,
which live on Admin > System) and `firewall_online_count` always (it's
folded into Fleet Availability's online/total ratio — `firewall_managed_count`
stays as its own row, since that raw count is useful on its own even though
it's also part of the ratio), plus AI Usage, Configuration Posture and Rule
Hygiene unless the source's latest snapshot actually reports
`ai_enabled: true` / `device_review` / `rule_hygiene` respectively — a
source on an older release that never sends those fields shouldn't get a
permanently empty row.

Every board row belongs to one of the six Scorecard domains
(`app/board.py`'s `WIDGET_DOMAIN`), which is a presentation-only mapping
distinct from `app/domains.py`'s `MEMBER_METRICS` (the fleet-score *inputs*)
— a metric can score under one domain and display under another when that's
the better fit for browsing.

## Saved per-user layouts (currently unused by any page)

Each user's widget arrangement can still be stored per-username via
[`app/layouts.py`](../app/layouts.py) (`get_layout`/`save_layout`), backed by
`metrics.db`. A layout is an ordered list of placed widget instances, each
referencing a `WIDGET_CATALOG` type, a `source_instance` id, a size, and a
date range. `POST /dashboard/layout` (`app/routes/dashboard_routes.py`)
accepts a layout and saves it, and Edit mode (`/dashboard/edit`) renders
whatever's saved — but since the Trend Board became the fixed, comprehensive
view above, nothing reads a saved layout to decide what to display anymore.
These endpoints remain functional in case a future personalized view needs
them again.
