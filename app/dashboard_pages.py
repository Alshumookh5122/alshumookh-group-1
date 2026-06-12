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
  GET /dashboard/stripe         → Stripe payment links and Checkout
  GET /dashboard/alchemy        → Alchemy Events
  GET /dashboard/counterparties → API Clients / Counterparties
  GET /dashboard/security       → Security Events
  GET /dashboard/documents      → Documents
  GET /dashboard/logs           → Audit Logs
  GET /dashboard/overview       → redirect → /dashboard
  POST /dashboard/logout        → clear session cookie
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status as http_status

import hmac

from app.auth import ADMIN_SESSION_COOKIE, is_admin_request_authenticated
from app.config import settings
from app.database import get_db
from app.models import (
    ApiClient,
    AuditLog,
    ExternalPayload,
    M1TokenizationJob,
    M1TokenizationStatus,
    OrderStatus,
    OutboundTransfer,
    OutboundTransferStatus,
    PaymentOrder,
)

router = APIRouter(tags=["dashboard-pages"])

# ═══════════════════════════════════════════════════════════════════
# SHARED HTML COMPONENTS
# ═══════════════════════════════════════════════════════════════════

_SIDEBAR_LINKS = [
    ("/dashboard",               "🏠", "Overview"),
    ("/dashboard/orders",        "📋", "Orders"),
    ("/dashboard/payloads",      "📥", "Settlement Payloads"),
    ("/dashboard/transfers",     "🚀", "Outbound Transfers"),
    ("/dashboard/tokenization",  "🔄", "M1 Tokenization"),
    ("/dashboard/m1-reserve",    "🏦", "M1 Reserve"),
    ("/dashboard/monitoring",    "📊", "Live Monitoring"),
    ("/dashboard/payments",      "💳", "Payments"),
    ("/dashboard/payments#moonpay", "🌙", "MoonPay"),
    ("/dashboard/payments#circle",  "⬤", "Circle USDC"),
    ("/dashboard/payments#direct",  "🔑", "Direct Crypto"),
    ("/dashboard/stripe",        "💵", "Stripe"),
    ("/dashboard/alchemy",       "⛓", "Alchemy Events"),
    ("/dashboard/counterparties","🔑", "Counterparties"),
    ("/dashboard/security",      "🛡", "Security"),
    ("/dashboard/documents",     "📄", "Documents"),
    ("/dashboard/reports",       "📊", "Reports"),
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
      &#9211; Logout
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
    <button class="btn btn-primary" onclick="saveTopAK()" style="padding:7px 10px;font-size:11px;">Save Key</button>
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
    if(el) el.textContent=new Date().toLocaleTimeString('en-US');
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
// ── Safe storage read (works even if storage is blocked) ─────────────────────
var AK = '';
try {
  AK = (sessionStorage.getItem('als_admin_key')||localStorage.getItem('als_admin_key')||'');
} catch(_se) {
  try { var _m=document.cookie.match(/als_ak=([^;]+)/); AK=_m?decodeURIComponent(_m[1]):''; } catch(_ce){}
}

// ── Global JS error visibility ────────────────────────────────────────────────
window.onerror = function(msg, src, line, col, err) {
  try {
    var d = document.getElementById('_js_err_bar');
    if(!d){ d=document.createElement('div'); d.id='_js_err_bar';
      d.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999999;background:#dc2626;color:#fff;padding:8px 16px;font-size:11px;font-family:monospace;word-break:break-all;';
      document.body&&document.body.appendChild(d); }
    d.textContent='JS Error: '+msg+' (line '+line+')';
  } catch(e2){}
  return false;
};

function syncAKInputs(){
  try{
    var top=document.getElementById('_top_ak_inp');
    var inp=document.getElementById('_ak_inp');
    if(top && AK) top.value=AK;
    if(inp && AK) inp.value=AK;
  }catch(e){}
}

// ── API Key Banner ────────────────────────────────────────────────────────────
try {
  var banner = document.createElement('div');
  banner.id = '_ak_banner';
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#1d4ed8,#2563eb);padding:10px 20px;display:flex;align-items:center;gap:12px;font-size:13px;color:#fff;box-shadow:0 4px 20px rgba(0,0,0,.4);';
  banner.innerHTML = '<span style="font-weight:700;">🔑 Admin API Key:</span>'
    +'<input id="_ak_inp" type="password" placeholder="Enter Admin API Key, then click Save..." '
    +'style="flex:1;max-width:440px;padding:7px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);color:#fff;font-size:13px;outline:none;" />'
    +'<button onclick="saveAK()" style="padding:7px 18px;border-radius:8px;background:#fff;color:#1d4ed8;font-weight:700;border:none;cursor:pointer;font-size:13px;">Save</button>'
    +'<button onclick="(function(){var b=document.getElementById(\\'_ak_banner\\');if(b)b.style.display=\\'none\\';})()" style="padding:7px 14px;border-radius:8px;background:rgba(255,255,255,.15);color:#fff;border:none;cursor:pointer;font-size:12px;">✕</button>';
  if(document.body) document.body.insertBefore(banner, document.body.firstChild);
  syncAKInputs();
  if(AK){
    banner.style.display='none';
    var ind = document.createElement('div');
    ind.id='_ak_ind';
    ind.style.cssText='position:fixed;bottom:24px;left:24px;z-index:9998;background:rgba(5,150,105,.9);color:#fff;padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;';
    ind.textContent='API Key set';
    ind.onclick=function(){var b=document.getElementById('_ak_banner');if(b)b.style.display='flex';};
    if(document.body) document.body.appendChild(ind);
  }
} catch(_berr) { console.error('Banner init error:', _berr); }

function saveAK(){
  try{
    var v=(document.getElementById('_ak_inp')||{}).value||'';
    v=v.trim();
    if(!v){alert('Enter Admin API Key first');return;}
    AK=v;
    try{sessionStorage.setItem('als_admin_key',v);}catch(e){}
    try{localStorage.setItem('als_admin_key',v);}catch(e){}
    try{document.cookie='als_ak='+encodeURIComponent(v)+';path=/;max-age=86400;samesite=lax';}catch(e){}
    try{var b=document.getElementById('_ak_banner');if(b)b.style.display='none';}catch(e){}
    showToast('Admin API Key saved. Refreshing...','ok');
    setTimeout(function(){location.reload();},1200);
  }catch(e){alert('Error: '+e.message);}
}

function saveTopAK(){
  try{
    var v=(document.getElementById('_top_ak_inp')||{}).value||'';
    v=v.trim();
    if(!v){alert('Enter Admin API Key first');return;}
    AK=v;
    try{sessionStorage.setItem('als_admin_key',v);}catch(e){}
    try{localStorage.setItem('als_admin_key',v);}catch(e){}
    try{document.cookie='als_ak='+encodeURIComponent(v)+';path=/;max-age=86400;samesite=lax';}catch(e){}
    syncAKInputs();
    showToast('Admin API Key saved. Refreshing...','ok');
    setTimeout(function(){location.reload();},900);
  }catch(e){alert('Error: '+e.message);}
}

function H(extra) {
  var h = {'Content-Type':'application/json'};
  if(AK) h['X-Admin-API-Key'] = AK;
  if(extra) Object.assign(h,extra);
  return h;
}

function api(url, opts) {
  opts = opts||{};
  var method = opts.method||'GET';
  var headers = H(opts.headers||{});
  var body = opts.body||null;
  function _errMsg(d, status) {
    if(!d) return 'HTTP '+status;
    if(typeof d.detail === 'string') return d.detail;
    if(typeof d.message === 'string') return d.message;
    if(d.detail) {
      try { return JSON.stringify(d.detail); } catch(ex) {}
    }
    try { return JSON.stringify(d); } catch(ex) {}
    return 'HTTP '+status;
  }
  function _authErr(status) {
    try{ var b=document.getElementById('_ak_banner'); if(b)b.style.display='flex'; }catch(ex){}
    showToast('Authentication failed. Enter the Admin API Key.','error');
  }
  if(typeof fetch !== 'undefined') {
    return fetch(url,{method:method,headers:headers,credentials:'include',body:body}).then(function(r){
      if(r.status===401||r.status===403){ _authErr(r.status); throw new Error('Unauthorized - HTTP '+r.status); }
      if(!r.ok){
        return r.json().then(function(d){ throw new Error(_errMsg(d, r.status)); },
                             function(){ throw new Error('HTTP '+r.status); });
      }
      return r.json();
    });
  }
  return new Promise(function(resolve,reject){
    var xhr=new XMLHttpRequest();
    xhr.open(method,url,true); xhr.withCredentials=true; xhr.timeout=30000;
    Object.keys(headers).forEach(function(k){ try{xhr.setRequestHeader(k,headers[k]);}catch(e){} });
    xhr.onreadystatechange=function(){
      if(xhr.readyState!==4) return;
      if(xhr.status===401||xhr.status===403){ _authErr(xhr.status); reject(new Error('Unauthorized - HTTP '+xhr.status)); return; }
      if(xhr.status>=200&&xhr.status<300){ try{resolve(JSON.parse(xhr.responseText));}catch(e){reject(new Error('Parse error'));} }
      else{ var msg='HTTP '+xhr.status; try{msg=_errMsg(JSON.parse(xhr.responseText), xhr.status);}catch(e){} reject(new Error(msg)); }
    };
    xhr.onerror=function(){reject(new Error('Network Error'));};
    xhr.ontimeout=function(){reject(new Error('Timeout'));};
    xhr.send(body);
  });
}

function dashboardUrl(url){
  url=String(url||'');
  var qIdx=url.indexOf('?');
  var path=qIdx>=0?url.slice(0,qIdx):url;
  var qs=qIdx>=0?url.slice(qIdx):'';
  var m={
    '/api/v1/admin/monitoring/live':'/dashboard/api/monitoring/live',
    '/api/v1/admin/system/readiness':'/dashboard/api/system/readiness',
    '/api/v1/admin/payloads':'/dashboard/api/payloads',
    '/api/v1/admin/summary':'/dashboard/api/summary'
  };
  return (m[path]||path)+qs;
}

function dashApi(url, opts){
  return api(dashboardUrl(url), opts);
}

function esc(v){
  return String(v || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}

function badge(s){
  var m={
    'COMPLETED':'#10b981','CONFIRMED':'#10b981','APPROVED':'#10b981','VERIFIED':'#10b981','RECONCILED':'#10b981',
    'ON_CHAIN_CONFIRMED':'#10b981','ALCHEMY_VERIFIED':'#10b981',
    'PENDING':'#f59e0b','PENDING_CONFIRMATION':'#f59e0b','QUEUED':'#f59e0b','AWAITING_APPROVAL':'#f59e0b',
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
  return new Date(d).toLocaleString('en-US',{dateStyle:'short',timeStyle:'short'});
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
  navigator.clipboard.writeText(txt).then(function(){showToast('Copied','ok');});
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
        '<html lang="en" dir="ltr">\n'
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
        + _SHARED_JS
        + body
        + "\n</main>\n"
        + "\n</body>\n</html>"
    )


def _guard(request: Request):
    """Return RedirectResponse if not authenticated, else None."""
    if not is_admin_request_authenticated(request):
        return RedirectResponse("/login?type=admin", status_code=http_status.HTTP_302_FOUND)
    return None


def _guard_api(request: Request) -> None:
    # Accept: session cookie, als_ak cookie, OR X-Admin-API-Key header
    if is_admin_request_authenticated(request):
        return
    expected_key = str(settings.admin_api_key or '')
    header_key = str(request.headers.get('X-Admin-API-Key') or '')
    if expected_key and header_key and hmac.compare_digest(header_key, expected_key):
        return
    raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _dt(value):
    return value.isoformat() if value else None


def _payload_row(p: ExternalPayload) -> dict:
    return {
        "id": p.id,
        "payload_id": p.id,
        "transaction_reference": p.transaction_reference,
        "tx_hash": p.tx_hash,
        "sender_wallet": p.sender_wallet,
        "receiver_wallet": p.receiver_wallet,
        "amount": str(p.amount) if p.amount is not None else None,
        "asset": p.asset,
        "network": p.network_name,
        "network_name": p.network_name,
        "verification_status": p.verification_status,
        "security_level": p.security_level,
        "client_ip": p.client_ip,
        "created_at": _dt(p.created_at),
        "updated_at": _dt(p.updated_at),
    }


# ═══════════════════════════════════════════════════════════════════
# PAGE BODIES
# ═══════════════════════════════════════════════════════════════════

_OVERVIEW_BODY = """
<div class="page-body">
  <div id="dashDebug" style="margin-bottom:14px;padding:10px 14px;border-radius:10px;border:1px solid rgba(59,130,246,.30);background:rgba(59,130,246,.08);color:#bfdbfe;font-size:12px;font-weight:700;">
    Loading dashboard overview...
  </div>

  <div class="stat-grid">
    <div class="stat-card"><div class="label">Total Orders</div><div class="value" id="sTotal">—</div></div>
    <div class="stat-card"><div class="label">Completed</div><div class="value" id="sCompleted" style="color:#10b981;">—</div></div>
    <div class="stat-card"><div class="label">Settlement Payloads</div><div class="value" id="sPayloads">—</div></div>
    <div class="stat-card"><div class="label">USDT Sent</div><div class="value" id="sUsdt" style="color:#a78bfa;">—</div><div class="sub">Completed total</div></div>
    <div class="stat-card"><div class="label">Pending Transfers</div><div class="value" id="sPending" style="color:#f59e0b;">—</div></div>
    <div class="stat-card"><div class="label">M1 Jobs</div><div class="value" id="sM1">—</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Recent Events</h3></div>
      <div id="recentEvents" style="padding:12px 16px;min-height:80px;"></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Recent Transfers</h3></div>
      <div id="recentTransfers" style="padding:12px 16px;min-height:80px;"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Settlement Payloads - Status Distribution</h3></div>
    <div id="payloadStatus" style="padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;min-height:40px;"></div>
  </div>

  <!-- Settlement Payloads List with Actions -->
  <div class="panel" id="ovPlPanel">
    <div class="panel-head">
      <h3>Settlement Payloads - Quick Actions</h3>
      <button class="btn btn-ghost" onclick="loadOvPayloads()" style="font-size:11px;padding:4px 10px;">Refresh</button>
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
          <button class="btn btn-ghost"   onclick="ovClosePayload()" style="font-size:11px;">Close</button>
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
    <div id="ovPlBody" style="padding:0;"><div class="empty-state"><div class="icon">📥</div>Loading...</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>System Readiness</h3>
      <button class="btn btn-ghost" onclick="loadOverview()" style="font-size:11px;padding:4px 10px;">Refresh</button>
    </div>
    <div id="readinessBody" style="padding:14px 16px;"></div>
  </div>
</div>

<script>
function setOverviewDebug(message, ok) {
  try {
    var el = document.getElementById('dashDebug');
    if (!el) return;
    el.style.borderColor = ok ? 'rgba(16,185,129,.35)' : 'rgba(239,68,68,.35)';
    el.style.background = ok ? 'rgba(16,185,129,.08)' : 'rgba(239,68,68,.08)';
    el.style.color = ok ? '#86efac' : '#fca5a5';
    el.textContent = message;
  } catch(e) {}
}

function setOverviewStats(value) {
  ['sTotal','sCompleted','sPayloads','sUsdt','sPending','sM1'].forEach(function(id) {
    try { document.getElementById(id).textContent = value; } catch(e) {}
  });
}

function loadOverview() {
  console.log("Loading dashboard overview...");
  setOverviewDebug('Loading dashboard overview... /dashboard/api/monitoring/live', true);
  setOverviewStats('...');
  try{ document.getElementById('readinessBody').innerHTML='<p style="color:var(--muted);font-size:12px;">Connecting to server...</p>'; }catch(e){}
  dashApi('/api/v1/admin/monitoring/live').then(function(m) {
    console.log("Dashboard monitoring data:", m);
    setOverviewDebug('Dashboard API OK: /dashboard/api/monitoring/live', true);
    document.getElementById('sTotal').textContent     = (m.orders && m.orders.total)||0;
    document.getElementById('sCompleted').textContent = (m.orders && m.orders.by_status && m.orders.by_status['COMPLETED'])||0;
    document.getElementById('sPayloads').textContent  = (m.payloads && m.payloads.total)||0;
    document.getElementById('sUsdt').textContent      = fmtNum((m.outbound_transfers && m.outbound_transfers.total_usdt_sent)||0) + ' USDT';
    document.getElementById('sPending').textContent   = (m.outbound_transfers && m.outbound_transfers.pending_approvals)||0;
    document.getElementById('sM1').textContent        = (m.tokenization_jobs && m.tokenization_jobs.total)||0;

    var ev = (m.recent_events)||[];
    document.getElementById('recentEvents').innerHTML = ev.length
      ? ev.map(function(e){return '<div style="padding:7px 0;border-bottom:1px solid var(--line);font-size:12px;"><span style="color:var(--gold);font-weight:700;">'+e.event_type+'</span><span style="float:left;color:var(--muted);font-size:11px;">'+fmtDate(e.created_at)+'</span></div>';}).join('')
      : '<p style="color:var(--muted);text-align:center;padding:16px;">No events found</p>';

    var tr = (m.outbound_transfers && m.outbound_transfers.recent)||[];
    document.getElementById('recentTransfers').innerHTML = tr.length
      ? tr.map(function(t){return '<div style="padding:7px 0;border-bottom:1px solid var(--line);font-size:12px;"><span style="color:var(--brand);font-weight:600;">'+(t.network||'').toUpperCase()+'</span><span style="margin:0 8px;">'+fmtNum(t.amount)+' USDT</span>'+badge(t.status)+'<div style="color:var(--muted);font-size:11px;margin-top:2px;">'+(t.tx_hash?t.tx_hash.slice(0,22)+'...':'No TX yet')+'</div></div>';}).join('')
      : '<p style="color:var(--muted);text-align:center;padding:16px;">No transfers found</p>';

    var ps = (m.payloads && m.payloads.by_status)||{};
    var psKeys = Object.keys(ps);
    document.getElementById('payloadStatus').innerHTML = psKeys.length
      ? psKeys.map(function(s){return '<div style="padding:8px 14px;border-radius:8px;background:rgba(255,255,255,.05);border:1px solid var(--line);">'+badge(s)+' <strong style="color:var(--ink);margin-right:6px;">'+ps[s]+'</strong></div>';}).join('')
      : '<p style="color:var(--muted);">No data available</p>';
  }).catch(function(e) {
    var errMsg = e.message||'Unknown error';
    console.error('Dashboard overview failed:', e);
    setOverviewDebug('Dashboard API FAILED: '+errMsg+' — route /dashboard/api/monitoring/live', false);
    setOverviewStats('ERR');
    document.getElementById('recentEvents').innerHTML='<p style="color:#ef4444;text-align:center;padding:16px;font-size:12px;">Load failed: '+errMsg+'</p>';
    document.getElementById('recentTransfers').innerHTML='<p style="color:#ef4444;text-align:center;padding:16px;font-size:12px;">Load failed: '+errMsg+'</p>';
    document.getElementById('payloadStatus').innerHTML='<p style="color:#ef4444;font-size:12px;">Load failed</p>';
    document.getElementById('ovPlBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+errMsg+'</div>';
    document.getElementById('readinessBody').innerHTML =
      '<div style="background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.3);border-radius:10px;padding:16px;">'
      +'<div style="color:#f87171;font-weight:700;margin-bottom:8px;">Connection failed - error: '+errMsg+'</div>'
      +'<div style="font-size:12px;color:var(--muted);margin-bottom:8px;">Make sure the correct Admin API Key is entered.</div>'
      +'<button onclick="var b=document.getElementById(&quot;_ak_banner&quot;);if(b){b.style.display=&quot;flex&quot;;}" '
      +'style="background:#2563eb;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:700;">Enter API Key</button>'
      +'</div>';
  });

  dashApi('/api/v1/admin/system/readiness').then(function(rd) {
    var checks = rd.checks||{};
    var warnings = rd.warnings||[];
    var html = Object.keys(checks).map(function(k){
      var v=checks[k];
      return '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line);font-size:12px;"><span>'+k.replace(/_/g,' ')+'</span><span style="color:'+(v===true||v==='ok'?'#10b981':'#f59e0b')+';font-weight:700;">'+(v===true?'OK':v===false?'Not Set':v)+'</span></div>';
    }).join('');
    if(warnings.length){
      html += '<div style="margin-top:12px;">'+warnings.map(function(w){return '<div style="padding:6px 10px;margin-top:4px;border-radius:6px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.2);font-size:12px;color:#fbbf24;">'+w+'</div>';}).join('')+'</div>';
    }
    document.getElementById('readinessBody').innerHTML = html||'<p style="color:var(--muted);">No data available</p>';
  }).catch(function(e) {
    // readinessBody might already show error from monitoring, that's ok
  });
}
// Run immediately AND on DOM ready as safety net
try{ loadOverview(); }catch(e){ console.error('loadOverview error:',e); }
setInterval(function(){ try{loadOverview();}catch(e){} }, 30000);
document.addEventListener('DOMContentLoaded', function(){
  try{ loadOverview(); }catch(e){}
});

// ── Settlement Payloads in Overview ──────────────────────────────────────────
var _ovCurrentPl = null;

function ovHtml(v){
  return String(v || '—').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function ovAttr(v){
  return ovHtml(v).replace(/"/g,'&quot;');
}
function ovInfoValue(label, value){
  var raw = value == null || value === '' ? '—' : String(value);
  if((label === 'TX Hash' || label === 'Sender' || label === 'Receiver Wallet' || label === 'Client IP') && raw !== '—'){
    var safe = ovAttr(raw);
    return '<div style="display:flex;align-items:center;gap:6px;min-width:0;">'
      +'<code title="'+safe+'" style="display:block;max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:ltr;text-align:left;font-size:11px;">'+safe+'</code>'
      +'<button class="btn btn-ghost" data-copy="'+safe+'" onclick="copyText(this.dataset.copy)" style="flex:0 0 auto;font-size:10px;padding:2px 6px;">Copy</button>'
      +'</div>';
  }
  return value;
}

function loadOvPayloads() {
  dashApi('/api/v1/admin/payloads').then(function(res) {
    var rows = res.payloads||[];
    if(!rows.length){
      document.getElementById('ovPlBody').innerHTML='<div class="empty-state"><div class="icon">📥</div>No payloads found</div>';
      return;
    }
    var th='<th>Reference</th><th>Amount</th><th>Network</th><th>Status</th><th>Security</th><th>TX Hash</th><th>Date</th><th>Action</th>';
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
  }).catch(function(e){
    document.getElementById('ovPlBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+e.message+'</div>';
  });
}

function ovViewPayload(id) {
  api('/api/v1/admin/payloads/'+id).then(function(p) {
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
        +'<div style="font-size:12px;font-weight:600;color:var(--ink);min-width:0;overflow:hidden;">'+ovInfoValue(f[0],f[1])+'</div></div>';
    }).join('');
    // Set priority dropdown
    document.getElementById('ovPriority').value = p.review_priority||'NORMAL';
    // Show raw JSON tab by default
    ovTab('raw');
    document.getElementById('ovPlDetail').style.display='block';
    document.body.style.overflow='hidden';
  }).catch(function(e){ showToast('Error: '+e.message,'error'); });
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

function ovVerify(){
  if(!_ovCurrentPl){return;}
  var pid=_ovCurrentPl.id||_ovCurrentPl.payload_id;
  api('/api/v1/admin/payloads/'+pid+'/verify',{method:'POST'}).then(function(){showToast('Verification request sent','ok');loadOvPayloads();ovViewPayload(pid);}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function ovManual(){
  if(!_ovCurrentPl){return;}
  var pid=_ovCurrentPl.id||_ovCurrentPl.payload_id;
  api('/api/v1/admin/payloads/'+pid+'/mark-manual-review',{method:'POST'}).then(function(){showToast('Marked for manual review','ok');loadOvPayloads();ovViewPayload(pid);}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function ovReview(decision){
  if(!_ovCurrentPl){return;}
  var note=document.getElementById('ovReviewNote').value||'';
  var action=(decision||'').toUpperCase();
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:action,note:note,priority:priority})}).then(function(){showToast(action==='APPROVE'?'Approved':'Rejected','ok');loadOvPayloads();ovClosePayload();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function ovHold(){
  if(!_ovCurrentPl){return;}
  var reason=document.getElementById('ovHoldReason').value;
  var note='HOLD: '+(reason||document.getElementById('ovReviewNote').value||'on hold');
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:'HOLD',note:note,hold_reason:reason||note,priority:priority})}).then(function(){showToast('Payload placed on hold','ok');loadOvPayloads();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function ovSaveNote(){
  if(!_ovCurrentPl){return;}
  var note=document.getElementById('ovReviewNote').value;
  if(!note){showToast('Write a note first','error');return;}
  var priority=document.getElementById('ovPriority').value||'NORMAL';
  api('/api/v1/admin/payloads/'+(_ovCurrentPl.id||_ovCurrentPl.payload_id)+'/review',{method:'POST',body:JSON.stringify({action:'NOTE',note:note,priority:priority})}).then(function(){showToast('Note saved','ok');}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function ovQuickAction(id,decision){
  var note=decision==='approve'?'Quick approval from dashboard':'Quick rejection from dashboard';
  var action=(decision||'').toUpperCase();
  api('/api/v1/admin/payloads/'+id+'/review',{method:'POST',body:JSON.stringify({action:action,note:note})}).then(function(){showToast(action==='APPROVE'?'Approved':'Rejected','ok');loadOvPayloads();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
try{ loadOvPayloads(); }catch(e){ console.error('loadOvPayloads error:',e); }
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
      <option value="">All statuses</option>
      <option>CREATED</option><option>PENDING</option><option>PROCESSING</option>
      <option>COMPLETED</option><option>FAILED</option><option>REFUNDED</option><option>EXPIRED</option>
    </select>
    <button class="btn btn-ghost" onclick="loadOrders()">Refresh</button>
  </div>
  <div class="panel">
    <div class="panel-head">
      <h3>Orders List</h3>
      <span id="ordCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="ordersBody"><div class="empty-state"><div class="icon">📋</div>Loading...</div></div>
  </div>
  <div id="orderDetailPanel" class="panel" style="display:none;">
    <div class="panel-head">
      <h3 id="orderDetailTitle">Transaction Details</h3>
      <button class="btn btn-ghost" onclick="closeOrderDetails()">Close</button>
    </div>
    <div id="orderDetailBody" style="padding:16px;"></div>
  </div>
</div>
<script>
function closeOrderDetails(){document.getElementById('orderDetailPanel').style.display='none';}
function openOrderDetails(id){
  var panel=document.getElementById('orderDetailPanel');
  var body=document.getElementById('orderDetailBody');
  panel.style.display='block';
  body.innerHTML='<div class="empty-state"><div class="icon">🔎</div>Loading transaction details...</div>';
  api('/api/v1/admin/orders/'+id+'/details').then(function(data){
    var o=data.order||{};
    var docs=data.documents||{};
    var logs=data.audit_logs||[];
    document.getElementById('orderDetailTitle').textContent='Transaction Details - '+(o.external_id||o.id||id);
    var rows=[
      ['Transaction ID',o.id],['External ID',o.external_id],['Provider',o.provider],['Status',o.status],
      ['Network',o.network],['Fiat Amount',(o.fiat_amount||'—')+' '+(o.fiat_currency||'')],
      ['Crypto Amount',(o.crypto_amount||'—')+' '+(o.crypto_currency||'')],
      ['Payment Reference',o.payment_reference],['Provider Order ID',o.provider_order_id],
      ['TX Hash',o.tx_hash],['Payer Email',o.payer_email],['Destination',o.destination_address],
      ['Treasury Wallet',o.treasury_wallet_address],['Customer Wallet',o.customer_wallet_address],
      ['Checkout URL',o.checkout_url||o.payment_url],['Idempotency Key',o.idempotency_key],
      ['Failure Reason',o.failure_reason],['Created At',fmtDate(o.created_at)],['Updated At',fmtDate(o.updated_at)]
    ];
    var detailRows=rows.map(function(r){
      var val=r[1]||'—';
      var isUrl=String(val).indexOf('http')===0;
      return '<tr><th style="width:220px;">'+esc(r[0])+'</th><td style="word-break:break-all;">'+(isUrl?'<a href="'+esc(val)+'" target="_blank">'+esc(val)+'</a>':esc(val))+'</td></tr>';
    }).join('');
    var logRows=logs.length?logs.map(function(l){
      return '<tr><td>'+esc(l.event_type||'')+'</td><td>'+esc(l.method||'')+'</td><td>'+esc(l.endpoint||'')+'</td><td>'+esc(String(l.status_code||'—'))+'</td><td>'+fmtDate(l.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan="5">No audit logs found.</td></tr>';
    body.innerHTML=
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">'
      +'<button class="btn btn-primary" onclick="window.open(\\'/api/v1/admin/orders/'+esc(o.id||id)+'/documents/statement\\',\\'_blank\\')">Print Statement</button>'
      +'<button class="btn btn-ghost" onclick="window.open(\\''+esc(docs.invoice_url||('/api/v1/admin/orders/'+(o.id||id)+'/documents/invoice'))+'\\',\\'_blank\\')">Invoice</button>'
      +'<button class="btn btn-ghost" onclick="window.open(\\'/api/v1/admin/reports/transactions?order_id='+esc(o.id||id)+'\\',\\'_blank\\')">Single Report</button>'
      +'</div>'
      +'<div class="table-wrap"><table><tbody>'+detailRows+'</tbody></table></div>'
      +'<h4 style="margin:18px 0 8px;">Audit Trail</h4><div class="table-wrap"><table><thead><tr><th>Event</th><th>Method</th><th>Endpoint</th><th>Status</th><th>Date</th></tr></thead><tbody>'+logRows+'</tbody></table></div>';
    panel.scrollIntoView({behavior:'smooth'});
  }).catch(function(e){body.innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}
function loadOrders() {
  var st = document.getElementById('ordStatus').value;
  var url = '/api/v1/admin/orders' + (st ? '?status='+st : '');
  api(url).then(function(rows) {
    if(!Array.isArray(rows)) rows = rows.orders||[];
    document.getElementById('ordCount').textContent = rows.length + ' orders';
    if(!rows.length){
      document.getElementById('ordersBody').innerHTML='<div class="empty-state"><div class="icon">📋</div>No orders found</div>';
      return;
    }
    var th = '<th>ID</th><th>Provider</th><th>Fiat</th><th>Crypto</th><th>Status</th><th>Network</th><th>Email</th><th>Ref</th><th>TX</th><th>Date</th><th>Action</th>';
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
      +'<td><div style="display:flex;gap:6px;flex-wrap:wrap;"><button class="btn btn-ghost" data-oid="'+o.id+'" onclick="openOrderDetails(this.dataset.oid)" style="font-size:11px;padding:3px 8px;">View</button><button class="btn btn-primary" data-oid="'+o.id+'" onclick="window.open(\\'/api/v1/admin/orders/'+o.id+'/documents/statement\\',\\'_blank\\')" style="font-size:11px;padding:3px 8px;">Statement</button><button class="btn btn-danger" data-oid="'+o.id+'" onclick="deleteOrderPage(this.dataset.oid)" style="font-size:11px;padding:3px 8px;">Delete</button></div></td>'
      +'</tr>';}).join('');
    document.getElementById('ordersBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e) {
    document.getElementById('ordersBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';
  });
}
function deleteOrderPage(id){
  if(!confirm('Delete this order? This cannot be undone.'))return;
  api('/api/v1/admin/orders/'+id,{method:'DELETE'}).then(function(){showToast('Order deleted','ok');loadOrders();}).catch(function(e){showToast(e.message||String(e),'error');});
}
loadOrders();
</script>
"""

# ─── PAYLOADS ────────────────────────────────────────────────────────────────

_PAYLOADS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="plStatus" onchange="loadPayloads()" style="min-width:180px;">
      <option value="">All statuses</option>
      <option>RECEIVED</option><option>PARSED</option><option>AWAITING_TX_HASH</option>
      <option>ALCHEMY_PENDING</option><option>ALCHEMY_VERIFIED</option>
      <option>ON_CHAIN_CONFIRMED</option><option>RECONCILED</option>
      <option>FAILED</option><option>MANUAL_REVIEW</option>
    </select>
    <button class="btn btn-ghost" onclick="loadPayloads()">Refresh</button>
  </div>

  <div id="plDetail" style="display:none;" class="panel">
    <div class="panel-head">
      <h3>Payload Details</h3>
      <button class="btn btn-ghost" onclick="document.getElementById('plDetail').style.display='none'" style="font-size:11px;padding:4px 10px;">Close</button>
    </div>
    <div id="plDetailBody" style="padding:16px;font-size:12px;line-height:1.8;"></div>
    <div id="plActions" style="padding:0 16px 16px;display:flex;gap:8px;flex-wrap:wrap;"></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>Settlement Payloads</h3>
      <span id="plCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="plBody"><div class="empty-state"><div class="icon">📥</div>Loading...</div></div>
  </div>
</div>
<script>
function loadPayloads() {
  var st = document.getElementById('plStatus').value;
  var url = '/api/v1/admin/payloads' + (st ? '?verification_status='+st : '');
  api(url).then(function(res) {
    var rows = res.payloads||[];
    document.getElementById('plCount').textContent = (res.count||rows.length)+' payload';
    if(!rows.length){
      document.getElementById('plBody').innerHTML='<div class="empty-state"><div class="icon">📥</div>No payloads found</div>';
      return;
    }
    var th = '<th>ID</th><th>Amount</th><th>Network</th><th>Sender</th><th>TX Hash</th><th>Security</th><th>Status</th><th>Date</th><th>View</th>';
    var tb = rows.map(function(r){var rid=r.id||r.payload_id;return '<tr data-rid="'+rid+'" onclick="viewPayload(this.dataset.rid)" style="cursor:pointer;">'
      +'<td><code style="font-size:10px;cursor:pointer;color:var(--brand);">'+rid.slice(0,10)+'...</code></td>'
      +'<td>'+fmtNum(r.amount)+' '+(r.asset||'USDT')+'</td>'
      +'<td>'+((r.network_name||r.network||'').toUpperCase())+'</td>'
      +'<td>'+(r.sender_wallet?'<code style="font-size:10px;" title="'+r.sender_wallet+'">'+r.sender_wallet.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td>'+(r.tx_hash?'<code style="font-size:10px;" title="'+r.tx_hash+'">'+r.tx_hash.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td><span style="font-size:10px;color:var(--muted);">'+(r.security_level||'—')+'</span></td>'
      +'<td>'+badge(r.verification_status)+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><button class="btn btn-ghost" data-rid="'+rid+'" onclick="event.stopPropagation();viewPayload(this.dataset.rid)" style="font-size:11px;padding:4px 10px;">View</button></td>'
      +'</tr>';}).join('');
    document.getElementById('plBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e) {
    document.getElementById('plBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';
  });
}

function viewPayload(id) {
  api('/api/v1/admin/payloads/'+id).then(function(p) {
    var fields=[
      ['ID',p.payload_id||p.id||'—'],['Verification Status',badge(p.verification_status)],
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
    if(['RECEIVED','PARSED','AWAITING_TX_HASH','MANUAL_REVIEW'].indexOf(vstatus)>=0){
      acts.push('<button class="btn btn-primary" data-pid="'+id+'" onclick="verifyPl(this.dataset.pid)">Verify On-Chain</button>');
    }
    if(vstatus!=='MANUAL_REVIEW'){
      acts.push('<button class="btn btn-ghost" data-pid="'+id+'" onclick="markManual(this.dataset.pid)">Mark Manual Review</button>');
    }
    acts.push('<button class="btn btn-success" data-pid="'+id+'" data-act="approve" onclick="reviewPl(this.dataset.pid,this.dataset.act)">Approve</button>');
    acts.push('<button class="btn btn-danger"  data-pid="'+id+'" data-act="reject"  onclick="reviewPl(this.dataset.pid,this.dataset.act)">Reject</button>');
    // Route to Provider section
    var eurAmt = p.amount ? parseFloat(p.amount).toFixed(2) : '0.00';
    var routeHtml = '<div style="margin-top:16px;padding:16px;background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);border-radius:10px;">'
      +'<div style="font-size:13px;font-weight:700;color:var(--gold);margin-bottom:12px;">🔀 Route Payload to Provider — تمويل SIG</div>'
      +'<div style="font-size:12px;color:var(--muted);margin-bottom:12px;">المبلغ: <strong style="color:var(--ink);">'+eurAmt+' '+(p.asset||'USDT')+'</strong> → اختر الوجهة لتحويل السيولة</div>'
      +'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;">'
      +'<label style="display:flex;align-items:center;gap:6px;cursor:pointer;padding:8px 14px;border:1px solid var(--glass-border);border-radius:8px;font-size:12px;"><input type="radio" name="plProvider_'+id+'" value="moonpay" style="accent-color:var(--brand);"> MoonPay</label>'
      +'<label style="display:flex;align-items:center;gap:6px;cursor:pointer;padding:8px 14px;border:1px solid var(--glass-border);border-radius:8px;font-size:12px;"><input type="radio" name="plProvider_'+id+'" value="circle" style="accent-color:var(--brand);"> Circle USDC</label>'
      +'<label style="display:flex;align-items:center;gap:6px;cursor:pointer;padding:8px 14px;border:1px solid var(--glass-border);border-radius:8px;font-size:12px;"><input type="radio" name="plProvider_'+id+'" value="stripe" style="accent-color:var(--brand);"> Stripe</label>'
      +'</div>'
      +'<button class="btn btn-primary" data-pid="'+id+'" onclick="routePayload(this.dataset.pid)" style="font-size:12px;">Route & Fund SIG Liquidity</button>'
      +'<div id="routeResult_'+id+'" style="margin-top:8px;font-size:12px;"></div>'
      +'</div>';
    document.getElementById('plDetailBody').innerHTML += routeHtml;
    document.getElementById('plActions').innerHTML=acts.join('');
    document.getElementById('plDetail').style.display='block';
    document.getElementById('plDetail').scrollIntoView({behavior:'smooth'});
  }).catch(function(e){ showToast('Error: '+e.message,'error'); });
}
function routePayload(id){
  var sel=document.querySelector('input[name="plProvider_'+id+'"]:checked');
  if(!sel){showToast('اختر Provider أولاً','error');return;}
  var provider=sel.value;
  var res=document.getElementById('routeResult_'+id);
  if(res) res.innerHTML='<span style="color:var(--muted);">جاري التوجيه إلى '+provider+'...</span>';
  api('/api/v1/admin/payloads/'+id+'/route-provider',{method:'POST',body:JSON.stringify({provider:provider})})
    .then(function(r){
      if(res) res.innerHTML='<span style="color:#22c55e;">✅ تم التوجيه إلى '+provider+' | '+JSON.stringify(r)+'</span>';
      showToast('Payload routed to '+provider,'ok');
    })
    .catch(function(e){
      if(res) res.innerHTML='<span style="color:#ef4444;">❌ '+esc(e.message)+'</span>';
      showToast('Route error: '+e.message,'error');
    });
}

function verifyPl(id){
  api('/api/v1/admin/payloads/'+id+'/verify',{method:'POST'}).then(function(){showToast('Verification request sent','ok');loadPayloads();viewPayload(id);}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function markManual(id){
  api('/api/v1/admin/payloads/'+id+'/mark-manual-review',{method:'POST'}).then(function(){showToast('Marked for manual review','ok');loadPayloads();viewPayload(id);}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function reviewPl(id,decision){
  var note=prompt('Review note ('+(decision==='approve'?'approve':'reject')+'): ')||'';
  var action=(decision||'').toUpperCase();
  api('/api/v1/admin/payloads/'+id+'/review',{method:'POST',body:JSON.stringify({action:action,note:note})}).then(function(){showToast(action==='APPROVE'?'Approved':'Rejected','ok');loadPayloads();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
loadPayloads();
</script>
"""

# ─── TRANSFERS ────────────────────────────────────────────────────────────────

_TRANSFERS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="xtStatus" onchange="loadTransfers()" style="min-width:160px;">
      <option value="">All statuses</option>
      <option>PENDING</option><option>AWAITING_APPROVAL</option><option>APPROVED</option>
      <option>BROADCASTING</option><option>PENDING_CONFIRMATION</option><option>CONFIRMED</option><option>COMPLETED</option><option>FAILED</option><option>CANCELLED</option>
    </select>
    <select id="xtNetwork" onchange="loadTransfers()" style="min-width:130px;">
      <option value="">All networks</option>
      <option value="ethereum">Ethereum</option>
      <option value="tron">TRON</option>
      <option value="base">Base</option>
    </select>
    <button class="btn btn-ghost" onclick="loadTransfers()">Refresh</button>
    <button class="btn btn-primary" onclick="toggleCF()">+ Create Transfer</button>
  </div>

  <div id="createXferForm" style="display:none;" class="panel">
    <div class="panel-head"><h3>Create New Transfer</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>Recipient Address *</label>
          <input id="cfTo" placeholder="0x... or T..."></div>
        <div class="form-field"><label>Amount *</label>
          <input id="cfAmt" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>Asset *</label>
          <select id="cfAsset"><option value="SIG" selected>SIG (Default)</option><option value="USDT">USDT</option></select></div>
        <div class="form-field"><label>Network *</label>
          <select id="cfNet">
            <option value="ethereum">Ethereum (ERC-20)</option>
            <option value="tron">TRON (TRC-20)</option>
            <option value="base">Base (ERC-20)</option>
          </select></div>
        <div class="form-field"><label>Callback URL</label>
          <input id="cfCb" placeholder="https://..."></div>
        <div class="form-field" style="grid-column:span 2;"><label>Notes</label>
          <input id="cfNotes" placeholder="Optional notes"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-success" onclick="createTransfer()">Create</button>
        <button class="btn btn-ghost" onclick="toggleCF()">Cancel</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>Outbound Transfers</h3>
      <span id="xtCount" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="xtBody"><div class="empty-state"><div class="icon">🚀</div>Loading...</div></div>
  </div>
  <div id="xferDetailPanel" class="panel" style="display:none;">
    <div class="panel-head">
      <h3 id="xferDetailTitle">Transfer Details</h3>
      <button class="btn btn-ghost" onclick="closeXferDetails()">Close</button>
    </div>
    <div id="xferDetailBody" style="padding:16px;"></div>
  </div>
</div>
<script>
var _xferRows={};
function toggleCF(){
  var el=document.getElementById('createXferForm');
  el.style.display=el.style.display==='none'?'block':'none';
}

function createTransfer(){
  var body={
    to_address:document.getElementById('cfTo').value.trim(),
    amount:document.getElementById('cfAmt').value,
    asset:document.getElementById('cfAsset').value,
    network:document.getElementById('cfNet').value,
    callback_url:document.getElementById('cfCb').value.trim()||null,
    notes:document.getElementById('cfNotes').value.trim()||null
  };
  if(!body.to_address){showToast('Recipient address is required','error');return;}
  if(!body.amount){showToast('Amount is required','error');return;}
  api('/api/v1/admin/outbound-transfers',{method:'POST',body:JSON.stringify(body)}).then(function(){
    showToast('Transfer created','ok');
    toggleCF();
    document.getElementById('cfTo').value='';document.getElementById('cfAmt').value='';
    document.getElementById('cfCb').value='';document.getElementById('cfNotes').value='';
    loadTransfers();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}

function approveXfer(id){
  if(!confirm('Approve this transfer?'))return;
  api('/api/v1/admin/outbound-transfers/'+id+'/approve',{method:'POST'}).then(function(){showToast('Transfer approved','ok');loadTransfers();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function broadcastXfer(id){
  if(!confirm('Broadcast this transfer on-chain?'))return;
  var btn=Array.from(document.querySelectorAll('button[data-action="broadcast"]')).find(function(el){return el.dataset.xid===id;});
  var old=btn?btn.textContent:'';
  if(btn){btn.disabled=true;btn.textContent='Broadcasting...';}
  api('/api/v1/admin/outbound-transfers/'+id+'/broadcast',{method:'POST'}).then(function(row){
    showToast(row&&row.tx_hash?'Broadcast submitted: '+row.tx_hash.slice(0,12)+'...':'Broadcast submitted','ok');
    loadTransfers();
  }).catch(function(e){
    showToast('Broadcast error: '+e.message,'error');
  }).finally(function(){
    if(btn){btn.disabled=false;btn.textContent=old||'Broadcast';}
  });
}
function cancelXfer(id){
  var r=prompt('Cancellation reason:')||'Cancelled by admin';
  api('/api/v1/admin/outbound-transfers/'+id+'/cancel',{method:'POST',body:JSON.stringify({reason:r})}).then(function(){showToast('Transfer cancelled','ok');loadTransfers();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function retryXfer(id){
  api('/api/v1/admin/outbound-transfers/'+id+'/retry',{method:'POST'}).then(function(){showToast('Retry started','ok');loadTransfers();}).catch(function(e){showToast('Retry error: '+e.message,'error');});
}
function deleteXfer(id){
  if(!confirm('Delete this transfer? This cannot be undone.'))return;
  api('/api/v1/admin/outbound-transfers/'+id,{method:'DELETE'}).then(function(){showToast('Transfer deleted','ok');loadTransfers();}).catch(function(e){showToast('Delete error: '+e.message,'error');});
}
function closeXferDetails(){document.getElementById('xferDetailPanel').style.display='none';}
function viewXfer(id){
  var r=_xferRows[id];
  if(!r){showToast('Transfer details not found. Refresh and try again.','error');return;}
  document.getElementById('xferDetailTitle').textContent='Transfer Details - '+id;
  var txValue=r.tx_hash?(r.explorer_url?'<a href="'+esc(r.explorer_url)+'" target="_blank"><code>'+esc(r.tx_hash)+'</code></a>':'<code>'+esc(r.tx_hash)+'</code>'):'—';
  var rows=[
    ['ID',esc(r.id)],['Network',esc(r.network)],['Amount',fmtNum(r.amount)+' '+esc(r.asset||'USDT')],['Status',badge(r.status)],
    ['To Address',esc(r.to_address)],['TX Hash',txValue],['Confirmations',esc(String(r.confirmations||0))],
    ['Block Number',esc(String(r.block_number||'—'))],['Approved By',esc(r.approved_by)],
    ['Broadcast Error',esc(r.error_message)],['Callback URL',esc(r.callback_url)],['Notes',esc(r.notes)],
    ['Created At',fmtDate(r.created_at)],['Updated At',fmtDate(r.updated_at)]
  ];
  document.getElementById('xferDetailBody').innerHTML='<div class="table-wrap"><table><tbody>'+rows.map(function(x){
    return '<tr><th style="width:220px;">'+esc(x[0])+'</th><td style="word-break:break-all;">'+(x[1]||'—')+'</td></tr>';
  }).join('')+'</tbody></table></div>';
  document.getElementById('xferDetailPanel').style.display='block';
  document.getElementById('xferDetailPanel').scrollIntoView({behavior:'smooth'});
}

function txLink(r){
  if(!r.tx_hash)return '—';
  var label='<code style="font-size:10px;" title="'+esc(r.tx_hash)+'">'+esc(r.tx_hash.slice(0,14))+'...</code>';
  return r.explorer_url?'<a href="'+esc(r.explorer_url)+'" target="_blank">'+label+'</a>':label;
}

function loadTransfers(){
  var st=document.getElementById('xtStatus').value;
  var nt=document.getElementById('xtNetwork').value;
  var url='/api/v1/admin/outbound-transfers?limit=100';
  if(st)url+='&status='+st;if(nt)url+='&network='+nt;
  api(url).then(function(rows) {
    if(!Array.isArray(rows))rows=[];
    _xferRows={}; rows.forEach(function(x){_xferRows[x.id]=x;});
    document.getElementById('xtCount').textContent=rows.length+' transfers';
    if(!rows.length){document.getElementById('xtBody').innerHTML='<div class="empty-state"><div class="icon">🚀</div>No transfers found</div>';return;}
    var th='<th>ID</th><th>Network</th><th>Amount</th><th>To Address</th><th>TX Hash</th><th>Status</th><th>Error</th><th>Approved By</th><th>Date</th><th>Actions</th>';
    var tb=rows.map(function(r){
      var btns=[];
      if(['PENDING','AWAITING_APPROVAL'].indexOf(r.status)>=0)
        btns.push('<button class="btn btn-success" data-xid="'+r.id+'" onclick="approveXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Approve</button>');
      if(r.status==='APPROVED')
        btns.push('<button class="btn btn-primary" data-xid="'+r.id+'" data-action="broadcast" onclick="broadcastXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Broadcast</button>');
      if(r.status==='FAILED')
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="retryXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Retry</button>');
      if(['COMPLETED','CONFIRMED','PENDING_CONFIRMATION','CANCELLED'].indexOf(r.status)<0)
        btns.push('<button class="btn btn-danger" data-xid="'+r.id+'" onclick="cancelXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Cancel</button>');
      if(['BROADCASTING','PENDING_CONFIRMATION'].indexOf(r.status)<0)
        btns.push('<button class="btn btn-danger" data-xid="'+r.id+'" onclick="deleteXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Delete</button>');
      btns.unshift('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="viewXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">View</button>');
      return '<tr>'
        +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,10)+'...</code></td>'
        +'<td><strong>'+(r.network||'').toUpperCase()+'</strong></td>'
        +'<td><strong style="color:#a78bfa;">'+fmtNum(r.amount)+' '+(r.asset||'USDT')+'</strong></td>'
        +'<td>'+(r.to_address?'<code style="font-size:10px;" title="'+r.to_address+'">'+r.to_address.slice(0,16)+'...</code>':'—')+'</td>'
        +'<td>'+txLink(r)+(r.confirmations?'<div style="font-size:10px;color:var(--muted);">'+r.confirmations+' conf</div>':'')+'</td>'
        +'<td>'+badge(r.status)+'</td>'
        +'<td>'+(r.error_message?'<code style="font-size:10px;color:#fca5a5;" title="'+esc(r.error_message)+'">'+esc(r.error_message).slice(0,36)+'...</code>':'—')+'</td>'
        +'<td>'+(r.approved_by||'—')+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
        +'<td>'+btns.join(' ')+'</td>'
        +'</tr>';
    }).join('');
    document.getElementById('xtBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('xtBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
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
      <h3>Live EUR/USD FX Rate</h3>
      <button class="btn btn-ghost" onclick="loadFx()" style="font-size:11px;padding:4px 10px;">Refresh</button>
    </div>
    <div id="fxBanner" style="padding:14px 16px;display:flex;gap:24px;align-items:center;min-height:48px;"></div>
  </div>

  <div class="filter-bar">
    <select id="m1Status" onchange="loadJobs()" style="min-width:140px;">
      <option value="">All statuses</option>
      <option>QUEUED</option><option>FX_FETCHED</option><option>CONVERTING</option>
      <option>SENDING</option><option>COMPLETED</option><option>FAILED</option>
    </select>
    <button class="btn btn-ghost" onclick="loadJobs()">Refresh</button>
    <button class="btn btn-primary" onclick="toggleM1F()">+ Create Job</button>
  </div>

  <div id="m1Form" style="display:none;" class="panel">
    <div class="panel-head"><h3>Create M1 Tokenization Job</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>EUR Amount *</label><input id="m1Eur" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>Destination Wallet *</label><input id="m1Dest" placeholder="0x... or T..."></div>
        <div class="form-field"><label>Reference</label><input id="m1Ref" placeholder="Optional"></div>
        <div class="form-field"><label>Sender Name</label><input id="m1Name" placeholder="Optional"></div>
        <div class="form-field"><label>Network</label>
          <select id="m1Net"><option value="ethereum">Ethereum</option><option value="tron">TRON</option><option value="base">Base</option></select></div>
        <div class="form-field"><label>Target Asset</label><select id="m1Asset"><option value="SIG" selected>SIG (Default)</option><option value="USDT">USDT</option></select></div>
        <div class="form-field"><label>IBAN</label><input id="m1Iban" placeholder="Optional"></div>
        <div class="form-field" style="grid-column:1 / -1;">
          <button type="button" class="btn btn-ghost" onclick="toggleM1FormGas()" style="font-size:11px;padding:4px 10px;">Show Manual Gas Estimate</button>
          <div id="m1FormGasBox" style="display:none;margin-top:8px;">
            <label>Manual Gas Estimate Override</label>
            <input id="m1ManualGas" type="number" step="0.00000001" placeholder="Optional estimate amount">
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-ghost" onclick="estimateM1GasFromForm()">Estimate Gas Fee</button>
        <button class="btn btn-success" onclick="createJob()">Create</button>
        <button class="btn btn-ghost" onclick="toggleM1F()">Cancel</button>
      </div>
      <div id="m1GasEstimate" style="margin-top:12px;"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>M1 Tokenization Jobs</h3>
      <span id="m1Count" style="color:var(--muted);font-size:12px;"></span>
    </div>
    <div id="m1Body"><div class="empty-state"><div class="icon">🔄</div>Loading...</div></div>
  </div>
</div>
<script>
var _m1Rows={};
function toggleM1FormGas(){
  var box=document.getElementById('m1FormGasBox');
  if(!box)return;
  box.style.display=(box.style.display==='none'||!box.style.display)?'block':'none';
}
function loadFx(){
  api('/api/v1/admin/tokenization-jobs/fx-rate/live').then(function(r) {
    document.getElementById('fxBanner').innerHTML='<div style="font-size:28px;font-weight:800;color:var(--gold);">1 EUR = '+parseFloat(r.eur_usd).toFixed(4)+' USD</div><div style="color:var(--muted);font-size:12px;">Provider: '+(r.provider||'—')+'<br>'+fmtDate(r.timestamp)+'</div>';
  }).catch(function(e){document.getElementById('fxBanner').innerHTML='<span style="color:var(--muted);">Unavailable: '+e.message+'</span>';});
}
function toggleM1F(){
  var el=document.getElementById('m1Form');
  el.style.display=el.style.display==='none'?'block':'none';
}
function createJob(){
  var body={eur_amount:document.getElementById('m1Eur').value,destination_wallet:document.getElementById('m1Dest').value.trim(),sender_reference:document.getElementById('m1Ref').value.trim()||null,sender_name:document.getElementById('m1Name').value.trim()||null,sender_iban:document.getElementById('m1Iban').value.trim()||null,network:document.getElementById('m1Net').value,target_asset:document.getElementById('m1Asset').value};
  if(!body.eur_amount){showToast('EUR amount is required','error');return;}
  if(!body.destination_wallet){showToast('Destination wallet is required','error');return;}
  api('/api/v1/admin/tokenization-jobs',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Job created','ok');toggleM1F();loadJobs();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function processJob(id){
  var r=_m1Rows&&_m1Rows[id]?_m1Rows[id]:null;
  var target=(r&&r.target_asset)||'SIG';
  if(!confirm('Run EUR to '+target+' tokenization now?'))return;
  api('/api/v1/admin/tokenization-jobs/'+id+'/process',{method:'POST',body:JSON.stringify({target_asset:target})}).then(function(){showToast('Job processed','ok');loadJobs();}).catch(function(e){showToast('Processing error: '+e.message,'error');});
}
function reprocessJobSIG(id){
  var r=_m1Rows&&_m1Rows[id]?_m1Rows[id]:null;
  var eur=r?fmtNum(r.eur_amount)+' EUR':'';
  if(!confirm('Reprocess job '+eur+' with SIG tokens (force=true)? This will create a new OutboundTransfer using SIG from the treasury.'))return;
  api('/api/v1/admin/tokenization-jobs/'+id+'/process',{method:'POST',body:JSON.stringify({target_asset:'SIG',force:true})})
    .then(function(){showToast('Job reprocessed with SIG','ok');loadJobs();})
    .catch(function(e){showToast('Reprocess error: '+e.message,'error');});
}
function renderGasEstimate(target, r){
  var html='<div class="panel" style="border-color:rgba(59,130,246,.35);margin:0;"><div style="padding:12px;font-size:12px;line-height:1.7;">'
    +'<strong>Estimated gas fee:</strong> '+esc(String(r.estimated_native_fee||'0'))+' '+esc(r.native_symbol||'')
    +'<br><span style="color:var(--muted);">Network: '+esc(r.network||'')+' · Gas limit: '+esc(String(r.gas_limit||'n/a'))+' · Source: '+esc(r.source||'estimate')+'</span>'
    +'</div></div>';
  var el=document.getElementById(target);
  if(el) el.innerHTML=html;
  showToast('Gas fee estimated','ok');
}
function readM1GasOverride(inputId){
  var rowEl=inputId?document.getElementById(inputId):null;
  var formEl=document.getElementById('m1ManualGas');
  var value=rowEl?rowEl.value.trim():(formEl?formEl.value.trim():'');
  if(value && !/^[0-9]+(\\.[0-9]+)?$/.test(value.replace(/,/g,''))){
    showToast('Gas fee must be a valid number','error');
    return null;
  }
  return value.replace(/,/g,'');
}
function estimateM1Gas(network,wallet,amount,target,inputId){
  var manualGas=readM1GasOverride(inputId);
  if(manualGas===null) return;
  if(manualGas){
    renderGasEstimate(target||'m1GasEstimate',{estimated_native_fee:manualGas,native_symbol:'USDT TRC20',network:'tron',source:'manual_admin_override'});
    return;
  }
  api('/api/v1/admin/tokenization-jobs/gas-fee/estimate',{method:'POST',body:JSON.stringify({network:network,destination_wallet:wallet,amount:amount||'1',manual_gas_fee:manualGas||null})})
    .then(function(r){renderGasEstimate(target||'m1GasEstimate',r);})
    .catch(function(e){showToast('Gas estimate error: '+e.message,'error');});
}
function estimateM1GasFromForm(){
  var eur=parseFloat(document.getElementById('m1Eur').value||'0');
  var approximateUsdt=eur>0?String(eur):'1';
  estimateM1Gas(document.getElementById('m1Net').value,document.getElementById('m1Dest').value.trim(),approximateUsdt,'m1GasEstimate');
}
var _m1GasOrders={};
function gasJobInvoice(id){
  var manualGas=readM1GasOverride('m1Gas_'+id);
  if(manualGas===null) return;
  if(!manualGas){
    toggleM1GasBox(id);
    showToast('Add the USDT TRC20 gas fee amount first','error');
    return;
  }
  api('/api/v1/admin/tokenization-jobs/'+id+'/gas-fee-invoice',{method:'POST',body:JSON.stringify({manual_gas_fee:manualGas})}).then(function(r){
    showToast('Gas fee invoice created','ok');
    if(r.invoice_url) window.open(r.invoice_url,'_blank');
    if(r.order && r.order.id){ _m1GasOrders[id]=r.order.id; }
    var statusEl=document.getElementById('m1InvStatus_'+id);
    if(statusEl) statusEl.style.display='flex';
    loadJobs();
  }).catch(function(e){showToast('Gas invoice error: '+e.message,'error');});
}
function setGasInvoiceStatus(jobId,status){
  var orderId=_m1GasOrders[jobId];
  if(!orderId){showToast('Create a gas invoice first, then set its status.','error');return;}
  var statusMap={COMPLETED:'COMPLETED',PENDING:'PENDING',REFUND:'FAILED'};
  var apiStatus=statusMap[status]||status;
  api('/api/v1/admin/orders/'+orderId+'/status',{method:'PUT',body:JSON.stringify({status:apiStatus,note:status==='REFUND'?'Gas invoice refunded from admin dashboard':null})})
    .then(function(){showToast('Gas invoice → '+status,'ok');})
    .catch(function(e){showToast('Status error: '+e.message,'error');});
}
function toggleM1GasBox(id){
  var box=document.getElementById('m1GasBox_'+id);
  var input=document.getElementById('m1Gas_'+id);
  if(!box) return;
  var open=box.style.display==='none' || !box.style.display;
  box.style.display=open?'grid':'none';
  if(open && input) input.focus();
}
function toggleM1RouteBox(id){
  var box=document.getElementById('m1RouteBox_'+id);
  if(!box) return;
  var open=box.style.display==='none' || !box.style.display;
  box.style.display=open?'block':'none';
}
function routeJobPayload(id){
  var sel=document.querySelector('input[name="jobProvider_'+id+'"]:checked');
  if(!sel){showToast('اختر Provider أولاً','error');return;}
  var provider=sel.value;
  var res=document.getElementById('jobRouteResult_'+id);
  if(res) res.innerHTML='<span style="color:var(--muted);">جاري التوجيه إلى '+provider+'...</span>';
  api('/api/v1/admin/tokenization-jobs/'+id+'/route-provider',{method:'POST',body:JSON.stringify({provider:provider})})
    .then(function(r){
      if(res) res.innerHTML='<span style="color:#22c55e;">✅ تم التوجيه إلى '+provider.toUpperCase()+' — '+esc(r.message||'')+'</span>';
      showToast('Routed to '+provider,'ok');
    })
    .catch(function(e){
      if(res) res.innerHTML='<span style="color:#ef4444;">❌ '+esc(e.message)+'</span>';
      showToast('Route error: '+e.message,'error');
    });
}
function deleteJob(id){
  if(!confirm('Delete this M1 job? This cannot be undone.'))return;
  api('/api/v1/admin/tokenization-jobs/'+id,{method:'DELETE'}).then(function(){showToast('M1 job deleted','ok');loadJobs();}).catch(function(e){showToast('Delete error: '+e.message,'error');});
}
function loadJobs(){
  var st=document.getElementById('m1Status').value;
  var url='/api/v1/admin/tokenization-jobs?limit=100'+(st?'&status='+st:'');
  api(url).then(function(rows) {
    if(!Array.isArray(rows))rows=[];
    _m1Rows={}; rows.forEach(function(x){_m1Rows[x.id]=x;});
    document.getElementById('m1Count').textContent=rows.length+' jobs';
    if(!rows.length){document.getElementById('m1Body').innerHTML='<div class="empty-state"><div class="icon">🔄</div>No M1 jobs found</div>';return;}
    var th='<th>ID</th><th>Ref</th><th>Sender</th><th>EUR</th><th>FX Rate</th><th>Token Amount</th><th>Network</th><th>Status</th><th>Error</th><th>Transfer</th><th>Date</th><th>Gas Fee</th><th>Actions</th>';
    var tb=rows.map(function(r){
      var wallet=esc(r.destination_wallet||'');
      var amount=esc(r.usdt_amount||r.eur_amount||'1');
      var target=esc(r.target_asset||'SIG');
      var net=esc(r.network||'ethereum');
      var btns=[];
      var gasInputId='m1Gas_'+r.id;
      if(r.status==='QUEUED') btns.push('<button class="btn btn-primary" data-jid="'+r.id+'" onclick="processJob(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">Process</button>');
      if(r.status==='COMPLETED'||r.status==='FAILED') btns.push('<button class="btn btn-warning" data-jid="'+r.id+'" onclick="reprocessJobSIG(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">⟳ Reprocess with SIG</button>');
      btns.push('<button class="btn btn-ghost" data-jid="'+r.id+'" onclick="toggleM1RouteBox(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">🔀 Route EUR</button>');
      btns.push('<button class="btn btn-ghost" data-jid="'+r.id+'" onclick="toggleM1GasBox(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">Add Gas Fee</button>');
      btns.push('<button class="btn btn-success" data-jid="'+r.id+'" onclick="gasJobInvoice(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">Gas Invoice</button>');
      if(r.status!=='SENDING') btns.push('<button class="btn btn-danger" data-jid="'+r.id+'" onclick="deleteJob(this.dataset.jid)" style="font-size:11px;padding:3px 8px;">Delete</button>');
      var routeBox='<div id="m1RouteBox_'+r.id+'" style="display:none;margin-top:6px;padding:10px 12px;background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);border-radius:8px;">'
        +'<div style="font-size:11px;font-weight:700;color:var(--gold);margin-bottom:8px;">🔀 Route EUR Payload to Provider</div>'
        +'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">'
        +'<label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;padding:5px 10px;border:1px solid var(--glass-border);border-radius:6px;"><input type="radio" name="jobProvider_'+r.id+'" value="moonpay" style="accent-color:var(--brand);"> MoonPay</label>'
        +'<label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;padding:5px 10px;border:1px solid var(--glass-border);border-radius:6px;"><input type="radio" name="jobProvider_'+r.id+'" value="circle" style="accent-color:var(--brand);"> Circle USDC</label>'
        +'<label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;padding:5px 10px;border:1px solid var(--glass-border);border-radius:6px;"><input type="radio" name="jobProvider_'+r.id+'" value="stripe" style="accent-color:var(--brand);"> Stripe</label>'
        +'</div>'
        +'<button class="btn btn-primary" data-jid="'+r.id+'" onclick="routeJobPayload(this.dataset.jid)" style="font-size:11px;padding:4px 10px;">Route & Fund SIG Liquidity</button>'
        +'<div id="jobRouteResult_'+r.id+'" style="margin-top:6px;font-size:11px;"></div>'
        +'</div>';
      var gasBox='<div id="m1GasBox_'+r.id+'" style="display:none;grid-template-columns:minmax(110px,1fr) auto;gap:6px;align-items:center;">'
        +'<input id="'+gasInputId+'" type="number" step="0.00000001" min="0" placeholder="USDT TRC20 amount" style="width:150px;min-height:34px;padding:6px 8px;font-size:11px;">'
        +'<button class="btn btn-ghost" data-net="'+net+'" data-wallet="'+wallet+'" data-amount="'+amount+'" data-target="m1GasEstimate" data-input="'+gasInputId+'" onclick="estimateM1Gas(this.dataset.net,this.dataset.wallet,this.dataset.amount,this.dataset.target,this.dataset.input)" style="font-size:11px;padding:3px 8px;">Check</button>'
        +'<div style="grid-column:1 / -1;color:var(--muted);font-size:10px;">Invoice fee is collected in USDT TRC20 on TRON.</div>'
        +'</div>'
        +'<div id="m1InvStatus_'+r.id+'" style="display:'+(_m1GasOrders&&_m1GasOrders[r.id]?'flex':'none')+';gap:4px;align-items:center;flex-wrap:wrap;margin-top:6px;">'
        +'<span style="font-size:10px;color:var(--muted);">Invoice:</span>'
        +'<button class="btn btn-success" data-jid="'+r.id+'" onclick="setGasInvoiceStatus(this.dataset.jid,\\'COMPLETED\\')" style="font-size:10px;padding:2px 7px;">✅ Paid</button>'
        +'<button class="btn btn-warning" data-jid="'+r.id+'" onclick="setGasInvoiceStatus(this.dataset.jid,\\'PENDING\\')" style="font-size:10px;padding:2px 7px;">⏳ Pending</button>'
        +'<button class="btn btn-danger" data-jid="'+r.id+'" onclick="setGasInvoiceStatus(this.dataset.jid,\\'REFUND\\')" style="font-size:10px;padding:2px 7px;">↩ Refund</button>'
        +'</div>';
      return '<tr>'
      +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,10)+'...</code></td>'
      +'<td>'+(r.sender_reference||'—')+'</td>'
      +'<td>'+(r.sender_name||'—')+'</td>'
      +'<td><strong style="color:#fbbf24;">'+fmtNum(r.eur_amount)+' EUR</strong></td>'
      +'<td>'+(r.fx_rate||'—')+'</td>'
      +'<td>'+(r.usdt_amount?'<strong style="color:#a78bfa;">'+fmtNum(r.usdt_amount)+' '+target+'</strong>':'—')+'</td>'
      +'<td>'+((r.network||'').toUpperCase())+'</td>'
      +'<td>'+badge(r.status)+'</td>'
      +'<td>'+(r.error_message?'<code style="font-size:10px;color:#fca5a5;" title="'+esc(r.error_message)+'">'+esc(r.error_message).slice(0,36)+'...</code>':'—')+'</td>'
      +'<td>'+(r.outbound_transfer_id?'<code style="font-size:10px;">'+r.outbound_transfer_id.slice(0,10)+'...</code>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td>'+routeBox+gasBox+'</td>'
      +'<td>'+btns.join(' ')+'</td>'
      +'</tr>';}).join('');
    document.getElementById('m1Body').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('m1Body').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
loadFx();loadJobs();
setInterval(loadJobs,30000);
</script>
"""

# ─── M1 FUNDS RESERVE ────────────────────────────────────────────────────────

_M1_RESERVE_BODY = """
<div class="page-body">
  <div class="filter-bar" style="justify-content:space-between;">
    <div style="display:flex;gap:8px;align-items:center;">
      <button class="btn btn-ghost" onclick="m1rLoad()">Refresh</button>
      <button class="btn btn-success" onclick="m1rSetStatus('active')">Activate</button>
      <button class="btn btn-warning" onclick="m1rSetStatus('paused')">Pause</button>
      <a class="btn btn-ghost" href="/api/v1/m1-funds/audit.csv" target="_blank" style="text-decoration:none;">Export Audit CSV</a>
      <span id="m1rStatusText" style="color:var(--muted);font-size:12px;">Loading...</span>
    </div>
    <span style="color:var(--muted);font-size:12px;">Admin-only reserve control module</span>
  </div>

  <div class="stats-grid">
    <div class="stat-card"><span>Total Reserve</span><strong id="m1rTotal">—</strong><small>USD</small></div>
    <div class="stat-card"><span>Tokenized Value</span><strong id="m1rTokenized">—</strong><small>USD</small></div>
    <div class="stat-card"><span>Issued Tokens</span><strong id="m1rIssued">—</strong><small>M1F</small></div>
    <div class="stat-card"><span>Available to Mint</span><strong id="m1rAvailable">—</strong><small>M1F</small></div>
    <div class="stat-card"><span>Backing Ratio</span><strong id="m1rBacking">—</strong><small>Reserve / issued</small></div>
    <div class="stat-card"><span>Status</span><strong id="m1rStatus">—</strong><small>Reserve state</small></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Readiness Checks</h3><span id="m1rReadyOverall" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="m1rReadyBody"><div class="empty-state"><div class="icon">R</div>Loading...</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>Token Contracts</h3>
      <div style="display:flex;gap:8px;align-items:center;">
        <span id="m1rContractsStatus" style="color:var(--muted);font-size:12px;">Loading...</span>
        <button class="btn btn-ghost" onclick="m1rSyncContracts()">Sync Blockchain</button>
      </div>
    </div>
    <div id="m1rContractsBody"><div class="empty-state"><div class="icon">T</div>Loading contract data...</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>M1 Tokenization Batches</h3>
      <div style="display:flex;gap:8px;align-items:center;">
        <span id="m1rBatchCount" style="color:var(--muted);font-size:12px;">Loading...</span>
        <button class="btn btn-primary" onclick="m1rShowBatchForm()">+ Create Batch</button>
      </div>
    </div>
    <div id="m1rBatchCards" class="stats-grid" style="padding:14px;"></div>
    <div id="m1rBatchForm" style="display:none;padding:14px;border-top:1px solid var(--line);">
      <div class="form-grid">
        <div class="form-field"><label>Batch ID (optional)</label><input id="m1bId" placeholder="M1-ALSHUMOOKH-2026-USD-001"></div>
        <div class="form-field"><label>Sender Reference</label><input id="m1bSenderRef" placeholder="TEST-M1-USD-001"></div>
        <div class="form-field"><label>Sender Name</label><input id="m1bSenderName" placeholder="Sender Name"></div>
        <div class="form-field"><label>Sender Wallet</label><input id="m1bSenderWallet" placeholder="0x... optional"></div>
        <div class="form-field"><label>Source Asset Type</label><input id="m1bAssetType" value="M1 Funds"></div>
        <div class="form-field"><label>Source Network</label><input id="m1bSourceNetwork" value="Internal"></div>
        <div class="form-field"><label>Source Transaction Hash / Ref</label><input id="m1bSourceHash" placeholder="REF-..."></div>
        <div class="form-field"><label>Currency</label><select id="m1bCurrency"><option value="USD">USD</option><option value="EUR">EUR</option></select></div>
        <div class="form-field"><label>Total Reserve Value</label><input id="m1bTotal" type="number" step="0.01" placeholder="100000000.00"></div>
        <div class="form-field"><label>Tokenized Value</label><input id="m1bTokenized" type="number" step="0.01" placeholder="10000000.00"></div>
        <div class="form-field"><label>FX Rate to USD</label><input id="m1bFx" type="number" step="0.00000001" value="1.00"></div>
        <div class="form-field"><label>FX Rate Source</label><input id="m1bFxSource" value="manual"></div>
        <div class="form-field"><label>Valuation Date</label><input id="m1bValuation" type="datetime-local"></div>
        <div class="form-field"><label>Proof Document Hash</label><input id="m1bProof" placeholder="0x..."></div>
        <div class="form-field"><label>Created By</label><input id="m1bCreatedBy" value="admin"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px;">
        <button class="btn btn-success" onclick="m1rCreateBatch()">Create Batch</button>
        <button class="btn btn-ghost" onclick="document.getElementById('m1rBatchForm').style.display='none'">Cancel</button>
      </div>
    </div>
    <div id="m1rBatchBody"><div class="empty-state"><div class="icon">B</div>Loading batches...</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Reserve Update</h3></div>
      <div class="form-grid" style="padding:14px;">
        <div class="form-field"><label>Total Reserve Value (USD)</label><input id="m1rTotalIn" type="number" step="0.01" placeholder="10000000.00"></div>
        <div class="form-field"><label>Tokenized Value (USD)</label><input id="m1rTokenizedIn" type="number" step="0.01" placeholder="1000000.00"></div>
        <div class="form-field"><label>Valuation Date</label><input id="m1rValuation" type="datetime-local"></div>
        <div class="form-field"><label>Proof Document Hash</label><input id="m1rProof" placeholder="0x..."></div>
        <div class="form-field"><label>Approved By</label><input id="m1rApprovedBy" placeholder="admin" value="admin"></div>
      </div>
      <div style="padding:0 14px 14px;"><button class="btn btn-primary" onclick="m1rUpdateReserve()">Update Reserve</button></div>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>Mint / Redeem Requests</h3></div>
      <div class="form-grid" style="padding:14px;">
        <div class="form-field"><label>Wallet</label><input id="m1rWallet" placeholder="0x..."></div>
        <div class="form-field"><label>Amount</label><input id="m1rAmount" type="number" step="0.01" placeholder="100000.00"></div>
        <div class="form-field"><label>Reason</label><input id="m1rReason" placeholder="Initial M1F tokenization"></div>
        <div class="form-field"><label>Network</label><input id="m1rNetwork" value="ERC20"></div>
      </div>
      <div style="padding:0 14px 14px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-success" onclick="m1rMintRequest()">Create Mint Approval</button>
        <button class="btn btn-warning" onclick="m1rRedeemRequest()">Create Redeem Approval</button>
      </div>
      <div id="m1rLastApproval" style="padding:0 14px 14px;color:var(--muted);font-size:12px;"></div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Mint Confirmation</h3></div>
      <div class="form-grid" style="padding:14px;">
        <div class="form-field"><label>Mint ID</label><input id="m1rMintId" placeholder="MINT-..."></div>
        <div class="form-field"><label>TX Hash</label><input id="m1rMintTx" placeholder="0x..."></div>
        <div class="form-field"><label>Contract Address</label><input id="m1rMintContract" placeholder="0x..."></div>
        <div class="form-field"><label>Wallet</label><input id="m1rMintWallet" placeholder="0x..."></div>
        <div class="form-field"><label>Amount</label><input id="m1rMintAmount" type="number" step="0.01"></div>
        <div class="form-field"><label>Block Number</label><input id="m1rMintBlock" placeholder="Optional"></div>
      </div>
      <div style="padding:0 14px 14px;"><button class="btn btn-success" onclick="m1rConfirmMint()">Confirm Mint</button></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Burn Confirmation</h3></div>
      <div class="form-grid" style="padding:14px;">
        <div class="form-field"><label>Redeem ID</label><input id="m1rRedeemId" placeholder="RED-..."></div>
        <div class="form-field"><label>TX Hash</label><input id="m1rBurnTx" placeholder="0x..."></div>
        <div class="form-field"><label>Contract Address</label><input id="m1rBurnContract" placeholder="0x..."></div>
        <div class="form-field"><label>Wallet</label><input id="m1rBurnWallet" placeholder="0x..."></div>
        <div class="form-field"><label>Amount</label><input id="m1rBurnAmount" type="number" step="0.01"></div>
        <div class="form-field"><label>Block Number</label><input id="m1rBurnBlock" placeholder="Optional"></div>
      </div>
      <div style="padding:0 14px 14px;"><button class="btn btn-danger" onclick="m1rConfirmBurn()">Confirm Burn</button></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>M1 Audit Logs</h3><span id="m1rAuditCount" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="m1rAuditBody"><div class="empty-state"><div class="icon">🏦</div>Loading...</div></div>
  </div>

  <div class="panel" id="m1rDetailPanel" style="display:none;">
    <div class="panel-head"><h3>Selected Operation Detail</h3><button class="btn btn-ghost" onclick="document.getElementById('m1rDetailPanel').style.display='none'">Close</button></div>
    <pre id="m1rDetailBody" style="white-space:pre-wrap;overflow:auto;background:#0f172a;border:1px solid var(--line);border-radius:8px;padding:12px;font-size:11px;color:#dbeafe;margin:14px;"></pre>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Mint Requests</h3><span id="m1rMintCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rMintBody"><div class="empty-state"><div class="icon">M</div>Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Redeem Requests</h3><span id="m1rRedeemCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rRedeemBody"><div class="empty-state"><div class="icon">R</div>Loading...</div></div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Oracle Reads</h3><span id="m1rOracleCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rOracleBody"><div class="empty-state"><div class="icon">O</div>Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Webhook Events</h3><span id="m1rWebhookCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rWebhookBody"><div class="empty-state"><div class="icon">W</div>Loading...</div></div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel">
      <div class="panel-head"><h3>Reserve Snapshots</h3><span id="m1rSnapshotCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rSnapshotBody"><div class="empty-state"><div class="icon">S</div>Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>API Signatures</h3><span id="m1rSignatureCount" style="color:var(--muted);font-size:12px;"></span></div>
      <div id="m1rSignatureBody"><div class="empty-state"><div class="icon">A</div>Loading...</div></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Blockchain Confirmations</h3><span id="m1rConfirmationCount" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="m1rConfirmationBody"><div class="empty-state"><div class="icon">C</div>Loading...</div></div>
  </div>
</div>
<script>
function m1rVal(id){var el=document.getElementById(id);return el?el.value.trim():'';}
function m1rIdem(prefix){return prefix+'-'+Date.now()+'-'+Math.random().toString(16).slice(2);}
function m1rISOFromLocal(id){
  var v=m1rVal(id);
  if(!v)return '';
  try{return new Date(v).toISOString();}catch(e){return v;}
}
function m1rLoad(){
  document.getElementById('m1rStatusText').textContent='Loading...';
  api('/api/v1/m1-funds/reserve').then(function(r){
    document.getElementById('m1rTotal').textContent=fmtNum(r.total_reserve_value);
    document.getElementById('m1rTokenized').textContent=fmtNum(r.tokenized_value);
    document.getElementById('m1rIssued').textContent=fmtNum(r.issued_tokens);
    document.getElementById('m1rAvailable').textContent=fmtNum(r.available_to_mint);
    document.getElementById('m1rBacking').textContent=r.backing_ratio||'N/A';
    document.getElementById('m1rStatus').innerHTML=badge((r.status||'active').toUpperCase());
    document.getElementById('m1rStatusText').textContent='Last updated: '+fmtDate(r.last_updated);
  }).catch(function(e){
    document.getElementById('m1rStatusText').textContent='Error: '+e.message;
    showToast('M1 reserve error: '+e.message,'error');
  });
  api('/api/v1/m1-funds/readiness').then(function(r){
    document.getElementById('m1rReadyOverall').textContent=r.overall||'—';
    var rows=(r.checks||[]);
    if(!rows.length){document.getElementById('m1rReadyBody').innerHTML='<div class="empty-state"><div class="icon">R</div>No readiness checks</div>';return;}
    var tb=rows.map(function(x){return '<tr><td>'+esc(x.name||'')+'</td><td>'+badge(String(x.status||'').toUpperCase())+'</td><td>'+esc(x.detail||'')+'</td></tr>';}).join('');
    document.getElementById('m1rReadyBody').innerHTML='<div class="table-wrap"><table><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('m1rReadyBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  m1rLoadContracts(false);
  m1rLoadBatches();
  api('/api/v1/m1-funds/audit?limit=100').then(function(r){
    var rows=(r.events||[]);
    document.getElementById('m1rAuditCount').textContent=rows.length+' events';
    if(!rows.length){document.getElementById('m1rAuditBody').innerHTML='<div class="empty-state"><div class="icon">🏦</div>No M1 audit events yet</div>';return;}
    var th='<th>Event</th><th>Fund</th><th>Batch</th><th>Actor</th><th>TX</th><th>Proof</th><th>Time</th>';
    var tb=rows.map(function(x){return '<tr><td>'+esc(x.type||'')+'</td><td><code style="font-size:10px;">'+esc(x.fund_id||'—')+'</code></td><td><code style="font-size:10px;">'+esc(x.batch_id||'—')+'</code></td><td>'+esc(x.actor||'—')+'</td><td>'+(x.tx_hash?'<code style="font-size:10px;">'+esc(x.tx_hash).slice(0,18)+'...</code>':'—')+'</td><td>'+(x.proof_document_hash?'<code style="font-size:10px;">'+esc(x.proof_document_hash).slice(0,18)+'...</code>':'—')+'</td><td style="font-size:11px;">'+fmtDate(x.timestamp)+'</td></tr>';}).join('');
    document.getElementById('m1rAuditBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('m1rAuditBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  m1rLoadLists();
}
function m1rContractCard(title, token, extra){
  token=token||{};
  var status=token.reachable?'READY':'NOT_READY';
  var err=token.error?'<div style="color:#f87171;font-size:11px;margin-top:6px;">'+esc(token.error)+'</div>':'';
  var max=token.max_supply?'<div class="stat-card"><span>Max Supply</span><strong>'+fmtNum(token.max_supply)+'</strong><small>'+esc(token.official_symbol||token.symbol||'')+'</small></div>':'';
  return '<div class="panel" style="margin:0;">'
    +'<div class="panel-head"><h3>'+esc(title)+'</h3>'+badge(status)+'</div>'
    +'<div style="padding:14px;display:grid;gap:10px;">'
    +'<div><span style="color:var(--muted);font-size:12px;">Official Name</span><br><strong>'+esc(token.official_name||token.name||'—')+'</strong></div>'
    +(token.arabic_display_name?'<div><span style="color:var(--muted);font-size:12px;">Arabic Display</span><br><strong>'+esc(token.arabic_display_name)+'</strong></div>':'')
    +'<div><span style="color:var(--muted);font-size:12px;">Contract Address</span><br><code style="font-size:11px;word-break:break-all;">'+esc(token.address||'—')+'</code></div>'
    +'<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));">'
    +'<div class="stat-card"><span>Contract Name</span><strong>'+esc(token.name||'—')+'</strong><small>On-chain</small></div>'
    +'<div class="stat-card"><span>Symbol</span><strong>'+esc(token.symbol||token.official_symbol||'—')+'</strong><small>decimals '+esc(String(token.decimals||'—'))+'</small></div>'
    +'<div class="stat-card"><span>Total Supply</span><strong>'+fmtNum(token.total_supply||0)+'</strong><small>'+esc(token.official_symbol||token.symbol||'')+'</small></div>'
    +'<div class="stat-card"><span>Treasury Balance</span><strong>'+fmtNum(token.treasury_balance||0)+'</strong><small>'+esc(token.official_symbol||token.symbol||'')+'</small></div>'
    +max
    +'</div>'+err+(extra||'')+'</div></div>';
}
function m1rLoadContracts(showToastOnSuccess){
  document.getElementById('m1rContractsStatus').textContent='Loading...';
  api('/api/v1/m1-funds/token-contracts').then(function(r){
    var chain=r.chain||{};
    var warnings=(r.warnings||[]).map(function(w){return '<div style="border:1px solid rgba(245,158,11,.35);background:rgba(245,158,11,.08);color:#facc15;border-radius:8px;padding:9px;margin-top:8px;">'+esc(w)+'</div>';}).join('');
    var top='<div style="padding:14px;display:grid;gap:12px;">'
      +'<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));">'
      +'<div class="stat-card"><span>Network</span><strong>'+esc(r.network||'—')+'</strong><small>Configured token network</small></div>'
      +'<div class="stat-card"><span>Chain ID</span><strong>'+esc(String(chain.chain_id_actual||'—'))+'</strong><small>Expected '+esc(String(chain.chain_id_expected||''))+'</small></div>'
      +'<div class="stat-card"><span>RPC Status</span><strong>'+esc(String(r.rpc_status||'—'))+'</strong><small>'+esc(chain.error||'Sepolia RPC')+'</small></div>'
      +'<div class="stat-card"><span>Readiness</span><strong>'+esc(String(r.readiness_status||'—'))+'</strong><small>Contracts + RPC</small></div>'
      +'</div>'
      +'<div><span style="color:var(--muted);font-size:12px;">Treasury Wallet</span><br><code style="font-size:11px;word-break:break-all;">'+esc(r.treasury_wallet||'—')+'</code></div>'
      +warnings
      +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">'
      +m1rContractCard('M1 Contract',r.m1||{})
      +m1rContractCard('SIG Contract',r.sig||{})
      +'</div></div>';
    document.getElementById('m1rContractsBody').innerHTML=top;
    document.getElementById('m1rContractsStatus').textContent='Last sync: '+fmtDate(r.last_sync_at);
    if(showToastOnSuccess) showToast('Blockchain sync completed','ok');
  }).catch(function(e){
    document.getElementById('m1rContractsStatus').textContent='Error';
    document.getElementById('m1rContractsBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';
  });
}
function m1rSyncContracts(){
  document.getElementById('m1rContractsStatus').textContent='Syncing...';
  api('/api/v1/m1-funds/blockchain-sync',{method:'POST',body:JSON.stringify({})}).then(function(r){
    document.getElementById('m1rContractsStatus').textContent='Last sync: '+fmtDate(r.last_sync_at);
    m1rLoadContracts(true);
    m1rLoadLists();
  }).catch(function(e){showToast('Blockchain sync error: '+e.message,'error');m1rLoadContracts(false);});
}
function m1rMoney(v,symbol){return fmtNum(v||0)+' '+esc(symbol||'');}
function m1rShowBatchForm(){
  var el=document.getElementById('m1rBatchForm');
  el.style.display=el.style.display==='none'?'block':'none';
}
function m1rLoadBatches(){
  api('/api/v1/m1-funds/batches?limit=100').then(function(r){
    var s=r.batch_summary||{};
    var cs=s.currency_summary||{};
    var usd=cs.USD||{}, eur=cs.EUR||{};
    document.getElementById('m1rBatchCount').textContent=(r.items||[]).length+' batches';
    document.getElementById('m1rBatchCards').innerHTML=
      '<div class="stat-card"><span>Total Reserve USD</span><strong>'+m1rMoney(usd.total_reserve_value,'USD')+'</strong><small>USD batches</small></div>'
      +'<div class="stat-card"><span>Total Reserve EUR</span><strong>'+m1rMoney(eur.total_reserve_value,'EUR')+'</strong><small>EUR batches</small></div>'
      +'<div class="stat-card"><span>Tokenized USD</span><strong>'+m1rMoney(usd.tokenized_value,'USD')+'</strong><small>USD batches</small></div>'
      +'<div class="stat-card"><span>Tokenized EUR</span><strong>'+m1rMoney(eur.tokenized_value,'EUR')+'</strong><small>EUR batches</small></div>'
      +'<div class="stat-card"><span>Total USD Equivalent</span><strong>'+m1rMoney(s.total_tokenized_value_usd_equivalent,'USD')+'</strong><small>All batches</small></div>'
      +'<div class="stat-card"><span>Issued Tokens</span><strong>'+m1rMoney(s.total_issued_tokens,'M1')+'</strong><small>Batch issued sum</small></div>'
      +'<div class="stat-card"><span>Available to Mint</span><strong>'+m1rMoney(s.total_available_to_mint,'M1')+'</strong><small>All batches</small></div>'
      +'<div class="stat-card"><span>Active / USD / EUR</span><strong>'+esc(String(s.active_batches_count||0))+' / '+esc(String(s.usd_batches_count||0))+' / '+esc(String(s.eur_batches_count||0))+'</strong><small>Batch counts</small></div>';
    var rows=r.items||[];
    if(!rows.length){document.getElementById('m1rBatchBody').innerHTML='<div class="empty-state"><div class="icon">B</div>No tokenization batches yet</div>';return;}
    var th='<th>Batch ID</th><th>Sender Ref</th><th>Sender</th><th>Source</th><th>Currency</th><th>FX</th><th>Reserve</th><th>Tokenized</th><th>Tokenized USD</th><th>Issued</th><th>Available</th><th>Proof</th><th>Status</th><th>Actions</th>';
    var tb=rows.map(function(x){
      return '<tr>'
        +'<td><code style="font-size:10px;">'+esc(x.batch_id||'')+'</code></td>'
        +'<td>'+esc(x.sender_reference||'—')+'</td>'
        +'<td>'+esc(x.sender_name||'—')+'</td>'
        +'<td>'+esc(x.source_asset_type||'—')+'</td>'
        +'<td><strong>'+esc(x.currency||'')+'</strong></td>'
        +'<td>'+esc(String(x.fx_rate_to_usd||'—'))+'</td>'
        +'<td>'+m1rMoney(x.total_reserve_value,x.currency)+'</td>'
        +'<td>'+m1rMoney(x.tokenized_value,x.currency)+'</td>'
        +'<td>'+m1rMoney(x.tokenized_value_usd,'USD')+'</td>'
        +'<td>'+m1rMoney(x.issued_tokens,'M1')+'</td>'
        +'<td>'+m1rMoney(x.available_to_mint,'M1')+'</td>'
        +'<td>'+(x.proof_document_hash?'<code style="font-size:10px;">'+esc(x.proof_document_hash).slice(0,14)+'...</code>':'—')+'</td>'
        +'<td>'+badge(String(x.status||'').toUpperCase())+'</td>'
        +'<td>'+m1rBatchActions(x)+'</td>'
        +'</tr>';
    }).join('');
    document.getElementById('m1rBatchBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('m1rBatchBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
}
function m1rBatchActions(x){
  var id=esc(x.batch_id||'');
  return '<div style="display:flex;gap:5px;flex-wrap:wrap;">'
    +'<button class="btn btn-ghost" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" onclick="m1rViewBatch(this.dataset.id)">View</button>'
    +'<button class="btn btn-success" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" data-action="approve" onclick="m1rBatchStatus(this.dataset.id,this.dataset.action)">Approve</button>'
    +'<button class="btn btn-warning" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" data-action="pause" onclick="m1rBatchStatus(this.dataset.id,this.dataset.action)">Pause</button>'
    +'<button class="btn btn-danger" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" data-action="close" onclick="m1rBatchStatus(this.dataset.id,this.dataset.action)">Close</button>'
    +'<button class="btn btn-primary" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" onclick="m1rReconcileBatch(this.dataset.id)">Reconcile</button>'
    +'<button class="btn btn-ghost" style="font-size:10px;padding:4px 7px;" data-id="'+id+'" onclick="m1rExportBatch(this.dataset.id)">Export</button>'
    +'</div>';
}
function m1rCreateBatch(){
  var body={
    batch_id:m1rVal('m1bId')||null,
    sender_reference:m1rVal('m1bSenderRef'),
    sender_name:m1rVal('m1bSenderName')||null,
    sender_wallet:m1rVal('m1bSenderWallet')||null,
    source_asset_type:m1rVal('m1bAssetType')||'M1 Funds',
    source_network:m1rVal('m1bSourceNetwork')||'Internal',
    source_transaction_hash:m1rVal('m1bSourceHash')||null,
    total_reserve_value:m1rVal('m1bTotal'),
    tokenized_value:m1rVal('m1bTokenized'),
    currency:m1rVal('m1bCurrency')||'USD',
    fx_rate_to_usd:m1rVal('m1bFx')||'1.00',
    fx_rate_source:m1rVal('m1bFxSource')||'manual',
    valuation_date:m1rISOFromLocal('m1bValuation'),
    proof_document_hash:m1rVal('m1bProof'),
    created_by:m1rVal('m1bCreatedBy')||'admin',
    metadata_json:{testnet:true}
  };
  api('/api/v1/m1-funds/batches',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Batch created','ok');document.getElementById('m1rBatchForm').style.display='none';m1rLoad();}).catch(function(e){showToast('Batch create error: '+e.message,'error');});
}
function m1rViewBatch(id){
  api('/api/v1/m1-funds/batches/'+encodeURIComponent(id)).then(function(r){
    document.getElementById('m1rDetailPanel').style.display='block';
    document.getElementById('m1rDetailBody').textContent=JSON.stringify(r,null,2);
    document.getElementById('m1rDetailPanel').scrollIntoView({behavior:'smooth',block:'center'});
  }).catch(function(e){showToast('Batch detail error: '+e.message,'error');});
}
function m1rBatchStatus(id,action){
  var reason=prompt('Reason for '+action+' batch '+id+' (optional):')||'';
  api('/api/v1/m1-funds/batches/'+encodeURIComponent(id)+'/'+action,{method:'POST',body:JSON.stringify({actor:'admin',reason:reason})}).then(function(){showToast('Batch '+action+' saved','ok');m1rLoad();}).catch(function(e){showToast('Batch '+action+' error: '+e.message,'error');});
}
function m1rReconcileBatch(id){
  var issued=prompt('Issued M1 tokens for this batch:');
  if(!issued)return;
  var tx=prompt('Mint tx_hash (optional). Leave empty for manual admin reconciliation:')||'';
  api('/api/v1/m1-funds/batches/'+encodeURIComponent(id)+'/reconcile',{method:'POST',body:JSON.stringify({issued_tokens:issued,mint_tx_hash:tx||null,source:tx?'sepolia_tx_hash':'manual_admin_reconciliation',approved_by:'admin'})}).then(function(){showToast('Batch reconciled','ok');m1rLoad();}).catch(function(e){showToast('Batch reconcile error: '+e.message,'error');});
}
function m1rExportBatch(id){
  api('/api/v1/m1-funds/batches/'+encodeURIComponent(id)+'/export').then(function(data){
    var blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
    var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=id+'.json';a.click();
    showToast('Batch exported','ok');
  }).catch(function(e){showToast('Batch export error: '+e.message,'error');});
}
function m1rTinyTable(target,countId,rows,columns,emptyIcon,emptyText){
  document.getElementById(countId).textContent=rows.length+' items';
  if(!rows.length){document.getElementById(target).innerHTML='<div class="empty-state"><div class="icon">'+emptyIcon+'</div>'+emptyText+'</div>';return;}
  var th=columns.map(function(c){return '<th>'+esc(c.label)+'</th>';}).join('');
  var tb=rows.map(function(r){
    return '<tr>'+columns.map(function(c){
      var v=(typeof c.value==='function')?c.value(r):r[c.value];
      return '<td>'+v+'</td>';
    }).join('')+'</tr>';
  }).join('');
  document.getElementById(target).innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
function m1rLoadLists(){
  api('/api/v1/m1-funds/mint-requests?limit=50').then(function(r){
    m1rTinyTable('m1rMintBody','m1rMintCount',r.items||[],[
      {label:'Mint ID',value:function(x){return '<code style="font-size:10px;">'+esc(x.mint_id||'')+'</code>';}},
      {label:'Amount',value:function(x){return '<strong>'+fmtNum(x.amount)+'</strong>';}},
      {label:'Status',value:function(x){return badge(String(x.status||'').toUpperCase());}},
      {label:'TX',value:function(x){return x.tx_hash?'<code style="font-size:10px;">'+esc(x.tx_hash).slice(0,14)+'...</code>':'—';}},
      {label:'Date',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.created_at)+'</span>';}},
      {label:'Actions',value:function(x){return m1rReqActions('mint',x.mint_id,x.status);}}
    ],'M','No mint requests yet');
  }).catch(function(e){document.getElementById('m1rMintBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/redeem-requests?limit=50').then(function(r){
    m1rTinyTable('m1rRedeemBody','m1rRedeemCount',r.items||[],[
      {label:'Redeem ID',value:function(x){return '<code style="font-size:10px;">'+esc(x.redeem_id||'')+'</code>';}},
      {label:'Amount',value:function(x){return '<strong>'+fmtNum(x.amount)+'</strong>';}},
      {label:'Status',value:function(x){return badge(String(x.status||'').toUpperCase());}},
      {label:'TX',value:function(x){return x.tx_hash?'<code style="font-size:10px;">'+esc(x.tx_hash).slice(0,14)+'...</code>':'—';}},
      {label:'Date',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.created_at)+'</span>';}},
      {label:'Actions',value:function(x){return m1rReqActions('redeem',x.redeem_id,x.status);}}
    ],'R','No redeem requests yet');
  }).catch(function(e){document.getElementById('m1rRedeemBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/oracle-reads?limit=50').then(function(r){
    m1rTinyTable('m1rOracleBody','m1rOracleCount',r.items||[],[
      {label:'Client',value:function(x){return esc(x.client_id||'public');}},
      {label:'IP',value:function(x){return esc(x.ip_address||'—');}},
      {label:'Hash',value:function(x){return '<code style="font-size:10px;">'+esc(x.response_hash||'').slice(0,14)+'...</code>';}},
      {label:'Time',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.timestamp)+'</span>';}}
    ],'O','No oracle reads yet');
  }).catch(function(e){document.getElementById('m1rOracleBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/webhook-events?limit=50').then(function(r){
    m1rTinyTable('m1rWebhookBody','m1rWebhookCount',r.items||[],[
      {label:'Event',value:function(x){return esc(x.event||'');}},
      {label:'Status',value:function(x){return badge(String(x.status||'').toUpperCase());}},
      {label:'Code',value:function(x){return esc(String(x.status_code||'—'));}},
      {label:'Time',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.created_at)+'</span>';}}
    ],'W','No webhook events yet');
  }).catch(function(e){document.getElementById('m1rWebhookBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/snapshots?limit=50').then(function(r){
    m1rTinyTable('m1rSnapshotBody','m1rSnapshotCount',r.items||[],[
      {label:'Reserve',value:function(x){return fmtNum(x.total_reserve_value)+' USD';}},
      {label:'Tokenized',value:function(x){return fmtNum(x.tokenized_value)+' USD';}},
      {label:'Proof',value:function(x){return x.proof_document_hash?'<code style="font-size:10px;">'+esc(x.proof_document_hash).slice(0,16)+'...</code>':'—';}},
      {label:'Approved By',value:function(x){return esc(x.approved_by||'—');}},
      {label:'Time',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.created_at)+'</span>';}}
    ],'S','No reserve snapshots yet');
  }).catch(function(e){document.getElementById('m1rSnapshotBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/signatures?limit=50').then(function(r){
    m1rTinyTable('m1rSignatureBody','m1rSignatureCount',r.items||[],[
      {label:'Scope',value:function(x){return esc(x.scope||'');}},
      {label:'Hash',value:function(x){return '<code style="font-size:10px;">'+esc(x.response_hash||'').slice(0,16)+'...</code>';}},
      {label:'Signature',value:function(x){return '<code style="font-size:10px;">'+esc(x.signature||'').slice(0,16)+'...</code>';}},
      {label:'Time',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.timestamp)+'</span>';}}
    ],'A','No API signatures yet');
  }).catch(function(e){document.getElementById('m1rSignatureBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
  api('/api/v1/m1-funds/confirmations?limit=50').then(function(r){
    m1rTinyTable('m1rConfirmationBody','m1rConfirmationCount',r.items||[],[
      {label:'Type',value:function(x){return esc(x.request_type||'');}},
      {label:'Request',value:function(x){return '<code style="font-size:10px;">'+esc(x.request_id||'')+'</code>';}},
      {label:'Amount',value:function(x){return fmtNum(x.amount)+' M1F';}},
      {label:'TX',value:function(x){return '<code style="font-size:10px;">'+esc(x.tx_hash||'').slice(0,18)+'...</code>';}},
      {label:'Verification',value:function(x){return badge(String(x.verification_status||'').toUpperCase());}},
      {label:'Time',value:function(x){return '<span style="font-size:11px;">'+fmtDate(x.created_at)+'</span>';}}
    ],'C','No blockchain confirmations yet');
  }).catch(function(e){document.getElementById('m1rConfirmationBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message)+'</div>';});
}
function m1rReqActions(type,id,status){
  var safeId=esc(id||'');
  var safeType=esc(type||'');
  var canClose=!['CONFIRMED','COMPLETED','REJECTED','EXPIRED'].includes(String(status||'').toUpperCase());
  return '<div style="display:flex;gap:5px;flex-wrap:wrap;"><button class="btn btn-ghost" style="font-size:10px;padding:4px 7px;" data-type="'+safeType+'" data-id="'+safeId+'" onclick="m1rViewReq(this.dataset.type,this.dataset.id)">View</button>'
    +(canClose?'<button class="btn btn-warning" style="font-size:10px;padding:4px 7px;" data-type="'+safeType+'" data-id="'+safeId+'" data-action="expire" onclick="m1rDecision(this.dataset.type,this.dataset.id,this.dataset.action)">Expire</button><button class="btn btn-danger" style="font-size:10px;padding:4px 7px;" data-type="'+safeType+'" data-id="'+safeId+'" data-action="reject" onclick="m1rDecision(this.dataset.type,this.dataset.id,this.dataset.action)">Reject</button>':'')+'</div>';
}
function m1rViewReq(type,id){
  var url=type==='mint'?'/api/v1/m1-funds/mint-requests/'+encodeURIComponent(id):'/api/v1/m1-funds/redeem-requests/'+encodeURIComponent(id);
  api(url).then(function(r){
    document.getElementById('m1rDetailPanel').style.display='block';
    document.getElementById('m1rDetailBody').textContent=JSON.stringify(r,null,2);
    document.getElementById('m1rDetailPanel').scrollIntoView({behavior:'smooth',block:'center'});
  }).catch(function(e){showToast('Detail error: '+e.message,'error');});
}
function m1rDecision(type,id,action){
  var reason=prompt('Reason for '+action+' (optional):')||'';
  var url=type==='mint'?'/api/v1/m1-funds/mint-requests/'+encodeURIComponent(id)+'/'+action:'/api/v1/m1-funds/redeem-requests/'+encodeURIComponent(id)+'/'+action;
  api(url,{method:'POST',body:JSON.stringify({reason:reason,actor:'admin'})}).then(function(){showToast(action+' saved','ok');m1rLoad();}).catch(function(e){showToast(action+' error: '+e.message,'error');});
}
function m1rSetStatus(status){
  var reason=prompt('Reason for setting reserve status to '+status+':')||'';
  api('/api/v1/m1-funds/status',{method:'PATCH',body:JSON.stringify({status:status,reason:reason,actor:'admin'})}).then(function(){showToast('Reserve status updated','ok');m1rLoad();}).catch(function(e){showToast('Status update error: '+e.message,'error');});
}
function m1rUpdateReserve(){
  var body={total_reserve_value:m1rVal('m1rTotalIn'),tokenized_value:m1rVal('m1rTokenizedIn'),valuation_date:m1rISOFromLocal('m1rValuation'),proof_document_hash:m1rVal('m1rProof'),approved_by:m1rVal('m1rApprovedBy')||'admin'};
  api('/api/v1/m1-funds/reserve-update',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Reserve updated','ok');m1rLoad();}).catch(function(e){showToast('Reserve update error: '+e.message,'error');});
}
function m1rApprovalBody(){return {wallet:m1rVal('m1rWallet'),amount:m1rVal('m1rAmount'),reason:m1rVal('m1rReason')||null,network:m1rVal('m1rNetwork')||'ERC20'};}
function m1rMintRequest(){
  api('/api/v1/m1-funds/mint-request',{method:'POST',headers:{'X-Idempotency-Key':m1rIdem('mint')},body:JSON.stringify(m1rApprovalBody())}).then(function(r){
    document.getElementById('m1rLastApproval').innerHTML='<strong>Mint approval:</strong> '+esc(r.mint_id)+' · '+esc(r.amount)+' · expires '+fmtDate(r.expires_at);
    document.getElementById('m1rMintId').value=r.mint_id||'';
    document.getElementById('m1rMintWallet').value=r.wallet||'';
    document.getElementById('m1rMintAmount').value=r.amount||'';
    showToast('Mint approval created','ok');m1rLoad();
  }).catch(function(e){showToast('Mint request error: '+e.message,'error');});
}
function m1rRedeemRequest(){
  api('/api/v1/m1-funds/redeem-request',{method:'POST',headers:{'X-Idempotency-Key':m1rIdem('redeem')},body:JSON.stringify(m1rApprovalBody())}).then(function(r){
    document.getElementById('m1rLastApproval').innerHTML='<strong>Redeem approval:</strong> '+esc(r.redeem_id)+' · '+esc(r.amount)+' · expires '+fmtDate(r.expires_at);
    document.getElementById('m1rRedeemId').value=r.redeem_id||'';
    document.getElementById('m1rBurnWallet').value=r.wallet||'';
    document.getElementById('m1rBurnAmount').value=r.amount||'';
    showToast('Redeem approval created','ok');m1rLoad();
  }).catch(function(e){showToast('Redeem request error: '+e.message,'error');});
}
function m1rConfirmMint(){
  var body={mint_id:m1rVal('m1rMintId'),tx_hash:m1rVal('m1rMintTx'),contract_address:m1rVal('m1rMintContract'),wallet:m1rVal('m1rMintWallet'),amount:m1rVal('m1rMintAmount'),network:'ERC20',block_number:m1rVal('m1rMintBlock')||null};
  api('/api/v1/m1-funds/mint-confirmation',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Mint confirmed','ok');m1rLoad();}).catch(function(e){showToast('Mint confirmation error: '+e.message,'error');});
}
function m1rConfirmBurn(){
  var body={redeem_id:m1rVal('m1rRedeemId'),tx_hash:m1rVal('m1rBurnTx'),contract_address:m1rVal('m1rBurnContract'),wallet:m1rVal('m1rBurnWallet'),amount:m1rVal('m1rBurnAmount'),network:'ERC20',block_number:m1rVal('m1rBurnBlock')||null};
  api('/api/v1/m1-funds/burn-confirmation',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Burn confirmed','ok');m1rLoad();}).catch(function(e){showToast('Burn confirmation error: '+e.message,'error');});
}
m1rLoad();
</script>
"""

# ─── MONITORING ───────────────────────────────────────────────────────────────

_MONITORING_BODY = """
<div class="page-body">
  <div class="filter-bar" style="justify-content:space-between;">
    <span id="monLastUp" style="color:var(--muted);font-size:12px;">—</span>
    <div style="display:flex;gap:8px;">
      <label style="color:var(--muted);font-size:12px;display:flex;align-items:center;gap:6px;">
        <input type="checkbox" id="autoR" checked onchange="toggleAuto()"> Auto refresh (10 seconds)
      </label>
      <button class="btn btn-ghost" onclick="loadMon()">Refresh</button>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
    <div class="panel"><div class="panel-head"><h3>Orders</h3></div><div id="monOrders" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>Transfers</h3></div><div id="monXfers" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>M1 Jobs</h3></div><div id="monM1" style="padding:14px;"></div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div class="panel"><div class="panel-head"><h3>Health Indicators</h3></div><div id="monHealth" style="padding:14px;"></div></div>
    <div class="panel"><div class="panel-head"><h3>Settlement Payloads</h3></div><div id="monPayloads" style="padding:14px;"></div></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Latest 5 Transfers</h3></div>
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
  }).join('')+'<div style="margin-top:10px;font-size:12px;color:var(--muted);">Total: <strong style="color:var(--ink);">'+total+'</strong></div>';
}
function loadMon(){
  dashApi('/api/v1/admin/monitoring/live').then(function(m) {
    document.getElementById('monLastUp').textContent='Last updated: '+new Date().toLocaleTimeString('en-US');
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
      var th2='<th>ID</th><th>Network</th><th>Amount</th><th>Status</th><th>TX</th><th>Date</th>';
      var tb2=tr.map(function(r){return '<tr><td><code style="font-size:10px;">'+r.id.slice(0,10)+'...</code></td><td>'+(r.network||'').toUpperCase()+'</td><td>'+fmtNum(r.amount)+' USDT</td><td>'+badge(r.status)+'</td><td>'+(r.tx_hash?r.tx_hash.slice(0,18)+'...':'—')+'</td><td style="font-size:11px;">'+fmtDate(r.created_at)+'</td></tr>';}).join('');
      document.getElementById('monRecentXfer').innerHTML='<div class="table-wrap"><table><thead><tr>'+th2+'</tr></thead><tbody>'+tb2+'</tbody></table></div>';
    }
  }).catch(function(e){
    console.error('Monitor error:',e);
    ['monOrders','monXfers','monM1','monPayloads','monHealth'].forEach(function(id){
      var el=document.getElementById(id);
      if(el) el.innerHTML='<p style="color:#ef4444;font-size:12px;padding:8px;">Error: '+(e.message||e)+'</p>';
    });
    document.getElementById('monRecentXfer').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+(e.message||e)+'</div>';
  });
}
loadMon();
_autoTimer=setInterval(loadMon,10000);
</script>
"""

# ─── PAYMENTS ─────────────────────────────────────────────────────────────────

_PAYMENTS_BODY = """
<div class="page-body">
  <div class="panel">
    <div class="panel-head"><h3>Payment Gateways</h3></div>
    <div style="padding:14px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">
      <a class="btn btn-ghost" href="#moonpay" style="text-decoration:none;text-align:center;">🌙 MoonPay</a>
      <a class="btn btn-ghost" href="#circle" style="text-decoration:none;text-align:center;">⬤ Circle USDC</a>
      <a class="btn btn-ghost" href="#direct" style="text-decoration:none;text-align:center;">🔑 Direct Crypto</a>
      <a class="btn btn-primary" href="/dashboard/stripe" style="text-decoration:none;text-align:center;">💵 Stripe</a>
    </div>
  </div>
  <div class="grid-2">
    <div id="moonpay" class="panel">
      <div class="panel-head"><h3>MoonPay Link</h3></div>
      <div style="padding:14px;display:grid;gap:10px;">
        <input id="mpAmount" placeholder="Fiat amount" inputmode="decimal" value="100.00">
        <input id="mpCurrency" placeholder="Fiat currency" value="USD" maxlength="3">
        <select id="mpNetwork"><option value="ethereum">Ethereum</option><option value="base">Base</option><option value="tron">TRON</option></select>
        <input id="mpEmail" placeholder="Customer email (optional)">
        <button class="btn btn-primary" onclick="createGatewayPayment('moonpay')">Create MoonPay Link</button>
      </div>
    </div>
    <div id="circle" class="panel">
      <div class="panel-head"><h3>Circle USDC Payment</h3></div>
      <div style="padding:14px;display:grid;gap:10px;">
        <input id="circleAmount" placeholder="USD amount" inputmode="decimal" value="100.00">
        <select id="circleNetwork"><option value="ethereum">Ethereum</option><option value="base">Base</option></select>
        <input id="circleEmail" placeholder="Customer email (optional)">
        <button class="btn btn-primary" onclick="createGatewayPayment('circle')">Create Circle Payment</button>
      </div>
    </div>
  </div>
  <div id="direct" class="panel">
    <div class="panel-head"><h3>Direct Crypto Payment</h3></div>
    <div style="padding:14px;display:grid;gap:10px;">
      <input id="directAmount" placeholder="Crypto amount" inputmode="decimal" value="100.00">
      <select id="directAsset"><option value="USDT">USDT</option><option value="USDC">USDC</option><option value="ETH">ETH</option><option value="SIG">SIG</option></select>
      <select id="directNetwork"><option value="ethereum">Ethereum</option><option value="base">Base</option><option value="tron">TRON</option></select>
      <input id="directEmail" placeholder="Payer email (optional)">
      <button class="btn btn-primary" onclick="createGatewayPayment('direct')">Create Direct Crypto Payment</button>
    </div>
  </div>
  <div id="gatewayResult"></div>
  <div id="paySum" style="min-height:120px;"></div>
  <div class="panel">
    <div class="panel-head"><h3>Status Distribution</h3><button class="btn btn-ghost" onclick="loadPayments()" style="font-size:11px;padding:4px 10px;">Refresh</button></div>
    <div id="payStatus" style="padding:14px;display:flex;flex-wrap:wrap;gap:10px;"></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>Latest Orders</h3></div>
    <div id="payTable"><div class="empty-state"><div class="icon">💳</div>Loading...</div></div>
  </div>
</div>
<script>
function gatewayResultBox(title, url, orderId){
  document.getElementById('gatewayResult').innerHTML='<div class="panel" style="border-color:rgba(16,185,129,.45);"><div class="panel-head"><h3>'+esc(title)+'</h3></div><div style="padding:14px;display:grid;gap:10px;"><div><span style="color:var(--muted);font-size:12px;">Order ID</span><br><code>'+esc(orderId||'')+'</code></div><input readonly value="'+esc(url||'')+'" onclick="this.select()"><div style="display:flex;gap:8px;flex-wrap:wrap;"><button class="btn btn-primary" data-url="'+esc(url||'')+'" data-target="_blank" onclick="window.open(this.dataset.url,this.dataset.target)">Open Payment Page</button><button class="btn btn-ghost" data-url="'+esc(url||'')+'" onclick="copyText(this.dataset.url)">Copy Link</button></div></div></div>';
}
function createGatewayPayment(kind){
  var endpoint='', body={};
  if(kind==='moonpay'){
    endpoint='/api/v1/admin/transactions';
    body={fiat_amount:document.getElementById('mpAmount').value,fiat_currency:document.getElementById('mpCurrency').value||'USD',network:document.getElementById('mpNetwork').value,customer_email:document.getElementById('mpEmail').value||null,crypto_currency:'USDC'};
  } else if(kind==='circle'){
    endpoint='/api/v1/admin/circle-payment';
    body={fiat_amount:document.getElementById('circleAmount').value,fiat_currency:'USD',network:document.getElementById('circleNetwork').value,payer_email:document.getElementById('circleEmail').value||null};
  } else {
    endpoint='/api/v1/admin/direct-payment';
    body={crypto_amount:document.getElementById('directAmount').value,crypto_currency:document.getElementById('directAsset').value||'USDT',network:document.getElementById('directNetwork').value,payer_email:document.getElementById('directEmail').value||null};
  }
  api(endpoint,{method:'POST',body:JSON.stringify(body)}).then(function(r){
    gatewayResultBox(kind.toUpperCase()+' payment created', r.payment_url || r.checkout_url, r.id || r.transaction_id);
    loadPayments();
  }).catch(function(e){showToast(e.message||String(e),'error');});
}
function loadPayments(){
  dashApi('/api/v1/admin/summary').then(function(s) {
    document.getElementById('paySum').innerHTML='<div class="stat-grid">'
      +'<div class="stat-card"><div class="label">Total Orders</div><div class="value">'+(s.orders_total||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">Completed</div><div class="value" style="color:#10b981;">'+(s.orders_completed||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">Pending</div><div class="value" style="color:#f59e0b;">'+(s.pending_orders||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">Failed</div><div class="value" style="color:#ef4444;">'+(s.failed_orders||0)+'</div></div>'
      +'<div class="stat-card"><div class="label">Total Fiat</div><div class="value">'+fmtNum(s.total_fiat_amount)+'</div></div>'
      +'<div class="stat-card"><div class="label">Total Crypto</div><div class="value">'+fmtNum(s.total_crypto_amount,6)+'</div></div>'
      +'</div>';
    var bs=s.by_status||{};
    document.getElementById('payStatus').innerHTML=Object.keys(bs).map(function(st){return '<div style="padding:8px 14px;border-radius:8px;background:rgba(255,255,255,.05);border:1px solid var(--line);">'+badge(st)+' <strong style="margin-right:6px;">'+bs[st]+'</strong></div>';}).join('');
    var latest=s.latest_orders||[];
    if(latest.length){
      var th='<th>ID</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>Status</th><th>Date</th><th>Action</th>';
      var tb=latest.map(function(r){return '<tr>'
        +'<td><code style="font-size:10px;">'+r.id.slice(0,10)+'...</code></td>'
        +'<td>'+fmtNum(r.fiat_amount)+' '+(r.fiat_currency||'')+'</td>'
        +'<td>'+fmtNum(r.crypto_amount,6)+' '+(r.crypto_currency||'')+'</td>'
        +'<td>'+(r.network||'—')+'</td>'
        +'<td>'+badge(r.status)+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
        +'<td><button class="btn btn-danger" data-oid="'+r.id+'" onclick="deleteOrder(this.dataset.oid)" style="font-size:11px;padding:3px 8px;">Delete</button></td>'
        +'</tr>';}).join('');
      document.getElementById('payTable').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
    }else{document.getElementById('payTable').innerHTML='<div class="empty-state"><div class="icon">💳</div>No orders found</div>';}
  }).catch(function(e){
    console.error(e);
    document.getElementById('paySum').innerHTML='<div class="empty-state" style="padding:20px;"><div class="icon">⚠</div>Load failed: '+(e.message||e)+'</div>';
    document.getElementById('payTable').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+(e.message||e)+'</div>';
  });
}
function deleteOrder(id){
  if(!confirm('Delete this order? This cannot be undone.'))return;
  api('/api/v1/admin/orders/'+id,{method:'DELETE'}).then(function(){showToast('Order deleted','ok');loadPayments();}).catch(function(e){showToast(e.message||String(e),'error');});
}
loadPayments();
</script>
"""

# ─── STRIPE ───────────────────────────────────────────────────────────────────

_STRIPE_BODY = """
<div class="page-body">
  <div class="panel">
    <div class="panel-head">
      <div>
        <h3>Stripe Payments</h3>
        <p style="margin:4px 0 0;color:var(--muted);font-size:12px;">Checkout and Payment Links inside the dashboard</p>
      </div>
      <button class="btn btn-ghost" onclick="loadStripe()" style="font-size:11px;padding:4px 10px;">Refresh</button>
    </div>
    <div id="stripeStatus" class="stat-grid" style="padding:14px;"></div>
    <div id="stripeConfigNotice" style="padding:0 14px 14px;"></div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <div class="panel-head"><h3>Stripe Balance</h3></div>
      <div id="stripeBalance" style="padding:14px;"><div class="empty-state"><div class="icon">💵</div>Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Stripe Activity</h3></div>
      <div id="stripeActivity" style="padding:14px;"><div class="empty-state"><div class="icon">📊</div>Loading...</div></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <div class="panel-head"><h3>Create Checkout Session</h3></div>
      <div style="padding:14px;display:grid;gap:10px;">
        <input id="stripeCheckoutAmount" placeholder="Amount" inputmode="decimal" value="100.00">
        <input id="stripeCheckoutCurrency" placeholder="Currency" value="USD" maxlength="3">
        <input id="stripeCheckoutEmail" placeholder="Customer email (optional)">
        <input id="stripeCheckoutDesc" placeholder="Description" value="ALSHUMOOKH payment">
        <button id="stripeCheckoutBtn" class="btn btn-primary" onclick="createStripeCheckout()">Create Checkout Link</button>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>Create Payment Link</h3></div>
      <div style="padding:14px;display:grid;gap:10px;">
        <input id="stripeLinkAmount" placeholder="Amount" inputmode="decimal" value="100.00">
        <input id="stripeLinkCurrency" placeholder="Currency" value="USD" maxlength="3">
        <input id="stripeLinkEmail" placeholder="Customer email (optional)">
        <input id="stripeLinkDesc" placeholder="Description" value="ALSHUMOOKH payment link">
        <button id="stripeLinkBtn" class="btn btn-primary" onclick="createStripePaymentLink()">Create Payment Link</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Create Stripe Invoice</h3></div>
    <div style="padding:14px;display:grid;gap:10px;">
      <input id="stripeInvoiceAmount" placeholder="Amount" inputmode="decimal" value="100.00">
      <input id="stripeInvoiceCurrency" placeholder="Currency" value="USD" maxlength="3">
      <input id="stripeInvoiceEmail" placeholder="Customer email *">
      <input id="stripeInvoiceDesc" placeholder="Description" value="ALSHUMOOKH invoice">
      <input id="stripeInvoiceDays" placeholder="Days until due" inputmode="numeric" value="7">
      <button id="stripeInvoiceBtn" class="btn btn-primary" onclick="createStripeInvoice()">Create Stripe Invoice</button>
    </div>
  </div>

  <div id="stripeResult"></div>

  <div class="panel">
    <div class="panel-head"><h3>Recent Stripe Orders</h3></div>
    <div id="stripeOrders"><div class="empty-state"><div class="icon">💵</div>Loading...</div></div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <div class="panel-head"><h3>Recent Payouts</h3></div>
      <div id="stripePayouts"><div class="empty-state"><div class="icon">🏦</div>Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>Recent Payments</h3></div>
      <div id="stripePayments"><div class="empty-state"><div class="icon">💳</div>Loading...</div></div>
    </div>
  </div>
</div>
<script>
var _stripeConfigured = false;

function stripeForm(prefix){
  return {
    amount: document.getElementById(prefix+'Amount').value,
    currency: document.getElementById(prefix+'Currency').value || 'USD',
    customer_email: document.getElementById(prefix+'Email').value || null,
    description: document.getElementById(prefix+'Desc').value || 'ALSHUMOOKH payment'
  };
}
function stripeInvoiceForm(){
  return {
    amount: document.getElementById('stripeInvoiceAmount').value,
    currency: document.getElementById('stripeInvoiceCurrency').value || 'USD',
    customer_email: document.getElementById('stripeInvoiceEmail').value,
    description: document.getElementById('stripeInvoiceDesc').value || 'ALSHUMOOKH invoice',
    days_until_due: Number(document.getElementById('stripeInvoiceDays').value || 7)
  };
}
function stripeAttr(v){
  return String(v || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}

function setStripeButtons(enabled){
  ['stripeCheckoutBtn','stripeLinkBtn','stripeInvoiceBtn'].forEach(function(id){
    var b=document.getElementById(id);
    if(!b) return;
    b.disabled=!enabled;
    b.style.opacity=enabled?'1':'.45';
    b.style.cursor=enabled?'pointer':'not-allowed';
  });
}

function stripeErrorBox(title, msg){
  document.getElementById('stripeResult').innerHTML =
    '<div class="panel" style="border-color:rgba(239,68,68,.45);">'
    +'<div class="panel-head"><h3 style="color:#f87171;">'+stripeAttr(title)+'</h3></div>'
    +'<div style="padding:14px;color:var(--muted);line-height:1.7;">'+stripeAttr(msg)+'</div>'
    +'</div>';
}

function stripeResultBox(title, url, orderId, invoiceUrl){
  var safeUrl = stripeAttr(url);
  var safeInvoice = stripeAttr(invoiceUrl || ('/api/v1/admin/orders/'+orderId+'/documents/invoice'));
  document.getElementById('stripeResult').innerHTML =
    '<div class="panel" style="border-color:rgba(16,185,129,.45);">'
    +'<div class="panel-head"><h3>'+title+'</h3></div>'
    +'<div style="padding:14px;display:grid;gap:10px;">'
    +'<div><span style="color:var(--muted);font-size:12px;">Order ID</span><br><code>'+orderId+'</code></div>'
    +'<input readonly value="'+safeUrl+'" onclick="this.select()">'
    +'<div style="display:flex;gap:8px;flex-wrap:wrap;">'
    +'<button class="btn btn-primary" data-url="'+safeUrl+'" data-target="_blank" onclick="window.open(this.dataset.url,this.dataset.target)">Open Stripe Page</button>'
    +'<button class="btn btn-ghost" data-url="'+safeUrl+'" onclick="copyText(this.dataset.url)">Copy Link</button>'
    +'<button class="btn btn-ghost" data-url="'+safeInvoice+'" data-target="_blank" onclick="window.open(this.dataset.url,this.dataset.target)">Open Invoice</button>'
    +'</div></div></div>';
}
function stripeMoney(obj){
  var amount = obj && typeof obj.amount !== 'undefined' ? obj.amount : 0;
  var cur = (obj && obj.currency ? obj.currency : '').toUpperCase();
  var zero = ['BIF','CLP','DJF','GNF','JPY','KMF','KRW','MGA','PYG','RWF','UGX','VND','VUV','XAF','XOF','XPF'].indexOf(cur)>=0;
  var n = Number(amount || 0) / (zero ? 1 : 100);
  return fmtNum(n) + ' ' + cur;
}
function renderStripeBalance(bal){
  var available=(bal.available||[]).map(stripeMoney).join('<br>')||'—';
  var pending=(bal.pending||[]).map(stripeMoney).join('<br>')||'—';
  document.getElementById('stripeBalance').innerHTML =
    '<div class="stat-grid">'
    +'<div class="stat-card"><div class="label">Available</div><div class="value" style="font-size:20px;">'+available+'</div></div>'
    +'<div class="stat-card"><div class="label">Pending</div><div class="value" style="font-size:20px;">'+pending+'</div></div>'
    +'</div>';
}
function renderMiniList(id, items, emptyText, formatter){
  if(!items || !items.length){
    document.getElementById(id).innerHTML='<div class="empty-state"><div class="icon">—</div>'+emptyText+'</div>';
    return;
  }
  document.getElementById(id).innerHTML='<div style="display:grid;gap:8px;padding:12px;">'+items.map(formatter).join('')+'</div>';
}
function loadStripeExtended(){
  api('/api/v1/admin/stripe/balance').then(renderStripeBalance).catch(function(e){
    document.getElementById('stripeBalance').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+stripeAttr(e.message||e)+'</div>';
  });
  Promise.all([
    api('/api/v1/admin/stripe/payment-intents?limit=8').catch(function(){return {data:[]};}),
    api('/api/v1/admin/stripe/charges?limit=8').catch(function(){return {data:[]};})
  ]).then(function(results){
    var intents=results[0].data||[];
    var charges=results[1].data||[];
    document.getElementById('stripeActivity').innerHTML =
      '<div class="stat-grid">'
      +'<div class="stat-card"><div class="label">Payment Intents</div><div class="value" style="font-size:20px;">'+intents.length+'</div></div>'
      +'<div class="stat-card"><div class="label">Charges</div><div class="value" style="font-size:20px;">'+charges.length+'</div></div>'
      +'</div>';
    renderMiniList('stripePayments', intents.concat(charges).slice(0,8), 'No Stripe payments yet', function(x){
      return '<div style="border:1px solid var(--line);border-radius:8px;padding:10px;">'
        +'<strong>'+stripeAttr(x.id)+'</strong><span style="float:left;color:var(--muted);">'+stripeAttr(x.status||'')+'</span><br>'
        +'<span style="color:var(--muted);font-size:12px;">'+stripeMoney(x)+'</span></div>';
    });
  });
  api('/api/v1/admin/stripe/payouts?limit=8').then(function(p){
    renderMiniList('stripePayouts', p.data||[], 'No Stripe payouts yet', function(x){
      return '<div style="border:1px solid var(--line);border-radius:8px;padding:10px;">'
        +'<strong>'+stripeAttr(x.id)+'</strong><span style="float:left;color:var(--muted);">'+stripeAttr(x.status||'')+'</span><br>'
        +'<span style="color:var(--muted);font-size:12px;">'+stripeMoney(x)+'</span></div>';
    });
  }).catch(function(e){
    document.getElementById('stripePayouts').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+stripeAttr(e.message||e)+'</div>';
  });
}
function loadStripe(){
  setStripeButtons(false);
  api('/api/v1/admin/stripe/status').then(function(st) {
    _stripeConfigured = !!st.configured;
    setStripeButtons(_stripeConfigured);
    document.getElementById('stripeStatus').innerHTML =
      '<div class="stat-card"><div class="label">Stripe</div><div class="value" style="font-size:20px;">'+(st.configured?'Configured':'Missing Key')+'</div></div>'
      +'<div class="stat-card"><div class="label">Mode</div><div class="value" style="font-size:20px;">'+(st.mode||'unknown')+'</div></div>'
      +'<div class="stat-card"><div class="label">Webhook</div><div class="value" style="font-size:20px;">'+(st.webhook_configured?'Ready':'Not Set')+'</div></div>'
      +'<div class="stat-card"><div class="label">Webhook URL</div><div style="font-size:11px;word-break:break-all;">'+(st.webhook_url||'')+'</div></div>';
    var notice = '';
    if(!st.configured){
      notice += '<div class="empty-state" style="border-color:rgba(239,68,68,.35);color:#fecaca;text-align:right;">'
        +'<strong>Stripe is not connected yet.</strong><br>'
        +'Add STRIPE_SECRET_KEY in Render Environment Variables, then restart the service. Without this key, the system cannot create Payment Links or Checkout Sessions.'
        +'</div>';
    } else if(!st.webhook_configured) {
      notice += '<div class="empty-state" style="border-color:rgba(245,158,11,.35);color:#fde68a;text-align:right;">'
        +'<strong>Webhook Secret is not configured.</strong><br>'
        +'Link creation works, but automatic payment confirmation requires STRIPE_WEBHOOK_SECRET from Stripe.'
        +'</div>';
    }
    if((st.webhook_url||'').indexOf('alshumookh.finance') >= 0){
      notice += '<div class="empty-state" style="border-color:rgba(245,158,11,.35);color:#fde68a;text-align:right;margin-top:8px;">'
        +'Webhook URL is showing the old domain. Set PUBLIC_BASE_URL=https://api.alshumookh-pay.com in Render.'
        +'</div>';
    }
    document.getElementById('stripeConfigNotice').innerHTML = notice;
    if(_stripeConfigured){ loadStripeExtended(); }
    return api('/api/v1/admin/stripe/orders?limit=30');
  }).then(function(rows) {
    var orders = rows.orders || [];
    if(!orders.length){
      document.getElementById('stripeOrders').innerHTML='<div class="empty-state"><div class="icon">💵</div>No Stripe orders yet</div>';
      return;
    }
    var th='<th>Reference</th><th>Amount</th><th>Status</th><th>Email</th><th>Stripe ID</th><th>Link</th><th>Invoice</th><th>Date</th>';
    var tb=orders.map(function(o){
      var link=o.checkout_url||'';
      var safeLink=stripeAttr(link);
      return '<tr>'
        +'<td><code style="font-size:10px;">'+(o.payment_reference||o.id)+'</code></td>'
        +'<td>'+fmtNum(o.fiat_amount)+' '+(o.fiat_currency||'')+'</td>'
        +'<td>'+badge(o.status)+'</td>'
        +'<td style="font-size:11px;">'+(o.payer_email||'—')+'</td>'
        +'<td><code style="font-size:10px;">'+(o.provider_order_id||'—')+'</code></td>'
        +'<td>'+(link?'<button class="btn btn-ghost" data-url="'+safeLink+'" data-target="_blank" onclick="window.open(this.dataset.url,this.dataset.target)" style="font-size:11px;padding:4px 8px;">Open</button>':'—')+'</td>'
        +'<td><button class="btn btn-ghost" data-url="'+stripeAttr(o.invoice_url || ('/api/v1/admin/orders/'+o.id+'/documents/invoice'))+'" data-target="_blank" onclick="window.open(this.dataset.url,this.dataset.target)" style="font-size:11px;padding:4px 8px;">Invoice</button></td>'
        +'<td style="font-size:11px;">'+fmtDate(o.created_at)+'</td>'
        +'</tr>';
    }).join('');
    document.getElementById('stripeOrders').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){
    console.error(e);
    document.getElementById('stripeStatus').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+(e.message||e)+'</div>';
    document.getElementById('stripeConfigNotice').innerHTML='';
    setStripeButtons(false);
  });
}
function createStripeCheckout(){
  if(!_stripeConfigured){
    stripeErrorBox('Stripe Missing Key', 'Cannot create a Checkout Link before adding STRIPE_SECRET_KEY in Render and restarting the service.');
    return;
  }
  api('/api/v1/admin/stripe/checkout-sessions',{method:'POST',body:JSON.stringify(stripeForm('stripeCheckout'))}).then(function(r){
    stripeResultBox('Checkout Session Created', r.order.checkout_url, r.order.id, r.invoice_url || r.order.invoice_url);
    loadStripe();
  }).catch(function(e){stripeErrorBox('Checkout creation failed', e.message||String(e));showToast(e.message||String(e),'error');});
}
function createStripePaymentLink(){
  if(!_stripeConfigured){
    stripeErrorBox('Stripe Missing Key', 'Cannot create a Payment Link before adding STRIPE_SECRET_KEY in Render and restarting the service.');
    return;
  }
  api('/api/v1/admin/stripe/payment-links',{method:'POST',body:JSON.stringify(stripeForm('stripeLink'))}).then(function(r){
    stripeResultBox('Payment Link Created', r.order.checkout_url, r.order.id, r.invoice_url || r.order.invoice_url);
    loadStripe();
  }).catch(function(e){stripeErrorBox('Payment Link creation failed', e.message||String(e));showToast(e.message||String(e),'error');});
}
function createStripeInvoice(){
  if(!_stripeConfigured){
    stripeErrorBox('Stripe Missing Key', 'Cannot create a Stripe Invoice before adding STRIPE_SECRET_KEY in Render and restarting the service.');
    return;
  }
  var body = stripeInvoiceForm();
  if(!body.customer_email){showToast('Customer email is required for invoices','error');return;}
  api('/api/v1/admin/stripe/invoices',{method:'POST',body:JSON.stringify(body)}).then(function(r){
    stripeResultBox('Stripe Invoice Created', r.hosted_invoice_url || r.invoice_pdf || r.order.checkout_url, r.order.id, r.invoice_url || r.order.invoice_url);
    loadStripe();
  }).catch(function(e){stripeErrorBox('Stripe invoice creation failed', e.message||String(e));showToast(e.message||String(e),'error');});
}
loadStripe();
</script>
"""

# ─── ALCHEMY ──────────────────────────────────────────────────────────────────

_ALCHEMY_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <input id="alchQ" placeholder="Search..." style="min-width:200px;" oninput="filterAlch()">
    <button class="btn btn-ghost" onclick="loadAlch()">Refresh</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>Alchemy Blockchain Events</h3><span id="alchCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="alchBody"><div class="empty-state"><div class="icon">⛓</div>Loading...</div></div>
  </div>
</div>
<script>
var _alchRows=[];
function loadAlch(){
  api('/api/v1/admin/alchemy-events?limit=200').then(function(data){
    _alchRows=Array.isArray(data)?data:[];
    document.getElementById('alchCnt').textContent=_alchRows.length+' events';
    renderAlch(_alchRows);
  }).catch(function(e){document.getElementById('alchBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
function filterAlch(){
  var q=document.getElementById('alchQ').value.toLowerCase();
  renderAlch(q?_alchRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_alchRows);
}
function renderAlch(rows){
  if(!rows.length){document.getElementById('alchBody').innerHTML='<div class="empty-state"><div class="icon">⛓</div>No Alchemy events found</div>';return;}
  var th='<th>Event Type</th><th>Order ID</th><th>TX ID</th><th>Status</th><th>IP</th><th>Details</th><th>Date</th>';
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
    <button class="btn btn-ghost" onclick="loadClients()">Refresh</button>
    <button class="btn btn-primary" onclick="toggleAddCl()">+ Add Counterparty</button>
  </div>

  <div id="addClForm" style="display:none;" class="panel">
    <div class="panel-head"><h3>Add New Counterparty</h3></div>
    <div style="padding:16px;">
      <div class="form-grid">
        <div class="form-field"><label>Name *</label><input id="clName" placeholder="Counterparty name"></div>
        <div class="form-field"><label>Allowed IPs (comma-separated)</label><input id="clIps" placeholder="1.2.3.4,5.6.7.8 (optional)"></div>
        <div class="form-field" style="grid-column:span 2;">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
            <input type="checkbox" id="clHmac" style="width:auto;"> Require HMAC Signature
          </label>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-success" onclick="addClient()">Create</button>
        <button class="btn btn-ghost" onclick="toggleAddCl()">Cancel</button>
      </div>
    </div>
  </div>

  <div id="clCreated" style="display:none;" class="panel">
    <div class="panel-head"><h3>Client Created - Save These Credentials Now</h3></div>
    <div id="clCreatedBody" style="padding:16px;font-size:12px;"></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Counterparties List</h3><span id="clCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="clBody"><div class="empty-state"><div class="icon">🔑</div>Loading...</div></div>
  </div>

  <div id="clientDetails" class="panel" style="display:none;">
    <div class="panel-head">
      <h3 id="clientDetailsTitle">Client Details</h3>
      <button class="btn btn-ghost" onclick="closeClientDetails()">Close</button>
    </div>
    <div id="clientDetailsBody" style="padding:16px;"></div>
  </div>
</div>
<script>
function toggleAddCl(){
  var el=document.getElementById('addClForm');
  el.style.display=el.style.display==='none'?'block':'none';
}
function addClient(){
  var ips=document.getElementById('clIps').value.trim();
  var body={name:document.getElementById('clName').value.trim(),allowed_ips:ips?ips.split(',').map(function(s){return s.trim();}).filter(Boolean):null,hmac_required:document.getElementById('clHmac').checked};
  if(!body.name){showToast('Name is required','error');return;}
  api('/api/v1/admin/clients',{method:'POST',body:JSON.stringify(body)}).then(function(r){
    var fields=[['Client ID',r.id],['API Key',r.api_key],['HMAC Secret',r.hmac_secret||'—'],['OAuth Client ID',r.oauth_client_id||'—'],['OAuth Client Secret',r.oauth_client_secret||'—']];
    document.getElementById('clCreatedBody').innerHTML=
      '<div style="padding:10px;background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);border-radius:8px;margin-bottom:12px;color:#10b981;font-weight:700;">Save these credentials now. They will not be shown again.</div>'
      +fields.map(function(f){return '<div style="display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line);"><span style="color:var(--muted);min-width:160px;">'+f[0]+'</span><code style="word-break:break-all;flex:1;" id="fv_'+f[0].replace(/\\s/g,'_')+'">'+f[1]+'</code><button class="btn btn-ghost" data-fid="fv_'+f[0].replace(/\\s/g,'_')+'" onclick="copyText(document.getElementById(this.dataset.fid).textContent)" style="font-size:10px;padding:2px 8px;">Copy</button></div>';}).join('');
    document.getElementById('clCreated').style.display='block';
    document.getElementById('clCreated').scrollIntoView({behavior:'smooth'});
    toggleAddCl();loadClients();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}
function toggleClient(id,active){
  active = active === true || active === 'true';
  api('/api/v1/admin/clients/'+id,{method:'PATCH',body:JSON.stringify({is_active:active})}).then(function(){showToast(active?'Activated':'Deactivated','ok');loadClients();}).catch(function(e){showToast('Error: '+e.message,'error');});
}
function closeClientDetails(){
  document.getElementById('clientDetails').style.display='none';
}
function openClientDetails(id){
  var panel=document.getElementById('clientDetails');
  var body=document.getElementById('clientDetailsBody');
  panel.style.display='block';
  body.innerHTML='<div class="empty-state"><div class="icon">🔎</div>Loading client details...</div>';
  api('/api/v1/admin/clients/'+id+'/details').then(function(data){
    var c=data.client||{};
    document.getElementById('clientDetailsTitle').textContent='Client Details - '+(c.name||c.id||id);
    var accounts=data.accounts||[];
    var orders=data.orders||[];
    var payloads=data.payloads||[];
    var logs=data.audit_logs||[];
    var accountHtml=accounts.length?accounts.map(function(a){
      return '<tr><td><code>'+esc(a.id||'')+'</code></td><td>'+esc(a.identifier||'')+'</td><td>'+badge(a.is_active?'ACTIVE':'DISABLED')+'</td><td>'+fmtDate(a.created_at)+'</td><td><a class="btn btn-ghost" href="'+esc(a.portal_url||'/client')+'" target="_blank" style="font-size:11px;padding:3px 8px;text-decoration:none;">Open Portal</a></td></tr>';
    }).join(''):'<tr><td colspan="5">No client login accounts found.</td></tr>';
    var orderHtml=orders.length?orders.map(function(o){
      return '<tr><td><code title="'+esc(o.id||'')+'">'+esc((o.id||'').slice(0,10))+'...</code></td><td>'+esc(o.external_id||'—')+'</td><td>'+esc(o.provider||'')+'</td><td>'+badge(o.status||'')+'</td><td>'+fmtNum(o.fiat_amount)+' '+esc(o.fiat_currency||'')+'</td><td>'+fmtNum(o.crypto_amount,6)+' '+esc(o.crypto_currency||'')+'</td><td><a class="btn btn-ghost" target="_blank" href="/api/v1/admin/orders/'+esc(o.id||'')+'/documents/invoice" style="font-size:11px;padding:3px 8px;text-decoration:none;">Invoice</a></td></tr>';
    }).join(''):'<tr><td colspan="7">No orders found.</td></tr>';
    var payloadHtml=payloads.length?payloads.map(function(p){
      return '<tr><td><code>'+esc((p.id||'').slice(0,10))+'...</code></td><td>'+esc(p.transaction_reference||'—')+'</td><td>'+fmtNum(p.amount)+' '+esc(p.asset||'')+'</td><td>'+esc(p.network||'')+'</td><td>'+badge(p.verification_status||p.parsing_status||'')+'</td><td>'+esc(p.tx_hash||'—')+'</td><td>'+fmtDate(p.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan="7">No settlement payloads found.</td></tr>';
    var logHtml=logs.length?logs.map(function(l){
      return '<tr><td>'+esc(l.event_type||'')+'</td><td>'+esc(l.method||'')+'</td><td>'+esc(l.endpoint||'')+'</td><td>'+esc(String(l.status_code||'—'))+'</td><td>'+esc(l.ip||'')+'</td><td>'+esc(l.error_message||'—')+'</td><td>'+fmtDate(l.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan="7">No audit logs found.</td></tr>';
    body.innerHTML=
      '<div class="stat-grid" style="margin-bottom:16px;">'
      +'<div class="stat-card"><div class="label">Client ID</div><div class="value" style="font-size:13px;word-break:break-all;">'+esc(c.id||'')+'</div></div>'
      +'<div class="stat-card"><div class="label">Status</div><div class="value">'+(c.is_active?'Active':'Disabled')+'</div></div>'
      +'<div class="stat-card"><div class="label">Allowed IPs</div><div class="value" style="font-size:13px;">'+esc((c.allowed_ips||[]).join(', ')||'Any IP')+'</div></div>'
      +'<div class="stat-card"><div class="label">Created</div><div class="value" style="font-size:13px;">'+fmtDate(c.created_at)+'</div></div>'
      +'</div>'
      +'<h4>Login Accounts</h4><div class="table-wrap"><table><thead><tr><th>ID</th><th>Identifier</th><th>Status</th><th>Created</th><th>Action</th></tr></thead><tbody>'+accountHtml+'</tbody></table></div>'
      +'<h4 style="margin-top:18px;">Client Transactions</h4><div class="table-wrap"><table><thead><tr><th>ID</th><th>Reference</th><th>Provider</th><th>Status</th><th>Fiat</th><th>Crypto</th><th>Invoice</th></tr></thead><tbody>'+orderHtml+'</tbody></table></div>'
      +'<h4 style="margin-top:18px;">Settlement Payloads</h4><div class="table-wrap"><table><thead><tr><th>ID</th><th>Reference</th><th>Amount</th><th>Network</th><th>Status</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>'+payloadHtml+'</tbody></table></div>'
      +'<h4 style="margin-top:18px;">Audit Logs</h4><div class="table-wrap"><table><thead><tr><th>Event</th><th>Method</th><th>Endpoint</th><th>Status</th><th>IP</th><th>Error</th><th>Date</th></tr></thead><tbody>'+logHtml+'</tbody></table></div>';
    panel.scrollIntoView({behavior:'smooth'});
  }).catch(function(e){body.innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}
function loadClients(){
  api('/api/v1/admin/clients').then(function(rows) {
    if(!Array.isArray(rows))rows=[];
    document.getElementById('clCnt').textContent=rows.length+' client';
    if(!rows.length){document.getElementById('clBody').innerHTML='<div class="empty-state"><div class="icon">🔑</div>No clients found</div>';return;}
    var th='<th>ID</th><th>Name</th><th>Active</th><th>HMAC</th><th>OAuth</th><th>mTLS</th><th>JWS</th><th>IPs</th><th>Created</th><th>Action</th>';
    var tb=rows.map(function(r){return '<tr>'
      +'<td><code style="font-size:10px;" title="'+r.id+'">'+r.id.slice(0,12)+'...</code></td>'
      +'<td><strong>'+r.name+'</strong></td>'
      +'<td>'+(r.is_active?'<span style="color:#10b981;font-weight:700;">Active</span>':'<span style="color:#ef4444;">Disabled</span>')+'</td>'
      +'<td>'+(r.hmac_required?'<span style="color:#10b981;">Yes</span>':'—')+'</td>'
      +'<td>'+(r.oauth_required?'<span style="color:#10b981;">Yes</span>':'—')+'</td>'
      +'<td>'+(r.mtls_required?'<span style="color:#10b981;">Yes</span>':'—')+'</td>'
      +'<td>'+(r.jws_required?'<span style="color:#10b981;">Yes</span>':'—')+'</td>'
      +'<td>'+((r.allowed_ips||[]).length?r.allowed_ips.join(', '):'Any IP')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><div style="display:flex;gap:6px;flex-wrap:wrap;"><button class="btn btn-ghost" data-cid="'+r.id+'" onclick="openClientDetails(this.dataset.cid)" style="font-size:11px;padding:3px 8px;">View</button><button class="btn '+(r.is_active?'btn-danger':'btn-success')+'" data-cid="'+r.id+'" data-active="'+(r.is_active?'false':'true')+'" onclick="toggleClient(this.dataset.cid,this.dataset.active)" style="font-size:11px;padding:3px 8px;">'+(r.is_active?'Disable':'Enable')+'</button></div></td>'
      +'</tr>';}).join('');
    document.getElementById('clBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('clBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
loadClients();
</script>
"""

# ─── SECURITY ─────────────────────────────────────────────────────────────────

_SECURITY_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <input id="secQ" placeholder="Search..." style="min-width:200px;" oninput="filterSec()">
    <button class="btn btn-ghost" onclick="loadSec()">Refresh</button>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Security Posture — Counterparties</h3></div>
    <div id="secPosture" style="padding:14px;"></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h3>Security Events</h3><span id="secCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="secBody"><div class="empty-state"><div class="icon">🛡</div>Loading...</div></div>
  </div>
</div>
<script>
var _secRows=[];
function loadSec(){
  api('/api/v1/admin/clients/security-posture').then(function(p) {
    var rows=Array.isArray(p)?p:(p.clients||[]);
    if(rows.length){
      var th='<th>Client</th><th>Score</th><th>HMAC</th><th>OAuth</th><th>mTLS</th><th>JWS</th><th>IP List</th><th>Posture</th>';
      var tb=rows.map(function(r){return '<tr>'
        +'<td>'+r.name+'</td>'
        +'<td><strong style="color:'+((r.security_score||r.score||0)>=4?'#10b981':(r.security_score||r.score||0)>=2?'#f59e0b':'#ef4444')+';"> '+(r.security_score||r.score||0)+'/6</strong></td>'
        +'<td>'+(r.hmac_required?'Yes':'—')+'</td>'
        +'<td>'+(r.oauth_required?'Yes':'—')+'</td>'
        +'<td>'+(r.mtls_required?'Yes':'—')+'</td>'
        +'<td>'+(r.jws_required?'Yes':'—')+'</td>'
        +'<td>'+((r.allowed_ips||[]).length?'Yes':'—')+'</td>'
        +'<td>'+badge(r.posture||'UNKNOWN')+'</td>'
        +'</tr>';}).join('');
      document.getElementById('secPosture').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
    }else{document.getElementById('secPosture').innerHTML='<p style="color:var(--muted);text-align:center;padding:16px;">No data available</p>';}
  }).catch(function(e){document.getElementById('secPosture').innerHTML='<p style="color:var(--muted);">'+e.message+'</p>';});
  api('/api/v1/admin/security-events').then(function(_secData) {
    _secRows=Array.isArray(_secData)?_secData:(_secData.recent_events||[]);
    document.getElementById('secCnt').textContent=_secRows.length+' events';
    renderSec(_secRows);
  }).catch(function(e){document.getElementById('secBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
function filterSec(){
  var q=document.getElementById('secQ').value.toLowerCase();
  renderSec(q?_secRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_secRows);
}
function renderSec(rows){
  if(!rows.length){document.getElementById('secBody').innerHTML='<div class="empty-state"><div class="icon">🛡</div>No security events found</div>';return;}
  var th='<th>Event</th><th>IP</th><th>Path</th><th>Status</th><th>User Agent</th><th>Date</th>';
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
    <button class="btn btn-ghost" onclick="loadDocs()">Refresh</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>Order Documents</h3><span id="docsCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="docsBody"><div class="empty-state"><div class="icon">📄</div>Loading...</div></div>
  </div>
</div>
<script>
function loadDocs(){
  api('/api/v1/admin/documents?limit=100').then(function(rows) {
    if(!Array.isArray(rows))rows=[];
    document.getElementById('docsCnt').textContent=rows.length+' documents';
    if(!rows.length){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">📄</div>No documents found</div>';return;}
    var th='<th>Order ID</th><th>External ID</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>Status</th><th>Date</th><th>Documents</th>';
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
        +'<a href="/api/v1/admin/orders/'+r.id+'/documents/statement" target="_blank" style="padding:2px 8px;border-radius:5px;background:rgba(199,154,69,.15);color:var(--gold);font-size:11px;text-decoration:none;border:1px solid rgba(199,154,69,.3);">Statement</a>'
        +'<a href="/api/v1/admin/orders/'+r.id+'/documents/receive-receipt" target="_blank" style="padding:2px 8px;border-radius:5px;background:rgba(16,185,129,.1);color:#10b981;font-size:11px;text-decoration:none;border:1px solid rgba(16,185,129,.2);">Receipt</a>'
        +'</div></td>'
      +'</tr>';}).join('');
    document.getElementById('docsBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
loadDocs();
</script>
"""

# ─── REPORTS ─────────────────────────────────────────────────────────────────

_REPORTS_BODY = """
<style>
.rpt-hero{background:linear-gradient(135deg,#0d2348 0%,#1a3a6b 100%);padding:26px 32px 22px;border-radius:8px 8px 0 0;position:relative;overflow:hidden;}
.rpt-hero::before{content:\'\';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#8b6914,#c9a227,#f0c040,#c9a227,#8b6914);}
.rpt-hero-title{font-size:21px;font-weight:700;color:#fff;letter-spacing:.4px;}
.rpt-hero-sub{font-size:11px;color:#8ca8d0;margin-top:5px;}
.rpt-hero-badge{position:absolute;right:28px;top:50%;transform:translateY(-50%);width:62px;height:62px;border:2px solid rgba(192,155,45,.65);border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;color:rgba(230,188,60,.8);font-size:8px;font-weight:700;line-height:1.3;letter-spacing:.3px;}
.action-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:20px;}
@media(max-width:860px){.action-grid{grid-template-columns:1fr;}}
.action-card{background:var(--surface2);border:1px solid var(--line);border-radius:8px;padding:20px;transition:border-color .2s,box-shadow .2s;}
.action-card:hover{border-color:var(--brand);box-shadow:0 4px 18px rgba(100,140,220,.12);}
.action-card-lbl{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px;}
.action-card-title{font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;}
.action-card-desc{font-size:11px;color:var(--muted);line-height:1.55;margin-bottom:16px;}
.rpt-stats{display:flex;gap:0;background:var(--surface2);border-top:1px solid var(--line);border-bottom:1px solid var(--line);}
.rpt-stat{flex:1;padding:14px 16px;text-align:center;border-right:1px solid var(--line);}
.rpt-stat:last-child{border-right:none;}
.rpt-stat-num{font-size:22px;font-weight:700;color:var(--brand);}
.rpt-stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px;}
.rtab-bar{display:flex;padding:0 20px;background:var(--surface);border-bottom:2px solid var(--line);}
.rtab-btn{padding:13px 22px;font-size:12px;font-weight:600;color:var(--muted);background:none;border:none;border-bottom:3px solid transparent;margin-bottom:-2px;cursor:pointer;transition:color .15s,border-color .15s;letter-spacing:.3px;}
.rtab-btn.active{color:var(--brand);border-bottom-color:var(--brand);}
.rtab-btn:hover{color:var(--text);}
.tab-toolbar{display:flex;align-items:center;gap:8px;padding:12px 20px;background:var(--surface2);border-bottom:1px solid var(--line);}
.tab-count-badge{font-size:11px;color:var(--muted);background:var(--surface);border:1px solid var(--line);padding:3px 10px;border-radius:12px;font-weight:600;}
.rpt-table{width:100%;border-collapse:collapse;font-size:12px;}
.rpt-table th{background:#1a3a6b;color:#fff;padding:9px 12px;text-align:left;font-size:11px;font-weight:600;letter-spacing:.3px;white-space:nowrap;}
.rpt-table td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:middle;}
.rpt-table tr:hover td{background:var(--surface2);}
.rpt-table tr:last-child td{border-bottom:none;}
.mono-id{font-family:monospace;font-size:10px;background:var(--surface2);border:1px solid var(--line);padding:2px 6px;border-radius:3px;cursor:help;color:var(--muted);}
.amt-eur{color:#fbbf24;font-weight:700;}
.amt-sig{color:#a78bfa;font-weight:700;}
.amt-usdt{color:#34d399;font-weight:700;}
.amt-fiat{color:var(--text);font-weight:600;}
</style>

<div class="page-body">

  <!-- Hero Header -->
  <div class="panel" style="padding:0;overflow:hidden;">
    <div class="rpt-hero">
      <div class="rpt-hero-title">&#128202; Financial Reports &amp; Statements</div>
      <div class="rpt-hero-sub">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; Certified Transaction Reports</div>
      <div class="rpt-hero-badge">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div>
    </div>

    <!-- Stats Bar -->
    <div class="rpt-stats">
      <div class="rpt-stat"><div class="rpt-stat-num" id="statOrders">&mdash;</div><div class="rpt-stat-lbl">Payment Orders</div></div>
      <div class="rpt-stat"><div class="rpt-stat-num" id="statM1">&mdash;</div><div class="rpt-stat-lbl">M1 Jobs</div></div>
      <div class="rpt-stat"><div class="rpt-stat-num" id="statPayloads">&mdash;</div><div class="rpt-stat-lbl">Payloads</div></div>
      <div class="rpt-stat"><div class="rpt-stat-num" id="statTransfers">&mdash;</div><div class="rpt-stat-lbl">Transfers</div></div>
    </div>

    <!-- Action Cards -->
    <div class="action-grid">
      <div class="action-card">
        <div class="action-card-lbl">All Transactions</div>
        <div class="action-card-title">&#128424; Full Report</div>
        <div class="action-card-desc">Comprehensive report of all Payment Orders including status, amount, provider, network, wallet address and TX hash.</div>
        <button class="btn btn-primary" style="width:100%;" onclick="window.open('/api/v1/admin/reports/transactions','_blank')">Print Full Report</button>
      </div>
      <div class="action-card">
        <div class="action-card-lbl">Single Transaction</div>
        <div class="action-card-title">&#128196; Bank Statement</div>
        <div class="action-card-desc">Enter a Payment Order ID to generate an official bank statement, detailed report, or certified invoice.</div>
        <input id="reportOrderId" placeholder="Order / Transaction ID" style="width:100%;margin-bottom:8px;box-sizing:border-box;">
        <div style="display:flex;gap:6px;">
          <button class="btn btn-ghost" style="flex:1;font-size:11px;" onclick="openSingleStatement()">Statement</button>
          <button class="btn btn-ghost" style="flex:1;font-size:11px;" onclick="openSingleReport()">Report</button>
          <button class="btn btn-ghost" style="flex:1;font-size:11px;" onclick="openSingleInvoice()">Invoice</button>
        </div>
      </div>
      <div class="action-card">
        <div class="action-card-lbl">Complete Audit</div>
        <div class="action-card-title">&#128193; Print All Records</div>
        <div class="action-card-desc">Printable A4 document combining all orders, M1 jobs, settlement payloads, and outbound transfers.</div>
        <button class="btn btn-success" style="width:100%;" onclick="printAllTransactions()">Print All Records</button>
      </div>
    </div>
  </div>

  <!-- Tabs Panel -->
  <div class="panel" style="padding:0;overflow:hidden;">
    <div class="rtab-bar">
      <button id="rtab_orders" class="rtab-btn active" onclick="switchRTab('orders')">Payment Orders</button>
      <button id="rtab_m1" class="rtab-btn" onclick="switchRTab('m1')">M1 Tokenization</button>
      <button id="rtab_payloads" class="rtab-btn" onclick="switchRTab('payloads')">Settlement Payloads</button>
      <button id="rtab_transfers" class="rtab-btn" onclick="switchRTab('transfers')">Outbound Transfers</button>
    </div>

    <!-- Orders Tab -->
    <div id="rpane_orders">
      <div class="tab-toolbar">
        <span class="tab-count-badge" id="rOrderCount">Loading&hellip;</span>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button class="btn btn-ghost" onclick="loadReportOrders()" style="font-size:11px;">&#8635; Refresh</button>
          <button class="btn btn-primary" onclick="printTabData('orders')" style="font-size:11px;">&#128424; Print Tab</button>
        </div>
      </div>
      <div id="reportOrders" style="padding:16px;"><div class="empty-state"><div class="icon">&#128202;</div>Loading orders&hellip;</div></div>
    </div>

    <!-- M1 Tab -->
    <div id="rpane_m1" style="display:none;">
      <div class="tab-toolbar">
        <span class="tab-count-badge" id="rM1Count">Loading&hellip;</span>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button class="btn btn-ghost" onclick="loadReportM1()" style="font-size:11px;">&#8635; Refresh</button>
          <button class="btn btn-primary" onclick="printTabData('m1')" style="font-size:11px;">&#128424; Print Tab</button>
        </div>
      </div>
      <div id="reportM1" style="padding:16px;"><div class="empty-state"><div class="icon">&#128260;</div>Loading M1 jobs&hellip;</div></div>
    </div>

    <!-- Payloads Tab -->
    <div id="rpane_payloads" style="display:none;">
      <div class="tab-toolbar">
        <span class="tab-count-badge" id="rPayloadCount">Loading&hellip;</span>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button class="btn btn-ghost" onclick="loadReportPayloads()" style="font-size:11px;">&#8635; Refresh</button>
          <button class="btn btn-primary" onclick="printTabData('payloads')" style="font-size:11px;">&#128424; Print Tab</button>
        </div>
      </div>
      <div id="reportPayloads" style="padding:16px;"><div class="empty-state"><div class="icon">&#128232;</div>Loading payloads&hellip;</div></div>
    </div>

    <!-- Transfers Tab -->
    <div id="rpane_transfers" style="display:none;">
      <div class="tab-toolbar">
        <span class="tab-count-badge" id="rXferCount">Loading&hellip;</span>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button class="btn btn-ghost" onclick="loadReportTransfers()" style="font-size:11px;">&#8635; Refresh</button>
          <button class="btn btn-primary" onclick="printTabData('transfers')" style="font-size:11px;">&#128424; Print Tab</button>
        </div>
      </div>
      <div id="reportTransfers" style="padding:16px;"><div class="empty-state"><div class="icon">&#128228;</div>Loading transfers&hellip;</div></div>
    </div>
  </div>
</div>

<script>
var _rData={orders:[],m1:[],payloads:[],transfers:[]};
var _rTab='orders';

function switchRTab(tab){
  ['orders','m1','payloads','transfers'].forEach(function(t){
    var p=document.getElementById('rpane_'+t);
    var b=document.getElementById('rtab_'+t);
    if(p) p.style.display=t===tab?'block':'none';
    if(b) b.classList.toggle('active',t===tab);
  });
  _rTab=tab;
  if(tab==='orders'&&!_rData.orders.length) loadReportOrders();
  if(tab==='m1'&&!_rData.m1.length) loadReportM1();
  if(tab==='payloads'&&!_rData.payloads.length) loadReportPayloads();
  if(tab==='transfers'&&!_rData.transfers.length) loadReportTransfers();
}
function openSingleStatement(){var id=document.getElementById('reportOrderId').value.trim();if(!id){showToast('Enter a transaction ID','error');return;}window.open('/api/v1/admin/orders/'+encodeURIComponent(id)+'/documents/statement','_blank');}
function openSingleReport(){var id=document.getElementById('reportOrderId').value.trim();if(!id){showToast('Enter a transaction ID','error');return;}window.open('/api/v1/admin/reports/transactions?order_id='+encodeURIComponent(id),'_blank');}
function openSingleInvoice(){var id=document.getElementById('reportOrderId').value.trim();if(!id){showToast('Enter a transaction ID','error');return;}window.open('/api/v1/admin/orders/'+encodeURIComponent(id)+'/documents/invoice','_blank');}

var _pCSS='body{font-family:"Helvetica Neue",Arial,sans-serif;font-size:10.5px;color:#0d1b2a;margin:0;padding:22px 28px;background:#fff;}'
  +'.gbar{height:5px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400);margin-bottom:0;}'
  +'.cband{background:#1a3a6b;color:#fff;padding:7px 20px;font-size:8px;font-weight:700;letter-spacing:.5px;display:flex;justify-content:space-between;}'
  +'.dhead{display:flex;justify-content:space-between;align-items:center;padding:14px 0 10px;border-bottom:2px solid #1a3a6b;margin-bottom:16px;}'
  +'.dco{font-size:14px;font-weight:800;color:#1a3a6b;}.dsub{font-size:9.5px;color:#5a6a80;margin-top:3px;}'
  +'.dmeta{font-size:9px;color:#888;text-align:right;line-height:1.6;}'
  +'.dseal{width:56px;height:56px;border:2px solid #b8860b;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7.5px;font-weight:700;color:#8b6914;line-height:1.3;margin-left:12px;}'
  +'h2{font-size:13px;color:#1a3a6b;border-bottom:1.5px solid #c5d3ee;padding-bottom:5px;margin:16px 0 9px;letter-spacing:.2px;}'
  +'.sgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px;}'
  +'.scard{border:1px solid #c5d3ee;padding:9px 12px;border-radius:5px;text-align:center;background:#f7f9fc;}'
  +'.snum{font-size:18px;font-weight:800;color:#1a3a6b;}.slbl{font-size:9px;color:#667;text-transform:uppercase;letter-spacing:.4px;}'
  +'table{width:100%;border-collapse:collapse;font-size:9.5px;margin-bottom:16px;}'
  +'thead th{background:#1a3a6b;color:#fff;padding:6px 9px;text-align:left;font-size:9px;letter-spacing:.3px;white-space:nowrap;}'
  +'tbody td{padding:5px 9px;border-bottom:1px solid #e5eaf3;}'
  +'tbody tr:nth-child(even) td{background:#f7f9fc;}'
  +'.b{display:inline-block;padding:2px 7px;border-radius:10px;font-size:8.5px;font-weight:700;text-transform:uppercase;}'
  +'.bc{background:#d1fae5;color:#065f46;}.bp{background:#fef3c7;color:#92400e;}.bf{background:#fee2e2;color:#991b1b;}.bd{background:#e5e7eb;color:#374151;}'
  +'.foot{margin-top:20px;padding-top:8px;border-top:1px solid #d0d9ea;display:flex;justify-content:space-between;align-items:flex-end;}'
  +'.ftxt{font-size:8px;color:#9aa;line-height:1.6;max-width:420px;}'
  +'.fseal{width:50px;height:50px;border:2px solid #b8860b;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7px;font-weight:700;color:#8b6914;line-height:1.3;}'
  +'@page{size:A4 landscape;margin:11mm 13mm}@media print{body{padding:0}}';

function _sb(s){s=(s||'—').toUpperCase();var c=s==='COMPLETED'||s==='VERIFIED'?'bc':s==='PENDING'||s==='PROCESSING'?'bp':s==='FAILED'||s==='REJECTED'?'bf':'bd';return '<span class="b '+c+'">'+ s+'</span>';}
function _ph(title,n){
  return '<div class="gbar"></div>'
    +'<div class="cband"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; BIC: ALSHAEXXXX &mdash; REG: UAE/FIN/2024/0081</span><span>CONFIDENTIAL</span></div>'
    +'<div class="dhead"><div><div class="dco">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div><div class="dsub">'+title+' &mdash; '+new Date().toUTCString()+'</div></div>'
    +'<div style="display:flex;align-items:center;"><div class="dmeta">Records: <strong>'+n+'</strong><br>'+new Date().toLocaleDateString()+'<br>Ref: RPT-'+Date.now().toString(36).toUpperCase()+'</div><div class="dseal">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div></div></div>';}
function _pf(){return '<div class="foot"><div class="ftxt">This document is auto-generated by ALSHUMOOKH internal system. CONFIDENTIAL &mdash; authorised personnel only.<br>&copy; ALSHUMOOKH GROUP 2026 &mdash; compliance@alshumookh-pay.com</div><div class="fseal">ALSH<br>CERT<br>&#9733;</div></div>';}

function printTabData(tab){
  var data=_rData[tab]||[];
  if(!data.length){showToast('No data &mdash; please wait for data to load or click Refresh','error');return;}
  var titles={orders:'Payment Orders Report',m1:'M1 Tokenization Jobs',payloads:'Settlement Payloads',transfers:'Outbound Transfers'};
  var html='<!doctype html><html><head><meta charset=utf-8><title>'+titles[tab]+'</title><style>'+_pCSS+'</style></head><body>'+_ph(titles[tab],data.length);
  if(tab==='orders'){
    html+='<table><thead><tr><th>Order ID</th><th>Reference</th><th>Provider</th><th>Network</th><th>Status</th><th>Fiat Amount</th><th>Crypto</th><th>Wallet</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>';
    data.forEach(function(o){html+='<tr><td>'+esc((o.id||'—').slice(0,14))+'</td><td>'+esc(o.external_id||o.payment_reference||'—')+'</td><td>'+esc(o.provider||'—')+'</td><td>'+esc((o.network||'—').toUpperCase())+'</td><td>'+_sb(o.status)+'</td><td><strong>'+esc(String(o.fiat_amount||'—'))+' '+esc(o.fiat_currency||'')+'</strong></td><td>'+esc(String(o.crypto_amount||'—'))+' '+esc(o.crypto_currency||'')+'</td><td>'+esc((o.user_wallet_address||o.treasury_wallet_address||'—').slice(0,18))+'</td><td>'+esc((o.tx_hash||'—').slice(0,16))+'</td><td>'+esc(o.created_at?new Date(o.created_at).toLocaleDateString():'—')+'</td></tr>';});
  }else if(tab==='m1'){
    html+='<table><thead><tr><th>Job ID</th><th>Reference</th><th>Sender</th><th>IBAN</th><th>EUR Amount</th><th>FX Rate</th><th>SIG Output</th><th>Network</th><th>Status</th><th>Date</th></tr></thead><tbody>';
    data.forEach(function(r){html+='<tr><td>'+esc((r.id||'—').slice(0,14))+'</td><td>'+esc(r.sender_reference||'—')+'</td><td>'+esc(r.sender_name||'—')+'</td><td>'+esc((r.sender_iban||'—').slice(0,20))+'</td><td><strong>'+esc(String(r.eur_amount||'—'))+' EUR</strong></td><td>'+esc(String(r.fx_rate_eur_usd||r.fx_rate||'—'))+'</td><td><strong>'+esc(String(r.usdt_amount||'—'))+' '+esc(r.target_asset||'SIG')+'</strong></td><td>'+esc((r.network||'—').toUpperCase())+'</td><td>'+_sb(r.status)+'</td><td>'+esc(r.created_at?new Date(r.created_at).toLocaleDateString():'—')+'</td></tr>';});
  }else if(tab==='payloads'){
    html+='<table><thead><tr><th>Payload ID</th><th>Reference</th><th>Asset</th><th>Amount</th><th>Network</th><th>Status</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>';
    data.forEach(function(p){html+='<tr><td>'+esc((p.id||'—').slice(0,14))+'</td><td>'+esc(p.transaction_reference||p.request_id||'—')+'</td><td>'+esc(p.asset||'—')+'</td><td><strong>'+esc(String(p.amount||'—'))+'</strong></td><td>'+esc(p.network_name||'—')+'</td><td>'+_sb(p.verification_status)+'</td><td>'+esc((p.tx_hash||'—').slice(0,18))+'</td><td>'+esc(p.created_at?new Date(p.created_at).toLocaleDateString():'—')+'</td></tr>';});
  }else if(tab==='transfers'){
    html+='<table><thead><tr><th>Transfer ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Wallet</th><th>Status</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>';
    data.forEach(function(x){html+='<tr><td>'+esc((x.id||'—').slice(0,14))+'</td><td><strong>'+esc((x.network||'—').toUpperCase())+'</strong></td><td>'+esc(x.asset||x.currency||'USDT')+'</td><td><strong>'+esc(String(x.amount||'—'))+'</strong></td><td>'+esc((x.to_address||'—').slice(0,20))+'</td><td>'+_sb(x.status)+'</td><td>'+esc((x.tx_hash||'—').slice(0,18))+'</td><td>'+esc(x.created_at?new Date(x.created_at).toLocaleDateString():'—')+'</td></tr>';});
  }
  html+='</tbody></table>'+_pf()+'</body></html>';
  var w=window.open('','_blank','width=1200,height=820');w.document.write(html);w.document.close();setTimeout(function(){w.print();},450);
}

function printAllTransactions(){
  Promise.all([
    api('/api/v1/admin/orders').catch(function(){return[];}),
    api('/api/v1/admin/tokenization-jobs?limit=200').catch(function(){return[];}),
    api('/api/v1/admin/payloads?limit=200').catch(function(){return[];}),
    api('/api/v1/admin/outbound-transfers?limit=200').catch(function(){return[];})
  ]).then(function(res){
    var orders=Array.isArray(res[0])?res[0]:(res[0].orders||[]);
    var m1=Array.isArray(res[1])?res[1]:[];
    var payloads=Array.isArray(res[2])?res[2]:(res[2].payloads||[]);
    var transfers=Array.isArray(res[3])?res[3]:(res[3].transfers||[]);
    var total=orders.length+m1.length+payloads.length+transfers.length;
    var html='<!doctype html><html><head><meta charset=utf-8><title>Complete Transaction Audit</title><style>'+_pCSS+'</style></head><body>'+_ph('Complete Transaction Audit',total);
    html+='<div class="sgrid"><div class="scard"><div class="snum">'+orders.length+'</div><div class="slbl">Payment Orders</div></div><div class="scard"><div class="snum">'+m1.length+'</div><div class="slbl">M1 Jobs</div></div><div class="scard"><div class="snum">'+payloads.length+'</div><div class="slbl">Payloads</div></div><div class="scard"><div class="snum">'+transfers.length+'</div><div class="slbl">Transfers</div></div></div>';
    if(orders.length){html+='<h2>Payment Orders ('+orders.length+')</h2><table><thead><tr><th>ID</th><th>Reference</th><th>Provider</th><th>Status</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>Date</th></tr></thead><tbody>';orders.forEach(function(o){html+='<tr><td>'+esc((o.id||'—').slice(0,14))+'</td><td>'+esc(o.external_id||o.payment_reference||'—')+'</td><td>'+esc(o.provider||'')+'</td><td>'+_sb(o.status)+'</td><td><strong>'+esc(String(o.fiat_amount||'—'))+' '+esc(o.fiat_currency||'')+'</strong></td><td>'+esc(String(o.crypto_amount||'—'))+' '+esc(o.crypto_currency||'')+'</td><td>'+esc(o.network||'')+'</td><td>'+esc(o.created_at?new Date(o.created_at).toLocaleDateString():'—')+'</td></tr>';});html+='</tbody></table>';}
    if(m1.length){html+='<h2>M1 Tokenization Jobs ('+m1.length+')</h2><table><thead><tr><th>ID</th><th>Reference</th><th>Sender</th><th>EUR</th><th>FX</th><th>SIG</th><th>Network</th><th>Status</th><th>Date</th></tr></thead><tbody>';m1.forEach(function(r){html+='<tr><td>'+esc((r.id||'—').slice(0,14))+'</td><td>'+esc(r.sender_reference||'—')+'</td><td>'+esc(r.sender_name||'—')+'</td><td><strong>'+esc(String(r.eur_amount||'—'))+' EUR</strong></td><td>'+esc(String(r.fx_rate_eur_usd||r.fx_rate||'—'))+'</td><td><strong>'+esc(String(r.usdt_amount||'—'))+' '+esc(r.target_asset||'SIG')+'</strong></td><td>'+esc((r.network||'—').toUpperCase())+'</td><td>'+_sb(r.status)+'</td><td>'+esc(r.created_at?new Date(r.created_at).toLocaleDateString():'—')+'</td></tr>';});html+='</tbody></table>';}
    if(payloads.length){html+='<h2>Settlement Payloads ('+payloads.length+')</h2><table><thead><tr><th>ID</th><th>Reference</th><th>Asset</th><th>Amount</th><th>Network</th><th>Status</th><th>Date</th></tr></thead><tbody>';payloads.forEach(function(p){html+='<tr><td>'+esc((p.id||'—').slice(0,14))+'</td><td>'+esc(p.transaction_reference||p.request_id||'—')+'</td><td>'+esc(p.asset||'—')+'</td><td><strong>'+esc(String(p.amount||'—'))+'</strong></td><td>'+esc(p.network_name||'—')+'</td><td>'+_sb(p.verification_status)+'</td><td>'+esc(p.created_at?new Date(p.created_at).toLocaleDateString():'—')+'</td></tr>';});html+='</tbody></table>';}
    if(transfers.length){html+='<h2>Outbound Transfers ('+transfers.length+')</h2><table><thead><tr><th>ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Wallet</th><th>Status</th><th>Date</th></tr></thead><tbody>';transfers.forEach(function(x){html+='<tr><td>'+esc((x.id||'—').slice(0,14))+'</td><td>'+esc((x.network||'—').toUpperCase())+'</td><td>'+esc(x.asset||x.currency||'USDT')+'</td><td><strong>'+esc(String(x.amount||'—'))+'</strong></td><td>'+esc((x.to_address||'—').slice(0,22))+'</td><td>'+_sb(x.status)+'</td><td>'+esc(x.created_at?new Date(x.created_at).toLocaleDateString():'—')+'</td></tr>';});html+='</tbody></table>';}
    html+=_pf()+'</body></html>';
    var w=window.open('','_blank','width=1200,height=820');w.document.write(html);w.document.close();setTimeout(function(){w.print();},500);
  }).catch(function(e){showToast('Print error: '+e.message,'error');});
}

function loadReportOrders(){
  document.getElementById('rOrderCount').textContent='Loadingâ¦';
  api('/api/v1/admin/orders').then(function(rows){
    if(!Array.isArray(rows)) rows=rows.orders||[];
    _rData.orders=rows;
    document.getElementById('rOrderCount').textContent=rows.length+' orders';
    document.getElementById('statOrders').textContent=rows.length;
    if(!rows.length){document.getElementById('reportOrders').innerHTML='<div class="empty-state"><div class="icon">&#128202;</div>No orders found</div>';return;}
    var tb=rows.map(function(o){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(o.id||'')+'">'+esc((o.id||'—').slice(0,12))+'&#8230;</span></td>'
      +'<td>'+esc(o.external_id||o.payment_reference||'—')+'</td>'
      +'<td>'+esc(o.provider||'')+'</td>'
      +'<td>'+badge(o.status||'')+'</td>'
      +'<td class="amt-fiat">'+fmtNum(o.fiat_amount)+' '+esc(o.fiat_currency||'')+'</td>'
      +'<td>'+fmtNum(o.crypto_amount,6)+' '+esc(o.crypto_currency||'')+'</td>'
      +'<td>'+esc(o.network||'')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(o.created_at)+'</td>'
      +'<td><div style="display:flex;gap:4px;flex-wrap:wrap;">'
        +'<button class="btn btn-primary" data-id="'+esc(o.id||'')+'" onclick="window.open(\'/api/v1/admin/orders/\'+encodeURIComponent(this.dataset.id)+\'/documents/statement\',\'_blank\')" style="font-size:10px;padding:2px 7px;">Statement</button>'
        +'<button class="btn btn-ghost" data-id="'+esc(o.id||'')+'" onclick="window.open(\'/api/v1/admin/orders/\'+encodeURIComponent(this.dataset.id)+\'/documents/invoice\',\'_blank\')" style="font-size:10px;padding:2px 7px;">Invoice</button>'
        +'<button class="btn btn-ghost" data-id="'+esc(o.id||'')+'" onclick="document.getElementById(\'reportOrderId\').value=this.dataset.id;openSingleReport();" style="font-size:10px;padding:2px 7px;">Report</button>'
        +'</div></td>'
      +'</tr>';}).join('');
    document.getElementById('reportOrders').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Provider</th><th>Status</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportOrders').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportM1(){
  document.getElementById('rM1Count').textContent='Loadingâ¦';
  api('/api/v1/admin/tokenization-jobs?limit=200').then(function(rows){
    if(!Array.isArray(rows)) rows=[];
    _rData.m1=rows;
    document.getElementById('rM1Count').textContent=rows.length+' jobs';
    document.getElementById('statM1').textContent=rows.length;
    if(!rows.length){document.getElementById('reportM1').innerHTML='<div class="empty-state"><div class="icon">&#128260;</div>No M1 jobs found</div>';return;}
    var tb=rows.map(function(r){return '<tr>'
      +'<td><span class="mono-id" title="'+r.id+'">'+r.id.slice(0,10)+'&#8230;</span></td>'
      +'<td>'+esc(r.sender_reference||'—')+'</td>'
      +'<td>'+esc(r.sender_name||'—')+'</td>'
      +'<td class="amt-eur">'+fmtNum(r.eur_amount)+' EUR</td>'
      +'<td>'+esc(String(r.fx_rate||r.fx_rate_eur_usd||'—'))+'</td>'
      +'<td class="amt-sig">'+fmtNum(r.usdt_amount)+' '+esc(r.target_asset||'SIG')+'</td>'
      +'<td>'+esc((r.network||'—').toUpperCase())+'</td>'
      +'<td>'+badge(r.status)+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><button class="btn btn-ghost" data-ref="'+esc(r.id||'')+'" onclick="document.getElementById(\'reportOrderId\').value=this.dataset.ref;switchRTab(\'orders\')" style="font-size:10px;padding:2px 7px;">Find Order</button></td>'
      +'</tr>';}).join('');
    document.getElementById('reportM1').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Sender</th><th>EUR</th><th>FX Rate</th><th>SIG Amount</th><th>Network</th><th>Status</th><th>Date</th><th></th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportM1').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportPayloads(){
  document.getElementById('rPayloadCount').textContent='Loadingâ¦';
  api('/api/v1/admin/payloads?limit=200').then(function(data){
    var rows=Array.isArray(data)?data:(data.payloads||[]);
    _rData.payloads=rows;
    document.getElementById('rPayloadCount').textContent=rows.length+' payloads';
    document.getElementById('statPayloads').textContent=rows.length;
    if(!rows.length){document.getElementById('reportPayloads').innerHTML='<div class="empty-state"><div class="icon">&#128232;</div>No payloads found</div>';return;}
    var tb=rows.map(function(p){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(p.id||'')+'">'+esc((p.id||'—').slice(0,10))+'&#8230;</span></td>'
      +'<td>'+esc(p.transaction_reference||p.request_id||'—')+'</td>'
      +'<td>'+esc(p.asset||'—')+'</td>'
      +'<td class="amt-usdt"><strong>'+fmtNum(p.amount)+' '+esc(p.asset||'')+'</strong></td>'
      +'<td>'+esc(p.network_name||'—')+'</td>'
      +'<td>'+badge(p.verification_status||'')+'</td>'
      +'<td>'+(p.tx_hash?'<span class="mono-id" title="'+esc(p.tx_hash)+'">'+esc(p.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(p.created_at)+'</td>'
      +'</tr>';}).join('');
    document.getElementById('reportPayloads').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Asset</th><th>Amount</th><th>Network</th><th>Status</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportPayloads').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportTransfers(){
  document.getElementById('rXferCount').textContent='Loadingâ¦';
  api('/api/v1/admin/outbound-transfers?limit=200').then(function(data){
    var rows=Array.isArray(data)?data:(data.transfers||[]);
    _rData.transfers=rows;
    document.getElementById('rXferCount').textContent=rows.length+' transfers';
    document.getElementById('statTransfers').textContent=rows.length;
    if(!rows.length){document.getElementById('reportTransfers').innerHTML='<div class="empty-state"><div class="icon">&#128228;</div>No transfers found</div>';return;}
    var tb=rows.map(function(x){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(x.id||'')+'">'+esc((x.id||'—').slice(0,10))+'&#8230;</span></td>'
      +'<td><strong>'+esc((x.network||'—').toUpperCase())+'</strong></td>'
      +'<td>'+esc(x.asset||x.currency||'USDT')+'</td>'
      +'<td class="amt-usdt"><strong>'+fmtNum(x.amount)+'</strong></td>'
      +'<td>'+(x.to_address?'<span class="mono-id" title="'+esc(x.to_address)+'">'+esc(x.to_address.slice(0,14))+'&#8230;</span>':'—')+'</td>'
      +'<td>'+badge(x.status||'')+'</td>'
      +'<td>'+(x.tx_hash?'<span class="mono-id" title="'+esc(x.tx_hash)+'">'+esc(x.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(x.created_at)+'</td>'
      +'</tr>';}).join('');
    document.getElementById('reportTransfers').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Wallet</th><th>Status</th><th>TX Hash</th><th>Date</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportTransfers').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

loadReportOrders();
loadReportM1();
loadReportPayloads();
loadReportTransfers();
</script>
"""

# ─── AUDIT LOGS ───────────────────────────────────────────────────────────────

_LOGS_BODY = """
<div class="page-body">
  <div class="filter-bar">
    <select id="logLim" onchange="loadLogs()" style="min-width:110px;">
      <option value="50">50 records</option>
      <option value="100" selected>100 records</option>
      <option value="250">250 records</option>
      <option value="500">500 records</option>
    </select>
    <input id="logQ" placeholder="Search..." style="min-width:200px;" oninput="filterLogs()">
    <button class="btn btn-ghost" onclick="loadLogs()">Refresh</button>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>Audit Log</h3><span id="logCnt" style="color:var(--muted);font-size:12px;"></span></div>
    <div id="logBody"><div class="empty-state"><div class="icon">📝</div>Loading...</div></div>
  </div>
</div>
<script>
var _logRows=[];
function loadLogs(){
  var lim=document.getElementById('logLim').value;
  api('/api/v1/admin/audit-logs?limit='+lim).then(function(data){
    _logRows=Array.isArray(data)?data:[];
    document.getElementById('logCnt').textContent=_logRows.length+' records';
    filterLogs();
  }).catch(function(e){document.getElementById('logBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+e.message+'</div>';});
}
function filterLogs(){
  var q=document.getElementById('logQ').value.toLowerCase();
  renderLogs(q?_logRows.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}):_logRows);
}
function renderLogs(rows){
  if(!rows.length){document.getElementById('logBody').innerHTML='<div class="empty-state"><div class="icon">📝</div>No logs found</div>';return;}
  var th='<th>Event</th><th>Order ID</th><th>Client</th><th>Method</th><th>Endpoint</th><th>IP</th><th>Status</th><th>TX ID</th><th>Error</th><th>Date</th>';
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

@router.get("/dashboard/api/monitoring/live")
async def dashboard_api_monitoring_live(request: Request, db: AsyncSession = Depends(get_db)):
    _guard_api(request)

    orders_result = await db.execute(
        select(PaymentOrder.status, func.count(PaymentOrder.id).label("cnt")).group_by(PaymentOrder.status)
    )
    orders_by_status = {str(_enum_value(row.status)): int(row.cnt or 0) for row in orders_result}

    payloads_result = await db.execute(
        select(ExternalPayload.verification_status, func.count(ExternalPayload.id).label("cnt"))
        .group_by(ExternalPayload.verification_status)
    )
    payloads_by_status = {str(row.verification_status): int(row.cnt or 0) for row in payloads_result}

    transfers_result = await db.execute(
        select(OutboundTransfer.status, func.count(OutboundTransfer.id).label("cnt")).group_by(OutboundTransfer.status)
    )
    transfers_by_status = {str(_enum_value(row.status)): int(row.cnt or 0) for row in transfers_result}

    jobs_result = await db.execute(
        select(M1TokenizationJob.status, func.count(M1TokenizationJob.id).label("cnt"))
        .group_by(M1TokenizationJob.status)
    )
    jobs_by_status = {str(_enum_value(row.status)): int(row.cnt or 0) for row in jobs_result}

    recent_xfer_result = await db.execute(
        select(OutboundTransfer).order_by(desc(OutboundTransfer.created_at)).limit(5)
    )
    recent_transfers = [
        {
            "id": t.id,
            "status": str(_enum_value(t.status)),
            "network": str(_enum_value(t.network)),
            "amount": str(t.amount),
            "tx_hash": t.tx_hash,
            "created_at": _dt(t.created_at),
        }
        for t in recent_xfer_result.scalars().all()
    ]

    pending_result = await db.execute(
        select(func.count(OutboundTransfer.id)).where(
            OutboundTransfer.status.in_([
                OutboundTransferStatus.PENDING.value,
                OutboundTransferStatus.AWAITING_APPROVAL.value,
            ])
        )
    )
    pending_approvals = int(pending_result.scalar() or 0)

    m1_pending_result = await db.execute(
        select(func.count(M1TokenizationJob.id)).where(
            M1TokenizationJob.status == M1TokenizationStatus.COMPLETED.value,
            M1TokenizationJob.outbound_transfer_id.isnot(None),
        )
    )
    m1_pending = int(m1_pending_result.scalar() or 0)

    usdt_result = await db.execute(
        select(func.coalesce(func.sum(OutboundTransfer.amount), 0)).where(
            OutboundTransfer.status == OutboundTransferStatus.COMPLETED.value
        )
    )
    total_usdt_sent = float(usdt_result.scalar() or 0)

    audit_result = await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(10))
    recent_events = [
        {"event_type": a.event_type, "order_id": a.order_id, "created_at": _dt(a.created_at)}
        for a in audit_result.scalars().all()
    ]

    return {
        "orders": {"by_status": orders_by_status, "total": sum(orders_by_status.values())},
        "payloads": {"by_status": payloads_by_status, "total": sum(payloads_by_status.values())},
        "outbound_transfers": {
            "by_status": transfers_by_status,
            "total": sum(transfers_by_status.values()),
            "pending_approvals": pending_approvals,
            "total_usdt_sent": total_usdt_sent,
            "recent": recent_transfers,
        },
        "tokenization_jobs": {
            "by_status": jobs_by_status,
            "total": sum(jobs_by_status.values()),
            "m1_awaiting_approval": m1_pending,
        },
        "recent_events": recent_events,
        "health": {"database": "ok", "pending_actions": pending_approvals + m1_pending},
    }


@router.get("/dashboard/api/system/readiness")
async def dashboard_api_system_readiness(request: Request, db: AsyncSession = Depends(get_db)):
    _guard_api(request)
    clients_total = (await db.execute(select(func.count(ApiClient.id)))).scalar() or 0
    payloads_total = (await db.execute(select(func.count(ExternalPayload.id)))).scalar() or 0
    warnings = list(settings.readiness_warnings())
    return {
        "status": "ok",
        "warning_count": len(warnings),
        "warnings": warnings,
        "checks": {
            "database": "ok",
            "dashboard_auth": "ok",
            "counterparties_total": int(clients_total),
            "payloads_total": int(payloads_total),
        },
    }


@router.get("/dashboard/api/summary")
async def dashboard_api_summary(request: Request, db: AsyncSession = Depends(get_db)):
    _guard_api(request)
    res = await db.execute(select(PaymentOrder).order_by(desc(PaymentOrder.created_at)).limit(50))
    orders = list(res.scalars().all())
    by_status = {status.value: 0 for status in OrderStatus}
    fiat_total = 0.0
    crypto_total = 0.0
    completed = failed = pending = 0
    for order in orders:
        st = str(_enum_value(order.status))
        by_status[st] = by_status.get(st, 0) + 1
        if st == OrderStatus.COMPLETED.value:
            completed += 1
            fiat_total += float(order.fiat_amount or 0)
            crypto_total += float(order.crypto_amount or 0)
        if st in {OrderStatus.CREATED.value, OrderStatus.PENDING.value, OrderStatus.PROCESSING.value}:
            pending += 1
        if st == OrderStatus.FAILED.value:
            failed += 1
    return {
        "orders_total": len(orders),
        "orders_completed": completed,
        "pending_orders": pending,
        "failed_orders": failed,
        "total_fiat_amount": round(fiat_total, 2),
        "total_crypto_amount": round(crypto_total, 8),
        "by_status": by_status,
        "latest_orders": [
            {
                "id": str(o.id),
                "status": str(_enum_value(o.status)),
                "fiat_amount": str(o.fiat_amount) if o.fiat_amount is not None else None,
                "fiat_currency": o.fiat_currency,
                "crypto_amount": str(o.crypto_amount) if o.crypto_amount is not None else None,
                "crypto_currency": o.crypto_currency,
                "network": str(_enum_value(o.network)),
                "created_at": _dt(o.created_at),
            }
            for o in orders[:10]
        ],
    }


@router.get("/dashboard/api/payloads")
async def dashboard_api_payloads(request: Request, db: AsyncSession = Depends(get_db)):
    _guard_api(request)
    res = await db.execute(select(ExternalPayload).order_by(desc(ExternalPayload.created_at)).limit(100))
    return {"payloads": [_payload_row(p) for p in res.scalars().all()]}


@router.post("/dashboard/api/deploy")
async def dashboard_api_deploy(request: Request):
    """Pull latest code from GitHub and restart the service."""
    import subprocess
    _guard_api(request)
    try:
        pull = subprocess.run(
            ["git", "pull", "--rebase"],
            capture_output=True, text=True, timeout=60,
            cwd="/root/alshumookh"
        )
        restart = subprocess.run(
            ["systemctl", "restart", "alshumookh"],
            capture_output=True, text=True, timeout=30
        )
        return {
            "status": "ok",
            "pull": pull.stdout.strip() or pull.stderr.strip(),
            "restart": restart.stdout.strip() or restart.stderr.strip() or "Service restarting...",
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Overview", "/dashboard", _OVERVIEW_BODY))


@router.get("/dashboard/overview", response_class=HTMLResponse)
async def dashboard_overview(request: Request):
    return RedirectResponse("/dashboard", status_code=http_status.HTTP_302_FOUND)


@router.get("/dashboard/orders", response_class=HTMLResponse)
async def dashboard_orders(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Orders", "/dashboard/orders", _ORDERS_BODY))


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


@router.get("/dashboard/m1-reserve", response_class=HTMLResponse)
async def dashboard_m1_reserve(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("M1 Reserve", "/dashboard/m1-reserve", _M1_RESERVE_BODY))


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
    return HTMLResponse(_page("Payments", "/dashboard/payments", _PAYMENTS_BODY))


@router.get("/dashboard/stripe", response_class=HTMLResponse)
async def dashboard_stripe(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Stripe", "/dashboard/stripe", _STRIPE_BODY))


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


@router.get("/dashboard/reports", response_class=HTMLResponse)
async def dashboard_reports(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Reports", "/dashboard/reports", _REPORTS_BODY))


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


@router.get("/dashboard/ping")
async def dashboard_ping(request: Request):
    """Public diagnostic endpoint — no auth needed."""
    import subprocess, sys
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "unknown"
    session_ok = is_admin_request_authenticated(request)
    header_key = request.headers.get("X-Admin-API-Key", "")
    cookie_key = request.cookies.get("als_ak", "")
    expected = str(settings.admin_api_key or "")
    header_valid = bool(header_key) and bool(expected) and hmac.compare_digest(header_key, expected)
    cookie_valid = bool(cookie_key) and bool(expected) and hmac.compare_digest(cookie_key, expected)
    from fastapi.responses import JSONResponse as _JR
    return _JR({
        "status": "ok",
        "commit": commit,
        "python": sys.version.split()[0],
        "auth": {
            "session_cookie": session_ok,
            "api_key_header": header_valid,
            "api_key_cookie": cookie_valid,
            "any_auth": session_ok or header_valid or cookie_valid,
        },
        "hint": "if any_auth=false, enter your Admin API Key in the dashboard top bar",
    })
