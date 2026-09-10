(function () {
  'use strict';

  // Hover tooltip for sparkline points: small inline JS, no library. Each
  // point circle (see _charts.html's sparkline_chart macro) carries
  // data-ts/data-value; we show them near the cursor on hover.
  var tooltip = document.createElement('div');
  tooltip.className = 'chart-hover-tooltip';
  tooltip.hidden = true;
  document.body.appendChild(tooltip);

  function formatDate(ts) {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
      d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  document.addEventListener('mouseover', function (e) {
    var target = e.target.closest && e.target.closest('.chart-hover-point');
    if (!target) return;
    tooltip.textContent = target.dataset.value + ' · ' + formatDate(target.dataset.ts);
    tooltip.hidden = false;
  });

  document.addEventListener('mousemove', function (e) {
    if (tooltip.hidden) return;
    tooltip.style.left = (e.pageX + 12) + 'px';
    tooltip.style.top = (e.pageY + 12) + 'px';
  });

  document.addEventListener('mouseout', function (e) {
    var target = e.target.closest && e.target.closest('.chart-hover-point');
    if (!target) return;
    tooltip.hidden = true;
  });
})();
