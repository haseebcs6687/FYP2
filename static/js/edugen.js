/* =========================================================================
   EduGen - shared frontend helpers
   ========================================================================= */

const EG = {

  /* ── fetch wrapper ──────────────────────────────────────── */
  async api(path, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    const method = (opts.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) {
        opts.headers['X-CSRF-Token'] = meta.content;
      }
    }
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }

    if (res.status === 401) {
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
      throw new Error('unauthenticated');
    }
    if (!res.ok) {
      throw new Error((data && (data.error || data.detail)) || ('Request failed (' + res.status + ')'));
    }
    return data;
  },

  get(path)         { return EG.api(path); },
  post(path, body)  { return EG.api(path, { method: 'POST', body: body || {} }); },

  /* ── DOM ────────────────────────────────────────────────── */
  $(sel, root)  { return (root || document).querySelector(sel); },
  $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); },

  esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },

  /* Render text that may contain ``` fenced code or inline `code`. */
  richText(text) {
    if (!text) return '';
    const parts = String(text).split(/```(?:java|Java)?\n?/);
    let out = '';
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        out += '<pre class="code"><code>' + EG.esc(part.replace(/\n$/, '')) + '</code></pre>';
      } else {
        const paragraphs = part.split(/\n{2,}/).filter(p => p.trim());
        out += paragraphs.map(p =>
          '<p>' + EG.esc(p.trim()).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\n/g, '<br>') + '</p>'
        ).join('');
      }
    });
    return out;
  },

  questionHtml(text) {
    if (!text) return '';
    const parts = String(text).split(/```(?:java|Java)?\n?/);
    return parts.map((part, i) =>
      i % 2 === 1
        ? '<pre class="code"><code>' + EG.esc(part.replace(/\n$/, '')) + '</code></pre>'
        : EG.esc(part).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\n/g, '<br>')
    ).join('');
  },

  loading(message) {
    return '<div class="loading"><span class="spinner"></span><span>' + EG.esc(message) + '</span></div>';
  },

  errorBox(message, retryLabel) {
    return '<div class="notice notice-crit"><strong>Could not load this.</strong> ' +
      EG.esc(message) + (retryLabel ? ' <button class="btn btn-sm btn-ghost" onclick="location.reload()" style="margin-left:8px">' +
      EG.esc(retryLabel) + '</button>' : '') + '</div>';
  },

  masteryClass(value) {
    if (value === null || value === undefined) return '';
    if (value < 50) return 'weak';
    if (value >= 80) return 'strong';
    return '';
  },

  meter(name, value, detail) {
    return '<div class="meter">' +
      '<div class="meter-head"><span class="meter-name">' + EG.esc(name) + '</span>' +
      '<span class="meter-val">' + (detail ? EG.esc(detail) : Math.round(value) + '%') + '</span></div>' +
      '<div class="meter-track"><div class="meter-fill ' + EG.masteryClass(value) +
      '" style="width:' + Math.max(2, Math.min(100, value)) + '%"></div></div></div>';
  },

  ring(percentage) {
    const r = 46, c = 2 * Math.PI * r;
    const offset = c - (Math.max(0, Math.min(100, percentage)) / 100) * c;
    const colour = percentage >= 80 ? 'var(--good)' : percentage >= 50 ? 'var(--signal)' : 'var(--attn)';
    return '<div class="ring"><svg width="108" height="108">' +
      '<circle cx="54" cy="54" r="' + r + '" fill="none" stroke="var(--line-2)" stroke-width="8"/>' +
      '<circle cx="54" cy="54" r="' + r + '" fill="none" stroke="' + colour + '" stroke-width="8"' +
      ' stroke-linecap="round" stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '"/>' +
      '</svg><div class="ring-label">' + Math.round(percentage) + '%</div></div>';
  },

  cleanPassageTitle(bookTitle, sectionTitle) {
    const ext = '.' + 'pdf';
    let book = (bookTitle || '').replace(new RegExp('\\' + ext + '$', 'i'), '').replace(/[_-]/g, ' ').trim();
    if (!book) book = 'Java Reference';
    let sec = (sectionTitle || '').trim();
    if (sec.toLowerCase().endsWith(ext)) sec = sec.slice(0, -ext.length).trim();
    if (!sec) return book;
    const nonSpace = sec.replace(/\s+/g, '');
    const letters = sec.replace(/[^a-zA-Z]/g, '');
    if (nonSpace.length > 0 && (letters.length / nonSpace.length) < 0.60) return book;
    if (sec.includes('$%') || /&\s*[a-zA-Z]/.test(sec)) return book;
    return book + ', ' + sec;
  },

  sourcesHtml(sources, heading) {
    if (!sources || !sources.length) return '';
    const cleaned = [];
    sources.forEach(s => {
      const b = (typeof s === 'string') ? s : (s.source || s.file || s.book || '');
      const sec = (typeof s === 'object') ? (s.section || s.title || '') : '';
      const line = this.cleanPassageTitle(b, sec);
      if (line && !cleaned.includes(line)) cleaned.push(line);
    });
    if (!cleaned.length) return '';
    return '<div class="small muted" style="margin-top:16px;padding-top:12px;border-top:1px solid var(--line-2)"><strong>Sources:</strong> ' +
      EG.esc(cleaned.join('; ')) + '</div>';
  },

  originBadge(content) {
    const by = content && content.generated_by;
    if (by === 'llm+rag') return '<span class="badge badge-good badge-dot">Curriculum verified</span>';
    if (by === 'llm')     return '<span class="badge badge-signal badge-dot">AI generated</span>';
    if (by === 'static-bank') return '<span class="badge badge-attn badge-dot">Question bank</span>';
    if (by === 'local-note')  return '<span class="badge badge-attn badge-dot">Offline notes</span>';
    return '';
  },

  timeAgo(timestamp) {
    if (!timestamp) return '';
    const then = new Date(String(timestamp).replace(' ', 'T'));
    if (isNaN(then)) return timestamp;
    const mins = Math.floor((Date.now() - then.getTime()) / 60000);
    if (mins < 1)    return 'just now';
    if (mins < 60)   return mins + ' min ago';
    const hours = Math.floor(mins / 60);
    if (hours < 24)  return hours + ' hr ago';
    const days = Math.floor(hours / 24);
    if (days < 30)   return days + ' day' + (days > 1 ? 's' : '') + ' ago';
    return then.toLocaleDateString();
  },

  store: {
    set(key, value) { try { sessionStorage.setItem('eg:' + key, JSON.stringify(value)); } catch (_) {} },
    get(key) {
      try { const v = sessionStorage.getItem('eg:' + key); return v ? JSON.parse(v) : null; }
      catch (_) { return null; }
    },
    clear(key) { try { sessionStorage.removeItem('eg:' + key); } catch (_) {} }
  }
};


/* =========================================================================
   Evaluator Activity Window Controller
   ========================================================================= */
const EvaluatorWindow = {
  lastId: 0,
  pollTimer: null,
  isPolling: false,
  totalEvents: 0,
  activeTab: 'live',
  state: 'minimized', // 'open' | 'minimized'

  init() {
    const pill = document.getElementById('evaluator-pill');
    const panel = document.getElementById('evaluator-panel');
    if (!pill || !panel) return;

    try {
      const savedState = localStorage.getItem('eg:eval_state');
      if (savedState === 'open') {
        this.state = 'open';
      } else {
        this.state = 'minimized';
        try {
          localStorage.setItem('eg:eval_state', 'minimized');
        } catch (_) {}
      }
      const savedTab = localStorage.getItem('eg:eval_tab');
      if (savedTab) this.activeTab = savedTab;
    } catch (_) {
      this.state = 'minimized';
    }

    this.applyState();

    pill.addEventListener('click', () => {
      this.setState('open');
      this.switchTab(this.activeTab);
    });

    const minBtn = document.getElementById('eval-minimize-btn');
    if (minBtn) {
      minBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.setState('minimized');
      });
    }

    document.querySelectorAll('.eval-tab').forEach(tabBtn => {
      tabBtn.addEventListener('click', () => {
        const tab = tabBtn.dataset.tab;
        this.switchTab(tab);
      });
    });

    const clearBtn = document.getElementById('eval-clear-events');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const list = document.getElementById('eval-live-list');
        if (list) list.innerHTML = '';
        this.totalEvents = 0;
        this.updateBadge();
      });
    }

    this.startPolling();
  },

  setState(st) {
    if (st !== 'open') {
      st = 'minimized';
    }
    this.state = st;
    try {
      localStorage.setItem('eg:eval_state', st);
    } catch (_) {}
    this.applyState();
    if (!this.pollTimer) this.startPolling();
  },

  applyState() {
    const pill = document.getElementById('evaluator-pill');
    const panel = document.getElementById('evaluator-panel');
    if (!pill || !panel) return;

    if (this.state === 'open') {
      panel.style.display = 'flex';
      pill.style.display = 'none';
      document.body.classList.add('has-evaluator');
      this.switchTab(this.activeTab);
    } else {
      panel.style.display = 'none';
      pill.style.display = 'flex';
      document.body.classList.add('has-evaluator');
    }
  },

  startPolling() {
    if (this.pollTimer) return;
    this.pollEvents();
    this.pollTimer = setInterval(() => this.pollEvents(), 2000);
  },

  async pollEvents() {
    if (this.isPolling) return;
    this.isPolling = true;
    try {
      const data = await EG.get('/api/events?since_id=' + this.lastId);
      if (data && data.events && data.events.length) {
        this.lastId = data.last_id || this.lastId;
        this.appendEvents(data.events);
      }
    } catch (_) {
      // Polling is best-effort
    } finally {
      this.isPolling = false;
    }
  },

  appendEvents(events) {
    const container = document.getElementById('eval-live-list');
    this.totalEvents += events.length;
    this.updateBadge();

    if (container) {
      events.forEach(ev => {
        const row = document.createElement('div');
        row.className = 'eval-event-row';
        const tStr = ev.time ? (ev.time.includes('T') ? ev.time.split('T')[1].slice(0, 8) : ev.time.slice(0, 8)) : '--:--:--';
        const agentName = ev.agent || 'System';
        const agentClass = agentName.split(' ')[0];
        const msStr = ev.ms ? ev.ms + 'ms' : '';

        row.innerHTML =
          '<span class="eval-event-time">' + EG.esc(tStr) + '</span>' +
          '<span><span class="eval-event-agent ' + EG.esc(agentClass) + '">' + EG.esc(agentName) + '</span></span>' +
          '<span class="eval-event-msg">' + EG.esc(ev.message || ev.action || '') + '</span>' +
          '<span class="eval-event-ms">' + EG.esc(msStr) + '</span>';

        if (ev.output || ev.input) {
          row.title = JSON.stringify({ input: ev.input, output: ev.output }, null, 2);
        }
        container.appendChild(row);
      });

      while (container.children.length > 250) {
        container.removeChild(container.firstChild);
      }
      container.scrollTop = container.scrollHeight;
    }

    const summary = document.getElementById('eval-live-summary');
    if (summary) summary.textContent = this.totalEvents + ' event(s) recorded';
  },

  updateBadge() {
    const badge = document.getElementById('eval-event-count');
    if (badge) badge.textContent = this.totalEvents;
  },

  switchTab(tab) {
    this.activeTab = tab;
    try {
      localStorage.setItem('eg:eval_tab', tab);
    } catch (_) {}

    document.querySelectorAll('.eval-tab').forEach(b => {
      b.classList.toggle('on', b.dataset.tab === tab);
    });
    document.querySelectorAll('.eval-pane').forEach(p => {
      p.classList.toggle('on', p.id === 'eval-pane-' + tab);
    });

    if (tab === 'runs') this.loadRuns();
    else if (tab === 'rag') this.loadRAG();
    else if (tab === 'decisions') this.loadDecisions();
    else if (tab === 'quiz_build') this.loadQuizBuild();
    else if (tab === 'system') this.loadSystem();
  },

  async loadRuns() {
    const el = document.getElementById('eval-runs-list');
    if (!el) return;
    try {
      const data = await EG.get('/api/runs');
      const runs = data.runs || [];
      if (!runs.length) {
        el.innerHTML = '<p class="small muted">No pipeline runs recorded yet.</p>';
        return;
      }
      el.innerHTML = runs.map(r =>
        '<div class="eval-card">' +
          '<div class="eval-card-header">' +
            '<span>Run #' + r.id + ' &middot; ' + EG.esc(r.trigger || 'pipeline') + '</span>' +
            '<span class="badge ' + (r.state === 'completed' ? 'badge-good' : 'badge-signal') + '">' + EG.esc(r.state) + '</span>' +
          '</div>' +
          '<div class="small muted">Started: ' + EG.esc(r.started_at) + (r.duration_ms ? ' (' + r.duration_ms + 'ms)' : '') + '</div>' +
        '</div>'
      ).join('');
    } catch (e) {
      el.innerHTML = '<p class="small muted">Error loading runs: ' + EG.esc(e.message) + '</p>';
    }
  },

  async loadRAG() {
    const el = document.getElementById('eval-rag-list');
    if (!el) return;
    try {
      const data = await EG.get('/api/evaluator/rag');
      const rets = data.retrievals || [];
      if (!rets.length) {
        el.innerHTML = '<p class="small muted">No RAG retrieval events recorded yet.</p>';
        return;
      }
      el.innerHTML = rets.map(r => {
        const rows = (r.top_k_passages || []).map((p, i) =>
          '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><strong>' + EG.esc(p.source_file) + '</strong><br><span class="muted tiny">' + EG.esc(p.cleaned_section) + '</span></td>' +
            '<td>' + (p.cosine !== undefined ? p.cosine.toFixed(2) : '--') + '</td>' +
            '<td>' + (p.lexical !== undefined ? p.lexical.toFixed(2) : '--') + '</td>' +
            '<td>' + (p.tag_score !== undefined ? p.tag_score.toFixed(2) : '--') + '</td>' +
            '<td><strong>' + (p.final_score !== undefined ? p.final_score.toFixed(2) : '--') + '</strong></td>' +
          '</tr>'
        ).join('');

        return '<div class="eval-card">' +
          '<div class="eval-card-header">' +
            '<span>Query: "' + EG.esc(r.query) + '"</span>' +
            '<span class="badge badge-signal">' + EG.esc(r.concept_filter || 'all') + '</span>' +
          '</div>' +
          '<table>' +
            '<thead><tr><th>#</th><th>Passage</th><th>Cosine</th><th>Lexical</th><th>Tag</th><th>Final</th></tr></thead>' +
            '<tbody>' + rows + '</tbody>' +
          '</table>' +
        '</div>';
      }).join('');
    } catch (e) {
      el.innerHTML = '<p class="small muted">Error loading RAG telemetry: ' + EG.esc(e.message) + '</p>';
    }
  },

  async loadDecisions() {
    const el = document.getElementById('eval-decisions-list');
    if (!el) return;
    try {
      const d = await EG.get('/api/evaluator/decisions');
      const checks = Object.entries(d.coverage_check || {}).map(([k, v]) =>
        '<span class="badge badge-good" style="margin-right:4px">' + EG.esc(k) + ': ' + EG.esc(v) + '</span>'
      ).join('');

      const steps = (d.plan_steps || []).map(s =>
        '<li><code>' + EG.esc(s.concept) + '</code> (' + EG.esc(s.kind) + ') &mdash; <span class="badge">' + EG.esc(s.status) + '</span></li>'
      ).join('');

      el.innerHTML =
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Rule Fired</span><span class="badge badge-signal">' + EG.esc(d.rule_fired) + '</span></div>' +
          '<div class="small" style="margin-bottom:6px"><strong>Concepts considered:</strong> ' + EG.esc((d.concepts_considered || []).join(', ') || 'none') + '</div>' +
          '<div class="small" style="margin-bottom:6px"><strong>Evidence:</strong> <pre style="margin:4px 0;background:#0F172A;padding:6px;border-radius:4px">' + EG.esc(JSON.stringify(d.evidence || {}, null, 2)) + '</pre></div>' +
          '<div class="small" style="margin-top:8px"><strong>Coverage &amp; Graph Checks:</strong><div style="margin-top:4px">' + (checks || 'None') + '</div></div>' +
        '</div>' +
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Active Plan Steps (' + (d.plan_steps || []).length + ')</span></div>' +
          '<ol class="small" style="margin:0;padding-left:18px">' + (steps || '<li>No active steps</li>') + '</ol>' +
        '</div>';
    } catch (e) {
      el.innerHTML = '<p class="small muted">Error loading decisions: ' + EG.esc(e.message) + '</p>';
    }
  },

  async loadQuizBuild() {
    const el = document.getElementById('eval-quiz-build-list');
    if (!el) return;
    try {
      const qb = await EG.get('/api/evaluator/quiz-build');
      const qRows = (qb.questions || []).map((q, i) =>
        '<tr>' +
          '<td>' + (i + 1) + '</td>' +
          '<td>' + EG.esc(q.concept || '--') + '</td>' +
          '<td>' + EG.esc(q.difficulty || '--') + '</td>' +
          '<td><span class="badge ' + (q.served_from === 'pool' ? 'badge-good' : 'badge-signal') + '">' + EG.esc(q.served_from) + '</span></td>' +
        '</tr>'
      ).join('');

      const biasRej = qb.bias_gate_rejections || {};
      const gateRej = qb.gate_rejections || {};

      el.innerHTML =
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Served Distribution</span>' +
            '<span>Pool: ' + qb.served_from_pool + ' | Live: ' + qb.generated_live + '</span>' +
          '</div>' +
          '<table><thead><tr><th>#</th><th>Concept</th><th>Difficulty</th><th>Served From</th></tr></thead><tbody>' +
            (qRows || '<tr><td colspan="4" class="muted">No questions built yet</td></tr>') +
          '</tbody></table>' +
        '</div>' +
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Gate &amp; Bias Rejections</span></div>' +
          '<div class="small"><strong>Bias Gate:</strong> Length disparity: ' + (biasRej.correct_option_too_long || 0) +
            ' | Absolute word: ' + (biasRej.absolute_word_bias || 0) + '</div>' +
          '<div class="small" style="margin-top:6px"><strong>Structural Rejections:</strong> ' +
            Object.entries(gateRej).map(([k, v]) => EG.esc(k) + ': ' + v).join(', ') + '</div>' +
          '<div class="small" style="margin-top:6px"><strong>Verifier Result:</strong> ' +
            EG.esc(JSON.stringify(qb.verifier_result || {})) + '</div>' +
        '</div>';
    } catch (e) {
      el.innerHTML = '<p class="small muted">Error loading quiz build telemetry: ' + EG.esc(e.message) + '</p>';
    }
  },

  async loadSystem() {
    const el = document.getElementById('eval-system-info');
    if (!el) return;
    try {
      const st = await EG.get('/api/evaluator/system');
      const agList = Object.entries(st.agent_status || {}).map(([k, v]) =>
        '<tr><td>' + EG.esc(k) + '</td><td><span class="badge ' + (v === 'active' ? 'badge-good' : 'badge-attn') + '">' + EG.esc(v) + '</span></td></tr>'
      ).join('');

      const tb = st.token_budget || {};

      el.innerHTML =
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>System Diagnostics</span></div>' +
          '<div class="small"><strong>KB Chunks:</strong> ' + st.kb_size + '</div>' +
          '<div class="small"><strong>Embedder:</strong> <code>' + EG.esc(st.embedder) + '</code></div>' +
          '<div class="small"><strong>Model:</strong> <code>' + EG.esc(st.model) + '</code></div>' +
          '<div class="small"><strong>Automation Ratio:</strong> <strong>' + (st.automation_ratio !== undefined ? (st.automation_ratio * 100).toFixed(1) + '%' : '--') + '</strong></div>' +
        '</div>' +
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Agent Status</span></div>' +
          '<table><thead><tr><th>Agent</th><th>Status</th></tr></thead><tbody>' + agList + '</tbody></table>' +
        '</div>' +
        '<div class="eval-card">' +
          '<div class="eval-card-header"><span>Token Budget</span></div>' +
          '<div class="small">Daily Limit: ' + (tb.daily_limit || 0).toLocaleString() + '</div>' +
          '<div class="small">Used Today: ' + (tb.used || 0).toLocaleString() + '</div>' +
          '<div class="small">Remaining: ' + (tb.remaining || 0).toLocaleString() + '</div>' +
        '</div>';
    } catch (e) {
      el.innerHTML = '<p class="small muted">Error loading system info: ' + EG.esc(e.message) + '</p>';
    }
  }
};


/* ── nav toggle & initialization ────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  EvaluatorWindow.init();
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav');
  if (toggle && nav) toggle.addEventListener('click', () => nav.classList.toggle('open'));

  const logoutBtn = document.querySelector('[data-action="logout"]');
  if (logoutBtn) logoutBtn.addEventListener('click', async (evt) => {
    evt.preventDefault();
    try {
      await EG.post('/api/auth/logout');
    } catch (_) {}
    window.location.href = '/';
  });
});
