// Session management
function loadSessions() {
  try { return JSON.parse(localStorage.getItem('ch_sessions') || '[]'); } catch { return []; }
}
function saveSessions(s) { localStorage.setItem('ch_sessions', JSON.stringify(s)); }
function activeSession() { return localStorage.getItem('ch_session_id') || ''; }
function setActive(id) { localStorage.setItem('ch_session_id', id); }

function uuidv4() {
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

// Ensure at least one session on first load
(function init() {
  const sessions = loadSessions();
  if (!sessions.length) {
    const id = uuidv4();
    sessions.push({ id, label: id.slice(0, 8), created_at: Date.now() });
    saveSessions(sessions);
    setActive(id);
  } else if (!activeSession()) {
    setActive(sessions[0].id);
  }
})();

// Snippets
let snippets = [];

async function loadSnippets() {
  try {
    const resp = await fetch('/api/snippets');
    snippets = await resp.json();
  } catch (e) {
    snippets = [];
  }
  renderSnippetTabs();
  if (snippets.length) selectSnippet(snippets[0]);
}

function renderSnippetTabs() {
  const container = document.getElementById('snippet-tabs');
  container.innerHTML = '';
  snippets.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'snippet-tab';
    btn.textContent = s.title;
    btn.title = s.description;
    btn.dataset.id = s.id;
    btn.onclick = () => selectSnippet(s);
    container.appendChild(btn);
  });
}

function selectSnippet(snippet) {
  document.querySelectorAll('.snippet-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.id === snippet.id);
  });
  document.getElementById('code-editor').value = snippet.code;
}

// Session UI
function renderSessions() {
  const sessions = loadSessions();
  const active = activeSession();
  const container = document.getElementById('session-list');
  container.innerHTML = '';
  sessions.forEach(s => {
    const div = document.createElement('div');
    div.className = 'session-item' + (s.id === active ? ' active' : '');
    const label = s.label || s.id.slice(0, 12);
    div.innerHTML =
      `<span class="dot"></span>` +
      `<span>${escHtml(label)}</span>` +
      `<span class="meta" id="smeta-${escAttr(s.id)}"></span>`;
    div.onclick = () => switchSession(s.id);
    container.appendChild(div);
  });
  updateBadge();
  sessions.forEach(s => refreshMeta(s.id, s.id === active));
}

async function refreshMeta(sessionId, isActive) {
  const el = document.getElementById(`smeta-${escAttr(sessionId)}`);
  if (!el) return;
  try {
    const resp = await fetch(`/api/status/${encodeURIComponent(sessionId)}`);
    const data = await resp.json();
    const count = (data.files || []).length;
    el.textContent = count ? `${count} file${count !== 1 ? 's' : ''}` : '';
    if (isActive) renderFiles(data.files || []);
  } catch {}
}

function switchSession(id) {
  setActive(id);
  renderSessions();
  document.getElementById('output-stdout').innerHTML =
    '<span class="empty">Switched session. Run a snippet to see output.</span>';
  renderFiles([]);
}

function addSession(id) {
  id = id.trim();
  if (!id) return;
  const sessions = loadSessions();
  if (sessions.find(s => s.id === id)) { switchSession(id); return; }
  sessions.push({ id, label: id.slice(0, 20), created_at: Date.now() });
  saveSessions(sessions);
  setActive(id);
  renderSessions();
}

// Run code
document.getElementById('run-btn').onclick = async () => {
  const code = document.getElementById('code-editor').value;
  const sessionId = activeSession();
  if (!code.trim()) return;
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.textContent = 'Running…';

  const out = document.getElementById('output-stdout');
  out.innerHTML = '<span class="meta-line">Running…</span>';

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, code }),
    });
    const data = await resp.json();
    out.innerHTML = '';
    const meta = document.createElement('span');
    meta.className = 'meta-line';
    const sessions = loadSessions();
    const s = sessions.find(x => x.id === sessionId);
    const label = s ? (s.label || sessionId.slice(0, 12)) : sessionId.slice(0, 12);
    meta.textContent = `session: ${label}  ·  ${data.duration_ms}ms`;
    out.appendChild(meta);
    if (data.stdout) {
      const span = document.createElement('span');
      span.className = 'out';
      span.textContent = data.stdout;
      out.appendChild(span);
    }
    if (data.stderr) {
      const span = document.createElement('span');
      span.className = 'err';
      span.textContent = data.stderr;
      out.appendChild(span);
    }
    if (!data.stdout && !data.stderr) {
      const span = document.createElement('span');
      span.className = 'empty';
      span.textContent = '(no output)';
      out.appendChild(span);
    }
    renderFiles(data.files || []);
    refreshMeta(sessionId, true);
  } catch (e) {
    out.innerHTML = `<span class="err">Error: ${escHtml(String(e))}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Run';
  }
};

// File list
function renderFiles(files) {
  const el = document.getElementById('files-list');
  if (!files.length) {
    el.innerHTML = '<span style="color:var(--muted);font-size:0.8rem">—</span>';
    return;
  }
  el.innerHTML = files.map(f =>
    `<div class="file-item">📄 ${escHtml(f.name)}<span class="size">${fmtSize(f.size)}</span></div>`
  ).join('');
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}kB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function updateBadge() {
  const id = activeSession();
  const sessions = loadSessions();
  const s = sessions.find(x => x.id === id);
  const label = s ? (s.label || id.slice(0, 12)) : id.slice(0, 12);
  document.getElementById('sandbox-badge').textContent = `sandbox: ${label}`;
}

// New session input/button
document.getElementById('new-session-input').value = uuidv4().slice(0, 8);
document.getElementById('new-session-btn').onclick = () => {
  const val = document.getElementById('new-session-input').value;
  addSession(val);
  document.getElementById('new-session-input').value = uuidv4().slice(0, 8);
};
document.getElementById('new-session-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('new-session-btn').click();
});

// Helpers
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function escAttr(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, '_'); }

// Boot
loadSnippets().then(() => renderSessions());
