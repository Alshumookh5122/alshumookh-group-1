/* ═══════════════════════════════════════════════════════════════════
   ALSHUMOOKH GLOBAL — Shared Dashboard Utilities
   Used by all admin pages + client pages
   ═══════════════════════════════════════════════════════════════════ */

// ── Active nav link highlight ─────────────────────────────────────
(function() {
  const path = location.pathname;
  document.querySelectorAll('.sidebar nav a').forEach(a => {
    const href = a.getAttribute('href');
    if (!href) return;
    if (href === path || (href !== '/' && path.startsWith(href))) {
      a.classList.add('active');
    }
  });
})();

// ── API helpers ───────────────────────────────────────────────────
const ADMIN_KEY_STORE = 'als_admin_key';
const CLIENT_KEY_STORE = 'als_client_key';

function getAdminKey() { return sessionStorage.getItem(ADMIN_KEY_STORE) || localStorage.getItem(ADMIN_KEY_STORE) || ''; }
function getClientKey() { return sessionStorage.getItem(CLIENT_KEY_STORE) || localStorage.getItem(CLIENT_KEY_STORE) || ''; }

function adminHeaders(extra = {}) {
  return { 'Content-Type': 'application/json', 'X-Admin-API-Key': getAdminKey(), ...extra };
}
function clientHeaders(extra = {}) {
  return { 'Content-Type': 'application/json', 'X-Api-Key': getClientKey(), ...extra };
}

async function apiFetch(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const d = await r.json(); msg = d.detail || d.message || msg; } catch(_) {}
    throw new Error(msg);
  }
  return r.json();
}

// ── Toast notification ────────────────────────────────────────────
function showToast(msg, type = 'info') {
  let t = document.getElementById('_als_toast');
  if (!t) {
    t = document.createElement('div');
    t.id = '_als_toast';
    t.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s;pointer-events:none;';
    document.body.appendChild(t);
  }
  const colors = { info:'#1d4ed8', ok:'#059669', error:'#dc2626', warn:'#d97706' };
  t.style.background = colors[type] || colors.info;
  t.style.color = '#fff';
  t.style.opacity = '1';
  t.textContent = msg;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.opacity = '0'; }, 3500);
}

// ── Confirm dialog ────────────────────────────────────────────────
function askConfirm(msg) { return confirm(msg); }

// ── Format helpers ────────────────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('ar-SA', { dateStyle:'short', timeStyle:'short' });
}
function fmtNum(n, dec = 2) {
  const v = parseFloat(n);
  return isNaN(v) ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function badge(status) {
  const map = {
    COMPLETED: '#10b981', APPROVED: '#10b981', VERIFIED: '#10b981', RECONCILED: '#10b981',
    PENDING: '#f59e0b', QUEUED: '#f59e0b', AWAITING_APPROVAL: '#f59e0b', FX_FETCHED: '#f59e0b',
    FAILED: '#ef4444', CANCELLED: '#ef4444', REJECTED: '#ef4444',
    BROADCASTING: '#8b5cf6', PROCESSING: '#8b5cf6', CONVERTING: '#8b5cf6', SENDING: '#8b5cf6',
    CREATED: '#6b7280', RECEIVED: '#6b7280', PARSED: '#6b7280',
  };
  const c = map[(status||'').toUpperCase()] || '#6b7280';
  return `<span style="display:inline-block;padding:2px 8px;border-radius:20px;background:${c}22;color:${c};border:1px solid ${c}44;font-size:11px;font-weight:700;">${status||'—'}</span>`;
}

// ── Table builder ─────────────────────────────────────────────────
function buildTable(cols, rows, opts = {}) {
  if (!rows || rows.length === 0) {
    return `<div style="text-align:center;padding:32px;color:var(--muted);">لا توجد بيانات</div>`;
  }
  const th = cols.map(c => `<th>${c.label}</th>`).join('');
  const tbody = rows.map(row => {
    const tds = cols.map(c => `<td>${c.render ? c.render(row) : (row[c.key] ?? '—')}</td>`).join('');
    return `<tr${opts.onRowClick ? ` style="cursor:pointer;" onclick="${opts.onRowClick}(this,'${row.id||''}')"` : ''}>${tds}</tr>`;
  }).join('');
  return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tbody}</tbody></table></div>`;
}

// ── Copy to clipboard ─────────────────────────────────────────────
function copyText(text) {
  navigator.clipboard.writeText(text).then(() => showToast('تم النسخ ✓', 'ok'));
}
