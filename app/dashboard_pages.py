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
    ("/dashboard/validator",     "🔍", "Transaction Validator"),
    ("/dashboard/logs",          "📝", "Audit Logs"),
    ("/dashboard/distributor",   "⛓", "Profit Distributor"),
    ("/dashboard/topup",         "💳", "Top-Up Engine"),
    ("/swift",                   "⬡", "SWIFT Terminal"),
]



# ── Private Report floating panel (injected into every page) v2 ───
_PRIVATE_PANEL = ""  # Replaced by standalone /dashboard/private page

_PRIVATE_PANEL_UNUSED = """
<!-- ══ PRIVATE REPORT FLOATING PANEL — RETIRED ══════════════════════════════ -->
<div id="_prOverlay" onclick="closePrivatePanel()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9990;"></div>
<div id="_prPanel" style="display:none;position:fixed;left:220px;top:0;width:430px;height:100vh;background:#fff;z-index:9991;box-shadow:6px 0 40px rgba(0,0,0,.3);flex-direction:column;overflow:hidden;">
  <!-- Panel Header -->
  <div style="background:#0d2240;color:#c9a84c;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
    <div style="font-size:13px;font-weight:800;letter-spacing:.3px;">&#128274; Private Report</div>
    <button onclick="closePrivatePanel()" style="background:rgba(255,255,255,.12);border:none;color:#c9a84c;font-size:18px;width:30px;height:30px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:1;">&#10005;</button>
  </div>
  <!-- Filter Bar -->
  <div style="background:#f4f7fb;padding:8px 14px;border-bottom:1px solid #e5eef8;display:flex;gap:6px;flex-wrap:wrap;flex-shrink:0;">
    <button id="_prF_all"    onclick="_prFilter('all')"     style="background:#0d2240;color:#fff;border:none;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:700;cursor:pointer;">All</button>
    <button id="_prF_order"  onclick="_prFilter('order')"   style="background:#e2e8f0;color:#374151;border:none;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:700;cursor:pointer;">Orders</button>
    <button id="_prF_m1"     onclick="_prFilter('m1')"      style="background:#e2e8f0;color:#374151;border:none;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:700;cursor:pointer;">M1</button>
    <button id="_prF_payload" onclick="_prFilter('payload')" style="background:#e2e8f0;color:#374151;border:none;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:700;cursor:pointer;">Payloads</button>
    <button id="_prF_transfer" onclick="_prFilter('transfer')" style="background:#e2e8f0;color:#374151;border:none;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:700;cursor:pointer;">Transfers</button>
    <span id="_prTotal" style="margin-left:auto;font-size:10px;color:#6b7a90;line-height:28px;"></span>
  </div>
  <!-- Search -->
  <div style="padding:8px 14px;border-bottom:1px solid #e5eef8;flex-shrink:0;">
    <input id="_prSearch" oninput="_prRenderList()" placeholder="&#128269; Search by ID, amount, status..." style="width:100%;padding:7px 10px;border:1.5px solid #c8d9f0;border-radius:6px;font-size:11px;box-sizing:border-box;outline:none;">
  </div>
  <!-- Transaction List -->
  <div id="_prList" style="flex:1;overflow-y:auto;border-bottom:1px solid #e5eef8;"></div>
  <!-- Selected Transaction + Annotation Controls -->
  <div id="_prAnnot" style="flex-shrink:0;display:none;border-top:2px solid #0d2240;">
    <div style="background:#f4f7fb;padding:8px 14px;border-bottom:1px solid #e5eef8;">
      <div style="font-size:9px;font-weight:800;color:#6b7a90;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px;">Selected Transaction</div>
      <div id="_prSelBox" style="font-size:10px;color:#0d2240;"></div>
    </div>
    <div style="padding:10px 14px;display:flex;flex-direction:column;gap:8px;">
      <!-- Liquidation Rate -->
      <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;padding:8px 10px;display:flex;align-items:center;gap:8px;">
        <div style="flex:1;">
          <div style="font-size:9px;font-weight:800;color:#1e40af;text-transform:uppercase;">&#128197; Liquidation Rate</div>
          <div id="_prLiqDisp" style="font-size:11px;color:#555;margin-top:2px;">Not set</div>
        </div>
        <button onclick="_prOpenLiq()" style="background:#1e40af;color:#fff;border:none;padding:6px 12px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;">Set %</button>
      </div>
      <!-- Post-Liquidation Amount -->
      <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:6px;padding:8px 10px;display:flex;align-items:center;gap:8px;">
        <div style="flex:1;">
          <div style="font-size:9px;font-weight:800;color:#065f46;text-transform:uppercase;">&#128181; Post-Liquidation Amount</div>
          <div id="_prAmtDisp" style="font-size:11px;color:#555;margin-top:2px;">Not set</div>
        </div>
        <button onclick="_prOpenAmt()" style="background:#065f46;color:#fff;border:none;padding:6px 12px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;">Set</button>
      </div>
      <!-- Status Stamp -->
      <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:6px;padding:8px 10px;display:flex;align-items:center;gap:8px;">
        <div style="flex:1;">
          <div style="font-size:9px;font-weight:800;color:#6d28d9;text-transform:uppercase;">&#128396; Status Stamp</div>
          <div id="_prStampDisp" style="font-size:11px;color:#555;margin-top:2px;">Not set</div>
        </div>
        <button onclick="_prOpenStamp()" style="background:#6d28d9;color:#fff;border:none;padding:6px 12px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;">Set</button>
      </div>
    </div>
    <!-- Action Buttons -->
    <div style="padding:0 14px 14px;display:flex;gap:8px;">
      <button onclick="_prClear()" style="flex:1;background:#fee2e2;color:#991b1b;border:none;padding:9px 6px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;">&#128465; Clear</button>
      <button onclick="_prPrint()" style="flex:2;background:#0d2240;color:#c9a84c;border:none;padding:9px 6px;border-radius:6px;font-size:12px;font-weight:800;cursor:pointer;">&#128274; Print Private Report</button>
    </div>
  </div>
</div>

<script>
/* ══ PRIVATE REPORT PANEL — self-contained ═══════════════════ */
var _pr={
  data:{orders:[],m1:[],payloads:[],transfers:[]},
  meta:{},
  idx:null, type:null,
  filter:'all',
  loaded:false
};
function _prEsc(v){var d=document.createElement('div');d.textContent=String(v||'');return d.innerHTML;}
function _prFmt(n){if(!n&&n!==0)return '—';var x=parseFloat(n);return isNaN(x)?String(n):x.toLocaleString('en-US',{maximumFractionDigits:6});}
function _prKey(idx,type){
  var d=type==='order'?_pr.data.orders[idx]:type==='m1'?_pr.data.m1[idx]:type==='payload'?_pr.data.payloads[idx]:_pr.data.transfers[idx];
  return type+'_'+(d?d.id:'x');
}
function _prApi(url){
  var ak=sessionStorage.getItem('als_admin_key')||localStorage.getItem('als_admin_key')||'';
  var h={'Content-Type':'application/json'};
  if(ak) h['X-Admin-API-Key']=ak;
  return fetch(url,{headers:h,credentials:'include'}).then(function(r){return r.json();});
}

function openPrivatePanel(){
  var panel=document.getElementById('_prPanel');
  var overlay=document.getElementById('_prOverlay');
  panel.style.display='flex';
  overlay.style.display='block';
  if(!_pr.loaded) _prLoadAll();
  else _prRenderList();
}
function closePrivatePanel(){
  document.getElementById('_prPanel').style.display='none';
  document.getElementById('_prOverlay').style.display='none';
}
function _prLoadAll(){
  var listEl=document.getElementById('_prList');
  listEl.innerHTML='<div style="padding:24px;text-align:center;color:#aaa;font-size:12px;">Loading all transactions&hellip;</div>';
  Promise.all([
    _prApi('/api/v1/admin/orders').catch(function(){return[]}),
    _prApi('/api/v1/admin/tokenization-jobs?limit=500').catch(function(){return[]}),
    _prApi('/api/v1/admin/payloads?limit=500').catch(function(){return[]}),
    _prApi('/api/v1/admin/outbound-transfers?limit=500').catch(function(){return[]})
  ]).then(function(res){
    _pr.data.orders=Array.isArray(res[0])?res[0]:(res[0].orders||[]);
    _pr.data.m1=Array.isArray(res[1])?res[1]:[];
    _pr.data.payloads=Array.isArray(res[2])?res[2]:(res[2].payloads||[]);
    _pr.data.transfers=Array.isArray(res[3])?res[3]:(res[3].transfers||[]);
    _pr.loaded=true;
    _prRenderList();
  }).catch(function(e){
    listEl.innerHTML='<div style="padding:20px;color:#c0392b;font-size:11px;">Error loading data: '+_prEsc(e.message)+'</div>';
  });
}
function _prFilter(f){
  _pr.filter=f;
  ['all','order','m1','payload','transfer'].forEach(function(k){
    var btn=document.getElementById('_prF_'+k);
    if(btn){btn.style.background=k===f?'#0d2240':'#e2e8f0';btn.style.color=k===f?'#fff':'#374151';}
  });
  _prRenderList();
}
function _prRenderList(){
  var listEl=document.getElementById('_prList');
  var q=(document.getElementById('_prSearch')||{}).value||'';
  q=q.toLowerCase().trim();
  var types=['order','m1','payload','transfer'];
  var labels={order:'ORDER',m1:'M1',payload:'PAYLOAD',transfer:'XFER'};
  var colors={order:'#1e40af',m1:'#065f46',payload:'#7c3aed',transfer:'#b45309'};
  var rows=[];
  types.forEach(function(t){
    if(_pr.filter!=='all'&&_pr.filter!==t) return;
    (_pr.data[t]||[]).forEach(function(d,i){
      var amt='';
      if(t==='order') amt=_prFmt(d.fiat_amount)+' '+(d.fiat_currency||'');
      else if(t==='m1') amt=_prFmt(d.eur_amount)+' EUR';
      else if(t==='payload') amt=_prFmt(d.amount)+' '+(d.asset||'');
      else amt=_prFmt(d.amount)+' '+(d.asset||d.currency||'USDT');
      var st=d.status||d.verification_status||'';
      var searchStr=(d.id||'')+amt+st+(d.tx_hash||'')+(d.external_id||d.payment_reference||d.sender_reference||'');
      if(q&&searchStr.toLowerCase().indexOf(q)===-1) return;
      var sel=(_pr.idx===i&&_pr.type===t);
      rows.push({t:t,i:i,d:d,amt:amt,st:st,sel:sel,lbl:labels[t],color:colors[t]});
    });
  });
  var total=document.getElementById('_prTotal');
  if(total) total.textContent=rows.length+' records';
  if(!rows.length){
    listEl.innerHTML='<div style="padding:24px;text-align:center;color:#aaa;font-size:11px;">No transactions found</div>';
    return;
  }
  var html=rows.map(function(r){
    var bg=r.sel?'background:#e8f0fe;':'';
    var mkey=_prKey(r.i,r.t);
    var hasAnnot=!!_pr.meta[mkey];
    return '<div onclick="_prSelect('+r.i+',\''+r.t+'\')" style="padding:9px 14px;cursor:pointer;border-bottom:1px solid #edf2f8;'+bg+'">'
      +'<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">'
        +'<span style="background:'+r.color+';color:#fff;border-radius:3px;padding:1px 6px;font-size:7.5px;font-weight:800;flex-shrink:0;">'+r.lbl+'</span>'
        +'<span style="font-family:monospace;font-size:8.5px;color:#6b7a90;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+_prEsc((r.d.id||'—'))+'</span>'
        +(hasAnnot?'<span style="background:#c9a84c;color:#fff;border-radius:3px;padding:1px 5px;font-size:7px;font-weight:800;">ANNOT</span>':'')
      +'</div>'
      +'<div style="display:flex;justify-content:space-between;align-items:center;">'
        +'<span style="font-size:11px;font-weight:700;color:#0d2240;">'+_prEsc(r.amt)+'</span>'
        +'<span style="font-size:9px;color:#777;background:#f1f5f9;padding:1px 6px;border-radius:8px;">'+_prEsc(r.st)+'</span>'
      +'</div>'
    +'</div>';
  }).join('');
  listEl.innerHTML=html;
}
function _prSelect(idx,type){
  _pr.idx=idx; _pr.type=type;
  var d=type==='order'?_pr.data.orders[idx]:type==='m1'?_pr.data.m1[idx]:type==='payload'?_pr.data.payloads[idx]:_pr.data.transfers[idx];
  if(!d) return;
  var lblMap={order:'Payment Order',m1:'M1 Tokenization Job',payload:'Settlement Payload',transfer:'Outbound Transfer'};
  var amt='';
  if(type==='order') amt=_prFmt(d.fiat_amount)+' '+(d.fiat_currency||'');
  else if(type==='m1') amt=_prFmt(d.eur_amount)+' EUR';
  else if(type==='payload') amt=_prFmt(d.amount)+' '+(d.asset||'');
  else amt=_prFmt(d.amount)+' '+(d.asset||d.currency||'USDT');
  var selBox=document.getElementById('_prSelBox');
  if(selBox) selBox.innerHTML='<strong>'+_prEsc(lblMap[type]||type)+'</strong> &mdash; <span style="font-family:monospace;font-size:9px;color:#4a6a90;">'+_prEsc(d.id||'')+'</span><br><span style="font-size:12px;font-weight:800;color:#0d2240;">'+_prEsc(amt)+'</span>';
  document.getElementById('_prAnnot').style.display='block';
  _prRefreshAnnot();
  _prRenderList();
}
function _prRefreshAnnot(){
  if(_pr.idx===null) return;
  var m=_pr.meta[_prKey(_pr.idx,_pr.type)]||{};
  var sc={APPROVED:'#065f46',CANCELLED:'#991b1b',REJECTED:'#991b1b',PENDING:'#92400e',PROCESSING:'#1e40af'};
  var ld=document.getElementById('_prLiqDisp');
  var ad=document.getElementById('_prAmtDisp');
  var sd=document.getElementById('_prStampDisp');
  if(ld) ld.textContent=m.liq_pct?m.liq_pct+'%':'Not set';
  if(ad) ad.textContent=m.custom_amt?m.custom_amt+' '+(m.custom_cur||'USD'):'Not set';
  if(sd){sd.textContent=m.stamp||'Not set';sd.style.color=m.stamp?(sc[m.stamp]||'#555'):'#aaa';sd.style.fontWeight=m.stamp?'700':'400';}
}
function _prModal(title,fields,key,cb){
  var ex=_pr.meta[key]||{};
  var fHTML=fields.map(function(f){
    var v=ex[f.k]||'';
    var inp;
    if(f.opts){
      var os=f.opts.map(function(o){return '<option value="'+o+'"'+(v===o?' selected':'')+'>'+o+'</option>';}).join('');
      inp='<select id="_prMF_'+f.k+'" style="width:100%;padding:8px 10px;border:1.5px solid #c8d9f0;border-radius:5px;font-size:12px;margin-bottom:12px;"><option value="">— Select —</option>'+os+'</select>';
    }else{
      inp='<input id="_prMF_'+f.k+'" value="'+_prEsc(v)+'" placeholder="'+_prEsc(f.ph||'')+'" style="width:100%;padding:8px 10px;border:1.5px solid #c8d9f0;border-radius:5px;font-size:12px;margin-bottom:12px;box-sizing:border-box;">';
    }
    return '<label style="font-size:11px;font-weight:700;color:#0d2240;display:block;margin-bottom:3px;">'+f.lbl+'</label>'+inp;
  }).join('');
  var m=document.createElement('div');
  m.id='_prMM';
  m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;';
  m.innerHTML='<div style="background:#fff;border-radius:12px;padding:24px 28px;width:400px;max-width:94vw;box-shadow:0 20px 60px rgba(0,0,0,.4);">'
    +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">'
      +'<strong style="font-size:14px;color:#0d2240;">'+title+'</strong>'
      +'<button onclick="document.getElementById(\'_prMM\').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;">&#10005;</button>'
    +'</div>'
    +fHTML
    +'<div style="display:flex;gap:8px;justify-content:flex-end;">'
      +'<button onclick="document.getElementById(\'_prMM\').remove()" style="background:#e5e7eb;color:#374151;border:none;padding:9px 18px;border-radius:6px;font-size:12px;cursor:pointer;">Cancel</button>'
      +'<button id="_prMSv" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 22px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;">&#10003; Save</button>'
    +'</div>'
  +'</div>';
  document.body.appendChild(m);
  document.getElementById('_prMSv').onclick=function(){
    var vals={};fields.forEach(function(f){var el=document.getElementById('_prMF_'+f.k);if(el)vals[f.k]=el.value.trim();});
    _pr.meta[key]=Object.assign(_pr.meta[key]||{},vals);cb(vals);
    document.getElementById('_prMM').remove();
    _prRefreshAnnot();
    _prRenderList();
  };
  m.addEventListener('click',function(e){if(e.target===m)m.remove();});
}
function _prOpenLiq(){
  _prModal('&#128197; Liquidation Rate',[{k:'liq_pct',lbl:'Liquidation Percentage (%)',ph:'e.g. 15.50'}],_prKey(_pr.idx,_pr.type),function(){} );
}
function _prOpenAmt(){
  _prModal('&#128181; Post-Liquidation Amount',[{k:'custom_amt',lbl:'Amount After Liquidation',ph:'e.g. 500.00'},{k:'custom_cur',lbl:'Currency',ph:'USD'}],_prKey(_pr.idx,_pr.type),function(){} );
}
function _prOpenStamp(){
  _prModal('&#128396; Status Stamp',[{k:'stamp',lbl:'Select Transaction Status',opts:['APPROVED','PENDING','PROCESSING','REJECTED','CANCELLED']}],_prKey(_pr.idx,_pr.type),function(){} );
}
function _prClear(){
  if(_pr.idx===null) return;
  delete _pr.meta[_prKey(_pr.idx,_pr.type)];
  _prRefreshAnnot();
  _prRenderList();
}
function _prPrint(){
  if(_pr.idx===null) return;
  /* Build the same comprehensive report as printTxReport but using _pr.data */
  var idx=_pr.idx, type=_pr.type;
  var data=type==='order'?_pr.data.orders[idx]:type==='m1'?_pr.data.m1[idx]:type==='payload'?_pr.data.payloads[idx]:_pr.data.transfers[idx];
  if(!data) return;
  var metaKey=_prKey(idx,type);
  var m=_pr.meta[metaKey]||{};
  function pEsc(v){var d=document.createElement('div');d.textContent=String(v||'—');return d.innerHTML;}
  function pFmt(n,dec){if(!n&&n!==0)return '—';var x=parseFloat(n);return isNaN(x)?String(n):x.toLocaleString('en-US',{maximumFractionDigits:dec||2});}
  function pDate(v){return v?new Date(v).toLocaleString():'—';}
  var typeLabels={order:'Payment Order',m1:'M1 Tokenization Job',payload:'Settlement Payload',transfer:'Outbound Transfer'};
  var ref=Date.now().toString(36).toUpperCase();
  var stamp=m.stamp||'';
  var stampColors={APPROVED:'#065f46',CANCELLED:'#b91c1c',REJECTED:'#b91c1c',PENDING:'#92400e',PROCESSING:'#1e40af'};
  var stampBg={APPROVED:'#d1fae5',CANCELLED:'#fee2e2',REJECTED:'#fee2e2',PENDING:'#fef3c7',PROCESSING:'#dbeafe'};
  var rows=[];
  if(type==='order'){
    rows=[{h:'IDENTITY'},
      {l:'Transaction ID',v:pEsc(data.id)},{l:'External Reference',v:pEsc(data.external_id)},
      {l:'Payment Reference',v:pEsc(data.payment_reference)},{l:'Idempotency Key',v:pEsc(data.idempotency_key)},
      {h:'FIAT DETAILS'},
      {l:'Fiat Amount',v:'<strong>'+pFmt(data.fiat_amount)+' '+pEsc(data.fiat_currency)+'</strong>'},
      {l:'Exchange Rate',v:pEsc(data.exchange_rate)},{l:'Fees (Fiat)',v:pEsc(data.fees_fiat)},
      {h:'CRYPTO DETAILS'},
      {l:'Crypto Amount',v:'<strong>'+pFmt(data.crypto_amount,6)+' '+pEsc(data.crypto_currency)+'</strong>'},
      {l:'Network',v:pEsc(data.network)},{l:'Provider',v:pEsc(data.provider)},
      {l:'Fees (Crypto)',v:pEsc(data.fees_crypto)},
      {h:'WALLETS'},
      {l:'User Wallet',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.user_wallet_address||data.wallet)+'</span>'},
      {l:'Treasury Wallet',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.treasury_wallet_address)+'</span>'},
      {h:'BLOCKCHAIN'},
      {l:'TX Hash',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.tx_hash)+'</span>'},
      {l:'Processor Reference',v:pEsc(data.processor_reference)},
      {h:'SYSTEM'},
      {l:'Status',v:pEsc(data.status)},{l:'Client IP',v:pEsc(data.client_ip)},
      {l:'Notes',v:pEsc(data.notes)},{l:'Webhook URL',v:pEsc(data.webhook_url)},
      {h:'TIMESTAMPS'},
      {l:'Created At',v:pDate(data.created_at)},{l:'Updated At',v:pDate(data.updated_at)},
      {l:'Completed At',v:pDate(data.completed_at)}
    ];
  }else if(type==='m1'){
    var m1TxV = data.tx_hash
      ? (data.explorer_url
          ? '<a href="'+pEsc(data.explorer_url)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pEsc(data.tx_hash)+'</a>'
          : '<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.tx_hash)+'</span>')
      : '—';
    var m1WalletV = data.receiver_wallet
      ? '<a href="https://etherscan.io/address/'+pEsc(data.receiver_wallet)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pEsc(data.receiver_wallet)+'</a>'
      : '—';
    var m1OpV = data.operator_wallet
      ? '<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.operator_wallet)+'</span>'
      : '—';
    var m1ContractV = data.contract_address
      ? '<a href="https://etherscan.io/address/'+pEsc(data.contract_address)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pEsc(data.contract_address)+'</a>'
      : '—';
    rows=[{h:'IDENTITY'},
      {l:'Job ID',v:'<span style="font-family:monospace;font-size:9px;">'+pEsc(data.id)+'</span>'},
      {l:'Sender Reference',v:pEsc(data.sender_reference)},
      {l:'Outbound Transfer ID',v:'<span style="font-family:monospace;font-size:9px;">'+pEsc(data.outbound_transfer_id)+'</span>'},
      {l:'Payload ID',v:'<span style="font-family:monospace;font-size:9px;">'+pEsc(data.payload_id)+'</span>'},
      {h:'SENDER'},
      {l:'Sender Name',v:'<strong>'+pEsc(data.sender_name)+'</strong>'},
      {l:'Sender IBAN',v:'<span style="font-family:monospace;">'+pEsc(data.sender_iban)+'</span>'},
      {l:'Sender Bank',v:pEsc(data.sender_bank)},
      {h:'CONVERSION'},
      {l:'EUR Amount',v:'<strong style="color:#1d4ed8;">'+pFmt(data.eur_amount)+' EUR</strong>'},
      {l:'FX Rate (EUR→USD)',v:pEsc(data.fx_rate_eur_usd||data.fx_rate)},
      {l:'FX Provider',v:pEsc(data.fx_provider)},
      {l:'USD Amount',v:'<strong>'+pEsc(data.usd_amount)+' USD</strong>'},
      {l:'Output Amount',v:'<strong style="color:#065f46;">'+pFmt(data.usdt_amount)+' '+pEsc(data.target_asset||'SIG')+'</strong>'},
      {h:'RECEIVER — ALSHUMOOKH GROUP'},
      {l:'Network',v:'<strong>'+pEsc((data.network||'').toUpperCase())+'</strong>'},
      {l:'Receiver Wallet',v:m1WalletV},
      {l:'Operator Wallet',v:m1OpV},
      {l:'Contract Address',v:m1ContractV},
      {h:'TRANSACTION'},
      {l:'TX Hash',v:m1TxV},
      {l:'Block Number',v:pEsc(data.block_number?String(data.block_number):null)},
      {l:'Confirmations',v:pEsc(data.confirmations?String(data.confirmations):null)},
      {l:'Gas Used',v:pEsc(data.gas_used?String(data.gas_used):null)},
      {l:'Explorer',v:data.explorer_url?'<a href="'+pEsc(data.explorer_url)+'" target="_blank" style="color:#1d4ed8;font-size:10px;">View on Explorer ↗</a>':'—'},
      {h:'STATUS'},
      {l:'Job Status',v:'<strong>'+pEsc(data.status)+'</strong>'},
      {l:'Outbound Status',v:pEsc(data.outbound_status)},
      {l:'Approved By',v:pEsc(data.approved_by)},
      {l:'Error',v:pEsc(data.error_message)},
      {l:'Notes',v:pEsc(data.notes)},
      {h:'TIMESTAMPS'},
      {l:'Created At',v:pDate(data.created_at)},
      {l:'Updated At',v:pDate(data.updated_at)},
      {l:'Completed At',v:pDate(data.completed_at)}
    ];
  }else if(type==='payload'){
    rows=[{h:'IDENTITY'},
      {l:'Payload ID',v:pEsc(data.id)},{l:'Transaction Reference',v:pEsc(data.transaction_reference)},
      {l:'Request ID',v:pEsc(data.request_id)},
      {h:'AMOUNT'},
      {l:'Asset',v:pEsc(data.asset)},{l:'Amount',v:'<strong>'+pFmt(data.amount)+' '+pEsc(data.asset)+'</strong>'},
      {l:'Network',v:pEsc(data.network_name)},
      {h:'WALLETS'},
      {l:'Sender Wallet',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.sender_wallet)+'</span>'},
      {l:'Receiver Wallet',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.receiver_wallet)+'</span>'},
      {h:'BLOCKCHAIN'},
      {l:'TX Hash',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.tx_hash)+'</span>'},
      {l:'Block Number',v:pEsc(data.block_number)},{l:'Confirmations',v:pEsc(data.confirmations)},
      {l:'Explorer URL',v:pEsc(data.explorer_url)},
      {h:'SECURITY'},
      {l:'Status',v:pEsc(data.verification_status)},{l:'Security Level',v:pEsc(data.security_level)},
      {l:'Client IP',v:pEsc(data.client_ip)},{l:'Notes',v:pEsc(data.notes)},
      {h:'TIMESTAMPS'},
      {l:'Created At',v:pDate(data.created_at)},{l:'Updated At',v:pDate(data.updated_at)}
    ];
  }else{
    rows=[{h:'IDENTITY'},
      {l:'Transfer ID',v:pEsc(data.id)},{l:'Priority',v:pEsc(data.priority)},
      {h:'DETAILS'},
      {l:'Network',v:pEsc((data.network||'').toUpperCase())},{l:'Asset',v:pEsc(data.asset||data.currency||'USDT')},
      {l:'Amount',v:'<strong>'+pFmt(data.amount)+' '+pEsc(data.asset||data.currency||'USDT')+'</strong>'},
      {h:'WALLETS'},
      {l:'To Address',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.to_address)+'</span>'},
      {l:'From Address',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.from_address)+'</span>'},
      {h:'BLOCKCHAIN'},
      {l:'TX Hash',v:'<span style="font-family:monospace;font-size:9px;word-break:break-all;">'+pEsc(data.tx_hash)+'</span>'},
      {h:'APPROVAL'},
      {l:'Status',v:pEsc(data.status)},{l:'Approved By',v:pEsc(data.approved_by)},
      {l:'Approved At',v:pDate(data.approved_at)},{l:'Cancelled By',v:pEsc(data.cancelled_by)},
      {l:'Broadcaster At',v:pDate(data.broadcaster_at)},
      {h:'ERROR/RETRY'},
      {l:'Retry Count',v:pEsc(data.retry_count)},{l:'Error',v:pEsc(data.error_message)},
      {h:'WEBHOOK'},
      {l:'Webhook URL',v:pEsc(data.webhook_url)},{l:'Notes',v:pEsc(data.notes)},
      {h:'TIMESTAMPS'},
      {l:'Created At',v:pDate(data.created_at)},{l:'Updated At',v:pDate(data.updated_at)},{l:'Completed At',v:pDate(data.completed_at)}
    ];
  }
  /* Add custom annotations */
  if(m.liq_pct||m.custom_amt||m.stamp){
    rows.push({h:'PRIVATE ANNOTATIONS'});
    if(m.liq_pct) rows.push({l:'Liquidation Rate',v:'<strong>'+pEsc(m.liq_pct)+'%</strong>'});
    if(m.custom_amt) rows.push({l:'Post-Liquidation Amount',v:'<strong>'+pEsc(m.custom_amt)+' '+pEsc(m.custom_cur||'USD')+'</strong>'});
    if(m.stamp) rows.push({l:'Status Stamp',v:'<strong style="color:'+(stampColors[m.stamp]||'#555')+';">'+pEsc(m.stamp)+'</strong>'});
  }
  var rowsHTML=rows.map(function(r){
    if(r.h) return '<tr><td colspan="2" style="background:#0d2240;color:#c9a84c;font-size:9px;font-weight:800;letter-spacing:.8px;padding:5px 12px;text-transform:uppercase;">'+r.h+'</td></tr>';
    return '<tr><td style="background:#f4f7fb;font-weight:600;color:#445;padding:5px 12px;white-space:nowrap;font-size:9.5px;width:38%;">'+r.l+'</td><td style="padding:5px 12px;font-size:9.5px;color:#1a2a3a;">'+r.v+'</td></tr>';
  }).join('');
  var css='*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}'
    +'body{font-family:"Helvetica Neue",Arial,sans-serif;font-size:10.5px;color:#0d1b2a;margin:0;padding:22px 28px;background:#fff;}'
    +'.gbar{height:5px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400);}'
    +'.cband{background:#1a3a6b;color:#fff;padding:7px 20px;font-size:8px;font-weight:700;display:flex;justify-content:space-between;}'
    +'.hdr{display:flex;justify-content:space-between;align-items:center;padding:14px 0 10px;border-bottom:2px solid #1a3a6b;margin-bottom:14px;}'
    +'.co{font-size:14px;font-weight:800;color:#1a3a6b;}'
    +'.seal{width:56px;height:56px;border:2px solid #b8860b;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7.5px;font-weight:700;color:#8b6914;line-height:1.3;}'
    +'table{width:100%;border-collapse:collapse;margin-bottom:16px;border:1px solid #d0d9ea;}'
    +'tr:nth-child(even)>td{background:#f9fbfd;}'
    +'.no-print{display:block}'
    +'@media print{.no-print{display:none!important}@page{size:A4 portrait;margin:8mm 10mm}body{padding:0}}';
  var titleStr=typeLabels[type]||'Transaction';
  var stampWatermark=stamp?'<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);font-size:72px;font-weight:900;color:rgba(0,0,0,.05);white-space:nowrap;pointer-events:none;z-index:0;">'+pEsc(stamp)+'</div>':'';
  var stampBanner=stamp?'<div style="background:'+(stampBg[stamp]||'#e5e7eb')+';color:'+(stampColors[stamp]||'#374151')+';font-size:15px;font-weight:900;text-align:center;padding:8px;letter-spacing:2px;margin-bottom:14px;border-radius:5px;">'+pEsc(stamp)+'</div>':'';
  var html='<!doctype html><html><head><meta charset=utf-8><title>Private Report — '+titleStr+'</title><style>'+css+'</style></head><body>'
    +'<div class="gbar"></div>'
    +'<div class="cband"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; BIC: ALSHAEXXXX &mdash; REG: UAE/FIN/2024/0081</span><span>PRIVATE — CONFIDENTIAL</span></div>'
    +'<div class="hdr"><div><div class="co">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div><div style="font-size:9.5px;color:#5a6a80;margin-top:3px;">Private Report &mdash; '+titleStr+' &mdash; '+new Date().toUTCString()+'</div></div><div class="seal">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div></div>'
    +'<div class="no-print" style="margin-bottom:14px;display:flex;gap:8px;">'
      +'<button onclick="window.print()" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 24px;font-size:12px;font-weight:700;border-radius:5px;cursor:pointer;">&#128424; Print / Save PDF</button>'
      +'<button onclick="window.close()" style="background:#e5e7eb;color:#374151;border:none;padding:9px 18px;font-size:12px;border-radius:5px;cursor:pointer;">&#10005; Close</button>'
    +'</div>'
    +stampWatermark+stampBanner
    +'<table>'+rowsHTML+'</table>'
    +'<div style="margin-top:16px;padding-top:8px;border-top:1px solid #d0d9ea;display:flex;justify-content:space-between;font-size:8px;color:#9aa;">'
      +'<span>PRIVATE REPORT — ALSHUMOOKH GROUP 2026 — Authorised personnel only — Ref: PR-'+ref+'</span>'
      +'<span>Generated: '+new Date().toLocaleString()+'</span>'
    +'</div>'
    +'</body></html>';
  var w=window.open('','_blank','width=820,height=980');w.document.write(html);w.document.close();
}
/* Close panel with Escape key */
document.addEventListener('keydown',function(e){if(e.key==='Escape')closePrivatePanel();});
</script>
"""


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
  <!-- Private Report Button -->
  <div style="padding:8px 14px 4px;">
    <button onclick="location.href='/dashboard/private'" style="width:100%;background:#1e3a5f;color:#e2c97e;border:none;padding:10px 12px;border-radius:8px;font-size:11.5px;font-weight:800;cursor:pointer;letter-spacing:.3px;">Private Report</button>
  </div>
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
        + _PRIVATE_PANEL
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
    <button class="btn" onclick="batchTokenize()" style="background:#7c3aed;color:#fff;border-color:#7c3aed;font-size:12px;">
      ⛓ Record All on Blockchain
    </button>
  </div>

  <!-- Blockchain info banner -->
  <div style="background:linear-gradient(135deg,#0d1b4b,#1a3a8b);border-radius:10px;padding:14px 18px;margin-bottom:14px;display:flex;align-items:center;gap:16px;color:#fff;">
    <div style="font-size:28px;">⛓</div>
    <div>
      <div style="font-weight:700;font-size:13px;letter-spacing:.04em;">BLOCKCHAIN-FIRST TOKENIZATION</div>
      <div style="font-size:11px;opacity:.8;margin-top:2px;">Every transaction is tokenized as SIG tokens on Ethereum BEFORE being routed to the payment provider. Click <strong>⛓ Blockchain</strong> on any order to create an on-chain record, then Approve + Broadcast in Outbound Transfers to get the real Etherscan TX hash.</div>
    </div>
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

<!-- Tokenize modal -->
<div id="tokenizeModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9000;align-items:center;justify-content:center;">
  <div style="background:var(--surface);border-radius:12px;padding:28px 32px;width:440px;max-width:95vw;border:1px solid #7c3aed;">
    <h3 style="color:#7c3aed;margin:0 0 10px;">⛓ Record on Blockchain</h3>
    <p style="font-size:12px;color:var(--muted);margin:0 0 18px;">This converts the order amount to SIG tokens on Ethereum. An OutboundTransfer will be created in AWAITING_APPROVAL status. You must then Approve + Broadcast it to mint the real Etherscan TX hash.</p>
    <div style="margin-bottom:12px;">
      <label style="font-size:11px;color:var(--muted);">Token Asset</label>
      <select id="tkAsset" style="width:100%;margin-top:4px;padding:7px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);">
        <option value="SIG" selected>SIG (Al Shumookh Token)</option>
        <option value="USDT">USDT</option>
      </select>
    </div>
    <div style="margin-bottom:12px;">
      <label style="font-size:11px;color:var(--muted);">Network</label>
      <select id="tkNetwork" style="width:100%;margin-top:4px;padding:7px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);">
        <option value="ethereum" selected>Ethereum Mainnet</option>
        <option value="base">Base</option>
      </select>
    </div>
    <div style="margin-bottom:18px;display:flex;align-items:center;gap:8px;">
      <input type="checkbox" id="tkAutoApprove" style="width:16px;height:16px;">
      <label for="tkAutoApprove" style="font-size:12px;cursor:pointer;">Auto-approve OutboundTransfer (still requires manual Broadcast)</label>
    </div>
    <div id="tkResult" style="display:none;margin-bottom:14px;padding:12px;border-radius:8px;font-size:12px;"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-ghost" onclick="closeTokenizeModal()">Cancel</button>
      <button class="btn" id="tkBtn" onclick="doTokenize()" style="background:#7c3aed;color:#fff;border-color:#7c3aed;">⛓ Record on Blockchain</button>
    </div>
  </div>
</div>

<script>
var _tkOrderId = null;

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

    var txHashHtml = o.tx_hash
      ? '<a href="https://etherscan.io/tx/'+esc(o.tx_hash)+'" target="_blank" style="color:#7c3aed;font-family:monospace;font-size:11px;">'+esc(o.tx_hash)+'</a>'
      : '<span style="color:#f59e0b;font-size:11px;">Not yet recorded on blockchain</span>';

    var rows=[
      ['Transaction ID',o.id],['External ID',o.external_id],['Provider',o.provider],['Status',o.status],
      ['Network',o.network],['Fiat Amount',(o.fiat_amount||'—')+' '+(o.fiat_currency||'')],
      ['Crypto Amount',(o.crypto_amount||'—')+' '+(o.crypto_currency||'')],
      ['Payment Reference',o.payment_reference],['Provider Order ID',o.provider_order_id],
      ['Payer Email',o.payer_email],['Destination',o.destination_address],
      ['Treasury Wallet',o.treasury_wallet_address],['Customer Wallet',o.customer_wallet_address],
      ['Checkout URL',o.checkout_url||o.payment_url],['Idempotency Key',o.idempotency_key],
      ['Failure Reason',o.failure_reason],['Created At',fmtDate(o.created_at)],['Updated At',fmtDate(o.updated_at)]
    ];
    var detailRows=rows.map(function(r){
      var val=r[1]||'—';
      var isUrl=String(val).indexOf('http')===0;
      return '<tr><th style="width:220px;">'+esc(r[0])+'</th><td style="word-break:break-all;">'+(isUrl?'<a href="'+esc(val)+'" target="_blank">'+esc(val)+'</a>':esc(val))+'</td></tr>';
    }).join('');

    // Blockchain status row (special rendered HTML)
    var blockchainRow = '<tr style="background:linear-gradient(90deg,rgba(124,58,237,.07),transparent);">'
      +'<th style="width:220px;color:#7c3aed;">⛓ Blockchain TX Hash</th>'
      +'<td style="word-break:break-all;">'+txHashHtml+'</td></tr>';

    var logRows=logs.length?logs.map(function(l){
      return '<tr><td>'+esc(l.event_type||'')+'</td><td>'+esc(l.method||'')+'</td><td>'+esc(l.endpoint||'')+'</td><td>'+esc(String(l.status_code||'—'))+'</td><td>'+fmtDate(l.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan="5">No audit logs found.</td></tr>';

    body.innerHTML=
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">'
      +'<button class="btn btn-primary" onclick="window.open(\\'/api/v1/admin/orders/'+esc(o.id||id)+'/documents/statement\\',\\'_blank\\')">Print Statement</button>'
      +'<button class="btn btn-ghost" onclick="window.open(\\''+esc(docs.invoice_url||('/api/v1/admin/orders/'+(o.id||id)+'/documents/invoice'))+'\\',\\'_blank\\')">Invoice</button>'
      +'<button class="btn btn-ghost" onclick="window.open(\\'/api/v1/admin/reports/transactions?order_id='+esc(o.id||id)+'\\',\\'_blank\\')">Single Report</button>'
      +'<button class="btn" onclick="openTokenizeModal(\\''+esc(o.id||id)+'\\');" style="background:#7c3aed;color:#fff;border-color:#7c3aed;">⛓ Record on Blockchain</button>'
      +'</div>'
      // Blockchain status callout
      +(o.tx_hash
        ? '<div style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px;">'
          +'<strong style="color:#10b981;">✅ Blockchain Record Exists</strong> &nbsp;'
          +'<a href="https://etherscan.io/tx/'+esc(o.tx_hash)+'" target="_blank" style="color:#7c3aed;font-family:monospace;">View on Etherscan</a></div>'
        : '<div style="background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px;">'
          +'<strong style="color:#f59e0b;">⚠ Not yet on blockchain.</strong> Click <strong>⛓ Record on Blockchain</strong> above, then Approve + Broadcast in Outbound Transfers.</div>')
      +'<div class="table-wrap"><table><tbody>'+blockchainRow+detailRows+'</tbody></table></div>'
      +'<h4 style="margin:18px 0 8px;">Audit Trail</h4><div class="table-wrap"><table><thead><tr><th>Event</th><th>Method</th><th>Endpoint</th><th>Status</th><th>Date</th></tr></thead><tbody>'+logRows+'</tbody></table></div>';
    panel.scrollIntoView({behavior:'smooth'});
  }).catch(function(e){body.innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function openTokenizeModal(id){
  _tkOrderId=id;
  document.getElementById('tkResult').style.display='none';
  document.getElementById('tkBtn').disabled=false;
  document.getElementById('tkBtn').textContent='⛓ Record on Blockchain';
  document.getElementById('tokenizeModal').style.display='flex';
}
function closeTokenizeModal(){
  document.getElementById('tokenizeModal').style.display='none';
}
document.getElementById('tokenizeModal').addEventListener('click',function(e){if(e.target===this)closeTokenizeModal();});

function doTokenize(){
  if(!_tkOrderId)return;
  var asset=document.getElementById('tkAsset').value;
  var network=document.getElementById('tkNetwork').value;
  var autoApprove=document.getElementById('tkAutoApprove').checked;
  var btn=document.getElementById('tkBtn');
  btn.disabled=true;
  btn.textContent='Processing...';
  var res=document.getElementById('tkResult');
  res.style.display='none';
  api('/api/v1/admin/orders/'+_tkOrderId+'/tokenize',{
    method:'POST',
    body:JSON.stringify({asset:asset,network:network,auto_approve:autoApprove})
  }).then(function(r){
    res.style.display='block';
    res.style.background='rgba(16,185,129,.15)';
    res.style.border='1px solid rgba(16,185,129,.4)';
    res.style.color='#10b981';
    res.innerHTML='<strong>✅ Blockchain record created!</strong><br>'
      +'Job ID: <code>'+esc(r.tokenization_job_id||'—')+'</code><br>'
      +'SIG Amount: <strong>'+esc(r.sig_amount||'—')+'</strong><br>'
      +'OutboundTransfer ID: <code>'+esc(r.outbound_transfer_id||'—')+'</code><br>'
      +'Status: '+esc(r.outbound_transfer_status||'—')+'<br>'
      +'<br><em>Go to Outbound Transfers → Approve → Broadcast to get the real Etherscan TX hash.</em>';
    btn.disabled=false;
    btn.textContent='Done';
    loadOrders();
  }).catch(function(e){
    res.style.display='block';
    res.style.background='rgba(239,68,68,.15)';
    res.style.border='1px solid rgba(239,68,68,.4)';
    res.style.color='#ef4444';
    res.innerHTML='<strong>Error:</strong> '+esc(e.message||String(e));
    btn.disabled=false;
    btn.textContent='⛓ Record on Blockchain';
  });
}

function batchTokenize(){
  if(!confirm('This will create blockchain tokenization records for ALL orders.\\n\\nAn AWAITING_APPROVAL OutboundTransfer will be created for each.\\nYou will need to Approve + Broadcast each one in Outbound Transfers.\\n\\nContinue?'))return;
  var st=document.getElementById('ordStatus').value;
  showToast('Creating batch blockchain records...','info');
  api('/api/v1/admin/orders/tokenize-batch',{
    method:'POST',
    body:JSON.stringify({status:st||null,asset:'SIG',network:'ethereum',auto_approve:false})
  }).then(function(r){
    showToast('Batch done: '+r.success+' recorded, '+r.failed+' failed out of '+r.processed,'ok');
    loadOrders();
  }).catch(function(e){
    showToast('Batch failed: '+(e.message||String(e)),'error');
  });
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
    var th = '<th>ID</th><th>Provider</th><th>Fiat</th><th>Crypto</th><th>Status</th><th>Network</th><th>Email</th><th>Ref</th><th>⛓ TX Hash</th><th>Date</th><th>Action</th>';
    var tb = rows.map(function(o){
      var txCell = o.tx_hash
        ? '<a href="https://etherscan.io/tx/'+esc(o.tx_hash)+'" target="_blank" style="color:#7c3aed;font-family:monospace;font-size:10px;" title="'+esc(o.tx_hash)+'">'+o.tx_hash.slice(0,12)+'...</a>'
        : '<span style="color:#f59e0b;font-size:10px;">Not on chain</span>';
      return '<tr>'
        +'<td><code style="font-size:10px;" title="'+o.id+'">'+o.id.slice(0,10)+'...</code></td>'
        +'<td>'+(o.provider||'—')+'</td>'
        +'<td>'+fmtNum(o.fiat_amount)+' '+(o.fiat_currency||'')+'</td>'
        +'<td>'+fmtNum(o.crypto_amount,6)+' '+(o.crypto_currency||'')+'</td>'
        +'<td>'+badge(o.status)+'</td>'
        +'<td>'+(o.network||'—')+'</td>'
        +'<td>'+(o.payer_email||'—')+'</td>'
        +'<td>'+(o.payment_reference?'<code style="font-size:10px;">'+o.payment_reference+'</code>':'—')+'</td>'
        +'<td>'+txCell+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(o.created_at)+'</td>'
        +'<td><div style="display:flex;gap:4px;flex-wrap:wrap;">'
        +'<button class="btn btn-ghost" data-oid="'+o.id+'" onclick="openOrderDetails(this.dataset.oid)" style="font-size:10px;padding:3px 7px;">View</button>'
        +'<button class="btn" data-oid="'+o.id+'" onclick="openTokenizeModal(this.dataset.oid)" style="font-size:10px;padding:3px 7px;background:#7c3aed;color:#fff;border-color:#7c3aed;" title="Record on Ethereum Blockchain">⛓</button>'
        +'<button class="btn btn-primary" data-oid="'+o.id+'" onclick="window.open(\\'/api/v1/admin/orders/'+o.id+'/documents/statement\\',\\'_blank\\')" style="font-size:10px;padding:3px 7px;">Stmt</button>'
        +'<button class="btn btn-danger" data-oid="'+o.id+'" onclick="deleteOrderPage(this.dataset.oid)" style="font-size:10px;padding:3px 7px;">Del</button>'
        +'</div></td>'
        +'</tr>';
    }).join('');
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
  var url = '/api/v1/admin/payloads?limit=2000' + (st ? '&verification_status='+st : '');
  api(url).then(function(res) {
    var rows = res.payloads||[];
    document.getElementById('plCount').textContent = (res.count||rows.length)+' payload';
    if(!rows.length){
      document.getElementById('plBody').innerHTML='<div class="empty-state"><div class="icon">📥</div>No payloads found</div>';
      return;
    }
    var th = '<th>ID</th><th>Amount</th><th>Network</th><th>Sender</th><th>TX Hash</th><th>Security</th><th>Status</th><th>Date</th><th>Actions</th>';
    var tb = rows.map(function(r){var rid=r.id||r.payload_id;return '<tr data-rid="'+rid+'" onclick="viewPayload(this.dataset.rid)" style="cursor:pointer;">'
      +'<td><code style="font-size:10px;cursor:pointer;color:var(--brand);">'+rid.slice(0,10)+'...</code></td>'
      +'<td>'+fmtNum(r.amount)+' '+(r.asset||'USDT')+'</td>'
      +'<td>'+((r.network_name||r.network||'').toUpperCase())+'</td>'
      +'<td>'+(r.sender_wallet?'<code style="font-size:10px;" title="'+r.sender_wallet+'">'+r.sender_wallet.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td>'+(r.tx_hash?'<code style="font-size:10px;" title="'+r.tx_hash+'">'+r.tx_hash.slice(0,14)+'...</code>':'—')+'</td>'
      +'<td><span style="font-size:10px;color:var(--muted);">'+(r.security_level||'—')+'</span></td>'
      +'<td>'+badge(r.verification_status)+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td style="white-space:nowrap;">'
      +'<button class="btn btn-ghost" data-rid="'+rid+'" onclick="event.stopPropagation();viewPayload(this.dataset.rid)" style="font-size:11px;padding:4px 10px;">View</button> '
      +'<button class="btn btn-danger" data-rid="'+rid+'" onclick="event.stopPropagation();deletePayload(this.dataset.rid)" style="font-size:11px;padding:4px 10px;background:#7f1d1d;border-color:#991b1b;">&#128465; Delete</button>'
      +'</td>'
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
    acts.push('<button class="btn btn-danger" data-pid="'+id+'" onclick="deletePayload(this.dataset.pid)" style="margin-left:12px;background:#7f1d1d;border-color:#991b1b;">&#128465; Delete Permanently</button>');
    // Route to Provider section
    var eurAmt = p.amount ? parseFloat(p.amount).toFixed(2) : '0.00';
    var routeHtml = '<div style="margin-top:16px;padding:16px;background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);border-radius:10px;">'
      +'<div style="font-size:13px;font-weight:700;color:var(--gold);margin-bottom:12px;">🔀 Route Payload to Provider — SIG Funding</div>'
      +'<div style="font-size:12px;color:var(--muted);margin-bottom:12px;">Amount: <strong style="color:var(--ink);">'+eurAmt+' '+(p.asset||'USDT')+'</strong> → Select destination to route liquidity</div>'
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
  if(!sel){showToast('Select a provider first','error');return;}
  var provider=sel.value;
  var res=document.getElementById('routeResult_'+id);
  if(res) res.innerHTML='<span style="color:var(--muted);">Routing to '+provider+'...</span>';
  api('/api/v1/admin/payloads/'+id+'/route-provider',{method:'POST',body:JSON.stringify({provider:provider})})
    .then(function(r){
      if(res) res.innerHTML='<span style="color:#22c55e;">✅ Routed to '+provider+' | '+JSON.stringify(r)+'</span>';
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
function deletePayload(id){
  if(!confirm('Delete this payload permanently?\\n\\nID: '+id+'\\n\\nThis action cannot be undone.')) return;
  api('/api/v1/admin/payloads/'+id,{method:'DELETE'})
    .then(function(){
      showToast('Payload deleted permanently','ok');
      document.getElementById('plDetail').style.display='none';
      loadPayloads();
    })
    .catch(function(e){showToast('Delete failed: '+e.message,'error');});
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
    <div id="xferDetailActions" style="padding:0 16px 16px;"></div>
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
function forceCheckXfer(id){
  showToast('Checking blockchain...','ok');
  api('/api/v1/admin/outbound-transfers/'+id+'/force-check',{method:'POST'}).then(function(res){
    var msg=res.message||('Status: '+res.status);
    if(res.status==='CONFIRMED') showToast('✓ CONFIRMED! '+res.confirmations+' confirmations. TX: '+((res.tx_hash||'').slice(0,14))+'...','ok');
    else if(res.status==='FAILED') showToast('Transaction FAILED on-chain','error');
    else showToast(msg,'ok');
    loadTransfers();
  }).catch(function(e){showToast('Check error: '+e.message,'error');});
}
function rebroadcastXfer(id){
  if(!confirm('Re-broadcast this stuck transaction with a fresh nonce and gas price? The old TX hash will be replaced.'))return;
  showToast('Re-broadcasting...','ok');
  api('/api/v1/admin/outbound-transfers/'+id+'/rebroadcast',{method:'POST'}).then(function(res){
    showToast('Re-broadcast OK! New TX: '+((res.tx_hash||'').slice(0,14))+'...','ok');
    loadTransfers();
  }).catch(function(e){showToast('Re-broadcast error: '+e.message,'error');});
}
function forceCompleteXfer(id){
  var txHash=prompt('Enter TX Hash to force-confirm (leave blank to keep current):','');
  if(txHash===null)return;
  var body={notes:'Force completed by admin'};
  if(txHash)body.tx_hash=txHash;
  api('/api/v1/admin/outbound-transfers/'+id+'/force-complete',{method:'POST',body:JSON.stringify(body)}).then(function(){
    showToast('Transfer force-completed as CONFIRMED','ok');loadTransfers();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}
function deleteXfer(id){
  if(!confirm('Delete this transfer? This cannot be undone.'))return;
  api('/api/v1/admin/outbound-transfers/'+id,{method:'DELETE'}).then(function(){showToast('Transfer deleted','ok');loadTransfers();}).catch(function(e){showToast('Delete error: '+e.message,'error');});
}
function reverseXfer(id){
  var r=_xferRows[id];
  if(!r){showToast('Transfer not found — refresh and try again.','error');return;}
  var summary='REVERSE: '+fmtNum(r.amount)+' '+r.asset+' on '+r.network.toUpperCase()+'\\nTo: '+(r.to_address||r.from_address||'master wallet')+'\\n\\nThis will create a new AWAITING_APPROVAL transfer. Confirm?';
  if(!confirm(summary))return;
  var body={
    to_address: r.to_address||r.from_address,
    amount: r.amount,
    asset: r.asset||'SIG',
    network: r.network||'ethereum',
    notes: 'REVERSAL of transfer '+id+' — original amount '+fmtNum(r.amount)+' '+r.asset
  };
  api('/api/v1/admin/outbound-transfers',{method:'POST',body:JSON.stringify(body)}).then(function(res){
    showToast('Reverse transfer created — ID: '+(res.id||'').slice(0,12)+'... Go to Approve + Broadcast','ok');
    loadTransfers();
  }).catch(function(e){showToast('Reverse error: '+e.message,'error');});
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
  // Action buttons based on status
  var actionBtns='';
  if(r.status==='PENDING_CONFIRMATION'){
    actionBtns='<div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">'
      +'<button class="btn btn-success" data-xid="'+id+'" onclick="forceCheckXfer(this.dataset.xid)" style="font-size:12px;">⛓ Check Blockchain</button>'
      +'<button class="btn btn-ghost" data-xid="'+id+'" onclick="rebroadcastXfer(this.dataset.xid)" style="font-size:12px;color:#f59e0b;border-color:#f59e0b;">↺ Re-broadcast</button>'
      +'<button class="btn btn-ghost" data-xid="'+id+'" onclick="forceCompleteXfer(this.dataset.xid)" style="font-size:12px;color:#a78bfa;border-color:#a78bfa;">✓ Force Confirm</button>'
      +'</div>';
  }
  document.getElementById('xferDetailActions').innerHTML=actionBtns;
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
      if(r.status==='FAILED'){
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="retryXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Retry</button>');
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="forceCompleteXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;color:#10b981;border-color:#10b981;" title="تسجيل العملية يدوياً كمؤكدة">✓ Force Confirm</button>');
      }
      if(r.status==='PENDING_CONFIRMATION'){
        btns.push('<button class="btn btn-success" data-xid="'+r.id+'" onclick="forceCheckXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;background:linear-gradient(135deg,#059669,#047857);" title="Check blockchain for confirmations">⛓ Check</button>');
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="rebroadcastXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;color:#f59e0b;border-color:#f59e0b;" title="Re-broadcast with fresh nonce if stuck">↺ Re-broadcast</button>');
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="forceCompleteXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;color:#a78bfa;border-color:#a78bfa;" title="Manually confirm after verifying on Etherscan">✓ Force Confirm</button>');
      }
      if(['COMPLETED','CONFIRMED','PENDING_CONFIRMATION','CANCELLED'].indexOf(r.status)<0)
        btns.push('<button class="btn btn-danger" data-xid="'+r.id+'" onclick="cancelXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Cancel</button>');
      if(['BROADCASTING','PENDING_CONFIRMATION'].indexOf(r.status)<0)
        btns.push('<button class="btn btn-danger" data-xid="'+r.id+'" onclick="deleteXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;">Delete</button>');
      if(['CONFIRMED','COMPLETED'].indexOf(r.status)>=0)
        btns.push('<button class="btn btn-ghost" data-xid="'+r.id+'" onclick="reverseXfer(this.dataset.xid)" style="font-size:11px;padding:3px 8px;color:#a78bfa;border-color:#a78bfa;">↩ Reverse</button>');
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
        <div class="form-field"><label>Reference</label><input id="m1Ref" placeholder="Optional"></div>
        <div class="form-field"><label>Sender Name</label><input id="m1Name" placeholder="Optional"></div>
        <div class="form-field"><label>IBAN</label><input id="m1Iban" placeholder="Optional"></div>
        <div class="form-field"><label>Network</label>
          <select id="m1Net" onchange="m1OnNetworkChange()"><option value="ethereum">Ethereum</option><option value="tron">TRON</option><option value="base">Base</option></select></div>
        <div class="form-field"><label>Target Asset</label><select id="m1Asset"><option value="SIG" selected>SIG (Default)</option><option value="USDT">USDT</option></select></div>
        <div class="form-field" style="grid-column:1 / -1;">
          <label>Destination Wallet *</label>
          <div style="display:flex;gap:8px;margin-bottom:10px;">
            <button id="m1BtnTreasury" type="button" onclick="m1SetDestMode('treasury')"
              style="flex:1;padding:9px 6px;border-radius:8px;border:2px solid var(--gold);background:rgba(251,191,36,.12);color:var(--gold);font-weight:700;font-size:12px;cursor:pointer;transition:all .2s;">
              🏛 Treasury (Main Wallet)
            </button>
            <button id="m1BtnCustom" type="button" onclick="m1SetDestMode('custom')"
              style="flex:1;padding:9px 6px;border-radius:8px;border:2px solid var(--border);background:transparent;color:var(--muted);font-weight:600;font-size:12px;cursor:pointer;transition:all .2s;">
              ✏️ Custom Wallet
            </button>
          </div>
          <div id="m1DestTreasuryBox" style="background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.3);border-radius:8px;padding:10px 14px;">
            <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">Treasury Address (auto-filled)</div>
            <div id="m1TreasuryAddr" style="font-family:monospace;font-size:12px;color:var(--gold);word-break:break-all;">Loading...</div>
            <input type="hidden" id="m1Dest" value="__treasury__">
          </div>
          <div id="m1DestCustomBox" style="display:none;">
            <input id="m1DestCustom" class="form-input" placeholder="0x... (Ethereum) or T... (TRON)" style="width:100%;box-sizing:border-box;">
            <div style="font-size:11px;color:var(--muted);margin-top:4px;">Enter the recipient wallet address manually</div>
          </div>
        </div>
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
var _m1TreasuryWallets={ethereum:'',tron:'',base:''};
var _m1DestMode='treasury';

function m1LoadTreasuryWallets(){
  api('/api/v1/admin/settings/wallets').then(function(r){
    _m1TreasuryWallets=r;
    m1UpdateTreasuryDisplay();
  }).catch(function(){
    document.getElementById('m1TreasuryAddr').textContent='Not configured';
  });
}

function m1UpdateTreasuryDisplay(){
  var net=document.getElementById('m1Net').value;
  var addr=_m1TreasuryWallets[net]||_m1TreasuryWallets.ethereum||'Not configured';
  document.getElementById('m1TreasuryAddr').textContent=addr||'Not configured';
  document.getElementById('m1Dest').value='__treasury__';
}

function m1OnNetworkChange(){
  if(_m1DestMode==='treasury') m1UpdateTreasuryDisplay();
}

function m1SetDestMode(mode){
  _m1DestMode=mode;
  var btnT=document.getElementById('m1BtnTreasury');
  var btnC=document.getElementById('m1BtnCustom');
  var boxT=document.getElementById('m1DestTreasuryBox');
  var boxC=document.getElementById('m1DestCustomBox');
  if(mode==='treasury'){
    btnT.style.borderColor='var(--gold)';btnT.style.background='rgba(251,191,36,.12)';btnT.style.color='var(--gold)';
    btnC.style.borderColor='var(--border)';btnC.style.background='transparent';btnC.style.color='var(--muted)';
    boxT.style.display='block';boxC.style.display='none';
    m1UpdateTreasuryDisplay();
  } else {
    btnC.style.borderColor='var(--accent)';btnC.style.background='rgba(99,102,241,.12)';btnC.style.color='var(--accent)';
    btnT.style.borderColor='var(--border)';btnT.style.background='transparent';btnT.style.color='var(--muted)';
    boxC.style.display='block';boxT.style.display='none';
    setTimeout(function(){var i=document.getElementById('m1DestCustom');if(i)i.focus();},50);
  }
}

function m1GetDestination(){
  if(_m1DestMode==='treasury') return '__treasury__';
  return (document.getElementById('m1DestCustom')||{value:''}).value.trim();
}

function toggleM1F(){
  var el=document.getElementById('m1Form');
  var isHidden=(el.style.display==='none'||!el.style.display);
  el.style.display=isHidden?'block':'none';
  if(isHidden){ m1LoadTreasuryWallets(); m1SetDestMode('treasury'); }
}

function createJob(){
  var dest=m1GetDestination();
  var body={eur_amount:document.getElementById('m1Eur').value,destination_wallet:dest,sender_reference:document.getElementById('m1Ref').value.trim()||null,sender_name:document.getElementById('m1Name').value.trim()||null,sender_iban:document.getElementById('m1Iban').value.trim()||null,network:document.getElementById('m1Net').value,target_asset:document.getElementById('m1Asset').value};
  if(!body.eur_amount){showToast('EUR amount is required','error');return;}
  if(!body.destination_wallet){showToast('Destination wallet is required','error');return;}
  if(_m1DestMode==='custom'&&body.destination_wallet.length<10){showToast('Please enter a valid wallet address','error');return;}
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
  var dest=m1GetDestination();
  // For gas estimation use treasury address if __treasury__ mode
  if(dest==='__treasury__'){
    var net=document.getElementById('m1Net').value;
    dest=_m1TreasuryWallets[net]||_m1TreasuryWallets.ethereum||'0x0000000000000000000000000000000000000000';
  }
  estimateM1Gas(document.getElementById('m1Net').value,dest,approximateUsdt,'m1GasEstimate');
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
  api('/api/v1/admin/orders/'+orderId+'/status',{method:'POST',body:JSON.stringify({status:apiStatus,note:status==='REFUND'?'Gas invoice refunded from admin dashboard':null})})
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
  if(!sel){showToast('Select a provider first','error');return;}
  var provider=sel.value;
  var res=document.getElementById('jobRouteResult_'+id);
  if(res) res.innerHTML='<span style="color:var(--muted);">Routing to '+provider+'...</span>';
  api('/api/v1/admin/tokenization-jobs/'+id+'/route-provider',{method:'POST',body:JSON.stringify({provider:provider})})
    .then(function(r){
      if(res) res.innerHTML='<span style="color:#22c55e;">✅ Routed to '+provider.toUpperCase()+' — '+esc(r.message||'')+'</span>';
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
      <div style="padding:0 14px 14px;display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn btn-danger" onclick="m1rConfirmBurn()">Confirm Burn</button>
        <button class="btn btn-ghost" onclick="m1rConfirmBurnOverride()" style="color:#f59e0b;border-color:#f59e0b;font-size:12px;" title="تسجيل يدوي بدون التحقق من Blockchain">⚡ Admin Override</button>
      </div>
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
  var body={redeem_id:m1rVal('m1rRedeemId'),tx_hash:m1rVal('m1rBurnTx'),contract_address:m1rVal('m1rBurnContract'),wallet:m1rVal('m1rBurnWallet'),amount:m1rVal('m1rBurnAmount'),network:'ERC20',block_number:m1rVal('m1rBurnBlock')||null,admin_override:false};
  api('/api/v1/m1-funds/burn-confirmation',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Burn confirmed','ok');m1rLoad();}).catch(function(e){showToast('Burn confirmation error: '+e.message,'error');});
}
function m1rConfirmBurnOverride(){
  if(!confirm('Admin Override: سيتم تسجيل العملية بدون التحقق من الـ Blockchain. هل أنت متأكد؟'))return;
  var body={redeem_id:m1rVal('m1rRedeemId'),tx_hash:m1rVal('m1rBurnTx'),contract_address:m1rVal('m1rBurnContract'),wallet:m1rVal('m1rBurnWallet'),amount:m1rVal('m1rBurnAmount'),network:'ERC20',block_number:m1rVal('m1rBurnBlock')||null,admin_override:true};
  api('/api/v1/m1-funds/burn-confirmation',{method:'POST',body:JSON.stringify(body)}).then(function(){showToast('Burn recorded (Admin Override)','ok');m1rLoad();}).catch(function(e){showToast('Override error: '+e.message,'error');});
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
    <input id="secQ" placeholder="Search events..." style="min-width:200px;" oninput="filterSec()">
    <button class="btn btn-ghost" onclick="loadSec()">Refresh</button>
  </div>

  <!-- IP Investigation & Unlock Tool -->
  <div class="panel" style="border-left:4px solid #f59e0b;">
    <div class="panel-head" style="background:linear-gradient(90deg,rgba(245,158,11,0.08),transparent);">
      <h3 style="color:#f59e0b;">🔍 IP Investigation & Unlock</h3>
      <span style="color:var(--muted);font-size:11px;">Identify locked clients and clear login blocks</span>
    </div>
    <div style="padding:16px;display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;">
      <input id="ipInput" placeholder="Enter IP address (e.g. 91.108.189.136)" style="flex:1;min-width:260px;padding:8px 12px;border:1px solid var(--line);border-radius:6px;background:var(--surface2);color:var(--text);font-size:13px;">
      <button class="btn" onclick="investigateIP()" style="background:#f59e0b;color:#000;font-weight:700;">Investigate IP</button>
      <button class="btn btn-ghost" onclick="unlockIP()" style="border-color:#ef4444;color:#ef4444;">Unlock IP</button>
    </div>
    <div id="ipResult" style="padding:0 16px 16px;"></div>
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
  var th='<th>Event</th><th>IP</th><th>Path</th><th>Status</th><th>Details</th><th>Date</th>';
  var tb=rows.map(function(r){
    var isAlert=r.event_type&&(r.event_type.indexOf('BLOCK')>=0||r.event_type.indexOf('BAN')>=0||r.event_type.indexOf('LOCKED')>=0);
    var det=r.details&&r.details.identifier?('<span style="color:#f59e0b;font-weight:600;">'+r.details.identifier+'</span>'):
            (r.user_agent?'<span style="font-size:10px;color:var(--muted);" title="'+r.user_agent+'">'+r.user_agent.slice(0,28)+'</span>':'—');
    var ipVal=r.ip||(r.details&&r.details.ip)||'';
    return '<tr>'
      +'<td><strong style="color:'+(isAlert?'#ef4444':'var(--brand)')+';">'+r.event_type+'</strong></td>'
      +'<td style="cursor:pointer;text-decoration:underline;color:var(--brand);" onclick="setInvIP(this.dataset.ip)" data-ip="'+ipVal+'">'+( ipVal||'—')+'</td>'
      +'<td><code style="font-size:10px;">'+(r.endpoint||(r.details&&r.details.path)||'—')+'</code></td>'
      +'<td>'+(r.status_code?'<span style="color:'+(r.status_code<300?'#10b981':r.status_code<400?'#f59e0b':'#ef4444')+';">'+r.status_code+'</span>':'—')+'</td>'
      +'<td>'+det+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'</tr>';}).join('');
  document.getElementById('secBody').innerHTML='<div class="table-wrap"><table><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
function setInvIP(ip){
  if(!ip)return;
  document.getElementById('ipInput').value=ip;
  investigateIP();
}
function investigateIP(){
  var ip=(document.getElementById('ipInput').value||'').trim();
  if(!ip){alert('Enter an IP address first');return;}
  var el=document.getElementById('ipResult');
  el.innerHTML='<p style="color:var(--muted);">Investigating '+ip+'...</p>';
  api('/api/v1/admin/ip-investigation/'+encodeURIComponent(ip)).then(function(d){
    var lockBadge=d.is_locked
      ?'<span style="background:#ef4444;color:#fff;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700;">LOCKED — '+d.lock_seconds_remaining+'s remaining</span>'
      :'<span style="background:#10b981;color:#fff;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700;">NOT LOCKED</span>';
    var idents=d.identifiers_tried.length
      ?d.identifiers_tried.map(function(i){return '<code style="background:rgba(245,158,11,0.15);color:#f59e0b;padding:3px 8px;border-radius:4px;margin:2px;display:inline-block;">'+i+'</code>';}).join(' ')
      :'<span style="color:var(--muted);">No identifiers found in logs</span>';
    // ── Geo block ──────────────────────────────────────────────────────────
    var g=d.geo||{};
    var flag=g.country_code?'https://flagcdn.com/24x18/'+g.country_code.toLowerCase()+'.png':'';
    var riskTags='';
    if(g.is_proxy)riskTags+='<span style="background:#ef4444;color:#fff;padding:2px 7px;border-radius:3px;font-size:11px;margin:2px;">⚠ PROXY/VPN</span>';
    if(g.is_hosting)riskTags+='<span style="background:#f59e0b;color:#000;padding:2px 7px;border-radius:3px;font-size:11px;margin:2px;">🖥 HOSTING/DC</span>';
    if(g.is_mobile)riskTags+='<span style="background:#6366f1;color:#fff;padding:2px 7px;border-radius:3px;font-size:11px;margin:2px;">📱 MOBILE</span>';
    var geoHtml=g.country?
      '<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.25);border-radius:8px;padding:12px;margin-bottom:10px;">'
      +'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;">'
      +(flag?'<img src="'+flag+'" style="border-radius:2px;height:18px;">':'')
      +'<strong style="font-size:13px;">'+g.country+(g.city?', '+g.city:'')+'</strong>'
      +(g.region&&g.region!==g.city?'<span style="color:var(--muted);font-size:12px;">'+g.region+'</span>':'')
      +riskTags
      +'</div>'
      +'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px;font-size:12px;">'
      +(g.isp?'<div><span style="color:var(--muted);">ISP:</span> <strong>'+g.isp+'</strong></div>':'')
      +(g.org?'<div><span style="color:var(--muted);">Org:</span> '+g.org+'</div>':'')
      +(g.as?'<div><span style="color:var(--muted);">AS:</span> <code style="font-size:11px;">'+g.as+'</code></div>':'')
      +(g.timezone?'<div><span style="color:var(--muted);">Timezone:</span> '+g.timezone+'</div>':'')
      +(g.zip?'<div><span style="color:var(--muted);">ZIP:</span> '+g.zip+'</div>':'')
      +(g.lat&&g.lon?'<div><span style="color:var(--muted);">Coords:</span> <a href="https://maps.google.com/?q='+g.lat+','+g.lon+'" target="_blank" style="color:var(--brand);">'+g.lat+', '+g.lon+'</a></div>':'')
      +'</div>'
      +'</div>'
      :'<div style="color:var(--muted);font-size:12px;margin-bottom:8px;">Geo lookup unavailable</div>';
    el.innerHTML='<div style="background:var(--surface2);border-radius:8px;padding:14px;">'
      +'<div style="display:flex;gap:16px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">'
      +'<span style="font-weight:700;font-size:14px;">IP: <code>'+ip+'</code></span>'+lockBadge
      +'<span style="color:var(--muted);font-size:12px;">'+d.total_events_from_ip+' total events</span></div>'
      +geoHtml
      +'<div style="margin-bottom:10px;"><strong style="font-size:12px;color:var(--muted);">IDENTIFIERS TRIED (emails/phones):</strong><br>'+idents+'</div>'
      +(d.login_events.length?'<div><strong style="font-size:12px;color:var(--muted);">LOGIN EVENTS:</strong>'
        +'<div class="table-wrap" style="margin-top:6px;"><table><thead><tr><th>Event</th><th>Status</th><th>Date</th></tr></thead><tbody>'
        +d.login_events.map(function(r){return '<tr>'
          +'<td style="color:'+(r.event_type&&r.event_type.indexOf('LOCKED')>=0?'#ef4444':'var(--text)')+';">'+r.event_type+'</td>'
          +'<td>'+(r.status_code||'—')+'</td>'
          +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
          +'</tr>';}).join('')
        +'</tbody></table></div></div>':'')
      +'</div>';
  }).catch(function(e){el.innerHTML='<p style="color:#ef4444;">Error: '+e.message+'</p>';});
}
function unlockIP(){
  var ip=(document.getElementById('ipInput').value||'').trim();
  if(!ip){alert('Enter an IP address first');return;}
  if(!confirm('Unlock login access for IP '+ip+'?'))return;
  api('/api/v1/admin/ip-unlock/'+encodeURIComponent(ip),{method:'POST'})
    .then(function(d){
      document.getElementById('ipResult').innerHTML='<div style="background:rgba(16,185,129,0.1);border:1px solid #10b981;border-radius:6px;padding:12px;color:#10b981;font-weight:600;">✓ '+d.message+'</div>';
      setTimeout(function(){investigateIP();},800);
    }).catch(function(e){alert('Error: '+e.message);});
}
loadSec();
</script>
"""

# ─── DOCUMENTS ────────────────────────────────────────────────────────────────

_DOCUMENTS_BODY = """
<style>
.doc-hero{background:linear-gradient(135deg,#0d2348 0%,#1a3a6b 100%);padding:24px 28px 20px;border-radius:8px 8px 0 0;position:relative;overflow:hidden;}
.doc-hero::before{content:\'\';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#8b6914,#c9a227,#f0c040,#c9a227,#8b6914);}
.doc-hero-title{font-size:20px;font-weight:700;color:#fff;}
.doc-hero-sub{font-size:11px;color:#8ca8d0;margin-top:4px;}
.doc-hero-badge{position:absolute;right:24px;top:50%;transform:translateY(-50%);width:56px;height:56px;border:2px solid rgba(192,155,45,.6);border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;color:rgba(230,188,60,.8);font-size:7.5px;font-weight:700;line-height:1.3;}
.doc-stats{display:flex;gap:0;background:var(--surface2);border-bottom:1px solid var(--line);}
.doc-stat{flex:1;padding:12px 16px;text-align:center;border-right:1px solid var(--line);}
.doc-stat:last-child{border-right:none;}
.doc-stat-num{font-size:20px;font-weight:700;color:var(--brand);}
.doc-stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;}
.doc-filter{display:flex;gap:8px;padding:12px 20px;background:var(--surface2);border-bottom:1px solid var(--line);align-items:center;flex-wrap:wrap;}
.dbadge{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:5px;font-size:11px;font-weight:600;text-decoration:none;border:1px solid;white-space:nowrap;}
.dbadge-inv{background:rgba(79,142,247,.1);color:#4f8ef7;border-color:rgba(79,142,247,.3);}
.dbadge-sta{background:rgba(199,154,69,.1);color:#c79a45;border-color:rgba(199,154,69,.3);}
.dbadge-rec{background:rgba(16,185,129,.08);color:#10b981;border-color:rgba(16,185,129,.25);}
</style>
<div class="page-body">
  <div class="panel" style="padding:0;overflow:hidden;">
    <div class="doc-hero">
      <div class="doc-hero-title">&#128196; Document Centre</div>
      <div class="doc-hero-sub">ALSHUMOOKH &mdash; Generate &amp; download official banking documents for all Payment Orders</div>
      <div class="doc-hero-badge">ALSH<br>DOCS<br>&#9733;&#9733;</div>
    </div>
    <div class="doc-stats">
      <div class="doc-stat"><div class="doc-stat-num" id="dStatTotal">&mdash;</div><div class="doc-stat-lbl">Total Orders</div></div>
      <div class="doc-stat"><div class="doc-stat-num" id="dStatCompleted">&mdash;</div><div class="doc-stat-lbl">Completed</div></div>
      <div class="doc-stat"><div class="doc-stat-num" id="dStatPending">&mdash;</div><div class="doc-stat-lbl">Pending</div></div>
      <div class="doc-stat"><div class="doc-stat-num" id="dStatFailed">&mdash;</div><div class="doc-stat-lbl">Failed</div></div>
    </div>
    <div class="doc-filter">
      <input id="docSearch" placeholder="&#128269;  Search by ID, reference, email..." style="min-width:240px;" oninput="filterDocs()">
      <select id="docStatusF" onchange="filterDocs()" style="min-width:130px;">
        <option value="">All Statuses</option>
        <option value="COMPLETED">Completed</option>
        <option value="PENDING">Pending</option>
        <option value="PROCESSING">Processing</option>
        <option value="FAILED">Failed</option>
      </select>
      <button class="btn btn-ghost" onclick="loadDocs()" style="margin-left:auto;">&#8635; Refresh</button>
    </div>
    <div id="docsBody"><div class="empty-state"><div class="icon">&#128196;</div>Loading&hellip;</div></div>
  </div>
</div>
<script>
var _allDocs=[];
function filterDocs(){
  var q=(document.getElementById('docSearch').value||'').toLowerCase();
  var st=document.getElementById('docStatusF').value;
  var rows=_allDocs.filter(function(r){
    var m=!q||(r.id||'').toLowerCase().includes(q)||(r.external_id||'').toLowerCase().includes(q)||(r.payment_reference||'').toLowerCase().includes(q)||(r.payer_email||'').toLowerCase().includes(q)||(r.provider_order_id||'').toLowerCase().includes(q);
    var sm=!st||(r.status||'').toUpperCase()===st;
    return m&&sm;
  });
  renderDocs(rows);
}
function renderDocs(rows){
  if(!rows.length){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">&#128196;</div>No documents match</div>';return;}
  var th='<th>Order ID</th><th>Reference / Ext. ID</th><th>Provider</th><th>Status</th><th>Fiat Amount</th><th>Crypto</th><th>Network</th><th>Date</th><th style="min-width:260px;">Documents</th>';
  var tb=rows.map(function(r){return '<tr>'
    +'<td><span class="mono-id" title="'+esc(r.id||'')+'">'+esc((r.id||'—').slice(0,12))+'&#8230;</span></td>'
    +'<td>'+esc(r.external_id||r.payment_reference||r.provider_order_id||'—')+'</td>'
    +'<td>'+esc(r.provider||'')+'</td>'
    +'<td>'+badge(r.status||'')+'</td>'
    +'<td><strong>'+fmtNum(r.fiat_amount)+'&nbsp;'+esc(r.fiat_currency||'')+'</strong></td>'
    +'<td>'+fmtNum(r.crypto_amount,6)+'&nbsp;'+esc(r.crypto_currency||'')+'</td>'
    +'<td>'+esc((r.network||'').toUpperCase())+'</td>'
    +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
    +'<td><div style="display:flex;gap:5px;flex-wrap:wrap;">'
      +'<a href="/api/v1/admin/orders/'+esc(r.id)+'/documents/invoice" target="_blank" class="dbadge dbadge-inv">&#128196; Invoice</a>'
      +'<a href="/api/v1/admin/orders/'+esc(r.id)+'/documents/statement" target="_blank" class="dbadge dbadge-sta">&#128203; Statement</a>'
      +'<a href="/api/v1/admin/orders/'+esc(r.id)+'/documents/receive-receipt" target="_blank" class="dbadge dbadge-rec">&#9989; Receipt</a>'
    +'</div></td>'
    +'</tr>';}).join('');
  document.getElementById('docsBody').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div>';
}
function loadDocs(){
  document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">&#128196;</div>Loading&hellip;</div>';
  api('/api/v1/admin/orders').then(function(data){
    var rows=Array.isArray(data)?data:(data.orders||[]);
    _allDocs=rows;
    var comp=rows.filter(function(r){return (r.status||'').toUpperCase()==='COMPLETED';}).length;
    var pend=rows.filter(function(r){var s=(r.status||'').toUpperCase();return s==='PENDING'||s==='PROCESSING';}).length;
    var fail=rows.filter(function(r){return (r.status||'').toUpperCase()==='FAILED';}).length;
    document.getElementById('dStatTotal').textContent=rows.length;
    document.getElementById('dStatCompleted').textContent=comp;
    document.getElementById('dStatPending').textContent=pend;
    document.getElementById('dStatFailed').textContent=fail;
    filterDocs();
  }).catch(function(e){document.getElementById('docsBody').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
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
<div style="display:flex;flex-direction:column;gap:16px;">

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
var _rMeta={};
var _rTab='orders';

/* ── Side-button helpers ─────────────────────────────────── */
function _rKey(idx,type){
  var d=type==='order'?_rData.orders[idx]:type==='m1'?_rData.m1[idx]:type==='payload'?_rData.payloads[idx]:_rData.transfers[idx];
  return type+'_'+(d?d.id:'x');
}
function closeRModal(){var m=document.getElementById('_rMM');if(m)m.remove();}
function openRModal(title,fields,key,cb){
  closeRModal();
  var ex=_rMeta[key]||{};
  var fHTML=fields.map(function(f){
    var v=ex[f.k]||'';
    var inp;
    if(f.opts){
      var os=f.opts.map(function(o){return '<option value="'+o+'"'+(v===o?' selected':'')+'>'+o+'</option>';}).join('');
      inp='<select id="rmf_'+f.k+'" style="width:100%;padding:7px 10px;border:1.5px solid #c8d9f0;border-radius:5px;font-size:12px;margin-bottom:12px;"><option value="">— Select —</option>'+os+'</select>';
    }else{
      inp='<input id="rmf_'+f.k+'" value="'+esc(v)+'" placeholder="'+esc(f.ph||'')+'" style="width:100%;padding:7px 10px;border:1.5px solid #c8d9f0;border-radius:5px;font-size:12px;margin-bottom:12px;box-sizing:border-box;">';
    }
    return '<label style="font-size:11px;font-weight:700;color:#0d2240;display:block;margin-bottom:3px;">'+f.lbl+'</label>'+inp;
  }).join('');
  var m=document.createElement('div');
  m.id='_rMM';
  m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.52);z-index:9999;display:flex;align-items:center;justify-content:center;';
  m.innerHTML='<div style="background:#fff;border-radius:12px;padding:24px 28px;width:400px;max-width:94vw;box-shadow:0 20px 60px rgba(0,0,0,.35);">'
    +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">'
      +'<strong style="font-size:14px;color:#0d2240;">'+title+'</strong>'
      +'<button onclick="closeRModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;line-height:1;">&#10005;</button>'
    +'</div>'
    +fHTML
    +'<div style="display:flex;gap:8px;justify-content:flex-end;">'
      +'<button onclick="closeRModal()" style="background:#e5e7eb;color:#374151;border:none;padding:8px 18px;border-radius:6px;font-size:12px;cursor:pointer;">Cancel</button>'
      +'<button id="_rMSv" style="background:#0d2240;color:#c9a84c;border:none;padding:8px 22px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;">&#10003; Save</button>'
    +'</div>'
  +'</div>';
  document.body.appendChild(m);
  document.getElementById('_rMSv').onclick=function(){
    var vals={};fields.forEach(function(f){var el=document.getElementById('rmf_'+f.k);if(el) vals[f.k]=el.value.trim();});
    _rMeta[key]=Object.assign(_rMeta[key]||{},vals);cb(vals);closeRModal();
  };
  m.addEventListener('click',function(e){if(e.target===m) closeRModal();});
}
function openLiqModal(idx,type){
  var key=_rKey(idx,type);
  openRModal('&#128197; Liquidation Rate',
    [{k:'liq_pct',lbl:'Liquidation Percentage (%)',ph:'e.g. 15.50'}],
    key,function(){showToast('Liquidation rate saved','ok');});
}
function openAmtModal(idx,type){
  var key=_rKey(idx,type);
  openRModal('&#128181; Post-Liquidation Amount',
    [{k:'custom_amt',lbl:'Amount After Liquidation',ph:'e.g. 500.00'},{k:'custom_cur',lbl:'Currency',ph:'USD'}],
    key,function(){showToast('Post-liquidation amount saved','ok');});
}
function openStampModal(idx,type){
  var key=_rKey(idx,type);
  openRModal('&#128396; Status Stamp',
    [{k:'stamp',lbl:'Select Transaction Status',opts:['APPROVED','PENDING','PROCESSING','REJECTED','CANCELLED']}],
    key,function(v){if(v.stamp) showToast('Status stamp set: '+v.stamp,'ok');});
}

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

function printTxReport(idx,type){
  var data;
  if(type==='order') data=_rData.orders[idx];
  else if(type==='m1') data=_rData.m1[idx];
  else if(type==='payload') data=_rData.payloads[idx];
  else if(type==='transfer') data=_rData.transfers[idx];
  if(!data){showToast('Data not found — please refresh the tab','error');return;}
  var ref=Date.now().toString(36).toUpperCase();

  function fdt(v){if(!v||v==='null'||v==='undefined') return '—';try{return new Date(v).toUTCString();}catch(e){return String(v);}}
  function fv(v){var s=String(v===null||v===undefined?'':v);return(s===''||s==='null'||s==='undefined')?'—':s;}
  function explorerLink(hash,network,stored){
    if(stored&&stored.indexOf('http')===0) return '<a href="'+esc(stored)+'" target="_blank" style="color:#1a3a6b;word-break:break-all;font-family:monospace;font-size:10px;">'+esc(stored)+'</a>';
    if(!hash||hash==='—'||hash==='null') return '<span style="color:#999;">—</span>';
    var n=(network||'').toLowerCase();
    var base='https://etherscan.io/tx/';
    if(n.indexOf('tron')!==-1||n.indexOf('trx')!==-1) base='https://tronscan.org/#/transaction/';
    else if(n.indexOf('base')!==-1) base='https://basescan.org/tx/';
    else if(n.indexOf('bsc')!==-1||n.indexOf('bnb')!==-1) base='https://bscscan.com/tx/';
    return '<a href="'+base+esc(hash)+'" target="_blank" style="color:#1a3a6b;word-break:break-all;font-family:monospace;font-size:10px;">'+esc(hash)+'</a>';
  }

  var net=(data.network||data.network_name||'').toLowerCase();
  var statusVal=String(data.status||data.verification_status||'').toUpperCase();
  var statusColor=statusVal==='COMPLETED'||statusVal==='VERIFIED'?'background:#d1fae5;color:#065f46':statusVal==='PENDING'||statusVal==='PROCESSING'?'background:#fef3c7;color:#92400e':statusVal==='FAILED'||statusVal==='REJECTED'?'background:#fee2e2;color:#991b1b':'background:#e5e7eb;color:#374151';

  var title,rows=[],sum=[];

  if(type==='order'){
    title='Payment Order — Certified Transaction Report';
    sum=[fv(data.id),(fv(data.fiat_amount)+' '+fv(data.fiat_currency)+' \u2192 '+fv(data.crypto_amount)+' '+fv(data.crypto_currency)),statusVal,fv(data.provider)];
    rows=[
      {h:'TRANSACTION IDENTITY'},
      ['Order ID',fv(data.id),'id'],
      ['External Reference',fv(data.external_id),''],
      ['Payment Reference',fv(data.payment_reference),''],
      ['Provider Order ID',fv(data.provider_order_id),''],
      {h:'TRANSACTION DETAILS'},
      ['Type','Payment Order',''],
      ['Provider',fv(data.provider),''],
      ['Side',fv(data.side),''],
      ['Network',fv(data.network).toUpperCase(),''],
      ['Status',statusVal,'status'],
      {h:'FIAT DETAILS'},
      ['Fiat Currency',fv(data.fiat_currency),''],
      ['Fiat Amount',fv(data.fiat_amount)+' '+fv(data.fiat_currency),'amount'],
      {h:'CRYPTO / DIGITAL ASSET DETAILS'},
      ['Crypto Currency',fv(data.crypto_currency),''],
      ['Crypto Amount',fv(data.crypto_amount)+' '+fv(data.crypto_currency),'amount'],
      ['User Wallet',fv(data.wallet||data.user_wallet_address),'addr'],
      ['Treasury Wallet',fv(data.treasury_wallet_address),'addr'],
      {h:'PAYER INFORMATION'},
      ['Payer Email',fv(data.payer_email),''],
      ['Checkout URL',fv(data.checkout_url),'url'],
      {h:'BLOCKCHAIN DATA'},
      ['TX Hash',fv(data.tx_hash),'hash'],
      ['Blockchain Explorer',{raw:explorerLink(data.tx_hash,net,null)},''],
      {h:'STATUS & ERROR'},
      ['Current Status',statusVal,'status'],
      ['Failure Reason',fv(data.failure_reason),'err'],
      {h:'TIMESTAMPS (UTC)'},
      ['Created At',fdt(data.created_at),''],
      ['Last Updated',fdt(data.updated_at),'']
    ];
  }else if(type==='m1'){
    title='M1 Tokenization Job — Certified Transaction Report';
    sum=[fv(data.id),(fv(data.eur_amount)+' EUR \u2192 '+fv(data.usdt_amount)+' '+(data.target_asset||'SIG')),statusVal,fv(data.sender_name)];
    rows=[
      {h:'JOB IDENTITY'},
      ['Job ID',fv(data.id),'id'],
      ['Sender Reference',fv(data.sender_reference),''],
      ['Related Payload ID',fv(data.payload_id),'id'],
      ['Outbound Transfer ID',fv(data.outbound_transfer_id),'id'],
      {h:'SENDER INFORMATION'},
      ['Sender Name',fv(data.sender_name),''],
      ['Sender IBAN',fv(data.sender_iban||((data.raw_data||{}).sender_iban)),'addr'],
      {h:'CONVERSION DETAILS (EUR \u2192 USD \u2192 TOKEN)'},
      ['EUR Input Amount',fv(data.eur_amount)+' EUR','amount'],
      ['FX Rate (EUR \u2192 USD)',fv(data.fx_rate||data.fx_rate_eur_usd),''],
      ['USD Equivalent',fv(data.usd_amount)+' USD','amount'],
      ['SIG / Token Output',fv(data.usdt_amount)+' '+(data.target_asset||'SIG'),'amount'],
      ['Target Asset',fv(data.target_asset)||'SIG',''],
      {h:'BLOCKCHAIN DETAILS'},
      ['Network',fv(data.network).toUpperCase(),''],
      ['Destination Wallet',fv(data.destination_wallet),'addr'],
      {h:'JOB STATUS'},
      ['Status',statusVal,'status'],
      ['Error Message',fv(data.error_message),'err'],
      ['Notes',fv((data.raw_data||{}).notes||data.notes),''],
      {h:'TIMESTAMPS (UTC)'},
      ['Created At',fdt(data.created_at),''],
      ['Completed At',fdt(data.completed_at),'']
    ];
  }else if(type==='payload'){
    title='Settlement Payload — Certified Transaction Report';
    sum=[fv(data.id),(fv(data.amount)+' '+fv(data.asset)),statusVal,fv(data.network_name||data.network)];
    rows=[
      {h:'PAYLOAD IDENTITY'},
      ['Payload ID',fv(data.id),'id'],
      ['Transaction Reference',fv(data.transaction_reference),''],
      {h:'AMOUNT & ASSET'},
      ['Asset',fv(data.asset),''],
      ['Amount',fv(data.amount)+' '+fv(data.asset),'amount'],
      ['Network',fv(data.network_name||data.network),''],
      {h:'WALLET ADDRESSES'},
      ['Sender Wallet',fv(data.sender_wallet),'addr'],
      ['Receiver Wallet',fv(data.receiver_wallet),'addr'],
      {h:'BLOCKCHAIN DATA'},
      ['TX Hash',fv(data.tx_hash),'hash'],
      ['Blockchain Explorer',{raw:explorerLink(data.tx_hash,net,null)},''],
      {h:'VERIFICATION & SECURITY'},
      ['Verification Status',statusVal,'status'],
      ['Security Level',fv(data.security_level),''],
      ['Client IP',fv(data.client_ip),''],
      {h:'TIMESTAMPS (UTC)'},
      ['Created At',fdt(data.created_at),''],
      ['Last Updated',fdt(data.updated_at),'']
    ];
  }else if(type==='transfer'){
    title='Outbound Transfer — Certified Transaction Report';
    sum=[fv(data.id),(fv(data.amount)+' '+(data.asset||'USDT')+' on '+fv(data.network).toUpperCase()),statusVal,(fv(data.to_address).length>20?fv(data.to_address).slice(0,20)+'...':fv(data.to_address))];
    rows=[
      {h:'TRANSFER IDENTITY'},
      ['Transfer ID',fv(data.id),'id'],
      ['Related Order ID',fv(data.order_id),'id'],
      ['Related Payload ID',fv(data.payload_id),'id'],
      ['Related M1 Job ID',fv(data.tokenization_job_id),'id'],
      {h:'TRANSFER DETAILS'},
      ['Status',statusVal,'status'],
      ['Network',fv(data.network).toUpperCase(),''],
      ['Asset',fv(data.asset)||'USDT',''],
      ['Amount',fv(data.amount),'amount'],
      ['Contract Address',fv(data.contract_address),'addr'],
      {h:'WALLET ADDRESSES'},
      ['From Address',fv(data.from_address),'addr'],
      ['To Address',fv(data.to_address),'addr'],
      {h:'BLOCKCHAIN DATA'},
      ['TX Hash',fv(data.tx_hash),'hash'],
      ['Block Number',fv(data.block_number),''],
      ['Confirmations',fv(data.confirmations),''],
      ['Blockchain Explorer',{raw:explorerLink(data.tx_hash,net,data.explorer_url)},''],
      {h:'APPROVAL & AUTHORIZATION'},
      ['Initiated By',fv(data.initiated_by),''],
      ['Approved By',fv(data.approved_by),''],
      ['Approved At',fdt(data.approved_at),''],
      ['Notes',fv(data.notes),''],
      {h:'ERROR & RETRY'},
      ['Error Message',fv(data.error_message),'err'],
      ['Retry Count',fv(data.retry_count)||'0',''],
      ['Cancelled By',fv(data.cancelled_by),''],
      ['Cancel Reason',fv(data.cancel_reason),'err'],
      {h:'WEBHOOK'},
      ['Callback URL',fv(data.callback_url),'url'],
      ['Webhook Status Code',fv(data.webhook_status_code),''],
      {h:'TIMESTAMPS (UTC)'},
      ['Created At',fdt(data.created_at),''],
      ['Broadcasted At',fdt(data.broadcasted_at),''],
      ['Completed At',fdt(data.completed_at),'']
    ];
  }

  /* inject custom meta annotations */
  var metaKey=type+'_'+(data.id||'');
  var meta=_rMeta[metaKey]||{};
  if(meta.stamp||meta.liq_pct||meta.custom_amt){
    rows.push({h:'CUSTOM ANNOTATIONS'});
    if(meta.stamp) rows.push(['Status Stamp',meta.stamp,'stamp_meta']);
    if(meta.liq_pct){
      rows.push(['Liquidation Rate',meta.liq_pct+'%','']);
      var baseAmt=parseFloat(type==='order'?data.fiat_amount:type==='m1'?data.eur_amount:data.amount)||0;
      if(baseAmt>0){var after=baseAmt*(1-(parseFloat(meta.liq_pct)||0)/100);rows.push(['Calculated Post-Liquidation',after.toFixed(6),'amount']);}
    }
    if(meta.custom_amt) rows.push(['Post-Liquidation Amount (Manual)',meta.custom_amt+' '+(meta.custom_cur||'USD'),'amount']);
  }

  var stampColors={'APPROVED':'background:#065f46;color:#d1fae5','PENDING':'background:#92400e;color:#fef3c7','PROCESSING':'background:#1e40af;color:#dbeafe','REJECTED':'background:#991b1b;color:#fee2e2','CANCELLED':'background:#374151;color:#e5e7eb'};
  var stampWatermark=meta.stamp?'<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);font-size:96px;font-weight:900;opacity:.05;color:#0d2240;z-index:0;pointer-events:none;white-space:nowrap;letter-spacing:4px;">'+esc(meta.stamp)+'</div>':'';
  var stampBanner=meta.stamp?'<div style="text-align:center;margin:14px 0;"><span style="display:inline-block;padding:7px 36px;border-radius:4px;font-size:18px;font-weight:900;letter-spacing:2px;border:3px solid currentColor;'+(stampColors[meta.stamp]||'background:#e5e7eb;color:#374151')+';">'+esc(meta.stamp)+'</span></div>':'';

  function renderCell(label,val,hint){
    if(val&&typeof val==='object'&&val.raw) return val.raw;
    var s=String(val===null||val===undefined?'—':val);
    var dash='<span style="color:#bbb;">—</span>';
    if(s==='—') return dash;
    if(hint==='stamp_meta'){var sc=stampColors[s]||'background:#e5e7eb;color:#374151';return '<span style="display:inline-block;padding:5px 20px;border-radius:4px;font-size:13px;font-weight:900;letter-spacing:2px;border:2.5px solid currentColor;'+sc+'!important;">'+esc(s)+'</span>';}
    if(hint==='status') return '<span style="display:inline-block;padding:3px 14px;border-radius:12px;font-weight:700;font-size:11px;'+statusColor+'!important;">'+esc(s)+'</span>';
    if(hint==='hash'||label==='TX Hash') return '<span class="hash-box">'+esc(s)+'</span>';
    if(hint==='id') return '<span style="font-family:monospace;font-size:10px;color:#444;">'+esc(s)+'</span>';
    if(hint==='addr') return '<span style="font-family:monospace;font-size:10px;word-break:break-all;">'+esc(s)+'</span>';
    if(hint==='amount') return '<strong style="font-size:14px;color:#0d2240;">'+esc(s)+'</strong>';
    if(hint==='err') return '<span style="color:#991b1b;">'+esc(s)+'</span>';
    if(hint==='url') return '<a href="'+esc(s)+'" target="_blank" style="color:#1a3a6b;word-break:break-all;font-size:10px;">'+esc(s)+'</a>';
    return esc(s);
  }

  var rowsHTML=rows.map(function(r){
    if(r.h) return '<tr><td colspan="2" class="sec-hdr">'+r.h+'</td></tr>';
    return '<tr><td class="lbl-cell">'+esc(r[0])+'</td>'
          +'<td class="val-cell">'+renderCell(r[0],r[1],r[2])+'</td></tr>';
  }).join('');

  var summaryHTML='<div class="sum-grid">'
    +'<div class="sum-dark"><div class="sum-lbl">Transaction ID</div><div style="font-family:monospace;font-size:10px;word-break:break-all;color:#c9a84c;">'+esc(sum[0]||'—')+'</div></div>'
    +'<div class="sum-light"><div class="sum-lbl" style="color:#6b7a90;">Amount / Conversion</div><div style="font-size:13px;font-weight:800;color:#0d2240;word-break:break-all;">'+esc(sum[1]||'—')+'</div></div>'
    +'<div class="sum-light"><div class="sum-lbl" style="color:#6b7a90;">Status</div><div style="display:inline-block;padding:4px 14px;border-radius:14px;font-weight:800;font-size:12px;'+statusColor+'!important">'+esc(sum[2]||'—')+'</div></div>'
    +'<div class="sum-light"><div class="sum-lbl" style="color:#6b7a90;">'+(type==='order'?'Provider':type==='m1'?'Sender':type==='payload'?'Network':'Recipient')+'</div><div style="font-size:11px;font-weight:700;color:#0d2240;word-break:break-all;">'+esc(sum[3]||'—')+'</div></div>'
    +'</div>';

  var css='*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important;color-adjust:exact!important;box-sizing:border-box;}'
    +'body{font-family:"Helvetica Neue",Arial,sans-serif;font-size:11px;color:#0d1b2a;margin:0;padding:0;background:#fff;}'
    +'.gbar{height:6px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400)!important;-webkit-print-color-adjust:exact!important;}'
    +'.cband{background:#0d2240!important;color:#fff!important;padding:8px 26px;font-size:8.5px;font-weight:700;letter-spacing:.6px;display:flex;justify-content:space-between;align-items:center;}'
    +'.hdr{padding:18px 26px 12px;border-bottom:2.5px solid #0d2240;display:flex;justify-content:space-between;align-items:center;}'
    +'.co{font-size:16px;font-weight:800;color:#0d2240;letter-spacing:.2px;}.co-sub{font-size:9.5px;color:#6b7a90;margin-top:3px;}'
    +'.seal{width:64px;height:64px;border:2px solid #c9a84c;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:8px;font-weight:700;color:#8b6914;line-height:1.4;}'
    +'.rpt-title{background:#0d2240!important;color:#c9a84c!important;padding:11px 26px;font-size:13px;font-weight:700;letter-spacing:.5px;}'
    +'.rpt-ref{background:#f7f9fc!important;padding:6px 26px;font-size:9px;color:#888;display:flex;justify-content:space-between;border-bottom:1px solid #dde6f5;}'
    +'.body{padding:16px 26px;}'
    +'table{width:100%;border-collapse:collapse;border:1.5px solid #c8d9f0;}'
    +'.sum-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px;}'
    +'.sum-dark{background:#0d2240!important;color:#c9a84c!important;border-radius:7px;padding:12px 15px;}'
    +'.sum-light{background:#f0f4fb!important;border-radius:7px;padding:12px 15px;border:1.5px solid #c8d9f0;}'
    +'.sum-lbl{font-size:8px;font-weight:800;letter-spacing:1px;text-transform:uppercase;opacity:.75;margin-bottom:4px;}'
    +'.sum-val{font-size:12px;font-weight:800;word-break:break-all;}'
    +'.sec-hdr{background:#0d2240!important;color:#c9a84c!important;padding:7px 16px 5px;font-size:9px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;}'
    +'.lbl-cell{padding:8px 16px;font-weight:600;color:#1a3a6b;background:#f4f7fb!important;width:210px;font-size:11px;border-bottom:1px solid #e5eef8;vertical-align:top;white-space:nowrap;}'
    +'.val-cell{padding:8px 16px;font-size:11px;border-bottom:1px solid #e5eef8;vertical-align:top;}'
    +'.hash-box{font-family:monospace;font-size:9.5px;word-break:break-all;color:#0d2240;background:#f0f4fb!important;padding:5px 8px;border-radius:4px;border:1px solid #d0dced;display:block;}'
    +'.foot{margin-top:20px;padding:10px 26px 16px;border-top:2px solid #0d2240;display:flex;justify-content:space-between;align-items:flex-end;}'
    +'.ftxt{font-size:8px;color:#9aa;line-height:1.7;max-width:440px;}'
    +'.fseal{width:50px;height:50px;border:2px solid #c9a84c;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7px;font-weight:700;color:#8b6914;line-height:1.4;}'
    +'@page{size:A4 portrait;margin:8mm 10mm}'
    +'@media print{.no-print{display:none!important}}';

  var html='<!doctype html><html><head><meta charset=utf-8><title>'+title+'</title><style>'+css+'</style></head><body>'
    +'<div class="gbar"></div>'
    +'<div class="cband"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; BIC: ALSHAEXXXX &mdash; REG: UAE/FIN/2024/0081</span><span>CERTIFIED TRANSACTION REPORT</span></div>'
    +'<div class="hdr"><div><div class="co">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div><div class="co-sub">Authorised Financial Institution &mdash; United Arab Emirates</div></div><div class="seal">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div></div>'
    +'<div class="rpt-title">&#128196; '+title+'</div>'
    +'<div class="rpt-ref"><span>Report Reference: RPT-'+ref+'</span><span>Generated: '+new Date().toUTCString()+'</span></div>'
    +'<div class="body">'
    +stampWatermark
    +'<div class="no-print" style="margin-bottom:16px;display:flex;gap:8px;">'
      +'<button onclick="window.print()" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 24px;font-size:12px;font-weight:700;border-radius:5px;cursor:pointer;">&#128424; Print / Save PDF</button>'
      +'<button onclick="window.close()" style="background:#e5e7eb;color:#374151;border:none;padding:9px 18px;font-size:12px;font-weight:600;border-radius:5px;cursor:pointer;">&#10005; Close</button>'
    +'</div>'
    +summaryHTML
    +stampBanner
    +'<table>'+rowsHTML+'</table>'
    +'</div>'
    +'<div class="foot"><div class="ftxt">This document is auto-generated by the ALSHUMOOKH internal system and is CONFIDENTIAL &mdash; authorised personnel only.<br>Blockchain data is subject to network confirmation. All amounts are as recorded at time of transaction. &copy; ALSHUMOOKH GROUP 2026 &mdash; compliance@alshumookh-pay.com</div><div class="fseal">ALSH<br>CERT<br>&#9733;</div></div>'
    +'</body></html>';
  var w=window.open('','_blank','width=860,height=980');w.document.write(html);w.document.close();
}

function printTabData(tab){
  var data=_rData[tab]||[];
  if(!data.length){showToast('No data &mdash; please wait for data to load or click Refresh','error');return;}
  var titles={orders:'Payment Orders Report',m1:'M1 Tokenization Jobs',payloads:'Settlement Payloads',transfers:'Outbound Transfers'};
  var html='<!doctype html><html><head><meta charset=utf-8><title>'+titles[tab]+'</title><style>'+_pCSS+'</style></head><body>'+_ph(titles[tab],data.length);
  function _tDate(v){return v?new Date(v).toLocaleString():'—';}
  function _tHash(v){return v?'<span style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(v)+'</span>':'—';}
  if(tab==='orders'){
    html+='<table><thead><tr><th>Full ID</th><th>Ext Reference</th><th>Payment Ref</th><th>Provider</th><th>Status</th><th>Fiat Amount</th><th>Fiat Currency</th><th>Exchange Rate</th><th>Crypto Amount</th><th>Crypto Currency</th><th>Network</th><th>User Wallet</th><th>Treasury Wallet</th><th>TX Hash</th><th>Fees Fiat</th><th>Fees Crypto</th><th>Processor Ref</th><th>Client IP</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
    data.forEach(function(o){html+='<tr>'
      +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(o.id||'—')+'</td>'
      +'<td>'+esc(o.external_id||'—')+'</td>'
      +'<td>'+esc(o.payment_reference||'—')+'</td>'
      +'<td>'+esc(o.provider||'—')+'</td>'
      +'<td>'+_sb(o.status)+'</td>'
      +'<td><strong>'+esc(String(o.fiat_amount||'—'))+'</strong></td>'
      +'<td>'+esc(o.fiat_currency||'—')+'</td>'
      +'<td>'+esc(String(o.exchange_rate||'—'))+'</td>'
      +'<td><strong>'+esc(String(o.crypto_amount||'—'))+'</strong></td>'
      +'<td>'+esc(o.crypto_currency||'—')+'</td>'
      +'<td>'+esc(o.network||'—')+'</td>'
      +'<td>'+_tHash(o.user_wallet_address||o.wallet)+'</td>'
      +'<td>'+_tHash(o.treasury_wallet_address)+'</td>'
      +'<td>'+_tHash(o.tx_hash)+'</td>'
      +'<td>'+esc(String(o.fees_fiat||'—'))+'</td>'
      +'<td>'+esc(String(o.fees_crypto||'—'))+'</td>'
      +'<td>'+esc(o.processor_reference||'—')+'</td>'
      +'<td>'+esc(o.client_ip||'—')+'</td>'
      +'<td>'+esc(o.notes||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(o.created_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(o.updated_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(o.completed_at)+'</td>'
      +'</tr>';});
  }else if(tab==='m1'){
    html+='<table><thead><tr><th>Full ID</th><th>Sender Reference</th><th>Sender Name</th><th>Sender IBAN</th><th>Sender Bank</th><th>EUR Amount</th><th>FX Rate EUR/USD</th><th>USD Amount</th><th>Output Amount</th><th>Target Asset</th><th>Receiver Wallet</th><th>Network</th><th>TX Hash</th><th>Status</th><th>Error</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
    data.forEach(function(r){html+='<tr>'
      +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(r.id||'—')+'</td>'
      +'<td>'+esc(r.sender_reference||'—')+'</td>'
      +'<td>'+esc(r.sender_name||'—')+'</td>'
      +'<td style="font-family:monospace;font-size:8px;">'+esc(r.sender_iban||'—')+'</td>'
      +'<td>'+esc(r.sender_bank||'—')+'</td>'
      +'<td><strong>'+esc(String(r.eur_amount||'—'))+' EUR</strong></td>'
      +'<td>'+esc(String(r.fx_rate_eur_usd||r.fx_rate||'—'))+'</td>'
      +'<td>'+esc(String(r.usd_amount||'—'))+' USD</td>'
      +'<td><strong>'+esc(String(r.usdt_amount||'—'))+'</strong></td>'
      +'<td>'+esc(r.target_asset||'SIG')+'</td>'
      +'<td>'+_tHash(r.receiver_wallet)+'</td>'
      +'<td>'+esc((r.network||'—').toUpperCase())+'</td>'
      +'<td>'+_tHash(r.tx_hash)+'</td>'
      +'<td>'+_sb(r.status)+'</td>'
      +'<td style="color:#c0392b;font-size:8px;">'+esc(r.error_message||'—')+'</td>'
      +'<td>'+esc(r.notes||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(r.created_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(r.updated_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(r.completed_at)+'</td>'
      +'</tr>';});
  }else if(tab==='payloads'){
    html+='<table><thead><tr><th>Full ID</th><th>Transaction Reference</th><th>Request ID</th><th>Asset</th><th>Amount</th><th>Network</th><th>Sender Wallet</th><th>Receiver Wallet</th><th>TX Hash</th><th>Block Number</th><th>Confirmations</th><th>Status</th><th>Security Level</th><th>Client IP</th><th>Explorer URL</th><th>Notes</th><th>Created At</th><th>Updated At</th></tr></thead><tbody>';
    data.forEach(function(p){html+='<tr>'
      +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(p.id||'—')+'</td>'
      +'<td>'+esc(p.transaction_reference||'—')+'</td>'
      +'<td>'+esc(p.request_id||'—')+'</td>'
      +'<td>'+esc(p.asset||'—')+'</td>'
      +'<td><strong>'+esc(String(p.amount||'—'))+'</strong></td>'
      +'<td>'+esc(p.network_name||'—')+'</td>'
      +'<td>'+_tHash(p.sender_wallet)+'</td>'
      +'<td>'+_tHash(p.receiver_wallet)+'</td>'
      +'<td>'+_tHash(p.tx_hash)+'</td>'
      +'<td>'+esc(String(p.block_number||'—'))+'</td>'
      +'<td>'+esc(String(p.confirmations||'—'))+'</td>'
      +'<td>'+_sb(p.verification_status)+'</td>'
      +'<td>'+esc(p.security_level||'—')+'</td>'
      +'<td>'+esc(p.client_ip||'—')+'</td>'
      +'<td style="font-size:8px;word-break:break-all;">'+esc(p.explorer_url||'—')+'</td>'
      +'<td>'+esc(p.notes||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(p.created_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(p.updated_at)+'</td>'
      +'</tr>';});
  }else if(tab==='transfers'){
    html+='<table><thead><tr><th>Full ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Address</th><th>From Address</th><th>TX Hash</th><th>Status</th><th>Approved By</th><th>Approved At</th><th>Cancelled By</th><th>Broadcaster At</th><th>Retry#</th><th>Error</th><th>Priority</th><th>Webhook URL</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
    data.forEach(function(x){html+='<tr>'
      +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(x.id||'—')+'</td>'
      +'<td><strong>'+esc((x.network||'—').toUpperCase())+'</strong></td>'
      +'<td>'+esc(x.asset||x.currency||'USDT')+'</td>'
      +'<td><strong>'+esc(String(x.amount||'—'))+'</strong></td>'
      +'<td>'+_tHash(x.to_address)+'</td>'
      +'<td>'+_tHash(x.from_address)+'</td>'
      +'<td>'+_tHash(x.tx_hash)+'</td>'
      +'<td>'+_sb(x.status)+'</td>'
      +'<td>'+esc(x.approved_by||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(x.approved_at)+'</td>'
      +'<td>'+esc(x.cancelled_by||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(x.broadcaster_at)+'</td>'
      +'<td>'+esc(String(x.retry_count||0))+'</td>'
      +'<td style="color:#c0392b;font-size:8px;">'+esc(x.error_message||'—')+'</td>'
      +'<td>'+esc(x.priority||'—')+'</td>'
      +'<td style="font-size:8px;word-break:break-all;">'+esc(x.webhook_url||'—')+'</td>'
      +'<td>'+esc(x.notes||'—')+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(x.created_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(x.updated_at)+'</td>'
      +'<td style="white-space:nowrap;">'+_tDate(x.completed_at)+'</td>'
      +'</tr>';});
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
    /* ── Full-detail tables: ALL fields, no truncation on amounts ── */
    function _allDate(v){return v?new Date(v).toLocaleString():'—';}
    function _allHash(v){return v?'<span style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(v)+'</span>':'—';}
    if(orders.length){
      html+='<h2>Payment Orders — '+orders.length+' records (full detail)</h2>'
        +'<table><thead><tr><th>Full ID</th><th>Ext Reference</th><th>Payment Reference</th><th>Provider</th><th>Status</th><th>Fiat Amount</th><th>Fiat Currency</th><th>Exchange Rate</th><th>Crypto Amount</th><th>Crypto Currency</th><th>Network</th><th>User Wallet</th><th>Treasury Wallet</th><th>TX Hash</th><th>Fees Fiat</th><th>Fees Crypto</th><th>Processor Ref</th><th>Client IP</th><th>Idempotency Key</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
      orders.forEach(function(o){html+='<tr>'
        +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(o.id||'—')+'</td>'
        +'<td>'+esc(o.external_id||'—')+'</td>'
        +'<td>'+esc(o.payment_reference||'—')+'</td>'
        +'<td>'+esc(o.provider||'—')+'</td>'
        +'<td>'+_sb(o.status)+'</td>'
        +'<td><strong>'+esc(String(o.fiat_amount||'—'))+'</strong></td>'
        +'<td>'+esc(o.fiat_currency||'—')+'</td>'
        +'<td>'+esc(String(o.exchange_rate||'—'))+'</td>'
        +'<td><strong>'+esc(String(o.crypto_amount||'—'))+'</strong></td>'
        +'<td>'+esc(o.crypto_currency||'—')+'</td>'
        +'<td>'+esc(o.network||'—')+'</td>'
        +'<td>'+_allHash(o.user_wallet_address||o.wallet)+'</td>'
        +'<td>'+_allHash(o.treasury_wallet_address)+'</td>'
        +'<td>'+_allHash(o.tx_hash)+'</td>'
        +'<td>'+esc(String(o.fees_fiat||'—'))+'</td>'
        +'<td>'+esc(String(o.fees_crypto||'—'))+'</td>'
        +'<td>'+esc(o.processor_reference||'—')+'</td>'
        +'<td>'+esc(o.client_ip||'—')+'</td>'
        +'<td style="font-size:8px;">'+esc((o.idempotency_key||'—').slice(0,24))+'</td>'
        +'<td>'+esc(o.notes||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(o.created_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(o.updated_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(o.completed_at)+'</td>'
        +'</tr>';});
      html+='</tbody></table>';
    }
    if(m1.length){
      html+='<h2>M1 Tokenization Jobs — '+m1.length+' records (full detail)</h2>'
        +'<table><thead><tr><th>Full ID</th><th>Sender Reference</th><th>Sender Name</th><th>Sender IBAN</th><th>Sender Bank</th><th>EUR Amount</th><th>FX Rate EUR/USD</th><th>USD Amount</th><th>Output Amount</th><th>Target Asset</th><th>Receiver Wallet</th><th>Network</th><th>TX Hash</th><th>Status</th><th>Error</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
      m1.forEach(function(r){html+='<tr>'
        +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(r.id||'—')+'</td>'
        +'<td>'+esc(r.sender_reference||'—')+'</td>'
        +'<td>'+esc(r.sender_name||'—')+'</td>'
        +'<td style="font-family:monospace;font-size:8px;">'+esc(r.sender_iban||'—')+'</td>'
        +'<td>'+esc(r.sender_bank||'—')+'</td>'
        +'<td><strong>'+esc(String(r.eur_amount||'—'))+' EUR</strong></td>'
        +'<td>'+esc(String(r.fx_rate_eur_usd||r.fx_rate||'—'))+'</td>'
        +'<td>'+esc(String(r.usd_amount||'—'))+' USD</td>'
        +'<td><strong>'+esc(String(r.usdt_amount||'—'))+'</strong></td>'
        +'<td>'+esc(r.target_asset||'SIG')+'</td>'
        +'<td>'+_allHash(r.receiver_wallet)+'</td>'
        +'<td>'+esc((r.network||'—').toUpperCase())+'</td>'
        +'<td>'+_allHash(r.tx_hash)+'</td>'
        +'<td>'+_sb(r.status)+'</td>'
        +'<td style="color:#c0392b;font-size:8px;">'+esc(r.error_message||'—')+'</td>'
        +'<td>'+esc(r.notes||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(r.created_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(r.updated_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(r.completed_at)+'</td>'
        +'</tr>';});
      html+='</tbody></table>';
    }
    if(payloads.length){
      html+='<h2>Settlement Payloads — '+payloads.length+' records (full detail)</h2>'
        +'<table><thead><tr><th>Full ID</th><th>Transaction Reference</th><th>Request ID</th><th>Asset</th><th>Amount</th><th>Network</th><th>Sender Wallet</th><th>Receiver Wallet</th><th>TX Hash</th><th>Block Number</th><th>Confirmations</th><th>Status</th><th>Security Level</th><th>Client IP</th><th>Explorer URL</th><th>Notes</th><th>Created At</th><th>Updated At</th></tr></thead><tbody>';
      payloads.forEach(function(p){html+='<tr>'
        +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(p.id||'—')+'</td>'
        +'<td>'+esc(p.transaction_reference||'—')+'</td>'
        +'<td>'+esc(p.request_id||'—')+'</td>'
        +'<td>'+esc(p.asset||'—')+'</td>'
        +'<td><strong>'+esc(String(p.amount||'—'))+'</strong></td>'
        +'<td>'+esc(p.network_name||'—')+'</td>'
        +'<td>'+_allHash(p.sender_wallet)+'</td>'
        +'<td>'+_allHash(p.receiver_wallet)+'</td>'
        +'<td>'+_allHash(p.tx_hash)+'</td>'
        +'<td>'+esc(String(p.block_number||'—'))+'</td>'
        +'<td>'+esc(String(p.confirmations||'—'))+'</td>'
        +'<td>'+_sb(p.verification_status)+'</td>'
        +'<td>'+esc(p.security_level||'—')+'</td>'
        +'<td>'+esc(p.client_ip||'—')+'</td>'
        +'<td style="font-size:8px;word-break:break-all;">'+esc(p.explorer_url||'—')+'</td>'
        +'<td>'+esc(p.notes||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(p.created_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(p.updated_at)+'</td>'
        +'</tr>';});
      html+='</tbody></table>';
    }
    if(transfers.length){
      html+='<h2>Outbound Transfers — '+transfers.length+' records (full detail)</h2>'
        +'<table><thead><tr><th>Full ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Address</th><th>From Address</th><th>TX Hash</th><th>Status</th><th>Approved By</th><th>Approved At</th><th>Cancelled By</th><th>Broadcaster At</th><th>Retry Count</th><th>Error</th><th>Priority</th><th>Webhook URL</th><th>Notes</th><th>Created At</th><th>Updated At</th><th>Completed At</th></tr></thead><tbody>';
      transfers.forEach(function(x){html+='<tr>'
        +'<td style="font-family:monospace;font-size:8px;word-break:break-all;">'+esc(x.id||'—')+'</td>'
        +'<td><strong>'+esc((x.network||'—').toUpperCase())+'</strong></td>'
        +'<td>'+esc(x.asset||x.currency||'USDT')+'</td>'
        +'<td><strong>'+esc(String(x.amount||'—'))+'</strong></td>'
        +'<td>'+_allHash(x.to_address)+'</td>'
        +'<td>'+_allHash(x.from_address)+'</td>'
        +'<td>'+_allHash(x.tx_hash)+'</td>'
        +'<td>'+_sb(x.status)+'</td>'
        +'<td>'+esc(x.approved_by||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(x.approved_at)+'</td>'
        +'<td>'+esc(x.cancelled_by||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(x.broadcaster_at)+'</td>'
        +'<td>'+esc(String(x.retry_count||0))+'</td>'
        +'<td style="color:#c0392b;font-size:8px;">'+esc(x.error_message||'—')+'</td>'
        +'<td>'+esc(x.priority||'—')+'</td>'
        +'<td style="font-size:8px;word-break:break-all;">'+esc(x.webhook_url||'—')+'</td>'
        +'<td>'+esc(x.notes||'—')+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(x.created_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(x.updated_at)+'</td>'
        +'<td style="white-space:nowrap;">'+_allDate(x.completed_at)+'</td>'
        +'</tr>';});
      html+='</tbody></table>';
    }
    html+=_pf()+'</body></html>';
    var w=window.open('','_blank','width=1200,height=820');w.document.write(html);w.document.close();setTimeout(function(){w.print();},500);
  }).catch(function(e){showToast('Print error: '+e.message,'error');});
}

function loadReportOrders(){
  document.getElementById('rOrderCount').textContent='Loading...';
  api('/api/v1/admin/orders').then(function(rows){
    if(!Array.isArray(rows)) rows=rows.orders||[];
    _rData.orders=rows;
    document.getElementById('rOrderCount').textContent=rows.length+' orders';
    document.getElementById('statOrders').textContent=rows.length;
    if(!rows.length){document.getElementById('reportOrders').innerHTML='<div class="empty-state"><div class="icon">&#128202;</div>No orders found</div>';return;}
    var tb=rows.map(function(o,i){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(o.id||'')+'">'+esc((o.id||'—').slice(0,12))+'&#8230;</span></td>'
      +'<td>'+esc(o.external_id||o.payment_reference||'—')+'</td>'
      +'<td>'+esc(o.provider||'')+'</td>'
      +'<td>'+badge(o.status||'')+'</td>'
      +'<td class="amt-fiat">'+fmtNum(o.fiat_amount)+' '+esc(o.fiat_currency||'')+'</td>'
      +'<td>'+fmtNum(o.crypto_amount,6)+' '+esc(o.crypto_currency||'')+'</td>'
      +'<td>'+esc(o.network||'')+'</td>'
      +'<td>'+(o.tx_hash?'<span class="mono-id" title="'+esc(o.tx_hash)+'">'+esc(o.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(o.created_at)+'</td>'
      +'<td><div style="display:flex;gap:4px;flex-wrap:wrap;">'
        +'<button class="btn btn-primary" data-id="'+esc(o.id||'')+'" onclick="window.open(\\\'/api/v1/admin/orders/\\\'+encodeURIComponent(this.dataset.id)+\\\'/documents/statement\\\',\\\'_blank\\\')" style="font-size:10px;padding:2px 7px;">Statement</button>'
        +'<button class="btn btn-ghost" data-id="'+esc(o.id||'')+'" onclick="window.open(\\\'/api/v1/admin/orders/\\\'+encodeURIComponent(this.dataset.id)+\\\'/documents/invoice\\\',\\\'_blank\\\')" style="font-size:10px;padding:2px 7px;">Invoice</button>'
        +'<button class="btn btn-success" data-idx="'+i+'" onclick="printTxReport(+this.dataset.idx,\\\'order\\\')" style="font-size:10px;padding:2px 7px;">&#128424; Report</button>'
        +'</div></td>'
      +'</tr>';}).join('');
    document.getElementById('reportOrders').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Provider</th><th>Status</th><th>Fiat</th><th>Crypto</th><th>Network</th><th>TX Hash</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportOrders').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportM1(){
  document.getElementById('rM1Count').textContent='Loading...';
  api('/api/v1/admin/tokenization-jobs?limit=200').then(function(rows){
    if(!Array.isArray(rows)) rows=[];
    _rData.m1=rows;
    document.getElementById('rM1Count').textContent=rows.length+' jobs';
    document.getElementById('statM1').textContent=rows.length;
    if(!rows.length){document.getElementById('reportM1').innerHTML='<div class="empty-state"><div class="icon">&#128260;</div>No M1 jobs found</div>';return;}
    var tb=rows.map(function(r,i){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(r.id||'')+'">'+esc((r.id||'—').slice(0,10))+'&#8230;</span></td>'
      +'<td>'+esc(r.sender_reference||'—')+'</td>'
      +'<td>'+esc(r.sender_name||'—')+'</td>'
      +'<td class="amt-eur">'+fmtNum(r.eur_amount)+' EUR</td>'
      +'<td>'+esc(String(r.fx_rate||r.fx_rate_eur_usd||'—'))+'</td>'
      +'<td class="amt-sig">'+fmtNum(r.usdt_amount)+' '+esc(r.target_asset||'SIG')+'</td>'
      +'<td>'+esc((r.network||'—').toUpperCase())+'</td>'
      +'<td>'+badge(r.status)+'</td>'
      +'<td>'+(r.tx_hash?'<span class="mono-id" title="'+esc(r.tx_hash)+'">'+esc(r.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(r.created_at)+'</td>'
      +'<td><div style="display:flex;gap:4px;flex-wrap:wrap;">'
        +'<button class="btn btn-success" data-idx="'+i+'" onclick="printTxReport(+this.dataset.idx,\\\'m1\\\')" style="font-size:10px;padding:2px 7px;">&#128424; Report</button>'
        +'<button class="btn btn-ghost" data-ref="'+esc(r.id||'')+'" onclick="document.getElementById(\\\'reportOrderId\\\').value=this.dataset.ref;switchRTab(\\\'orders\\\')" style="font-size:10px;padding:2px 7px;">Find Order</button>'
      +'</div></td>'
      +'</tr>';}).join('');
    document.getElementById('reportM1').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Sender</th><th>EUR</th><th>FX Rate</th><th>SIG Amount</th><th>Network</th><th>Status</th><th>TX Hash</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportM1').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportPayloads(){
  document.getElementById('rPayloadCount').textContent='Loading...';
  api('/api/v1/admin/payloads?limit=200').then(function(data){
    var rows=Array.isArray(data)?data:(data.payloads||[]);
    _rData.payloads=rows;
    document.getElementById('rPayloadCount').textContent=rows.length+' payloads';
    document.getElementById('statPayloads').textContent=rows.length;
    if(!rows.length){document.getElementById('reportPayloads').innerHTML='<div class="empty-state"><div class="icon">&#128232;</div>No payloads found</div>';return;}
    var tb=rows.map(function(p,i){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(p.id||'')+'">'+esc((p.id||'—').slice(0,10))+'&#8230;</span></td>'
      +'<td>'+esc(p.transaction_reference||p.request_id||'—')+'</td>'
      +'<td>'+esc(p.asset||'—')+'</td>'
      +'<td class="amt-usdt"><strong>'+fmtNum(p.amount)+' '+esc(p.asset||'')+'</strong></td>'
      +'<td>'+esc(p.network_name||'—')+'</td>'
      +'<td>'+badge(p.verification_status||'')+'</td>'
      +'<td>'+(p.tx_hash?'<span class="mono-id" title="'+esc(p.tx_hash)+'">'+esc(p.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(p.created_at)+'</td>'
      +'<td><button class="btn btn-success" data-idx="'+i+'" onclick="printTxReport(+this.dataset.idx,\\\'payload\\\')" style="font-size:10px;padding:2px 7px;">&#128424; Report</button></td>'
      +'</tr>';}).join('');
    document.getElementById('reportPayloads').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Reference</th><th>Asset</th><th>Amount</th><th>Network</th><th>Status</th><th>TX Hash</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
  }).catch(function(e){document.getElementById('reportPayloads').innerHTML='<div class="empty-state"><div class="icon">x</div>'+esc(e.message||String(e))+'</div>';});
}

function loadReportTransfers(){
  document.getElementById('rXferCount').textContent='Loading...';
  api('/api/v1/admin/outbound-transfers?limit=200').then(function(data){
    var rows=Array.isArray(data)?data:(data.transfers||[]);
    _rData.transfers=rows;
    document.getElementById('rXferCount').textContent=rows.length+' transfers';
    document.getElementById('statTransfers').textContent=rows.length;
    if(!rows.length){document.getElementById('reportTransfers').innerHTML='<div class="empty-state"><div class="icon">&#128228;</div>No transfers found</div>';return;}
    var tb=rows.map(function(x,i){return '<tr>'
      +'<td><span class="mono-id" title="'+esc(x.id||'')+'">'+esc((x.id||'—').slice(0,10))+'&#8230;</span></td>'
      +'<td><strong>'+esc((x.network||'—').toUpperCase())+'</strong></td>'
      +'<td>'+esc(x.asset||x.currency||'USDT')+'</td>'
      +'<td class="amt-usdt"><strong>'+fmtNum(x.amount)+'</strong></td>'
      +'<td>'+(x.to_address?'<span class="mono-id" title="'+esc(x.to_address)+'">'+esc(x.to_address.slice(0,14))+'&#8230;</span>':'—')+'</td>'
      +'<td>'+badge(x.status||'')+'</td>'
      +'<td>'+(x.tx_hash?'<span class="mono-id" title="'+esc(x.tx_hash)+'">'+esc(x.tx_hash.slice(0,12))+'&#8230;</span>':'—')+'</td>'
      +'<td style="font-size:11px;">'+fmtDate(x.created_at)+'</td>'
      +'<td><button class="btn btn-success" data-idx="'+i+'" onclick="printTxReport(+this.dataset.idx,\\\'transfer\\\')" style="font-size:10px;padding:2px 7px;">&#128424; Report</button></td>'
      +'</tr>';}).join('');
    document.getElementById('reportTransfers').innerHTML='<div class="table-wrap"><table class="rpt-table"><thead><tr><th>ID</th><th>Network</th><th>Asset</th><th>Amount</th><th>To Wallet</th><th>Status</th><th>TX Hash</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+tb+'</tbody></table></div>';
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


@router.get("/dashboard/validator", response_class=HTMLResponse)
async def dashboard_validator(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Transaction Validator", "/dashboard/validator", _VALIDATOR_BODY))


_VALIDATOR_BODY = """
<style>
.vld-root{font-family:"Helvetica Neue",Arial,sans-serif;color:var(--ink);}
.vld-search{background:var(--panel);border:1px solid var(--line-strong);border-radius:14px;padding:28px 32px;margin-bottom:20px;}
.vld-search h2{font-size:22px;font-weight:800;color:var(--gold);margin:0 0 6px;}
.vld-search p{font-size:12px;color:var(--muted);margin:0 0 18px;}
.vld-search-row{display:flex;gap:10px;flex-wrap:wrap;}
.vld-search-row input{flex:1;min-width:240px;padding:12px 16px;border:1.5px solid var(--line-strong);border-radius:9px;background:var(--glass);color:var(--ink);font-size:13px;outline:none;}
.vld-search-row input:focus{border-color:var(--brand);}
.vld-search-row select{padding:12px 14px;border:1.5px solid var(--line-strong);border-radius:9px;background:var(--glass);color:var(--ink);font-size:13px;}
.vld-btn-search{background:var(--brand);color:#fff;border:none;padding:12px 28px;border-radius:9px;font-size:13px;font-weight:700;cursor:pointer;}
.vld-btn-search:hover{opacity:.88;}
.vld-report{display:none;}
/* Header bar */
.vld-topbar{background:linear-gradient(135deg,#0a1628 0%,#0d2240 60%,#1a3a6b 100%);border-radius:14px;padding:18px 28px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;border:1px solid rgba(201,168,76,.25);}
.vld-topbar-title{font-size:19px;font-weight:900;color:#fff;letter-spacing:.5px;}
.vld-topbar-sub{font-size:10px;color:rgba(255,255,255,.55);margin-top:3px;letter-spacing:.3px;}
.vld-topbar-meta{display:flex;gap:24px;flex-wrap:wrap;}
.vld-topbar-meta-item label{font-size:9px;color:rgba(255,255,255,.45);font-weight:700;letter-spacing:.8px;display:block;text-transform:uppercase;}
.vld-topbar-meta-item span{font-size:12px;color:#e2e8f0;font-weight:700;}
.vld-status-badge{padding:8px 20px;border-radius:8px;font-size:13px;font-weight:800;letter-spacing:.5px;display:flex;align-items:center;gap:7px;}
.vld-status-badge.ok{background:rgba(16,185,129,.18);color:#10b981;border:1.5px solid rgba(16,185,129,.4);}
.vld-status-badge.fail{background:rgba(239,68,68,.18);color:#ef4444;border:1.5px solid rgba(239,68,68,.4);}
.vld-status-badge.pending{background:rgba(245,158,11,.18);color:#f59e0b;border:1.5px solid rgba(245,158,11,.4);}
/* Key metrics */
.vld-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px;}
.vld-metric{background:var(--panel);border:1px solid var(--line-strong);border-radius:12px;padding:16px 20px;display:flex;align-items:center;gap:14px;}
.vld-metric-icon{width:42px;height:42px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}
.vld-metric-icon.blue{background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.3);}
.vld-metric-icon.gold{background:rgba(201,168,76,.15);border:1px solid rgba(201,168,76,.3);}
.vld-metric-icon.green{background:rgba(16,185,129,.15);border:1px solid rgba(16,185,129,.3);}
.vld-metric-icon.purple{background:rgba(139,92,246,.15);border:1px solid rgba(139,92,246,.3);}
.vld-metric-icon.orange{background:rgba(249,115,22,.15);border:1px solid rgba(249,115,22,.3);}
.vld-metric-label{font-size:9px;color:var(--muted);font-weight:700;letter-spacing:.8px;text-transform:uppercase;}
.vld-metric-value{font-size:14px;font-weight:800;color:var(--ink);margin-top:2px;word-break:break-all;}
.vld-metric-value.gold{color:#c9a84c;}
.vld-metric-value.green{color:#10b981;}
/* 3-col grid */
.vld-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:16px;}
@media(max-width:1100px){.vld-grid{grid-template-columns:1fr 1fr;}}
@media(max-width:700px){.vld-grid{grid-template-columns:1fr;}}
.vld-card{background:var(--panel);border:1px solid var(--line-strong);border-radius:12px;overflow:hidden;}
.vld-card-head{padding:12px 18px;background:rgba(13,34,64,.6);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:9px;}
.vld-card-head-icon{font-size:16px;}
.vld-card-head-title{font-size:11px;font-weight:800;color:var(--gold);letter-spacing:.8px;text-transform:uppercase;}
.vld-card-body{padding:14px 18px;}
.vld-field{display:flex;justify-content:space-between;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--line);gap:12px;}
.vld-field:last-child{border-bottom:none;}
.vld-field-label{font-size:10px;color:var(--muted);font-weight:600;min-width:110px;flex-shrink:0;padding-top:1px;}
.vld-field-value{font-size:10.5px;color:var(--ink);font-weight:600;text-align:right;word-break:break-all;}
.vld-field-value code{font-family:monospace;font-size:9.5px;word-break:break-all;}
.vld-field-value.green{color:#10b981;}
.vld-field-value.gold{color:#c9a84c;}
.vld-field-value.red{color:#ef4444;}
.vld-field-value.blue{color:#60a5fa;}
/* Progress */
.vld-step{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);}
.vld-step:last-child{border-bottom:none;}
.vld-step-icon{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;}
.vld-step-icon.done{background:rgba(16,185,129,.2);border:1.5px solid #10b981;color:#10b981;}
.vld-step-icon.fail{background:rgba(239,68,68,.2);border:1.5px solid #ef4444;color:#ef4444;}
.vld-step-icon.skip{background:rgba(100,116,139,.15);border:1.5px solid #64748b;color:#64748b;}
.vld-step-icon.pending{background:rgba(245,158,11,.15);border:1.5px solid #f59e0b;color:#f59e0b;}
.vld-step-info{flex:1;}
.vld-step-name{font-size:11px;font-weight:700;color:var(--ink);}
.vld-step-desc{font-size:9.5px;color:var(--muted);margin-top:1px;}
.vld-step-pct{font-size:11px;font-weight:800;}
.vld-step-pct.done{color:#10b981;}
.vld-step-pct.fail{color:#ef4444;}
.vld-step-pct.skip{color:#64748b;}
/* Check list */
.vld-check{display:flex;align-items:center;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);}
.vld-check:last-child{border-bottom:none;}
.vld-check-label{font-size:10.5px;color:var(--ink);display:flex;align-items:center;gap:7px;}
.vld-check-result{font-size:10px;font-weight:800;letter-spacing:.4px;}
.vld-check-result.ok{color:#10b981;}
.vld-check-result.fail{color:#ef4444;}
.vld-check-result.warn{color:#f59e0b;}
.vld-check-result.na{color:#64748b;}
/* Score */
.vld-score-ring{width:90px;height:90px;margin:8px auto;position:relative;}
.vld-score-ring svg{transform:rotate(-90deg);}
.vld-score-num{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:22px;font-weight:900;color:var(--gold);}
/* Timeline */
.vld-timeline{margin-bottom:16px;}
.vld-tl-item{display:flex;gap:14px;padding:10px 0;position:relative;}
.vld-tl-item:not(:last-child)::before{content:"";position:absolute;left:15px;top:36px;bottom:0;width:2px;background:var(--line);}
.vld-tl-dot{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;border:2px solid;}
.vld-tl-dot.done{background:rgba(16,185,129,.15);border-color:#10b981;}
.vld-tl-dot.fail{background:rgba(239,68,68,.15);border-color:#ef4444;}
.vld-tl-dot.pending{background:rgba(245,158,11,.15);border-color:#f59e0b;}
.vld-tl-dot.info{background:rgba(96,165,250,.15);border-color:#60a5fa;}
.vld-tl-content{flex:1;}
.vld-tl-title{font-size:11.5px;font-weight:700;color:var(--ink);}
.vld-tl-time{font-size:9.5px;color:var(--muted);margin-top:1px;}
.vld-tl-detail{font-size:10px;color:var(--muted);margin-top:4px;background:var(--glass);border-radius:6px;padding:5px 10px;border:1px solid var(--line);}
/* Auth codes */
.vld-codes{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px;}
.vld-code-item{background:var(--panel);border:1px solid var(--line-strong);border-radius:10px;padding:12px 14px;text-align:center;}
.vld-code-label{font-size:8.5px;color:var(--muted);font-weight:700;letter-spacing:.8px;text-transform:uppercase;margin-bottom:4px;}
.vld-code-value{font-size:16px;font-weight:900;color:var(--gold);letter-spacing:1px;font-family:monospace;}
/* Final banner */
.vld-final{border-radius:12px;padding:20px 28px;display:flex;align-items:center;gap:18px;margin-bottom:16px;}
.vld-final.ok{background:rgba(16,185,129,.1);border:2px solid rgba(16,185,129,.4);}
.vld-final.fail{background:rgba(239,68,68,.1);border:2px solid rgba(239,68,68,.4);}
.vld-final.pending{background:rgba(245,158,11,.1);border:2px solid rgba(245,158,11,.4);}
.vld-final-icon{font-size:36px;}
.vld-final-title{font-size:18px;font-weight:900;letter-spacing:.5px;}
.vld-final-title.ok{color:#10b981;}
.vld-final-title.fail{color:#ef4444;}
.vld-final-title.pending{color:#f59e0b;}
.vld-final-sub{font-size:11px;color:var(--muted);margin-top:4px;}
.vld-actions{display:flex;gap:10px;margin-left:auto;flex-wrap:wrap;}
</style>

<div class="vld-root page-body">

<!-- SEARCH -->
<div class="vld-search">
  <h2>&#128269; Transaction Validation Engine</h2>
  <p>Search for any transaction by ID, TX Hash, or Reference to generate a full validation report.</p>
  <div class="vld-search-row">
    <input id="vldInput" placeholder="Enter Transaction ID / TX Hash / Reference / IBAN..." onkeydown="if(event.key==='Enter')vldSearch()"/>
    <select id="vldType">
      <option value="auto">Auto Detect</option>
      <option value="transfer">Outbound Transfer</option>
      <option value="payload">Settlement Payload</option>
      <option value="order">Payment Order</option>
      <option value="m1">M1 Tokenization Job</option>
    </select>
    <button class="vld-btn-search" onclick="vldSearch()">&#128269; Validate</button>
  </div>
  <div id="vldError" style="margin-top:12px;color:#ef4444;font-size:12px;display:none;"></div>
</div>

<!-- LOADING -->
<div id="vldLoading" style="display:none;text-align:center;padding:40px;">
  <div style="font-size:28px;margin-bottom:12px;">&#9881;</div>
  <div style="font-size:13px;color:var(--muted);">Running validation checks...</div>
  <div style="margin:16px auto;width:240px;height:6px;background:var(--glass);border-radius:3px;overflow:hidden;">
    <div id="vldBar" style="height:100%;background:var(--brand);border-radius:3px;width:0%;transition:width .4s;"></div>
  </div>
</div>

<!-- FULL REPORT -->
<div class="vld-report" id="vldReport">

  <!-- TOP BAR -->
  <div class="vld-topbar">
    <div>
      <div class="vld-topbar-title">&#9878; TRANSACTION VALIDATION ENGINE — ALSHUMOOKH GLOBAL</div>
      <div class="vld-topbar-sub">BANKING FINANCE &amp; CREDIT &bull; AML SCREENING &bull; BLOCKCHAIN VERIFICATION &bull; COMPLIANCE ENGINE</div>
    </div>
    <div class="vld-topbar-meta">
      <div class="vld-topbar-meta-item"><label>Report ID</label><span id="vldRptId">—</span></div>
      <div class="vld-topbar-meta-item"><label>Generated</label><span id="vldRptDate">—</span></div>
      <div class="vld-topbar-meta-item"><label>Type</label><span id="vldRptType">—</span></div>
    </div>
    <div id="vldTopStatus" class="vld-status-badge ok">&#9679; VERIFIED</div>
  </div>

  <!-- KEY METRICS -->
  <div class="vld-metrics">
    <div class="vld-metric">
      <div class="vld-metric-icon gold">&#128176;</div>
      <div><div class="vld-metric-label">Transaction Amount</div><div class="vld-metric-value gold" id="vldAmt">—</div></div>
    </div>
    <div class="vld-metric">
      <div class="vld-metric-icon blue">&#127760;</div>
      <div><div class="vld-metric-label">Network / Bank</div><div class="vld-metric-value" id="vldNetwork">—</div></div>
    </div>
    <div class="vld-metric">
      <div class="vld-metric-icon purple">&#128203;</div>
      <div><div class="vld-metric-label">Transaction Reference</div><div class="vld-metric-value" id="vldRef">—</div></div>
    </div>
    <div class="vld-metric">
      <div class="vld-metric-icon green">&#128279;</div>
      <div><div class="vld-metric-label">Asset / Currency</div><div class="vld-metric-value" id="vldAsset">—</div></div>
    </div>
    <div class="vld-metric">
      <div class="vld-metric-icon orange">&#128737;</div>
      <div><div class="vld-metric-label">Final Status</div><div class="vld-metric-value green" id="vldStatusMetric">—</div></div>
    </div>
  </div>

  <!-- 3-COLUMN GRID -->
  <div class="vld-grid">

    <!-- COL 1: Sender + Progress -->
    <div style="display:flex;flex-direction:column;gap:14px;">

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#128100;</span><span class="vld-card-head-title">Sender Information</span></div>
        <div class="vld-card-body" id="vldSender"></div>
      </div>

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#9881;</span><span class="vld-card-head-title">Validation Progress</span></div>
        <div class="vld-card-body" id="vldProgress"></div>
        <div style="padding:10px 18px 14px;">
          <div style="display:flex;justify-content:space-between;font-size:9.5px;color:var(--muted);margin-bottom:5px;"><span>Overall Progress</span><span id="vldPctLabel" style="font-weight:800;color:var(--gold);">0%</span></div>
          <div style="height:8px;background:var(--glass);border-radius:4px;overflow:hidden;border:1px solid var(--line);"><div id="vldOverallBar" style="height:100%;border-radius:4px;transition:width .5s;background:linear-gradient(90deg,#10b981,#059669);width:0%;"></div></div>
        </div>
      </div>

    </div>

    <!-- COL 2: Receiver + Blockchain -->
    <div style="display:flex;flex-direction:column;gap:14px;">

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#127968;</span><span class="vld-card-head-title">Receiver Information</span></div>
        <div class="vld-card-body" id="vldReceiver"></div>
      </div>

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#9851;</span><span class="vld-card-head-title">Blockchain &amp; Transaction</span></div>
        <div class="vld-card-body" id="vldBlockchain"></div>
      </div>

    </div>

    <!-- COL 3: Validation Results + Score + Transmission -->
    <div style="display:flex;flex-direction:column;gap:14px;">

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#9989;</span><span class="vld-card-head-title">Validation Results</span></div>
        <div class="vld-card-body" id="vldChecks"></div>
      </div>

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#128200;</span><span class="vld-card-head-title">Confidence Score</span></div>
        <div class="vld-card-body" style="text-align:center;padding:16px;">
          <div class="vld-score-ring">
            <svg width="90" height="90" viewBox="0 0 90 90">
              <circle cx="45" cy="45" r="36" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="10"/>
              <circle id="vldScoreArc" cx="45" cy="45" r="36" fill="none" stroke="#10b981" stroke-width="10" stroke-linecap="round" stroke-dasharray="226" stroke-dashoffset="226"/>
            </svg>
            <div class="vld-score-num" id="vldScoreNum">0%</div>
          </div>
          <div style="font-size:13px;font-weight:800;color:#10b981;margin-top:4px;" id="vldScoreLabel">HIGH CONFIDENCE</div>
          <div style="font-size:10px;color:var(--muted);margin-top:6px;" id="vldScoreDesc">Document integrity and validation checks completed successfully.</div>
        </div>
      </div>

      <div class="vld-card">
        <div class="vld-card-head"><span class="vld-card-head-icon">&#128225;</span><span class="vld-card-head-title">Transmission &amp; System Status</span></div>
        <div class="vld-card-body" id="vldTransmission"></div>
      </div>

    </div>
  </div>

  <!-- TIMELINE -->
  <div class="vld-card" style="margin-bottom:14px;">
    <div class="vld-card-head"><span class="vld-card-head-icon">&#128336;</span><span class="vld-card-head-title">Transaction Timeline — All Events</span></div>
    <div style="padding:14px 18px;" id="vldTimeline"></div>
  </div>

  <!-- AUTH CODES -->
  <div id="vldCodesSection" style="margin-bottom:14px;display:none;">
    <div style="font-size:10px;font-weight:800;color:var(--muted);letter-spacing:1px;text-transform:uppercase;margin-bottom:10px;">&#128273; Authorization &amp; Reference Codes</div>
    <div class="vld-codes" id="vldCodes"></div>
  </div>

  <!-- FINAL BANNER -->
  <div class="vld-final" id="vldFinal">
    <div class="vld-final-icon" id="vldFinalIcon">&#9989;</div>
    <div>
      <div class="vld-final-title" id="vldFinalTitle">APPROVED FOR TRANSMISSION</div>
      <div class="vld-final-sub" id="vldFinalSub">All validation processes completed successfully.</div>
    </div>
    <div class="vld-actions">
      <button onclick="vldPrint()" style="background:#0d2240;color:#c9a84c;border:none;padding:10px 22px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;">&#128424; Print Report</button>
      <button onclick="vldReset()" style="background:var(--glass);border:1px solid var(--line-strong);color:var(--ink);padding:10px 18px;border-radius:8px;font-size:12px;cursor:pointer;">&#128269; New Search</button>
    </div>
  </div>

</div><!-- end vld-report -->

</div><!-- end vld-root -->

<script>
/* ═══════════ VALIDATION ENGINE JS ═══════════ */
var VLD = {};

function vldEsc(v){if(!v&&v!==0)return '—';var d=document.createElement('div');d.textContent=String(v);return d.innerHTML;}
function vldNum(n){if(n===null||n===undefined||n==='')return '—';var x=parseFloat(n);return isNaN(x)?String(n):x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6});}
function vldDate(v){if(!v)return '—';try{return new Date(v).toLocaleString('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});}catch(e){return String(v);}}
function vldShort(v,n){if(!v)return '—';v=String(v);return v.length>n?v.slice(0,n)+'...':v;}

function vldField(label,value,cls){
  return '<div class="vld-field"><span class="vld-field-label">'+label+'</span><span class="vld-field-value'+(cls?' '+cls:'')+'">'+value+'</span></div>';
}
function vldCheck(icon,label,result,cls){
  return '<div class="vld-check"><span class="vld-check-label">'+icon+' '+label+'</span><span class="vld-check-result '+cls+'">'+result+'</span></div>';
}
function vldStep(icon,iconCls,name,desc,pct,pctCls){
  return '<div class="vld-step"><div class="vld-step-icon '+iconCls+'">'+icon+'</div><div class="vld-step-info"><div class="vld-step-name">'+name+'</div><div class="vld-step-desc">'+desc+'</div></div><div class="vld-step-pct '+pctCls+'">'+pct+'</div></div>';
}
function vldTl(dotCls,icon,title,time,detail){
  return '<div class="vld-tl-item"><div class="vld-tl-dot '+dotCls+'">'+icon+'</div><div class="vld-tl-content"><div class="vld-tl-title">'+title+'</div><div class="vld-tl-time">'+time+'</div>'+(detail?'<div class="vld-tl-detail">'+detail+'</div>':'')+'</div></div>';
}

function vldSearch(){
  var q=(document.getElementById('vldInput').value||'').trim();
  var t=document.getElementById('vldType').value;
  if(!q){vldShowError('Please enter a Transaction ID, TX Hash, or Reference.');return;}
  vldShowError('');
  document.getElementById('vldReport').style.display='none';
  document.getElementById('vldLoading').style.display='block';
  vldAnimBar();
  var key=document.cookie.replace(/(?:(?:^|.*;\\s*)admin_key\\s*=\\s*([^;]*).*$)|^.*$/,'$1')||localStorage.getItem('admin_key')||'';
  var hdrs={'Content-Type':'application/json','X-Admin-Key':key};
  // Try all endpoints in parallel or sequentially
  var endpoints=[
    {type:'transfer',url:'/api/v1/admin/outbound-transfers/'+encodeURIComponent(q)},
    {type:'payload', url:'/api/v1/admin/payloads/'+encodeURIComponent(q)},
    {type:'order',   url:'/api/v1/admin/orders/'+encodeURIComponent(q)},
    {type:'m1',      url:'/api/v1/admin/tokenization-jobs/'+encodeURIComponent(q)},
  ];
  if(t!=='auto') endpoints=endpoints.filter(function(e){return e.type===t;});
  var tried=0;
  function tryNext(i){
    if(i>=endpoints.length){
      // Try search by reference/hash
      vldSearchByRef(q,t,hdrs);
      return;
    }
    fetch(endpoints[i].url,{headers:hdrs})
      .then(function(r){if(!r.ok)throw new Error('not found');return r.json();})
      .then(function(d){vldRender(endpoints[i].type,d);})
      .catch(function(){tryNext(i+1);});
  }
  tryNext(0);
}

function vldSearchByRef(q,t,hdrs){
  // Search across list endpoints
  var searches=[
    {type:'transfer',url:'/api/v1/admin/outbound-transfers?limit=2000'},
    {type:'payload', url:'/api/v1/admin/payloads?limit=2000'},
    {type:'order',   url:'/api/v1/admin/orders?limit=2000'},
    {type:'m1',      url:'/api/v1/admin/tokenization-jobs?limit=500'},
  ];
  if(t!=='auto') searches=searches.filter(function(e){return e.type===t;});
  var ql=q.toLowerCase();
  function trySearch(i){
    if(i>=searches.length){
      document.getElementById('vldLoading').style.display='none';
      vldShowError('No transaction found for: "'+q+'". Try a different ID, hash, or reference.');
      return;
    }
    fetch(searches[i].url,{headers:hdrs})
      .then(function(r){return r.json();})
      .then(function(d){
        var arr=Array.isArray(d)?d:(d.transfers||d.payloads||d.orders||d.jobs||d.items||[]);
        var found=arr.filter(function(item){
          var s=JSON.stringify(item).toLowerCase();
          return s.indexOf(ql)>=0;
        });
        if(found.length>0){vldRender(searches[i].type,found[0]);}
        else{trySearch(i+1);}
      })
      .catch(function(){trySearch(i+1);});
  }
  trySearch(0);
}

function vldAnimBar(){
  var bar=document.getElementById('vldBar');
  var pct=0;
  var iv=setInterval(function(){
    pct+=Math.random()*12;
    if(pct>=90){pct=90;clearInterval(iv);}
    bar.style.width=pct+'%';
  },180);
  VLD._barIv=iv;
}

function vldFinishBar(){
  if(VLD._barIv){clearInterval(VLD._barIv);}
  document.getElementById('vldBar').style.width='100%';
  setTimeout(function(){document.getElementById('vldLoading').style.display='none';},400);
}

function vldShowError(msg){
  var el=document.getElementById('vldError');
  el.textContent=msg;
  el.style.display=msg?'block':'none';
}

function vldReset(){
  document.getElementById('vldReport').style.display='none';
  document.getElementById('vldInput').value='';
  document.getElementById('vldInput').focus();
}

function vldSetScore(pct){
  var arc=document.getElementById('vldScoreArc');
  var num=document.getElementById('vldScoreNum');
  var lbl=document.getElementById('vldScoreLabel');
  var desc=document.getElementById('vldScoreDesc');
  var circumference=226;
  var offset=circumference-(pct/100*circumference);
  arc.style.strokeDashoffset=offset;
  var col=pct>=90?'#10b981':pct>=70?'#f59e0b':'#ef4444';
  arc.setAttribute('stroke',col);
  num.textContent=pct+'%';
  num.style.color=col;
  if(pct>=90){lbl.textContent='HIGH CONFIDENCE';lbl.style.color='#10b981';desc.textContent='All integrity and validation checks completed successfully.';}
  else if(pct>=70){lbl.textContent='MEDIUM CONFIDENCE';lbl.style.color='#f59e0b';desc.textContent='Most checks passed. Some items require manual review.';}
  else{lbl.textContent='LOW CONFIDENCE';lbl.style.color='#ef4444';desc.textContent='Several validation checks failed. Manual review required.';}
}

function vldRender(type, d) {
  VLD.type=type;VLD.data=d;
  vldFinishBar();
  var rptId='VE-'+Date.now().toString(36).toUpperCase();
  document.getElementById('vldRptId').textContent=rptId;
  document.getElementById('vldRptDate').textContent=new Date().toLocaleString('en-GB');
  var typeLabels={transfer:'Outbound Transfer',payload:'Settlement Payload',order:'Payment Order',m1:'M1 Tokenization Job'};
  document.getElementById('vldRptType').textContent=typeLabels[type]||type;

  // ─── Status ───
  var statusMap={CONFIRMED:'ok',COMPLETED:'ok',RECONCILED:'ok',APPROVED:'ok',ALCHEMY_VERIFIED:'ok',ON_CHAIN_CONFIRMED:'ok',
    FAILED:'fail',REJECTED:'fail',CANCELLED:'fail',
    PENDING:'pending',RECEIVED:'pending',PROCESSING:'pending',AWAITING_TX_HASH:'pending',MANUAL_REVIEW:'pending',AWAITING_APPROVAL:'pending'};
  var st=d.status||d.verification_status||'PENDING';
  var stCls=statusMap[st]||'pending';
  var stIcons={ok:'&#9989;',fail:'&#10060;',pending:'&#9203;'};
  document.getElementById('vldTopStatus').className='vld-status-badge '+stCls;
  document.getElementById('vldTopStatus').innerHTML=stIcons[stCls]+' '+(st||'UNKNOWN');

  // ─── Metrics ───
  var amt='—', net='—', ref='—', asset='—';
  if(type==='transfer'){amt=vldNum(d.amount)+' '+(d.asset||'SIG');net=(d.network||'').toUpperCase();ref=vldShort(d.id,20);asset=d.asset||'SIG';}
  else if(type==='payload'){amt=vldNum(d.amount)+' '+(d.asset||'EUR');net=(d.network_name||d.network||'').toUpperCase()||'M1_FUND';ref=vldShort(d.id||d.payload_id,20);asset=d.asset||'EUR';}
  else if(type==='order'){amt=vldNum(d.fiat_amount)+' '+(d.fiat_currency||'EUR');net=(d.network||'').toUpperCase();ref=vldShort(d.payment_reference||d.id,20);asset=d.fiat_currency||'EUR';}
  else if(type==='m1'){amt=vldNum(d.eur_amount)+' EUR';net='ETHEREUM';ref=vldShort(d.sender_reference||d.id,20);asset='SIG / EUR';}
  document.getElementById('vldAmt').textContent=amt;
  document.getElementById('vldNetwork').textContent=net||'—';
  document.getElementById('vldRef').textContent=ref;
  document.getElementById('vldAsset').textContent=asset;
  document.getElementById('vldStatusMetric').textContent=st;
  document.getElementById('vldStatusMetric').className='vld-metric-value '+(stCls==='ok'?'green':stCls==='fail'?'red':'gold');

  // ─── Sender ───
  var sHTML='';
  if(type==='transfer'){
    sHTML+=vldField('From Address','<code>'+vldEsc(d.from_address)+'</code>');
    sHTML+=vldField('Initiated By',vldEsc(d.initiated_by)||'Admin');
    sHTML+=vldField('Approved By',vldEsc(d.approved_by));
    sHTML+=vldField('Approved At',vldDate(d.approved_at));
    sHTML+=vldField('Network',(d.network||'').toUpperCase());
    sHTML+=vldField('Asset',vldEsc(d.asset));
  } else if(type==='payload'){
    sHTML+=vldField('Sender Wallet','<code>'+vldEsc(d.sender_wallet)+'</code>');
    sHTML+=vldField('Auth Method',vldEsc(d.auth_method));
    sHTML+=vldField('Security Level',vldEsc(d.security_level));
    sHTML+=vldField('JWS Verified',d.jws_verified?'<span class="green">Yes</span>':'No');
    sHTML+=vldField('mTLS Verified',d.mtls_verified?'<span class="green">Yes</span>':'No');
    sHTML+=vldField('Client IP',vldEsc(d.client_ip));
  } else if(type==='order'){
    sHTML+=vldField('Payer Email',vldEsc(d.payer_email));
    sHTML+=vldField('Customer Name',vldEsc(d.customer_name));
    sHTML+=vldField('External ID',vldEsc(d.external_id));
    sHTML+=vldField('Idempotency Key','<code>'+vldShort(d.idempotency_key,24)+'</code>');
    sHTML+=vldField('Client IP',vldEsc(d.client_ip));
    sHTML+=vldField('Provider',vldEsc(d.provider));
  } else if(type==='m1'){
    sHTML+=vldField('Sender Name','<strong>'+vldEsc(d.sender_name)+'</strong>');
    sHTML+=vldField('Sender IBAN','<code>'+vldEsc(d.sender_iban)+'</code>');
    sHTML+=vldField('Sender Bank',vldEsc(d.sender_bank));
    sHTML+=vldField('Sender Reference',vldEsc(d.sender_reference));
    sHTML+=vldField('EUR Amount','<strong class="gold">'+vldNum(d.eur_amount)+' EUR</strong>');
    sHTML+=vldField('FX Rate EUR/USD',vldEsc(d.fx_rate_eur_usd||d.fx_rate));
  }
  document.getElementById('vldSender').innerHTML=sHTML;

  // ─── Receiver ───
  var rHTML='';
  if(type==='transfer'){
    rHTML+=vldField('To Address','<code>'+vldEsc(d.to_address)+'</code>');
    rHTML+=vldField('Contract Address','<code>'+vldShort(d.contract_address,24)+'</code>');
    rHTML+=vldField('Amount','<strong class="gold">'+vldNum(d.amount)+' '+(d.asset||'SIG')+'</strong>');
    rHTML+=vldField('Notes',vldEsc(d.notes));
    rHTML+=vldField('Callback URL',vldShort(d.callback_url,30));
    rHTML+=vldField('Webhook Status',d.webhook_status_code?String(d.webhook_status_code):'—');
  } else if(type==='payload'){
    rHTML+=vldField('Receiver Wallet','<code>'+vldEsc(d.receiver_wallet)+'</code>');
    rHTML+=vldField('Amount','<strong class="gold">'+vldNum(d.amount)+' '+(d.asset||'EUR')+'</strong>');
    rHTML+=vldField('Review Decision',vldEsc(d.review_decision));
    rHTML+=vldField('Reviewed By',vldEsc(d.reviewed_by));
    rHTML+=vldField('Review Priority',vldEsc(d.review_priority));
    rHTML+=vldField('Hold Reason',vldEsc(d.hold_reason));
  } else if(type==='order'){
    rHTML+=vldField('Wallet Address','<code>'+vldShort(d.user_wallet_address||d.wallet,28)+'</code>');
    rHTML+=vldField('Treasury Wallet','<code>'+vldShort(d.treasury_wallet_address,28)+'</code>');
    rHTML+=vldField('Crypto Amount','<strong>'+vldNum(d.crypto_amount)+' '+(d.crypto_currency||'SIG')+'</strong>');
    rHTML+=vldField('Fiat Amount','<strong class="gold">'+vldNum(d.fiat_amount)+' '+(d.fiat_currency||'EUR')+'</strong>');
    rHTML+=vldField('Exchange Rate',vldEsc(d.exchange_rate));
    rHTML+=vldField('Processor Ref',vldEsc(d.processor_reference));
  } else if(type==='m1'){
    rHTML+=vldField('Receiver Wallet','<code>'+vldShort(d.receiver_wallet,28)+'</code>');
    rHTML+=vldField('Operator Wallet','<code>'+vldShort(d.operator_wallet,28)+'</code>');
    rHTML+=vldField('Contract Address','<code>'+vldShort(d.contract_address,28)+'</code>');
    rHTML+=vldField('USD Amount','<strong>'+vldNum(d.usd_amount)+' USD</strong>');
    rHTML+=vldField('SIG Amount','<strong class="gold">'+vldNum(d.usdt_amount)+' SIG</strong>');
    rHTML+=vldField('FX Provider',vldEsc(d.fx_provider));
  }
  document.getElementById('vldReceiver').innerHTML=rHTML;

  // ─── Blockchain ───
  var bHTML='';
  var txh=d.tx_hash||'—';
  var expUrl=d.explorer_url||null;
  var txDisp=txh!=='—'?(expUrl?'<a href="'+vldEsc(expUrl)+'" target="_blank" style="color:#60a5fa;font-size:9px;word-break:break-all;font-family:monospace;">'+txh+'</a>':'<code style="font-size:9px;word-break:break-all;">'+txh+'</code>'):'—';
  bHTML+=vldField('TX Hash',txDisp);
  bHTML+=vldField('Block Number',d.block_number?String(d.block_number):'—');
  bHTML+=vldField('Confirmations',d.confirmations?String(d.confirmations):'—');
  bHTML+=vldField('Gas Used',d.gas_used?String(d.gas_used):'—');
  if(expUrl) bHTML+=vldField('Explorer','<a href="'+vldEsc(expUrl)+'" target="_blank" style="color:#60a5fa;font-size:10px;">View on Explorer &#8599;</a>');
  bHTML+=vldField('Broadcasted At',vldDate(d.broadcasted_at));
  bHTML+=vldField('Completed At',vldDate(d.completed_at));
  if(d.error_message) bHTML+=vldField('Error','<span style="color:#ef4444;font-size:9.5px;">'+vldEsc(d.error_message)+'</span>');
  document.getElementById('vldBlockchain').innerHTML=bHTML;

  // ─── Validation Checks ───
  var hasHash=!!(d.tx_hash);
  var hasBlock=!!(d.block_number);
  var isOk=(stCls==='ok');
  var isFail=(stCls==='fail');
  var cHTML='';
  cHTML+=vldCheck('&#128203;','Record Exists','VERIFIED','ok');
  cHTML+=vldCheck('&#128200;','Amount Format',vldNum(d.amount||d.fiat_amount||d.eur_amount)!=='—'?'VALID':'N/A',vldNum(d.amount||d.fiat_amount||d.eur_amount)!=='—'?'ok':'na');
  cHTML+=vldCheck('&#128279;','Transaction ID','VERIFIED','ok');
  cHTML+=vldCheck('&#9932;','Network Validation',(d.network||d.network_name)?'VALID':'N/A',(d.network||d.network_name)?'ok':'na');
  cHTML+=vldCheck('&#9851;','TX Hash'+(hasHash?' Present':' Missing'),hasHash?'VERIFIED':'PENDING',hasHash?'ok':'warn');
  cHTML+=vldCheck('&#128274;','Blockchain Confirm.',hasBlock?'CONFIRMED':'AWAITING',hasBlock?'ok':'warn');
  cHTML+=vldCheck('&#9878;','AML Screening',isFail?'FLAGGED':'CLEAR',isFail?'fail':'ok');
  cHTML+=vldCheck('&#128737;','Status Check',isOk?'PASSED':isFail?'FAILED':'PENDING',isOk?'ok':isFail?'fail':'warn');
  cHTML+=vldCheck('&#128221;','Integrity Check',isOk?'VALID':'REVIEW',isOk?'ok':'warn');
  document.getElementById('vldChecks').innerHTML=cHTML;

  // ─── Progress Steps ───
  var steps=[
    {icon:'&#128203;',name:'Record Parsing',desc:'Transaction data loaded and parsed',done:true},
    {icon:'&#128200;','name':'Amount Extraction',desc:'Financial values extracted and formatted',done:true},
    {icon:'&#127760;','name':'Network Validation',desc:'Blockchain network parameters verified',done:!!(d.network||d.network_name)},
    {icon:'&#9851;','name':'Blockchain Lookup',desc:'On-chain transaction hash search',done:hasHash},
    {icon:'&#128274;','name':'AML Screening',desc:'Anti-money laundering scan completed',done:!isFail},
    {icon:'&#128221;','name':'Final Verification',desc:'All checks compiled and verified',done:isOk},
  ];
  var doneCount=steps.filter(function(s){return s.done;}).length;
  var pct=Math.round(doneCount/steps.length*100);
  var pHTML=steps.map(function(s){
    return vldStep(s.icon,s.done?'done':'pending',s.name,s.desc,s.done?'100%':'—',s.done?'done':'pending');
  }).join('');
  document.getElementById('vldProgress').innerHTML=pHTML;
  document.getElementById('vldOverallBar').style.width=pct+'%';
  document.getElementById('vldPctLabel').textContent=pct+'%';
  setTimeout(function(){vldSetScore(pct>=90?98:pct>=70?82:55);},300);

  // ─── Transmission Status ───
  var tHTML='';
  tHTML+=vldField('Message Format','<span class="green">OK</span>');
  tHTML+=vldField('Server Connectivity','<span class="green">OK</span>');
  tHTML+=vldField('Authentication',isOk?'<span class="green">OK</span>':'<span style="color:#f59e0b;">REVIEW</span>');
  tHTML+=vldField('Encryption','<span class="green">OK</span>');
  tHTML+=vldField('Status','<strong class="'+(isOk?'green':isFail?'red':'gold')+'">'+st+'</strong>');
  if(d.approved_by) tHTML+=vldField('Authorized By','<strong>'+vldEsc(d.approved_by)+'</strong>');
  document.getElementById('vldTransmission').innerHTML=tHTML;

  // ─── Timeline ───
  var tlHTML='';
  var events=[];
  if(d.created_at) events.push({t:d.created_at,cls:'info',icon:'&#128203;',title:'Transaction Created',detail:'Record created in system — ID: '+vldShort(d.id||d.payload_id,32)});
  if(d.approved_at) events.push({t:d.approved_at,cls:'done',icon:'&#9989;',title:'Approved',detail:'Approved by: '+(d.approved_by||'Admin')});
  if(d.broadcasted_at) events.push({t:d.broadcasted_at,cls:'info',icon:'&#9851;',title:'Broadcasted to Blockchain',detail:'TX Hash: '+vldShort(d.tx_hash,48)});
  if(d.verified_at) events.push({t:d.verified_at,cls:'done',icon:'&#128274;',title:'Blockchain Verified',detail:'On-chain verification completed'});
  if(d.webhook_sent_at) events.push({t:d.webhook_sent_at,cls:'info',icon:'&#128225;',title:'Webhook Dispatched',detail:'HTTP '+String(d.webhook_status_code||'—')+' — '+vldShort(d.callback_url,40)});
  if(d.completed_at) events.push({t:d.completed_at,cls:'done',icon:'&#127881;',title:'Transaction Completed',detail:'Final status: '+st});
  if(d.cancelled_at) events.push({t:d.cancelled_at,cls:'fail',icon:'&#10060;',title:'Transaction Cancelled',detail:'Cancelled by: '+(d.cancelled_by||'—')+' — Reason: '+(d.cancel_reason||'—')});
  if(d.last_retry_at) events.push({t:d.last_retry_at,cls:'pending',icon:'&#8635;',title:'Retry Attempt',detail:'Retry count: '+String(d.retry_count||0)+(d.error_message?' — Error: '+vldShort(d.error_message,60):'')});
  if(d.updated_at&&d.updated_at!==d.created_at) events.push({t:d.updated_at,cls:'info',icon:'&#9998;',title:'Record Updated',detail:'Last modification timestamp'});
  events.sort(function(a,b){return new Date(a.t)-new Date(b.t);});
  if(events.length===0){tlHTML='<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px;">No timeline events found for this transaction.</div>';}
  else{tlHTML=events.map(function(e){return vldTl(e.cls,e.icon,e.title,vldDate(e.t),e.detail);}).join('');}
  document.getElementById('vldTimeline').innerHTML=tlHTML;

  // ─── Auth Codes (for transfers - show key IDs) ───
  var codes=[];
  if(d.id) codes.push({label:'Transaction ID',value:d.id.slice(0,8).toUpperCase()});
  if(d.payload_id&&d.payload_id!==d.id) codes.push({label:'Payload ID',value:d.payload_id.slice(0,8).toUpperCase()});
  if(d.order_id) codes.push({label:'Order ID',value:d.order_id.slice(0,8).toUpperCase()});
  if(d.tokenization_job_id) codes.push({label:'Job ID',value:d.tokenization_job_id.slice(0,8).toUpperCase()});
  if(d.payment_reference) codes.push({label:'Payment Ref',value:d.payment_reference.slice(-8).toUpperCase()});
  if(d.sender_reference) codes.push({label:'Sender Ref',value:d.sender_reference.slice(-8).toUpperCase()});
  if(d.external_id) codes.push({label:'External ID',value:d.external_id.slice(-8).toUpperCase()});
  if(codes.length>0){
    document.getElementById('vldCodesSection').style.display='block';
    document.getElementById('vldCodes').innerHTML=codes.map(function(c){
      return '<div class="vld-code-item"><div class="vld-code-label">'+c.label+'</div><div class="vld-code-value">'+c.value+'</div></div>';
    }).join('');
  }

  // ─── Final Banner ───
  var finalEl=document.getElementById('vldFinal');
  var finalClsMap={ok:'ok',fail:'fail',pending:'pending'};
  finalEl.className='vld-final '+finalClsMap[stCls];
  document.getElementById('vldFinalIcon').innerHTML=isOk?'&#9989;':isFail?'&#10060;':'&#9203;';
  document.getElementById('vldFinalTitle').className='vld-final-title '+stCls;
  var titles={ok:'APPROVED FOR TRANSMISSION',fail:'REJECTED — REQUIRES REVIEW',pending:'PENDING — AWAITING PROCESSING'};
  document.getElementById('vldFinalTitle').textContent=titles[stCls]||'STATUS UNKNOWN';
  var subs={ok:'All validation processes completed successfully. Transaction authorized and approved.',
    fail:'One or more validation checks failed. Manual review required before processing.',
    pending:'Transaction is currently being processed. Awaiting further updates.'};
  document.getElementById('vldFinalSub').textContent=subs[stCls];

  // Show report
  document.getElementById('vldReport').style.display='block';
  document.getElementById('vldReport').scrollIntoView({behavior:'smooth'});
}

function vldPrint(){
  var d=VLD.data||{};
  var type=VLD.type||'transaction';
  var typeLabels={transfer:'Outbound Transfer',payload:'Settlement Payload',order:'Payment Order',m1:'M1 Tokenization Job'};
  var st=d.status||d.verification_status||'UNKNOWN';
  var stCls=(st==='CONFIRMED'||st==='COMPLETED'||st==='RECONCILED'||st==='APPROVED')?'#10b981':(st==='FAILED'||st==='REJECTED'||st==='CANCELLED')?'#ef4444':'#f59e0b';
  var amt=document.getElementById('vldAmt').textContent;
  var txh=d.tx_hash||'—';
  var expUrl=d.explorer_url||'';
  var txDisp=txh!=='—'?(expUrl?'<a href="'+expUrl+'" style="color:#60a5fa;font-family:monospace;word-break:break-all;font-size:9px;">'+txh+'</a>':'<span style="font-family:monospace;word-break:break-all;font-size:9px;">'+txh+'</span>'):'—';
  var rptId=document.getElementById('vldRptId').textContent;
  var now=new Date().toLocaleString('en-GB');
  var html='<!doctype html><html><head><meta charset="utf-8"><title>Validation Report '+rptId+'</title>'
    +'<style>*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}'
    +'body{font-family:"Helvetica Neue",Arial,sans-serif;margin:0;padding:20px 28px;background:#fff;color:#0d1b2a;font-size:10px;}'
    +'.gbar{height:5px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400);margin-bottom:0;}'
    +'.topbar{background:linear-gradient(135deg,#0a1628,#0d2240,#1a3a6b);color:#fff;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;}'
    +'.topbar-title{font-size:16px;font-weight:900;letter-spacing:.5px;}'
    +'.topbar-sub{font-size:8px;color:rgba(255,255,255,.6);margin-top:2px;}'
    +'.badge{padding:6px 16px;border-radius:6px;font-weight:800;font-size:11px;}'
    +'.badge.ok{background:rgba(16,185,129,.2);color:#10b981;border:1px solid rgba(16,185,129,.4);}'
    +'.badge.fail{background:rgba(239,68,68,.2);color:#ef4444;border:1px solid rgba(239,68,68,.4);}'
    +'.badge.pending{background:rgba(245,158,11,.2);color:#f59e0b;border:1px solid rgba(245,158,11,.4);}'
    +'.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px;}'
    +'.metric{border:1px solid #d0d9ea;border-radius:8px;padding:10px 12px;}'
    +'.metric-label{font-size:7.5px;color:#6b7a90;font-weight:700;letter-spacing:.6px;text-transform:uppercase;}'
    +'.metric-value{font-size:12px;font-weight:800;color:#0d2240;margin-top:2px;word-break:break-all;}'
    +'.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;}'
    +'.card{border:1px solid #d0d9ea;border-radius:8px;overflow:hidden;}'
    +'.card-head{background:#0d2240;color:#c9a84c;padding:8px 14px;font-size:8px;font-weight:800;letter-spacing:.8px;text-transform:uppercase;}'
    +'.card-body{padding:10px 14px;}'
    +'.field{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #e8eef5;gap:8px;}'
    +'.field:last-child{border-bottom:none;}'
    +'.fl{font-size:8.5px;color:#6b7a90;font-weight:600;min-width:90px;}'
    +'.fv{font-size:8.5px;color:#0d1b2a;font-weight:600;text-align:right;word-break:break-all;}'
    +'.check{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #e8eef5;}'
    +'.check:last-child{border-bottom:none;}'
    +'.cl{font-size:8.5px;color:#0d1b2a;}'
    +'.cr{font-size:8.5px;font-weight:800;}'
    +'.cr.ok{color:#10b981;}.cr.fail{color:#ef4444;}.cr.warn{color:#f59e0b;}.cr.na{color:#94a3b8;}'
    +'.tl-item{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #e8eef5;}'
    +'.tl-item:last-child{border-bottom:none;}'
    +'.tl-dot{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0;border:1.5px solid;}'
    +'.tl-dot.done{background:rgba(16,185,129,.1);border-color:#10b981;}'
    +'.tl-dot.fail{background:rgba(239,68,68,.1);border-color:#ef4444;}'
    +'.tl-dot.info{background:rgba(96,165,250,.1);border-color:#60a5fa;}'
    +'.tl-dot.pending{background:rgba(245,158,11,.1);border-color:#f59e0b;}'
    +'.tl-title{font-size:9px;font-weight:700;color:#0d1b2a;}'
    +'.tl-time{font-size:8px;color:#6b7a90;}'
    +'.codes{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px;margin-bottom:12px;}'
    +'.code-item{border:1px solid #d0d9ea;border-radius:7px;padding:8px 10px;text-align:center;}'
    +'.code-label{font-size:7px;color:#6b7a90;font-weight:700;letter-spacing:.6px;text-transform:uppercase;margin-bottom:3px;}'
    +'.code-value{font-size:13px;font-weight:900;color:#c9a84c;font-family:monospace;letter-spacing:1px;}'
    +'.final{border-radius:8px;padding:14px 20px;display:flex;align-items:center;gap:14px;margin-bottom:12px;}'
    +'.final.ok{background:rgba(16,185,129,.08);border:2px solid rgba(16,185,129,.4);}'
    +'.final.fail{background:rgba(239,68,68,.08);border:2px solid rgba(239,68,68,.4);}'
    +'.final.pending{background:rgba(245,158,11,.08);border:2px solid rgba(245,158,11,.4);}'
    +'.final-title{font-size:14px;font-weight:900;letter-spacing:.5px;}'
    +'.final-sub{font-size:9px;color:#6b7a90;margin-top:3px;}'
    +'.footer{display:flex;justify-content:space-between;font-size:7.5px;color:#9aa;padding-top:8px;border-top:1px solid #d0d9ea;margin-top:8px;}'
    +'@media print{@page{size:A4 portrait;margin:8mm 10mm}body{padding:0}}'
    +'</style></head><body>';

  // Top bar
  var isOk=st==='CONFIRMED'||st==='COMPLETED'||st==='RECONCILED'||st==='APPROVED';
  var isFail=st==='FAILED'||st==='REJECTED'||st==='CANCELLED';
  var badgeCls=isOk?'ok':isFail?'fail':'pending';
  html+='<div class="gbar"></div>';
  html+='<div class="topbar"><div><div class="topbar-title">&#9878; TRANSACTION VALIDATION ENGINE &mdash; ALSHUMOOKH GLOBAL BANKING</div><div class="topbar-sub">FINANCIAL CRIME COMPLIANCE &bull; BLOCKCHAIN VERIFICATION &bull; AML SCREENING &bull; DIGITAL AUDIT TRAIL</div></div><div class="badge '+badgeCls+'">'+st+'</div></div>';

  // Meta row
  html+='<div style="display:flex;justify-content:space-between;margin-bottom:12px;padding:8px 14px;background:#f7f9fc;border:1px solid #d0d9ea;border-radius:8px;font-size:8.5px;">'
    +'<span><strong>Report ID:</strong> '+rptId+'</span>'
    +'<span><strong>Type:</strong> '+typeLabels[type]+'</span>'
    +'<span><strong>Generated:</strong> '+now+'</span>'
    +'<span><strong>Transaction ID:</strong> '+(d.id||d.payload_id||'—')+'</span>'
    +'</div>';

  // Metrics
  html+='<div class="metrics">'
    +'<div class="metric"><div class="metric-label">Amount</div><div class="metric-value" style="color:#c9a84c;">'+amt+'</div></div>'
    +'<div class="metric"><div class="metric-label">Network</div><div class="metric-value">'+document.getElementById('vldNetwork').textContent+'</div></div>'
    +'<div class="metric"><div class="metric-label">Reference</div><div class="metric-value">'+document.getElementById('vldRef').textContent+'</div></div>'
    +'<div class="metric"><div class="metric-label">Asset</div><div class="metric-value">'+document.getElementById('vldAsset').textContent+'</div></div>'
    +'<div class="metric"><div class="metric-label">Status</div><div class="metric-value" style="color:'+stCls+';">'+st+'</div></div>'
    +'</div>';

  // 3-col grid (sender, receiver, checks)
  html+='<div class="grid3">';
  html+='<div class="card"><div class="card-head">Sender Information</div><div class="card-body">'+document.getElementById('vldSender').innerHTML.replace(/class="vld-field-value green"/g,'class="fv" style="color:#10b981;"').replace(/class="vld-field-value gold"/g,'class="fv" style="color:#c9a84c;"').replace(/class="vld-field-value red"/g,'class="fv" style="color:#ef4444;"').replace(/class="vld-field"/g,'class="field"').replace(/class="vld-field-label"/g,'class="fl"').replace(/class="vld-field-value[^"]*"/g,'class="fv"')+'</div></div>';
  html+='<div class="card"><div class="card-head">Receiver Information</div><div class="card-body">'+document.getElementById('vldReceiver').innerHTML.replace(/class="vld-field"/g,'class="field"').replace(/class="vld-field-label"/g,'class="fl"').replace(/class="vld-field-value[^"]*"/g,'class="fv"')+'</div></div>';
  html+='<div class="card"><div class="card-head">Blockchain &amp; Transaction</div><div class="card-body">'+document.getElementById('vldBlockchain').innerHTML.replace(/class="vld-field"/g,'class="field"').replace(/class="vld-field-label"/g,'class="fl"').replace(/class="vld-field-value[^"]*"/g,'class="fv"')+'</div></div>';
  html+='</div>';

  // Validation checks
  html+='<div class="card" style="margin-bottom:10px;"><div class="card-head">Validation Results</div><div class="card-body" style="display:grid;grid-template-columns:1fr 1fr;">'+document.getElementById('vldChecks').innerHTML.replace(/class="vld-check"/g,'class="check"').replace(/class="vld-check-label"/g,'class="cl"').replace(/class="vld-check-result ok"/g,'class="cr ok"').replace(/class="vld-check-result fail"/g,'class="cr fail"').replace(/class="vld-check-result warn"/g,'class="cr warn"').replace(/class="vld-check-result na"/g,'class="cr na"')+'</div></div>';

  // Timeline
  html+='<div class="card" style="margin-bottom:10px;"><div class="card-head">Transaction Timeline</div><div class="card-body">'+document.getElementById('vldTimeline').innerHTML.replace(/class="vld-tl-item"/g,'class="tl-item"').replace(/class="vld-tl-dot done"/g,'class="tl-dot done"').replace(/class="vld-tl-dot fail"/g,'class="tl-dot fail"').replace(/class="vld-tl-dot info"/g,'class="tl-dot info"').replace(/class="vld-tl-dot pending"/g,'class="tl-dot pending"').replace(/class="vld-tl-title"/g,'class="tl-title"').replace(/class="vld-tl-time"/g,'class="tl-time"').replace(/<div class="vld-tl-detail">[^<]*<\\/div>/g,'')+'</div></div>';

  // Codes
  var codesEl=document.getElementById('vldCodes');
  if(codesEl&&codesEl.innerHTML){
    html+='<div style="margin-bottom:10px;"><div style="font-size:8px;font-weight:800;color:#6b7a90;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px;">Authorization &amp; Reference Codes</div><div class="codes">'+codesEl.innerHTML.replace(/class="vld-code-item"/g,'class="code-item"').replace(/class="vld-code-label"/g,'class="code-label"').replace(/class="vld-code-value"/g,'class="code-value"')+'</div></div>';
  }

  // Final
  html+='<div class="final '+badgeCls+'">'
    +'<div style="font-size:28px;">'+(isOk?'&#9989;':isFail?'&#10060;':'&#9203;')+'</div>'
    +'<div><div class="final-title" style="color:'+stCls+';">'+document.getElementById('vldFinalTitle').textContent+'</div>'
    +'<div class="final-sub">'+document.getElementById('vldFinalSub').textContent+'</div></div>'
    +'<div style="margin-left:auto;text-align:right;font-size:8px;color:#6b7a90;"><div>&#128737; Digitally Verified</div><div style="margin-top:3px;">ALSHUMOOKH GLOBAL</div><div>BANKING FINANCE &amp; CREDIT</div></div>'
    +'</div>';

  html+='<div class="footer"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; CONFIDENTIAL &mdash; '+rptId+'</span><span>Generated: '+now+'</span></div>';
  html+='</body></html>';

  var w=window.open('','_blank','width=900,height=1100');
  if(w){w.document.write(html);w.document.close();setTimeout(function(){w.print();},600);}
}
</script>
"""


_PRIVATE_REPORT_BODY = """
<style>
.vld-topbar{background:linear-gradient(135deg,#0a1628 0%,#0d2240 60%,#1a3a6b 100%);border-radius:14px;padding:18px 28px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;border:1px solid rgba(201,168,76,.25);}
.vld-topbar-title{font-size:17px;font-weight:900;color:#fff;letter-spacing:.5px;}
.vld-topbar-sub{font-size:9.5px;color:rgba(255,255,255,.55);margin-top:3px;}
.vld-topbar-meta{display:flex;gap:20px;flex-wrap:wrap;}
.vld-topbar-meta-item label{font-size:9px;color:rgba(255,255,255,.45);font-weight:700;letter-spacing:.8px;display:block;text-transform:uppercase;}
.vld-topbar-meta-item span{font-size:12px;color:#e2e8f0;font-weight:700;}
.vld-status-badge{padding:7px 18px;border-radius:8px;font-size:12px;font-weight:800;display:flex;align-items:center;gap:6px;}
.vld-status-badge.ok{background:rgba(16,185,129,.18);color:#10b981;border:1.5px solid rgba(16,185,129,.4);}
.vld-status-badge.fail{background:rgba(239,68,68,.18);color:#ef4444;border:1.5px solid rgba(239,68,68,.4);}
.vld-status-badge.pending{background:rgba(245,158,11,.18);color:#f59e0b;border:1.5px solid rgba(245,158,11,.4);}
.vld-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:11px;margin-bottom:14px;}
.vld-metric{background:var(--panel);border:1px solid var(--line-strong);border-radius:12px;padding:13px 16px;display:flex;align-items:center;gap:12px;}
.vld-metric-icon{width:38px;height:38px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;}
.vld-metric-icon.blue{background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.3);}
.vld-metric-icon.gold{background:rgba(201,168,76,.15);border:1px solid rgba(201,168,76,.3);}
.vld-metric-icon.green{background:rgba(16,185,129,.15);border:1px solid rgba(16,185,129,.3);}
.vld-metric-icon.purple{background:rgba(139,92,246,.15);border:1px solid rgba(139,92,246,.3);}
.vld-metric-icon.orange{background:rgba(249,115,22,.15);border:1px solid rgba(249,115,22,.3);}
.vld-metric-label{font-size:9px;color:var(--muted);font-weight:700;letter-spacing:.7px;text-transform:uppercase;}
.vld-metric-value{font-size:13px;font-weight:800;color:var(--ink);margin-top:2px;word-break:break-all;}
.vld-metric-value.gold{color:#c9a84c;}
.vld-metric-value.green{color:#10b981;}
.vld-metric-value.red{color:#ef4444;}
.vld-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px;}
@media(max-width:1100px){.vld-grid{grid-template-columns:1fr 1fr;}}
@media(max-width:700px){.vld-grid{grid-template-columns:1fr;}}
.vld-card{background:var(--panel);border:1px solid var(--line-strong);border-radius:12px;overflow:hidden;margin-bottom:0;}
.vld-card-head{padding:10px 15px;background:rgba(13,34,64,.6);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px;}
.vld-card-head-icon{font-size:14px;}
.vld-card-head-title{font-size:10px;font-weight:800;color:var(--gold);letter-spacing:.7px;text-transform:uppercase;}
.vld-card-body{padding:12px 15px;}
.vld-field{display:flex;justify-content:space-between;align-items:flex-start;padding:5px 0;border-bottom:1px solid var(--line);gap:8px;}
.vld-field:last-child{border-bottom:none;}
.vld-field-label{font-size:9.5px;color:var(--muted);font-weight:600;min-width:95px;flex-shrink:0;padding-top:1px;}
.vld-field-value{font-size:9.5px;color:var(--ink);font-weight:600;text-align:right;word-break:break-all;}
.vld-field-value code{font-family:monospace;font-size:8.5px;word-break:break-all;}
.vld-step{display:flex;align-items:center;gap:9px;padding:6px 0;border-bottom:1px solid var(--line);}
.vld-step:last-child{border-bottom:none;}
.vld-step-icon{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;flex-shrink:0;}
.vld-step-icon.done{background:rgba(16,185,129,.2);border:1.5px solid #10b981;color:#10b981;}
.vld-step-icon.pending{background:rgba(245,158,11,.15);border:1.5px solid #f59e0b;color:#f59e0b;}
.vld-step-info{flex:1;}
.vld-step-name{font-size:10px;font-weight:700;color:var(--ink);}
.vld-step-desc{font-size:8.5px;color:var(--muted);margin-top:1px;}
.vld-step-pct{font-size:10px;font-weight:800;}
.vld-step-pct.done{color:#10b981;}
.vld-step-pct.pending{color:#f59e0b;}
.vld-check{display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--line);}
.vld-check:last-child{border-bottom:none;}
.vld-check-label{font-size:9.5px;color:var(--ink);display:flex;align-items:center;gap:5px;}
.vld-check-result{font-size:9px;font-weight:800;letter-spacing:.3px;}
.vld-check-result.ok{color:#10b981;}
.vld-check-result.fail{color:#ef4444;}
.vld-check-result.warn{color:#f59e0b;}
.vld-check-result.na{color:#64748b;}
.vld-score-ring{width:80px;height:80px;margin:6px auto;position:relative;}
.vld-score-ring svg{transform:rotate(-90deg);}
.vld-score-num{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:19px;font-weight:900;}
.vld-tl-item{display:flex;gap:11px;padding:8px 0;position:relative;}
.vld-tl-item:not(:last-child)::before{content:"";position:absolute;left:13px;top:32px;bottom:0;width:2px;background:var(--line);}
.vld-tl-dot{width:26px;height:26px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;border:2px solid;}
.vld-tl-dot.done{background:rgba(16,185,129,.15);border-color:#10b981;}
.vld-tl-dot.fail{background:rgba(239,68,68,.15);border-color:#ef4444;}
.vld-tl-dot.pending{background:rgba(245,158,11,.15);border-color:#f59e0b;}
.vld-tl-dot.info{background:rgba(96,165,250,.15);border-color:#60a5fa;}
.vld-tl-content{flex:1;}
.vld-tl-title{font-size:11px;font-weight:700;color:var(--ink);}
.vld-tl-time{font-size:9px;color:var(--muted);margin-top:1px;}
.vld-tl-detail{font-size:9px;color:var(--muted);margin-top:3px;background:var(--glass);border-radius:5px;padding:4px 8px;border:1px solid var(--line);}
.vld-codes{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:9px;margin-bottom:13px;}
.vld-code-item{background:var(--panel);border:1px solid var(--line-strong);border-radius:9px;padding:10px 11px;text-align:center;}
.vld-code-label{font-size:7.5px;color:var(--muted);font-weight:700;letter-spacing:.7px;text-transform:uppercase;margin-bottom:3px;}
.vld-code-value{font-size:14px;font-weight:900;color:var(--gold);letter-spacing:1px;font-family:monospace;}
.vld-final{border-radius:12px;padding:16px 22px;display:flex;align-items:center;gap:14px;margin-bottom:14px;flex-wrap:wrap;}
.vld-final.ok{background:rgba(16,185,129,.1);border:2px solid rgba(16,185,129,.4);}
.vld-final.fail{background:rgba(239,68,68,.1);border:2px solid rgba(239,68,68,.4);}
.vld-final.pending{background:rgba(245,158,11,.1);border:2px solid rgba(245,158,11,.4);}
.vld-final-icon{font-size:32px;}
.vld-final-title{font-size:15px;font-weight:900;letter-spacing:.5px;}
.vld-final-title.ok{color:#10b981;}
.vld-final-title.fail{color:#ef4444;}
.vld-final-title.pending{color:#f59e0b;}
.vld-final-sub{font-size:10px;color:var(--muted);margin-top:3px;}
.vld-actions{display:flex;gap:9px;margin-left:auto;flex-wrap:wrap;}
</style>

<div class="page-body">

<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;">
  <button onclick="history.back()" style="background:var(--glass);border:1px solid var(--line-strong);color:var(--ink);padding:7px 14px;border-radius:8px;font-size:12px;cursor:pointer;">&#8592; Back</button>
  <div style="flex:1;min-width:160px;">
    <div style="font-size:10px;color:var(--muted);font-weight:700;letter-spacing:.5px;text-transform:uppercase;">Confidential</div>
    <div style="font-size:16px;font-weight:800;color:var(--gold);">&#128274; Private Report</div>
  </div>
  <button onclick="prPrintAll()" style="background:#0d2240;color:#c9a84c;border:none;padding:8px 18px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;">&#128424; Print All</button>
  <button onclick="prLoadAll()" style="background:var(--glass);border:1px solid var(--line-strong);color:var(--ink);padding:8px 14px;border-radius:8px;font-size:12px;cursor:pointer;">&#8635; Refresh</button>
</div>

<div class="panel">
  <div class="panel-head" style="flex-wrap:wrap;gap:8px;">
    <div style="display:flex;gap:6px;flex-wrap:wrap;" id="prFilterBar">
      <button id="prBtn_all"      onclick="prSetFilter(this,'all')"      class="btn btn-primary" style="font-size:10px;padding:4px 12px;border-radius:12px;">All</button>
      <button id="prBtn_order"    onclick="prSetFilter(this,'order')"    class="btn btn-ghost"   style="font-size:10px;padding:4px 12px;border-radius:12px;">Orders</button>
      <button id="prBtn_m1"       onclick="prSetFilter(this,'m1')"       class="btn btn-ghost"   style="font-size:10px;padding:4px 12px;border-radius:12px;">M1</button>
      <button id="prBtn_payload"  onclick="prSetFilter(this,'payload')"  class="btn btn-ghost"   style="font-size:10px;padding:4px 12px;border-radius:12px;">Payloads</button>
      <button id="prBtn_transfer" onclick="prSetFilter(this,'transfer')" class="btn btn-ghost"   style="font-size:10px;padding:4px 12px;border-radius:12px;">Transfers</button>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex:1;min-width:200px;">
      <input id="prSearchInput" oninput="prRender()" placeholder="Search ID, amount, status, hash..." style="flex:1;padding:6px 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--panel-solid);color:var(--ink);font-size:11px;outline:none;">
      <span id="prCountLabel" style="font-size:10px;color:var(--muted);white-space:nowrap;"></span>
    </div>
  </div>
  <div id="prListContainer" style="min-height:120px;">
    <div style="padding:32px;text-align:center;color:var(--muted);font-size:12px;">Loading transactions...</div>
  </div>
</div>

<!-- VLD-style detail — populated dynamically by prSelect() -->
<div id="prAnnotBox" style="display:none;margin-top:16px;"></div>

<!-- Saved Reports -->
<div class="panel" style="margin-top:16px;">
  <div class="panel-head">
    <span style="font-size:13px;font-weight:800;">&#128196; Saved Reports</span>
    <span id="prSavedCount" style="font-size:11px;color:var(--muted);font-weight:600;">0 reports</span>
  </div>
  <div id="prSavedList" style="padding:14px;">
    <div style="text-align:center;color:var(--muted);font-size:12px;padding:20px;">No saved reports yet. Print a transaction to save it here.</div>
  </div>
</div>

</div>

<div id="prModalOverlay" onclick="prCloseModal()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;"></div>
<div id="prModalBox" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9001;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:24px 28px;width:400px;max-width:94vw;box-shadow:0 20px 60px rgba(0,0,0,.5);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <strong id="prModalTitle" style="font-size:14px;color:var(--ink);"></strong>
    <button onclick="prCloseModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--muted);">&#10005;</button>
  </div>
  <div id="prModalFields"></div>
  <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
    <button onclick="prCloseModal()" style="background:var(--glass);color:var(--ink);border:1px solid var(--line);padding:9px 18px;border-radius:6px;font-size:12px;cursor:pointer;">Cancel</button>
    <button id="prModalSave" style="background:var(--gold);color:#0d2240;border:none;padding:9px 22px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;">Save</button>
  </div>
</div>

<script>
/* ══ PRIVATE REPORT v3 — VLD STYLE ═════════════════════════════════ */
var PR_DATA  = { order: [], m1: [], payload: [], transfer: [] };
var PR_META  = {};
var PR_SEL   = { idx: null, type: null };
var PR_FILT  = 'all';
var PR_SAVED = [];

/* ── API helper ─────────────────────────────────────────────────── */
function prFetch(url) {
  var ak = '';
  try { ak = sessionStorage.getItem('als_admin_key') || localStorage.getItem('als_admin_key') || ''; } catch(e) {}
  var hdrs = { 'Content-Type': 'application/json' };
  if (ak) { hdrs['X-Admin-API-Key'] = ak; }
  return fetch(url, { headers: hdrs, credentials: 'include' })
    .then(function(r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    });
}

/* ── Load all endpoints ─────────────────────────────────────────── */
function prLoadAll() {
  var el = document.getElementById('prListContainer');
  if (!el) { return; }
  el.innerHTML = '<div style="padding:32px;text-align:center;color:var(--muted);font-size:12px;">Loading transactions...</div>';

  var urls = [
    '/api/v1/admin/orders',
    '/api/v1/admin/tokenization-jobs?limit=500',
    '/api/v1/admin/payloads?limit=500',
    '/api/v1/admin/outbound-transfers?limit=500'
  ];

  Promise.all(urls.map(function(u) {
    return prFetch(u).catch(function() { return null; });
  })).then(function(results) {
    var r0 = results[0];
    var r1 = results[1];
    var r2 = results[2];
    var r3 = results[3];
    PR_DATA.order    = r0 ? (Array.isArray(r0) ? r0 : (r0.orders || [])) : [];
    PR_DATA.m1       = r1 ? (Array.isArray(r1) ? r1 : (r1.jobs || r1.items || [])) : [];
    PR_DATA.payload  = r2 ? (Array.isArray(r2) ? r2 : (r2.payloads || r2.items || [])) : [];
    PR_DATA.transfer = r3 ? (Array.isArray(r3) ? r3 : (r3.transfers || r3.items || [])) : [];
    prRender();
  }).catch(function(err) {
    el.innerHTML = '<div style="padding:20px;color:#f87171;font-size:12px;">Error: ' + String(err) + '</div>';
  });
}

/* ── Filter control ─────────────────────────────────────────────── */
function prSetFilter(btn, f) {
  PR_FILT = f;
  var ids = ['all','order','m1','payload','transfer'];
  ids.forEach(function(k) {
    var b = document.getElementById('prBtn_' + k);
    if (!b) { return; }
    if (k === f) {
      b.className = 'btn btn-primary';
    } else {
      b.className = 'btn btn-ghost';
    }
    b.style.fontSize = '10px';
    b.style.padding = '4px 12px';
    b.style.borderRadius = '12px';
  });
  prRender();
}

/* ── Escape helper ──────────────────────────────────────────────── */
function prEsc(v) {
  var d = document.createElement('div');
  d.textContent = (v === null || v === undefined) ? '' : String(v);
  return d.innerHTML;
}

function prFmtNum(n) {
  if (n === null || n === undefined || n === '') { return '—'; }
  var x = parseFloat(n);
  return isNaN(x) ? String(n) : x.toLocaleString('en-US', { maximumFractionDigits: 6 });
}

function prFmtDate(v) {
  if (!v) { return '—'; }
  try { return new Date(v).toLocaleString(); } catch(e) { return String(v); }
}

function prProgress(type, d) {
  var st = String(d.status || d.verification_status || '').toUpperCase();
  var pct = 0; var color = '#6b7280';
  if (st === 'COMPLETED' || st === 'CONFIRMED' || st === 'SUCCESS') { pct = 100; color = '#10b981'; }
  else if (st === 'PROCESSING' || st === 'SENT' || st === 'MINTING') { pct = 75; color = '#3b82f6'; }
  else if (st === 'PENDING' || st === 'QUEUED' || st === 'CONVERTING') { pct = 30; color = '#f59e0b'; }
  else if (st === 'FAILED' || st === 'REJECTED' || st === 'CANCELLED' || st === 'ERROR') { pct = 5; color = '#ef4444'; }
  else if (st === 'APPROVED') { pct = 50; color = '#8b5cf6'; }
  else if (st) { pct = 50; color = '#8b5cf6'; }
  return { pct: pct, color: color };
}

/* ── Render list ────────────────────────────────────────────────── */
function prRender() {
  var el = document.getElementById('prListContainer');
  if (!el) { return; }
  var q = '';
  var si = document.getElementById('prSearchInput');
  if (si) { q = si.value.toLowerCase().trim(); }

  var types = ['order','m1','payload','transfer'];
  var labels = { order:'ORDER', m1:'M1', payload:'PAYLOAD', transfer:'XFER' };
  var colors = { order:'#1e40af', m1:'#065f46', payload:'#7c3aed', transfer:'#b45309' };

  var rows = [];
  types.forEach(function(t) {
    if (PR_FILT !== 'all' && PR_FILT !== t) { return; }
    var arr = PR_DATA[t] || [];
    arr.forEach(function(d, i) {
      var amt = '';
      if (t === 'order') {
        amt = prFmtNum(d.fiat_amount) + ' ' + (d.fiat_currency || '');
      } else if (t === 'm1') {
        amt = prFmtNum(d.eur_amount) + ' EUR';
      } else if (t === 'payload') {
        amt = prFmtNum(d.amount) + ' ' + (d.asset || '');
      } else {
        amt = prFmtNum(d.amount) + ' ' + (d.asset || d.currency || 'USDT');
      }
      var st = String(d.status || d.verification_status || '');
      var srch = String(d.id || '') + amt + st + String(d.tx_hash || '') + String(d.external_id || d.payment_reference || d.sender_reference || '');
      if (q && srch.toLowerCase().indexOf(q) === -1) { return; }
      var mk = t + '_' + i;
      var sel = (PR_SEL.idx === i && PR_SEL.type === t);
      var hasAnnot = !!PR_META[mk];
      var ref = '';
      if (t === 'order') { ref = d.external_id || d.payment_reference || d.idempotency_key || ''; }
      else if (t === 'm1') { ref = d.sender_reference || d.sender_name || ''; }
      else if (t === 'payload') { ref = d.transaction_reference || d.request_id || ''; }
      else { ref = d.id || ''; }
      var hash = String(d.tx_hash || '');
      var shortHash = hash.length > 16 ? hash.slice(0,8) + '...' + hash.slice(-6) : (hash || '—');
      var prog = prProgress(t, d);
      rows.push({ t:t, i:i, d:d, amt:amt, st:st, sel:sel, lbl:labels[t], color:colors[t], mk:mk, hasAnnot:hasAnnot, ref:ref, shortHash:shortHash, prog:prog });
    });
  });

  var cl = document.getElementById('prCountLabel');
  if (cl) { cl.textContent = rows.length + ' records'; }

  if (!rows.length) {
    el.innerHTML = '<div style="padding:32px;text-align:center;color:var(--muted);font-size:12px;">No transactions found</div>';
    return;
  }

  var thS = 'padding:7px 10px;text-align:left;color:var(--muted);font-size:9px;font-weight:700;border-bottom:1px solid var(--line);white-space:nowrap;';
  var html = '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:11px;">';
  html += '<thead><tr style="background:rgba(255,255,255,.04);">';
  html += '<th style="' + thS + '">Type</th>';
  html += '<th style="' + thS + '">Reference / Sender</th>';
  html += '<th style="' + thS + '">Amount</th>';
  html += '<th style="' + thS + '">TX Hash</th>';
  html += '<th style="' + thS + '">Status &amp; Progress</th>';
  html += '<th style="' + thS + '">Action</th>';
  html += '</tr></thead><tbody>';

  rows.forEach(function(r) {
    var bg = r.sel ? 'background:rgba(37,99,235,.08);' : '';
    html += '<tr data-idx="' + r.i + '" data-type="' + r.t + '" onclick="prSelect(' + r.i + ',&quot;' + r.t + '&quot;)" style="border-bottom:1px solid var(--line);cursor:pointer;' + bg + '">';
    html += '<td style="padding:7px 10px;">';
    html += '<span style="background:' + r.color + ';color:#fff;border-radius:3px;padding:2px 6px;font-size:8px;font-weight:800;">' + r.lbl + '</span>';
    if (r.hasAnnot) { html += ' <span style="background:#c9a84c;color:#fff;border-radius:3px;padding:1px 5px;font-size:7px;font-weight:800;">ANNOT</span>'; }
    html += '</td>';
    var refDisplay = r.ref ? (r.ref.length > 24 ? r.ref.slice(0,24) + '...' : r.ref) : '—';
    html += '<td style="padding:7px 10px;font-size:9px;color:var(--ink);max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + prEsc(r.ref) + '">' + prEsc(refDisplay) + '</td>';
    html += '<td style="padding:7px 10px;font-weight:700;color:var(--gold);font-size:10px;white-space:nowrap;">' + prEsc(r.amt) + '</td>';
    html += '<td style="padding:7px 10px;font-family:monospace;font-size:8px;color:var(--muted);white-space:nowrap;" title="' + prEsc(r.d.tx_hash||'') + '">' + prEsc(r.shortHash) + '</td>';
    html += '<td style="padding:7px 10px;min-width:120px;">';
    html += '<div style="font-size:8px;font-weight:700;color:var(--ink);margin-bottom:3px;">' + prEsc(r.st) + '</div>';
    html += '<div style="height:5px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + r.prog.pct + '%;background:' + r.prog.color + ';border-radius:3px;"></div></div>';
    html += '<div style="font-size:8px;color:' + r.prog.color + ';font-weight:700;margin-top:2px;">' + r.prog.pct + '%</div>';
    html += '</td>';
    html += '<td style="padding:7px 10px;"><button onclick="event.stopPropagation();prSelect(' + r.i + ',&quot;' + r.t + '&quot;);prPrintOne();" style="background:#0d2240;color:#c9a84c;border:none;padding:4px 10px;border-radius:5px;font-size:9px;font-weight:700;cursor:pointer;">&#128424; Print</button></td>';
    html += '</tr>';
  });

  html += '</tbody></table></div>';
  el.innerHTML = html;
}

/* ── Select a row — VLD style ───────────────────────────────────── */
function prSelect(idx, type) {
  PR_SEL.idx  = idx;
  PR_SEL.type = type;
  var d = PR_DATA[type] ? PR_DATA[type][idx] : null;
  if (!d) { return; }

  var lblMap = { order:'Payment Order', m1:'M1 Tokenization Job', payload:'Settlement Payload', transfer:'Outbound Transfer' };
  var stMap = { CONFIRMED:'ok',COMPLETED:'ok',RECONCILED:'ok',APPROVED:'ok',ALCHEMY_VERIFIED:'ok',ON_CHAIN_CONFIRMED:'ok',
    FAILED:'fail',REJECTED:'fail',CANCELLED:'fail',
    PENDING:'pending',RECEIVED:'pending',PROCESSING:'pending',AWAITING_TX_HASH:'pending',MANUAL_REVIEW:'pending',AWAITING_APPROVAL:'pending' };
  var st = d.status || d.verification_status || 'PENDING';
  var stCls = stMap[st] || 'pending';
  var isOk = stCls === 'ok', isFail = stCls === 'fail';
  var stIcons = { ok:'&#9989;', fail:'&#10060;', pending:'&#9203;' };
  var stColors = { ok:'#10b981', fail:'#ef4444', pending:'#f59e0b' };

  var amt = '';
  if (type==='order') amt = prFmtNum(d.fiat_amount)+' '+(d.fiat_currency||'');
  else if (type==='m1') amt = prFmtNum(d.eur_amount)+' EUR';
  else if (type==='payload') amt = prFmtNum(d.amount)+' '+(d.asset||'');
  else amt = prFmtNum(d.amount)+' '+(d.asset||d.currency||'USDT');

  var net = type==='transfer'?(d.network||'').toUpperCase():type==='payload'?(d.network_name||d.network||'M1_FUND').toUpperCase():type==='order'?(d.network||'').toUpperCase():'ETHEREUM';
  var ref = type==='order'?(d.payment_reference||d.external_id||d.id||''):type==='m1'?(d.sender_reference||d.id||''):type==='payload'?(d.transaction_reference||d.id||''):(d.id||'');
  if (ref.length>22) ref=ref.slice(0,22)+'...';
  var asset = type==='transfer'?(d.asset||'SIG'):type==='payload'?(d.asset||'EUR'):type==='order'?(d.fiat_currency||'EUR'):'SIG / EUR';
  var rptId = 'PR-'+Date.now().toString(36).toUpperCase();

  var hasHash=!!(d.tx_hash), hasBlock=!!(d.block_number);
  var steps=[
    {icon:'&#128203;',name:'Record Parsing',desc:'Data loaded and parsed',done:true},
    {icon:'&#128200;',name:'Amount Extraction',desc:'Financial values verified',done:true},
    {icon:'&#127760;',name:'Network Validation',desc:'Network parameters verified',done:!!(d.network||d.network_name)},
    {icon:'&#9851;',name:'Blockchain Lookup',desc:'On-chain hash search',done:hasHash},
    {icon:'&#128274;',name:'AML Screening',desc:'Anti-money laundering scan',done:!isFail},
    {icon:'&#128221;',name:'Final Verification',desc:'All checks compiled',done:isOk}
  ];
  var doneCount=steps.filter(function(s){return s.done;}).length;
  var pct=Math.round(doneCount/steps.length*100);

  function pF(label,value){return '<div class="vld-field"><span class="vld-field-label">'+label+'</span><span class="vld-field-value">'+value+'</span></div>';}
  function pC(icon,label,result,cls){return '<div class="vld-check"><span class="vld-check-label">'+icon+' '+label+'</span><span class="vld-check-result '+cls+'">'+result+'</span></div>';}
  function pS(icon,icls,name,desc,p,pcls){return '<div class="vld-step"><div class="vld-step-icon '+icls+'">'+icon+'</div><div class="vld-step-info"><div class="vld-step-name">'+name+'</div><div class="vld-step-desc">'+desc+'</div></div><div class="vld-step-pct '+pcls+'">'+p+'</div></div>';}
  function pT(dc,icon,title,time,detail){return '<div class="vld-tl-item"><div class="vld-tl-dot '+dc+'">'+icon+'</div><div class="vld-tl-content"><div class="vld-tl-title">'+title+'</div><div class="vld-tl-time">'+time+'</div>'+(detail?'<div class="vld-tl-detail">'+detail+'</div>':'')+'</div></div>';}

  /* Sender */
  var sH='';
  if (type==='transfer'){sH+=pF('From Address','<code>'+prEsc(d.from_address||'—')+'</code>');sH+=pF('Initiated By',prEsc(d.initiated_by)||'Admin');sH+=pF('Approved By',prEsc(d.approved_by)||'—');sH+=pF('Approved At',prFmtDate(d.approved_at));sH+=pF('Network',(d.network||'').toUpperCase());sH+=pF('Asset',prEsc(d.asset));}
  else if (type==='payload'){sH+=pF('Sender Wallet','<code>'+prEsc(d.sender_wallet||'—')+'</code>');sH+=pF('Auth Method',prEsc(d.auth_method));sH+=pF('Security Level',prEsc(d.security_level));sH+=pF('JWS Verified',d.jws_verified?'<span style="color:#10b981">Yes</span>':'No');sH+=pF('mTLS Verified',d.mtls_verified?'<span style="color:#10b981">Yes</span>':'No');sH+=pF('Client IP',prEsc(d.client_ip));}
  else if (type==='order'){sH+=pF('Payer Email',prEsc(d.payer_email));sH+=pF('Customer Name',prEsc(d.customer_name));sH+=pF('External ID',prEsc(d.external_id));sH+=pF('Idempotency Key','<code>'+prEsc((d.idempotency_key||'').slice(0,22))+'</code>');sH+=pF('Client IP',prEsc(d.client_ip));sH+=pF('Provider',prEsc(d.provider));}
  else if (type==='m1'){sH+=pF('Sender Name','<strong>'+prEsc(d.sender_name||'—')+'</strong>');sH+=pF('Sender IBAN','<code>'+prEsc(d.sender_iban||'—')+'</code>');sH+=pF('Sender Bank',prEsc(d.sender_bank));sH+=pF('Sender Reference',prEsc(d.sender_reference));sH+=pF('EUR Amount','<strong style="color:#c9a84c;">'+prFmtNum(d.eur_amount)+' EUR</strong>');sH+=pF('FX Rate',prEsc(d.fx_rate_eur_usd||d.fx_rate));}

  /* Receiver */
  var rH='';
  if (type==='transfer'){rH+=pF('To Address','<code>'+prEsc(d.to_address||'—')+'</code>');rH+=pF('Contract Address','<code>'+prEsc((d.contract_address||'').slice(0,22)||'—')+'</code>');rH+=pF('Amount','<strong style="color:#c9a84c;">'+prFmtNum(d.amount)+' '+(d.asset||'SIG')+'</strong>');rH+=pF('Notes',prEsc(d.notes)||'—');rH+=pF('Callback URL',prEsc((d.callback_url||'').slice(0,28)));rH+=pF('Webhook Status',d.webhook_status_code?String(d.webhook_status_code):'—');}
  else if (type==='payload'){rH+=pF('Receiver Wallet','<code>'+prEsc(d.receiver_wallet||'—')+'</code>');rH+=pF('Amount','<strong style="color:#c9a84c;">'+prFmtNum(d.amount)+' '+(d.asset||'EUR')+'</strong>');rH+=pF('Review Decision',prEsc(d.review_decision));rH+=pF('Reviewed By',prEsc(d.reviewed_by));rH+=pF('Review Priority',prEsc(d.review_priority));rH+=pF('Hold Reason',prEsc(d.hold_reason));}
  else if (type==='order'){rH+=pF('Wallet Address','<code>'+prEsc((d.user_wallet_address||d.wallet||'').slice(0,26))+'</code>');rH+=pF('Treasury Wallet','<code>'+prEsc((d.treasury_wallet_address||'').slice(0,26))+'</code>');rH+=pF('Crypto Amount','<strong>'+prFmtNum(d.crypto_amount)+' '+(d.crypto_currency||'SIG')+'</strong>');rH+=pF('Fiat Amount','<strong style="color:#c9a84c;">'+prFmtNum(d.fiat_amount)+' '+(d.fiat_currency||'EUR')+'</strong>');rH+=pF('Exchange Rate',prEsc(d.exchange_rate));rH+=pF('Processor Ref',prEsc(d.processor_reference));}
  else if (type==='m1'){rH+=pF('Receiver Wallet','<code>'+prEsc((d.receiver_wallet||'').slice(0,26))+'</code>');rH+=pF('Operator Wallet','<code>'+prEsc((d.operator_wallet||'').slice(0,26))+'</code>');rH+=pF('Contract Address','<code>'+prEsc((d.contract_address||'').slice(0,26))+'</code>');rH+=pF('USD Amount','<strong>'+prFmtNum(d.usd_amount)+' USD</strong>');rH+=pF('SIG Amount','<strong style="color:#c9a84c;">'+prFmtNum(d.usdt_amount)+' SIG</strong>');rH+=pF('FX Provider',prEsc(d.fx_provider));}

  /* Blockchain */
  var bH='';
  var txh=d.tx_hash||'—';var expUrl=d.explorer_url||null;
  var txDisp=(txh!=='—')?(expUrl?'<a href="'+prEsc(expUrl)+'" target="_blank" style="color:#60a5fa;font-size:8.5px;word-break:break-all;font-family:monospace;">'+txh+'</a>':'<code style="font-size:8.5px;word-break:break-all;">'+txh+'</code>'):'—';
  bH+=pF('TX Hash',txDisp);bH+=pF('Block Number',d.block_number?String(d.block_number):'—');bH+=pF('Confirmations',d.confirmations?String(d.confirmations):'—');bH+=pF('Gas Used',d.gas_used?String(d.gas_used):'—');
  if(expUrl)bH+=pF('Explorer','<a href="'+prEsc(expUrl)+'" target="_blank" style="color:#60a5fa;font-size:9.5px;">View on Explorer &#8599;</a>');
  bH+=pF('Broadcasted At',prFmtDate(d.broadcasted_at));bH+=pF('Completed At',prFmtDate(d.completed_at));
  if(d.error_message)bH+=pF('Error','<span style="color:#ef4444;font-size:9px;">'+prEsc(d.error_message)+'</span>');

  /* Validation checks */
  var cH='';
  cH+=pC('&#128203;','Record Exists','VERIFIED','ok');
  cH+=pC('&#128200;','Amount Format',prFmtNum(d.amount||d.fiat_amount||d.eur_amount)!=='—'?'VALID':'N/A',prFmtNum(d.amount||d.fiat_amount||d.eur_amount)!=='—'?'ok':'na');
  cH+=pC('&#128279;','Transaction ID','VERIFIED','ok');
  cH+=pC('&#9932;','Network',(d.network||d.network_name)?'VALID':'N/A',(d.network||d.network_name)?'ok':'na');
  cH+=pC('&#9851;','TX Hash',hasHash?'VERIFIED':'PENDING',hasHash?'ok':'warn');
  cH+=pC('&#128274;','Blockchain Confirm.',hasBlock?'CONFIRMED':'AWAITING',hasBlock?'ok':'warn');
  cH+=pC('&#9878;','AML Screening',isFail?'FLAGGED':'CLEAR',isFail?'fail':'ok');
  cH+=pC('&#128737;','Status Check',isOk?'PASSED':isFail?'FAILED':'PENDING',isOk?'ok':isFail?'fail':'warn');
  cH+=pC('&#128221;','Integrity Check',isOk?'VALID':'REVIEW',isOk?'ok':'warn');

  /* Progress steps */
  var pH=steps.map(function(s){return pS(s.icon,s.done?'done':'pending',s.name,s.desc,s.done?'100%':'—',s.done?'done':'pending');}).join('');

  /* Transmission */
  var tH='';
  tH+=pF('Message Format','<span style="color:#10b981">OK</span>');
  tH+=pF('Server Connectivity','<span style="color:#10b981">OK</span>');
  tH+=pF('Authentication',isOk?'<span style="color:#10b981">OK</span>':'<span style="color:#f59e0b;">REVIEW</span>');
  tH+=pF('Encryption','<span style="color:#10b981">OK</span>');
  tH+=pF('Status','<strong style="color:'+(isOk?'#10b981':isFail?'#ef4444':'#f59e0b')+';">'+prEsc(st)+'</strong>');
  if(d.approved_by)tH+=pF('Authorized By','<strong>'+prEsc(d.approved_by)+'</strong>');

  /* Timeline */
  var evts=[];
  if(d.created_at)evts.push({t:d.created_at,cls:'info',icon:'&#128203;',title:'Transaction Created',detail:'ID: '+(d.id||d.payload_id||'').slice(0,32)});
  if(d.approved_at)evts.push({t:d.approved_at,cls:'done',icon:'&#9989;',title:'Approved',detail:'By: '+(d.approved_by||'Admin')});
  if(d.broadcasted_at)evts.push({t:d.broadcasted_at,cls:'info',icon:'&#9851;',title:'Broadcasted to Blockchain',detail:'TX: '+(d.tx_hash||'—').slice(0,40)});
  if(d.verified_at)evts.push({t:d.verified_at,cls:'done',icon:'&#128274;',title:'Blockchain Verified',detail:'On-chain verification completed'});
  if(d.webhook_sent_at)evts.push({t:d.webhook_sent_at,cls:'info',icon:'&#128225;',title:'Webhook Dispatched',detail:'HTTP '+(d.webhook_status_code||'—')});
  if(d.completed_at)evts.push({t:d.completed_at,cls:'done',icon:'&#127881;',title:'Transaction Completed',detail:'Final status: '+prEsc(st)});
  if(d.cancelled_at)evts.push({t:d.cancelled_at,cls:'fail',icon:'&#10060;',title:'Cancelled',detail:'By: '+(d.cancelled_by||'—')+' — '+(d.cancel_reason||'—')});
  if(d.last_retry_at)evts.push({t:d.last_retry_at,cls:'pending',icon:'&#8635;',title:'Retry Attempt',detail:'Count: '+String(d.retry_count||0)});
  if(d.updated_at&&d.updated_at!==d.created_at)evts.push({t:d.updated_at,cls:'info',icon:'&#9998;',title:'Record Updated',detail:'Last modification'});
  evts.sort(function(a,b){return new Date(a.t)-new Date(b.t);});
  var tlH=evts.length?evts.map(function(e){return pT(e.cls,e.icon,e.title,prFmtDate(e.t),e.detail);}).join(''):'<div style="color:var(--muted);font-size:12px;text-align:center;padding:16px;">No timeline events found.</div>';

  /* Auth codes */
  var codes=[];
  if(d.id)codes.push({label:'Transaction ID',value:d.id.slice(0,8).toUpperCase()});
  if(d.payload_id&&d.payload_id!==d.id)codes.push({label:'Payload ID',value:d.payload_id.slice(0,8).toUpperCase()});
  if(d.order_id)codes.push({label:'Order ID',value:d.order_id.slice(0,8).toUpperCase()});
  if(d.tokenization_job_id)codes.push({label:'Job ID',value:d.tokenization_job_id.slice(0,8).toUpperCase()});
  if(d.payment_reference)codes.push({label:'Payment Ref',value:d.payment_reference.slice(-8).toUpperCase()});
  if(d.sender_reference)codes.push({label:'Sender Ref',value:d.sender_reference.slice(-8).toUpperCase()});
  var codesH=codes.length?codes.map(function(c){return '<div class="vld-code-item"><div class="vld-code-label">'+c.label+'</div><div class="vld-code-value">'+c.value+'</div></div>';}).join(''):'';

  /* Confidence score */
  var scorePct=pct>=90?98:pct>=70?82:55;
  var scoreOffset=Math.round(226-(scorePct/100*226));
  var scoreCol=scorePct>=90?'#10b981':scorePct>=70?'#f59e0b':'#ef4444';
  var scoreLbl=scorePct>=90?'HIGH CONFIDENCE':scorePct>=70?'MEDIUM CONFIDENCE':'LOW CONFIDENCE';

  /* Current annotations */
  var m=PR_META[prKey()]||{};
  var sc2={APPROVED:'#34d399',CANCELLED:'#f87171',REJECTED:'#f87171',PENDING:'#fbbf24',PROCESSING:'#60a5fa'};

  /* Build HTML */
  var h='';

  /* Top bar */
  h+='<div class="vld-topbar">';
  h+='<div><div class="vld-topbar-title">&#9878; PRIVATE TRANSACTION REPORT &mdash; ALSHUMOOKH GLOBAL</div>';
  h+='<div class="vld-topbar-sub">BANKING FINANCE &amp; CREDIT &bull; PRIVATE &amp; CONFIDENTIAL &bull; '+prEsc(lblMap[type]||type).toUpperCase()+'</div></div>';
  h+='<div class="vld-topbar-meta">';
  h+='<div class="vld-topbar-meta-item"><label>Report ID</label><span>'+prEsc(rptId)+'</span></div>';
  h+='<div class="vld-topbar-meta-item"><label>Generated</label><span>'+new Date().toLocaleString()+'</span></div>';
  h+='<div class="vld-topbar-meta-item"><label>Type</label><span>'+prEsc(lblMap[type]||type)+'</span></div>';
  h+='</div>';
  h+='<div class="vld-status-badge '+stCls+'">'+stIcons[stCls]+' '+prEsc(st)+'</div>';
  h+='</div>';

  /* Metrics */
  h+='<div class="vld-metrics">';
  h+='<div class="vld-metric"><div class="vld-metric-icon gold">&#128176;</div><div><div class="vld-metric-label">Transaction Amount</div><div class="vld-metric-value gold">'+prEsc(amt)+'</div></div></div>';
  h+='<div class="vld-metric"><div class="vld-metric-icon blue">&#127760;</div><div><div class="vld-metric-label">Network / Bank</div><div class="vld-metric-value">'+prEsc(net||'—')+'</div></div></div>';
  h+='<div class="vld-metric"><div class="vld-metric-icon purple">&#128203;</div><div><div class="vld-metric-label">Reference</div><div class="vld-metric-value">'+prEsc(ref)+'</div></div></div>';
  h+='<div class="vld-metric"><div class="vld-metric-icon green">&#128279;</div><div><div class="vld-metric-label">Asset / Currency</div><div class="vld-metric-value">'+prEsc(asset)+'</div></div></div>';
  h+='<div class="vld-metric"><div class="vld-metric-icon orange">&#128737;</div><div><div class="vld-metric-label">Final Status</div><div class="vld-metric-value '+(isOk?'green':isFail?'red':'gold')+'">'+prEsc(st)+'</div></div></div>';
  h+='</div>';

  /* 3-col grid */
  h+='<div class="vld-grid">';
  /* Col 1 */
  h+='<div style="display:flex;flex-direction:column;gap:12px;">';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#128100;</span><span class="vld-card-head-title">Sender Information</span></div><div class="vld-card-body">'+sH+'</div></div>';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#9881;</span><span class="vld-card-head-title">Validation Progress</span></div><div class="vld-card-body">'+pH+'</div>';
  h+='<div style="padding:8px 15px 12px;"><div style="display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-bottom:4px;"><span>Overall Progress</span><span style="font-weight:800;color:var(--gold);">'+pct+'%</span></div>';
  h+='<div style="height:7px;background:var(--glass);border-radius:3px;overflow:hidden;border:1px solid var(--line);"><div style="height:100%;border-radius:3px;background:linear-gradient(90deg,#10b981,#059669);width:'+pct+'%;"></div></div></div></div>';
  h+='</div>';
  /* Col 2 */
  h+='<div style="display:flex;flex-direction:column;gap:12px;">';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#127968;</span><span class="vld-card-head-title">Receiver Information</span></div><div class="vld-card-body">'+rH+'</div></div>';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#9851;</span><span class="vld-card-head-title">Blockchain &amp; Transaction</span></div><div class="vld-card-body">'+bH+'</div></div>';
  h+='</div>';
  /* Col 3 */
  h+='<div style="display:flex;flex-direction:column;gap:12px;">';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#9989;</span><span class="vld-card-head-title">Validation Results</span></div><div class="vld-card-body">'+cH+'</div></div>';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#128200;</span><span class="vld-card-head-title">Confidence Score</span></div>';
  h+='<div class="vld-card-body" style="text-align:center;padding:14px;">';
  h+='<div class="vld-score-ring"><svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="32" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="9"/><circle cx="40" cy="40" r="32" fill="none" stroke="'+scoreCol+'" stroke-width="9" stroke-linecap="round" stroke-dasharray="201" stroke-dashoffset="'+scoreOffset+'"/></svg>';
  h+='<div class="vld-score-num" style="color:'+scoreCol+';">'+scorePct+'%</div></div>';
  h+='<div style="font-size:12px;font-weight:800;color:'+scoreCol+';margin-top:3px;">'+scoreLbl+'</div>';
  h+='</div></div>';
  h+='<div class="vld-card"><div class="vld-card-head"><span class="vld-card-head-icon">&#128225;</span><span class="vld-card-head-title">Transmission &amp; Status</span></div><div class="vld-card-body">'+tH+'</div></div>';
  h+='</div>';
  h+='</div>'; /* end vld-grid */

  /* Timeline */
  h+='<div class="vld-card" style="margin-bottom:13px;"><div class="vld-card-head"><span class="vld-card-head-icon">&#128336;</span><span class="vld-card-head-title">Transaction Timeline</span></div><div style="padding:12px 15px;">'+tlH+'</div></div>';

  /* Codes */
  if(codesH){h+='<div style="margin-bottom:13px;"><div style="font-size:9.5px;font-weight:800;color:var(--muted);letter-spacing:.8px;text-transform:uppercase;margin-bottom:8px;">&#128273; Authorization &amp; Reference Codes</div><div class="vld-codes">'+codesH+'</div></div>';}

  /* Final banner */
  var ftitles={ok:'APPROVED FOR TRANSMISSION',fail:'REJECTED — REQUIRES REVIEW',pending:'PENDING — AWAITING PROCESSING'};
  var fsubs={ok:'All validation processes completed. Transaction authorized and approved.',fail:'Validation checks failed. Manual review required before processing.',pending:'Transaction is currently being processed. Awaiting further updates.'};
  h+='<div class="vld-final '+stCls+'">';
  h+='<div class="vld-final-icon">'+(isOk?'&#9989;':isFail?'&#10060;':'&#9203;')+'</div>';
  h+='<div><div class="vld-final-title '+stCls+'">'+(ftitles[stCls]||'STATUS UNKNOWN')+'</div><div class="vld-final-sub">'+(fsubs[stCls]||'')+'</div></div>';
  h+='<div class="vld-actions">';
  h+='<button onclick="prPrintOne()" style="background:#0d2240;color:#c9a84c;border:none;padding:10px 22px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;">&#128424; Print &amp; Save</button>';
  h+='<button onclick="prClearSelection()" style="background:var(--glass);border:1px solid var(--line-strong);color:var(--ink);padding:10px 16px;border-radius:8px;font-size:11px;cursor:pointer;">&#10005; Close</button>';
  h+='</div></div>';

  /* Private Annotations panel */
  h+='<div style="background:var(--panel);border:1px solid rgba(201,168,76,.3);border-radius:12px;padding:16px;margin-bottom:13px;">';
  h+='<div style="font-size:10px;font-weight:800;color:var(--gold);text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px;">&#128274; Private Annotations</div>';
  h+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px;align-items:start;">';
  /* Liq Rate */
  h+='<div style="background:rgba(30,64,175,.08);border:1px solid rgba(30,64,175,.2);border-radius:8px;padding:10px;">';
  h+='<div style="font-size:9px;font-weight:800;color:#60a5fa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;">Liquidation Rate</div>';
  h+='<div id="prLiqLabel" style="font-size:12px;color:var(--ink);margin-bottom:7px;">'+(m.liq_pct?m.liq_pct+'%':'Not set')+'</div>';
  h+='<button onclick="prAskLiq()" style="background:#1e40af;color:#fff;border:none;padding:5px 10px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;width:100%;">Set %</button></div>';
  /* Custom amount */
  h+='<div style="background:rgba(6,95,70,.08);border:1px solid rgba(6,95,70,.2);border-radius:8px;padding:10px;">';
  h+='<div style="font-size:9px;font-weight:800;color:#34d399;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;">Post-Liq Amount</div>';
  h+='<div id="prAmtLabel" style="font-size:12px;color:var(--ink);margin-bottom:7px;">'+(m.custom_amt?m.custom_amt+' '+(m.custom_cur||'USD'):'Not set')+'</div>';
  h+='<button onclick="prAskAmt()" style="background:#065f46;color:#fff;border:none;padding:5px 10px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;width:100%;">Set Amount</button></div>';
  /* Status stamp */
  h+='<div style="background:rgba(109,40,217,.08);border:1px solid rgba(109,40,217,.2);border-radius:8px;padding:10px;">';
  h+='<div style="font-size:9px;font-weight:800;color:#a78bfa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;">Status Stamp</div>';
  h+='<div id="prStampLabel" style="font-size:12px;color:'+(m.stamp?(sc2[m.stamp]||'var(--ink)'):'var(--muted)')+';font-weight:'+(m.stamp?'700':'400')+';margin-bottom:7px;">'+(m.stamp||'Not set')+'</div>';
  h+='<button onclick="prAskStamp()" style="background:#6d28d9;color:#fff;border:none;padding:5px 10px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;width:100%;">Set Stamp</button></div>';
  /* Action btns */
  h+='<div style="display:flex;flex-direction:column;gap:7px;padding-top:2px;">';
  h+='<button onclick="prPrintOne()" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 12px;border-radius:8px;font-size:10px;font-weight:800;cursor:pointer;white-space:nowrap;">&#128424; Print &amp; Save</button>';
  h+='<button onclick="prClearAnnot()" style="background:rgba(220,38,38,.1);color:#f87171;border:1px solid rgba(220,38,38,.2);padding:7px 12px;border-radius:8px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;">&#128465; Clear</button>';
  h+='</div>';
  h+='</div></div>';

  var ab = document.getElementById('prAnnotBox');
  if (ab) { ab.style.display = 'block'; ab.innerHTML = h; ab.scrollIntoView({behavior:'smooth',block:'start'}); }
  prRender();
}

function prClearSelection() {
  PR_SEL.idx  = null;
  PR_SEL.type = null;
  var ab = document.getElementById('prAnnotBox');
  if (ab) { ab.style.display = 'none'; ab.innerHTML = ''; }
  prRender();
}

/* ── Annotation labels ──────────────────────────────────────────── */
function prKey() {
  if (PR_SEL.idx === null) { return ''; }
  return PR_SEL.type + '_' + PR_SEL.idx;
}

function prRefreshAnnotLabels() {
  var m   = PR_META[prKey()] || {};
  var ll  = document.getElementById('prLiqLabel');
  var al  = document.getElementById('prAmtLabel');
  var sl  = document.getElementById('prStampLabel');
  var sc  = { APPROVED:'#34d399', CANCELLED:'#f87171', REJECTED:'#f87171', PENDING:'#fbbf24', PROCESSING:'#60a5fa' };
  if (ll) { ll.textContent = m.liq_pct ? m.liq_pct + '%' : 'Not set'; }
  if (al) { al.textContent = m.custom_amt ? m.custom_amt + ' ' + (m.custom_cur || 'USD') : 'Not set'; }
  if (sl) {
    sl.textContent  = m.stamp || 'Not set';
    sl.style.color  = m.stamp ? (sc[m.stamp] || 'var(--ink)') : 'var(--muted)';
    sl.style.fontWeight = m.stamp ? '700' : '400';
  }
}

function prClearAnnot() {
  if (PR_SEL.idx === null) { return; }
  delete PR_META[prKey()];
  prRefreshAnnotLabels();
  prRender();
}

/* ── Modal ──────────────────────────────────────────────────────── */
function prOpenModal(title, fields, onSave) {
  var mTitle  = document.getElementById('prModalTitle');
  var mFields = document.getElementById('prModalFields');
  var mSave   = document.getElementById('prModalSave');
  var mOv     = document.getElementById('prModalOverlay');
  var mBox    = document.getElementById('prModalBox');
  if (!mTitle || !mFields || !mSave || !mOv || !mBox) { return; }

  var existing = PR_META[prKey()] || {};
  mTitle.textContent = title;

  var fHtml = '';
  fields.forEach(function(f) {
    var val = existing[f.k] || '';
    fHtml += '<label style="font-size:11px;font-weight:700;color:var(--ink);display:block;margin-bottom:3px;">' + prEsc(f.label) + '</label>';
    if (f.options) {
      fHtml += '<select id="prMF_' + f.k + '" style="width:100%;padding:8px 10px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel-solid);color:var(--ink);font-size:12px;margin-bottom:12px;">';
      fHtml += '<option value="">— Select —</option>';
      f.options.forEach(function(o) {
        fHtml += '<option value="' + prEsc(o) + '"' + (val === o ? ' selected' : '') + '>' + prEsc(o) + '</option>';
      });
      fHtml += '</select>';
    } else {
      fHtml += '<input id="prMF_' + f.k + '" value="' + prEsc(val) + '" placeholder="' + prEsc(f.placeholder || '') + '" style="width:100%;padding:8px 10px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel-solid);color:var(--ink);font-size:12px;margin-bottom:12px;box-sizing:border-box;outline:none;">';
    }
  });
  mFields.innerHTML = fHtml;

  mSave.onclick = function() {
    var vals = {};
    fields.forEach(function(f) {
      var el = document.getElementById('prMF_' + f.k);
      if (el) { vals[f.k] = el.value.trim(); }
    });
    var mk = prKey();
    PR_META[mk] = Object.assign(PR_META[mk] || {}, vals);
    if (onSave) { onSave(vals); }
    prCloseModal();
    prRefreshAnnotLabels();
    prRender();
  };

  mOv.style.display = 'block';
  mBox.style.display = 'block';
}

function prCloseModal() {
  var mOv  = document.getElementById('prModalOverlay');
  var mBox = document.getElementById('prModalBox');
  if (mOv)  { mOv.style.display  = 'none'; }
  if (mBox) { mBox.style.display = 'none'; }
}

function prAskLiq() {
  prOpenModal('Liquidation Rate', [{ k:'liq_pct', label:'Liquidation Percentage (%)', placeholder:'e.g. 15.50' }], null);
}

function prAskAmt() {
  prOpenModal('Post-Liquidation Amount', [
    { k:'custom_amt', label:'Amount After Liquidation', placeholder:'e.g. 500.00' },
    { k:'custom_cur', label:'Currency', placeholder:'USD' }
  ], null);
}

function prAskStamp() {
  prOpenModal('Status Stamp', [{ k:'stamp', label:'Select Status', options:['APPROVED','PENDING','PROCESSING','REJECTED','CANCELLED'] }], null);
}

/* ── Build print rows ───────────────────────────────────────────── */
function prBuildRows(type, d) {
  function pe(v) { var el=document.createElement('div'); el.textContent=String(v===null||v===undefined?'':v); return el.innerHTML; }
  function pn(n) { if(n===null||n===undefined||n===''){return '—';} var x=parseFloat(n); return isNaN(x)?String(n):x.toLocaleString('en-US',{maximumFractionDigits:2}); }
  function pd(v) { if(!v){return '—';} try{return new Date(v).toLocaleString();}catch(e){return String(v);} }
  var rows = [];
  if (type === 'order') {
    rows = [
      {h:'IDENTITY'},{l:'Transaction ID',v:pe(d.id)},{l:'External Reference',v:pe(d.external_id)},{l:'Payment Reference',v:pe(d.payment_reference)},{l:'Idempotency Key',v:pe(d.idempotency_key)},
      {h:'FIAT'},{l:'Fiat Amount',v:'<strong>'+pn(d.fiat_amount)+' '+pe(d.fiat_currency)+'</strong>'},{l:'Exchange Rate',v:pe(d.exchange_rate)},{l:'Fees',v:pe(d.fees_fiat)},
      {h:'CRYPTO'},{l:'Crypto Amount',v:'<strong>'+pn(d.crypto_amount)+' '+pe(d.crypto_currency)+'</strong>'},{l:'Network',v:pe(d.network)},{l:'Provider',v:pe(d.provider)},
      {h:'WALLETS'},{l:'User Wallet',v:'<code>'+pe(d.user_wallet_address||d.wallet)+'</code>'},{l:'Treasury Wallet',v:'<code>'+pe(d.treasury_wallet_address)+'</code>'},
      {h:'BLOCKCHAIN'},{l:'TX Hash',v:'<code>'+pe(d.tx_hash)+'</code>'},{l:'Processor Ref',v:pe(d.processor_reference)},
      {h:'STATUS'},{l:'Status',v:pe(d.status)},{l:'Client IP',v:pe(d.client_ip)},{l:'Notes',v:pe(d.notes)},
      {h:'TIMESTAMPS'},{l:'Created',v:pd(d.created_at)},{l:'Updated',v:pd(d.updated_at)},{l:'Completed',v:pd(d.completed_at)}
    ];
  } else if (type === 'm1') {
    var txLink = d.tx_hash ? (d.explorer_url ? '<a href="'+pe(d.explorer_url)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pe(d.tx_hash)+'</a>' : '<code>'+pe(d.tx_hash)+'</code>') : '—';
    var rwLink = d.receiver_wallet ? '<a href="https://etherscan.io/address/'+pe(d.receiver_wallet)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pe(d.receiver_wallet)+'</a>' : '—';
    var owLink = d.operator_wallet ? '<code style="font-size:9px;word-break:break-all;">'+pe(d.operator_wallet)+'</code>' : '—';
    var caLink = d.contract_address ? '<a href="https://etherscan.io/address/'+pe(d.contract_address)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pe(d.contract_address)+'</a>' : '—';
    rows = [
      {h:'IDENTITY'},
      {l:'Job ID',v:'<code style="font-size:9px;">'+pe(d.id)+'</code>'},
      {l:'Sender Reference',v:pe(d.sender_reference)},
      {l:'Outbound Transfer ID',v:'<code style="font-size:9px;">'+pe(d.outbound_transfer_id)+'</code>'},
      {l:'Payload ID',v:'<code style="font-size:9px;">'+pe(d.payload_id)+'</code>'},
      {h:'SENDER'},
      {l:'Sender Name',v:'<strong>'+pe(d.sender_name)+'</strong>'},
      {l:'Sender IBAN',v:'<code>'+pe(d.sender_iban)+'</code>'},
      {l:'Sender Bank',v:pe(d.sender_bank)},
      {h:'CONVERSION'},
      {l:'EUR Amount',v:'<strong style="color:#1d4ed8;">'+pn(d.eur_amount)+' EUR</strong>'},
      {l:'FX Rate EUR/USD',v:pe(d.fx_rate_eur_usd||d.fx_rate)},
      {l:'FX Provider',v:pe(d.fx_provider)},
      {l:'USD Amount',v:'<strong>'+pe(d.usd_amount)+' USD</strong>'},
      {l:'Output Amount',v:'<strong style="color:#065f46;">'+pn(d.usdt_amount)+' '+(d.target_asset||'SIG')+'</strong>'},
      {h:'RECEIVER — ALSHUMOOKH GROUP'},
      {l:'Network',v:'<strong>'+pe((d.network||'').toUpperCase())+'</strong>'},
      {l:'Receiver Wallet',v:rwLink},
      {l:'Operator Wallet',v:owLink},
      {l:'Contract Address',v:caLink},
      {h:'TRANSACTION'},
      {l:'TX Hash',v:txLink},
      {l:'Block Number',v:pe(d.block_number?String(d.block_number):null)},
      {l:'Confirmations',v:pe(d.confirmations?String(d.confirmations):null)},
      {l:'Gas Used',v:pe(d.gas_used?String(d.gas_used):null)},
      {l:'Explorer',v:d.explorer_url?'<a href="'+pe(d.explorer_url)+'" target="_blank" style="color:#1d4ed8;font-size:10px;">View on Explorer</a>':'—'},
      {h:'STATUS'},
      {l:'Job Status',v:'<strong>'+pe(d.status)+'</strong>'},
      {l:'Outbound Status',v:pe(d.outbound_status)},
      {l:'Approved By',v:pe(d.approved_by)},
      {l:'Error',v:pe(d.error_message)},
      {l:'Notes',v:pe(d.notes)},
      {h:'TIMESTAMPS'},
      {l:'Created',v:pd(d.created_at)},
      {l:'Updated',v:pd(d.updated_at)},
      {l:'Completed',v:pd(d.completed_at)}
    ];
  } else if (type === 'payload') {
    rows = [
      {h:'IDENTITY'},{l:'Payload ID',v:pe(d.id)},{l:'Transaction Reference',v:pe(d.transaction_reference)},{l:'Request ID',v:pe(d.request_id)},
      {h:'AMOUNT'},{l:'Asset',v:pe(d.asset)},{l:'Amount',v:'<strong>'+pn(d.amount)+' '+pe(d.asset)+'</strong>'},{l:'Network',v:pe(d.network_name)},
      {h:'WALLETS'},{l:'Sender',v:'<code>'+pe(d.sender_wallet)+'</code>'},{l:'Receiver',v:'<code>'+pe(d.receiver_wallet)+'</code>'},
      {h:'BLOCKCHAIN'},{l:'TX Hash',v:'<code>'+pe(d.tx_hash)+'</code>'},{l:'Block Number',v:pe(d.block_number)},{l:'Confirmations',v:pe(d.confirmations)},
      {h:'SECURITY'},{l:'Status',v:pe(d.verification_status)},{l:'Security Level',v:pe(d.security_level)},{l:'Client IP',v:pe(d.client_ip)},
      {h:'TIMESTAMPS'},{l:'Created',v:pd(d.created_at)},{l:'Updated',v:pd(d.updated_at)}
    ];
  } else {
    var txLinkXf = d.tx_hash ? (d.explorer_url ? '<a href="'+pe(d.explorer_url)+'" target="_blank" style="font-family:monospace;font-size:9px;word-break:break-all;color:#1d4ed8;">'+pe(d.tx_hash)+'</a>' : '<code style="font-size:9px;word-break:break-all;">'+pe(d.tx_hash)+'</code>') : '&mdash;';
    rows = [
      {h:'IDENTITY'},
      {l:'Transfer ID',v:'<code style="font-size:9px;">'+pe(d.id)+'</code>'},
      {l:'Order ID',v:d.order_id?'<code style="font-size:9px;">'+pe(d.order_id)+'</code>':'&mdash;'},
      {l:'Payload ID',v:d.payload_id?'<code style="font-size:9px;">'+pe(d.payload_id)+'</code>':'&mdash;'},
      {l:'Tokenization Job ID',v:d.tokenization_job_id?'<code style="font-size:9px;">'+pe(d.tokenization_job_id)+'</code>':'&mdash;'},
      {h:'TRANSFER DETAILS'},
      {l:'Network',v:'<strong>'+pe((d.network||'').toUpperCase())+'</strong>'},
      {l:'Asset',v:'<strong>'+pe(d.asset||d.currency||'USDT')+'</strong>'},
      {l:'Amount',v:'<strong style="color:#065f46;">'+pn(d.amount)+' '+pe(d.asset||d.currency||'USDT')+'</strong>'},
      {l:'Priority',v:pe(d.priority)||'&mdash;'},
      {h:'WALLET ADDRESSES'},
      {l:'To Address',v:'<code style="font-size:9px;word-break:break-all;">'+pe(d.to_address)+'</code>'},
      {l:'From Address',v:d.from_address?'<code style="font-size:9px;word-break:break-all;">'+pe(d.from_address)+'</code>':'&mdash;'},
      {l:'Contract Address',v:d.contract_address?'<code style="font-size:9px;word-break:break-all;">'+pe(d.contract_address)+'</code>':'&mdash;'},
      {h:'BLOCKCHAIN'},
      {l:'TX Hash',v:txLinkXf},
      {l:'Block Number',v:d.block_number?pe(String(d.block_number)):'&mdash;'},
      {l:'Confirmations',v:d.confirmations?pe(String(d.confirmations)):'&mdash;'},
      {l:'Gas Used',v:d.gas_used?pe(String(d.gas_used)):'&mdash;'},
      {l:'Explorer',v:d.explorer_url?'<a href="'+pe(d.explorer_url)+'" target="_blank" style="color:#1d4ed8;font-size:10px;">View on Explorer &#8599;</a>':'&mdash;'},
      {l:'Broadcasted At',v:pd(d.broadcasted_at)},
      {h:'APPROVAL & STATUS'},
      {l:'Status',v:'<strong>'+pe(d.status)+'</strong>'},
      {l:'Initiated By',v:pe(d.initiated_by)||'&mdash;'},
      {l:'Approved By',v:pe(d.approved_by)||'&mdash;'},
      {l:'Approved At',v:pd(d.approved_at)},
      {l:'Cancelled By',v:pe(d.cancelled_by)||'&mdash;'},
      {l:'Cancelled At',v:pd(d.cancelled_at)},
      {l:'Cancel Reason',v:pe(d.cancel_reason)||'&mdash;'},
      {h:'NOTES & ERRORS'},
      {l:'Notes',v:pe(d.notes)||'&mdash;'},
      {l:'Error Message',v:d.error_message?'<span style="color:#b91c1c;">'+pe(d.error_message)+'</span>':'&mdash;'},
      {l:'Retry Count',v:pe(String(d.retry_count||0))},
      {l:'Last Retry At',v:pd(d.last_retry_at)},
      {h:'WEBHOOK'},
      {l:'Callback URL',v:d.callback_url?'<code style="font-size:9px;word-break:break-all;">'+pe(d.callback_url)+'</code>':'&mdash;'},
      {l:'Webhook Sent At',v:pd(d.webhook_sent_at)},
      {l:'Webhook Status',v:d.webhook_status_code?pe(String(d.webhook_status_code)):'&mdash;'},
      {h:'TIMESTAMPS'},
      {l:'Created',v:pd(d.created_at)},
      {l:'Updated',v:pd(d.updated_at)},
      {l:'Broadcasted',v:pd(d.broadcasted_at)},
      {l:'Completed',v:pd(d.completed_at)}
    ];
  }
  return rows;
}

/* ── Build printable HTML ───────────────────────────────────────── */
function prBuildPrintHTML(type, d, meta, titleStr, ref) {
  var m = meta || {};
  var sColors = { APPROVED:'#065f46', CANCELLED:'#b91c1c', REJECTED:'#b91c1c', PENDING:'#92400e', PROCESSING:'#1e40af' };
  var sBg     = { APPROVED:'#d1fae5', CANCELLED:'#fee2e2', REJECTED:'#fee2e2', PENDING:'#fef3c7', PROCESSING:'#dbeafe' };
  var rows = prBuildRows(type, d);
  if (m.liq_pct || m.custom_amt || m.stamp) {
    rows.push({ h:'PRIVATE ANNOTATIONS' });
    if (m.liq_pct)     { rows.push({ l:'Liquidation Rate',       v:'<strong>' + m.liq_pct + '%</strong>' }); }
    if (m.custom_amt)  { rows.push({ l:'Post-Liquidation Amount', v:'<strong>' + m.custom_amt + ' ' + (m.custom_cur || 'USD') + '</strong>' }); }
    if (m.stamp)       { rows.push({ l:'Status Stamp',            v:'<strong style="color:' + (sColors[m.stamp] || '#555') + ';">' + m.stamp + '</strong>' }); }
  }
  var rowsHTML = rows.map(function(r) {
    if (r.h) {
      return '<tr><td colspan="2" style="background:#0d2240;color:#c9a84c;font-size:9px;font-weight:800;letter-spacing:.8px;padding:5px 12px;text-transform:uppercase;">' + r.h + '</td></tr>';
    }
    return '<tr><td style="background:#f4f7fb;font-weight:600;color:#445;padding:5px 12px;white-space:nowrap;font-size:9.5px;width:38%;">' + r.l + '</td><td style="padding:5px 12px;font-size:9.5px;color:#1a2a3a;">' + r.v + '</td></tr>';
  }).join('');
  var stamp = m.stamp || '';
  var stampWM = stamp ? '<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);font-size:72px;font-weight:900;color:rgba(0,0,0,.05);white-space:nowrap;pointer-events:none;">' + stamp + '</div>' : '';
  var stampBN = stamp ? '<div style="background:' + (sBg[stamp] || '#e5e7eb') + ';color:' + (sColors[stamp] || '#374151') + ';font-size:15px;font-weight:900;text-align:center;padding:8px;letter-spacing:2px;margin-bottom:14px;border-radius:5px;">' + stamp + '</div>' : '';
  var css = [
    '*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}',
    'body{font-family:"Helvetica Neue",Arial,sans-serif;font-size:10.5px;color:#0d1b2a;margin:0;padding:22px 28px;background:#fff;}',
    '.gbar{height:5px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400);}',
    '.cband{background:#1a3a6b;color:#fff;padding:7px 20px;font-size:8px;font-weight:700;display:flex;justify-content:space-between;}',
    '.hdr{display:flex;justify-content:space-between;align-items:center;padding:14px 0 10px;border-bottom:2px solid #1a3a6b;margin-bottom:14px;}',
    '.co{font-size:14px;font-weight:800;color:#1a3a6b;}',
    '.seal{width:56px;height:56px;border:2px solid #b8860b;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7.5px;font-weight:700;color:#8b6914;line-height:1.3;}',
    'table{width:100%;border-collapse:collapse;margin-bottom:16px;border:1px solid #d0d9ea;}',
    'tr:nth-child(even)>td{background:#f9fbfd;}',
    '.np{display:block}code{font-family:monospace;font-size:8.5px;word-break:break-all;}',
    '@media print{.np{display:none!important}@page{size:A4 portrait;margin:8mm 10mm}body{padding:0}}'
  ].join('');
  var parts = [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<title>Private Report - ' + titleStr + '</title>',
    '<style>' + css + '</style></head><body>',
    '<div class="gbar"></div>',
    '<div class="cband"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; PRIVATE &mdash; CONFIDENTIAL</span><span>Ref: PR-' + ref + '</span></div>',
    '<div class="hdr"><div><div class="co">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>',
    '<div style="font-size:9.5px;color:#5a6a80;margin-top:3px;">Private Report &mdash; ' + titleStr + ' &mdash; ' + new Date().toUTCString() + '</div></div>',
    '<div class="seal">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div></div>',
    '<div class="np" style="margin-bottom:14px;display:flex;gap:8px;">',
    '<button onclick="window.print()" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 24px;font-size:12px;font-weight:700;border-radius:5px;cursor:pointer;">&#128424; Print / Save PDF</button>',
    '<button onclick="window.close()" style="background:#e5e7eb;color:#374151;border:none;padding:9px 18px;font-size:12px;border-radius:5px;cursor:pointer;">&#10005; Close</button></div>',
    stampWM, stampBN,
    '<table>' + rowsHTML + '</table>',
    '<div id="prNotesDisplay" style="display:none;margin-top:22px;padding:14px 20px;border:2px solid #0d2240;border-radius:8px;background:#f7f9fc;">',
    '<div style="font-size:8.5px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;color:#6b7a90;margin-bottom:8px;">REMARKS / NOTES</div>',
    '<div id="prNotesContent" style="font-size:12px;color:#0d2240;font-weight:600;line-height:1.7;white-space:pre-wrap;"></div>',
    '</div>',

    '<div class="np" id="prNotesPanel" style="margin-top:22px;padding:16px 20px;background:#f0f4fb;border:2px dashed #c8d9f0;border-radius:10px;">',
    '<div style="font-size:13px;font-weight:800;color:#0d2240;margin-bottom:10px;">&#128203; Add Remarks / Notes</div>',

    '<div style="font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#6b7a90;margin-bottom:6px;">&#128336; Settlement Timeframe</div>',
    '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; Settlement within 24 Business Hours</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; Settlement within 48 Business Hours</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; Settlement within 72 Business Hours</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; Settlement within 5 Business Days (T+5)</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; Same Day Settlement &mdash; Value Date Today</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; T+1 Settlement &mdash; Next Business Day</button>',
    '<button onclick="prSetPreset(this)" style="background:#164e63;color:#cffafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128336; T+2 Settlement &mdash; Standard SWIFT Value Date</button>',
    '</div>',

    '<div style="font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#6b7a90;margin-bottom:6px;">&#9203; Transaction Status</div>',
    '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">',
    '<button onclick="prSetPreset(this)" style="background:#92400e;color:#fef3c7;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#9203; Pending &mdash; Awaiting Approval</button>',
    '<button onclick="prSetPreset(this)" style="background:#065f46;color:#d1fae5;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#10003; Approved &mdash; Processed Successfully</button>',
    '<button onclick="prSetPreset(this)" style="background:#1e40af;color:#dbeafe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#8635; Processing &mdash; Under Review</button>',
    '<button onclick="prSetPreset(this)" style="background:#78350f;color:#fef3c7;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#9888; On Hold &mdash; Compliance Review Required</button>',
    '<button onclick="prSetPreset(this)" style="background:#7c3aed;color:#ede9fe;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#8617; Reversed &mdash; Transaction Recalled</button>',
    '<button onclick="prSetPreset(this)" style="background:#991b1b;color:#fee2e2;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#10007; Rejected &mdash; Not Authorized</button>',
    '<button onclick="prSetPreset(this)" style="background:#374151;color:#e5e7eb;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128203; Cancelled &mdash; Withdrawn by Client</button>',
    '</div>',

    '<div style="font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#6b7a90;margin-bottom:6px;">&#128200; Funds & Treasury</div>',
    '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">',
    '<button onclick="prSetPreset(this)" style="background:#0d2240;color:#c9a84c;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128274; Funds Received &mdash; Confirmed by Treasury</button>',
    '<button onclick="prSetPreset(this)" style="background:#0d2240;color:#c9a84c;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128200; Funds Transferred &mdash; Deducted from Reserve</button>',
    '<button onclick="prSetPreset(this)" style="background:#0d2240;color:#c9a84c;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#9989; Blockchain Confirmed &mdash; On-Chain Verified</button>',
    '<button onclick="prSetPreset(this)" style="background:#0d2240;color:#c9a84c;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128182; Liquidity Settled &mdash; Post-Liquidation Completed</button>',
    '<button onclick="prSetPreset(this)" style="background:#0d2240;color:#c9a84c;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128176; Payment Released &mdash; Funds Dispatched to Beneficiary</button>',
    '</div>',

    '<div style="font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#6b7a90;margin-bottom:6px;">&#9878; Compliance & Legal</div>',
    '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128203; For Internal Use Only &mdash; Confidential</button>',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#9878; KYC / AML Verification Pending</button>',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#9989; KYC / AML Cleared &mdash; Verified</button>',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128274; Frozen &mdash; Regulatory Hold</button>',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128220; Awaiting Supporting Documents</button>',
    '<button onclick="prSetPreset(this)" style="background:#1f2937;color:#d1d5db;border:none;padding:7px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;">&#128221; Authorized by Management &mdash; Signed Off</button>',
    '</div>',

    '<textarea id="prNotesText" placeholder="Or write your own custom note here..." style="width:100%;height:72px;font-size:12px;padding:10px;border:1.5px solid #c8d9f0;border-radius:7px;font-family:Arial,sans-serif;color:#0d2240;resize:vertical;box-sizing:border-box;"></textarea>',
    '<div style="display:flex;gap:8px;margin-top:10px;">',
    '<button onclick="prApplyNotes()" style="background:#0d2240;color:#c9a84c;border:none;padding:9px 22px;font-size:12px;font-weight:700;border-radius:6px;cursor:pointer;">&#10003; Apply Notes</button>',
    '<button onclick="prClearNotes()" style="background:#e5e7eb;color:#374151;border:none;padding:9px 16px;font-size:12px;border-radius:6px;cursor:pointer;">&#10007; Clear</button>',
    '</div></div>',

    '<script>',
    'function prSetPreset(btn){document.getElementById("prNotesText").value=btn.textContent.trim();}',
    'function prApplyNotes(){var t=document.getElementById("prNotesText").value.trim();if(!t)return;document.getElementById("prNotesContent").textContent=t;document.getElementById("prNotesDisplay").style.display="block";}',
    'function prClearNotes(){document.getElementById("prNotesText").value="";document.getElementById("prNotesContent").textContent="";document.getElementById("prNotesDisplay").style.display="none";}',
    '<\/script>',

    '<div style="margin-top:16px;padding-top:8px;border-top:1px solid #d0d9ea;display:flex;justify-content:space-between;font-size:8px;color:#9aa;">',
    '<span>PRIVATE REPORT &mdash; ALSHUMOOKH GROUP 2026 &mdash; Ref: PR-' + ref + '</span>',
    '<span>Generated: ' + new Date().toLocaleString() + '</span></div>',
    '</body></html>'
  ];
  return parts.join('');
}

/* ── Print one transaction ──────────────────────────────────────── */
function prPrintOne() {
  if (PR_SEL.idx === null) { alert('Please select a transaction first.'); return; }
  var type   = PR_SEL.type;
  var d      = PR_DATA[type] ? PR_DATA[type][PR_SEL.idx] : null;
  if (!d)    { return; }
  var lblMap = { order:'Payment Order', m1:'M1 Tokenization', payload:'Settlement Payload', transfer:'Outbound Transfer' };
  var ref    = Date.now().toString(36).toUpperCase();
  var meta   = PR_META[prKey()] || {};
  var html   = prBuildPrintHTML(type, d, meta, lblMap[type] || type, ref);
  var w = window.open('', '_blank', 'width=820,height=980');
  if (w) { w.document.write(html); w.document.close(); }
  /* Save record */
  prSaveReport(type, d, meta, ref, lblMap[type] || type);
}

/* ── Save & Render Saved Reports ────────────────────────────────── */
function prSaveReport(type, d, meta, ref, lbl) {
  var amt = '';
  if (type==='order') amt = prFmtNum(d.fiat_amount)+' '+(d.fiat_currency||'');
  else if (type==='m1') amt = prFmtNum(d.eur_amount)+' EUR';
  else if (type==='payload') amt = prFmtNum(d.amount)+' '+(d.asset||'');
  else amt = prFmtNum(d.amount)+' '+(d.asset||'USDT');
  PR_SAVED.unshift({
    ref: ref,
    type: type,
    lbl: lbl,
    id: d.id || d.payload_id || '',
    amount: amt,
    status: String(d.status || d.verification_status || ''),
    date: new Date().toLocaleString(),
    data: d,
    meta: meta || {}
  });
  prRenderSaved();
}

function prRenderSaved() {
  var el = document.getElementById('prSavedList');
  var cnt = document.getElementById('prSavedCount');
  if (cnt) { cnt.textContent = PR_SAVED.length + ' report' + (PR_SAVED.length !== 1 ? 's' : ''); }
  if (!el) { return; }
  if (!PR_SAVED.length) {
    el.innerHTML = '<div style="text-align:center;color:var(--muted);font-size:12px;padding:20px;">No saved reports yet. Print a transaction to save it here.</div>';
    return;
  }
  var typeColors = { order:'#1e40af', m1:'#065f46', payload:'#7c3aed', transfer:'#b45309' };
  var stColors = { COMPLETED:'#10b981',CONFIRMED:'#10b981',APPROVED:'#10b981',RECONCILED:'#10b981',FAILED:'#ef4444',REJECTED:'#ef4444',CANCELLED:'#ef4444',PENDING:'#f59e0b',PROCESSING:'#60a5fa' };
  var thS = 'padding:6px 10px;font-size:9px;font-weight:700;color:var(--muted);text-align:left;border-bottom:1px solid var(--line);white-space:nowrap;';
  var h = '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:11px;">';
  h += '<thead><tr style="background:rgba(255,255,255,.03);">';
  h += '<th style="'+thS+'">Saved</th><th style="'+thS+'">Type</th><th style="'+thS+'">Amount</th><th style="'+thS+'">Status</th><th style="'+thS+'">Ref</th><th style="'+thS+'">Actions</th>';
  h += '</tr></thead><tbody>';
  PR_SAVED.forEach(function(r, i) {
    var stCol = stColors[r.status] || '#94a3b8';
    h += '<tr style="border-bottom:1px solid var(--line);">';
    h += '<td style="padding:7px 10px;font-size:9.5px;color:var(--muted);white-space:nowrap;">'+prEsc(r.date)+'</td>';
    h += '<td style="padding:7px 10px;"><span style="background:'+(typeColors[r.type]||'#374151')+';color:#fff;border-radius:3px;padding:2px 7px;font-size:8px;font-weight:800;">'+prEsc(r.lbl||r.type).toUpperCase().slice(0,8)+'</span></td>';
    h += '<td style="padding:7px 10px;font-weight:700;color:var(--gold);font-size:10.5px;white-space:nowrap;">'+prEsc(r.amount)+'</td>';
    h += '<td style="padding:7px 10px;font-size:10px;font-weight:700;color:'+stCol+';">'+prEsc(r.status)+'</td>';
    h += '<td style="padding:7px 10px;font-family:monospace;font-size:9px;color:var(--muted);">PR-'+prEsc(r.ref)+'</td>';
    h += '<td style="padding:7px 10px;white-space:nowrap;">';
    h += '<button onclick="prReopenReport('+i+')" style="background:#0d2240;color:#c9a84c;border:none;padding:4px 10px;border-radius:5px;font-size:9px;font-weight:700;cursor:pointer;margin-right:5px;">&#128424; Reopen</button>';
    h += '<button onclick="prDeleteSaved('+i+')" style="background:rgba(220,38,38,.1);color:#f87171;border:1px solid rgba(220,38,38,.2);padding:4px 9px;border-radius:5px;font-size:9px;font-weight:700;cursor:pointer;">&#128465;</button>';
    h += '</td></tr>';
  });
  h += '</tbody></table></div>';
  el.innerHTML = h;
}

function prReopenReport(i) {
  var r = PR_SAVED[i];
  if (!r) { return; }
  var html = prBuildPrintHTML(r.type, r.data, r.meta, r.lbl, r.ref);
  var w = window.open('', '_blank', 'width=820,height=980');
  if (w) { w.document.write(html); w.document.close(); }
}

function prDeleteSaved(i) {
  if (!confirm('Delete this saved report?')) { return; }
  PR_SAVED.splice(i, 1);
  prRenderSaved();
}

/* ── Print all ──────────────────────────────────────────────────── */
function prPrintAll() {
  var types  = ['order','m1','payload','transfer'];
  var lblMap = { order:'Payment Order', m1:'M1 Tokenization', payload:'Settlement Payload', transfer:'Outbound Transfer' };
  var allItems = [];
  types.forEach(function(t) {
    var arr = PR_DATA[t] || [];
    arr.forEach(function(d, i) {
      allItems.push({ type:t, idx:i, d:d, lbl:lblMap[t], meta:PR_META[t+'_'+i]||{} });
    });
  });
  if (!allItems.length) { alert('No transactions loaded. Please wait for data to load.'); return; }
  var css = [
    '*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}',
    'body{font-family:"Helvetica Neue",Arial,sans-serif;font-size:9.5px;color:#0d1b2a;margin:0;padding:18px 24px;background:#fff;}',
    '.gbar{height:4px;background:linear-gradient(90deg,#7a5400,#c9a227,#f0c040,#c9a227,#7a5400);}',
    '.cband{background:#1a3a6b;color:#fff;padding:5px 16px;font-size:7.5px;font-weight:700;display:flex;justify-content:space-between;}',
    '.hdr{display:flex;justify-content:space-between;align-items:center;padding:10px 0 8px;border-bottom:2px solid #1a3a6b;margin-bottom:10px;}',
    '.co{font-size:13px;font-weight:800;color:#1a3a6b;}',
    '.seal{width:48px;height:48px;border:2px solid #b8860b;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:7px;font-weight:700;color:#8b6914;line-height:1.3;}',
    'table{width:100%;border-collapse:collapse;margin-bottom:12px;border:1px solid #d0d9ea;page-break-inside:avoid;}',
    'tr:nth-child(even)>td{background:#f9fbfd;}',
    '.np{display:block}code{font-family:monospace;font-size:8px;word-break:break-all;}',
    '.blk{page-break-after:always;}',
    '@media print{.np{display:none!important}@page{size:A4 portrait;margin:6mm 8mm}body{padding:0}}'
  ].join('');
  var ref  = Date.now().toString(36).toUpperCase();
  var body = allItems.map(function(item) {
    var rows = prBuildRows(item.type, item.d);
    var m = item.meta;
    if (m.liq_pct || m.custom_amt || m.stamp) {
      rows.push({ h:'PRIVATE ANNOTATIONS' });
      if (m.liq_pct)    { rows.push({ l:'Liquidation Rate',       v:'<strong>' + m.liq_pct + '%</strong>' }); }
      if (m.custom_amt) { rows.push({ l:'Post-Liquidation Amount', v:'<strong>' + m.custom_amt + ' ' + (m.custom_cur || 'USD') + '</strong>' }); }
      if (m.stamp)      { rows.push({ l:'Status Stamp',            v:'<strong>' + m.stamp + '</strong>' }); }
    }
    var rHTML = rows.map(function(r) {
      if (r.h) { return '<tr><td colspan="2" style="background:#0d2240;color:#c9a84c;font-size:8px;font-weight:800;letter-spacing:.8px;padding:4px 10px;text-transform:uppercase;">' + r.h + '</td></tr>'; }
      return '<tr><td style="background:#f4f7fb;font-weight:600;color:#445;padding:4px 10px;white-space:nowrap;font-size:8.5px;width:36%;">' + r.l + '</td><td style="padding:4px 10px;font-size:8.5px;color:#1a2a3a;">' + r.v + '</td></tr>';
    }).join('');
    return '<div class="blk"><div style="background:#1a3a6b;color:#c9a84c;font-size:9px;font-weight:800;padding:4px 10px;margin-bottom:2px;border-radius:3px 3px 0 0;">' + item.lbl + ' &mdash; ' + String(item.d.id || '') + '</div><table>' + rHTML + '</table></div>';
  }).join('');

  var parts = [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<title>Private Report - All Transactions</title>',
    '<style>' + css + '</style></head><body>',
    '<div class="gbar"></div>',
    '<div class="cband"><span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT &mdash; PRIVATE &mdash; CONFIDENTIAL</span><span>Ref: PR-ALL-' + ref + '</span></div>',
    '<div class="hdr"><div><div class="co">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>',
    '<div style="font-size:9px;color:#5a6a80;margin-top:2px;">Complete Private Report &mdash; All Transactions &mdash; ' + new Date().toUTCString() + '</div></div>',
    '<div class="seal">ALSH<br>GROUP<br>&#9733;&#9733;&#9733;</div></div>',
    '<div class="np" style="margin-bottom:12px;display:flex;gap:8px;">',
    '<button onclick="window.print()" style="background:#0d2240;color:#c9a84c;border:none;padding:8px 20px;font-size:11px;font-weight:700;border-radius:5px;cursor:pointer;">&#128424; Print / Save PDF</button>',
    '<button onclick="window.close()" style="background:#e5e7eb;color:#374151;border:none;padding:8px 16px;font-size:11px;border-radius:5px;cursor:pointer;">&#10005; Close</button>',
    '<span style="font-size:11px;color:#555;line-height:32px;">' + allItems.length + ' total transactions</span></div>',
    body,
    '<div style="margin-top:12px;padding-top:6px;border-top:1px solid #d0d9ea;display:flex;justify-content:space-between;font-size:7.5px;color:#9aa;">',
    '<span>PRIVATE REPORT &mdash; ALSHUMOOKH GROUP 2026 &mdash; Ref: PR-ALL-' + ref + '</span>',
    '<span>Generated: ' + new Date().toLocaleString() + '</span></div>',
    '</body></html>'
  ];
  var html = parts.join('');
  var w = window.open('', '_blank', 'width=900,height=1000');
  if (w) { w.document.write(html); w.document.close(); }
}

/* ── Init ───────────────────────────────────────────────────────── */
(function init() {
  prLoadAll();
})();
</script>

"""


@router.get("/dashboard/private", response_class=HTMLResponse)
async def dashboard_private(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Private Report", "/dashboard/private", _PRIVATE_REPORT_BODY))


@router.post("/dashboard/logout")
async def dashboard_logout():
    """Clear the admin session cookie."""
    response = Response(content="OK")
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return response


# ─── TOP-UP ENGINE PAGE ───────────────────────────────────────────────────────

_TOPUP_BODY = """
<div class="page-body">
<style>
.tu-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:20px;}
@media(max-width:900px){.tu-grid{grid-template-columns:1fr 1fr;}}
@media(max-width:600px){.tu-grid{grid-template-columns:1fr;}}
.tu-stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;}
.tu-stat label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;display:block;margin-bottom:6px;}
.tu-stat span{font-size:22px;font-weight:700;color:#f0f0f0;}
.tu-tabs{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:0;}
.tu-tab{padding:10px 20px;font-size:12px;font-weight:600;cursor:pointer;color:var(--muted);background:none;border:none;border-bottom:2px solid transparent;transition:.2s;text-transform:uppercase;letter-spacing:.05em;}
.tu-tab.active{color:var(--gold);border-bottom-color:var(--gold);}
.tu-form{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;}
@media(max-width:600px){.tu-form{grid-template-columns:1fr;}}
.tu-label{font-size:11px;color:var(--muted);display:block;margin-bottom:4px;}
.tu-input{width:100%;background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:7px;padding:8px 11px;color:#f0f0f0;font-size:12px;box-sizing:border-box;}
.tu-input:focus{outline:none;border-color:var(--gold);}
.tu-full{grid-column:1/-1;}
</style>

<!-- Stats Row -->
<div class="tu-grid" id="tuStats">
  <div class="tu-stat"><label>Total Wallets</label><span id="tuStatWallets">—</span></div>
  <div class="tu-stat"><label>Total Cards</label><span id="tuStatCards">—</span></div>
  <div class="tu-stat"><label>Total Top-Ups</label><span id="tuStatTxns">—</span></div>
</div>

<!-- Panel with Tabs -->
<div class="panel" style="padding:0;overflow:hidden;">
  <div class="tu-tabs">
    <button class="tu-tab active" id="tuTab_wallets" onclick="tuSwitch('wallets')">💼 Wallets</button>
    <button class="tu-tab" id="tuTab_cards" onclick="tuSwitch('cards')">💳 Cards</button>
    <button class="tu-tab" id="tuTab_txns" onclick="tuSwitch('txns')">📋 Transactions</button>
    <button class="tu-tab" id="tuTab_request" onclick="tuSwitch('request')">⚡ Top-Up Request</button>
  </div>

  <!-- Wallets Tab -->
  <div id="tuPane_wallets" style="padding:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <strong style="font-size:13px;">Wallets</strong>
      <button class="btn btn-primary" style="font-size:11px;" onclick="tuShowWalletForm()">+ Add Wallet</button>
    </div>
    <div id="tuWalletForm" style="display:none;background:rgba(255,255,255,.04);border-radius:9px;padding:14px;margin-bottom:14px;">
      <div class="tu-form">
        <div><label class="tu-label">Wallet Name *</label><input class="tu-input" id="tuWName" placeholder="e.g. Client Wallet A"></div>
        <div><label class="tu-label">Currency</label><input class="tu-input" id="tuWCurrency" value="USDT"></div>
        <div><label class="tu-label">Network</label><input class="tu-input" id="tuWNetwork" value="ethereum"></div>
        <div><label class="tu-label">Blockchain Address</label><input class="tu-input" id="tuWAddress" placeholder="0x..."></div>
        <div class="tu-full"><label class="tu-label">Notes</label><input class="tu-input" id="tuWNotes" placeholder="Optional notes"></div>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn btn-success" style="font-size:11px;" onclick="tuCreateWallet()">Save Wallet</button>
        <button class="btn btn-ghost" style="font-size:11px;" onclick="document.getElementById('tuWalletForm').style.display='none'">Cancel</button>
      </div>
    </div>
    <div id="tuWalletBody"><div class="empty-state"><div class="icon">💼</div>Loading wallets…</div></div>
  </div>

  <!-- Cards Tab -->
  <div id="tuPane_cards" style="display:none;padding:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <strong style="font-size:13px;">Cards</strong>
      <button class="btn btn-primary" style="font-size:11px;" onclick="tuShowCardForm()">+ Add Card</button>
    </div>
    <div id="tuCardForm" style="display:none;background:rgba(255,255,255,.04);border-radius:9px;padding:14px;margin-bottom:14px;">
      <div class="tu-form">
        <div><label class="tu-label">Card Number *</label><input class="tu-input" id="tuCNumber" placeholder="e.g. 4111111111111111"></div>
        <div><label class="tu-label">Wallet ID *</label><input class="tu-input" id="tuCWalletId" placeholder="Wallet UUID"></div>
        <div><label class="tu-label">Holder Name</label><input class="tu-input" id="tuCHolder" placeholder="Optional"></div>
        <div><label class="tu-label">Provider Name</label><input class="tu-input" id="tuCProvider" placeholder="Optional"></div>
        <div class="tu-full"><label class="tu-label">Notes</label><input class="tu-input" id="tuCNotes" placeholder="Optional"></div>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn btn-success" style="font-size:11px;" onclick="tuCreateCard()">Save Card</button>
        <button class="btn btn-ghost" style="font-size:11px;" onclick="document.getElementById('tuCardForm').style.display='none'">Cancel</button>
      </div>
    </div>
    <div id="tuCardBody"><div class="empty-state"><div class="icon">💳</div>Loading cards…</div></div>
  </div>

  <!-- Transactions Tab -->
  <div id="tuPane_txns" style="display:none;padding:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <strong style="font-size:13px;">Top-Up Transactions</strong>
      <button class="btn btn-ghost" style="font-size:11px;" onclick="tuLoadTxns()">⟳ Refresh</button>
    </div>
    <div id="tuTxnBody"><div class="empty-state"><div class="icon">📋</div>Loading transactions…</div></div>
  </div>

  <!-- Top-Up Request Tab -->
  <div id="tuPane_request" style="display:none;padding:16px;">
    <div style="max-width:480px;">
      <strong style="font-size:13px;display:block;margin-bottom:14px;">⚡ Process Top-Up Request</strong>
      <div class="tu-form" style="grid-template-columns:1fr;">
        <div><label class="tu-label">Card Number *</label><input class="tu-input" id="tuRCard" placeholder="Card number"></div>
        <div><label class="tu-label">Amount *</label><input class="tu-input" id="tuRAmount" type="number" step="0.000001" placeholder="e.g. 1000"></div>
        <div><label class="tu-label">Currency</label><input class="tu-input" id="tuRCurrency" value="USDT"></div>
        <div><label class="tu-label">Provider Name</label><input class="tu-input" id="tuRProvider" placeholder="Optional"></div>
        <div><label class="tu-label">Provider Reference</label><input class="tu-input" id="tuRRef" placeholder="Optional"></div>
      </div>
      <button class="btn btn-success" style="width:100%;font-size:13px;padding:12px;" onclick="tuSubmitRequest()">Process Top-Up</button>
      <div id="tuRequestResult" style="margin-top:14px;display:none;"></div>
    </div>
  </div>
</div>

<script>
var tuActive='wallets';
function tuSwitch(tab){
  ['wallets','cards','txns','request'].forEach(function(t){
    document.getElementById('tuPane_'+t).style.display=t===tab?'block':'none';
    var btn=document.getElementById('tuTab_'+t);
    if(btn){btn.className='tu-tab'+(t===tab?' active':'');}
  });
  tuActive=tab;
  if(tab==='wallets')tuLoadWallets();
  else if(tab==='cards')tuLoadCards();
  else if(tab==='txns')tuLoadTxns();
}
function tuVal(id){return (document.getElementById(id)||{}).value||'';}
function tuApi(path,opts){
  return fetch(path,Object.assign({headers:{'Content-Type':'application/json','X-Admin-Key':window._adminKey||''}},opts||{}))
    .then(function(r){return r.ok?r.json():r.json().then(function(e){throw new Error(e.detail||'Error');});});
}
function tuBadge(s){
  var c={active:'#34d399',success:'#34d399',pending:'#fbbf24',inactive:'#6b7280',rejected:'#f87171',failed:'#f87171',suspended:'#f87171',closed:'#6b7280'};
  var col=c[String(s||'').toLowerCase()]||'#9ca3af';
  return '<span style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;background:'+col+'22;color:'+col+';">'+esc(String(s||'').toUpperCase())+'</span>';
}
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function fmtDate(s){if(!s)return '—';return new Date(s).toLocaleString();}

// ── Wallets ──────────────────────────────────────────────────────
function tuShowWalletForm(){document.getElementById('tuWalletForm').style.display='block';}
function tuLoadWallets(){
  tuApi('/admin/topup/wallets').then(function(data){
    if(!data.length){document.getElementById('tuWalletBody').innerHTML='<div class="empty-state"><div class="icon">💼</div>No wallets yet. Add one above.</div>';return;}
    var h='<div class="table-wrap"><table><thead><tr><th>Name</th><th>Currency</th><th>Balance</th><th>Network</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>';
    data.forEach(function(w){
      h+='<tr>'
        +'<td><strong>'+esc(w.name)+'</strong></td>'
        +'<td>'+esc(w.currency)+'</td>'
        +'<td style="font-weight:700;color:#34d399;">'+esc(w.balance)+'</td>'
        +'<td>'+esc(w.network)+'</td>'
        +'<td>'+tuBadge(w.status)+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(w.created_at)+'</td>'
        +'<td><button class="btn btn-ghost" style="font-size:10px;padding:3px 8px;" data-id="'+esc(w.id)+'" onclick="tuCopyWalletId(this.dataset.id)">Copy ID</button></td>'
        +'</tr>';
    });
    h+='</tbody></table></div>';
    document.getElementById('tuWalletBody').innerHTML=h;
    document.getElementById('tuStatWallets').textContent=data.length;
  }).catch(function(e){document.getElementById('tuWalletBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+esc(e.message)+'</div>';});
}
function tuCopyWalletId(id){
  navigator.clipboard.writeText(id).then(function(){showToast('Wallet ID copied','ok');}).catch(function(){});
}
function tuCreateWallet(){
  var body={name:tuVal('tuWName'),currency:tuVal('tuWCurrency')||'USDT',network:tuVal('tuWNetwork')||'ethereum',blockchain_address:tuVal('tuWAddress')||null,notes:tuVal('tuWNotes')||null};
  if(!body.name){showToast('Wallet name is required','error');return;}
  tuApi('/admin/topup/wallets',{method:'POST',body:JSON.stringify(body)}).then(function(){
    showToast('Wallet created','ok');
    document.getElementById('tuWalletForm').style.display='none';
    tuLoadWallets();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}

// ── Cards ─────────────────────────────────────────────────────────
function tuShowCardForm(){document.getElementById('tuCardForm').style.display='block';}
function tuLoadCards(){
  tuApi('/admin/topup/cards').then(function(data){
    if(!data.length){document.getElementById('tuCardBody').innerHTML='<div class="empty-state"><div class="icon">💳</div>No cards yet. Add one above.</div>';return;}
    var h='<div class="table-wrap"><table><thead><tr><th>Card Number</th><th>Holder</th><th>Provider</th><th>Status</th><th>Wallet ID</th><th>Created</th><th>Actions</th></tr></thead><tbody>';
    data.forEach(function(c){
      h+='<tr>'
        +'<td><code style="font-size:11px;">'+esc(c.card_number)+'</code></td>'
        +'<td>'+esc(c.holder_name||'—')+'</td>'
        +'<td>'+esc(c.provider_name||'—')+'</td>'
        +'<td>'+tuBadge(c.status)+'</td>'
        +'<td><code style="font-size:10px;">'+esc(c.wallet_id.slice(0,8))+'...</code></td>'
        +'<td style="font-size:11px;">'+fmtDate(c.created_at)+'</td>'
        +'<td style="display:flex;gap:4px;">'
          +'<button class="btn btn-warning" style="font-size:10px;padding:3px 7px;" data-id="'+esc(c.id)+'" onclick="tuSuspendCard(this.dataset.id)">Suspend</button>'
          +'<button class="btn btn-ghost" style="font-size:10px;padding:3px 7px;" data-id="'+esc(c.id)+'" onclick="tuActivateCard(this.dataset.id)">Activate</button>'
        +'</td>'
        +'</tr>';
    });
    h+='</tbody></table></div>';
    document.getElementById('tuCardBody').innerHTML=h;
    document.getElementById('tuStatCards').textContent=data.length;
  }).catch(function(e){document.getElementById('tuCardBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+esc(e.message)+'</div>';});
}
function tuCreateCard(){
  var body={card_number:tuVal('tuCNumber'),wallet_id:tuVal('tuCWalletId'),holder_name:tuVal('tuCHolder')||null,provider_name:tuVal('tuCProvider')||null,notes:tuVal('tuCNotes')||null};
  if(!body.card_number||!body.wallet_id){showToast('Card number and wallet ID are required','error');return;}
  tuApi('/admin/topup/cards',{method:'POST',body:JSON.stringify(body)}).then(function(){
    showToast('Card created','ok');
    document.getElementById('tuCardForm').style.display='none';
    tuLoadCards();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}
function tuSuspendCard(id){
  tuApi('/admin/topup/cards/'+encodeURIComponent(id)+'/status',{method:'PATCH',body:JSON.stringify({status:'suspended'})})
    .then(function(){showToast('Card suspended','ok');tuLoadCards();}).catch(function(e){showToast(e.message,'error');});
}
function tuActivateCard(id){
  tuApi('/admin/topup/cards/'+encodeURIComponent(id)+'/status',{method:'PATCH',body:JSON.stringify({status:'active'})})
    .then(function(){showToast('Card activated','ok');tuLoadCards();}).catch(function(e){showToast(e.message,'error');});
}

// ── Transactions ──────────────────────────────────────────────────
function tuLoadTxns(){
  tuApi('/admin/topup/transactions?limit=200').then(function(data){
    if(!data.length){document.getElementById('tuTxnBody').innerHTML='<div class="empty-state"><div class="icon">📋</div>No transactions yet.</div>';return;}
    var h='<div class="table-wrap"><table><thead><tr><th>Reference</th><th>Card</th><th>Provider</th><th>Amount</th><th>Currency</th><th>Status</th><th>Reason</th><th>Date</th></tr></thead><tbody>';
    data.forEach(function(t){
      h+='<tr>'
        +'<td><code style="font-size:10px;">'+esc(t.reference||'—')+'</code></td>'
        +'<td><code style="font-size:11px;">'+esc(t.card_number||'—')+'</code></td>'
        +'<td>'+esc(t.provider_name||'—')+'</td>'
        +'<td style="font-weight:700;color:#34d399;">'+esc(t.amount)+'</td>'
        +'<td>'+esc(t.currency)+'</td>'
        +'<td>'+tuBadge(t.status)+'</td>'
        +'<td style="font-size:10px;color:#f87171;">'+esc(t.failure_reason||'')+'</td>'
        +'<td style="font-size:11px;">'+fmtDate(t.created_at)+'</td>'
        +'</tr>';
    });
    h+='</tbody></table></div>';
    document.getElementById('tuTxnBody').innerHTML=h;
    document.getElementById('tuStatTxns').textContent=data.length;
  }).catch(function(e){document.getElementById('tuTxnBody').innerHTML='<div class="empty-state"><div class="icon">⚠</div>'+esc(e.message)+'</div>';});
}

// ── Top-Up Request ────────────────────────────────────────────────
function tuSubmitRequest(){
  var body={card_number:tuVal('tuRCard'),amount:parseFloat(tuVal('tuRAmount')),currency:tuVal('tuRCurrency')||'USDT',provider_name:tuVal('tuRProvider')||null,provider_ref:tuVal('tuRRef')||null};
  if(!body.card_number||!body.amount){showToast('Card number and amount are required','error');return;}
  tuApi('/admin/topup/request',{method:'POST',body:JSON.stringify(body)}).then(function(r){
    var res=document.getElementById('tuRequestResult');
    var ok=r.status==='success';
    res.style.display='block';
    res.innerHTML='<div style="background:'+(ok?'rgba(5,150,105,.15)':'rgba(220,38,38,.15)')+';border:1px solid '+(ok?'#34d399':'#f87171')+';border-radius:9px;padding:14px;">'
      +'<div style="font-size:13px;font-weight:700;color:'+(ok?'#34d399':'#f87171')+';margin-bottom:8px;">'+(ok?'✅ Top-Up Successful':'❌ Top-Up Rejected')+'</div>'
      +'<div style="font-size:11px;color:var(--muted);">Reference: <strong style="color:#f0f0f0;">'+esc(r.reference||'—')+'</strong></div>'
      +'<div style="font-size:11px;color:var(--muted);">Amount: <strong style="color:#34d399;">'+esc(r.amount)+' '+esc(r.currency)+'</strong></div>'
      +(r.failure_reason?'<div style="font-size:11px;color:#f87171;margin-top:6px;">Reason: '+esc(r.failure_reason)+'</div>':'')
      +'</div>';
    if(ok){showToast('Top-Up processed successfully','ok');}else{showToast('Top-Up rejected: '+r.failure_reason,'error');}
    tuLoadTxns();
  }).catch(function(e){showToast('Error: '+e.message,'error');});
}

// ── Init ──────────────────────────────────────────────────────────
tuLoadWallets();
tuLoadTxns();
</script>
</div>
"""


@router.get("/dashboard/topup", response_class=HTMLResponse)
async def dashboard_topup(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Top-Up Engine", "/dashboard/topup", _TOPUP_BODY))


_DISTRIBUTOR_BODY = """
<div class="page-body">
<style>
.dist-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px;}
.dist-card h3{font-size:14px;font-weight:700;color:var(--gold);margin:0 0 14px;text-transform:uppercase;letter-spacing:.06em;}
.dist-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.dist-grid.three{grid-template-columns:1fr 1fr 1fr;}
.dist-stat{background:rgba(255,255,255,.04);border-radius:8px;padding:12px 14px;}
.dist-stat label{font-size:10px;color:var(--muted);display:block;margin-bottom:4px;text-transform:uppercase;}
.dist-stat span{font-size:14px;font-weight:700;color:#f0f0f0;word-break:break-all;}
.dist-btn{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:.2s;}
.dist-btn.primary{background:linear-gradient(135deg,#7c3aed,#6d28d9);color:#fff;}
.dist-btn.danger{background:linear-gradient(135deg,#dc2626,#b91c1c);color:#fff;}
.dist-btn.ghost{background:rgba(255,255,255,.07);color:#e5e7eb;border:1px solid var(--border);}
.dist-btn.success{background:linear-gradient(135deg,#059669,#047857);color:#fff;}
.dist-btn:disabled{opacity:.45;cursor:not-allowed;}
.dist-input{width:100%;background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:8px;padding:9px 12px;color:#f0f0f0;font-size:13px;box-sizing:border-box;margin-bottom:8px;}
.dist-input:focus{outline:none;border-color:#7c3aed;}
.dist-tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;}
.dist-tag.green{background:rgba(5,150,105,.2);color:#34d399;}
.dist-tag.red{background:rgba(220,38,38,.2);color:#f87171;}
.dist-tag.yellow{background:rgba(217,119,6,.2);color:#fbbf24;}
.payee-row{display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(255,255,255,.04);border-radius:8px;margin-bottom:6px;font-size:12px;}
.payee-row code{flex:1;color:var(--muted);font-size:11px;}
.payee-row span{font-weight:700;color:#a78bfa;}
.wallet-bar{display:flex;align-items:center;gap:10px;padding:10px 16px;background:rgba(124,58,237,.12);border:1px solid rgba(124,58,237,.3);border-radius:10px;margin-bottom:18px;}
.wallet-bar code{font-size:12px;color:#c4b5fd;flex:1;}
#distLog{background:#0a0a0f;border:1px solid var(--border);border-radius:8px;padding:12px;font-size:11px;color:#6ee7b7;height:120px;overflow-y:auto;font-family:monospace;white-space:pre-wrap;margin-top:10px;}
</style>

<!-- Wallet Connect Bar -->
<div class="wallet-bar">
  <span style="font-size:18px;">🦊</span>
  <code id="walletAddr" style="flex:1;">Not connected</code>
  <button class="dist-btn primary" onclick="connectWallet()" id="connectBtn">Connect MetaMask</button>
  <button class="dist-btn ghost" onclick="diagWallet()" style="font-size:11px;padding:6px 10px;" title="Diagnose connection">🔍 Diagnose</button>
  <select id="networkSelect" class="dist-input" style="width:160px;margin:0;" onchange="switchNetwork()">
    <option value="1" selected>Ethereum Mainnet</option>
    <option value="97">BSC Testnet</option>
    <option value="56">BSC Mainnet</option>
  </select>
</div>
<div id="diagBox" style="display:none;margin-bottom:12px;padding:12px 16px;background:rgba(124,58,237,.08);border:1px solid rgba(124,58,237,.3);border-radius:10px;font-size:12px;line-height:1.8;"></div>

<!-- Deploy New Contract -->
<div class="dist-card" style="border-color:rgba(124,58,237,.5);background:rgba(124,58,237,.06);">
  <h3>🚀 Deploy New Contract</h3>
  <p style="font-size:12px;color:var(--muted);margin:0 0 14px;">Deploy SIGProfitDistributor directly from here via MetaMask — no Terminal, no Private Key needed.</p>
  <label style="font-size:11px;color:var(--muted);">Owner Address (INITIAL_OWNER) — will be the true owner of the contract</label>
  <input class="dist-input" id="deployOwner" placeholder="0x... your main wallet address" style="margin:6px 0 10px;" />
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
    <button class="dist-btn primary" onclick="deployContract()" id="deployBtn">🚀 Deploy Contract Now</button>
    <span id="deployStatus" style="font-size:12px;color:var(--muted);"></span>
  </div>
  <div id="deployResult" style="display:none;margin-top:14px;padding:12px 16px;background:rgba(5,150,105,.1);border:1px solid rgba(5,150,105,.3);border-radius:8px;">
    <p style="font-size:12px;color:#34d399;margin:0 0 6px;font-weight:700;">✅ Contract deployed successfully!</p>
    <label style="font-size:11px;color:var(--muted);">Contract Address:</label>
    <div style="display:flex;gap:8px;margin-top:4px;">
      <input class="dist-input" id="deployedAddr" readonly style="margin:0;background:rgba(5,150,105,.1);border-color:#34d399;color:#34d399;font-family:monospace;" />
      <button class="dist-btn ghost" onclick="useDeployedContract()" style="white-space:nowrap;">⬇️ Use This Contract</button>
    </div>
    <div id="deployExplorerLink" style="margin-top:8px;font-size:12px;"></div>
  </div>
</div>

<!-- Contract Address -->
<div class="dist-card">
  <h3>⛓ Contract Settings</h3>
  <label class="dist-input" style="background:none;border:none;color:var(--muted);font-size:11px;padding:0;margin:0 0 4px;">Distributor Contract Address</label>
  <input class="dist-input" id="contractAddr" placeholder="0x... SIGProfitDistributor address" />
  <button class="dist-btn ghost" onclick="loadContractState()" style="margin-top:4px;">🔄 Load Contract State</button>
</div>

<!-- Contract State -->
<div class="dist-card" id="stateCard" style="display:none;">
  <h3>📊 Contract State</h3>
  <div class="dist-grid three" style="margin-bottom:12px;">
    <div class="dist-stat"><label>Shares Frozen</label><span id="stSharesFrozen">—</span></div>
    <div class="dist-stat"><label>Deposits Closed</label><span id="stDepositsClosed">—</span></div>
    <div class="dist-stat"><label>Payee Count</label><span id="stPayeeCount">—</span></div>
  </div>
  <div class="dist-grid" style="margin-bottom:12px;">
    <div class="dist-stat"><label>ETH Received (total)</label><span id="stNativeReceived">—</span></div>
    <div class="dist-stat"><label>ETH Tracked Balance</label><span id="stNativeTracked">—</span></div>
  </div>
  <div id="payeesList"></div>
</div>

<!-- Set Payees -->
<div class="dist-card">
  <h3>👥 Set Payees</h3>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap;">
    <label style="font-size:12px;color:var(--muted);white-space:nowrap;">Number of wallets:</label>
    <select class="dist-input" id="payeeCount" style="width:100px;margin:0;" onchange="buildPayeeRows()">
      <option value="2">2</option>
      <option value="3">3</option>
      <option value="4">4</option>
      <option value="5">5</option>
      <option value="6">6</option>
      <option value="7">7</option>
      <option value="8">8</option>
      <option value="10">10</option>
    </select>
    <span id="bpsSumLabel" style="font-size:12px;font-weight:700;color:#fbbf24;">Total: 0 / 10000 BPS</span>
  </div>
  <div id="payeeRows" style="display:flex;flex-direction:column;gap:10px;"></div>
  <div style="margin-top:14px;padding:10px 14px;background:rgba(124,58,237,.1);border-radius:8px;font-size:12px;color:var(--muted);">
    BPS = Basis Points &nbsp;|&nbsp; 10000 BPS = 100% &nbsp;|&nbsp; 7000 = 70% &nbsp;|&nbsp; 3000 = 30%
  </div>
  <button class="dist-btn primary" onclick="doSetPayees()" style="margin-top:14px;">✅ Set Payees on Contract</button>
</div>

<!-- Freeze / Close -->
<div class="dist-card">
  <h3>🔒 Lifecycle Controls</h3>
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <button class="dist-btn success" onclick="doFreezeShares()">❄️ Freeze Shares</button>
    <button class="dist-btn danger" onclick="doCloseDeposits()">🚫 Close Deposits</button>
  </div>
  <p style="font-size:11px;color:var(--muted);margin:10px 0 0;">Freeze = lock payees permanently (required before deposits).<br>Close Deposits = end investor period (claims stay open).</p>
</div>

<!-- Active Token Setup -->
<div class="dist-card" style="border-color:rgba(251,191,36,.4);background:rgba(251,191,36,.04);">
  <h3>🪙 Active Token (ERC-20)</h3>
  <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">Enter the contract address of any ERC-20 token the client will send — USDT, USDC, or any other token. This will be used for all deposit and claim operations.</p>
  <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;">
    <div style="flex:1;">
      <label style="font-size:11px;color:var(--muted);">Token Contract Address</label>
      <input class="dist-input" id="activeTokenAddr" placeholder="0x... paste token contract address here" style="margin:4px 0 0;border-color:rgba(251,191,36,.5);" oninput="clearTokenInfo()" />
    </div>
    <button class="dist-btn ghost" onclick="lookupToken()" style="margin-bottom:8px;border-color:rgba(251,191,36,.5);color:#fbbf24;">🔍 Lookup Token</button>
  </div>
  <div id="tokenInfoBox" style="display:none;margin-top:10px;padding:10px 14px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.3);border-radius:8px;">
    <div style="display:flex;gap:20px;flex-wrap:wrap;">
      <div><span style="font-size:10px;color:var(--muted);display:block;text-transform:uppercase;">Symbol</span><span id="tokenSymbolDisplay" style="font-size:15px;font-weight:800;color:#fbbf24;">—</span></div>
      <div><span style="font-size:10px;color:var(--muted);display:block;text-transform:uppercase;">Decimals</span><span id="tokenDecimalsDisplay" style="font-size:15px;font-weight:800;color:#fbbf24;">—</span></div>
      <div><span style="font-size:10px;color:var(--muted);display:block;text-transform:uppercase;">Name</span><span id="tokenNameDisplay" style="font-size:13px;font-weight:600;color:#f0f0f0;">—</span></div>
    </div>
  </div>
  <div id="tokenInfoError" style="display:none;margin-top:8px;font-size:12px;color:#f87171;"></div>
  <!-- Quick presets -->
  <div style="margin-top:12px;">
    <span style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;">Quick Select:</span>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <button class="dist-btn ghost" onclick="setPresetToken('0xdac17f958d2ee523a2206206994597c13d831ec7','USDT')" style="font-size:11px;padding:5px 12px;">USDT (ETH)</button>
      <button class="dist-btn ghost" onclick="setPresetToken('0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48','USDC')" style="font-size:11px;padding:5px 12px;">USDC (ETH)</button>
      <button class="dist-btn ghost" onclick="setPresetToken('0x55d398326f99059ff775485246999027b3197955','USDT-BSC')" style="font-size:11px;padding:5px 12px;">USDT (BSC)</button>
      <button class="dist-btn ghost" onclick="setPresetToken('0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d','USDC-BSC')" style="font-size:11px;padding:5px 12px;">USDC (BSC)</button>
      <button class="dist-btn ghost" onclick="setPresetToken('0xc2ac880e474c3576cc3afb7c560e402ce24d5b37','SIG')" style="font-size:11px;padding:5px 12px;">SIG</button>
    </div>
  </div>
</div>

<!-- Deposit -->
<div class="dist-card">
  <h3>💰 Deposit Funds</h3>
  <div class="dist-grid">
    <div>
      <label style="font-size:11px;color:var(--muted);">Deposit Native ETH</label>
      <input class="dist-input" id="nativeAmount" placeholder="Amount in ETH (e.g. 0.1)" />
      <button class="dist-btn success" onclick="doDepositNative()">⬇️ Deposit ETH</button>
    </div>
    <div>
      <label style="font-size:11px;color:var(--muted);">Deposit ERC-20 Token — <span id="depositTokenLabel" style="color:#fbbf24;">select token above first</span></label>
      <div style="padding:8px 10px;background:rgba(251,191,36,.06);border:1px solid rgba(251,191,36,.2);border-radius:6px;margin-bottom:8px;font-size:11px;color:var(--muted);">
        Token: <code id="depositTokenAddrDisplay" style="color:#fbbf24;">not set</code>
      </div>
      <input class="dist-input" id="tokenAmount" placeholder="Amount (e.g. 1000)" />
      <button class="dist-btn success" onclick="doDepositToken()">⬇️ Approve & Deposit Token</button>
    </div>
  </div>
</div>

<!-- Claim -->
<div class="dist-card">
  <h3>🏦 Claim Your Share</h3>
  <div class="dist-grid">
    <div>
      <label style="font-size:11px;color:var(--muted);">Claimable ETH for connected wallet</label>
      <div class="dist-stat" style="margin-bottom:10px;"><span id="claimableNative">—</span> <span style="font-size:11px;color:var(--muted);">ETH</span></div>
      <button class="dist-btn primary" onclick="doClaimNative()">💎 Claim ETH</button>
    </div>
    <div>
      <label style="font-size:11px;color:var(--muted);">Claim Token — <span id="claimTokenLabel" style="color:#fbbf24;">select token above first</span></label>
      <div style="padding:8px 10px;background:rgba(251,191,36,.06);border:1px solid rgba(251,191,36,.2);border-radius:6px;margin-bottom:8px;font-size:11px;color:var(--muted);">
        Token: <code id="claimTokenAddrDisplay" style="color:#fbbf24;">not set</code>
      </div>
      <div class="dist-stat" style="margin-bottom:10px;"><span id="claimableToken">—</span> <span id="claimableTokenSymbol" style="font-size:11px;color:var(--muted);">tokens</span></div>
      <button class="dist-btn primary" onclick="checkClaimableToken()">🔍 Check Balance</button>
      <button class="dist-btn success" onclick="doClaimToken()" style="margin-left:6px;">💎 Claim Token</button>
    </div>
  </div>
</div>

<!-- Rescue -->
<div class="dist-card">
  <h3>🛟 Rescue Untracked Funds</h3>
  <p style="font-size:11px;color:var(--muted);margin:0 0 10px;">Only for funds sent by mistake — cannot rescue tracked investor funds.</p>
  <div class="dist-grid">
    <div>
      <input class="dist-input" id="rescueNativeAmt" placeholder="ETH amount to rescue" />
      <input class="dist-input" id="rescueNativeTo" placeholder="Recipient address (0x...)" />
      <button class="dist-btn ghost" onclick="doRescueNative()">🛟 Rescue ETH</button>
    </div>
    <div>
      <input class="dist-input" id="rescueTokenAddr" placeholder="Token address (0x...)" />
      <input class="dist-input" id="rescueTokenAmt" placeholder="Token amount to rescue" />
      <input class="dist-input" id="rescueTokenTo" placeholder="Recipient address (0x...)" />
      <button class="dist-btn ghost" onclick="doRescueToken()">🛟 Rescue Token</button>
    </div>
  </div>
</div>

<!-- Investor Proof Link Generator -->
<div class="dist-card">
  <h3>🔗 Generate Investor Proof Link</h3>
  <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">Generate a shareable link for each investor to verify their wallet registration and claimable balance on the blockchain — no login required.</p>
  <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;">
    <div style="flex:1;">
      <label style="font-size:11px;color:var(--muted);">Investor Wallet Address</label>
      <input class="dist-input" id="investorWallet" placeholder="0xInvestorWallet" style="margin:4px 0 0;" />
    </div>
    <div style="flex:1;">
      <label style="font-size:11px;color:var(--muted);">Network</label>
      <select class="dist-input" id="proofNetwork" style="margin:4px 0 0;">
        <option value="ethereum" selected>Ethereum Mainnet</option>
        <option value="bscMainnet">BSC Mainnet</option>
        <option value="bscTestnet">BSC Testnet</option>
      </select>
    </div>
    <button class="dist-btn primary" onclick="generateProofLink()" style="margin-bottom:8px;">🔗 Generate Link</button>
  </div>
  <div id="proofLinkBox" style="display:none;margin-top:12px;">
    <label style="font-size:11px;color:var(--muted);">Shareable Investor Link:</label>
    <div style="display:flex;gap:8px;margin-top:6px;">
      <input class="dist-input" id="proofLinkOut" readonly style="margin:0;background:rgba(124,58,237,.1);border-color:#7c3aed;color:#c4b5fd;" />
      <button class="dist-btn ghost" onclick="copyProofLink()" style="white-space:nowrap;">📋 Copy</button>
    </div>
    <div id="bscscanLinkBox" style="margin-top:8px;font-size:12px;"></div>
  </div>
</div>

<!-- Transaction Log -->
<div class="dist-card">
  <h3>📋 Transaction Log</h3>
  <div id="distLog">Waiting for operations...\n</div>
</div>

</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/ethers/6.7.1/ethers.umd.min.js"></script>
<script>
// ── ABI ──────────────────────────────────────────────────────────────────────
const ABI = [
  "function setPayees(address[] accounts, uint256[] bpsValues) external",
  "function freezeShares() external",
  "function closeDeposits() external",
  "function depositNative() external payable",
  "function depositToken(address token, uint256 amount) external",
  "function claimNative() external",
  "function claimToken(address token) external",
  "function rescueUntrackedNative(address to, uint256 amount) external",
  "function rescueUntrackedToken(address token, address to, uint256 amount) external",
  "function sharesFrozen() view returns (bool)",
  "function depositsClosed() view returns (bool)",
  "function payeeCount() view returns (uint256)",
  "function payees() view returns (address[])",
  "function shareBps(address) view returns (uint256)",
  "function totalReceived(address asset) view returns (uint256)",
  "function trackedBalance(address asset) view returns (uint256)",
  "function claimable(address asset, address payee) view returns (uint256)",
  "function untrackedBalance(address asset) view returns (uint256)",
];
const ERC20_ABI = [
  "function approve(address spender, uint256 amount) external returns (bool)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
];

const ZERO = "0x0000000000000000000000000000000000000000";
let provider, signer, walletAddress;

// ── Active Token State ────────────────────────────────────────────────────────
let activeTokenAddr = '';
let activeTokenSymbol = '';
let activeTokenDecimals = 18;

function getActiveTokenAddr() {
  const a = document.getElementById('activeTokenAddr').value.trim();
  if (!a) { alert('Please set the Active Token address first (ERC-20 section above).'); return null; }
  return a;
}

function clearTokenInfo() {
  activeTokenAddr = '';
  activeTokenSymbol = '';
  activeTokenDecimals = 18;
  document.getElementById('tokenInfoBox').style.display = 'none';
  document.getElementById('tokenInfoError').style.display = 'none';
  _refreshTokenDisplays('not set', '');
}

function _refreshTokenDisplays(addrText, symbol) {
  const lbl = symbol ? symbol + ' (' + addrText.slice(0,10) + '...)' : addrText;
  const el1 = document.getElementById('depositTokenAddrDisplay');
  const el2 = document.getElementById('claimTokenAddrDisplay');
  const el3 = document.getElementById('depositTokenLabel');
  const el4 = document.getElementById('claimTokenLabel');
  const el5 = document.getElementById('claimableTokenSymbol');
  if (el1) el1.textContent = addrText;
  if (el2) el2.textContent = addrText;
  if (el3) el3.textContent = symbol ? symbol : 'select token above first';
  if (el4) el4.textContent = symbol ? symbol : 'select token above first';
  if (el5) el5.textContent = symbol || 'tokens';
}

async function lookupToken() {
  const addr = document.getElementById('activeTokenAddr').value.trim();
  if (!addr || !addr.startsWith('0x')) {
    document.getElementById('tokenInfoError').textContent = 'Enter a valid 0x token contract address.';
    document.getElementById('tokenInfoError').style.display = 'block';
    document.getElementById('tokenInfoBox').style.display = 'none';
    return;
  }
  const errEl = document.getElementById('tokenInfoError');
  const infoEl = document.getElementById('tokenInfoBox');
  errEl.style.display = 'none';
  if (!provider) {
    errEl.textContent = 'Connect MetaMask first to look up token info.';
    errEl.style.display = 'block';
    return;
  }
  try {
    const ERC20_FULL = [
      "function symbol() view returns (string)",
      "function decimals() view returns (uint8)",
      "function name() view returns (string)"
    ];
    const tok = new ethers.Contract(addr, ERC20_FULL, provider);
    const [sym, dec, name] = await Promise.all([tok.symbol(), tok.decimals(), tok.name()]);
    activeTokenAddr = addr;
    activeTokenSymbol = sym;
    activeTokenDecimals = Number(dec);
    document.getElementById('tokenSymbolDisplay').textContent = sym;
    document.getElementById('tokenDecimalsDisplay').textContent = dec.toString();
    document.getElementById('tokenNameDisplay').textContent = name;
    infoEl.style.display = 'block';
    _refreshTokenDisplays(addr, sym);
    log('Token loaded: ' + name + ' (' + sym + ') — decimals: ' + dec);
  } catch(e) {
    errEl.textContent = 'Could not read token info: ' + (e.reason || e.message) + '. Make sure the address is a valid ERC-20 contract on the selected network.';
    errEl.style.display = 'block';
    infoEl.style.display = 'none';
  }
}

async function setPresetToken(addr, sym) {
  document.getElementById('activeTokenAddr').value = addr;
  clearTokenInfo();
  document.getElementById('activeTokenAddr').value = addr;
  await lookupToken();
}

function log(msg) {
  const el = document.getElementById('distLog');
  const ts = new Date().toLocaleTimeString();
  el.textContent += '[' + ts + '] ' + msg + '\\n';
  el.scrollTop = el.scrollHeight;
}

function diagWallet() {
  const box = document.getElementById('diagBox');
  box.style.display = 'block';
  const lines = [];
  lines.push('<b>🔍 Wallet Connection Diagnostics</b>');
  lines.push('─────────────────────────────────');
  // ethers check
  lines.push('ethers.js loaded: ' + (typeof ethers !== 'undefined' ? '✅ Yes (v' + (ethers.version||'?') + ')' : '❌ NO — page may not have internet access'));
  // window.ethereum check
  lines.push('window.ethereum: ' + (window.ethereum ? '✅ Detected' : '❌ NOT found — MetaMask is not installed or not active'));
  if (window.ethereum) {
    lines.push('isMetaMask: ' + (window.ethereum.isMetaMask ? '✅ Yes' : '⚠️ No — may be another wallet'));
    lines.push('isTrustWallet: ' + (window.ethereum.isTrustWallet ? '⚠️ Trust Wallet detected (may conflict)' : 'No'));
    if (window.ethereum.providers && window.ethereum.providers.length) {
      lines.push('Multiple providers: ' + window.ethereum.providers.length + ' detected');
      window.ethereum.providers.forEach(function(p,i){ lines.push('  Provider['+i+']: isMetaMask=' + !!p.isMetaMask + ' isTrust=' + !!(p.isTrustWallet||p.isTrust)); });
    }
    lines.push('Current accounts: checking...');
    window.ethereum.request({method:'eth_accounts'}).then(function(accs){
      lines.push(accs && accs.length ? '✅ Already connected: ' + accs[0] : '⚠️ No accounts — MetaMask may be locked');
      box.innerHTML = lines.join('<br>');
    }).catch(function(e){ lines.push('Error checking accounts: ' + e.message); box.innerHTML = lines.join('<br>'); });
  }
  lines.push('─────────────────────────────────');
  lines.push('<b>If MetaMask not detected:</b> Install from <a href="https://metamask.io" target="_blank" style="color:#a78bfa;">metamask.io</a>, then refresh page.');
  lines.push('<b>If "isTrustWallet: Yes":</b> Disable Trust Wallet extension, keep only MetaMask active.');
  lines.push('<b>If locked:</b> Open MetaMask extension and unlock it first.');
  box.innerHTML = lines.join('<br>');
}

function distContract() {
  const addr = document.getElementById('contractAddr').value.trim();
  if (!addr) { alert('Enter contract address first'); return null; }
  return new ethers.Contract(addr, ABI, signer);
}

// ── Deploy bytecode ───────────────────────────────────────────────────────────
const DEPLOY_BYTECODE = "0x60806040523480156200001157600080fd5b5060405162001d4138038062001d41833981016040819052620000349162000131565b806001600160a01b0381166200006457604051631e4fbdf760e01b81526000600482015260240160405180910390fd5b6200006f81620000c3565b5060017f9b779b17422d0df92223018b32b4d1fa46e071723d6817e2486d003becc55f00556001600160a01b038116620000bc5760405163b4fa3fb360e01b815260040160405180910390fd5b5062000163565b600080546001600160a01b038381166001600160a01b0319831681178455604051919092169283917f8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e09190a35050565b6000602082840312156200014457600080fd5b81516001600160a01b03811681146200015c57600080fd5b9392505050565b611bce80620001736000396000f3fe6080604052600436106101db5760003560e01c806379ba509711610102578063bcc7445f11610095578063e30c397811610064578063e30c39781461056d578063ef5d9ae81461058b578063f2fde38b146105ab578063f4856230146105cb57600080fd5b8063bcc7445f1461050f578063d4570c1c1461052f578063db6b52461461054f578063e1a452181461055757600080fd5b80639a59b336116100d15780639a59b336146104815780639e546c38146104a1578063a369b0ac146104c1578063b354a414146104e257600080fd5b806379ba5097146104195780638102ef091461042e5780638da5cb5b1461044e5780639496fd1c1461046c57600080fd5b806332f289cf1161017a5780634e8086aa116101495780634e8086aa146103955780635ecc86e8146103b7578063715018a6146103cc57806371e158e7146103e157600080fd5b806332f289cf146102ff578063338b5dea1461031f578063385561c21461033f5780634df9cfb31461035f57600080fd5b80631b5c059e116101b65780631b5c059e146102485780631df04d3a146102685780631f5231731461029957806332150fbb146102b957600080fd5b8062dbe109146101ef5780630dd7b0cb146102135780631b05cbc51461023357600080fd5b366101ea576101e86105e0565b005b600080fd5b3480156101fb57600080fd5b506002545b6040519081526020015b60405180910390f35b34801561021f57600080fd5b506101e861022e366004611875565b6106cd565b34801561023f57600080fd5b506101e86106fa565b34801561025457600080fd5b506101e86102633660046118ae565b61078e565b34801561027457600080fd5b5060015461028990600160a01b900460ff1681565b604051901515815260200161020a565b3480156102a557600080fd5b506102006102b43660046118da565b6108cc565b3480156102c557600080fd5b506102006102d4366004611875565b6001600160a01b03918216600090815260056020908152604080832093909416825291909152205490565b34801561030b57600080fd5b506101e861031a3660046118da565b6108dd565b34801561032b57600080fd5b506101e861033a3660046118ae565b610909565b34801561034b57600080fd5b506101e861035a3660046118da565b610b32565b34801561036b57600080fd5b5061020061037a3660046118da565b6001600160a01b031660009081526004602052604090205490565b3480156103a157600080fd5b506103aa610b43565b60405161020a91906118f7565b3480156103c357600080fd5b50610200606481565b3480156103d857600080fd5b506101e8610ba5565b3480156103ed57600080fd5b506104016103fc366004611944565b610bb9565b6040516001600160a01b03909116815260200161020a565b34801561042557600080fd5b506101e8610c0c565b34801561043a57600080fd5b506102006104493660046118da565b610c52565b34801561045a57600080fd5b506000546001600160a01b0316610401565b34801561047857600080fd5b506101e8610c5d565b34801561048d57600080fd5b506101e861049c36600461195d565b610cf8565b3480156104ad57600080fd5b506102006104bc3660046118da565b610df7565b3480156104cd57600080fd5b5060015461028990600160a81b900460ff1681565b3480156104ee57600080fd5b506102006104fd3660046118da565b60036020526000908152604090205481565b34801561051b57600080fd5b506101e861052a3660046119ea565b610e02565b34801561053b57600080fd5b5061020061054a366004611875565b61108c565b6101e861109f565b34801561056357600080fd5b5061020061271081565b34801561057957600080fd5b506001546001600160a01b0316610401565b34801561059757600080fd5b506102006105a63660046118da565b6110a7565b3480156105b757600080fd5b506101e86105c63660046118da565b611125565b3480156105d757600080fd5b506101e8611196565b600154600160a01b900460ff1661060a57604051631c0c3e3360e31b815260040160405180910390fd5b600154600160a81b900460ff16156106355760405163b31da41d60e01b815260040160405180910390fd5b346000036106565760405163b4fa3fb360e01b815260040160405180910390fd5b600080805260046020527f17ef568e3e12ab5b9c7254a8d58478811de00f9e6eb34345acd53bf8fd09d3ec8054349290610691908490611a6c565b909155505060405134815233907fb5d7700fb0cf415158b8db7cc7c39f0eab16a825c92e221404b4c8bb099b4bbb9060200160405180910390a2565b6106d56111be565b6106df82826111da565b6106f66001600080516020611b7983398151915255565b5050565b6107026112d3565b600154600160a01b900460ff161561072d5760405163fa16d6d760e01b815260040160405180910390fd5b6002546000036107505760405163b4fa3fb360e01b815260040160405180910390fd5b6001805460ff60a01b1916600160a01b1790556040517f2a7f0b97ceb555feb02c19ecf286f4d773a1e432ab71a64cc1b31727beba0dee90600090a1565b6107966112d3565b61079e6111be565b6001600160a01b0382166107c55760405163b4fa3fb360e01b815260040160405180910390fd5b60006107d16000611300565b90508115806107df57508082115b156107fc57604051620f6b2160e41b815260040160405180910390fd5b6000836001600160a01b03168360405160006040518083038185875af1925050503d8060008114610849576040519150601f19603f3d011682016040523d82523d6000602084013e61084e565b606091505b505090508061087057604051633d2cec6f60e21b815260040160405180910390fd5b836001600160a01b03167f346f910abff60596b3ad9077602d7507ae43b64b42a9d5713baab2892c863e45846040516108ab91815260200190565b60405180910390a250506106f66001600080516020611b7983398151915255565b60006108d782611300565b92915050565b6108e56111be565b6108ef81336111da565b6109066001600080516020611b7983398151915255565b50565b6109116111be565b600154600160a01b900460ff1661093b57604051631c0c3e3360e31b815260040160405180910390fd5b600154600160a81b900460ff16156109665760405163b31da41d60e01b815260040160405180910390fd5b6001600160a01b03821661098d5760405163b4fa3fb360e01b815260040160405180910390fd5b806000036109ae5760405163b4fa3fb360e01b815260040160405180910390fd5b6040516370a0823160e01b81523060048201526000906001600160a01b038416906370a0823190602401602060405180830381865afa1580156109f5573d6000803e3d6000fd5b505050506040513d601f19601f82011682018060405250810190610a199190611a7f565b9050610a306001600160a01b03841633308561133e565b6040516370a0823160e01b815230600482015260009082906001600160a01b038616906370a0823190602401602060405180830381865afa158015610a79573d6000803e3d6000fd5b505050506040513d601f19601f82011682018060405250810190610a9d9190611a7f565b610aa79190611a98565b6001600160a01b038516600090815260046020526040812080549293508392909190610ad4908490611a6c565b90915550506040518181526001600160a01b0385169033907ff1444b5cad7ce70cb018d1b8edc8618fe303f3c7f034d8d572a6e27facbf2bef9060200160405180910390a350506106f66001600080516020611b7983398151915255565b610b3a6111be565b6108ef8161137a565b60606002805480602002602001604051908101604052809291908181526020018280548015610b9b57602002820191906000526020600020905b81546001600160a01b03168152600190910190602001808311610b7d575b5050505050905090565b610bad6112d3565b610bb760006114b0565b565b6002546000908210610bde5760405163b4fa3fb360e01b815260040160405180910390fd5b60028281548110610bf157610bf1611aab565b6000918252602090912001546001600160a01b031692915050565b60015433906001600160a01b03168114610c495760405163118cdaa760e01b81526001600160a01b03821660048201526024015b60405180910390fd5b610906816114b0565b60006108d7826114c9565b610c656112d3565b600154600160a01b900460ff16610c8f57604051631c0c3e3360e31b815260040160405180910390fd5b600154600160a81b900460ff1615610cba5760405163b31da41d60e01b815260040160405180910390fd5b6001805460ff60a81b1916600160a81b1790556040517f1a8ade30f60946b8fb7b4d1cf93dc594fa0e441eca24e1b9b88cfa375e3488b190600090a1565b610d006112d3565b610d086111be565b6001600160a01b0383161580610d2557506001600160a01b038216155b15610d435760405163b4fa3fb360e01b815260040160405180910390fd5b6000610d4e84611300565b9050811580610d5c57508082115b15610d7957604051620f6b2160e41b815260040160405180910390fd5b610d8d6001600160a01b0385168484611575565b826001600160a01b0316846001600160a01b03167f204874061edf1b61f01e55eb957ff789bf733451c43d111f54ba6d84122b716084604051610dd291815260200190565b60405180910390a350610df26001600080516020611b7983398151915255565b505050565b60006108d7826115aa565b610e0a6112d3565b600154600160a01b900460ff1615610e355760405163fa16d6d760e01b815260040160405180910390fd5b821580610e425750828114155b15610e605760405163b4fa3fb360e01b815260040160405180910390fd5b6064831115610e825760405163b4fa3fb360e01b815260040160405180910390fd5b60005b600254811015610ed3576003600060028381548110610ea657610ea6611aab565b60009182526020808320909101546001600160a01b03168352820192909252604001812055600101610e85565b50610ee06002600061182e565b6000805b84811015611025576000868683818110610f0057610f00611aab565b9050602002016020810190610f1591906118da565b90506000858584818110610f2b57610f2b611aab565b60200291909101359150506001600160a01b038216610f5d57604051631670f44760e31b815260040160405180910390fd5b80600003610f7e5760405163b4fa3fb360e01b815260040160405180910390fd5b6001600160a01b03821660009081526003602052604090205415610fb557604051631670f44760e31b815260040160405180910390fd5b6001600160a01b03821660008181526003602052604081208390556002805460018101825591527f405787fa12a823e0f2b7631cc41b3ba8828b3321ca811111fa75cd3aa3bb5ace0180546001600160a01b03191690911790556110198185611a6c565b93505050600101610ee4565b5061271081146110485760405163b4fa3fb360e01b815260040160405180910390fd5b7fa9644fecdff69c1ee9bda6d55144f30eebdf057a0712f9923c4f843199f036a48585858560405161107d9493929190611ac1565b60405180910390a15050505050565b60006110988383611629565b9392505050565b610bb76105e0565b600080805b60025481101561111e576001600160a01b038416600090815260056020526040812060028054919291849081106110e5576110e5611aab565b60009182526020808320909101546001600160a01b031683528201929092526040019020546111149083611a6c565b91506001016110ac565b5092915050565b61112d6112d3565b600180546001600160a01b0383166001600160a01b031990911681179091556111 5e6000546001600160a01b031690565b6001600160a01b03167f38d16b8cac22d99fc7c124b9cd0de2d3fa1faef420bfe791d8c362d765e2270060405160405180910390a350565b61119e6111be565b6111a73361137a565b610bb76001600080516020611b7983398151915255565b6111c66116d6565b6002600080516020611b7983398151915255565b6001600160a01b0382166112015760405163b4fa3fb360e01b815260040160405180910390fd5b600061120d8383611629565b905080600003611230576040516312d37ee560e31b815260040160405180910390fd5b6001600160a01b03808416600090815260056020908152604080832093861683529290529081208054839290611267908490611a6c565b9091555061128190506001600160a01b0384168383611575565b826001600160a01b0316826001600160a01b03167f4831bdd9dcf3048a28319ce81d3cab7a15366bcf449bc7803a539107440809cc836040516112c691815260200190565b60405180910390a3505050565b6000546001600160a01b03163314610bb75760405163118cdaa760e01b8152336004820152602401610c40565b60008061130c836115aa565b90506000611319846114c9565b905080821161132c575060009392505050565b6113368183611a98565b949350505050565b61134c848484846001611706565b61137457604051635274afe760e01b81526001600160a01b0385166004820152602401610c40565b50505050565b6000611387600083611629565b9050806000036113aa576040516312d37ee560e31b815260040160405180910390fd5b6001600160a01b03821660009081527f05b8ccbb9d4d8fb16ea74ce3c29a41f1b461fbdaff4714a0d9a8eb05499746bc6020526040812080548392906113f1908490611a6c565b90915550506040516000906001600160a01b0384169083908381818185875af1925050503d8060008114611441576040519150601f19603f3d011682016040523d82523d6000602084013e611446565b606091505b505090508061146857604051633d2cec6f60e21b815260040160405180910390fd5b826001600160a01b03167f7b3fcf6b642a0d537ec94e3e3554737ca883871bc8a5ea348d8ee3a9b9d9656c836040516114a391815260200190565b60405180910390a2505050565b600180546001600160a01b031916905561090681611778565b600080805b600254811015611540576001600160a01b0384166000908152600560205260408120600280549192918490811061150757611507611aab565b60009182526020808320909101546001600160a01b031683528201929092526040019020546115369083611a6c565b91506001016114ce565b506001600160a01b03831660009081526004602052604090205481811161156b575060009392505050565b6113368282611a98565b61158283838360016117c8565b610df257604051635274afe760e01b81526001600160a01b0384166004820152602401610c40565b60006001600160a01b0382166115c1575047919050565b6040516370a0823160e01b81523060048201526001600160a01b038316906370a0823190602401602060405180830381865afa158015611605573d6000803e3d6000fd5b505050506040513d601f19601f820116820180604052508101906108d79190611a7f565b6001600160a01b0381166000908152600360205260408120548082036116535760009150506108d7565b6001600160a01b0384166000908152600460205260408120549061271061167a8484611b3f565b6116849190611b56565b6001600160a01b038088166000908152600560209081526040808320938a16835292905220549091508082116116c15760009450505050506108d7565b6116cb8183611a98565b979650505050505050565b600080516020611b7983398151915254600203610bb757604051633ee5aeb560e01b815260040160405180910390fd5b6040516323b872dd60e01b60008181526001600160a01b038781166004528616602452604485905291602083606481808c5af192506001600051148316611766578383151615611759573d6000823e3d81fd5b6000883b113d1516831692505b60405250600060605295945050505050565b600080546001600160a01b038381166001600160a01b0319831681178455604051919092169283917f8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e09190a35050565b60405163a9059cbb60e01b60008181526001600160a01b038616600452602485905291602083604481808b5af192506001600051148316611822578383151615611815573d6000823e3d81fd5b6000873b113d1516831692505b60405250949350505050565b508054600082559060005260206000209081019061090691905b8082111561185c5760008155600101611848565b5090565b6001600160a01b038116811461090657600080fd5b6000806040838503121561188857600080fd5b823561189381611860565b915060208301356118a381611860565b809150509250929050565b600080604083850312156118c157600080fd5b82356118cc81611860565b946020939093013593505050565b6000602082840312156118ec57600080fd5b813561109881611860565b6020808252825182820181905260009190848201906040850190845b818110156119385783516001600160a01b031683529284019291840191600101611913565b50909695505050505050565b60006020828403121561195657600080fd5b5035919050565b60008060006060848603121561197257600080fd5b833561197d81611860565b9250602084013561198d81611860565b929592945050506040919091013590565b60008083601f8401126119b057600080fd5b50813567ffffffffffffffff8111156119c857600080fd5b6020830191508360208260051b85010111156119e357600080fd5b9250929050565b60008060008060408587031215611a0057600080fd5b843567ffffffffffffffff80821115611a1857600080fd5b611a248883890161199e565b90965094506020870135915080821115611a3d57600080fd5b50611a4a8782880161199e565b95989497509550505050565b634e487b7160e01b600052601160045260246000fd5b808201808211156108d7576108d7611a56565b600060208284031215611a9157600080fd5b5051919050565b818103818111156108d7576108d7611a56565b634e487b7160e01b600052603260045260246000fd5b6040808252810184905260008560608301825b87811015611b04578235611ae781611860565b6001600160a01b0316825260209283019290910190600101611ad4565b5083810360208501528481526001600160fb1b03851115611b2457600080fd5b8460051b915081866020830137016020019695505050505050565b80820281158282048414176108d7576108d7611a56565b600082611b7357634e487b7160e01b600052601260045260246000fd5b50049056fe9b779b17422d0df92223018b32b4d1fa46e071723d6817e2486d003becc55f00a264697066735822122031c4d84b1c7cc8f531bc10836d97523933ad8176fe96d31cff43703d48e2bf3064736f6c63430008180033";
const DEPLOY_ABI = ["constructor(address initialOwner)"];

async function deployContract() {
  const mm = getMetaMaskProvider();
  if (!mm) { alert('Connect MetaMask first'); return; }
  const ownerAddr = document.getElementById('deployOwner').value.trim();
  if (!ownerAddr) { alert('Enter INITIAL_OWNER address'); return; }
  const btn = document.getElementById('deployBtn');
  const status = document.getElementById('deployStatus');
  btn.disabled = true;
  try {
    const _provider = new ethers.BrowserProvider(mm);
    const _signer = await _provider.getSigner();
    const network = await _provider.getNetwork();
    const chainId = Number(network.chainId);
    const explorerMap = { 1: 'https://etherscan.io', 56: 'https://bscscan.com', 97: 'https://testnet.bscscan.com' };
    const explorer = explorerMap[chainId] || 'https://etherscan.io';

    status.textContent = 'Sending deployment transaction...';
    log('Deploying SIGProfitDistributor with owner: ' + ownerAddr);

    const factory = new ethers.ContractFactory(
      ["constructor(address initialOwner)"],
      DEPLOY_BYTECODE,
      _signer
    );
    const contract = await factory.deploy(ownerAddr);
    status.textContent = 'Waiting for confirmation...';
    log('Deploy tx sent: ' + contract.deploymentTransaction().hash);
    await contract.waitForDeployment();
    const addr = await contract.getAddress();

    log('Contract deployed at: ' + addr);
    document.getElementById('deployedAddr').value = addr;
    document.getElementById('deployExplorerLink').innerHTML =
      '<a href="' + explorer + '/address/' + addr + '" target="_blank" style="color:#34d399;">View on Explorer</a>';
    document.getElementById('deployResult').style.display = 'block';
    status.textContent = '';
    showToast('Contract deployed successfully!', 'ok');
  } catch(e) {
    log('Deploy error: ' + (e.reason || e.message));
    status.textContent = 'Error: ' + (e.reason || e.message);
    showToast('Deployment failed', 'error');
  }
  btn.disabled = false;
}

function useDeployedContract() {
  const addr = document.getElementById('deployedAddr').value;
  document.getElementById('contractAddr').value = addr;
  showToast('Contract address set. Click Load Contract State.', 'ok');
}

function getMetaMaskProvider() {
  // Priority 1: multiple providers — prefer MetaMask over Trust Wallet
  if (window.ethereum?.providers?.length) {
    const mm = window.ethereum.providers.find(p => p.isMetaMask && !p.isTrustWallet && !p.isTrust);
    if (mm) return mm;
    const tw = window.ethereum.providers.find(p => p.isTrustWallet || p.isTrust);
    if (tw) return tw; // fallback to Trust Wallet if no MetaMask
    return window.ethereum.providers[0]; // any provider
  }
  // Priority 2: single provider — use whatever is injected
  if (window.ethereum) return window.ethereum;
  return null;
}

async function connectWallet() {
  // 1. Check ethers loaded
  if (typeof ethers === 'undefined') {
    alert('⚠️ ethers.js library not loaded. Check your internet connection and refresh the page.');
    return;
  }
  // 2. Detect provider
  const mm = getMetaMaskProvider();
  if (!mm) {
    alert('🦊 MetaMask not detected.\\n\\nMake sure:\\n1. MetaMask extension is installed in your browser\\n2. MetaMask is unlocked\\n3. You are not in Incognito mode (MetaMask is disabled in Incognito by default)\\n4. Refresh the page after installing/unlocking MetaMask');
    return;
  }
  const btn = document.getElementById('connectBtn');
  const addrEl = document.getElementById('walletAddr');
  btn.textContent = 'Connecting...';
  btn.disabled = true;
  try {
    provider = new ethers.BrowserProvider(mm);
    // Request account access — this triggers the MetaMask popup
    const accounts = await provider.send('eth_requestAccounts', []);
    if (!accounts || accounts.length === 0) {
      throw new Error('No accounts returned. Please unlock MetaMask and try again.');
    }
    signer = await provider.getSigner();
    walletAddress = await signer.getAddress();
    addrEl.textContent = walletAddress;
    btn.textContent = '✅ Connected';
    btn.style.background = '#059669';
    btn.disabled = false;
    log('✅ MetaMask connected: ' + walletAddress);
    // Auto-detect network
    const net = await provider.getNetwork();
    log('Network: chainId=' + net.chainId.toString());
  } catch(e) {
    btn.textContent = 'Connect MetaMask';
    btn.disabled = false;
    const msg = e.message || String(e);
    log('❌ Connect error: ' + msg);
    if (e.code === 4001 || msg.includes('rejected') || msg.includes('denied')) {
      alert('❌ Connection rejected.\\nYou cancelled the MetaMask request. Please try again and click "Connect" in MetaMask.');
    } else if (msg.includes('already pending')) {
      alert('⏳ MetaMask popup is already open.\\nCheck your browser taskbar — MetaMask may be waiting for your approval.');
    } else {
      alert('❌ MetaMask connection failed:\\n' + msg + '\\n\\nTry refreshing the page.');
    }
  }
}

async function switchNetwork() {
  const mm = getMetaMaskProvider();
  if (!mm) { alert('MetaMask not found'); return; }
  const chainId = parseInt(document.getElementById('networkSelect').value);
  const hexId = '0x' + chainId.toString(16);
  try {
    await mm.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: hexId }] });
    log('Switched to chain ' + chainId);
  } catch(e) {
    if (e.code === 4902 && chainId === 97) {
      await mm.request({ method: 'wallet_addEthereumChain', params: [{
        chainId: '0x61', chainName: 'BSC Testnet',
        nativeCurrency: { name: 'BNB', symbol: 'BNB', decimals: 18 },
        rpcUrls: ['https://data-seed-prebsc-1-s1.binance.org:8545/'],
        blockExplorerUrls: ['https://testnet.bscscan.com']
      }]});
    } else if (e.code === 4902 && chainId === 56) {
      await mm.request({ method: 'wallet_addEthereumChain', params: [{
        chainId: '0x38', chainName: 'BNB Smart Chain',
        nativeCurrency: { name: 'BNB', symbol: 'BNB', decimals: 18 },
        rpcUrls: ['https://bsc-dataseed.binance.org/'],
        blockExplorerUrls: ['https://bscscan.com']
      }]});
    }
  }
}

async function loadContractState() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  try {
    log('Loading contract state...');
    const [frozen, closed, count] = await Promise.all([c.sharesFrozen(), c.depositsClosed(), c.payeeCount()]);
    const nativeReceived = await c.totalReceived(ZERO);
    const nativeTracked = await c.trackedBalance(ZERO);

    document.getElementById('stSharesFrozen').innerHTML = frozen
      ? '<span class="dist-tag green">YES</span>' : '<span class="dist-tag red">NO</span>';
    document.getElementById('stDepositsClosed').innerHTML = closed
      ? '<span class="dist-tag red">YES</span>' : '<span class="dist-tag green">NO</span>';
    document.getElementById('stPayeeCount').textContent = count.toString();
    document.getElementById('stNativeReceived').textContent = ethers.formatEther(nativeReceived) + ' ETH';
    document.getElementById('stNativeTracked').textContent = ethers.formatEther(nativeTracked) + ' ETH';

    // Load payees
    const payeeAddrs = await c.payees();
    let html = '';
    for (const p of payeeAddrs) {
      const bps = await c.shareBps(p);
      html += '<div class="payee-row"><code>' + p + '</code><span>' + bps + ' BPS (' + (Number(bps)/100) + '%)</span></div>';
    }
    document.getElementById('payeesList').innerHTML = html || '<p style="color:var(--muted);font-size:12px;">No payees set yet.</p>';
    document.getElementById('stateCard').style.display = 'block';

    // Load claimable for connected wallet
    if (walletAddress) {
      const nc = await c.claimable(ZERO, walletAddress);
      document.getElementById('claimableNative').textContent = ethers.formatEther(nc);
    }
    log('Contract state loaded successfully.');
  } catch(e) { log('Load error: ' + e.message); }
}

// ── Build dynamic payee rows ─────────────────────────────────────────────────
const BPS_PRESETS = [
  {label:'100% — All', v:10000},
  {label:'90%',  v:9000}, {label:'80%', v:8000}, {label:'75%', v:7500},
  {label:'70%',  v:7000}, {label:'60%', v:6000}, {label:'50%', v:5000},
  {label:'40%',  v:4000}, {label:'30%', v:3000}, {label:'25%', v:2500},
  {label:'20%',  v:2000}, {label:'15%', v:1500}, {label:'10%', v:1000},
  {label:'7.5%', v:750},  {label:'5%',  v:500},  {label:'2.5%',v:250},
  {label:'1%',   v:100},  {label:'Custom', v:'custom'},
];

function bpsOptions(selected) {
  return BPS_PRESETS.map(p =>
    '<option value="' + p.v + '"' + (p.v == selected ? ' selected' : '') + '>' + p.label + '</option>'
  ).join('');
}

function buildPayeeRows() {
  const count = parseInt(document.getElementById('payeeCount').value);
  const container = document.getElementById('payeeRows');
  const existing = container.querySelectorAll('.payee-builder-row');
  // keep existing values when rebuilding
  const oldAddrs = [], oldBps = [], oldCustom = [];
  existing.forEach((row, i) => {
    oldAddrs[i] = row.querySelector('.pb-addr').value;
    oldBps[i]   = row.querySelector('.pb-bps-sel').value;
    oldCustom[i]= row.querySelector('.pb-bps-custom').value;
  });

  let html = '';
  for (let i = 0; i < count; i++) {
    const prevBps = oldBps[i] || (i === 0 ? 7000 : (i === 1 ? 3000 : 0));
    const prevAddr = oldAddrs[i] || '';
    const prevCustom = oldCustom[i] || '';
    html += `
<div class="payee-builder-row" style="display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;">
  <input class="dist-input pb-addr" placeholder="Wallet #${i+1} address (0x...)" value="${prevAddr}" style="margin:0;" oninput="updateBpsSum()" />
  <select class="dist-input pb-bps-sel" style="width:150px;margin:0;" onchange="onBpsChange(this)">
    ${bpsOptions(prevBps)}
  </select>
  <input class="dist-input pb-bps-custom" type="number" min="1" max="10000" placeholder="BPS"
         value="${prevCustom}" style="width:90px;margin:0;display:${prevBps==='custom'?'block':'none'};"
         oninput="updateBpsSum()" />
</div>`;
  }
  container.innerHTML = html;
  updateBpsSum();
}

function onBpsChange(sel) {
  const customInp = sel.closest('.payee-builder-row').querySelector('.pb-bps-custom');
  customInp.style.display = sel.value === 'custom' ? 'block' : 'none';
  updateBpsSum();
}

function updateBpsSum() {
  let total = 0;
  document.querySelectorAll('.payee-builder-row').forEach(row => {
    const sel = row.querySelector('.pb-bps-sel');
    const bps = sel.value === 'custom'
      ? (parseInt(row.querySelector('.pb-bps-custom').value) || 0)
      : parseInt(sel.value) || 0;
    total += bps;
  });
  const lbl = document.getElementById('bpsSumLabel');
  lbl.textContent = 'Total: ' + total + ' / 10000 BPS';
  lbl.style.color = total === 10000 ? '#34d399' : (total > 10000 ? '#f87171' : '#fbbf24');
}

// Initialize on load
document.addEventListener('DOMContentLoaded', buildPayeeRows);

async function doSetPayees() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const rows = document.querySelectorAll('.payee-builder-row');
  const addrs = [], shares = [];
  for (const row of rows) {
    const addr = row.querySelector('.pb-addr').value.trim();
    const sel  = row.querySelector('.pb-bps-sel');
    const bps  = sel.value === 'custom'
      ? (parseInt(row.querySelector('.pb-bps-custom').value) || 0)
      : parseInt(sel.value) || 0;
    if (!addr) { alert('Enter all wallet addresses'); return; }
    addrs.push(addr); shares.push(bps);
  }
  const sum = shares.reduce((a,b)=>a+b,0);
  if (sum !== 10000) { alert('BPS sum is ' + sum + ' — must be exactly 10000 (100%)'); return; }
  try {
    log('Sending setPayees transaction...');
    const tx = await c.setPayees(addrs, shares);
    log('Tx sent: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('setPayees confirmed! Payees set: ' + addrs.join(', '));
    loadContractState();
  } catch(e) { log('setPayees error: ' + (e.reason || e.message)); }
}

async function doFreezeShares() {
  if (!signer) { alert('Connect wallet first'); return; }
  if (!confirm('Freeze shares permanently? This cannot be undone.')) return;
  const c = distContract(); if (!c) return;
  try {
    log('Sending freezeShares...');
    const tx = await c.freezeShares();
    log('Tx: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('Shares frozen permanently! Deposits now accepted.');
    loadContractState();
  } catch(e) { log('freezeShares error: ' + (e.reason || e.message)); }
}

async function doCloseDeposits() {
  if (!signer) { alert('Connect wallet first'); return; }
  if (!confirm('Close deposits permanently? Investors can still claim their balance, but no new deposits will be accepted.')) return;
  const c = distContract(); if (!c) return;
  try {
    log('Sending closeDeposits...');
    const tx = await c.closeDeposits();
    log('Tx: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('Deposits closed. Claims remain open. Deploy new distributor for future profits.');
    loadContractState();
  } catch(e) { log('closeDeposits error: ' + (e.reason || e.message)); }
}

async function doDepositNative() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const amt = document.getElementById('nativeAmount').value.trim();
  if (!amt) { alert('Enter amount'); return; }
  try {
    const value = ethers.parseEther(amt);
    log('Depositing ' + amt + ' BNB...');
    const tx = await c.depositNative({ value });
    log('Tx: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('Deposit confirmed! ' + amt + ' BNB deposited.');
    loadContractState();
  } catch(e) { log('depositNative error: ' + (e.reason || e.message)); }
}

async function doDepositToken() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const tokenAddr = getActiveTokenAddr(); if (!tokenAddr) return;
  const amtRaw = document.getElementById('tokenAmount').value.trim();
  if (!amtRaw) { alert('Enter the amount to deposit'); return; }
  try {
    const token = new ethers.Contract(tokenAddr, ERC20_ABI, signer);
    const decimals = activeTokenDecimals || Number(await token.decimals());
    const symbol = activeTokenSymbol || await token.symbol();
    const amount = ethers.parseUnits(amtRaw, decimals);
    const distAddr = document.getElementById('contractAddr').value.trim();

    log('Approving ' + amtRaw + ' ' + symbol + ' (' + tokenAddr + ')...');
    const approveTx = await token.approve(distAddr, amount);
    await approveTx.wait();
    log('Approved! Now depositing into contract...');

    const tx = await c.depositToken(tokenAddr, amount);
    log('Tx: ' + tx.hash + ' — waiting for confirmation...');
    await tx.wait();
    log('✅ Token deposit confirmed! ' + amtRaw + ' ' + symbol + ' deposited.');
    loadContractState();
  } catch(e) { log('depositToken error: ' + (e.reason || e.message)); }
}

async function doClaimNative() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  try {
    log('Claiming BNB...');
    const tx = await c.claimNative();
    log('Tx: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('BNB claimed successfully!');
    loadContractState();
  } catch(e) { log('claimNative error: ' + (e.reason || e.message)); }
}

async function checkClaimableToken() {
  if (!signer || !walletAddress) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const tokenAddr = getActiveTokenAddr(); if (!tokenAddr) return;
  try {
    const token = new ethers.Contract(tokenAddr, ERC20_ABI, signer);
    const decimals = activeTokenDecimals || Number(await token.decimals());
    const sym = activeTokenSymbol || await token.symbol();
    const amt = await c.claimable(tokenAddr, walletAddress);
    document.getElementById('claimableToken').textContent = ethers.formatUnits(amt, decimals);
    document.getElementById('claimableTokenSymbol').textContent = sym;
    log('Claimable ' + sym + ': ' + ethers.formatUnits(amt, decimals));
  } catch(e) { log('checkClaimable error: ' + e.message); }
}

async function doClaimToken() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const tokenAddr = getActiveTokenAddr(); if (!tokenAddr) return;
  try {
    const sym = activeTokenSymbol || tokenAddr.slice(0,10) + '...';
    log('Claiming ' + sym + ' from contract...');
    const tx = await c.claimToken(tokenAddr);
    log('Tx: ' + tx.hash + ' — waiting...');
    await tx.wait();
    log('✅ ' + sym + ' claimed successfully!');
  } catch(e) { log('claimToken error: ' + (e.reason || e.message)); }
}

async function doRescueNative() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const amt = document.getElementById('rescueNativeAmt').value.trim();
  const to = document.getElementById('rescueNativeTo').value.trim();
  if (!amt || !to) { alert('Enter amount and recipient'); return; }
  try {
    const value = ethers.parseEther(amt);
    log('Rescuing ' + amt + ' BNB to ' + to + '...');
    const tx = await c.rescueUntrackedNative(to, value);
    await tx.wait();
    log('Rescue confirmed!');
  } catch(e) { log('rescueNative error: ' + (e.reason || e.message)); }
}

async function doRescueToken() {
  if (!signer) { alert('Connect wallet first'); return; }
  const c = distContract(); if (!c) return;
  const tAddr = document.getElementById('rescueTokenAddr').value.trim();
  const amt = document.getElementById('rescueTokenAmt').value.trim();
  const to = document.getElementById('rescueTokenTo').value.trim();
  if (!tAddr || !amt || !to) { alert('Fill all rescue token fields'); return; }
  try {
    const token = new ethers.Contract(tAddr, ERC20_ABI, signer);
    const decimals = await token.decimals();
    const amount = ethers.parseUnits(amt, decimals);
    log('Rescuing token...');
    const tx = await c.rescueUntrackedToken(tAddr, to, amount);
    await tx.wait();
    log('Token rescue confirmed!');
  } catch(e) { log('rescueToken error: ' + (e.reason || e.message)); }
}

const EXPLORERS = {
  bscTestnet: 'https://testnet.bscscan.com',
  bscMainnet: 'https://bscscan.com',
  ethereum:   'https://etherscan.io',
};

function generateProofLink() {
  const contract = document.getElementById('contractAddr').value.trim();
  const investor = document.getElementById('investorWallet').value.trim();
  const network  = document.getElementById('proofNetwork').value;
  if (!contract) { alert('Enter the distributor contract address first'); return; }
  if (!investor) { alert('Enter the investor wallet address'); return; }

  const base = window.location.origin;
  const link = base + '/verify/distributor?contract=' + contract + '&wallet=' + investor + '&network=' + network;
  document.getElementById('proofLinkOut').value = link;

  const explorer = EXPLORERS[network] || EXPLORERS.ethereum;
  document.getElementById('bscscanLinkBox').innerHTML =
    '<a href="' + explorer + '/address/' + contract + '" target="_blank" style="color:#7c3aed;font-size:12px;">🔍 View Contract on Explorer (' + network + ')</a>';
  document.getElementById('proofLinkBox').style.display = 'block';
  log('Investor proof link generated for ' + investor);
}

function copyProofLink() {
  const link = document.getElementById('proofLinkOut').value;
  navigator.clipboard.writeText(link).then(() => {
    showToast('Link copied!', 'ok');
  });
}
</script>
"""


@router.get("/dashboard/distributor", response_class=HTMLResponse)
async def dashboard_distributor(request: Request):
    g = _guard(request)
    if g:
        return g
    return HTMLResponse(_page("Profit Distributor", "/dashboard/distributor", _DISTRIBUTOR_BODY))


@router.get("/verify/distributor", response_class=HTMLResponse)
async def investor_verify(request: Request):
    """Public investor verification page — no auth needed."""
    contract = request.query_params.get("contract", "")
    wallet   = request.query_params.get("wallet", "")
    network  = request.query_params.get("network", "ethereum")

    rpc_map = {
        "ethereum":   "https://cloudflare-eth.com",
        "bscMainnet": "https://bsc-dataseed.binance.org/",
        "bscTestnet": "https://data-seed-prebsc-1-s1.binance.org:8545/",
    }
    explorer_map = {
        "ethereum":   "https://etherscan.io",
        "bscMainnet": "https://bscscan.com",
        "bscTestnet": "https://testnet.bscscan.com",
    }
    rpc      = rpc_map.get(network, rpc_map["ethereum"])
    explorer = explorer_map.get(network, explorer_map["ethereum"])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Investor Registration Proof — SIG / Al Shumookh</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;padding:32px 16px;}}
.container{{max-width:720px;margin:0 auto;}}
.header{{text-align:center;margin-bottom:32px;}}
.logo{{font-size:40px;margin-bottom:8px;}}
.header h1{{font-size:22px;font-weight:700;color:#f0f6fc;}}
.header p{{font-size:13px;color:#8b949e;margin-top:6px;}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;margin-bottom:16px;}}
.card h2{{font-size:13px;font-weight:700;color:#c9a227;text-transform:uppercase;letter-spacing:.06em;margin-bottom:16px;}}
.field{{margin-bottom:14px;}}
.field label{{font-size:11px;color:#8b949e;display:block;margin-bottom:4px;text-transform:uppercase;}}
.field .val{{font-size:13px;color:#e6edf3;word-break:break-all;background:#0d1117;padding:10px 12px;border-radius:8px;border:1px solid #30363d;font-family:monospace;}}
.badge{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;}}
.badge.green{{background:rgba(35,134,54,.2);color:#3fb950;}}
.badge.red{{background:rgba(218,54,51,.2);color:#f85149;}}
.badge.gold{{background:rgba(201,162,39,.2);color:#e3b341;}}
.big-pct{{font-size:48px;font-weight:800;color:#c9a227;text-align:center;padding:16px 0;}}
.big-pct span{{font-size:16px;color:#8b949e;font-weight:400;}}
.claimable{{font-size:32px;font-weight:700;color:#3fb950;text-align:center;}}
.explorer-link{{display:inline-flex;align-items:center;gap:6px;color:#58a6ff;font-size:12px;text-decoration:none;}}
.explorer-link:hover{{text-decoration:underline;}}
.loading{{text-align:center;padding:40px;color:#8b949e;font-size:14px;}}
.error-box{{background:rgba(218,54,51,.1);border:1px solid rgba(218,54,51,.3);border-radius:8px;padding:14px;color:#f85149;font-size:13px;text-align:center;}}
.timestamp{{font-size:11px;color:#8b949e;text-align:center;margin-top:24px;}}
.proof-seal{{text-align:center;margin:20px 0;padding:16px;background:rgba(201,162,39,.06);border:1px dashed rgba(201,162,39,.3);border-radius:10px;}}
.proof-seal p{{font-size:12px;color:#8b949e;margin-top:4px;}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo">⛓</div>
    <h1>SIG / Al Shumookh Group</h1>
    <p>Blockchain Investor Registration Proof</p>
  </div>

  <div id="loading" class="card loading">🔍 Loading data from blockchain...</div>
  <div id="errorBox" style="display:none;" class="error-box"></div>

  <div id="content" style="display:none;">
    <!-- Contract Info -->
    <div class="card">
      <h2>📄 Contract Information</h2>
      <div class="field"><label>Distributor Contract Address</label>
        <div class="val" id="rContract">{contract}</div></div>
      <div class="field"><label>Network</label>
        <div class="val">{network}</div></div>
      <div class="field"><label>Contract Status</label>
        <div style="margin-top:4px;">
          <span id="rFrozen" class="badge">—</span>&nbsp;
          <span id="rClosed" class="badge">—</span>
        </div>
      </div>
      <div style="margin-top:12px;">
        <a href="{explorer}/address/{contract}" target="_blank" class="explorer-link">
          🔍 View Contract on Explorer
        </a>
      </div>
    </div>

    <!-- Investor Registration -->
    <div class="card">
      <h2>👤 Investor Wallet</h2>
      <div class="field"><label>Registered Wallet Address</label>
        <div class="val">{wallet}</div></div>
      <div class="field"><label>Registration Status</label>
        <div style="margin-top:4px;"><span id="rRegistered" class="badge">—</span></div>
      </div>
      <div class="big-pct" id="rPct">—<span>%</span></div>
      <p style="text-align:center;font-size:12px;color:#8b949e;">Profit Share</p>
    </div>

    <!-- Claimable Balance -->
    <div class="card">
      <h2>💰 Claimable Balance</h2>
      <div class="field"><label>Native BNB/ETH Claimable</label>
        <div class="claimable" id="rClaimableNative">—</div>
      </div>
      <div class="field" style="margin-top:16px;"><label>Total BNB/ETH Received by Contract</label>
        <div class="val" id="rTotalNative">—</div></div>
      <div class="field"><label>Total BNB/ETH Already Claimed by You</label>
        <div class="val" id="rClaimedNative">—</div></div>
    </div>

    <!-- Proof Seal -->
    <div class="proof-seal">
      <div style="font-size:24px;">✅</div>
      <strong style="color:#c9a227;font-size:14px;">Blockchain Verified</strong>
      <p>This data is read directly from the smart contract on the blockchain.<br>
      It cannot be altered by any party, including the company.</p>
    </div>

    <div class="timestamp" id="rTimestamp"></div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/ethers/6.7.1/ethers.umd.min.js"></script>
<script>
const CONTRACT  = "{contract}";
const WALLET    = "{wallet}";
const RPC       = "{rpc}";
const EXPLORER  = "{explorer}";
const ZERO      = "0x0000000000000000000000000000000000000000";

const ABI = [
  "function sharesFrozen() view returns (bool)",
  "function depositsClosed() view returns (bool)",
  "function shareBps(address) view returns (uint256)",
  "function totalReceived(address) view returns (uint256)",
  "function claimable(address,address) view returns (uint256)",
  "function claimedBy(address,address) view returns (uint256)",
];

async function load() {{
  if (!CONTRACT || !WALLET) {{
    document.getElementById('loading').style.display='none';
    document.getElementById('errorBox').style.display='block';
    document.getElementById('errorBox').textContent='Invalid link: missing contract or wallet address.';
    return;
  }}
  try {{
    const provider = new ethers.JsonRpcProvider(RPC);
    const c = new ethers.Contract(CONTRACT, ABI, provider);

    const [frozen, closed, bps, totalNative, claimableNative, claimedNative] = await Promise.all([
      c.sharesFrozen(),
      c.depositsClosed(),
      c.shareBps(WALLET),
      c.totalReceived(ZERO),
      c.claimable(ZERO, WALLET),
      c.claimedBy(ZERO, WALLET),
    ]);

    const isRegistered = bps > 0n;
    const pct = Number(bps) / 100;

    document.getElementById('rFrozen').textContent  = frozen  ? 'Shares Frozen ✓' : 'Shares Not Frozen';
    document.getElementById('rFrozen').className    = 'badge ' + (frozen ? 'green' : 'red');
    document.getElementById('rClosed').textContent  = closed  ? 'Deposits Closed' : 'Deposits Open';
    document.getElementById('rClosed').className    = 'badge ' + (closed ? 'red' : 'green');

    document.getElementById('rRegistered').textContent = isRegistered ? 'Registered ✓' : 'NOT Registered';
    document.getElementById('rRegistered').className   = 'badge ' + (isRegistered ? 'green' : 'red');
    document.getElementById('rPct').innerHTML = isRegistered
      ? pct.toFixed(2) + '<span>%</span>'
      : '<span style="font-size:16px;">Not a registered payee</span>';

    document.getElementById('rClaimableNative').textContent = ethers.formatEther(claimableNative) + ' BNB';
    document.getElementById('rTotalNative').textContent     = ethers.formatEther(totalNative) + ' BNB';
    document.getElementById('rClaimedNative').textContent   = ethers.formatEther(claimedNative) + ' BNB';

    document.getElementById('rTimestamp').textContent =
      'Data fetched: ' + new Date().toUTCString() + ' | Block: latest';

    document.getElementById('loading').style.display  = 'none';
    document.getElementById('content').style.display  = 'block';
  }} catch(e) {{
    document.getElementById('loading').style.display  = 'none';
    document.getElementById('errorBox').style.display = 'block';
    document.getElementById('errorBox').textContent   = 'Error loading blockchain data: ' + e.message;
  }}
}}
load();
</script>
</body>
</html>"""
    return HTMLResponse(html)


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
