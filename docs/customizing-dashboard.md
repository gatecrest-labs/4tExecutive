# Customizing the dashboard

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
(`4texecutive.*`, which live on Admin > System) and the two aliased firewall
counters always, plus AI Usage, Configuration Posture and Rule Hygiene
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
