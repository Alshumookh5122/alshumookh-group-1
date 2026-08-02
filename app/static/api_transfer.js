/* API Transfer Workflow — Transfer Requests, Fiat Deposits, OTC Quotes
   Uses global  api()  and  showToast()  from _SHARED_JS              */

var _BASE = '/api/v1';

function showTab(id) {
  document.querySelectorAll('.tab-panel').forEach(function(p) {
    p.style.display = 'none';
  });
  document.getElementById(id).style.display = '';
  if (id === 'tab-tr')   loadTR();
  if (id === 'tab-fd')   loadFD();
  if (id === 'tab-otc')  loadOTC();
  if (id === 'tab-rate') fetchLiveRate();
}

function sbOtc(s) {
  var colors = {
    CREATED:'#60a5fa', EUR_RECEIVED:'#a78bfa', QUOTE_REQUESTED:'#fbbf24',
    QUOTE_APPROVED:'#34d399', LOCKED:'#34d399', CONVERTING:'#f59e0b',
    USDT_SENT:'#818cf8', CONFIRMED:'#4ade80', COMPLETED:'#22c55e',
    FAILED:'#ef4444', CANCELLED:'#6b7280', PENDING:'#fbbf24',
    RECEIVED:'#34d399', MATCHED:'#818cf8', REFUNDED:'#f87171',
    REQUESTED:'#60a5fa', APPROVED:'#34d399', EXECUTED:'#22c55e', EXPIRED:'#6b7280'
  };
  var c = colors[s] || '#6b7280';
  return '<span style="background:' + c + '22;color:' + c +
    ';padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;">' + s + '</span>';
}

/* ── Transfer Requests ────────────────────────────────────────────── */

function loadTR() {
  var st  = document.getElementById('tr_filter').value;
  var url = _BASE + '/admin/transfer-requests?limit=100' + (st ? '&status=' + st : '');
  api(url).then(function(d) {
    if (!d.ok) {
      document.getElementById('tr_table').innerHTML =
        '<p style="color:#ef4444;">' + JSON.stringify(d) + '</p>';
      return;
    }
    var rows = (d.transfer_requests || []).map(function(x) {
      return '<tr>' +
        '<td><code style="font-size:10px;">' + (x.reference || '') + '</code></td>' +
        '<td>' + sbOtc(x.status) + '</td>' +
        '<td style="font-weight:700;color:var(--gold);">' +
          parseFloat(x.amount_eur || 0).toLocaleString() + ' EUR</td>' +
        '<td>' + (x.amount_usdt
          ? parseFloat(x.amount_usdt).toLocaleString() + ' USDT' : '—') + '</td>' +
        '<td style="font-size:10px;">' + (x.sender_name || '—') + '</td>' +
        '<td><code style="font-size:9px;">' +
          (x.recipient_wallet ? x.recipient_wallet.slice(0, 16) + '…' : '—') +
          '</code></td>' +
        '<td style="font-size:10px;">' + (x.recipient_network || '') + '</td>' +
        '<td style="font-size:10px;">' +
          (x.created_at ? new Date(x.created_at).toLocaleString() : '—') + '</td>' +
        '<td>' +
          '<button class="btn" style="font-size:9px;padding:2px 6px;" ' +
            'onclick="advanceTR(\'' + x.id + '\',\'EUR_RECEIVED\')">EUR ✓</button> ' +
          '<button class="btn" style="font-size:9px;padding:2px 6px;" ' +
            'onclick="advanceTR(\'' + x.id + '\',\'USDT_SENT\')">USDT ✓</button> ' +
          '<button class="btn" style="font-size:9px;padding:2px 6px;' +
            'background:#22c55e22;color:#22c55e;" ' +
            'onclick="advanceTR(\'' + x.id + '\',\'COMPLETED\')">Done</button>' +
        '</td>' +
        '</tr>';
    }).join('');
    document.getElementById('tr_table').innerHTML = rows
      ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>Reference</th><th>Status</th><th>EUR</th><th>USDT</th>' +
          '<th>Sender</th><th>Wallet</th><th>Network</th><th>Created</th><th>Actions</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<p style="color:var(--muted);padding:10px;font-size:12px;">No transfer requests found.</p>';
  }).catch(function(e) {
    document.getElementById('tr_table').innerHTML =
      '<p style="color:#ef4444;">' + e.message + '</p>';
  });
}

function createTR() {
  var eur    = document.getElementById('tr_eur').value;
  var wallet = document.getElementById('tr_wallet').value;
  if (!eur || !wallet) {
    document.getElementById('tr_msg').innerHTML =
      '<span style="color:#ef4444;">EUR amount and wallet are required</span>';
    return;
  }
  var payload = JSON.stringify({
    amount_eur:       parseFloat(eur),
    recipient_wallet: wallet,
    recipient_network: document.getElementById('tr_net').value,
    sender_name: document.getElementById('tr_sender').value || null,
    client_id:   document.getElementById('tr_cid').value    || null,
    notes:       document.getElementById('tr_notes').value  || null
  });
  api(_BASE + '/admin/transfer-requests', { method: 'POST', body: payload }).then(function(d) {
    if (d.ok) {
      document.getElementById('tr_msg').innerHTML =
        '<span style="color:#34d399;">✓ Created: ' + d.transfer_request.reference + '</span>';
      loadTR();
    } else {
      document.getElementById('tr_msg').innerHTML =
        '<span style="color:#ef4444;">' + JSON.stringify(d) + '</span>';
    }
  }).catch(function(e) {
    document.getElementById('tr_msg').innerHTML =
      '<span style="color:#ef4444;">' + e.message + '</span>';
  });
}

function advanceTR(id, status) {
  api(_BASE + '/admin/transfer-requests/' + id + '/advance', {
    method: 'POST',
    body: JSON.stringify({ status: status })
  }).then(function(d) {
    if (d.ok) loadTR();
    else showToast(JSON.stringify(d), 'error');
  }).catch(function(e) { showToast(e.message, 'error'); });
}

/* ── Fiat Deposits ────────────────────────────────────────────────── */

function loadFD() {
  api(_BASE + '/admin/fiat/deposits?limit=100').then(function(d) {
    if (!d.ok) {
      document.getElementById('fd_table').innerHTML =
        '<p style="color:#ef4444;">' + JSON.stringify(d) + '</p>';
      return;
    }
    var rows = (d.deposits || []).map(function(x) {
      return '<tr>' +
        '<td><code style="font-size:10px;">' + (x.reference || '') + '</code></td>' +
        '<td>' + sbOtc(x.status) + '</td>' +
        '<td style="font-weight:700;color:var(--gold);">' +
          parseFloat(x.amount_eur || 0).toLocaleString() + ' EUR</td>' +
        '<td>' + (x.sender_name || '—') + '</td>' +
        '<td>' + (x.sender_bank || '—') + '</td>' +
        '<td style="font-size:10px;">' + (x.payment_method || '') + '</td>' +
        '<td style="font-size:10px;">' + (x.bank_reference || '—') + '</td>' +
        '<td style="font-size:10px;">' +
          (x.created_at ? new Date(x.created_at).toLocaleString() : '—') + '</td>' +
        '<td>' +
          (x.status === 'PENDING'
            ? '<button class="btn" style="font-size:9px;padding:2px 6px;" ' +
                'onclick="confirmFD(\'' + x.id + '\')">Confirm</button> ' : '') +
          '<button class="btn" style="font-size:9px;padding:2px 6px;' +
            'background:#ef444422;color:#ef4444;" ' +
            'onclick="refundFD(\'' + x.id + '\')">Refund</button>' +
        '</td>' +
        '</tr>';
    }).join('');
    document.getElementById('fd_table').innerHTML = rows
      ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>Reference</th><th>Status</th><th>Amount</th><th>Sender</th>' +
          '<th>Bank</th><th>Method</th><th>Bank Ref</th><th>Created</th><th>Actions</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<p style="color:var(--muted);padding:10px;font-size:12px;">No deposits found.</p>';
  }).catch(function(e) {
    document.getElementById('fd_table').innerHTML =
      '<p style="color:#ef4444;">' + e.message + '</p>';
  });
}

function createFD() {
  var eur = document.getElementById('fd_eur').value;
  if (!eur) {
    document.getElementById('fd_msg').innerHTML =
      '<span style="color:#ef4444;">Amount is required</span>';
    return;
  }
  var payload = JSON.stringify({
    amount_eur:     parseFloat(eur),
    sender_name:    document.getElementById('fd_name').value   || null,
    sender_bank:    document.getElementById('fd_bank').value   || null,
    sender_iban:    document.getElementById('fd_iban').value   || null,
    payment_method: document.getElementById('fd_method').value,
    bank_reference: document.getElementById('fd_ref').value    || null
  });
  api(_BASE + '/admin/fiat/deposits', { method: 'POST', body: payload }).then(function(d) {
    if (d.ok) {
      document.getElementById('fd_msg').innerHTML =
        '<span style="color:#34d399;">✓ Registered: ' + d.deposit.reference + '</span>';
      loadFD();
    } else {
      document.getElementById('fd_msg').innerHTML =
        '<span style="color:#ef4444;">' + JSON.stringify(d) + '</span>';
    }
  }).catch(function(e) {
    document.getElementById('fd_msg').innerHTML =
      '<span style="color:#ef4444;">' + e.message + '</span>';
  });
}

function confirmFD(id) {
  api(_BASE + '/admin/fiat/deposits/' + id + '/confirm', { method: 'POST' })
    .then(function(d) { if (d.ok) loadFD(); else showToast(JSON.stringify(d), 'error'); })
    .catch(function(e) { showToast(e.message, 'error'); });
}

function refundFD(id) {
  if (!confirm('Mark this deposit as REFUNDED?')) return;
  api(_BASE + '/admin/fiat/deposits/' + id + '/refund', { method: 'POST', body: '{}' })
    .then(function(d) { if (d.ok) loadFD(); else showToast(JSON.stringify(d), 'error'); })
    .catch(function(e) { showToast(e.message, 'error'); });
}

/* ── OTC Quotes ───────────────────────────────────────────────────── */

function loadOTC() {
  api(_BASE + '/admin/otc/quotes?limit=100').then(function(d) {
    if (!d.ok) {
      document.getElementById('otc_table').innerHTML =
        '<p style="color:#ef4444;">' + JSON.stringify(d) + '</p>';
      return;
    }
    var rows = (d.quotes || []).map(function(x) {
      var done = ['EXECUTED', 'CANCELLED', 'EXPIRED'].indexOf(x.status) >= 0;
      return '<tr>' +
        '<td><code style="font-size:10px;">' + (x.reference || '') + '</code></td>' +
        '<td>' + sbOtc(x.status) + '</td>' +
        '<td style="font-weight:700;">' +
          parseFloat(x.amount_eur || 0).toLocaleString() + ' EUR</td>' +
        '<td style="color:#a78bfa;font-weight:700;">' +
          parseFloat(x.rate_eur_usdt || 0).toFixed(5) + '</td>' +
        '<td style="font-weight:700;color:#34d399;">' +
          parseFloat(x.amount_usdt || 0).toLocaleString() + ' USDT</td>' +
        '<td style="font-size:10px;">' + (x.rate_source || x.source || '') + '</td>' +
        '<td style="font-size:10px;">' +
          (x.locked_until ? new Date(x.locked_until).toLocaleString() : '—') + '</td>' +
        '<td style="font-size:10px;">' +
          (x.created_at ? new Date(x.created_at).toLocaleString() : '—') + '</td>' +
        '<td>' +
          (x.status === 'REQUESTED'
            ? '<button class="btn" style="font-size:9px;padding:2px 5px;" ' +
                'onclick="otcAction(\'' + x.id + '\',\'approve\')">Approve</button> ' : '') +
          (x.status === 'REQUESTED'
            ? '<button class="btn" style="font-size:9px;padding:2px 5px;" ' +
                'onclick="otcAction(\'' + x.id + '\',\'refresh\')">↻ Rate</button> ' : '') +
          (x.status === 'APPROVED'
            ? '<button class="btn" style="font-size:9px;padding:2px 5px;' +
                'background:#34d39922;color:#34d399;" ' +
                'onclick="otcAction(\'' + x.id + '\',\'lock\')">Lock</button> ' : '') +
          (x.status === 'LOCKED'
            ? '<button class="btn" style="font-size:9px;padding:2px 5px;' +
                'background:#22c55e22;color:#22c55e;" ' +
                'onclick="otcAction(\'' + x.id + '\',\'execute\')">Execute</button> ' : '') +
          (!done
            ? '<button class="btn" style="font-size:9px;padding:2px 5px;' +
                'background:#ef444422;color:#ef4444;" ' +
                'onclick="otcAction(\'' + x.id + '\',\'cancel\')">✕</button>' : '') +
        '</td>' +
        '</tr>';
    }).join('');
    document.getElementById('otc_table').innerHTML = rows
      ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>Reference</th><th>Status</th><th>EUR</th><th>Rate</th><th>USDT</th>' +
          '<th>Source</th><th>Locked Until</th><th>Created</th><th>Actions</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<p style="color:var(--muted);padding:10px;font-size:12px;">No OTC quotes found.</p>';
  }).catch(function(e) {
    document.getElementById('otc_table').innerHTML =
      '<p style="color:#ef4444;">' + e.message + '</p>';
  });
}

function createOTC() {
  var eur  = document.getElementById('otc_eur').value;
  if (!eur) {
    document.getElementById('otc_msg').innerHTML =
      '<span style="color:#ef4444;">Amount is required</span>';
    return;
  }
  var rate = document.getElementById('otc_rate').value;
  document.getElementById('otc_msg').innerHTML =
    '<span style="color:#fbbf24;">⏳ Fetching rate...</span>';
  var payload = JSON.stringify({
    amount_eur:      parseFloat(eur),
    manual_rate:     rate ? parseFloat(rate) : null,
    fiat_deposit_id: document.getElementById('otc_fdid').value  || null,
    notes:           document.getElementById('otc_notes').value || null
  });
  api(_BASE + '/admin/otc/quotes', { method: 'POST', body: payload }).then(function(d) {
    if (d.ok) {
      var q = d.quote;
      document.getElementById('otc_msg').innerHTML =
        '<span style="color:#34d399;">✓ ' + q.reference + ' | ' +
        parseFloat(q.rate_eur_usdt).toFixed(5) + ' | ' +
        parseFloat(q.amount_usdt).toLocaleString() + ' USDT</span>';
      loadOTC();
    } else {
      document.getElementById('otc_msg').innerHTML =
        '<span style="color:#ef4444;">' + JSON.stringify(d) + '</span>';
    }
  }).catch(function(e) {
    document.getElementById('otc_msg').innerHTML =
      '<span style="color:#ef4444;">' + e.message + '</span>';
  });
}

function otcAction(id, action) {
  api(_BASE + '/admin/otc/quotes/' + id + '/' + action, { method: 'POST' })
    .then(function(d) { if (d.ok) loadOTC(); else showToast(JSON.stringify(d), 'error'); })
    .catch(function(e) { showToast(e.message, 'error'); });
}

/* ── Live Rate ────────────────────────────────────────────────────── */

var _liveRate = null;

function fetchLiveRate() {
  document.getElementById('live_rate_val').textContent = '⏳';
  api(_BASE + '/admin/otc/rate').then(function(d) {
    if (d.ok) {
      _liveRate = parseFloat(d.rate);
      document.getElementById('live_rate_val').textContent =
        _liveRate.toFixed(5) + ' USDT';
      document.getElementById('live_rate_src').textContent  = 'Source: ' + d.source;
      document.getElementById('live_rate_time').textContent =
        'Updated: ' + new Date().toLocaleTimeString();
      calcUsdt();
    } else {
      document.getElementById('live_rate_val').textContent = 'Error';
    }
  }).catch(function(e) {
    document.getElementById('live_rate_val').textContent = 'Error: ' + e.message;
  });
}

function calcUsdt() {
  if (!_liveRate) return;
  var eur = parseFloat(document.getElementById('calc_eur').value) || 0;
  document.getElementById('calc_usdt').textContent =
    (eur * _liveRate).toFixed(2) + ' USDT';
}

/* ── Init ─────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() { loadTR(); });
