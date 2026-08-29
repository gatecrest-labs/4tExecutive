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
       "default_size": "1x1",
   },
   ```

   - `source_system` must match a `system` value used in
     `config/sources.json` source records.
   - `metric_type` and `field` must match what the collector writes for that
     source into `metrics.db` (see `write_snapshot` in
     [`app/metrics_db.py`](../app/metrics_db.py) and the collector's poll
     logic in [`app/collector.py`](../app/collector.py)).
   - `default_size` is one of `1x1`, `2x1`, `2x2`.

2. If this widget pulls from a source system that isn't polled yet, the
   collector needs to know how to fetch and store that metric — see
   [Adding a source system](#adding-a-source-system) below.

3. No route or template change is required — the Dashboard's "Edit" mode
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

## Dashboard layouts

Each user's widget arrangement is stored per-username via
[`app/layouts.py`](../app/layouts.py) (`get_layout`/`save_layout`), backed by
`metrics.db`. A layout is an ordered list of placed widget instances, each
referencing a `WIDGET_CATALOG` type, a `source_instance` id, a size, and a
date range.

**There is currently no UI to build one.** `POST /dashboard/layout`
(`app/routes/dashboard_routes.py`) accepts a layout and saves it, and Edit
mode (`/dashboard/edit`) renders whatever's saved, but nothing in
`app/templates/dashboard.html` actually calls that route yet — no
add/remove/resize controls exist. Until that's built, the only way to set
a specific layout is `save_layout(username, widgets)` directly (e.g. via
`docker compose exec app python -c "..."` in a running deployment).

**Default layout, when nothing's saved**: `default_layout()`
(`app/widgets.py`) generates one widget per `WIDGET_CATALOG` entry × each
*enabled* source whose `system` matches that entry's `source_system` — so
a user with no saved layout sees everything currently configured instead
of a blank dashboard. A few entries are skipped: host metrics
(`4texecutive.*`, which live on Admin > System) and `firewall_online_count`
always (it's folded into Fleet Availability's online/total ratio —
`firewall_managed_count` stays as its own "Total Managed Firewalls" tile,
since that raw count is useful on its own even though it's also part of the
ratio), plus AI Usage, Configuration Posture and Rule Hygiene
unless the source's latest snapshot actually reports `ai_enabled: true` /
`device_review` / `rule_hygiene` respectively — a source on an older release
that never sends those fields shouldn't get permanently empty tiles. Saved
layouts containing any of them still render normally.
`app/routes/dashboard_routes.py`'s `index()`/`edit()`
use this as a fallback (`get_layout(username) or default_layout()`); a
user with any saved layout, even a single widget, always sees exactly
that instead — the default only fills in for someone who's saved nothing
at all. Each widget's card shows the source instance's `name` next to its
label so widgets from different instances of the same system stay
distinguishable.
