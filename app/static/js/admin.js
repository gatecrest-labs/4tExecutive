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
})();
