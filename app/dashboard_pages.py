"""
ALSHUMOOKH GLOBAL — Admin Dashboard (Multi-Page, Complete Rebuild)

Endpoints served:
  GET /dashboard                → Overview
  GET /dashboard/orders         → Payment Orders
  GET /dashboard/payloads       → Settlement Payloads
  GET /dashboard/transfers      → Outbound Transfers
  GET /dashboard/tokenization   → M1 Tokenization
  GET /dashboard/monitoring     → Live Monitoring
  GET /dashboard/payments       → Payments
  GET /dashboard/alchemy        → Alchemy Events
  GET /dashboard/counterparties → API Clients / Counterparties
  GET /dashboard/security       → Security Events
  GET /dashboard/documents      → Documents
  GET /dashboard/logs           → Audit Logs
  GET /dashboard/overview       → redirect → /dashboard
  POST /dashboard/logout        → clear session cookie
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette import status as http_status

from app.auth import ADMIN_SESSION_COOKIE, is_admin_request_authenticated

router = APIRouter(tags=["dashboard-pages"])

# ═══════════════════════════════════════════════════════════════════
# SHARED HTML COMPONENTS
# ═══════════════════════════════════════════════════════════════════

_SIDEBAR_LINKS = [
    ("/dashboard",               "🏠", "نظرة عامة"),
    ("/dashboard/orders",        "📋", "الطلبات"),
    ("/dashboard/payloads",      "📥", "Settlement Payloads"),
    ("/dashboard/transfers",     "🚀", "Outbound Transfers"),
    ("/dashboard/tokenization",  "🔄", "M1 Tokenization"),
    ("/dashboard/monitoring",    "📊", "Live Monitoring"),
    ("/dashboard/payments",      "💳", "المدفوعات"),
    ("/dashboard/alchemy",       "⛓", "Alchemy Events"),
    ("/dashboard/counterparties","🔑", "Counterparties"),
    ("/dashboard/security",      "🛡", "Security"),
    ("/dashboard/documents",     "📄", "Documents"),
    ("/dashboard/logs",          "📝", "Audit Logs"),
    ("/swift",                   "⬡", "SWIFT Terminal"),
]


def _sidebar(active_path: str) -> str:
    links = ""
    for href, icon, label in _SIDEBAR_LINKS:
        is_active = (href == active_path)
        cls = ' class="active"' if is_active else ""
        links += f'<a href="{href}"{cls}>{icon} {label}</a>\n'

    return f"""
<aside class="sidebar">
  <div class="brand-panel">
    <img class="brand-logo" src="/static/company-logo.png" alt="Logo"
         onerror="this.style.display='none';this.nextElementSibling.style.display='grid';">
    <div class="brand-mark">SG</div>
    <div>
      <p class="eyebrow">ALSHUMOOKH GLOBAL</p>
      <h1>Banking Finance &amp; Credit</h1>
    </div>
  </div>
  <nav>{links}</nav>
  <div class="sidebar-foot">
    <span style="font-weight:700;color:var(--gold);">Settlement Wallets</span>
    <div style="margin-top:6px;">
      <strong style="color:#a78bfa;font-size:11px;">Ethereum (ERC-20)</strong><br>
      <code style="font-size:10px;color:var(--muted);">0xBD682...4d939</code>
    </div>
    <div style="margin-top:4px;">
      <strong style="color:#34d399;font-size:11px;">TRON (TRC-20)</strong><br>
      <code style="font-size:10px;color:var(--muted);">TLARV2...EEqjTn</code>
    </div>
    <a href="/dashboard/logout"
       onclick="event.preventDefault();fetch('/dashboard/logout',{{method:'POST'}}).then(()=>{{location.href='/login?type=admin';}})"
       style="margin-top:12px;display:block;text-align:center;padding:7px;
              background:rgba(220,38,38,.15);border:1px solid rgba(220,38,38,.3);
              border-radius:6px;color:#f87171;font-size:11px;font-weight:700;text-decoration:none;">
      &#9211; تسجيل الخروج
    </a>
  </div>
</aside>
"""


def _topbar(title: str, subtitle: str = "Admin Panel") -> str:
    return f"""
<section class="topbar">
  <div>
    <p class="eyebrow">{subtitle}</p>
    <h2 style="margin:0;font-size:18px;font-weight:800;color:var(--gold);">{title}</h2>
  </div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
    <input id="_top_ak_inp" type="password" placeholder="Admin API Key"
           style="width:220px;max-width:38vw;background:var(--panel-solid);border:1px solid var(--line-strong);
                  border-radius:8px;padding:7px 10px;color:var(--ink);font-size:11px;outline:none;" />
    <button class="btn btn-primary" onclick="saveTopAK()" style="padding:7px 10px;font-size:11px;">حفظ المفتاح</button>
    <span id="_liveTime" style="color:var(--muted);font-size:12px;"></span>
    <span style="width:8px;height:8px;border-radius:50%;background:#34d399;
                 display:inline-block;box-shadow:0 0 6px #34d39988;"></span>
    <span style="color:#34d399;font-size:12px;font-weight:700;">Live</span>
  </div>
</section>
<script>
(function(){{
  function tick(){{
    var el=document.getElementById('_liveTime');
    if(el) el.textContent=new Date().toLocaleTimeString('ar-SA');
  }}
  tick(); setInterval(tick,1000);
}})();
</script>
"""


_BASE_CSS = """
.page-body {{ display:grid; gap:14px; }}
.stat-grid  {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }}
.stat-card  {{ background:var(--glass); border:1px solid var(--glass-border);
               border-radius:12px; padding:16px 14px; }}
.stat-card .label {{ font-size:11px; color:var(--muted); margin-bottom:6px; }}
.stat-card .value {{ font-size:22px; font-weight:800; color:var(--ink); }}
.stat-card .sub   {{ font-size:11px; color:var(--muted); margin-top:4px; }}
.panel      {{ background:var(--glass); border:1px solid var(--glass-border);
               border-radius:12px; overflow:hidden; }}
.panel-head {{ padding:12px 16px; border-bottom:1px solid var(--line);
               display:flex; align-items:center; justify-content:space-between; }}
.panel-head h3 {{ margin:0; font-size:13px; font-weight:700; color:var(--ink); }}
.filter-bar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
.table-wrap {{ overflow-x:auto; }}
table  {{ width:100%; border-collapse:collapse; font-size:12px; }}
thead  {{ background:rgba(255,255,255,0.04); }}
th     {{ padding:10px 12px; text-align:right; color:var(--muted);
          font-weight:700; font-size:11px; border-bottom:1px solid var(--line); white-space:nowrap; }}
td     {{ padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:middle; color:var(--ink); }}
tr:hover td {{ background:rgba(255,255,255,0.03); }}
.btn   {{ display:inline-flex; align-items:center; gap:5px; padding:7px 14px;
          border-radius:8px; font-size:12px; font-weight:700; cursor:pointer;
          border:1px solid var(--glass-border); transition:all .2s; white-space:nowrap; }}
.btn-primary {{ background:linear-gradient(135deg,#2563eb,#1d4ed8); color:#fff; border-color:transparent; }}
.btn-primary:hover {{ background:linear-gradient(135deg,#1d4ed8,#1e40af); transform:translateY(-1px); }}
.btn-success {{ background:linear-gradient(135deg,#059669,#047857); color:#fff; border-color:transparent; }}
.btn-success:hover {{ background:linear-gradient(135deg,#047857,#065f46); }}
.btn-danger  {{ background:rgba(220,38,38,.15); color:#f87171; border-color:rgba(220,38,38,.3); }}
.btn-danger:hover  {{ background:rgba(220,38,38,.25); }}
.btn-ghost   {{ background:var(--glass); color:var(--ink); }}
.btn-ghost:hover {{ background:rgba(255,255,255,.1); }}
.empty-state {{ text-align:center; padding:40px 20px; color:var(--muted); }}
.empty-state .icon {{ font-size:36px; margin-bottom:12px; }}
.form-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.form-field label {{ display:block; font-size:11px; color:var(--muted); margin-bottom:4px; }}
.form-field input,.form-field select,.form-field textarea {{
  width:100%; background:var(--panel-solid); border:1px solid var(--line-strong);
  border-radius:8px; padding:9px 12px; color:var(--ink); font-size:12px; }}
.form-field textarea {{ resize:vertical; min-height:72px; }}
"""


_SHARED_JS = """
<script>
var AK = (sessionStorage.getItem('als_admin_key')||localStorage.getItem('als_admin_key')||'');

function syncAKInputs(){
  var top=document.getElementById('_top_ak_inp');
  var banner=document.getElementById('_ak_inp');
  if(top && AK) top.value=AK;
  if(banner && AK) banner.value=AK;
}

// ── API Key Banner ────────────────────────────────────────────────────────────
(function(){
  var banner = document.createElement('div');
  banner.id = '_ak_banner';
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#1d4ed8,#2563eb);padding:10px 20px;display:flex;align-items:center;gap:12px;font-size:13px;color:#fff;box-shadow:0 4px 20px rgba(0,0,0,.4);';
  banner.innerHTML = '<span style="font-weight:700;">🔑 Admin API Key:</span>'
    +'<input id="_ak_inp" type="password" placeholder="أدخل Admin API Key..." '
    +'style="flex:1;max-width:420px;padding:7px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);color:#fff;font-size:13px;outline:none;" />'
    +'<button onclick="saveAK()" style="padding:7px 18px;border-radius:8px;background:#fff;color:#1d4ed8;font-weight:700;border:none;cursor:pointer;font-size:13px;">حفظ ✓</button>'
    +'<button onclick="document.getElementById(\\'_ak_banner\\').style.display=\\'none\\'" style="padding:7px 14px;border-radius:8px;background:rgba(255,255,255,.15);color:#fff;border:none;cursor:pointer;font-size:12px;">✕</button>';
  document.body.insertBefore(banner, document.body.firstChild);
  syncAKInputs();
  if(AK){
    banner.style.display='none';
    // Show small indicator instead
    var ind = document.createElement('div');
    ind.id='_ak_ind';
    ind.style.cssText='position:fixed;bottom:24px;left:24px;z-index:9998;background:rgba(5,150,105,.9);color:#fff;padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;';
    ind.textContent='🔑 API Key مُعيّن';
    ind.onclick=function(){ document.getElementById('_ak_banner').style.display='flex'; };
    document.body.appendChild(ind);
  }
})();

function saveAK(){
  var v = document.getElementById('_ak_inp').value.trim();
  if(!v){ alert('أدخل API Key أولاً'); return; }
  AK = v;
  sessionStorage.setItem('als_admin_key', v);
  localStorage.setItem('als_admin_key', v);
  document.getElementById('_ak_banner').style.display='none';
  showToast('تم حفظ API Key ✓ جاري تحديث البيانات...','ok');
  setTimeout(function(){ location.reload(); }, 1200);
}

function saveTopAK(){
  var v = document.getElementById('_top_ak_inp').value.trim();
  if(!v){ alert('أدخل API Key أولاً'); return; }
  AK = v;
  sessionStorage.setItem('als_admin_key', v);
  localStorage.setItem('als_admin_key', v);
  syncAKInputs();
  showToast('تم حفظ API Key ✓ جاري تحديث البيانات...','ok');
  setTimeout(function(){ location.reload(); }, 900);
}

function H(extra) {
  var h = {'Content-Type':'application/json'};
  if(AK) h['X-Admin-API-Key'] = AK;
  if(extra) Object.assign(h,extra);
  return h;
}

async function api(url, opts) {
  opts = opts||{};
  opts.headers = H(opts.headers||{});
  opts.credentials = 'include';
  var r = await fetch(url, opts);
  if(r.status === 401 || r.status === 403){
    // Show API key banner on auth failure
    var b=document.getElementById('_ak_banner');
    if(b) b.style.display='flex';
    showToast('خطأ في المصادقة — أدخل Admin API Key','error');
    throw new Error('غير مصرح — HTTP '+r.status);
  }
  if(!r.ok){
    var m='HTTP '+r.status;
    try{ var d=await r.json(); m=d.detail||d.message||m; }catch(e){}
    throw new Error(m);
  }
  return r.json();
}

function badge(s){
  var m={
    'COMPLETED':'#10b981','APPROVED':'#10b981','VERIFIED':'#10b981','RECONCILED':'#10b981',
    'ON_CHAIN_CONFIRMED':'#10b981','ALCHEMY_VERIFIED':'#10b981',
    'PENDING':'#f59e0b','QUEUED':'#f59e0b','AWAITING_APPROVAL':'#f59e0b',
    'FX_FETCHED':'#f59e0b','AWAITING_TX_HASH':'#f59e0b','ALCHEMY_PENDING':'#f59e0b',
    'FAILED':'#ef4444','CANCELLED':'#ef4444','REJECTED':'#ef4444',
    'BROADCASTING':'#8b5cf6','PROCESSING':'#8b5cf6','CONVERTING':'#8b5cf6','SENDING':'#8b5cf6',
    'CREATED':'#6b7280','RECEIVED':'#6b7280','PARSED':'#6b7280',
    'MANUAL_REVIEW':'#f97316'
  };
  var c=m[(s||'').toUpperCase()]||'#6b7280';
  return '<span style="display:inline-block;padding:2px 9px;border-radius:20px;background:'+c+'22;color:'+c+';border:1px solid '+c+'44;font-size:11px;font-weight:700;">'+(s||'—')+'</span>';
}

function fmtDate(d){
  if(!d) return '—';
  return new Date(d).toLocaleString('ar-SA',{dateStyle:'short',timeStyle:'short'});
}

function fmtNum(n,dec){
  dec=(dec===undefined)?2:dec;
  var v=parseFloat(n);
  if(isNaN(v)) return '—';
  return v.toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec});
}

function showToast(msg,type){
  type=type||'info';
  var t=document.getElementById('_als_toast');
  if(!t){
    t=document.createElement('div');
    t.id='_als_toast';
    t.style.cssText='position:fixed;bottom:24px;right:24px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s;';
    document.body.appendChild(t);
  }
  var col={info:'#1d4ed8',ok:'#059669',error:'#dc2626',warn:'#d97706'};
  t.style.background=col[type]||col['info'];
  t.style.color='#fff';
  t.style.opacity='1';
  t.textContent=msg;
  clearTimeout(t._t);
  t._t=setTimeout(function(){t.style.opacity='0';},3500);
}

function copyText(txt){
  navigator.clipboard.writeText(txt).then(function(){showToast('تم النسخ','ok');});
}

// Mark active nav link
(function(){
  var p=location.pathname;
  document.querySelectorAll('.sidebar nav a').forEach(function(a){
    var h=a.getAttribute('href');
    if(h&&h===p) a.classList.add('active');
  });
})();
</script>
"""


def _page(title: str, active: str, body: str) -> str:
    """Wrap page body in the shared shell."""
    css = _BASE_CSS.replace("{", "{{").replace("}", "}}").replace("{{{{", "{{").replace("}}}}", "}}")
    # Use the CSS as-is (no format string in CSS)
    return (
        "<!doctype html>\n"
        '<html lang="ar" dir="rtl">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"  <title>{title} — ALSHUMOOKH GLOBAL</title>\n"
        '  <link rel="stylesheet" href="/static/dashboard.css?v=v4">\n'
        "  <style>\n"
        ".page-body { display:grid; gap:14px; }\n"
        ".stat-grid  { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }\n"
        ".stat-card  { background:var(--glass); border:1px solid var(--glass-border); border-radius:12px; padding:16px 14px; }\n"
        ".stat-card .label { font-size:11px; color:var(--muted); margin-bottom:6px; }\n"
        ".stat-card .value { font-size:22px; font-weight:800; color:var(--ink); }\n"
        ".stat-card .sub   { font-size:11px; color:var(--muted); margin-top:4px; }\n"
        ".panel      { background:var(--glass); border:1px solid var(--glass-border); border-radius:12px; overflow:hidden; }\n"
        ".panel-head { padding:12px 16px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; }\n"
        ".panel-head h3 { margin:0; font-size:13px; font-weight:700; color:var(--ink); }\n"
        ".filter-bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }\n"
        ".table-wrap { overflow-x:auto; }\n"
        "table  { width:100%; border-collapse:collapse; font-size:12px; }\n"
        "thead  { background:rgba(255,255,255,0.04); }\n"
        "th     { padding:10px 12px; text-align:right; color:var(--muted); font-weight:700; font-size:11px; border-bottom:1px solid var(--line); white-space:nowrap; }\n"
        "td     { padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:middle; color:var(--ink); }\n"
        "tr:hover td { background:rgba(255,255,255,0.03); }\n"
        ".btn   { display:inline-flex; align-items:center; gap:5px; padding:7px 14px; border-radius:8px; font-size:12px; font-weight:700; cursor:pointer; border:1px solid var(--glass-border); transition:all .2s; white-space:nowrap; }\n"
        ".btn-primary { background:linear-gradient(135deg,#2563eb,#1d4ed8); color:#fff; border-color:transparent; }\n"
        ".btn-primary:hover { background:linear-gradient(135deg,#1d4ed8,#1e40af); transform:translateY(-1px); }\n"
        ".btn-success { background:linear-gradient(135deg,#059669,#047857); color:#fff; border-color:transparent; }\n"
        ".btn-success:hover { background:linear-gradient(135deg,#047857,#065f46); }\n"
        ".btn-danger  { background:rgba(220,38,38,.15); color:#f87171; border-color:rgba(220,38,38,.3); }\n"
        ".btn-danger:hover  { background:rgba(220,38,38,.25); }\n"
        ".btn-ghost   { background:var(--glass); color:var(--ink); }\n"
        ".btn-ghost:hover { background:rgba(255,255,255,.1); }\n"
        ".empty-state { text-align:center; padding:40px 20px; color:var(--muted); }\n"
        ".empty-state .icon { font-size:36px; margin-bottom:12px; }\n"
        ".form-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }\n"
        ".form-field label { display:block; font-size:11px; color:var(--muted); margin-bottom:4px; }\n"
        ".form-field input,.form-field select,.form-field textarea { width:100%; background:var(--panel-solid); border:1px solid var(--line-strong); border-radius:8px; padding:9px 12px; color:var(--ink); font-size:12px; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        + _sidebar(active)
        + "<main>\n"
        + _topbar(title)
        + body
        + "\n</main>\n"
        + _SHARED_JS
        + "\n</body>\n</html>"
    )


def _guard(request: Request):
    """Return RedirectResponse if not authenticated, else None."""
    if not is_admin_request_authenticated(request):
        return RedirectResponse("/login?type=admin", status_code=http_status.HTTP_302_FOUND)
    return None


# ═══════════════════════════════════════════════════════════════════
# PAGE BODIES
# ═══════════════════════════════════════════════════════════════════

_OVERVIEW_BODY = """
<div class="page-body">
  <div class="stat-grid">
    <div class="stat-card"><div class="label">اجمالي الطلبات</div><div class="value" id="sTotal">—</div></div>
    <div class="stat-card"><div class="label">مكتملة</div><div class="value" id="sCompleted" style="color:#10b981;">—</div></div>
    <div class="stat-card"><div class="label">Settlement Payloads</div><div class="value" id="sPayloads">—</div></div>
    <div class="stat-card"><div class="label">USDT المرسل</div><div class="value" id="sUsdt" style="color:#a78bfa;">—</div><div class="sub">اجمالي المكتملة</div></div>
    <div class="stat-card"><div class="label">تحويلات معلقة</div><div class="value" id="sPending" style="color:#f59e0b;">—</div></div>
    <div class="stat-card"><div class="label">وظائف M1</div><div class="value" id="sM1">—</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>اخر الاحداث</h3></div>
      <div id="recentEvents" style="padding:12px 16px;min-height:80px;"></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>اخر التحويلات</h3></div>
      <div id="recentTransfers" style="padding:12px 16px;min-height:80px;"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Settlement Payloads - توزيع الحالة</h3></div>
    <div id="payloadStatus" style="padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;min-height:40px;"></div>
  </div>

  <!-- Settlement Payloads List with Actions -->
  <div class="panel" id="ovPlPanel">
    <div class="panel-head">
      <h3>📥 Settlement Payloads — إجراءات سريعة</h3>
      <button class="btn btn-ghost" onclick="loadOvPayloads()" style="font-size:11px;padding:4px 10px;">تحديث</button>
    </div>
    <!-- Detail modal like legacy dashboard -->
    <div id="ovPlDetail" style="display:none;position:fixed;inset:0;z-index:100000;background:rgba(15,23,42,.70);overflow-y:auto;padding:24px;">
      <div style="max-width:1180px;margin:0 auto;background:var(--panel-solid);border:1px solid var(--line-strong);border-radius:14px;box-shadow:0 24px 80px rgba(0,0,0,.55);overflow:hidden;">
      <div style="padding:16px 18px;border-bottom:1px solid var(--line);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h4 id="ovPlRef" style="margin:0;font-size:13px;color:var(--brand);"></h4>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary" id="ovBtnVerify" onclick="ovVerify()">Verify with Alchemy</button>
          <button class="btn btn-ghost"   id="ovBtnManual" onclick="ovManual()">Manual Review</button>
          <button class="btn btn-ghost"   onclick="ovClosePayload()" style="font-size:11px;">✕ إغلاق</button>
        </div>
      </div>
      </div>
      <div style="padding:16px 18px;">
      <!-- Info grid -->
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:14px;" id="ovPlInfoGrid"></div>
      <!-- Operational Controls -->
      <div style="background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px;">
        <div style="font-size:12px;font-weight:700;color:var(--ink);margin-bottom:10px;">Operational Review Controls</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
          <div>
            <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px;">Priority</label>
            <select id="ovPriority" style="width:100%;background:var(--panel-solid);border:1px solid var(--line-strong);border-radius:8px;padding:8px 10px;color:var(--ink);font-size:12px;">
              <option>NORMAL</option><option>HIGH</option><option>URGENT</option><option>LOW</option>
            </select>
          </div>
          <div>
            <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px;">Hold reason</label>
            <input id="ovHoldReason" type="text" placeholder="Reason for hold or exception" style="width:100%;background:var(--panel-solid);border:1px solid var(--line-strong);border-radius:8px;padding:8px 10px;color:var(--ink);font-size:12px;">
          </div>
        </div>
        <div style="margin-bottom:10px;">
          <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px;">Review note</label>
          <textarea id="ovReviewNote" rows="3" placeholder="Operational notes, analyst comments, mismatch findings, or reconciliation note" style="width:100%;background:var(--panel-solid);border:1px solid var(--line-strong);border-radius:8px;padding:8px 10px;color:var(--ink);font-size:12px;resize:vertical;"></textarea>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-success" onclick="ovReview('approve')">✅ Approve</button>
          <button class="btn" style="background:rgba(245,158,11,.15);color:#f59e0b;border-color:rgba(245,158,11,.3);" onclick="ovHold()">⏸ Hold</button>
          <button class="btn btn-danger"  onclick="ovReview('reject')">❌ Reject</button>
          <button class="btn btn-ghost"   onclick="ovSaveNote()">💾 Save Note</button>
        </div>
      </div>
      <!-- Tabs -->
      <div style="border-bottom:1px solid var(--line);margin-bottom:12px;display:flex;gap:0;">
        <button class="ov-tab active" onclick="ovTab('raw')" id="tab-raw" style="padding:8px 16px;font-size:12px;background:none;border:none;border-bottom:2px solid var(--brand);color:var(--brand);cursor:pointer;font-weight:700;">Raw JSON</button>
        <button class="ov-tab" onclick="ovTab('parsed')" id="tab-parsed" style="padding:8px 16px;font-size:12px;background:none;border:none;color:var(--muted);cursor:pointer;">Parsed Fields</button>
        <button class="ov-tab" onclick="ovTab('blockchain')" id="tab-blockchain" style="padding:8px 16px;font-size:12px;background:none;border:none;color:var(--muted);cursor:pointer;">Blockchain Result</button>
        <button class="ov-tab" onclick="ovTab('headers')" id="tab-headers" style="padding:8px 16px;font-size:12px;background:none;border:none;color:var(--muted);cursor:pointer;">Headers</button>
        <button class="ov-tab" onclick="ovTab('audit')" id="tab-audit" style="padding:8px 16px;font-size:12px;background:none;border:none;color:var(--muted);cursor:pointer;">Audit</button>
      </div>
      <div id="ovTabContent" style="font-size:11px;font-family:monospace;background:rgba(0,0,0,.3);border-radius:8px;padding:12px;max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;"></div>
      </div>
      </div>
    </div>
    <div id="ovPlBody" style="padding:0;"><div class="empty-state"><div class="icon">📥</div>جاري التحميل...</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>System Readiness</h3>
      <button class="btn btn-ghost" onclick="loadOverview()" style="font-size:11px;padding:4px 10px;">تحديث</button>
    </div>
    <div id="readinessBody" style="padding:14px 16px;"></div>
  </div>
</div>

<script>
async function loadOverview() {
  document.getElementById('readinessBody').innerHTML='<p style="color:var(--muted);font-size:12px;">جاري الاتصال بالخادم...</p>';
  try {
    var m = await api('/api/v1/admin/monitoring/live');
    document.getElementById('sTotal').textContent     = (m.orders && m.orders.total)||0;
    document.getElementById('sCompleted').textContent = (m.orders && m.orders.by_status && m.orders.by_status['COMPLETED'])||0;
    document.getElementById('sPayloads').textContent  = (m.payloads && m.payloads.total)||0;
    document.getElementById('sUsdt').textContent      = fmtNum((m.outbound_transfers && m.outbound_transfers.total_usdt_sent)||0) + ' USDT';
    document.getElementById('sPending').textContent   = (m.outbound_transfers && m.outbound_transfers.pending_approvals)||0;
    document.getElementById('sM1').textContent        = (m.tokenization_jobs && m.tokenization_jobs.total)||0;

    var ev = (m.recent_events)||[];
    document.getElementById('recentEvents').innerHTML = ev.length
      ? ev.map(function(e){return '<div style="padding:7px 0;border-bottom:1px solid var(--line);font-size:12px;"><span style="color:var(--gold);font-weight:700;">'+e.event_type+'</span><span style="float:left;color:var(--muted);font-size:11px;">'+fmtDate(e.created_at)+'</span></div>';}).join('')
      : '<p style="color:var(--muted);text-align:center;padding:16px;">لا توجد احداث</p>';

    var tr = (m.outbound_transfers && m.outbound_transfers.recent)||[];
    document.getElementById('recentTransfers').innerHTML = tr.length
      ? tr.map(function(t){return '<div style="padding:7px 0;border-bottom:1px solid var(--line);font-size:12px;"><span style="color:var(--brand);font-weight:600;">'+(t.network||'').toUpperCase()+'</span><span style="margin:0 8px;">'+fmtNum(t.amount)+' USDT</span>'+badge(t.status)+'<div style="color:var(--muted);font-size:11px;margin-top:2px;">'+(t.tx_hash?t.tx_hash.slice(0,22)+'...':'No TX yet')+'</div></div>';}).join('')
      : '<p style="color:var(--muted);text-align:center;padding:16px;">لا توجد تحويلات</p>';

    var ps = (m.payloads && m.payloads.by_status)||{};
    var psKeys = Object.keys(ps);
    document.getElementById('payloadStatus').innerHTML = psKeys.length
      ? psKeys.map(function(s){return '<div style="padding:8px 14px;border-radius:8px;background:rgba(255,255,255,.05);border:1px solid var(--line);">'+badge(s)+' <strong style="color:var(--ink);margin-right:6px;">'+ps[s]+'</strong></div>';}).join('')
      : '<p style="color:var(--muted);">لا توجد بيانات</p>';
  } catch(e) {
    var errMsg = e.message||'خطأ غير معروف';
    // Show error visibly so user can diagnose
    document.getElementById('sTotal').textContent='ERR';
    document.getElementById('readinessBody').innerHTML =
      '<div style="background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.3);border-radius:10px;padding:16px;margin-bottom:12px;">'
      +'<div style="color:#f87171;font-weight:700;margin-bottom:8px;">❌ فشل الاتصال بالـ API</div>'
      +'<div style="color:#fca5a5;font-size:12px;margin-bottom:12px;">الخطأ: '+errMsg+'</div>'
      +'<div style="font-size:12px;color:var(--muted);margin-bottom:8px;">الحل: أدخل Admin API Key في الشريط الأزرق أعلى الصفحة</div>'
      +'<button onclick="var b=document.getElementById(\\'_ak_banner\\');if(b){b.style.display=\\'flex\\';}" '
      +'style="background:#2563eb;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:700;">🔑 إدخال API Key</button>'
      +'</div>';
  }

  try {
    var rd = await api('/api/v1/admin/system/readiness');
    var checks = rd.checks||{};
    var warnings = rd.warnings||[];
    var html = Object.keys(checks).map(function(k){
      var v=checks[k];
      return '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line);font-size:12px;"><span>'+k.replace(/_/g,' ')+'</span><span style="color:'+(v===true||v==='ok'?'#10b981':'#f59e0b')+';font-weight:700;">'+(v===true?'OK':v===false?'Not Set':v)+'</span></div>';
    }).join('');
    if(warnings.length){
      html += '<div style="margin-top:12px;">'+warnings.map(function(w){return '<div style="padding:6px 10px;margin-top:4px;border-radius:6px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.2);font-size:12px;color:#fbbf24;">'+w+'</div>';}).join('')+'</div>';
    }
    document.getElementById('readinessBody').innerHTML = html||'<p style="color:var(--muted);">لا توجد بيانات</p>';
  } catch(e) {
    // readinessBody might already show error from monitoring, that's ok
  }
}
loadOverview();
setInterval(loadOverview, 30000);

// ── Settlement Payloads in Overview ──────────────────────────────────────────
var _ovCurrentPl = null;

async function loadOvPayloads() {
  try {
    var res = await api('/api/v1/admin/payloads');
    var rows = res.payloads||[];
    if(!rows.length){
      document.getElementById('ovPlBody').innerHTML='<div class="empty-state"><div class="icon">📥</div>لا توجد payloads</div>';
      return;
    }
    var th='<th>Reference</th><th>Amount</th><th>Network</th><th>Status</th><th>Security</th><th>TX Hash</th><th>التاريخ</th><th>إجراء</th>';
    var tb=rows.map(function(r){
      var rid=r.id||r.payload_id;
      var ref=r.transaction_reference||(rid?rid.slice(0,12)+'...':'—');
      var eid=encodeURIComponent(rid);
      return '<tr data-plid="'+eid+'" onclick="ovViewPayload(this.dataset.plid)" style="cursor:pointer;">'
        +'<td><span style="font-size:10px;font-family:monospace;color:var(--brand);cursor:pointer;" data-plid="'+eid+'" onclick="ovViewPayload(this.dataset.plid)">'+ref+'</span></td>'
        +'<td><strong>'+fmtNum(r.amount)+'</strong> <span style="color:var(--muted);">'+(r.asset||'USDT')+'</span></td>'
        +'<td>'+(r.network||r.network_name||'—').toUpperCase()+'</td>'
        +'<td>'+badge(r.verification_status)+'</td>'
        +'<td style="font-size:10px;color:var(--muted);">'+(r.security_level||'—')+'</td>'
        +'<td style="font-size:10px;font-family:monospace;">'+(r.tx_hash?r.tx_hash.slice(0,16)+'...':'—')+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
        +'<td><div style="display:flex;gap:4px;">'
          +'<button class="btn btn-ghost"   data-plid="'+eid+'"                    onclick="event.stopPropagation();ovViewPayload(this.dataset.plid)" style="font-size:10px;padding:3px 8px;">🔍</button>'
          +'<button class="btn btn-success" data-plid="'+eid+'" data-act="approve" onclick="event.stopPropagation();ovQuickAction(this.dataset.plid,this.dataset.act)" style="font-size:10px;padding:3px 8px;">✅</button>'
          +'<button class="btn btn-danger"  data-plid="'+eid+'" data-act="reject"  onclick="event.stopPropagation();ovQuickAction(this.dataset.plid,this.dataset.act)" style="font-size:10px;padding:3px 8px;">❌</button>'
        +'</div></td>'
        +'</tr>';
    }).join('');
    document.getElementById('ovPlBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  } catch(e){
    document.getElementById('ovPlBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+e.message+'</div>';
  }
}

async function ovViewPayload(id) {
  try {
    var p = await api('/api/v1/admin/payloads/'+id);
    _ovCurrentPl = p;
    document.getElementById('ovPlRef').textContent = p.transaction_reference||p.id;
    // Info grid
    var infos=[
      ['Status', badge(p.verification_status)],
      ['Security', p.security_level||'—'],
      ['Network', (p.network||p.network_name||'—').toUpperCase()],
      ['Asset', p.asset||'USDT'],
      ['Amount', fmtNum(p.amount)],
      ['Priority', '<span style="background:rgba(255,255,255,.08);padding:2px 8px;border-radius:4px;font-size:11px;">'+(p.review_priority||'NORMAL')+'</span>'],
      ['Decision', p.review_decision||'—'],
      ['TX Hash', p.tx_hash||'—'],
      ['Confirmations', p.confirmations||'—'],
      ['Client IP', p.client_ip||'—'],
    ];
    document.getElementById('ovPlInfoGrid').innerHTML=infos.map(function(f){
      return '<div style="background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:8px;padding:10px 12px;">'
        +'<div style="font-size:10px;color:var(--muted);margin-bottom:4px;">'+f[0]+'</div>'
        +'<div style="font-size:12px;font-weight:600;color:var(--ink);">'+f[1]+'</div></div>';
    }).join('');
    // Set priority dropdown
    document.getElementById('ovPriority').value = p.review_priority||'NORMAL';
    // Show raw JSON tab by default
    ovTab('raw');
    document.getElementById('ovPlDetail').style.display='block';
    document.body.style.overflow='hidden';
  } catch(e){ showToast('خطأ: '+e.message,'error'); }
}

function ovClosePayload(){
  document.getElementById('ovPlDetail').style.display='none';
  document.body.style.overflow='';
}

function ovTab(tab) {
  var p = _ovCurrentPl||{};
  var content='';
  var tabs=['raw','parsed','blockchain','headers','audit'];
  tabs.forEach(function(t){
    var el=document.getElementById('tab-'+t);
    if(el){ el.style.borderBottom=t===tab?'2px solid var(--brand)':'none'; el.style.color=t===tab?'var(--brand)':'var(--muted)'; }
  });
  if(tab==='raw'){
    content=p.pretty_payload||p.raw_payload||JSON.stringify(p,null,2);
  } else if(tab==='parsed'){
    content=JSON.stringify(p.parsed_payload||{},null,2);
  } else if(tab==='blockchain'){
    content=JSON.stringify(p.blockchain_result||{tx_hash:p.tx_hash||null,confirmations:p.confirmations||0,block_number:p.block_number||null,network:p.network,explorer_url:p.explorer_url||null,on_chain_status:p.verification_status},null,2);
  } else if(tab==='headers'){
    content=JSON.stringify(p.headers||{security_level:p.security_level,auth_method:p.auth_method,jws_verified:p.jws_verified,mtls_verified:p.mtls_verified,client_ip:p.client_ip},null,2);
  } else if(tab==='audit'){
    content=JSON.stringify({payload_id:p.payload_id||p.id,created_at:p.created_at,updated_at:p.updated_at,reviewed_by:p.reviewed_by,review_note:p.review_note,review_decision:p.review_decision,hold_reason:p.hold_reason,error_message:p.error_message},null,2);
  }
  document.getElementById('ovTabContent').textContent=content;
}

async function ovVerify(){
  if(!_ovCurrentPl){return;}
  var pid=_ovCurrentPl.id||_ovCurrentPl.payload_id;
  try{await api('/api/v1/admin/payloads/'+pid+'/verify',{method:'POST'});showToast('تم إرسال طلب التحقق','ok');loadOvPayloads();ovViewPayload(pid);}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function ovManual(){
  if(!_ovCurrentPl){return;}
  var pid=_ovCurrentPl.id||_ovCurrentPl.payload_id;
  try{await api('/api/v1/admin/payloads/'+pid+'/mark-manual-review',{method:'POST'});showToast('تم التحديد للمراجعة','ok');loadOvPayloads();ovViewPayload(pid);}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function ovReview(decision){
  if(!_ovCurrentPl){return;}
  var note=document.getElementById('ovReviewNote').value||'';
  var action=(decision||'').toUpperCase();
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  try{await api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:action,note:note,priority:priority})});showToast(action==='APPROVE'?'تمت الموافقة ✅':'تم الرفض ❌','ok');loadOvPayloads();ovClosePayload();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function ovHold(){
  if(!_ovCurrentPl){return;}
  var reason=document.getElementById('ovHoldReason').value;
  var note='HOLD: '+(reason||document.getElementById('ovReviewNote').value||'on hold');
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  try{await api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:'HOLD',note:note,hold_reason:reason||note,priority:priority})});showToast('تم وضع الـ Payload في الانتظار','ok');loadOvPayloads();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function ovSaveNote(){
  if(!_ovCurrentPl){return;}
  var note=document.getElementById('ovReviewNote').value;
  if(!note){showToast('اكتب ملاحظة أولاً','error');return;}
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  try{await api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:'NOTE',note:note,priority:priority})});showToast('تم حفظ الملاحظة','ok');}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function ovQuickAction(id,decision){
  var note=decision==='approve'?'Quick approval from dashboard':'Quick rejection from dashboard';
  var action=(decision||'').toUpperCase();
  try{await api('/api/v1/admin/payloads/'+id+'/review',{method:'POST',body:JSON.stringify({action:action,note:note})});showToast(action==='APPROVE'?'تمت الموافقة ✅':'تم الرفض ❌','ok');loadOvPayloads();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
loadOvPayloads();
document.addEventListener('keydown', function(e){
  if(e.key==='Escape'){
    var d=document.getElementById('ovPlDetail');
    if(d && d.style.display==='block'){ ovClosePayload(); }
  }
});
</script>
"""

# ─── ORDERS ──────────────────────────────────────────────────────────────────

_ORDERS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="ordStatus" onchange="loadOrders()" style="min-width:140px;">
      <option value="">جميع الحالات</option>
      <option>CREATED</option><option>PENDING</option><option>PROCESSING</option>
      <option>COMPLETED</option><option>FAILED</option><option>REFUNDED</option><option>EXPIRED</option>
    </select>
    <button class="btn btn-ghost" onclick="loadOrders()">تحديث</button>
  </div>
  <div class="panel">
    <div class="panel-head">
      <h3>قائمة الطلبات</h3>
      <span id="ordCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="ordersBody"><div class="empty-state"><div class="icon">📋</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
async function loadOrders() {
  var st = document.getElementById('ordStatus').value;
  var url = '/api/v1/admin/orders' + (st ? '?status='+st : '');
  try {
    var rows = await api(url);
    if(!Array.isArray(rows)) rows = rows.orders||[];
    document.getElementById('ordCount').textContent = rows.length + ' طلب';
    if(!rows.length){
      document.getElementById('ordersBody').innerHTML='<div class="empty-state"><div class="icon">📋</div>لا توجد طلبات</div>';
      return;
    }
    var th = '<th>ID</th><th>Provider</th><th>Fiat</th><th>Crypto</th><th>الحالة</th><th>Network</th><th>Email</th><th>Ref</th><th>TX</th><th>التاريخ</th>';
    var tb = rows.map(function(o){return '<tr>'
      +'<td><code style="font-size:10px;" title="'+o.id+'">'+o.id.slice(0,10)+'...</code></td>'
      +'<td>'+(o.provider||'—')+'</td>'
      +'<td>'+fmtNum(o.fiat_amount)+' '+(o.fiat_currency||'')+'</td>'
      +'<td>'+fmtNum(o.crypto_amount,6)+' '+(o.crypto_currency||'')+'</td>'
      +'<td>'+badge(o.status)+'</td>'
      +'<td>'+(o.network||'—')+'</td>'
      +'<td>'+(o.payer_email||'—')+'</td>'
      +'<td>'+(o.payment_reference?'<code style="font-size:10px;">'+o.payment_reference+'</code>':'—')+'</td>'
      +'<td>'+(o.tx_hash?'<code style="font-size:10px;" title="'+o.tx_hash+'">'+o.tx_hash.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(o.created_at)+'</td>'
      +'</tr>';}).join('');
    document.getElementById('ordersBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  } catch(e) {
    document.getElementById('ordersBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';
  }
}
loadOrders();
</script>
"""

# ─── PAYLOADS ────────────────────────────────────────────────────────────────

_PAYLOADS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="plStatus" onchange="loadPayloads()" style="min-width:180px;">
      <option value="">جميع الحالات</option>
      <option>RECEIVED</option><option>PARSED</option><option>AWAITING_TX_HASH</option>
      <option>ALCHEMY_PENDING</option><option>ALCHEMY_VERIFIED</option>
      <option>ON_CHAIN_CONFIRMED</option><option>RECONCILED</option>
      <option>FAILED</option><option>MANUAL_REVIEW</option>
    </select>
    <button class="btn btn-ghost" onclick="loadPayloads()">تحديث</button>
  </div>

  <div id="plDetail" style="display:none;" class="panel">
    <div class="panel-head">
      <h3>تفاصيل الـ Payload</h3>
      <button class="btn btn-ghost" onclick="document.getElementById('plDetail').style.display='none'" style="font-size:11px;padding:4px 10px;">اغلاق</button>
    </div>
    <div id="plDetailBody" style="padding:16px;font-size:12px;line-height:1.8;"></div>
    <div id="plActions" style="padding:0 16px 16px;display:flex;gap:8px;flex-wrap:wrap;"></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>Settlement Payloads</h3>
      <span id="plCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="plBody"><div class="empty-state"><div class="icon">📥</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
async function loadPayloads() {
  var st = document.getElementById('plStatus').value;
  var url = '/api/v1/admin/payloads' + (st ? '?verification_status='+st : '');
  try {
    var res = await api(url);
    var rows = res.payloads||[];
    document.getElementById('plCount').textContent = (res.count||rows.length)+' payload';
    if(!rows.length){
      document.getElementById('plBody').innerHTML='<div class="empty-state"><div class="icon">📥</div>لا توجد payloads</div>';
      return;
    }
    var th = '<th>ID</th><th>Amount</th><th>Network</th><th>Sender</th><th>TX Hash</th><th>Security</th><th>الحالة</th><th>التاريخ</th><th>عرض</th>';
    var tb = rows.map(function(r){var rid=r.id||r.payload_id;return '<tr onclick="viewPayload(\\''+rid+'\\')" style="cursor:pointer;">'
      +'<td><code style="font-size:10px;cursor:pointer;color:var(--brand);">'+rid.slice(0,10)+'...</code></td>'
      +'<td>'+fmtNum(r.amount)+' '+(r.asset||'USDT')+'</td>'
      +'<td>'+((r.network_name||r.network||'').toUpperCase())+'</td>'
      +'<td>'+(r.sender_wallet?'<code style="font-size:10px;" title="'+r.sender_wallet+'">'+r.sender_wallet.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td>'+(r.tx_hash?'<code style="font-size:10px;" title="'+r.tx_hash+'">'+r.tx_hash.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td><span style="font-size:10px;color:var(--muted);">'+(r.security_level||'—')+'</span></td>'
      +'<td>'+badge(r.verification_status)+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><button class="btn btn-ghost" onclick="event.stopPropagation();viewPayload(\\''+rid+'\\')" style="font-size:11px;padding:4px 10px;">عرض</button></td>'
      +'</tr>';}).join('');
    document.getElementById('plBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  } catch(e) {
    document.getElementById('plBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';
  }
}

async function viewPayload(id) {
  try {
    var p = await api('/api/v1/admin/payloads/'+id);
    var fields=[
      ['ID',p.id],['Verification Status',badge(p.verification_status)],
      ['Amount',fmtNum(p.amount)+' '+(p.asset||'USDT')],
      ['Network',(p.network_name||p.network||'—').toUpperCase()],
      ['TX Hash',p.tx_hash||'—'],['Sender',p.sender_wallet||'—'],
      ['Receiver',p.receiver_wallet||'—'],['Callback URL',p.callback_url||'—'],
      ['Security Level',p.security_level||'—'],['Auth Method',p.auth_method||'—'],
      ['JWS Verified',p.jws_verified?'Yes':'No'],
      ['mTLS Verified',p.mtls_verified?'Yes':'No'],
      ['Review Priority',p.review_priority||'—'],
      ['Review Decision',p.review_decision||'—'],
      ['Reviewed By',p.reviewed_by||'—'],
      ['Created',fmtDate(p.created_at)],['Updated',fmtDate(p.updated_at)]
    ];
    document.getElementById('plDetailBody').innerHTML = fields.map(function(f){
      return '<div style="display:flex;gap:12px;padding:5px 0;border-bottom:1px solid var(--line);">'
        +'<span style="color:var(--muted);min-width:140px;flex-shrink:0;">'+f[0]+'</span>'
        +'<span style="word-break:break-all;">'+f[1]+'</span></div>';
    }).join('');

    var acts=[];
    var vstatus=p.verification_status||'';
    if(['RECEIVED','PARSED','AWAITING_TX_HASH'].indexOf(vstatus)>=0){
      acts.push('<button class="btn btn-primary" onclick="verifyPl(\\''+id+'\\')">Verify On-Chain</button>');
    }
    if(vstatus!=='MANUAL_REVIEW'){
      acts.push('<button class="btn btn-ghost" onclick="markManual(\\''+id+'\\')">Mark Manual Review</button>');
    }
    acts.push('<button class="btn btn-success" onclick="reviewPl(\\''+id+'\\',\\'approve\\')">Approve</button>');
    acts.push('<button class="btn btn-danger"  onclick="reviewPl(\\''+id+'\\',\\'reject\\')">Reject</button>');
    document.getElementById('plActions').innerHTML=acts.join('');
    document.getElementById('plDetail').style.display='block';
    document.getElementById('plDetail').scrollIntoView({behavior:'smooth'});
  } catch(e){ showToast('خطأ: '+e.message,'error'); }
}

async function verifyPl(id){
  try{await api('/api/v1/admin/payloads/'+id+'/verify',{method:'POST'});showToast('تم ارسال طلب التحقق','ok');loadPayloads();viewPayload(id);}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function markManual(id){
  try{await api('/api/v1/admin/payloads/'+id+'/mark-manual-review',{method:'POST'});showToast('تم التحديد للمراجعة','ok');loadPayloads();viewPayload(id);}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function reviewPl(id,decision){
  var note=prompt('ملاحظة ('+(decision==='approve'?'موافقة':'رفض')+'): ')||'';
  var action=(decision||'').toUpperCase();
  try{await api('/api/v1/admin/payloads/'+id+'/review',{method:'POST',body:JSON.stringify({action:action,note:note})});showToast('تم '+(action==='APPROVE'?'القبول':'الرفض'),'ok');loadPayloads();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
loadPayloads();
</script>
"""

# ─── TRANSFERS ────────────────────────────────────────────────────────────────

_TRANSFERS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="xtStatus" onchange="loadTransfers()" style="min-width:160px;">
      <option value="">جميع الحالات</option>
      <option>PENDING</option><option>AWAITING_APPROVAL</option><option>APPROVED</option>
      <option>BROADCASTING</option><option>COMPLETED</option><option>FAILED</option><option>CANCELLED</option>
    </select>
    <select id="xtNetwork" onchange="loadTransfers()" style="min-width:130px;">
      <option value="">جميع الشبكات</option>
      <option value="ethereum">Ethereum</option>
      <option value="tron">TRON</option>
      <option value="base">Base</option>
    </select>
    <button class="btn btn-ghost" onclick="loadTransfers()">تحديث</button>
    <button class="btn btn-primary" onclick="toggleCF()">+ انشاء تحويل</button>
  </div>

  <div id="createXferForm" style="display:none;" class="panel">
    <div class="panel-head"><h3>انشاء تحويل USDT جديد</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>عنوان المستلم *</label>
          <input id="cfTo" placeholder="0x... او T..."></div>
        <div class="form-field"><label>المبلغ (USDT) *</label>
          <input id="cfAmt" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>الشبكة *</label>
          <select id="cfNet">
            <option value="ethereum">Ethereum (ERC-20)</option>
            <option value="tron">TRON (TRC-20)</option>
            <option value="base">Base (ERC-20)</option>
          </select></div>
        <div class="form-field"><label>Callback URL</label>
          <input id="cfCb" placeholder="https://..."></div>
        <div class="form-field" style="grid-column:span 2;"><label>ملاحظات</label>
          <input id="cfNotes" placeholder="ملاحظات اختيارية"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-success" onclick="createTransfer()">انشاء</button>
        <button class="btn btn-ghost" onclick="toggleCF()">الغاء</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>التحويلات الصادرة</h3>
      <span id="xtCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="xtBody"><div class="empty-state"><div class="icon">🚀</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
function toggleCF(){
  var el=document.getElementById('createXferForm');
  el.style.display=el.style.display==='none'?'block':'none';
}

async function createTransfer(){
  var body={
    to_address:document.getElementById('cfTo').value.trim(),
    amount:document.getElementById('cfAmt').value,
    network:document.getElementById('cfNet').value,
    callback_url:document.getElementById('cfCb').value.trim()||null,
    notes:document.getElementById('cfNotes').value.trim()||null
  };
  if(!body.to_address){showToast('عنوان المستلم مطلوب','error');return;}
  if(!body.amount){showToast('المبلغ مطلوب','error');return;}
  try{
    await api('/api/v1/admin/outbound-transfers',{method:'POST',body:JSON.stringify(body)});
    showToast('تم انشاء التحويل','ok');
    toggleCF();
    document.getElementById('cfTo').value='';document.getElementById('cfAmt').value='';
    document.getElementById('cfCb').value='';document.getElementById('cfNotes').value='';
    loadTransfers();
  }catch(e){showToast('خطأ: '+e.message,'error');}
}

async function approveXfer(id){
  if(!confirm('تاكيد الموافقة؟'))return;
  try{await api('/api/v1/admin/outbound-transfers/'+id+'/approve',{method:'POST'});showToast('تمت الموافقة','ok');loadTransfers();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function broadcastXfer(id){
  if(!confirm('تاكيد البث على الشبكة؟'))return;
  try{await api('/api/v1/admin/outbound-transfers/'+id+'/broadcast',{method:'POST'});showToast('جاري البث','ok');loadTransfers();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function cancelXfer(id){
  var r=prompt('سبب الالغاء:')||'Cancelled by admin';
  try{await api('/api/v1/admin/outbound-transfers/'+id+'/cancel',{method:'POST',body:JSON.stringify({reason:r})});showToast('تم الالغاء','ok');loadTransfers();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function retryXfer(id){
  try{await api('/api/v1/admin/outbound-transfers/'+id+'/retry',{method:'POST'});showToast('تمت اعادة المحاولة','ok');loadTransfers();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}

async function loadTransfers(){
  var st=document.getElementById('xtStatus').value;
  var nt=document.getElementById('xtNetwork').value;
  var url='/api/v1/admin/outbound-transfers?limit=100';
  if(st)url+='&status='+st;if(nt)url+='&network='+nt;
  try{
    var rows=await api(url);
    if(!Array.isArray(rows))rows=[];
    document.getElementById('xtCount').textContent=rows.length+' تحويل';
    if(!rows.length){document.getElementById('xtBody').innerHTML='<div class="empty-state"><div class="icon">🚀</div>لا توجد تحويلات</div>';return;}
    var th='<th>ID</th><th>Network</th><th>Amount</th><th>To Address</th><th>TX Hash</th><th>الحالة</th><th>Approved By</th><th>التاريخ</th><th>اجراءات</th>';
    var tb=rows.map(function(r){
      var btns=[];
      if(['PENDING','AWAITING_APPROVAL'].indexOf(r.status)>=0)
        btns.push('<button class="btn btn-success" onclick="approveXfer(\\''+r.id+'\\')" style="font-size:11px;padding:3px 8px;">موافقة</button>');
      if(r.status==='APPROVED')
        btns.push('<button class="btn btn-primary" onclick="broadcastXfer(\\''+r.id+'\\')" style="font-size:11px;padding:3px 8px;">بث</button>');
      if(r.status==='FAILED')
        btns.push('<button class="btn btn-ghost" onclick="retryXfer(\\''+r.id+'\\')" style="font-size:11px;padding:3px 8px;">اعادة</button>');
      if(['COMPLETED','CANCELLED'].indexOf(r.status)<0)
        btns.push('<button class="btn btn-danger" onclick="cancelXfer(\\''+r.id+'\\')" style="font-size:11px;padding:3px 8px;">الغاء</button>');
      return '<tr>'
        +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,10)+'...</code></td>'
        +'<td><strong>'+(r.network||'').toUpperCase()+'</strong></td>'
        +'<td><strong style="color:#a78bfa;">'+fmtNum(r.amount)+' USDT</strong></td>'
        +'<td>'+(r.to_address?'<code style="font-size:10px;" title="'+r.to_address+'">'+r.to_address.slice(0,16)+'...</code>':'—')+'</td>'
        +'<td>'+(r.tx_hash?'<code style="font-size:10px;" title="'+r.tx_hash+'">'+r.tx_hash.slice(0,14)+'...</code>':'—')+'</td>'
        +'<td>'+badge(r.status)+'</td>'
        +'<td>'+(r.approved_by||'—')+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
        +'<td>'+btns.join(' ')+'</td>'
        +'</tr>';
    }).join('');
    document.getElementById('xtBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }catch(e){document.getElementById('xtBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
loadTransfers();
setInterval(loadTransfers,20000);
</script>
"""

# ─── TOKENIZATION ─────────────────────────────────────────────────────────────

_TOKENIZATION_BODY = """
<div class="page-body">
  <div class="panel">
    <div class="panel-head">
      <h3>سعر الصرف المباشر EUR/USD</h3>
      <button class="btn btn-ghost" onclick="loadFx()" style="font-size:11px;padding:4px 10px;">تحديث</button>
    </div>
    <div id="fxBanner" style="padding:14px 16px;display:flex;gap:24px;align-items:center;min-height:48px;"></div>
  </div>

  <div class="filter-bar">
    <select id="m1Status" onchange="loadJobs()" style="min-width:140px;">
      <option value="">جميع الحالات</option>
      <option>QUEUED</option><option>FX_FETCHED</option><option>CONVERTING</option>
      <option>SENDING</option><option>COMPLETED</option><option>FAILED</option>
    </select>
    <button class="btn btn-ghost" onclick="loadJobs()">تحديث</button>
    <button class="btn btn-primary" onclick="toggleM1F()">+ انشاء وظيفة</button>
  </div>

  <div id="m1Form" style="display:none;" class="panel">
    <div class="panel-head"><h3>انشاء وظيفة M1 Tokenization</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>مبلغ EUR *</label><input id="m1Eur" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>محفظة الوجهة *</label><input id="m1Dest" placeholder="0x... او T..."></div>
        <div class="form-field"><label>المرجع</label><input id="m1Ref" placeholder="اختياري"></div>
        <div class="form-field"><label>اسم المرسل</label><input id="m1Name" placeholder="اختياري"></div>
        <div class="form-field"><label>الشبكة</label>
          <select id="m1Net"><option value="ethereum">Ethereum</option><option value="tron">TRON</option><option value="base">Base</option></select></div>
        <div class="form-field"><label>IBAN</label><input id="m1Iban" placeholder="اختياري"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-success" onclick="createJob()">انشاء</button>
        <button class="btn btn-ghost" onclick="toggleM1F()">الغاء</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>وظائف M1 Tokenization</h3>
      <span id="m1Count" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="m1Body"><div class="empty-state"><div class="icon">🔄</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
async function loadFx(){
  try{
    var r=await api('/api/v1/admin/tokenization-jobs/fx-rate/live');
    document.getElementById('fxBanner').innerHTML='<div style="font-size:28px;font-weight:800;color:var(--gold);">1 EUR = '+parseFloat(r.eur_usd).toFixed(4)+' USD</div><div style="color:var(--muted);font-size:12px;">Provider: '+(r.provider||'—')+'<br>'+fmtDate(r.timestamp)+'</div>';
  }catch(e){document.getElementById('fxBanner').innerHTML='<span style="color:var(--muted);">غير متاح: '+e.message+'</span>';}
}
function toggleM1F(){
  var el=document.getElementById('m1Form');
  el.style.display=el.style.display==='none'?'block':'none';
}
async function createJob(){
  var body={eur_amount:document.getElementById('m1Eur').value,destination_wallet:document.getElementById('m1Dest').value.trim(),sender_reference:document.getElementById('m1Ref').value.trim()||null,sender_name:document.getElementById('m1Name').value.trim()||null,sender_iban:document.getElementById('m1Iban').value.trim()||null,network:document.getElementById('m1Net').value};
  if(!body.eur_amount){showToast('مبلغ EUR مطلوب','error');return;}
  if(!body.destination_wallet){showToast('محفظة الوجهة مطلوبة','error');return;}
  try{await api('/api/v1/admin/tokenization-jobs',{method:'POST',body:JSON.stringify(body)});showToast('تم انشاء الوظيفة','ok');toggleM1F();loadJobs();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function processJob(id){
  if(!confirm('تشغيل وظيفة EUR->USDT الان؟'))return;
  try{await api('/api/v1/admin/tokenization-jobs/'+id+'/process',{method:'POST'});showToast('تمت المعالجة','ok');loadJobs();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function loadJobs(){
  var st=document.getElementById('m1Status').value;
  var url='/api/v1/admin/tokenization-jobs?limit=100'+(st?'&status='+st:'');
  try{
    var rows=await api(url);
    if(!Array.isArray(rows))rows=[];
    document.getElementById('m1Count').textContent=rows.length+' وظيفة';
    if(!rows.length){document.getElementById('m1Body').innerHTML='<div class="empty-state"><div class="icon">🔄</div>لا توجد وظائف</div>';return;}
    var th='<th>ID</th><th>Ref</th><th>Sender</th><th>EUR</th><th>FX Rate</th><th>USDT</th><th>Network</th><th>الحالة</th><th>Transfer</th><th>التاريخ</th><th>اجراء</th>';
    var tb=rows.map(function(r){return '<tr>'
      +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,10)+'...</code></td>'
      +'<td>'+(r.sender_reference||'—')+'</td>'
      +'<td>'+(r.sender_name||'—')+'</td>'
      +'<td><strong style="color:#fbbf24;">'+fmtNum(r.eur_amount)+' EUR</strong></td>'
      +'<td>'+(r.fx_rate||'—')+'</td>'
      +'<td>'+(r.usdt_amount?'<strong style="color:#a78bfa;">'+fmtNum(r.usdt_amount)+' USDT</strong>':'—')+'</td>'
      +'<td>'+((r.network||'').toUpperCase())+'</td>'
      +'<td>'+badge(r.status)+'</td>'
      +'<td>'+(r.outbound_transfer_id?'<code style="font-size:10px;">'+r.outbound_transfer_id.slice(0,10)+'...</code>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td>'+(r.status==='QUEUED'?'<button class="btn btn-primary" onclick="processJob(\\''+r.id+'\\')" style="font-size:11px;padding:3px 8px;">تشغيل</button>':'—')+'</td>'
      +'</tr>';}).join('');
    document.getElementById('m1Body').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }catch(e){document.getElementById('m1Body').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
loadFx();loadJobs();
setInterval(loadJobs,30000);
</script>
"""

# ─── MONITORING ───────────────────────────────────────────────────────────────

_MONITORING_BODY = """
<div class="page-body">
  <div class="filter-bar" style="justify-content:space-between;">
    <span id="monLastUp" style="color:var(--muted);font-size:12px;">—</span>
    <div style="display:flex;gap:8px;">
      <label style="color:var(--muted);font-size:12px;display:flex;align-items:center;gap:6px;">
        <input type="checkbox" id="autoR" checked onchange="toggleAuto()"> تحديث تلقائي (10 ثانية)
      </label>
      <button class="btn btn-ghost" onclick="loadMon()">تحديث</button>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
    <div class="panel"><div class="panel-head"><h3>الطلبات Orders</h3></div><div id="monOrders" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>التحويلات</h3></div><div id="monXfers" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>M1 Jobs</h3></div><div id="monM1" style="padding:14px;"></div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel"><div class="panel-head"><h3>Health Indicators</h3></div><div id="monHealth" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>Settlement Payloads</h3></div><div id="monPayloads" style="padding:14px;"></div></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>اخر 5 تحويلات</h3></div>
    <div id="monRecentXfer"></div>
  </div>
</div>
<script>
var _autoTimer=null;
function toggleAuto(){
  if(document.getElementById('autoR').checked){_autoTimer=setInterval(loadMon,10000);}
  else{clearInterval(_autoTimer);}
}
function _srows(byStatus,total){
  return Object.keys(byStatus).map(function(s){
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--line);">'+badge(s)+'<strong style="color:var(--ink);">'+byStatus[s]+'</strong></div>';
  }).join('')+'<div style="margin-top:10px;font-size:12px;color:var(--muted);">اجمالي: <strong style="color:var(--ink);">'+total+'</strong></div>';
}
async function loadMon(){
  try{
    var m=await api('/api/v1/admin/monitoring/live');
    document.getElementById('monLastUp').textContent='اخر تحديث: '+new Date().toLocaleTimeString('ar-SA');
    document.getElementById('monOrders').innerHTML  =_srows(m.orders&&m.orders.by_status||{},m.orders&&m.orders.total||0);
    document.getElementById('monXfers').innerHTML   =_srows(m.outbound_transfers&&m.outbound_transfers.by_status||{},m.outbound_transfers&&m.outbound_transfers.total||0);
    document.getElementById('monM1').innerHTML      =_srows(m.tokenization_jobs&&m.tokenization_jobs.by_status||{},m.tokenization_jobs&&m.tokenization_jobs.total||0);
    document.getElementById('monPayloads').innerHTML=_srows(m.payloads&&m.payloads.by_status||{},m.payloads&&m.payloads.total||0);
    var h=m.health||{};
    var usdt=m.outbound_transfers&&m.outbound_transfers.total_usdt_sent||0;
    var pa=h.pending_actions||0;
    document.getElementById('monHealth').innerHTML=
      '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);"><span style="color:var(--muted);">Database</span><strong style="color:'+(h.database==='ok'?'#10b981':'#ef4444')+';">'+(h.database==='ok'?'OK':'Issue')+'</strong></div>'
      +'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);"><span style="color:var(--muted);">Pending Actions</span><strong style="color:'+(pa>0?'#f59e0b':'#10b981')+';">'+pa+'</strong></div>'
      +'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);"><span style="color:var(--muted);">Total USDT Sent</span><strong style="color:#a78bfa;">'+fmtNum(usdt)+' USDT</strong></div>'
      +'<div style="display:flex;justify-content:space-between;padding:5px 0;"><span style="color:var(--muted);">M1 Awaiting Approval</span><strong style="color:'+(m.tokenization_jobs&&m.tokenization_jobs.m1_awaiting_approval>0?'#f59e0b':'#10b981')+';">'+(m.tokenization_jobs&&m.tokenization_jobs.m1_awaiting_approval||0)+'</strong></div>';
    var tr=m.outbound_transfers&&m.outbound_transfers.recent||[];
    if(tr.length){
      var th2='<th>ID</th><th>Network</th><th>Amount</th><th>الحالة</th><th>TX</th><th>التاريخ</th>';
      var tb2=tr.map(function(r){return '<tr><td><code style="font-size:10px;">'+r.id.slice(0,10)+'...</code></td><td>'+(r.network||'').toUpperCase()+'</td><td>'+fmtNum(r.amount)+' USDT</td><td>'+badge(r.status)+'</td><td>'+(r.tx_hash?r.tx_hash.slice(0,18)+'...':'—')+'</td><td style="font-size:11px;">'+fmtDate(r.created_at)+'</td></tr>';}).join('');
      document.getElementById('monRecentXfer').innerHTML='<div class="table-wrap"><table><thead><tr>'+th2+'</tr></thead><tbody>'+tb2+'</tbody></table></div>';
    }
  }catch(e){console.error('Monitor error:',e);}
}
loadMon();
_autoTimer=setInterval(loadMon,10000);
</script>
"""

# ─── PAYMENTS ─────────────────────────────────────────────────────────────────

_PAYMENTS_BODY = """
<div class="page-body">
  <div id="paySum" style="min-height:120px;"></div>
  <div class="panel">
    <div class="panel-head"><h3>توزيع بالحالة</h3><button class="btn btn-ghost" onclick="loadPayments()" style="font-size:11px;padding:4px 10px;">تحديث</button></div>
    <div id="payStatus" style="padding:14px;display:flex;flex-wrap:wrap;gap:10px;"></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>اخر الطلبات</h3></div>
    <div id="payTable"><div class="empty-state"><div class="icon">💳</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
async function loadPayments(){
  try{
    var s=await api('/api/v1/admin/summary');
    document.getElementById('paySum').innerHTML='<div class="stat-grid">'
      +'<div class="stat-card"><div class="label">اجمالي الطلبات</div><div class="value">'+(s.orders_total||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">مكتملة</div><div class="value" style="color:#10b981;">'+(s.orders_completed||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">معلقة</div><div class="value" style="color:#f59e0b;">'+(s.pending_orders||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">فاشلة</div><div class="value" style="color:#ef4444;">'+(s.failed_orders||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">اجمالي Fiat</div><div class="value">'+fmtNum(s.total_fiat_amount)+'</div></div>'
      +'<div class="stat-card"><div class="label">اجمالي Crypto</div><div class="value">'+fmtNum(s.total_crypto_amount,6)+'</div></div>'
      +'</div>';
    var bs=s.by_status||{};
    document.getElementById('payStatus').innerHTML=Object.keys(bs).map(function(st){return '<div style="padding:8px 14px;border-radius:8px;background:rgba(255,255,255,.05);border:1px solid var(--line);">'+badge(st)+' <strong style="margin-right:6px;">'+bs[st]+'</strong></div>';}).join('');
    var latest=s.latest_orders||[];
    if(latest.length){
      var th='<th>ID</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>الحالة</th><th>التاريخ</th>';
      var tb=latest.map(function(r){return '<tr>'
        +'<td><code style="font-size:10px;">'+r.id.slice(0,10)+'...</code></td>'
        +'<td>'+fmtNum(r.fiat_amount)+' '+(r.fiat_currency||'')+'</td>'
        +'<td>'+fmtNum(r.crypto_amount,6)+' '+(r.crypto_currency||'')+'</td>'
        +'<td>'+(r.network||'—')+'</td>'
        +'<td>'+badge(r.status)+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
        +'</tr>';}).join('');
      document.getElementById('payTable').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
    }else{document.getElementById('payTable').innerHTML='<div class="empty-state"><div class="icon">💳</div>لا توجد طلبات</div>';}
  }catch(e){console.error(e);}
}
loadPayments();
</script>
"""

# ─── ALCHEMY ──────────────────────────────────────────────────────────────────

_ALCHEMY_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <input id="alchQ" placeholder="بحث..." style="min-width:200px;" oninput="filterAlch()">
    <button class="btn btn-ghost" onclick="loadAlch()">تحديث</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>Alchemy Blockchain Events</h3><span id="alchCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="alchBody"><div class="empty-state"><div class="icon">⛓</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
var _alchRows=[];
async function loadAlch(){
  try{
    _alchRows=await api('/api/v1/admin/alchemy-events?limit=200');
    if(!Array.isArray(_alchRows))_alchRows=[];
    document.getElementById('alchCnt').textContent=_alchRows.length+' حدث';
    renderAlch(_alchRows);
  }catch(e){document.getElementById('alchBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
function filterAlch(){
  var q=document.getElementById('alchQ').value.toLowerCase();
  renderAlch(q?_alchRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_alchRows);
}
function renderAlch(rows){
  if(!rows.length){document.getElementById('alchBody').innerHTML='<div class="empty-state"><div class="icon">⛓</div>لا توجد احداث Alchemy</div>';return;}
  var th='<th>Event Type</th><th>Order ID</th><th>TX ID</th><th>Status</th><th>IP</th><th>Details</th><th>التاريخ</th>';
  var tb=rows.map(function(r){return '<tr>'
    +'<td><strong style="color:var(--brand);">'+r.event_type+'</strong></td>'
    +'<td>'+(r.order_id?'<code style="font-size:10px;">'+r.order_id.slice(0,10)+'...</code>':'—')+'</td>'
    +'<td>'+(r.transaction_id?'<code style="font-size:10px;" title="'+r.transaction_id+'">'+r.transaction_id.slice(0,14)+'...</code>':'—')+'</td>'
    +'<td>'+(r.status_code?'<span style="color:'+(r.status_code<300?'#10b981':'#ef4444')+';">'+r.status_code+'</span>':'—')+'</td>'
    +'<td>'+(r.ip||'—')+'</td>'
    +'<td>'+(r.details?'<code style="font-size:10px;">'+JSON.stringify(r.details).slice(0,50)+'...</code>':'—')+'</td>'
    +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
    +'</tr>';}).join('');
  document.getElementById('alchBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
loadAlch();
</script>
"""

# ─── COUNTERPARTIES ───────────────────────────────────────────────────────────

_COUNTERPARTIES_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <button class="btn btn-ghost" onclick="loadClients()">تحديث</button>
    <button class="btn btn-primary" onclick="toggleAddCl()">+ اضافة Counterparty</button>
  </div>

  <div id="addClForm" style="display:none;" class="panel">
    <div class="panel-head"><h3>اضافة Counterparty جديد</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>الاسم *</label><input id="clName" placeholder="اسم الطرف المقابل"></div>
        <div class="form-field"><label>IPs المسموحة (فاصلة)</label><input id="clIps" placeholder="1.2.3.4,5.6.7.8 (اختياري)"></div>
        <div class="form-field" style="grid-column:span 2;">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
            <input type="checkbox" id="clHmac" style="width:auto;"> تطلب HMAC Signature
          </label>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-success" onclick="addClient()">انشاء</button>
        <button class="btn btn-ghost" onclick="toggleAddCl()">الغاء</button>
      </div>
    </div>
  </div>

  <div id="clCreated" style="display:none;" class="panel">
    <div class="panel-head"><h3>تم انشاء الـ Client — احفظ هذه البيانات الان</h3></div>
    <div id="clCreatedBody" style="padding:16px;font-size:12px;"></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>قائمة الـ Counterparties</h3><span id="clCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="clBody"><div class="empty-state"><div class="icon">🔑</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
function toggleAddCl(){
  var el=document.getElementById('addClForm');
  el.style.display=el.style.display==='none'?'block':'none';
}
async function addClient(){
  var ips=document.getElementById('clIps').value.trim();
  var body={name:document.getElementById('clName').value.trim(),allowed_ips:ips?ips.split(',').map(function(s){return s.trim();}).filter(Boolean):null,hmac_required:document.getElementById('clHmac').checked};
  if(!body.name){showToast('الاسم مطلوب','error');return;}
  try{
    var r=await api('/api/v1/admin/clients',{method:'POST',body:JSON.stringify(body)});
    var fields=[['Client ID',r.id],['API Key',r.api_key],['HMAC Secret',r.hmac_secret||'—'],['OAuth Client ID',r.oauth_client_id||'—'],['OAuth Client Secret',r.oauth_client_secret||'—']];
    document.getElementById('clCreatedBody').innerHTML=
      '<div style="padding:10px;background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);border-radius:8px;margin-bottom:12px;color:#10b981;font-weight:700;">احفظ هذه المعلومات الان - لن تعرض مرة اخرى</div>'
      +fields.map(function(f){return '<div style="display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line);"><span style="color:var(--muted);min-width:160px;">'+f[0]+'</span><code style="word-break:break-all;flex:1;">'+f[1]+'</code><button class="btn btn-ghost" onclick="copyText(\\''+f[1]+'\\')" style="font-size:10px;padding:2px 8px;">نسخ</button></div>';}).join('');
    document.getElementById('clCreated').style.display='block';
    document.getElementById('clCreated').scrollIntoView({behavior:'smooth'});
    toggleAddCl();loadClients();
  }catch(e){showToast('خطأ: '+e.message,'error');}
}
async function toggleClient(id,active){
  try{await api('/api/v1/admin/clients/'+id,{method:'PATCH',body:JSON.stringify({is_active:active})});showToast(active?'تم التفعيل':'تم التعطيل','ok');loadClients();}
  catch(e){showToast('خطأ: '+e.message,'error');}
}
async function loadClients(){
  try{
    var rows=await api('/api/v1/admin/clients');
    if(!Array.isArray(rows))rows=[];
    document.getElementById('clCnt').textContent=rows.length+' client';
    if(!rows.length){document.getElementById('clBody').innerHTML='<div class="empty-state"><div class="icon">🔑</div>لا يوجد clients</div>';return;}
    var th='<th>ID</th><th>Name</th><th>Active</th><th>HMAC</th><th>OAuth</th><th>mTLS</th><th>JWS</th><th>IPs</th><th>تاريخ الانشاء</th><th>اجراء</th>';
    var tb=rows.map(function(r){return '<tr>'
      +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,12)+'...</code></td>'
      +'<td><strong>'+r.name+'</strong></td>'
      +'<td>'+(r.is_active?'<span style="color:#10b981;font-weight:700;">نشط</span>':'<span style="color:#ef4444;">معطل</span>')+'</td>'
      +'<td>'+(r.hmac_required?'<span style="color:#10b981;">نعم</span>':'—')+'</td>'
      +'<td>'+(r.oauth_required?'<span style="color:#10b981;">نعم</span>':'—')+'</td>'
      +'<td>'+(r.mtls_required?'<span style="color:#10b981;">نعم</span>':'—')+'</td>'
      +'<td>'+(r.jws_required?'<span style="color:#10b981;">نعم</span>':'—')+'</td>'
      +'<td>'+((r.allowed_ips||[]).length?r.allowed_ips.join(', '):'اي IP')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><button class="btn '+(r.is_active?'btn-danger':'btn-success')+'" onclick="toggleClient(\\''+r.id+'\\','+(r.is_active?'false':'true')+')" style="font-size:11px;padding:3px 8px;">'+(r.is_active?'تعطيل':'تفعيل')+'</button></td>'
      +'</tr>';}).join('');
    document.getElementById('clBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }catch(e){document.getElementById('clBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
loadClients();
</script>
"""

# ─── SECURITY ─────────────────────────────────────────────────────────────────

_SECURITY_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <input id="secQ" placeholder="بحث..." style="min-width:200px;" oninput="filterSec()">
    <button class="btn btn-ghost" onclick="loadSec()">تحديث</button>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Security Posture — Counterparties</h3></div>
    <div id="secPosture" style="padding:14px;"></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>احداث الامان</h3><span id="secCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="secBody"><div class="empty-state"><div class="icon">🛡</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
var _secRows=[];
async function loadSec(){
  try{
    var p=await api('/api/v1/admin/clients/security-posture');
    var rows=Array.isArray(p)?p:(p.clients||[]);
    if(rows.length){
      var th='<th>Client</th><th>Score</th><th>HMAC</th><th>OAuth</th><th>mTLS</th><th>JWS</th><th>IP List</th><th>Posture</th>';
      var tb=rows.map(function(r){return '<tr>'
        +'<td>'+r.name+'</td>'
        +'<td><strong style="color:'+(r.score>=4?'#10b981':r.score>=2?'#f59e0b':'#ef4444')+';">'+(r.score||0)+'/6</strong></td>'
        +'<td>'+(r.hmac_required?'نعم':'—')+'</td>'
        +'<td>'+(r.oauth_required?'نعم':'—')+'</td>'
        +'<td>'+(r.mtls_required?'نعم':'—')+'</td>'
        +'<td>'+(r.jws_required?'نعم':'—')+'</td>'
        +'<td>'+((r.allowed_ips||[]).length?'نعم':'—')+'</td>'
        +'<td>'+badge(r.posture||'UNKNOWN')+'</td>'
        +'</tr>';}).join('');
      document.getElementById('secPosture').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
    }else{document.getElementById('secPosture').innerHTML='<p style="color:var(--muted);text-align:center;padding:16px;">لا توجد بيانات</p>';}
  }catch(e){document.getElementById('secPosture').innerHTML='<p style="color:var(--muted);">'+e.message+'</p>';}
  try{
    _secRows=await api('/api/v1/admin/security-events');
    if(!Array.isArray(_secRows))_secRows=[];
    document.getElementById('secCnt').textContent=_secRows.length+' حدث';
    renderSec(_secRows);
  }catch(e){document.getElementById('secBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
function filterSec(){
  var q=document.getElementById('secQ').value.toLowerCase();
  renderSec(q?_secRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_secRows);
}
function renderSec(rows){
  if(!rows.length){document.getElementById('secBody').innerHTML='<div class="empty-state"><div class="icon">🛡</div>لا توجد احداث امان</div>';return;}
  var th='<th>Event</th><th>IP</th><th>Path</th><th>Status</th><th>User Agent</th><th>التاريخ</th>';
  var tb=rows.map(function(r){
    var isAlert=r.event_type&&(r.event_type.indexOf('BLOCK')>=0||r.event_type.indexOf('BAN')>=0);
    return '<tr>'
      +'<td><strong style="color:'+(isAlert?'#ef4444':'var(--brand)')+';">'+r.event_type+'</strong></td>'
      +'<td>'+(r.ip||(r.details&&r.details.ip)||'—')+'</td>'
      +'<td><code style="font-size:10px;">'+(r.endpoint||(r.details&&r.details.path)||'—')+'</code></td>'
      +'<td>'+(r.status_code?'<span style="color:'+(r.status_code<300?'#10b981':r.status_code<400?'#f59e0b':'#ef4444')+';">'+r.status_code+'</span>':'—')+'</td>'
      +'<td><span style="font-size:10px;color:var(--muted);" title="'+(r.user_agent||'')+'">'+((r.user_agent||'—').slice(0,30))+'</span></td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'</tr>';}).join('');
  document.getElementById('secBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
loadSec();
</script>
"""

# ─── DOCUMENTS ────────────────────────────────────────────────────────────────

_DOCUMENTS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <button class="btn btn-ghost" onclick="loadDocs()">تحديث</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>مستندات الطلبات</h3><span id="docsCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="docsBody"><div class="empty-state"><div class="icon">📄</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
async function loadDocs(){
  try{
    var rows=await api('/api/v1/admin/documents?limit=100');
    if(!Array.isArray(rows))rows=[];
    document.getElementById('docsCnt').textContent=rows.length+' مستند';
    if(!rows.length){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">📄</div>لا توجد مستندات</div>';return;}
    var th='<th>Order ID</th><th>External ID</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>الحالة</th><th>التاريخ</th><th>مستندات</th>';
    var tb=rows.map(function(r){return '<tr>'
      +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,10)+'...</code></td>'
      +'<td>'+(r.external_id||'—')+'</td>'
      +'<td>'+fmtNum(r.fiat_amount)+' '+(r.fiat_currency||'')+'</td>'
      +'<td>'+fmtNum(r.crypto_amount,6)+' '+(r.crypto_currency||'')+'</td>'
      +'<td>'+(r.network||'—')+'</td>'
      +'<td>'+badge(r.status)+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><div style="display:flex;gap:4px;">'
        +'<a href="/api/v1/admin/orders/'+r.id+'/documents/invoice" target="_blank" style="padding:2px 8px;border-radius:5px;background:rgba(79,142,247,.15);color:var(--brand);font-size:11px;text-decoration:none;border:1px solid rgba(79,142,247,.3);">Invoice</a>'
        +'<a href="/api/v1/admin/orders/'+r.id+'/documents/receive-receipt" target="_blank" style="padding:2px 8px;border-radius:5px;background:rgba(16,185,129,.1);color:#10b981;font-size:11px;text-decoration:none;border:1px solid rgba(16,185,129,.2);">Receipt</a>'
        +'</div></td>'
      +'</tr>';}).join('');
    document.getElementById('docsBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }catch(e){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
loadDocs();
</script>
"""

# ─── AUDIT LOGS ───────────────────────────────────────────────────────────────

_LOGS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="logLim" onchange="loadLogs()" style="min-width:110px;">
      <option value="50">50 سجل</option>
      <option value="100" selected>100 سجل</option>
      <option value="250">250 سجل</option>
      <option value="500">500 سجل</option>
    </select>
    <input id="logQ" placeholder="بحث..." style="min-width:200px;" oninput="filterLogs()">
    <button class="btn btn-ghost" onclick="loadLogs()">تحديث</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>سجل التدقيق</h3><span id="logCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="logBody"><div class="empty-state"><div class="icon">📝</div>جاري التحميل...</div></div>
  </div>
</div>
<script>
var _logRows=[];
async function loadLogs(){
  var lim=document.getElementById('logLim').value;
  try{
    _logRows=await api('/api/v1/admin/audit-logs?limit='+lim);
    if(!Array.isArray(_logRows))_logRows=[];
    document.getElementById('logCnt').textContent=_logRows.length+' سجل';
    filterLogs();
  }catch(e){document.getElementById('logBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';}
}
function filterLogs(){
  var q=document.getElementById('logQ').value.toLowerCase();
  renderLogs(q?_logRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_logRows);
}
function renderLogs(rows){
  if(!rows.length){document.getElementById('logBody').innerHTML='<div class="empty-state"><div class="icon">📝</div>لا توجد سجلات</div>';return;}
  var th='<th>Event</th><th>Order ID</th><th>Client</th><th>Method</th><th>Endpoint</th><th>IP</th><th>Status</th><th>TX ID</th><th>Error</th><th>التاريخ</th>';
  var tb=rows.map(function(r){return '<tr>'
    +'<td><strong style="color:var(--brand);font-size:11px;">'+r.event_type+'</strong></td>'
    +'<td>'+(r.order_id?'<code style="font-size:10px;">'+r.order_id.slice(0,10)+'...</code>':'—')+'</td>'
    +'<td>'+(r.client_id?'<code style="font-size:10px;">'+r.client_id.slice(0,10)+'...</code>':'—')+'</td>'
    +'<td>'+(r.method||'—')+'</td>'
    +'<td><code style="font-size:10px;">'+((r.endpoint||'—').slice(0,40))+'</code></td>'
    +'<td>'+(r.ip||'—')+'</td>'
    +'<td>'+(r.status_code?'<span style="color:'+(r.status_code<300?'#10b981':r.status_code<400?'#f59e0b':'#ef4444')+';">'+r.status_code+'</span>':'—')+'</td>'
    +'<td>'+(r.transaction_id?'<code style="font-size:10px;">'+r.transaction_id.slice(0,12)+'...</code>':'—')+'</td>'
    +'<td>'+(r.error_message?'<span style="color:#f87171;font-size:11px;">'+r.error_message.slice(0,40)+'</span>':'—')+'</td>'
    +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
    +'</tr>';}).join('');
  document.getElementById('logBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
loadLogs();
</script>
"""


# ═══════════════════════════════════════════════════════════════════
# ROUTE HANDLERS
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("نظرة عامة", "/dashboard", _OVERVIEW_BODY))


@router.get("/dashboard/overview", response_class=HTMLResponse)
async def dashboard_overview(request: Request):
    return RedirectResponse("/dashboard", status_code=http_status.HTTP_302_FOUND)


@router.get("/dashboard/orders", response_class=HTMLResponse)
async def dashboard_orders(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("الطلبات", "/dashboard/orders", _ORDERS_BODY))


@router.get("/dashboard/payloads", response_class=HTMLResponse)
async def dashboard_payloads(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Settlement Payloads", "/dashboard/payloads", _PAYLOADS_BODY))


@router.get("/dashboard/transfers", response_class=HTMLResponse)
async def dashboard_transfers(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Outbound Transfers", "/dashboard/transfers", _TRANSFERS_BODY))


@router.get("/dashboard/tokenization", response_class=HTMLResponse)
async def dashboard_tokenization(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("M1 Tokenization", "/dashboard/tokenization", _TOKENIZATION_BODY))


@router.get("/dashboard/monitoring", response_class=HTMLResponse)
async def dashboard_monitoring(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Live Monitoring", "/dashboard/monitoring", _MONITORING_BODY))


@router.get("/dashboard/payments", response_class=HTMLResponse)
async def dashboard_payments(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("المدفوعات", "/dashboard/payments", _PAYMENTS_BODY))


@router.get("/dashboard/alchemy", response_class=HTMLResponse)
async def dashboard_alchemy(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Alchemy Events", "/dashboard/alchemy", _ALCHEMY_BODY))


@router.get("/dashboard/counterparties", response_class=HTMLResponse)
async def dashboard_counterparties(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Counterparties", "/dashboard/counterparties", _COUNTERPARTIES_BODY))


@router.get("/dashboard/security", response_class=HTMLResponse)
async def dashboard_security(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Security", "/dashboard/security", _SECURITY_BODY))


@router.get("/dashboard/documents", response_class=HTMLResponse)
async def dashboard_documents(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Documents", "/dashboard/documents", _DOCUMENTS_BODY))


@router.get("/dashboard/logs", response_class=HTMLResponse)
async def dashboard_logs(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Audit Logs", "/dashboard/logs", _LOGS_BODY))


@router.post("/dashboard/logout")
async def dashboard_logout():
    """Clear the admin session cookie."""
    response = Response(content="OK")
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return response
