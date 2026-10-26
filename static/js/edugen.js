/* =========================================================================
   EduGen - shared frontend helpers
   ========================================================================= */

const EG = {

  /* ── fetch wrapper ──────────────────────────────────────── */
  async api(path, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
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

  sourcesHtml(sources, heading) {
    if (!sources || !sources.length) return '';
    return '<div class="sources"><h4>' + EG.esc(heading || 'Sources this was built from') + '</h4>' +
      sources.map(s =>
        '<div class="source-item"><span class="source-n">' + s.n + '</span>' +
        '<div><strong>' + EG.esc(s.source) + '</strong>' +
        (s.section ? '<div class="muted tiny">' + EG.esc(s.section) + '</div>' : '') +
        '</div><span class="spacer"></span>' +
        '<span class="badge badge-agent tiny">' + (s.score || 0).toFixed(2) + '</span></div>'
      ).join('') + '</div>';
  },

  originBadge(content) {
    const by = content && content.generated_by;
    if (by === 'llm+rag') return '<span class="badge badge-agent badge-dot">Generated from your knowledge base</span>';
    if (by === 'llm')     return '<span class="badge badge-signal badge-dot">AI generated</span>';
    if (by === 'static-bank') return '<span class="badge badge-attn badge-dot">Built-in question bank</span>';
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
   Agent activity console
   Polls /api/logs and streams what the four agents are doing.
   Hide it in production with EDUGEN_SHOW_LOGS=0 in .env.
   ========================================================================= */
const AgentConsole = {
  lastId: 0,
  timer: null,
  count: 0,

  init() {
    const el = document.getElementById('console');
    if (!el) return;

    const collapsed = localStorage.getItem('eg:console') === 'closed';
    if (collapsed) el.classList.add('collapsed');

    document.getElementById('console-head').addEventListener('click', (evt) => {
      if (evt.target.closest('[data-console-action]')) return;
      el.classList.toggle('collapsed');
      localStorage.setItem('eg:console', el.classList.contains('collapsed') ? 'closed' : 'open');
    });

    const hideBtn = document.querySelector('[data-console-action="hide"]');
    if (hideBtn) hideBtn.addEventListener('click', (evt) => {
      evt.stopPropagation();
      el.style.display = 'none';
      const pill = document.getElementById('console-pill');
      if (pill) pill.classList.add('show');
    });

    const pill = document.getElementById('console-pill');
    if (pill) pill.addEventListener('click', () => {
      el.style.display = 'flex';
      pill.classList.remove('show');
    });

    const clearBtn = document.querySelector('[data-console-action="clear"]');
    if (clearBtn) clearBtn.addEventListener('click', async (evt) => {
      evt.stopPropagation();
      await fetch('/api/logs/clear', { method: 'POST' });
      document.getElementById('console-body').innerHTML = '';
      AgentConsole.lastId = 0;
      AgentConsole.count = 0;
      AgentConsole.updateCount();
    });

    this.poll();
    this.timer = setInterval(() => this.poll(), 1600);
  },

  async poll() {
    try {
      const data = await fetch('/api/logs?after=' + this.lastId).then(r => r.json());
      if (data.logs && data.logs.length) this.append(data.logs);
    } catch (_) { /* polling is best-effort */ }
  },

  append(logs) {
    const body = document.getElementById('console-body');
    if (!body) return;
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 60;

    logs.forEach(log => {
      this.lastId = Math.max(this.lastId, log.id);
      this.count += 1;
      const line = document.createElement('div');
      line.className = 'log-line ' + (log.type || 'info');
      line.innerHTML =
        '<span class="log-time">' + EG.esc(log.timestamp) + '</span>' +
        '<span class="log-agent ' + EG.esc(log.slug || 'system') + '">' + EG.esc(log.agent) + '</span>' +
        '<span class="log-msg">' + EG.esc(log.message) + '</span>';
      if (log.payload && Object.keys(log.payload).length) {
        line.title = JSON.stringify(log.payload, null, 2);
      }
      body.appendChild(line);
    });

    while (body.children.length > 200) body.removeChild(body.firstChild);
    if (nearBottom) body.scrollTop = body.scrollHeight;
    this.updateCount();
  },

  updateCount() {
    const el = document.getElementById('console-count');
    if (el) el.textContent = this.count + ' events';
  }
};


/* ── nav toggle ─────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  AgentConsole.init();
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav');
  if (toggle && nav) toggle.addEventListener('click', () => nav.classList.toggle('open'));

  const logoutBtn = document.querySelector('[data-action="logout"]');
  if (logoutBtn) logoutBtn.addEventListener('click', async (evt) => {
    evt.preventDefault();
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/';
  });
});
