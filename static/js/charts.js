/* =========================================================================
   EduGen - Lightweight SVG Charts & Visualizations (static/js/charts.js)
   -------------------------------------------------------------------------
   Pure-vanilla, zero-dependency inline SVG charts.
   Strict visual language:
     BLUE   (--signal): student interactions and scores
     VIOLET (--agent):  system/agent actions and telemetry
     AMBER  (--attn):   weakness / needs consolidation
     GREEN  (--good):   mastered concepts
     GREY   (--line-2 / --ink-4): unassessed / muted
     RED is never used for chart tones or low accuracy (amber only).
   ========================================================================= */

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.EGCharts = factory();
  }
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  function esc(value) {
    if (value === null || value === undefined) return '';
    if (typeof EG !== 'undefined' && typeof EG.esc === 'function') {
      return EG.esc(value);
    }
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const TONES = {
    student: 'var(--signal, #1F4FE0)',
    agent:   'var(--agent, #6B4EE6)',
    weak:    'var(--attn, #D9700B)',
    strong:  'var(--good, #0E8C63)',
    muted:   'var(--ink-4, #A8B2C1)',
  };

  const TONES_HEX = {
    student: '#1F4FE0',
    agent:   '#6B4EE6',
    weak:    '#D9700B',
    strong:  '#0E8C63',
    muted:   '#A8B2C1',
  };

  function resolveTone(tone, fallback) {
    if (tone && TONES[tone]) return TONES[tone];
    return fallback || TONES.student;
  }

  const EGCharts = {
    tones: TONES,

    /* ── 1. Circular Progress Ring ───────────────────────────── */
    ring(value, max, options = {}) {
      const m = (typeof max === 'number' && max > 0) ? max : 100;
      const valNum = Number(value);
      const isNull = value === null || value === undefined || isNaN(valNum);
      const pct = isNull ? 0 : Math.max(0, (valNum / m) * 100);
      const clampedPct = Math.min(100, pct);

      const r = 46;
      const c = 2 * Math.PI * r; // ~289.027
      const offset = c - (clampedPct / 100) * c;

      let strokeColor;
      if (options.tone && TONES[options.tone]) {
        strokeColor = TONES[options.tone];
      } else {
        strokeColor = pct >= 80 ? 'var(--good)' : pct >= 50 ? 'var(--signal)' : 'var(--attn)';
      }

      const displayLabel = options.label !== undefined
        ? esc(options.label)
        : (isNull ? '&mdash;' : Math.round(pct) + '%');

      const subHtml = options.sub
        ? '<div class="ch-ring-sub">' + esc(options.sub) + '</div>'
        : '';

      const ariaText = esc(options.label || (isNull ? '0%' : Math.round(pct) + '%')) +
        (options.sub ? ' ' + esc(options.sub) : '');

      return '<div class="ch-ring" role="img" aria-label="' + ariaText + '">' +
        '<svg class="ch-ring-svg" width="108" height="108" viewBox="0 0 108 108" aria-hidden="true">' +
          '<circle cx="54" cy="54" r="' + r + '" fill="none" stroke="var(--line-2)" stroke-width="8"/>' +
          '<circle cx="54" cy="54" r="' + r + '" fill="none" stroke="' + strokeColor + '" stroke-width="8"' +
            ' stroke-linecap="round" stroke-dasharray="' + c.toFixed(3) + '" stroke-dashoffset="' + offset.toFixed(3) + '"/>' +
        '</svg>' +
        '<div class="ch-ring-inner">' +
          '<div class="ch-ring-val">' + displayLabel + '</div>' +
          subHtml +
        '</div>' +
      '</div>';
    },

    /* ── 2. Horizontal Comparative Bars ──────────────────────── */
    bars(items, options = {}) {
      if (!Array.isArray(items) || items.length === 0) {
        return '<div class="ch-empty"><p class="small muted" style="margin:0">No data available</p></div>';
      }

      const unit = options.unit || '';
      const fallbackTone = options.tone || 'student';
      let max = typeof options.max === 'number' && options.max > 0 ? options.max : 0;
      if (max <= 0) {
        items.forEach(it => {
          const v = Number(it.value) || 0;
          if (v > max) max = v;
        });
        if (max <= 0) max = 1;
      }

      const rows = items.map((it, idx) => {
        const val = Number(it.value) || 0;
        const clamped = Math.max(0, Math.min(max, val));
        const pct = (clamped / max) * 100;
        const toneColor = resolveTone(it.tone || fallbackTone, TONES.student);
        const subText = it.sub ? '<span class="ch-bar-sub">' + esc(it.sub) + '</span>' : '';
        const titleText = esc(it.label) + ': ' + val + unit + (it.sub ? ' (' + it.sub + ')' : '');

        return '<div class="ch-bar-row" title="' + titleText + '">' +
          '<div class="ch-bar-meta">' +
            '<span class="ch-bar-label">' + esc(it.label) + '</span>' +
            '<span class="ch-bar-val">' + val + esc(unit) + ' ' + subText + '</span>' +
          '</div>' +
          '<div class="ch-bar-track">' +
            '<div class="ch-bar-fill" style="width:' + Math.max(2, pct).toFixed(1) + '%;background:' + toneColor + ';"></div>' +
          '</div>' +
        '</div>';
      }).join('');

      return '<div class="ch-bars" role="img" aria-label="Horizontal comparison bars">' + rows + '</div>';
    },

    /* ── 3. Chronological Line Chart with Reference Line ─────── */
    line(points, options = {}) {
      if (!Array.isArray(points) || points.length === 0) {
        return '<div class="ch-empty"><p class="small muted" style="margin:0">No quiz attempts yet</p></div>';
      }

      const yMin = typeof options.yMin === 'number' ? options.yMin : 0;
      const yMax = typeof options.yMax === 'number' ? options.yMax : 100;
      const yRange = Math.max(1, yMax - yMin);
      const toneColor = resolveTone(options.tone, TONES.student);

      const w = 360;
      const h = 130;
      const padL = 32;
      const padR = 20;
      const padT = 16;
      const padB = 26;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;

      // Y-axis helper
      const getY = (val) => {
        const v = Math.max(yMin, Math.min(yMax, Number(val) || 0));
        return padT + plotH - ((v - yMin) / yRange) * plotH;
      };

      // Background grid lines (yMin, mid, yMax)
      const midVal = Math.round((yMin + yMax) / 2);
      const gridHtml =
        '<g class="ch-grid" stroke="var(--line-2)" stroke-width="1">' +
          '<line x1="' + padL + '" y1="' + getY(yMax) + '" x2="' + (w - padR) + '" y2="' + getY(yMax) + '"/>' +
          '<line x1="' + padL + '" y1="' + getY(midVal) + '" x2="' + (w - padR) + '" y2="' + getY(midVal) + '" stroke-dasharray="2 3"/>' +
          '<line x1="' + padL + '" y1="' + getY(yMin) + '" x2="' + (w - padR) + '" y2="' + getY(yMin) + '"/>' +
        '</g>' +
        '<g class="ch-grid-labels" font-size="9" fill="var(--ink-3)" font-family="var(--font-ui)" text-anchor="end">' +
          '<text x="' + (padL - 6) + '" y="' + (getY(yMax) + 3) + '">' + yMax + '%</text>' +
          '<text x="' + (padL - 6) + '" y="' + (getY(midVal) + 3) + '">' + midVal + '%</text>' +
          '<text x="' + (padL - 6) + '" y="' + (getY(yMin) + 3) + '">' + yMin + '%</text>' +
        '</g>';

      // Optional reference line (e.g. 70% passing threshold)
      let refHtml = '';
      if (options.refLine !== undefined && options.refLine !== null) {
        const refVal = typeof options.refLine === 'object' ? options.refLine.value : Number(options.refLine);
        const refLabel = typeof options.refLine === 'object' ? (options.refLine.label || (refVal + '%')) : (refVal + '%');
        if (!isNaN(refVal)) {
          const rY = getY(refVal);
          refHtml = '<g class="ch-ref-line">' +
            '<line x1="' + padL + '" y1="' + rY + '" x2="' + (w - padR) + '" y2="' + rY + '"' +
              ' stroke="var(--attn)" stroke-dasharray="4 4" stroke-width="1.5"/>' +
            '<text x="' + (w - padR) + '" y="' + (rY - 4) + '" text-anchor="end" font-size="9" fill="var(--attn)" font-weight="600">' +
              esc(refLabel) +
            '</text>' +
          '</g>';
        }
      }

      // Handle points
      const n = points.length;
      let dataHtml = '';
      const dotCoords = [];

      if (n === 1) {
        const singleY = getY(points[0]);
        const singleX = padL + plotW / 2;
        dotCoords.push({ x: singleX, y: singleY, val: points[0], idx: 0 });
        dataHtml += '<circle cx="' + singleX + '" cy="' + singleY + '" r="5" fill="' + toneColor + '" stroke="var(--surface)" stroke-width="2"/>';
      } else {
        const pts = points.map((p, i) => {
          const x = padL + (i / (n - 1)) * plotW;
          const y = getY(p);
          dotCoords.push({ x, y, val: p, idx: i });
          return x.toFixed(1) + ',' + y.toFixed(1);
        });

        // Area fill
        const firstX = padL.toFixed(1);
        const lastX = (padL + plotW).toFixed(1);
        const baseY = getY(yMin).toFixed(1);
        const areaPoints = pts.join(' ') + ' ' + lastX + ',' + baseY + ' ' + firstX + ',' + baseY;

        dataHtml += '<polygon points="' + areaPoints + '" fill="' + toneColor + '" fill-opacity="0.10"/>' +
          '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + toneColor + '" stroke-width="2.5"' +
            ' stroke-linecap="round" stroke-linejoin="round"/>';
      }

      // Dots with hover titles
      const dotsHtml = dotCoords.map(d => {
        const labelText = options.labels && options.labels[d.idx] ? options.labels[d.idx] : ('Quiz #' + (d.idx + 1));
        const valText = Math.round(Number(d.val) || 0) + '%';
        return '<circle cx="' + d.x.toFixed(1) + '" cy="' + d.y.toFixed(1) + '" r="4" fill="' + toneColor + '" stroke="var(--surface)" stroke-width="2">' +
          '<title>' + esc(labelText) + ': ' + valText + '</title>' +
        '</circle>';
      }).join('');

      // X-axis label row
      let xLabelsHtml = '';
      if (options.labels && Array.isArray(options.labels) && options.labels.length > 0) {
        const step = n > 8 ? Math.ceil(n / 6) : 1;
        xLabelsHtml = '<g class="ch-x-labels" font-size="9" fill="var(--ink-3)" font-family="var(--font-ui)" text-anchor="middle">';
        dotCoords.forEach((d, i) => {
          if (i === 0 || i === n - 1 || i % step === 0) {
            xLabelsHtml += '<text x="' + d.x.toFixed(1) + '" y="' + (h - 6) + '">' + esc(options.labels[i]) + '</text>';
          }
        });
        xLabelsHtml += '</g>';
      }

      return '<div class="ch-line" role="img" aria-label="Performance trend over time">' +
        '<svg class="ch-line-svg" width="100%" height="100%" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
          gridHtml +
          refHtml +
          dataHtml +
          dotsHtml +
          xLabelsHtml +
        '</svg>' +
      '</div>';
    },

    /* ── 4. Stacked Segmented Distribution Bar ───────────────── */
    stacked(parts, options = {}) {
      if (!Array.isArray(parts) || parts.length === 0) {
        return '<div class="ch-empty"><p class="small muted" style="margin:0">No distribution data</p></div>';
      }

      const sum = parts.reduce((acc, p) => acc + (Number(p.value) || 0), 0);
      const total = typeof options.total === 'number' && options.total > 0 ? options.total : Math.max(1, sum);

      const barHeight = typeof options.height === 'number' ? options.height : (options.compact ? 6 : 14);
      const segments = parts.map(p => {
        const val = Number(p.value) || 0;
        const pct = (val / total) * 100;
        if (pct <= 0) return '';
        const color = p.color || resolveTone(p.tone, TONES.muted);
        const titleText = esc(p.label) + ': ' + val + ' (' + Math.round(pct) + '%)';
        return '<span class="ch-stacked-seg" style="width:' + pct.toFixed(2) + '%;background:' + color + ';" title="' + titleText + '"></span>';
      }).join('');

      const showLegend = options.legend !== false && !options.compact;
      const legend = showLegend ? parts.map(p => {
        const val = Number(p.value) || 0;
        const color = p.color || resolveTone(p.tone, TONES.muted);
        return '<span class="ch-legend-item">' +
          '<span class="ch-legend-dot" style="background:' + color + '"></span>' +
          '<span class="ch-legend-label">' + esc(p.label) + '</span>' +
          '<strong class="ch-legend-val">' + val + '</strong>' +
        '</span>';
      }).join('') : '';

      return '<div class="ch-stacked ch-stacked-wrap" role="img" aria-label="Segmented distribution">' +
        '<div class="ch-stacked-bar" style="height:' + barHeight + 'px">' + (segments || '<span class="ch-stacked-seg" style="width:100%;background:var(--line-2);"></span>') + '</div>' +
        (showLegend ? '<div class="ch-legend">' + legend + '</div>' : '') +
      '</div>';
    },

    /* ── 5. Compact Inline Sparkline ─────────────────────────── */
    spark(values, options = {}) {
      if (!Array.isArray(values) || values.length === 0) {
        return '<svg class="ch-spark" width="70" height="20" viewBox="0 0 70 20" aria-hidden="true">' +
          '<line x1="2" y1="10" x2="68" y2="10" stroke="var(--ink-4)" stroke-dasharray="2 2" stroke-width="1.5"/>' +
        '</svg>';
      }

      const w = 70;
      const h = 20;
      const pad = 3;
      const toneColor = resolveTone(options.tone, TONES.student);

      const nums = values.map(v => Number(v) || 0);
      const min = Math.min(...nums);
      const max = Math.max(...nums);
      const range = max === min ? 1 : (max - min);

      let ptsHtml = '';
      if (nums.length === 1) {
        ptsHtml = '<circle cx="35" cy="10" r="3" fill="' + toneColor + '"/>';
      } else {
        const coords = nums.map((v, i) => {
          const x = pad + (i / (nums.length - 1)) * (w - 2 * pad);
          const y = pad + (h - 2 * pad) - ((v - min) / range) * (h - 2 * pad);
          return x.toFixed(1) + ',' + y.toFixed(1);
        });
        const lastX = (pad + (w - 2 * pad)).toFixed(1);
        const lastY = (pad + (h - 2 * pad) - ((nums[nums.length - 1] - min) / range) * (h - 2 * pad)).toFixed(1);

        ptsHtml = '<polyline points="' + coords.join(' ') + '" fill="none" stroke="' + toneColor + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
          '<circle cx="' + lastX + '" cy="' + lastY + '" r="2.5" fill="' + toneColor + '"/>';
      }

      const titleText = 'Recent values: ' + nums.join(', ');
      return '<svg class="ch-spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(titleText) + '">' +
        '<title>' + esc(titleText) + '</title>' +
        ptsHtml +
      '</svg>';
    },

    /* ── 6. Stat Card with Integrated Visualization ──────────── */
    statCard(config = {}) {
      const val = config.value !== undefined ? esc(config.value) : '0';
      const unit = config.unit ? '<span class="ch-stat-unit">' + esc(config.unit) + '</span>' : '';
      const label = config.label ? '<div class="stat-label">' + esc(config.label) + '</div>' : '';
      const sub = config.sub ? '<div class="stat-sub">' + esc(config.sub) + '</div>' : '';
      const chartHtml = config.chart ? '<div class="ch-stat-chart">' + config.chart + '</div>' : '';
      const toneClass = config.tone ? ' ch-tone-' + esc(config.tone) : '';

      return '<div class="stat ch-stat' + toneClass + '">' +
        '<div class="ch-stat-top">' +
          '<div>' +
            '<div class="stat-value ch-stat-val">' + val + unit + '</div>' +
            label +
          '</div>' +
          chartHtml +
        '</div>' +
        sub +
      '</div>';
    }
  };

  return EGCharts;
});
