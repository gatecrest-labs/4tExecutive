"""Tests for the line_chart/bar_chart Jinja macros, rendered directly (no HTTP request needed)."""


def _render_line_chart(app, points, min_v, max_v):
    with app.app_context():
        module = app.jinja_env.get_template("_charts.html").module
        return str(module.line_chart(points, min_v, max_v))


def _render_bar_chart(app, data):
    with app.app_context():
        module = app.jinja_env.get_template("_charts.html").module
        return str(module.bar_chart(data))


def test_line_chart_renders_polyline_for_multiple_points(app):
    html = _render_line_chart(app, [("t0", 10), ("t1", 30), ("t2", 20)], 10, 30)
    assert "<polyline" in html
    assert "<svg" in html


def test_line_chart_shows_min_and_max_as_text(app):
    html = _render_line_chart(app, [("t0", 10), ("t1", 30)], 10, 30)
    assert "10" in html
    assert "30" in html


def test_line_chart_renders_flat_line_for_single_point(app):
    html = _render_line_chart(app, [("t0", 42)], 42, 42)
    assert "<line" in html
    assert "42" in html


def test_bar_chart_renders_rect_per_entry_with_labels(app):
    html = _render_bar_chart(app, {"7.4.5": 62, "7.2.9": 41})
    assert html.count("<rect") == 2
    assert "7.4.5" in html
    assert "62" in html
    assert "7.2.9" in html
    assert "41" in html


def test_bar_chart_handles_single_entry(app):
    html = _render_bar_chart(app, {"7.4.5": 62})
    assert html.count("<rect") == 1
