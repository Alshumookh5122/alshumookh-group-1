"""
ALSHUMOOKH GLOBAL — Client Portal Multi-Page System
Each section is a dedicated page with shared sidebar + navigation.
"""
from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status

router = APIRouter(tags=["client-pages"])

ETH_WALLET  = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
TRON_WALLET = "TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn"

# ── Sidebar ───────────────────────────────────────────────────────────────────
CLIENT_SIDEBAR = f"""
<aside class="sidebar">
  <div class="brand-panel">
    <img class="brand-logo" src="/static/company-logo.png" alt="Logo"
         onerror="this.style.display='none';this.nextElementSibling.style.display='grid';">
    <div class="brand-mark">SG</div>
    <div>
      <p class="eyebrow">Client Portal</p>
      <h1>ALSHUMOOKH GLOBAL</h1>
    </div>
  </div>
  <nav>
    <a href="/client">🏠 Overview</a>
    <a href="/client/orders">📋 معاملاتي</a>
    <a href="/client/pay/direct">🔑 Crypto Direct</a>
    <a href="/client/pay/moonpay">🌙 MoonPay</a>
    <a href="/client/pay/onramper">🏦 Onramper</a>
  </nav>
  <div class="sidebar-foot">
    <span>محافظ التسوية</span>
    <strong style="color:#a78bfa;">Ethereum (ERC-20)</strong>
    <code style="font-size:10px;">{ETH_WALLET[:14]}…</code>
    <strong style="color:#34d399;margin-top:6px;">TRON (TRC-20)</strong>
    <code style="font-size:10px;">{TRON_WALLET[:14]}…</code>
    <a href="#" onclick="event.preventDefault();fetch('/client/logout',{{method:'POST'}}).then(()=>location.href='/login?type=client')"
       style="margin-top:12px;display:block;text-align:center;padding:7px;background:rgba(220,38,38,.15);border:1px solid rgba(220,38,38,.3);border-radius:6px;color:#f87171;font-size:11px;font-weight:700;text-decoration:none;">
      ⏻ تسجيل الخروج
    </a>
  </div>
</aside>
"""

def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} — ALSHUMOOKH GLOBAL</title>
  <link rel="stylesheet" href="/static/dashboard.css?v=cp003">
</head>
<body>
{CLIENT_SIDEBAR}
<main>
{body}
</main>
<script src="/static/shared.js"></script>
</body>
</html>"""

def _topbar(title: str, sub: str = "Client Portal") -> str:
    return f"""
<section class="topbar">
  <div>
    <p class="eyebrow">{sub}</p>
    <h2 style="margin:0;font-size:18px;font-weight:800;color:var(--gold);">{title}</h2>
  </div>
  <div style="display:flex;gap:10px;align-items:center;">
    <span id="_accountName" style="color:var(--muted);font-size:13px;"></span>
    <span id="_keyState" style="width:8px;height:8px;border-radius:50%;background:#34d399;display:inline-block;"></span>
  </div>
</section>
<script>
const CK = sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'';
if(!CK) {{ location.href='/login?type=client'; }}
</script>
"""

def _auth_check(request: Request) -> bool:
    from app.auth import ADMIN_SESSION_COOKIE
    # client portal uses API key — check cookie or redirect
    # For session-based client auth:
    cookie = request.cookies.get("client_session")
    return bool(cookie)

def _redir():
    return RedirectResponse("/login?type=client", status_code=status.HTTP_303_SEE_OTHER)


# ════════════════════════════════════════════════════════════════════
# PAGE: CLIENT OVERVIEW
# ════════════════════════════════════════════════════════════════════
CLIENT_OVERVIEW_HTML = """
<div class="page-body">
  <div class="stat-grid">
    <div class="stat-card"><div class="label">إجمالي الطلبات</div><div class="value" id="cTotal">—</div></div>
    <div class="stat-card"><div class="label">مكتملة</div><div class="value" id="cCompleted" style="color:#10b981;">—</div></div>
    <div class="stat-card"><div class="label">معلّقة</div><div class="value" id="cPending" style="color:#f59e0b;">—</div></div>
    <div class="stat-card"><div class="label">فاشلة</div><div class="value" id="cFailed" style="color:#ef4444;">—</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px;">
    <div class="panel">
      <div class="panel-head"><h3>🔑 مفتاح API</h3></div>
      <div style="padding:16px;">
        <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">أدخل مفتاح API لبدء استخدام البوابة</p>
        <div style="display:flex;gap:8px;">
          <input id="apiKeyInput" type="password" placeholder="أدخل Client API Key"
            style="flex:1;background:var(--panel);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;">
          <button class="btn btn-success" onclick="saveKey()">حفظ</button>
        </div>
        <div id="keyStatus" style="margin-top:10px;font-size:12px;"></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>⚡ إجراءات سريعة</h3></div>
      <div style="padding:16px;display:grid;gap:10px;">
        <a href="/client/pay/direct" class="btn btn-primary" style="text-decoration:none;text-align:center;">🔑 Crypto Direct</a>
        <a href="/client/pay/moonpay" class="btn btn-ghost" style="text-decoration:none;text-align:center;">🌙 MoonPay</a>
        <a href="/client/pay/onramper" class="btn btn-ghost" style="text-decoration:none;text-align:center;">🏦 Onramper</a>
      </div>
    </div>
  </div>

  <div class="panel" style="margin-top:16px;">
    <div class="panel-head"><h3>📋 آخر الطلبات</h3><a href="/client/orders" class="btn btn-ghost" style="text-decoration:none;font-size:12px;padding:4px 12px;">عرض الكل</a></div>
    <div id="recentOrders" style="padding:16px;"></div>
  </div>
</div>

<script>
const CK = ()=>(sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'');
const H = ()=>({'X-Api-Key':CK(),'Content-Type':'application/json'});

function saveKey() {
  const k = document.getElementById('apiKeyInput').value.trim();
  if(!k){showToast('أدخل المفتاح أولاً','warn');return;}
  sessionStorage.setItem('als_client_key',k);
  localStorage.setItem('als_client_key',k);
  showToast('✓ تم حفظ المفتاح','ok');
  loadOverview();
}

async function loadOverview() {
  try {
    const data = await fetch('/client/api/orders',{headers:H()}).then(r=>r.json());
    const rows = Array.isArray(data)?data:(data.orders||[]);
    const total = rows.length;
    const completed = rows.filter(r=>r.status==='COMPLETED').length;
    const pending = rows.filter(r=>['PENDING','CREATED','PROCESSING'].includes(r.status)).length;
    const failed = rows.filter(r=>r.status==='FAILED').length;
    document.getElementById('cTotal').textContent = total;
    document.getElementById('cCompleted').textContent = completed;
    document.getElementById('cPending').textContent = pending;
    document.getElementById('cFailed').textContent = failed;

    const recent = rows.slice(0,5);
    document.getElementById('recentOrders').innerHTML = recent.length ? recent.map(o=>`
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);font-size:13px;">
        <span><code style="font-size:11px;">${o.id.slice(0,10)}…</code> <span style="color:var(--muted);">${o.provider||''}</span></span>
        <span>${badge(o.status)}</span>
        <span style="color:var(--gold);font-weight:700;">${parseFloat(o.amount||0).toLocaleString()} ${o.currency||''}</span>
      </div>`).join('') : '<div style="color:var(--muted);text-align:center;padding:20px;">لا توجد طلبات</div>';

    document.getElementById('keyStatus').innerHTML = '<span style="color:#10b981;font-weight:600;">✓ مفتاح API يعمل</span>';
  } catch(e) {
    document.getElementById('keyStatus').innerHTML = '<span style="color:#ef4444;">✗ تحقق من المفتاح</span>';
  }
}

function badge(s){const c={COMPLETED:'#10b981',PENDING:'#f59e0b',FAILED:'#ef4444',PROCESSING:'#8b5cf6',CREATED:'#6b7280'}[s]||'#6b7280';return `<span style="padding:2px 8px;border-radius:12px;background:${c}22;color:${c};border:1px solid ${c}44;font-size:11px;font-weight:700;">${s}</span>`;}
function showToast(msg,t){let el=document.getElementById('_t');if(!el){el=document.createElement('div');el.id='_t';el.style.cssText='position:fixed;bottom:24px;right:24px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s;';document.body.appendChild(el);}el.style.background={ok:'#059669',error:'#dc2626',warn:'#d97706',info:'#1d4ed8'}[t]||'#1d4ed8';el.style.color='#fff';el.style.opacity='1';el.textContent=msg;clearTimeout(el._tm);el._tm=setTimeout(()=>el.style.opacity='0',3500);}

const existing = CK();
if(existing) { document.getElementById('apiKeyInput').value='***stored***'; loadOverview(); }
</script>
"""

# ════════════════════════════════════════════════════════════════════
# PAGE: CLIENT ORDERS
# ════════════════════════════════════════════════════════════════════
CLIENT_ORDERS_HTML = """
<div class="page-body">
  <div class="filter-bar">
    <select id="orderFilter" onchange="loadOrders()">
      <option value="">جميع الحالات</option>
      <option>CREATED</option><option>PENDING</option><option>PROCESSING</option>
      <option>COMPLETED</option><option>FAILED</option>
      <option>RECEIVED</option><option>MANUAL_REVIEW</option><option>VERIFIED</option><option>REJECTED</option>
    </select>
    <button class="btn btn-ghost" onclick="loadOrders()">🔄 تحديث</button>
  </div>
  <div id="ordersTable"><div class="empty-state"><div class="icon">📋</div>جاري التحميل...</div></div>
  <div class="panel" style="margin-top:16px;">
    <div class="panel-head"><h3>Submitted Payloads</h3></div>
    <div id="payloadsTable" style="padding:16px;"><div class="empty-state"><div class="icon">📦</div>Loading payloads...</div></div>
  </div>
</div>
<script>
const CK = ()=>(sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'');
const H = ()=>({'X-Api-Key':CK()});

async function loadOrders() {
  const st = document.getElementById('orderFilter').value;
  try {
    const [ordersData, payloadsData] = await Promise.all([
      fetch('/client/api/orders'+(st?'?status='+st:''),{headers:H()}).then(r=>r.json()),
      fetch('/client/api/payloads'+(st?'?status='+st:''),{headers:H()}).then(r=>r.json())
    ]);
    const rows = Array.isArray(ordersData)?ordersData:(ordersData.orders||[]);
    const payloads = Array.isArray(payloadsData)?payloadsData:(payloadsData.payloads||[]);
    document.getElementById('ordersTable').innerHTML = rows.length ? buildTable(rows) : '<div class="empty-state"><div class="icon">📋</div>لا توجد طلبات</div>';
    document.getElementById('payloadsTable').innerHTML = payloads.length ? buildPayloadsTable(payloads) : '<div class="empty-state"><div class="icon">📦</div>No submitted payloads</div>';
  } catch(e) { document.getElementById('ordersTable').innerHTML=`<div class="empty-state"><div class="icon">❌</div>${e.message}</div>`; }
}

function buildTable(rows){
  const h=['ID','Provider','Currency','Amount','Network','Status','TX Hash','تاريخ'].map(l=>`<th>${l}</th>`).join('');
  const r=rows.map(o=>`<tr>
    <td><code style="font-size:10px;">${o.id.slice(0,10)}…</code></td>
    <td>${o.provider||'—'}</td>
    <td>${o.currency||'—'}</td>
    <td style="font-weight:700;color:var(--gold);">${parseFloat(o.amount||0).toLocaleString()}</td>
    <td>${o.network||'—'}</td>
    <td>${badge(o.status)}</td>
    <td>${o.tx_hash?`<code style="font-size:10px;">${o.tx_hash.slice(0,12)}…</code>`:'—'}</td>
    <td style="font-size:11px;">${fmtDate(o.created_at)}</td>
  </tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${h}</tr></thead><tbody>${r}</tbody></table></div>`;
}

function buildPayloadsTable(rows){
  const h=['Reference','Amount','Asset','Network','Verification','TX Hash','Submitted'].map(l=>`<th>${l}</th>`).join('');
  const r=rows.map(p=>`<tr>
    <td><code style="font-size:10px;">${escapeHtml(p.payload_reference||p.id||'—')}</code></td>
    <td style="font-weight:700;color:var(--gold);">${p.amount?parseFloat(p.amount).toLocaleString():'—'}</td>
    <td>${escapeHtml(p.asset||'—')}</td>
    <td>${escapeHtml(p.network||'—')}</td>
    <td>${badge(p.verification_status||'RECEIVED')}</td>
    <td>${p.tx_hash?`<a href="${p.explorer_url||'#'}" target="_blank" style="color:#60a5fa;"><code style="font-size:10px;">${p.tx_hash.slice(0,12)}…</code></a>`:'—'}</td>
    <td style="font-size:11px;">${fmtDate(p.submitted_date||p.created_at)}</td>
  </tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${h}</tr></thead><tbody>${r}</tbody></table></div>`;
}

function badge(s){const c={COMPLETED:'#10b981',PENDING:'#f59e0b',FAILED:'#ef4444',PROCESSING:'#8b5cf6',CREATED:'#6b7280'}[s]||'#6b7280';return `<span style="padding:2px 8px;border-radius:12px;background:${c}22;color:${c};border:1px solid ${c}44;font-size:11px;font-weight:700;">${s}</span>`;}
function fmtDate(d){return d?new Date(d).toLocaleString('ar-SA',{dateStyle:'short',timeStyle:'short'}):'—';}
function escapeHtml(v){return String(v||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}
loadOrders();
</script>
"""

# ════════════════════════════════════════════════════════════════════
# PAGE: CRYPTO DIRECT
# ════════════════════════════════════════════════════════════════════
ETH_WALLET_FULL  = ETH_WALLET
TRON_WALLET_FULL = TRON_WALLET

CLIENT_DIRECT_HTML = f"""
<div class="page-body">
  <div style="max-width:680px;margin:0 auto;">
    <div class="panel" style="border-top:3px solid var(--gold);">
      <div class="panel-head"><h3>🔑 Crypto Direct Payment</h3><span class="state">ETH / TRON / Base</span></div>
      <div style="padding:20px;">
        <p style="color:var(--muted);font-size:13px;margin:0 0 20px;">إرسال USDT مباشرة إلى محفظة الشركة — اختر الشبكة المناسبة</p>

        <!-- Network tabs -->
        <div style="display:flex;gap:8px;margin-bottom:20px;">
          <button class="btn btn-primary" id="tabEth" onclick="switchNet('eth')">🔷 Ethereum</button>
          <button class="btn btn-ghost"   id="tabTron" onclick="switchNet('tron')">🔴 TRON</button>
          <button class="btn btn-ghost"   id="tabBase" onclick="switchNet('base')">🔵 Base</button>
        </div>

        <!-- ETH card -->
        <div id="cardEth" style="background:linear-gradient(135deg,#1e1b4b,#312e81);border:2px solid #6366f1;border-radius:14px;padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="background:#6366f1;color:#fff;border-radius:6px;padding:3px 12px;font-size:12px;font-weight:800;">ERC-20</span>
            <span style="color:#a5b4fc;font-size:13px;">Ethereum Mainnet — USDT / USDC</span>
          </div>
          <div style="font-size:11px;color:#818cf8;margin-bottom:6px;">عنوان محفظة ALSHUMOOKH</div>
          <code style="color:#e0e7ff;word-break:break-all;display:block;margin:8px 0;font-size:13px;background:rgba(0,0,0,.3);border-radius:8px;padding:10px;">{ETH_WALLET_FULL}</code>
          <button class="btn btn-primary" onclick="navigator.clipboard.writeText('{ETH_WALLET_FULL}');showToast('تم النسخ ✓','ok')">نسخ العنوان</button>
        </div>

        <!-- TRON card (hidden) -->
        <div id="cardTron" style="display:none;background:linear-gradient(135deg,#064e3b,#065f46);border:2px solid #10b981;border-radius:14px;padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="background:#10b981;color:#fff;border-radius:6px;padding:3px 12px;font-size:12px;font-weight:800;">TRC-20</span>
            <span style="color:#6ee7b7;font-size:13px;">TRON Network — USDT TRC-20 فقط</span>
          </div>
          <div style="background:rgba(245,158,11,.15);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:10px;margin-bottom:10px;font-size:12px;color:#fcd34d;">
            ⚠️ أرسل USDT TRC-20 فقط — لا تُرسل ETH أو ERC-20 على هذه الشبكة
          </div>
          <code style="color:#d1fae5;word-break:break-all;display:block;margin:8px 0;font-size:13px;background:rgba(0,0,0,.3);border-radius:8px;padding:10px;">{TRON_WALLET_FULL}</code>
          <button class="btn btn-success" onclick="navigator.clipboard.writeText('{TRON_WALLET_FULL}');showToast('تم النسخ ✓','ok')">نسخ العنوان</button>
        </div>

        <!-- Base card (hidden) -->
        <div id="cardBase" style="display:none;background:linear-gradient(135deg,#1e3a5f,#1d4ed8);border:2px solid #60a5fa;border-radius:14px;padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="background:#60a5fa;color:#fff;border-radius:6px;padding:3px 12px;font-size:12px;font-weight:800;">Base</span>
            <span style="color:#bfdbfe;font-size:13px;">Base Network — USDC / USDT</span>
          </div>
          <code style="color:#dbeafe;word-break:break-all;display:block;margin:8px 0;font-size:13px;background:rgba(0,0,0,.3);border-radius:8px;padding:10px;">{ETH_WALLET_FULL}</code>
          <button class="btn btn-ghost" onclick="navigator.clipboard.writeText('{ETH_WALLET_FULL}');showToast('تم النسخ ✓','ok')">نسخ العنوان</button>
        </div>

        <!-- Create payment form -->
        <div class="panel" style="margin-top:20px;">
          <div class="panel-head"><h3>إنشاء طلب دفع مباشر</h3></div>
          <div style="padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><label style="font-size:12px;color:var(--muted);">المبلغ</label>
              <input id="dcAmt" type="number" placeholder="100.00" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
            <div><label style="font-size:12px;color:var(--muted);">العملة</label>
              <select id="dcCurrency" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;">
                <option>USDT</option><option>USDC</option><option>ETH</option><option>SIG</option>
              </select></div>
            <div style="grid-column:span 2;"><label style="font-size:12px;color:var(--muted);">رقم مرجعي (اختياري)</label>
              <input id="dcRef" placeholder="INV-2026-001" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
            <div style="grid-column:span 2;">
              <button class="btn btn-primary" style="width:100%;" onclick="createDirect()">إنشاء طلب دفع</button>
            </div>
          </div>
          <div id="dcResult" style="padding:0 16px 16px;font-size:12px;"></div>
        </div>
      </div>
    </div>
  </div>
</div>
<script>
let currentNet = 'eth';
function switchNet(n) {{
  currentNet = n;
  ['eth','tron','base'].forEach(x=>{{
    document.getElementById('card'+x.charAt(0).toUpperCase()+x.slice(1)).style.display=x===n?'block':'none';
    document.getElementById('tab'+x.charAt(0).toUpperCase()+x.slice(1)).className='btn '+(x===n?'btn-primary':'btn-ghost');
  }});
}}

const CK = ()=>(sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'');
async function createDirect() {{
  const body = {{
    crypto_amount: document.getElementById('dcAmt').value,
    crypto_currency: document.getElementById('dcCurrency').value,
    network: currentNet==='eth'?'ethereum':currentNet,
    external_id: document.getElementById('dcRef').value||undefined,
  }};
  try {{
    const d = await fetch('/client/pay/direct',{{method:'POST',headers:{{'X-Api-Key':CK(),'Content-Type':'application/json'}},body:JSON.stringify(body)}}).then(r=>r.json());
    const wallet = currentNet==='tron'?'{TRON_WALLET_FULL}':'{ETH_WALLET_FULL}';
    document.getElementById('dcResult').innerHTML = `
      <div style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);border-radius:10px;padding:14px;">
        <strong style="color:#10b981;">✅ تم إنشاء طلب الدفع</strong><br><br>
        <b>المرجع:</b> <code>${{d.external_id||d.id}}</code><br>
        <b>المبلغ:</b> ${{body.crypto_amount}} ${{body.crypto_currency}}<br>
        <b>الشبكة:</b> ${{body.network}}<br>
        <b>العنوان:</b><br><code style="word-break:break-all;">${{wallet}}</code>
      </div>`;
  }} catch(e) {{ document.getElementById('dcResult').innerHTML=`<span style="color:#ef4444;">${{e.message}}</span>`; }}
}}

function showToast(msg,t){{let el=document.getElementById('_t');if(!el){{el=document.createElement('div');el.id='_t';el.style.cssText='position:fixed;bottom:24px;right:24px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s;';document.body.appendChild(el);}}el.style.background={{ok:'#059669',error:'#dc2626',warn:'#d97706',info:'#1d4ed8'}}[t]||'#1d4ed8';el.style.color='#fff';el.style.opacity='1';el.textContent=msg;clearTimeout(el._tm);el._tm=setTimeout(()=>el.style.opacity='0',3500);}}
</script>
"""

# ════════════════════════════════════════════════════════════════════
# PAGE: MOONPAY
# ════════════════════════════════════════════════════════════════════
CLIENT_MOONPAY_HTML = """
<div class="page-body">
  <div style="max-width:680px;margin:0 auto;">
    <div class="panel accent" style="border-top:3px solid #9333ea;">
      <div class="panel-head"><h3>🌙 MoonPay — Fiat to Crypto</h3><span class="state">بطاقة / تحويل بنكي</span></div>
      <div style="padding:20px;">
        <p style="color:var(--muted);font-size:13px;margin:0 0 20px;">
          ادفع ببطاقة Visa/Mastercard أو تحويل بنكي — تستلم الشركة USDC/ETH مباشرة
        </p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label style="font-size:12px;color:var(--muted);">قيمة الدفع</label>
            <input id="mpAmt" type="number" placeholder="100" value="100" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div><label style="font-size:12px;color:var(--muted);">عملة الدفع</label>
            <input id="mpFiat" value="USD" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div><label style="font-size:12px;color:var(--muted);">عملة الشراء</label>
            <select id="mpCrypto" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;">
              <option>USDC</option><option>ETH</option><option>USDT</option><option>SIG</option>
            </select></div>
          <div><label style="font-size:12px;color:var(--muted);">الشبكة</label>
            <select id="mpNet" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;">
              <option value="ethereum">Ethereum</option><option value="base">Base</option>
            </select></div>
          <div style="grid-column:span 2;"><label style="font-size:12px;color:var(--muted);">رقم مرجعي</label>
            <input id="mpRef" placeholder="INV-2026-001" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div style="grid-column:span 2;">
            <button class="btn btn-primary" style="width:100%;" onclick="createMoonpay()">🌙 إنشاء رابط MoonPay</button>
          </div>
        </div>
        <div id="mpResult" style="margin-top:16px;font-size:12px;"></div>
      </div>
    </div>
  </div>
</div>
<script>
const CK = ()=>(sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'');
async function createMoonpay() {
  const body = {
    fiat_amount: document.getElementById('mpAmt').value,
    fiat_currency: document.getElementById('mpFiat').value,
    crypto_currency: document.getElementById('mpCrypto').value,
    network: document.getElementById('mpNet').value,
    external_id: document.getElementById('mpRef').value||undefined,
  };
  try {
    const d = await fetch('/client/pay/moonpay',{method:'POST',headers:{'X-Api-Key':CK(),'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    const url = d.widget_url||d.checkout_url||d.url;
    document.getElementById('mpResult').innerHTML = url ?
      `<div style="background:rgba(147,51,234,.1);border:1px solid rgba(147,51,234,.3);border-radius:10px;padding:14px;">
        <strong style="color:#a78bfa;">✅ رابط MoonPay جاهز</strong><br><br>
        <a href="${url}" target="_blank" class="btn btn-primary" style="text-decoration:none;display:inline-block;margin-top:8px;">🔗 فتح صفحة الدفع</a>
        <button class="btn btn-ghost" style="margin-right:8px;" onclick="navigator.clipboard.writeText('${url}');showToast('تم النسخ','ok')">نسخ الرابط</button>
       </div>` :
      `<pre style="color:#10b981;font-size:11px;white-space:pre-wrap;">${JSON.stringify(d,null,2)}</pre>`;
  } catch(e) { document.getElementById('mpResult').innerHTML=`<span style="color:#ef4444;">${e.message}</span>`; }
}
function showToast(msg,t){let el=document.getElementById('_t');if(!el){el=document.createElement('div');el.id='_t';el.style.cssText='position:fixed;bottom:24px;right:24px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s;';document.body.appendChild(el);}el.style.background={ok:'#059669',error:'#dc2626',warn:'#d97706'}[t]||'#1d4ed8';el.style.color='#fff';el.style.opacity='1';el.textContent=msg;clearTimeout(el._tm);el._tm=setTimeout(()=>el.style.opacity='0',3500);}
</script>
"""

# Circle is intentionally not exposed in the client portal.
CLIENT_CIRCLE_HTML = ""

# ════════════════════════════════════════════════════════════════════
# PAGE: ONRAMPER
# ════════════════════════════════════════════════════════════════════
CLIENT_ONRAMPER_HTML = """
<div class="page-body">
  <div style="max-width:680px;margin:0 auto;">
    <div class="panel" style="border-top:3px solid #00c26f;">
      <div class="panel-head"><h3>🏦 Onramper — 30+ مزود دفع</h3></div>
      <div style="padding:20px;">
        <p style="color:var(--muted);font-size:13px;margin:0 0 8px;">
          Visa/Mastercard · SEPA · Apple Pay · Google Pay · iDEAL · Sofort · وأكثر
        </p>
        <p style="color:var(--muted);font-size:12px;margin:0 0 20px;">يختار Onramper تلقائياً أفضل مزود متاح في منطقتك بأقل رسوم</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label style="font-size:12px;color:var(--muted);">المبلغ</label>
            <input id="orAmt" type="number" placeholder="100" value="100" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div><label style="font-size:12px;color:var(--muted);">العملة الورقية</label>
            <input id="orFiat" value="EUR" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div style="grid-column:span 2;"><label style="font-size:12px;color:var(--muted);">رقم مرجعي</label>
            <input id="orRef" placeholder="INV-2026-001" style="width:100%;background:var(--bg2);border:1px solid var(--line-strong);border-radius:8px;padding:9px 12px;color:var(--ink);font-size:13px;margin-top:4px;"></div>
          <div style="grid-column:span 2;">
            <button class="btn btn-success" style="width:100%;" onclick="createOnramper()">🏦 إنشاء رابط Onramper</button>
          </div>
        </div>
        <div id="orResult" style="margin-top:16px;font-size:12px;"></div>
      </div>
    </div>
  </div>
</div>
<script>
const CK = ()=>(sessionStorage.getItem('als_client_key')||localStorage.getItem('als_client_key')||'');
async function createOnramper() {
  const body = {
    amount: document.getElementById('orAmt').value,
    fiat_currency: document.getElementById('orFiat').value,
    external_id: document.getElementById('orRef').value||undefined,
  };
  try {
    const d = await fetch('/client/pay/onramper',{method:'POST',headers:{'X-Api-Key':CK(),'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    const url = d.widget_url||d.checkout_url||d.url;
    document.getElementById('orResult').innerHTML = url ?
      `<div style="background:rgba(0,194,111,.1);border:1px solid rgba(0,194,111,.3);border-radius:10px;padding:14px;">
        <strong style="color:#00c26f;">✅ رابط Onramper جاهز</strong><br><br>
        <a href="${url}" target="_blank" class="btn btn-success" style="text-decoration:none;display:inline-block;margin-top:8px;">🔗 فتح صفحة الدفع</a>
        <button class="btn btn-ghost" style="margin-right:8px;" onclick="navigator.clipboard.writeText('${url}')">نسخ</button>
       </div>` :
      `<pre style="color:#10b981;font-size:11px;white-space:pre-wrap;background:rgba(16,185,129,.05);border:1px solid rgba(16,185,129,.2);border-radius:8px;padding:12px;">${JSON.stringify(d,null,2)}</pre>`;
  } catch(e) { document.getElementById('orResult').innerHTML=`<span style="color:#ef4444;">${e.message}</span>`; }
}
</script>
"""


# ════════════════════════════════════════════════════════════════════
# CLIENT API PROXY ENDPOINTS (forward to existing client_portal routes)
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
# ROUTE HANDLERS
# ════════════════════════════════════════════════════════════════════

@router.get("/client", response_class=HTMLResponse)
async def client_overview(request: Request):
    return HTMLResponse(_page("Overview", _topbar("🏠 Overview") + CLIENT_OVERVIEW_HTML))

@router.get("/client/orders", response_class=HTMLResponse)
async def client_orders(request: Request):
    return HTMLResponse(_page("معاملاتي", _topbar("📋 معاملاتي وطلباتي") + CLIENT_ORDERS_HTML))

@router.get("/client/pay/direct", response_class=HTMLResponse)
async def client_pay_direct(request: Request):
    return HTMLResponse(_page("Crypto Direct", _topbar("🔑 Crypto Direct Payment") + CLIENT_DIRECT_HTML))

@router.get("/client/pay/moonpay", response_class=HTMLResponse)
async def client_pay_moonpay(request: Request):
    return HTMLResponse(_page("MoonPay", _topbar("🌙 MoonPay Payment") + CLIENT_MOONPAY_HTML))

@router.get("/client/pay/circle", response_class=HTMLResponse)
async def client_pay_circle(request: Request):
    return RedirectResponse("/client", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/client/pay/onramper", response_class=HTMLResponse)
async def client_pay_onramper(request: Request):
    return HTMLResponse(_page("Onramper", _topbar("🏦 Onramper — 30+ مزود دفع") + CLIENT_ONRAMPER_HTML))
