const adminKeyInput = document.querySelector('#adminKey');
const clientKeyInput = document.querySelector('#clientKey');
const saveKeyButton = document.querySelector('#saveKey');
const refreshButton = document.querySelector('#refresh');
const orderForm = document.querySelector('#orderForm');
const directCryptoForm = document.querySelector('#directCryptoForm');
const createdLink = document.querySelector('#createdLink');
const directResult = document.querySelector('#directResult');
const ledgerWallet = document.querySelector('#ledgerWallet');
const copyWalletButton = document.querySelector('#copyWallet');
const openReportButton = document.querySelector('#openReport');
const alchemyBody = document.querySelector('#alchemyBody');
const readinessBody = document.querySelector('#readinessBody');
const securityBody = document.querySelector('#securityBody');
const counterpartiesBody = document.querySelector('#counterpartiesBody');
const counterpartyForm = document.querySelector('#counterpartyForm');
const counterpartyMessage = document.querySelector('#counterpartyMessage');

const LEDGER_ETHEREUM_WALLET = '0xBD682cfD8382a90adfDd6745780D3D7959c4d939';

const MARKET_IDS = {
  ETH: 'ethereum',
  USDT: 'tether',
  USDC: 'usd-coin',
};

const state = {
  adminKey: localStorage.getItem('adminApiKey') || '',
  clientKey: localStorage.getItem('clientApiKey') || '',
  counterparties: [],
};

adminKeyInput.value = state.adminKey;
clientKeyInput.value = state.clientKey;

if (ledgerWallet) {
  ledgerWallet.textContent = LEDGER_ETHEREUM_WALLET;
}

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-Admin-API-Key': state.adminKey,
  };
}

function setApiState(text) {
  const element = document.querySelector('#apiState');
  const value = String(text || '');
  element.textContent = value.length > 90 ? `${value.slice(0, 90)}...` : value;
  element.title = value;
}

function formatDate(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ar');
}

function formatUsd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }

  return Number(value).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: Number(value) >= 10 ? 2 : 6,
  });
}

function formatAmount(value, currency = '', maximumFractionDigits = 8) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
    return '-';
  }

  const number = Number(value);
  const formatted = number.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  });

  return `${formatted}${currency ? ` ${currency}` : ''}`;
}

function formatChange(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }

  const number = Number(value);
  const sign = number > 0 ? '+' : '';

  return `${sign}${number.toFixed(2)}%`;
}

function qrUrl(text, size = 180) {
  return `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(text)}`;
}

function publicPaymentUrl(order) {
  const id = order.id || order.transaction_id;
  return `${window.location.origin}/pay/direct/${id}`;
}

function explorerLink(network, txHash) {
  if (!txHash) return '';

  if (String(network || '').toLowerCase() === 'base') {
    return `https://basescan.org/tx/${txHash}`;
  }

  return `https://etherscan.io/tx/${txHash}`;
}

async function copyText(text, message = 'تم النسخ') {
  await navigator.clipboard.writeText(text);
  setApiState(message);
}

function readableApiError(detail) {
  if (!detail) {
    return '';
  }

  if (typeof detail === 'string') {
    return detail;
  }

  if (detail.message) {
    const providerMessage =
      detail.moonpay_response?.message ||
      detail.moonpay_response?.error ||
      detail.moonpay_response?.detail;

    return providerMessage
      ? `${detail.message}: ${providerMessage}`
      : detail.message;
  }

  return JSON.stringify(detail);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();

    try {
      const parsed = JSON.parse(message);
      const detail = parsed.detail || parsed.message || parsed.error;
      const readable = readableApiError(detail);

      if (readable) {
        throw new Error(readable);
      }
    } catch (parseError) {
      if (parseError instanceof Error && parseError.message !== message) {
        throw parseError;
      }
    }

    throw new Error(message || `HTTP ${response.status}`);
  }

  return response.json();
}

function renderSummary(summary) {
  document.querySelector('#ordersTotal').textContent =
    summary.orders_total ?? summary.total_orders ?? 0;

  document.querySelector('#ordersCompleted').textContent =
    summary.orders_completed ?? summary.completed_orders ?? 0;

  document.querySelector('#fiatTotal').textContent =
    formatUsd(summary.fiat_completed_total ?? summary.total_fiat_amount ?? 0);
}

function renderReadiness(report) {
  if (!readinessBody) return;

  const warnings = report?.warnings || [];
  const metrics = report?.metrics || {};
  const weakCounterparties = report?.weak_counterparties || [];

  const metricCards = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px;">
      <article class="alchemy-item"><div><span class="alchemy-status ok">Counterparties</span><strong>${metrics.counterparties_total ?? 0}</strong><small>Total configured senders</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status ok">Institutional</span><strong>${metrics.institutional_ready ?? 0}</strong><small>Institutional-ready senders</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status warn">Compatibility</span><strong>${metrics.compatibility_counterparties ?? 0}</strong><small>Still below target security posture</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status warn">Manual Review</span><strong>${metrics.manual_review_payloads ?? 0}</strong><small>Payloads waiting human action</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status bad">Failed</span><strong>${metrics.failed_payloads ?? 0}</strong><small>Payloads currently failed</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status ok">Reconciled</span><strong>${metrics.reconciled_payloads ?? 0}</strong><small>Payloads fully reconciled</small></div></article>
    </div>
  `;

  const weakList = weakCounterparties.length
    ? `
      <div style="margin-bottom:16px;">
        <strong style="display:block;margin-bottom:8px;">Counterparties needing hardening</strong>
        <div style="display:grid;gap:8px;">
          ${weakCounterparties.map((client) => `
            <article class="alchemy-item">
              <div>
                <span class="alchemy-status warn">${client.posture}</span>
                <strong>${client.name}</strong>
                <small>Score ${client.score} · Allowed IPs ${client.allowed_ip_count}</small>
              </div>
            </article>
          `).join('')}
        </div>
      </div>
    `
    : '';

  if (!warnings.length) {
    readinessBody.innerHTML = metricCards + weakList + '<div class="empty-state">No active enterprise readiness warnings.</div>';
    return;
  }

  readinessBody.innerHTML = metricCards + weakList + warnings
    .map((warning) => `
      <article class="alchemy-item">
        <div>
          <span class="alchemy-status warn">Warning</span>
          <strong>${warning}</strong>
          <small>Review and close before high-value onboarding.</small>
        </div>
      </article>
    `)
    .join('');
}

function renderCounterparties(report) {
  if (!counterpartiesBody) return;

  const clients = report?.clients || [];
  state.counterparties = clients;
  if (!clients.length) {
    counterpartiesBody.innerHTML = '<tr><td colspan="9" style="padding:20px;text-align:center;color:#667085;">No counterparties found.</td></tr>';
    return;
  }

  counterpartiesBody.innerHTML = clients.map((client) => {
    const controls = [
      client.allowed_ip_count ? `IP(${client.allowed_ip_count})` : null,
      client.hmac_required ? 'HMAC' : null,
      client.oauth_required ? 'OAuth2' : null,
      client.mtls_required ? 'mTLS' : null,
      client.jws_required ? 'JWS' : null,
      client.jwe_required ? 'JWE' : null,
    ].filter(Boolean).join(', ') || 'API key only';

    return `
      <tr>
        <td>${client.name}</td>
        <td><span class="badge ${String(client.posture).toUpperCase()}">${client.posture}</span></td>
        <td>${client.security_score}</td>
        <td>${client.allowed_ip_count}</td>
        <td>${controls}</td>
        <td>${client.payload_count}</td>
        <td>${formatDate(client.latest_payload_at)}</td>
        <td>${client.latest_verification_status || '-'}</td>
        <td class="actions-cell">
          <button class="small" type="button" onclick="editCounterparty('${client.client_id}')">Edit</button>
          <button class="small" type="button" onclick="rotateCounterpartySecrets('${client.client_id}')">Rotate</button>
        </td>
      </tr>
    `;
  }).join('');
}

function renderSecurity(report) {
  if (!securityBody) return;

  const summary = report?.summary || {};
  const blocked = report?.blocked_ips || [];
  const suspiciousIps = report?.suspicious_ips || [];
  const suspiciousPaths = report?.suspicious_paths || [];
  const requestFrequency = report?.request_frequency || [];
  const events = report?.recent_events || [];

  const cards = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px;">
      <article class="alchemy-item"><div><span class="alchemy-status bad">Blocked IPs</span><strong>${summary.blocked_ip_count ?? 0}</strong><small>Currently banned</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status warn">Suspicious IPs</span><strong>${summary.suspicious_ip_count ?? 0}</strong><small>Risk-scored sources</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status bad">Failed Logins</span><strong>${summary.failed_login_count ?? 0}</strong><small>Recent failed auth attempts</small></div></article>
      <article class="alchemy-item"><div><span class="alchemy-status warn">Security Events</span><strong>${summary.security_event_count ?? 0}</strong><small>Recent alerts and probes</small></div></article>
    </div>
  `;

  const blockedList = blocked.length
    ? blocked.map((item) => `<article class="alchemy-item"><div><span class="alchemy-status bad">Blocked</span><strong>${item.ip}</strong><small>${item.seconds_remaining}s remaining</small></div></article>`).join('')
    : '<div class="empty-state">No blocked IPs right now.</div>';

  const suspiciousList = suspiciousIps.length
    ? suspiciousIps.slice(0, 8).map((item) => `
      <article class="alchemy-item">
        <div>
          <span class="alchemy-status warn">Score ${item.score}</span>
          <strong>${item.ip}</strong>
          <small>${item.country || '-'} · failed logins ${item.failed_logins || 0}</small>
        </div>
      </article>
    `).join('')
    : '<div class="empty-state">No suspicious IPs currently tracked.</div>';

  const pathList = suspiciousPaths.length
    ? suspiciousPaths.slice(0, 8).map((item) => `
      <article class="alchemy-item">
        <div>
          <span class="alchemy-status warn">Path</span>
          <strong>${item.path}</strong>
          <small>${item.count} hits</small>
        </div>
      </article>
    `).join('')
    : '<div class="empty-state">No suspicious paths observed yet.</div>';

  const requesterList = requestFrequency.length
    ? requestFrequency.slice(0, 8).map((item) => `
      <article class="alchemy-item">
        <div>
          <span class="alchemy-status ok">Requests ${item.requests}</span>
          <strong>${item.ip}</strong>
          <small>${item.country || '-'} · failed logins ${item.failed_logins || 0}</small>
        </div>
      </article>
    `).join('')
    : '<div class="empty-state">No request-frequency data yet.</div>';

  const eventList = events.length
    ? events.slice(0, 10).map((item) => `
      <article class="alchemy-item">
        <div>
          <span class="alchemy-status ${String(item.event_type || '').startsWith('SECURITY_') ? 'bad' : 'warn'}">${item.event_type}</span>
          <strong>${item.ip || item.request_id || '-'}</strong>
          <small>${formatDate(item.created_at)} · ${item.endpoint || '-'}</small>
        </div>
      </article>
    `).join('')
    : '<div class="empty-state">No recent security events.</div>';

  securityBody.innerHTML = `
    ${cards}
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;">
      <div><strong style="display:block;margin-bottom:8px;">Blocked IPs</strong>${blockedList}</div>
      <div><strong style="display:block;margin-bottom:8px;">Suspicious IPs</strong>${suspiciousList}</div>
      <div><strong style="display:block;margin-bottom:8px;">Suspicious Paths</strong>${pathList}</div>
      <div><strong style="display:block;margin-bottom:8px;">Request Frequency</strong>${requesterList}</div>
    </div>
    <div style="margin-top:16px;">
      <strong style="display:block;margin-bottom:8px;">Recent Security Events</strong>
      ${eventList}
    </div>
  `;
}

function counterpartyPayloadFromForm() {
  const allowedIps = String(document.querySelector('#cpAllowedIps')?.value || '')
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);

  return {
    name: document.querySelector('#cpName')?.value?.trim(),
    allowed_ips: allowedIps.length ? allowedIps : null,
    is_active: document.querySelector('#cpIsActive')?.checked,
    hmac_required: document.querySelector('#cpHmac')?.checked,
    oauth_required: document.querySelector('#cpOauth')?.checked,
    mtls_required: document.querySelector('#cpMtls')?.checked,
    mtls_cert_fingerprint: document.querySelector('#cpMtlsFingerprint')?.value?.trim() || null,
    jws_required: document.querySelector('#cpJws')?.checked,
    jws_public_key_pem: document.querySelector('#cpJwsPem')?.value?.trim() || null,
    jwe_required: document.querySelector('#cpJwe')?.checked,
  };
}

function resetCounterpartyForm() {
  document.querySelector('#counterpartyId').value = '';
  document.querySelector('#cpName').value = '';
  document.querySelector('#cpAllowedIps').value = '';
  document.querySelector('#cpIsActive').checked = true;
  document.querySelector('#cpHmac').checked = false;
  document.querySelector('#cpOauth').checked = false;
  document.querySelector('#cpMtls').checked = false;
  document.querySelector('#cpJws').checked = false;
  document.querySelector('#cpJwe').checked = false;
  document.querySelector('#cpMtlsFingerprint').value = '';
  document.querySelector('#cpJwsPem').value = '';
  document.querySelector('#counterpartySaveBtn').textContent = 'Create Counterparty';
  document.querySelector('#counterpartyRotateBtn').disabled = true;
  counterpartyMessage.hidden = true;
  counterpartyMessage.textContent = '';
}

function showCounterpartyMessage(text, ok = true) {
  if (!counterpartyMessage) return;
  counterpartyMessage.hidden = false;
  counterpartyMessage.className = `result ${ok ? 'status-ok' : 'status-bad'}`;
  counterpartyMessage.textContent = text;
}

function editCounterparty(clientId) {
  const client = state.counterparties.find((item) => item.client_id === clientId);
  if (!client) return;

  document.querySelector('#counterpartyId').value = client.client_id;
  document.querySelector('#cpName').value = client.name || '';
  document.querySelector('#cpAllowedIps').value = (client.allowed_ips || []).join(', ');
  document.querySelector('#cpIsActive').checked = !!client.is_active;
  document.querySelector('#cpHmac').checked = !!client.hmac_required;
  document.querySelector('#cpOauth').checked = !!client.oauth_required;
  document.querySelector('#cpMtls').checked = !!client.mtls_required;
  document.querySelector('#cpJws').checked = !!client.jws_required;
  document.querySelector('#cpJwe').checked = !!client.jwe_required;
  document.querySelector('#cpMtlsFingerprint').value = client.mtls_cert_fingerprint || '';
  document.querySelector('#cpJwsPem').value = '';
  document.querySelector('#counterpartySaveBtn').textContent = 'Update Counterparty';
  document.querySelector('#counterpartyRotateBtn').disabled = false;
  showCounterpartyMessage(`Editing ${client.name}. Add fingerprint or JWS key only if changing them.`, true);
}

async function rotateCounterpartySecrets(clientId) {
  const id = clientId || document.querySelector('#counterpartyId').value;
  if (!id) {
    showCounterpartyMessage('Select a counterparty first.', false);
    return;
  }

  try {
    const data = await api(`/api/v1/admin/clients/${id}/rotate-secrets`, {
      method: 'POST',
    });
    showCounterpartyMessage(
      `New credentials issued for ${data.name}. API key: ${data.api_key} | OAuth client id: ${data.oauth_client_id}`,
      true,
    );
    await refreshAll();
  } catch (error) {
    showCounterpartyMessage(error.message, false);
  }
}

function renderOrders(orders) {
  const body = document.querySelector('#ordersBody');
  body.innerHTML = '';

  for (const order of orders) {
    const row = document.createElement('tr');

    const wallet =
      order.wallet ||
      order.treasury_wallet_address ||
      order.user_wallet_address ||
      LEDGER_ETHEREUM_WALLET;

    const clientLink = publicPaymentUrl(order);

    row.innerHTML = `
      <td>${order.external_id || order.id}</td>
      <td><span class="badge ${order.status}">${order.status}</span></td>
      <td>${order.network}</td>
      <td>${formatAmount(order.fiat_amount, order.fiat_currency, 2)}</td>
      <td>${formatAmount(order.crypto_amount, order.crypto_currency, 8)}</td>
      <td class="mono-cell">${wallet}</td>
      <td>${formatDate(order.created_at)}</td>
      <td class="actions-cell">
        <button class="small" type="button" data-copy-link="${clientLink}">نسخ رابط العميل</button>
        <button class="small status-ok" type="button" data-status-order="${order.id}" data-status-value="COMPLETED">تم الدفع</button>
        <button class="small status-bad" type="button" data-status-order="${order.id}" data-status-value="FAILED">مرفوض</button>
      </td>
    `;

    body.appendChild(row);
  }
}

function docButton(label, url) {
  if (!url) {
    return '<span class="muted-cell">غير متاح</span>';
  }

  return `<button class="small" type="button" data-doc-url="${url}">${label}</button>`;
}

function renderDocuments(documents) {
  const body = document.querySelector('#documentsBody');
  body.innerHTML = '';

  for (const item of documents) {
    const row = document.createElement('tr');

    row.innerHTML = `
      <td>${item.external_id || item.transaction_id}</td>
      <td><span class="badge ${item.status}">${item.status}</span></td>
      <td>${formatAmount(item.crypto_amount || item.fiat_amount, item.crypto_currency || item.fiat_currency, 8)}</td>
      <td class="mono-cell">${item.wallet || LEDGER_ETHEREUM_WALLET}</td>
      <td>${docButton('فاتورة', item.invoice_url)}</td>
      <td>${docButton('Pending', item.pending_url)}</td>
      <td>${docButton('استلام', item.receive_receipt_url)}</td>
      <td>${docButton('إرسال', item.send_receipt_url)}</td>
    `;

    body.appendChild(row);
  }
}

function renderLogs(logs) {
  const body = document.querySelector('#logsBody');
  body.innerHTML = '';

  for (const log of logs) {
    const item = document.createElement('article');
    item.className = 'log-item';

    item.innerHTML = `
      <strong>${log.event_type}</strong>
      <span>${formatDate(log.created_at)}</span>
      <code>${JSON.stringify(log.details || {}, null, 2)}</code>
    `;

    body.appendChild(item);
  }
}

function renderAlchemyEvents(logs) {
  if (!alchemyBody) return;

  alchemyBody.innerHTML = '';

  const events = logs.filter((log) => String(log.event_type || '').startsWith('ALCHEMY_'));

  if (!events.length) {
    alchemyBody.innerHTML = '<div class="empty-state">لا توجد أحداث Alchemy ضمن آخر السجلات المعروضة.</div>';
    return;
  }

  for (const log of events) {
    const details = log.details || {};
    const item = document.createElement('article');
    item.className = 'alchemy-item';
    const txUrl = explorerLink(details.network, details.tx_hash);

    const statusClass =
      log.event_type === 'ALCHEMY_PAYMENT_CONFIRMED'
        ? 'ok'
        : log.event_type === 'ALCHEMY_UNSUPPORTED_TOKEN_CONTRACT'
          ? 'bad'
          : 'warn';

    item.innerHTML = `
      <div>
        <span class="alchemy-status ${statusClass}">${log.event_type}</span>
        <strong>${formatAmount(details.display_amount || details.amount, details.asset || details.raw_asset || '', 8)}</strong>
        <small>${formatDate(log.created_at)}</small>
      </div>
      <dl>
        <dt>Amount</dt><dd>${formatAmount(details.display_amount || details.amount, details.asset || details.raw_asset || '', 8)}</dd>
        <dt>Network</dt><dd>${details.network || '-'}</dd>
        <dt>Wallet</dt><dd class="mono-cell">${details.to_address || '-'}</dd>
        <dt>Contract</dt><dd class="mono-cell">${details.contract_address || 'Native ETH'}</dd>
        <dt>TX</dt><dd class="mono-cell">${txUrl ? `<a href="${txUrl}" target="_blank" rel="noopener">${details.tx_hash}</a>` : (details.tx_hash || '-')}</dd>
      </dl>
    `;

    alchemyBody.appendChild(item);
  }
}

async function refreshMarketTicker() {
  const ids = Object.values(MARKET_IDS).join(',');
  const tickerState = document.querySelector('#tickerState');

  try {
    const response = await fetch(
      `https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd&include_24hr_change=true`,
      { cache: 'no-store' },
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    for (const [symbol, id] of Object.entries(MARKET_IDS)) {
      const priceEl = document.querySelector(`#price${symbol}`);
      const changeEl = document.querySelector(`#change${symbol}`);
      const item = data[id] || {};
      const change = item.usd_24h_change;

      priceEl.textContent = formatUsd(item.usd);
      changeEl.textContent = formatChange(change);
      changeEl.className = Number(change) >= 0 ? 'up' : 'down';
    }

    tickerState.textContent = 'Live';
  } catch (error) {
    tickerState.textContent = 'Offline';
  }
}

async function openHtmlWindow(url, title) {
  if (!state.adminKey) {
    setApiState('أدخل مفتاح الإدارة');
    return;
  }

  const win = window.open('about:blank', '_blank');

  if (!win) {
    throw new Error('المتصفح منع فتح النافذة');
  }

  win.document.open();
  win.document.write(`
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <title>${title}</title>
      </head>
      <body style="font-family:Arial;padding:32px">
        Loading...
      </body>
    </html>
  `);
  win.document.close();

  const response = await fetch(url, {
    headers: {
      'X-Admin-API-Key': state.adminKey,
    },
  });

  if (!response.ok) {
    const message = await response.text();

    win.document.open();
    win.document.write(`
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8">
          <title>Error</title>
        </head>
        <body style="font-family:Arial;padding:32px;color:#b83232">
          <h1>Error</h1>
          <pre style="white-space:pre-wrap">${message || `HTTP ${response.status}`}</pre>
        </body>
      </html>
    `);
    win.document.close();

    throw new Error(message || `HTTP ${response.status}`);
  }

  const html = await response.text();

  win.document.open();
  win.document.write(html);
  win.document.close();
}

async function refreshAll() {
  if (!state.adminKey) {
    setApiState('أدخل مفتاح الإدارة');
    return;
  }

  setApiState('تحميل');

  const calls = await Promise.allSettled([
    api('/api/v1/admin/summary'),
    api('/api/v1/admin/orders'),
    api('/api/v1/admin/documents?limit=100'),
    api('/api/v1/admin/audit-logs?limit=30'),
    api('/api/v1/admin/alchemy-events?limit=200'),
    api('/api/v1/admin/system/readiness'),
    api('/api/v1/admin/security-events'),
    api('/api/v1/admin/clients/security-posture'),
  ]);

  const valueAt = (index, fallback) =>
    calls[index].status === 'fulfilled' ? calls[index].value : fallback;

  renderSummary(valueAt(0, {}));
  renderOrders(valueAt(1, []));
  renderDocuments(valueAt(2, []));
  renderLogs(valueAt(3, []));
  renderAlchemyEvents(valueAt(4, []));
  renderReadiness(valueAt(5, { warnings: ['Enterprise readiness endpoint is temporarily unavailable.'], metrics: {} }));
  renderSecurity(valueAt(6, { summary: {}, blocked_ips: [], suspicious_ips: [], suspicious_paths: [], request_frequency: [], recent_events: [] }));
  renderCounterparties(valueAt(7, { clients: [] }));

  const failed = calls
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.status === 'rejected');

  if (failed.length) {
    setApiState(`متصل جزئياً: ${failed.length} endpoint يحتاج مراجعة`);
    return;
  }

  setApiState('متصل');
}

async function updateOrderStatus(orderId, status) {
  if (!state.adminKey) {
    setApiState('أدخل مفتاح الإدارة');
    return;
  }

  const note =
    status === 'COMPLETED'
      ? 'Manual dashboard confirmation'
      : 'Manual dashboard rejection';

  await api(`/api/v1/admin/orders/${orderId}/status`, {
    method: 'POST',
    body: JSON.stringify({
      status,
      note,
    }),
  });

  setApiState(status === 'COMPLETED' ? 'تم تحويل الطلب إلى مدفوع' : 'تم رفض الطلب');
  await refreshAll();
}

saveKeyButton.addEventListener('click', async () => {
  state.adminKey = adminKeyInput.value.trim();
  state.clientKey = clientKeyInput.value.trim();

  localStorage.setItem('adminApiKey', state.adminKey);
  localStorage.setItem('clientApiKey', state.clientKey);

  await refreshAll().catch((error) => setApiState(error.message));
});

refreshButton.addEventListener('click', async () => {
  await refreshAll().catch((error) => setApiState(error.message));
});

document.querySelector('#counterpartyResetBtn')?.addEventListener('click', () => {
  resetCounterpartyForm();
});

if (counterpartyForm) {
  resetCounterpartyForm();
  counterpartyForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const clientId = document.querySelector('#counterpartyId').value;
    const payload = counterpartyPayloadFromForm();
    const method = clientId ? 'PATCH' : 'POST';
    const path = clientId
      ? `/api/v1/admin/clients/${clientId}`
      : '/api/v1/admin/clients';

    try {
      const data = await api(path, {
        method,
        body: JSON.stringify(payload),
      });

      if (method === 'POST') {
        resetCounterpartyForm();
        showCounterpartyMessage(
          `Created ${data.name}. API key: ${data.api_key} | OAuth client id: ${data.oauth_client_id}`,
          true,
        );
      } else {
        resetCounterpartyForm();
        showCounterpartyMessage(`Updated ${data.name} successfully.`, true);
      }

      await refreshAll();
    } catch (error) {
      showCounterpartyMessage(error.message, false);
    }
  });
}

if (copyWalletButton) {
  copyWalletButton.addEventListener('click', async () => {
    await copyText(LEDGER_ETHEREUM_WALLET, 'تم نسخ المحفظة');
  });
}

orderForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const formData = new FormData(orderForm);

  const payload = {
    fiat_amount: Number(formData.get('fiat_amount')),
    fiat_currency: formData.get('fiat_currency'),
    crypto_currency: formData.get('crypto_currency'),
    network: formData.get('network'),
    country: formData.get('country') || undefined,
    subdivision: formData.get('subdivision') || undefined,
    redirect_url: formData.get('redirect_url') || undefined,
  };

  createdLink.hidden = true;
  setApiState('إنشاء MoonPay');

  try {
    const data = await api('/api/v1/admin/transactions', {
      method: 'POST',
      headers: {
        'Idempotency-Key': `dash-moonpay-${Date.now()}`,
      },
      body: JSON.stringify(payload),
    });

    const link =
      data.checkout_url ||
      data.payment_url ||
      data.quote?.checkout_url ||
      data.quote?.payment_url ||
      data.quote?.provider_response?.checkoutUrl ||
      data.quote?.provider_response?.url ||
      data.quote?.provider_response?.link;

    createdLink.innerHTML = `
      <div>تم إنشاء الطلب: <strong>${data.external_id || data.transaction_id || data.id}</strong></div>
      ${link ? `<a href="${link}" target="_blank" rel="noopener">فتح رابط MoonPay للدفع</a>` : ''}
    `;

    createdLink.hidden = false;
    setApiState('تم');

    await refreshAll();
  } catch (error) {
    setApiState(error.message);
  }
});

if (directCryptoForm) {
  directCryptoForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!state.adminKey && !state.clientKey) {
      setApiState('أدخل Admin API Key أو Client API Key أولاً');
      return;
    }

    const formData = new FormData(directCryptoForm);
    const amount = Number(formData.get('crypto_amount'));
    const currency = String(formData.get('crypto_currency') || 'USDT').toUpperCase();
    const networkHidden = document.getElementById('directNetworkHidden');
    const network = String(networkHidden ? networkHidden.value : (formData.get('network') || 'ethereum')).toLowerCase();
    const externalId = formData.get('external_id') || `DIRECT-${currency.toUpperCase()}-${Date.now()}`;

    const isTron = network === 'tron';
    const TRON_WALLET = 'TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn';
    const settlementWallet = isTron ? TRON_WALLET : LEDGER_ETHEREUM_WALLET;
    const displayNetwork = isTron ? 'TRON (TRC-20)' : 'Ethereum (ERC-20)';

    // Build API payload — works for both ETH and TRON
    const apiPayload = {
      external_id: externalId,
      network,
      fiat_currency: 'USD',
      crypto_currency: currency,
      crypto_amount: amount,
    };

    directResult.hidden = true;
    setApiState('جاري إنشاء رابط الدفع…');

    // Route: client key → client endpoint; admin key → new admin direct-payment endpoint
    const useClientKey = !!state.clientKey;
    const endpoint = useClientKey
      ? '/api/v1/payments/client/direct-payment'
      : '/api/v1/admin/direct-payment';
    const authHeaders = useClientKey
      ? { 'X-API-Key': state.clientKey }
      : { 'X-Admin-API-Key': state.adminKey };

    try {
      const data = await api(endpoint, {
        method: 'POST',
        headers: {
          ...authHeaders,
          'Idempotency-Key': `dash-direct-${Date.now()}`,
        },
        body: JSON.stringify(apiPayload),
      });

      const paymentPageUrl = data.payment_url || publicPaymentUrl(data);
      const wallet = data.treasury_wallet_address || settlementWallet;
      const qrPayload = [
        'ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT',
        `${currency} ${displayNetwork} Payment`,
        `Amount: ${amount} ${currency}`,
        `Wallet: ${wallet}`,
        `Reference: ${data.external_id || data.id}`,
      ].join('\n');

      directResult.innerHTML = `
        <div class="direct-created">
          <div>
            <strong style="color:${isTron ? '#10b981' : '#7c3aed'};">✅ تم إنشاء رابط دفع ${displayNetwork}</strong>
            <p>المرجع: <code>${data.external_id || data.id}</code></p>
            <p>المبلغ: <strong>${amount} ${currency}</strong></p>
            <p>الشبكة: <strong>${displayNetwork}</strong></p>
            <p class="mono-cell" style="word-break:break-all;background:${isTron ? '#064e3b' : '#1e1b4b'};color:${isTron ? '#d1fae5' : '#ede9fe'};padding:10px;border-radius:6px;">${wallet}</p>
            <p style="color:#f59e0b;font-size:12px;">⚠️ أرسل ${currency} على شبكة ${isTron ? 'TRON TRC-20' : 'Ethereum ERC-20'} فقط</p>
            ${paymentPageUrl ? `<a href="${paymentPageUrl}" target="_blank" rel="noopener" style="display:inline-block;margin-top:8px;padding:8px 16px;background:${isTron ? '#10b981' : '#7c3aed'};color:#fff;border-radius:6px;text-decoration:none;">🔗 فتح رابط الدفع</a>` : ''}
            <button class="small" type="button" onclick="navigator.clipboard.writeText('${wallet}').then(()=>setApiState('تم نسخ العنوان'))" style="background:#6b7280;border-color:#6b7280;color:#fff;margin-top:8px;margin-right:8px;">نسخ العنوان</button>
            ${paymentPageUrl ? `<button class="small" type="button" onclick="navigator.clipboard.writeText('${paymentPageUrl}').then(()=>setApiState('تم نسخ الرابط'))" style="background:#1d4ed8;border-color:#1d4ed8;color:#fff;margin-top:8px;">نسخ الرابط</button>` : ''}
          </div>
          <img class="qr-preview" src="${qrUrl(qrPayload)}" alt="${displayNetwork} QR" style="border:2px solid ${isTron ? '#10b981' : '#7c3aed'};">
        </div>
      `;

      directResult.hidden = false;
      setApiState('تم إنشاء رابط الدفع بنجاح');
      await refreshAll();
    } catch (error) {
      setApiState(error.message);
      directResult.hidden = false;
      directResult.innerHTML = `<p style="color:#b83232;font-weight:700;">❌ ${error.message}</p>`;
    }
  });
}

// ── Circle USDC Payment Form ──────────────────────────────────────────────
const circleForm = document.querySelector('#circleForm');
const circleResult = document.querySelector('#circleResult');

if (circleForm && circleResult) {
  circleForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!state.adminKey && !state.clientKey) {
      setApiState('أدخل Admin API Key أو Client API Key أولاً');
      return;
    }

    const formData = new FormData(circleForm);
    const amount = Number(formData.get('fiat_amount'));
    const network = String(formData.get('network') || 'ethereum').toLowerCase();
    const externalId = formData.get('external_id') || `CIRCLE-${Date.now()}`;

    const payload = {
      external_id: externalId,
      network,
      fiat_currency: 'USD',
      crypto_currency: 'USDC',
      fiat_amount: amount,
    };

    circleResult.hidden = true;
    setApiState('جاري إنشاء رابط Circle USDC…');

    const useClientKey = !!state.clientKey;
    const endpoint = useClientKey
      ? '/api/v1/payments/client/circle-payment'
      : '/api/v1/admin/circle-payment';

    try {
      const data = await api(endpoint, {
        method: 'POST',
        headers: { 'Idempotency-Key': `dash-circle-${Date.now()}` },
        body: JSON.stringify(payload),
      });

      const checkoutUrl = data.checkout_url || data.payment_url;
      circleResult.innerHTML = `
        <div>
          <strong style="color:#1652f0;">✅ تم إنشاء رابط Circle USDC</strong>
          <p>المرجع: <code>${data.external_id || data.id}</code></p>
          <p>المبلغ: <strong>${amount} USDC</strong></p>
          <p>الشبكة: <strong>${network.toUpperCase()}</strong></p>
          ${checkoutUrl ? `<a href="${checkoutUrl}" target="_blank" rel="noopener" style="display:inline-block;margin-top:8px;padding:8px 16px;background:#1652f0;color:#fff;border-radius:6px;text-decoration:none;">🔗 فتح صفحة دفع USDC</a>` : ''}
          ${checkoutUrl ? `<button class="small" type="button" onclick="navigator.clipboard.writeText('${checkoutUrl}').then(()=>setApiState('تم نسخ الرابط'))" style="background:#1652f0;border-color:#1652f0;color:#fff;margin-top:8px;margin-right:8px;">نسخ الرابط</button>` : ''}
        </div>
      `;
      circleResult.hidden = false;
      setApiState('تم إنشاء رابط Circle');
      await refreshAll();
    } catch (error) {
      setApiState(error.message);
      circleResult.hidden = false;
      circleResult.innerHTML = `<p style="color:#b83232;font-weight:700;">❌ ${error.message}</p>`;
    }
  });
}

// ── Onramper (Card & Bank Transfer) ─────────────────────────────────
const onramperForm = document.querySelector('#onramperForm');
const onramperResult = document.querySelector('#onramperResult');

if (onramperForm && onramperResult) {
  onramperForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!state.adminKey && !state.clientKey) {
      setApiState('أدخل Admin API Key أو Client API Key أولاً');
      return;
    }

    const formData = new FormData(onramperForm);
    const amount   = Number(formData.get('fiat_amount'));
    const fiat     = String(formData.get('fiat_currency') || 'USD').toUpperCase();
    const crypto   = String(formData.get('crypto') || 'USDC').toUpperCase();
    const network  = String(formData.get('network') || 'ethereum').toLowerCase();
    const extId    = formData.get('external_id') || `ONR-${Date.now()}`;

    const payload = {
      external_id: extId,
      network,
      fiat_currency: fiat,
      fiat_amount: amount,
      crypto,
    };

    onramperResult.hidden = true;
    setApiState('جاري إنشاء رابط Onramper…');

    // Admin only for now (can extend to client later)
    const endpoint = '/api/v1/admin/onramper-payment';

    try {
      const data = await api(endpoint, {
        method: 'POST',
        headers: { 'Idempotency-Key': `dash-onr-${Date.now()}` },
        body: JSON.stringify(payload),
      });

      const checkoutUrl = data.checkout_url || data.payment_url;
      onramperResult.innerHTML = `
        <div>
          <strong style="color:#00c26f;">✅ تم إنشاء رابط Onramper</strong>
          <p>المرجع: <code>${data.external_id || data.id}</code></p>
          <p>المبلغ: <strong>${amount} ${fiat}</strong> ← <strong>${crypto}</strong></p>
          <p>الشبكة: <strong>${network.toUpperCase()}</strong></p>
          <p style="font-size:0.85em;color:#8fa3be;">أرسل هذا الرابط للعميل — يدفع ببطاقة، تحويل بنكي، Apple Pay أو Google Pay.</p>
          ${checkoutUrl ? `<a href="${checkoutUrl}" target="_blank" rel="noopener" style="display:inline-block;margin-top:8px;padding:8px 18px;background:linear-gradient(135deg,#00a85a,#00c26f);color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">🔗 فتح صفحة Onramper</a>` : ''}
          ${checkoutUrl ? `<button class="small" type="button" onclick="navigator.clipboard.writeText('${checkoutUrl.replace(/'/g,"\\'")}').then(()=>setApiState('تم نسخ الرابط ✓'))" style="background:#00a85a;border-color:#00c26f;color:#fff;margin-top:8px;margin-right:8px;">نسخ الرابط</button>` : ''}
        </div>
      `;
      onramperResult.hidden = false;
      setApiState('تم إنشاء رابط Onramper ✓');
      await refreshAll();
    } catch (error) {
      setApiState(error.message);
      onramperResult.hidden = false;
      onramperResult.innerHTML = `<p style="color:#b83232;font-weight:700;">❌ ${error.message}</p>`;
    }
  });
}

if (openReportButton) {
  openReportButton.addEventListener('click', async () => {
    try {
      setApiState('فتح التقرير');
      await openHtmlWindow('/api/v1/admin/reports/transactions', 'Transactions Report');
      setApiState('متصل');
    } catch (error) {
      setApiState(error.message);
    }
  });
}

document.addEventListener('click', async (event) => {
  const copyButton = event.target.closest('[data-copy-link]');

  if (copyButton) {
    await copyText(copyButton.dataset.copyLink, 'تم نسخ رابط العميل');
    return;
  }

  const statusButton = event.target.closest('[data-status-order]');

  if (statusButton) {
    const orderId = statusButton.dataset.statusOrder;
    const status = statusButton.dataset.statusValue;

    const message =
      status === 'COMPLETED'
        ? 'تأكيد تحويل الطلب إلى تم الدفع؟'
        : 'تأكيد تحويل الطلب إلى مرفوض؟';

    if (!window.confirm(message)) {
      return;
    }

    try {
      setApiState('تحديث الحالة');
      await updateOrderStatus(orderId, status);
    } catch (error) {
      setApiState(error.message);
    }

    return;
  }

  const button = event.target.closest('[data-doc-url]');

  if (!button) {
    return;
  }

  try {
    setApiState('فتح المستند');
    await openHtmlWindow(button.dataset.docUrl, 'Payment Document');
    setApiState('متصل');
  } catch (error) {
    setApiState(error.message);
  }
});

refreshMarketTicker();
setInterval(refreshMarketTicker, 60000);

refreshAll().catch(() => setApiState('أدخل المفاتيح'));

// ═══════════════════════════════════════════════════════════════════════════
// SETTLEMENT PAYLOADS DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════

let _currentPayloadId = null;

const STATUS_COLORS = {
  RECEIVED:          '#667085',
  PARSED:            '#1f5fd0',
  AWAITING_TX_HASH:  '#d97706',
  ALCHEMY_PENDING:   '#7c3aed',
  ALCHEMY_VERIFIED:  '#059669',
  ON_CHAIN_CONFIRMED:'#047857',
  RECONCILED:        '#0f766e',
  FAILED:            '#dc2626',
  MANUAL_REVIEW:     '#c2410c',
};

const PRIORITY_COLORS = {
  LOW: '#667085',
  NORMAL: '#1f5fd0',
  HIGH: '#d97706',
  CRITICAL: '#dc2626',
};

function statusBadge(status) {
  const color = STATUS_COLORS[status] || '#667085';
  return `<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:800;background:${color}18;color:${color};border:1px solid ${color}44;">${status || '-'}</span>`;
}

function priorityBadge(priority) {
  const value = String(priority || 'NORMAL').toUpperCase();
  const color = PRIORITY_COLORS[value] || '#667085';
  return `<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:800;background:${color}18;color:${color};border:1px solid ${color}44;">${value}</span>`;
}

function decisionBadge(decision) {
  if (!decision) return '<span style="color:#98a2b3;">-</span>';
  const map = {
    APPROVED: '#059669',
    ON_HOLD: '#d97706',
    REJECTED: '#dc2626',
    RECONCILED: '#0f766e',
    MANUAL_REVIEW: '#b45309',
    NOTED: '#475467',
  };
  const color = map[String(decision).toUpperCase()] || '#667085';
  return `<span style="display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:800;background:${color}18;color:${color};border:1px solid ${color}44;">${decision}</span>`;
}

function shortAddr(addr) {
  if (!addr) return '-';
  if (addr.length > 18) return addr.slice(0, 8) + '…' + addr.slice(-6);
  return addr;
}

function shortHash(hash) {
  if (!hash) return '-';
  if (hash.length > 20) return hash.slice(0, 10) + '…' + hash.slice(-6);
  return hash;
}

async function loadPayloads() {
  const body = document.querySelector('#payloadsBody');
  if (!body) return;

  const filterEl = document.querySelector('#payloadStatusFilter');
  const filter = filterEl ? filterEl.value : '';
  const url = '/api/v1/admin/payloads?limit=50' + (filter ? `&verification_status=${filter}` : '');

  body.innerHTML = '<tr><td colspan="14" style="padding:20px;text-align:center;color:#667085;">Loading…</td></tr>';

  try {
    const resp = await fetch(url, { headers: headers() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const payloads = data.payloads || [];

    if (!payloads.length) {
      body.innerHTML = '<tr><td colspan="14" style="padding:20px;text-align:center;color:#667085;">No payloads found.</td></tr>';
      return;
    }

    body.innerHTML = payloads.map(p => `
      <tr onclick="openPayloadModal('${p.payload_id}')" style="cursor:pointer;transition:background .1s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background=''">
        <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#667085;">${(p.payload_id || '').slice(0,8)}…</td>
        <td style="padding:9px 8px;font-size:12px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${p.transaction_reference || '-'}</td>
        <td style="padding:9px 8px;font-family:monospace;font-size:11px;">${shortAddr(p.sender_wallet)}</td>
        <td style="padding:9px 8px;font-family:monospace;font-size:11px;">${shortAddr(p.receiver_wallet)}</td>
        <td style="padding:9px 8px;font-weight:700;">${formatAmount(p.amount, '', 6)}</td>
        <td style="padding:9px 8px;">${p.asset || '-'}</td>
        <td style="padding:9px 8px;font-size:11px;">${p.network || '-'}</td>
        <td style="padding:9px 8px;font-family:monospace;font-size:11px;">${shortHash(p.tx_hash)}</td>
        <td style="padding:9px 8px;">${statusBadge(p.verification_status)}</td>
        <td style="padding:9px 8px;">${priorityBadge(p.review_priority)}</td>
        <td style="padding:9px 8px;">${decisionBadge(p.review_decision)}</td>
        <td style="padding:9px 8px;font-size:11px;">${p.security_level || '-'}</td>
        <td style="padding:9px 8px;font-size:11px;">${p.client_ip || '-'}</td>
        <td style="padding:9px 8px;font-size:11px;">${p.created_at ? new Date(p.created_at).toLocaleString() : '-'}</td>
      </tr>
    `).join('');

  } catch (err) {
    body.innerHTML = `<tr><td colspan="14" style="padding:20px;text-align:center;color:#b83232;">Error: ${err.message}</td></tr>`;
  }
}

async function openPayloadModal(payloadId) {
  _currentPayloadId = payloadId;
  const modal = document.querySelector('#payloadModal');
  modal.style.display = 'block';

  document.querySelector('#modalPayloadId').textContent = `Payload ID: ${payloadId}`;
  document.querySelector('#modalTxRef').textContent = 'Loading…';
  document.querySelector('#modalSummary').innerHTML = '';
  document.querySelector('#modalRawJson').textContent = 'Loading…';
  document.querySelector('#modalParsedJson').textContent = '';
  document.querySelector('#modalBlockchainJson').textContent = '';
  document.querySelector('#modalHeadersJson').textContent = '';
  document.querySelector('#modalAuditTimeline').innerHTML = '';
  document.querySelector('#modalReviewPriority').value = 'NORMAL';
  document.querySelector('#modalReviewNote').value = '';
  document.querySelector('#modalHoldReason').value = '';
  document.querySelector('#modalError').style.display = 'none';

  switchModalTab('raw');

  try {
    const resp = await fetch(`/api/v1/admin/payloads/${payloadId}`, { headers: headers() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const p = await resp.json();

    document.querySelector('#modalTxRef').textContent = p.transaction_reference || p.payload_id;

    // Summary grid
    const summaryItems = [
      ['Status', statusBadge(p.verification_status)],
      ['Security', `<code style="font-size:11px;">${p.security_level || '-'}</code>`],
      ['Network', p.network || '-'],
      ['Asset', p.asset || '-'],
      ['Amount', formatAmount(p.amount, p.asset, 6)],
      ['Priority', priorityBadge(p.review_priority)],
      ['Decision', decisionBadge(p.review_decision)],
      ['TX Hash', p.tx_hash ? `<a href="${p.explorer_url || '#'}" target="_blank" style="font-size:11px;font-family:monospace;">${shortHash(p.tx_hash)}</a>` : '-'],
      ['Confirmations', p.confirmations != null ? p.confirmations : '-'],
      ['Client IP', p.client_ip || '-'],
    ];

    document.querySelector('#modalSummary').innerHTML = summaryItems.map(([label, val]) =>
      `<div style="background:#f8fafc;border-radius:6px;padding:10px 12px;border:1px solid #e2e8f0;">
        <div style="font-size:11px;color:#667085;margin-bottom:4px;">${label}</div>
        <div style="font-weight:700;font-size:13px;">${val}</div>
      </div>`
    ).join('');

    // Raw JSON
    document.querySelector('#modalRawJson').textContent =
      p.pretty_payload || p.raw_payload || '(empty)';

    // Parsed fields
    document.querySelector('#modalParsedJson').textContent =
      JSON.stringify(p.parsed_payload || {}, null, 2);

    // Blockchain result
    if (p.blockchain_result) {
      document.querySelector('#modalBlockchainJson').textContent =
        JSON.stringify(p.blockchain_result, null, 2);
    } else {
      document.querySelector('#modalBlockchainJson').textContent =
        '(No blockchain verification result yet — click "Verify with Alchemy")';
    }

    // Blockchain info bar
    const bcInfoEl = document.querySelector('#modalBlockchainInfo');
    if (p.explorer_url) {
      bcInfoEl.innerHTML = `<a href="${p.explorer_url}" target="_blank" style="font-size:13px;color:#1f5fd0;font-weight:700;">🔗 View on Explorer</a>`;
    } else {
      bcInfoEl.innerHTML = '';
    }

    // Headers
    document.querySelector('#modalHeadersJson').textContent =
      JSON.stringify(p.headers || {}, null, 2);

    document.querySelector('#modalReviewPriority').value = String(p.review_priority || 'NORMAL').toUpperCase();
    document.querySelector('#modalReviewNote').value = p.review_note || '';
    document.querySelector('#modalHoldReason').value = p.hold_reason || '';

    // Audit timeline
    const audit = [
      { label: 'Received', time: p.created_at, color: '#667085' },
      p.verified_at ? { label: 'Verified', time: p.verified_at, color: '#059669' } : null,
      p.reviewed_at ? {
        label: `Review: ${p.review_decision || 'UPDATED'}`,
        time: p.reviewed_at,
        detail: [p.reviewed_by, p.review_note, p.hold_reason].filter(Boolean).join(' | '),
        color: '#1f5fd0',
      } : null,
      p.error_message ? { label: 'Error', detail: p.error_message, color: '#dc2626' } : null,
    ].filter(Boolean);

    document.querySelector('#modalAuditTimeline').innerHTML = audit.map(item => `
      <div style="display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #e2e8f0;">
        <div style="width:10px;height:10px;border-radius:50%;background:${item.color};margin-top:3px;flex-shrink:0;"></div>
        <div>
          <strong style="color:${item.color};">${item.label}</strong>
          ${item.time ? `<span style="margin-left:12px;color:#667085;font-size:12px;">${new Date(item.time).toLocaleString()}</span>` : ''}
          ${item.detail ? `<div style="font-size:12px;color:#667085;margin-top:4px;">${item.detail}</div>` : ''}
        </div>
      </div>
    `).join('');

  } catch (err) {
    const errEl = document.querySelector('#modalError');
    errEl.textContent = `Failed to load payload: ${err.message}`;
    errEl.style.display = 'block';
  }
}

function closePayloadModal() {
  document.querySelector('#payloadModal').style.display = 'none';
  _currentPayloadId = null;
}

function switchModalTab(tab) {
  document.querySelectorAll('.modal-tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.modal-tab').forEach(btn => {
    const isActive = btn.dataset.tab === tab;
    btn.style.color = isActive ? '#1f5fd0' : '#667085';
    btn.style.borderBottom = isActive ? '2px solid #1f5fd0' : '2px solid transparent';
    btn.style.fontWeight = isActive ? '800' : '400';
  });
  const content = document.querySelector(`#tab-${tab}`);
  if (content) content.style.display = 'block';
}

async function verifyPayload() {
  if (!_currentPayloadId) return;

  const btn = document.querySelector('#verifyBtn');
  const origText = btn.textContent;
  btn.textContent = 'Verifying…';
  btn.disabled = true;

  try {
    const resp = await fetch(`/api/v1/admin/payloads/${_currentPayloadId}/verify`, {
      method: 'POST',
      headers: headers(),
    });
    const data = await resp.json();

    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);

    // Refresh modal
    await openPayloadModal(_currentPayloadId);
    await loadPayloads();

  } catch (err) {
    const errEl = document.querySelector('#modalError');
    errEl.textContent = `Verification failed: ${err.message}`;
    errEl.style.display = 'block';
  } finally {
    btn.textContent = origText;
    btn.disabled = false;
  }
}

async function markManualReview() {
  if (!_currentPayloadId) return;

  const btn = document.querySelector('#manualReviewBtn');
  btn.disabled = true;

  try {
    const resp = await fetch(`/api/v1/admin/payloads/${_currentPayloadId}/mark-manual-review`, {
      method: 'POST',
      headers: headers(),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    await openPayloadModal(_currentPayloadId);
    await loadPayloads();

  } catch (err) {
    const errEl = document.querySelector('#modalError');
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
  }
}

async function reviewPayload(action) {
  if (!_currentPayloadId) return;

  const priority = document.querySelector('#modalReviewPriority')?.value || 'NORMAL';
  const note = document.querySelector('#modalReviewNote')?.value?.trim() || null;
  const holdReason = document.querySelector('#modalHoldReason')?.value?.trim() || null;
  const errEl = document.querySelector('#modalError');
  errEl.style.display = 'none';

  try {
    const resp = await fetch(`/api/v1/admin/payloads/${_currentPayloadId}/review`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        action,
        priority,
        note,
        hold_reason: holdReason,
      }),
    });

    const data = await resp.json();
    if (!resp.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : (data.detail?.message || JSON.stringify(data.detail));
      throw new Error(detail || `HTTP ${resp.status}`);
    }

    await openPayloadModal(_currentPayloadId);
    await loadPayloads();
  } catch (err) {
    errEl.textContent = `Review action failed: ${err.message}`;
    errEl.style.display = 'block';
  }
}

// Close modal on outside click
document.querySelector('#payloadModal').addEventListener('click', function(e) {
  if (e.target === this) closePayloadModal();
});

// Auto-load payloads when section comes into view
const payloadObserver = new IntersectionObserver(entries => {
  if (entries[0].isIntersecting) loadPayloads();
}, { threshold: 0.1 });

const payloadsSection = document.querySelector('#payloads');
if (payloadsSection) payloadObserver.observe(payloadsSection);

document.querySelector('#payloadStatusFilter')?.addEventListener('change', loadPayloads);

// ══════════════════════════════════════════════════════════════════════════════
//  SWIFT TERMINAL — Transaction Lookup & File Management
// ══════════════════════════════════════════════════════════════════════════════

(function () {
  // ── Clock ────────────────────────────────────────────────────────────────
  function swtTick() {
    const el = document.getElementById('swt-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toUTCString().replace('GMT', 'UTC');
  }
  setInterval(swtTick, 1000);
  swtTick();

  // ── Allow Enter key in search ─────────────────────────────────────────────
  document.getElementById('swtInput')?.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') swiftLookup();
  });

  // ── Drop zone for file upload ─────────────────────────────────────────────
  const dropZone = document.getElementById('swt-drop-zone');
  const fileInput = document.getElementById('swt-file-input');
  if (dropZone && fileInput) {
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) swiftDoUpload(file);
    });
    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      if (file) swiftDoUpload(file);
    });
  }
})();

// Current upload target
var _swiftUploadRecordId = '';
var _swiftUploadRef = '';
var _swiftLastResults = [];

// ── Status line helper ────────────────────────────────────────────────────
function swiftStatus(msg, type) {
  const el = document.getElementById('swt-status-text');
  if (el) {
    el.textContent = msg;
    el.className = 'swt-status-' + (type || 'info');
  }
}

// ── Clear ─────────────────────────────────────────────────────────────────
function swiftClear() {
  const inp = document.getElementById('swtInput');
  if (inp) inp.value = '';
  const res = document.getElementById('swt-results');
  if (res) res.innerHTML = '<div class="swt-idle-screen"><pre class="swt-art">  ╔══════════════════════════════════════════════════════════════════╗\n  ║   ALSHUMOOKH GLOBAL  —  SWIFT FINANCIAL MESSAGING TERMINAL      ║\n  ║   Secure Transaction Retrieval & Document Management System     ║\n  ╠══════════════════════════════════════════════════════════════════╣\n  ║                                                                  ║\n  ║   QUERY CLEARED — ENTER A NEW TRANSACTION REFERENCE             ║\n  ║                                                                  ║\n  ╚══════════════════════════════════════════════════════════════════╝</pre></div>';
  swiftStatus('SYSTEM READY — AWAITING QUERY INPUT', 'info');
  _swiftLastResults = [];
}

// ── Main lookup ───────────────────────────────────────────────────────────
async function swiftLookup() {
  const q = (document.getElementById('swtInput')?.value || '').trim();
  if (!q) { swiftStatus('ERROR — QUERY FIELD EMPTY', 'error'); return; }

  swiftStatus('EXECUTING QUERY… SEARCHING ALL RECORDS…', 'loading');
  const res = document.getElementById('swt-results');
  if (res) res.innerHTML = '<div class="swt-loading"><span class="swt-spinner">⟳</span> RETRIEVING TRANSACTION RECORDS…</div>';

  try {
    const data = await api('/api/v1/admin/swift/lookup?q=' + encodeURIComponent(q));
    _swiftLastResults = data.results || [];

    if (!_swiftLastResults.length) {
      swiftStatus('QUERY COMPLETE — NO RECORDS FOUND FOR: ' + q, 'warn');
      if (res) res.innerHTML = '<div class="swt-no-result">⚠ NO TRANSACTION RECORDS FOUND FOR QUERY: <strong>' + q + '</strong><br><small>Verify the reference number and try again.</small></div>';
      return;
    }

    swiftStatus('QUERY COMPLETE — ' + _swiftLastResults.length + ' RECORD(S) RETRIEVED', 'ok');
    if (res) res.innerHTML = _swiftLastResults.map((r, i) => swiftRenderCard(r, i)).join('');

  } catch (err) {
    swiftStatus('SYSTEM ERROR — ' + (err.message || 'UNKNOWN ERROR'), 'error');
    if (res) res.innerHTML = '<div class="swt-no-result">✕ SYSTEM ERROR: ' + (err.message || 'Request failed') + '</div>';
  }
}

// ── Render a single transaction card ─────────────────────────────────────
function swiftRenderCard(r, idx) {
  const isOrder = r.record_type === 'PAYMENT_ORDER';
  const typeLabel = isOrder ? 'MT103 — PAYMENT ORDER' : 'MT202 — SETTLEMENT PAYLOAD';
  const statusClass = { COMPLETED: 'ok', RECONCILED: 'ok', FAILED: 'bad', MANUAL_REVIEW: 'warn' }[r.status] || 'info';

  const fmtVal = (v) => v ? String(v) : '—';
  const fmtDate = (d) => d ? new Date(d).toUTCString() : '—';
  const fmtSize = (b) => b >= 1048576 ? (b/1048576).toFixed(1)+'MB' : b >= 1024 ? (b/1024).toFixed(0)+'KB' : b+'B';

  const fields = isOrder ? [
    ['TRANSACTION UUID', r.id],
    ['PAYMENT REFERENCE', r.reference],
    ['STATUS', r.status],
    ['PROVIDER / NETWORK', (r.provider||'') + ' / ' + (r.network||'')],
    ['FIAT AMOUNT', r.fiat_amount ? r.fiat_amount + ' ' + (r.fiat_currency||'') : '—'],
    ['CRYPTO AMOUNT', r.crypto_amount ? r.crypto_amount + ' ' + (r.crypto_currency||'') : '—'],
    ['SENDER EMAIL', r.sender_email],
    ['SENDER WALLET', r.sender_wallet],
    ['RECEIVER WALLET', r.receiver_wallet],
    ['TX HASH / ON-CHAIN', r.tx_hash],
    ['PROVIDER ORDER ID', r.provider_order_id],
    ['EXTERNAL ID', r.external_id],
    ['CHECKOUT URL', r.checkout_url],
    ['FAILURE REASON', r.failure_reason],
    ['VALUE DATE (CREATED)', fmtDate(r.created_at)],
    ['LAST UPDATED', fmtDate(r.updated_at)],
  ] : [
    ['PAYLOAD UUID', r.id],
    ['TRANSACTION REFERENCE', r.reference],
    ['VERIFICATION STATUS', r.status],
    ['PARSING STATUS', r.parsing_status],
    ['SECURITY LEVEL', r.security_level],
    ['AMOUNT / ASSET', r.amount ? r.amount + ' ' + (r.asset||'') : '—'],
    ['NETWORK', r.network],
    ['SENDER WALLET', r.sender_wallet],
    ['RECEIVER WALLET', r.receiver_wallet],
    ['TX HASH / ON-CHAIN', r.tx_hash],
    ['TOKEN CONTRACT', r.token_contract],
    ['SETTLEMENT TYPE', r.settlement_type],
    ['AUTHORIZATION CODE', r.authorization_code],
    ['BLOCK NUMBER', r.block_number],
    ['CONFIRMATIONS', r.confirmations],
    ['EXPLORER URL', r.explorer_url],
    ['REVIEW PRIORITY', r.review_priority],
    ['REVIEW DECISION', r.review_decision],
    ['REVIEW NOTE', r.review_note],
    ['ERROR MESSAGE', r.error_message],
    ['VALUE DATE (CREATED)', fmtDate(r.created_at)],
  ];

  const fieldRows = fields.map(([k, v]) => {
    if (!v || v === '—' || v === 'null' || v === 'undefined') {
      return '<tr class="swt-row-empty"><td class="swt-field-key">' + k + '</td><td class="swt-field-val empty">—</td></tr>';
    }
    const isUrl = String(v).startsWith('http');
    const display = isUrl ? '<a href="' + v + '" target="_blank" class="swt-link">' + v.substring(0, 60) + (v.length > 60 ? '…' : '') + '</a>' : '<span class="swt-val-text">' + v + '</span>';
    return '<tr class="swt-row"><td class="swt-field-key">' + k + '</td><td class="swt-field-val">' + display + '</td></tr>';
  }).join('');

  // Files section
  const files = r.files || [];
  const fileRows = files.length
    ? files.map(f => `
        <tr class="swt-file-row">
          <td class="swt-file-icon">${swiftFileIcon(f.content_type)}</td>
          <td class="swt-file-name">${f.filename}</td>
          <td class="swt-file-size">${fmtSize(f.file_size)}</td>
          <td class="swt-file-desc">${f.description || '—'}</td>
          <td class="swt-file-date">${f.created_at ? new Date(f.created_at).toLocaleDateString() : '—'}</td>
          <td class="swt-file-actions">
            <button class="swt-btn-dl" onclick="swiftDownload('${f.id}','${f.filename}')">⬇ DL</button>
            <button class="swt-btn-del" onclick="swiftDeleteFile('${f.id}',${idx})">✕</button>
          </td>
        </tr>`).join('')
    : '<tr><td colspan="6" class="swt-no-files">NO DOCUMENTS ATTACHED</td></tr>';

  return `
    <div class="swt-card" id="swt-card-${idx}">
      <div class="swt-card-header">
        <div class="swt-card-type">${typeLabel}</div>
        <div class="swt-card-ref">${fmtVal(r.reference)}</div>
        <div class="swt-card-status swt-status-dot-${statusClass}">${r.status}</div>
      </div>

      <table class="swt-detail-table">
        <tbody>${fieldRows}</tbody>
      </table>

      <div class="swt-docs-section">
        <div class="swt-docs-head">
          <span>📎 ATTACHED DOCUMENTS (${files.length})</span>
          <button class="swt-btn-upload" onclick="swiftOpenUpload('${r.id}','${fmtVal(r.reference)}')">⬆ ATTACH DOCUMENT</button>
        </div>
        <table class="swt-file-table">
          <thead>
            <tr>
              <th></th><th>FILENAME</th><th>SIZE</th><th>DESCRIPTION</th><th>DATE</th><th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>${fileRows}</tbody>
        </table>
      </div>
    </div>`;
}

function swiftFileIcon(ct) {
  if (!ct) return '📄';
  if (ct.includes('pdf')) return '📕';
  if (ct.includes('image')) return '🖼';
  if (ct.includes('excel') || ct.includes('sheet')) return '📊';
  if (ct.includes('word') || ct.includes('document')) return '📝';
  if (ct.includes('csv') || ct.includes('text')) return '📋';
  return '📄';
}

// ── Upload modal ──────────────────────────────────────────────────────────
function swiftOpenUpload(recordId, ref) {
  _swiftUploadRecordId = recordId;
  _swiftUploadRef = ref;
  const label = document.getElementById('swt-upload-ref-label');
  if (label) label.textContent = ref;
  const modal = document.getElementById('swt-upload-modal');
  if (modal) modal.style.display = 'flex';
  const prog = document.getElementById('swt-upload-progress');
  if (prog) prog.style.display = 'none';
  const inp = document.getElementById('swt-file-input');
  if (inp) inp.value = '';
  const desc = document.getElementById('swt-upload-desc');
  if (desc) desc.value = '';
}

function swiftCloseUpload() {
  const modal = document.getElementById('swt-upload-modal');
  if (modal) modal.style.display = 'none';
}

async function swiftDoUpload(file) {
  const prog = document.getElementById('swt-upload-progress');
  const fill = document.getElementById('swt-pfill');
  const msg = document.getElementById('swt-upload-status-msg');
  const desc = (document.getElementById('swt-upload-desc')?.value || '').trim();

  if (prog) prog.style.display = 'block';
  if (fill) fill.style.width = '30%';
  if (msg) msg.textContent = 'UPLOADING: ' + file.name + '…';

  const form = new FormData();
  form.append('file', file);
  form.append('description', desc);
  form.append('transaction_ref', _swiftUploadRef);

  try {
    const resp = await fetch('/api/v1/admin/swift/' + _swiftUploadRecordId + '/files', {
      method: 'POST',
      headers: { 'X-Admin-API-Key': localStorage.getItem('adminApiKey') || '' },
      body: form,
      credentials: 'include',
    });
    if (fill) fill.style.width = '100%';

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      if (msg) msg.textContent = '✕ ERROR: ' + (err.detail || resp.status);
      if (fill) { fill.style.background = '#f87171'; }
      return;
    }

    if (msg) msg.textContent = '✓ DOCUMENT UPLOADED SUCCESSFULLY — ' + file.name;
    if (fill) fill.style.background = '#00ff41';

    // Refresh results after 1s
    setTimeout(() => {
      swiftCloseUpload();
      swiftLookup();
    }, 1200);

  } catch (err) {
    if (msg) msg.textContent = '✕ UPLOAD FAILED: ' + err.message;
    if (fill) fill.style.background = '#f87171';
  }
}

// ── Download file ─────────────────────────────────────────────────────────
function swiftDownload(fileId, filename) {
  const key = localStorage.getItem('adminApiKey') || '';
  const url = '/api/v1/admin/swift/files/' + fileId;
  // Open in new tab with key in header is not possible — use anchor trick
  fetch(url, { headers: { 'X-Admin-API-Key': key }, credentials: 'include' })
    .then(r => r.blob())
    .then(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
    })
    .catch(err => swiftStatus('DOWNLOAD ERROR: ' + err.message, 'error'));
}

// ── Delete file ───────────────────────────────────────────────────────────
async function swiftDeleteFile(fileId, cardIdx) {
  if (!confirm('DELETE THIS DOCUMENT?\nThis action cannot be undone.')) return;
  const key = localStorage.getItem('adminApiKey') || '';
  try {
    const r = await fetch('/api/v1/admin/swift/files/' + fileId, {
      method: 'DELETE',
      headers: { 'X-Admin-API-Key': key },
      credentials: 'include',
    });
    if (!r.ok) throw new Error('Server returned ' + r.status);
    swiftStatus('DOCUMENT DELETED SUCCESSFULLY', 'ok');
    swiftLookup(); // re-query to refresh
  } catch (err) {
    swiftStatus('DELETE ERROR: ' + err.message, 'error');
  }
}
