
// NFL Parlay Competition - Client-side app
// Loads site_data JSON bundles, renders leaderboard, trades, profiles, verification

async function fetchJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch(e) { return null; }
}

function fmt$(n) {
  if (n == null) return '-';
  const v = Number(n);
  return (v >= 0 ? '+' : '') + '$' + v.toFixed(2);
}
function fmtPct(n) {
  if (n == null) return '-';
  const v = Number(n);
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}
function fmtDate(s) {
  if (!s) return '-';
  try { return new Date(s).toLocaleString(); } catch(e) { return s; }
}
function fmtShort(s) {
  if (!s) return '-';
  try { return new Date(s).toLocaleDateString(); } catch(e) { return s; }
}
function cls$(n) { return n >= 0 ? 'positive' : 'negative'; }
function badge(status) {
  const s = (status || '').toLowerCase();
  return `<span class="badge badge-${s}">${status}</span>`;
}
// Settlement provenance: never let a simulated outcome look like a real one.
function provBadge(t) {
  const src = t.settlement_result_source;
  if (!src) return '';
  const map = {
    OFFICIAL: ['prov-official', 'OFFICIAL RESULT', 'Read from the settled Kalshi market result field'],
    SIMULATED: ['prov-simulated', 'SIMULATED SETTLEMENT', 'No official Kalshi result was stored: the outcome was drawn from the market-implied probability. Not a verified result.'],
    PARTIAL: ['prov-simulated', 'PARTLY SIMULATED', 'Some legs had official results; others were drawn from market-implied probability'],
    UNKNOWN: ['prov-unknown', 'PROVENANCE UNKNOWN', 'Settlement provenance was not recorded for this trade'],
  };
  const [cls, label, title] = map[src] || map.UNKNOWN;
  return ` <span class="badge ${cls}" title="${title}">${label}</span>`;
}
function provCell(t) {
  const src = t.settlement_result_source;
  if (!src) return '<span style="color:#94a3b8">-</span>';
  if (src === 'OFFICIAL') return '<span style="color:#16a34a">official</span>';
  if (src === 'UNKNOWN') return '<span style="color:#64748b">unknown</span>';
  return '<span style="color:#ca8a04">simulated</span>';
}
// Expandable full record so any trade can be audited field by field.
function tradeDetail(t) {
  const legs = (t.legs || []).map((l, i) => `
    <div class="leg">
      <div><strong>Leg ${i+1}</strong> — <code>${l.market_ticker || ''}</code></div>
      <div class="kv"><span>Event</span><span><code>${l.event_ticker || ''}</code></span></div>
      <div class="kv"><span>Series</span><span><code>${l.series_ticker || ''}</code></span></div>
      <div class="kv"><span>Side</span><span>${l.side || ''}</span></div>
      <div class="kv"><span>Entry price</span><span>${l.entry_price ?? '-'}</span></div>
      <div class="kv"><span>Exec price</span><span>${l.exec_price ?? '-'}</span></div>
      <div class="kv"><span>Quantity</span><span>${l.quantity ?? '-'}${l.quantity_requested != null && l.quantity_requested !== l.quantity ? ` (requested ${l.quantity_requested})` : ''}</span></div>
      <div class="kv"><span>Bid / Ask at entry</span><span>${l.bid_at_entry ?? '-'} / ${l.ask_at_entry ?? '-'}</span></div>
      <div class="kv"><span>Spread</span><span>${l.spread ?? '-'}</span></div>
      <div class="kv"><span>Implied prob</span><span>${l.implied_prob ?? '-'}</span></div>
      <div class="kv"><span>Liquidity at entry</span><span>${l.liquidity_at_entry ?? '-'}</span></div>
      <div class="kv"><span>Snapshot file</span><span><code>${l.source_file || ''}</code></span></div>
      <div class="kv"><span>Snapshot SHA-256</span><span><code>${l.source_sha256 || ''}</code></span></div>
      <div class="kv"><span>Entry timestamp</span><span>${l.entry_timestamp || ''}</span></div>
      <div class="kv"><span>Official source</span><span><a href="${l.source_url||'#'}" target="_blank">${l.source_url || ''}</a></span></div>
    </div>`).join('');
  const flags = (t.flags || []).map(f =>
    `<div class="mini-flag flag-${f.severity||'low'}"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}</div>`
  ).join('') || '<div style="color:#16a34a">No flags on this trade</div>';
  const sources = (t.official_sources || []).map(s =>
    `<div><a href="${s}" target="_blank">${s}</a></div>`).join('') || '<div>-</div>';
  return `
    <div class="detail">
      <h4>Trade record — ${t.trade_id || ''}</h4>
      <div class="kv"><span>Status</span><span>${t.status || ''}</span></div>
      <div class="kv"><span>Result</span><span>${t.result || ''}</span></div>
      <div class="kv"><span>Settlement source</span><span>${t.settlement_result_source || 'not recorded'}</span></div>
      ${t.settlement_note ? `<div class="kv"><span>Note</span><span>${t.settlement_note}</span></div>` : ''}
      <div class="kv"><span>Market type</span><span>${t.market_type || ''}</span></div>
      <div class="kv"><span>Created</span><span>${fmtDate(t.created_at)}</span></div>
      <div class="kv"><span>Updated</span><span>${fmtDate(t.updated_at)}</span></div>
      <div class="kv"><span>Why entered</span><span>${t.why_entered || ''}</span></div>
      <div class="kv"><span>Expected value</span><span>${t.expected_value ?? '-'}</span></div>
      <div class="kv"><span>Cost (price x contracts)</span><span>$${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Fees paid at entry</span><span>$${(t.fees ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Total debit</span><span>$${(t.total_debit_dollars ?? t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Payout at settlement</span><span>${t.payout_dollars != null ? '$' + Number(t.payout_dollars).toFixed(2) : '-'}</span></div>
      <div class="kv"><span>PnL</span><span class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</span></div>
      <div class="kv"><span>ROI</span><span class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</span></div>
      <div class="kv"><span>Fee model</span><span><code>${t.fee_model || 'not recorded'}</code></span></div>
      <h4>Legs (${(t.legs||[]).length})</h4>${legs}
      <h4>Official sources (verify here)</h4>${sources}
      <h4>Flags (${(t.flags||[]).length})</h4>${flags}
    </div>`;
}
// Pretty-print the arithmetic a reviewer would check by hand.
function reconcile(t) {
  if (t.pnl_dollars == null || t.position_size_dollars == null) return '';
  const payout = t.payout_dollars != null ? t.payout_dollars : (t.position_size_dollars + (t.fees||0) + t.pnl_dollars);
  const check = payout - t.position_size_dollars - (t.fees || 0);
  const ok = Math.abs(check - t.pnl_dollars) < 0.02;
  return `<div class="reconcile">
    <code>payout ${fmtMoneyPlain(payout)} - cost ${fmtMoneyPlain(t.position_size_dollars)} - fees ${fmtMoneyPlain(t.fees||0)} = ${fmtMoneyPlain(check)}</code>
    ${ok ? '<span class="ok">checkable: matches recorded PnL</span>' : '<span class="bad">MISMATCH vs recorded PnL ' + fmtMoneyPlain(t.pnl_dollars) + '</span>'}
  </div>`;
}
function fmtMoneyPlain(n) { return '$' + Number(n || 0).toFixed(2); }
function toggleDetail(tradeId) {
  const el = document.getElementById('detail-' + tradeId);
  if (el) el.classList.toggle('open');
}

// Navigation
let currentPage = 1;
let currentSearch = '';
let currentSort = 'rank';
let currentPageSize = 25;

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const section = link.dataset.section;
    if (!section) return;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const el = document.getElementById(section);
    if (el) el.classList.add('active');
    link.classList.add('active');
    if (section === 'leaderboard') loadLeaderboard();
  });
});

// Overview
async function loadOverview() {
  const data = await fetchJSON('site_data/competition.json');
  if (!data) { document.getElementById('overview-content').innerHTML = '<p>No competition data yet. Run simulate.py first.</p>'; return; }
  const top = data.top_performer;
  const worst = data.worst_performer;
  const statusCounts = data.by_status || {};
  const exec = (statusCounts.EXECUTED||0) + (statusCounts.SETTLED||0) + (statusCounts.CLOSED||0);

  document.getElementById('overview-content').innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Season</div><div class="value">${data.season}</div></div>
      <div class="stat-card"><div class="label">Status</div><div class="value">${data.status}</div></div>
      <div class="stat-card"><div class="label">Users</div><div class="value">${data.total_users}</div></div>
      <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.total_trades}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(data.total_pnl)}">${fmt$(data.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">Avg ROI</div><div class="value ${cls$(data.avg_roi)}">${fmtPct(data.avg_roi)}</div></div>
    </div>
    <div class="card">
      <h3>Top Performer</h3>
      <p>${top ? `<strong>${top.username}</strong> — ${top.strategy_name}<br>PnL ${fmt$(top.total_pnl)} | ROI ${fmtPct(top.roi_percent)} | ${top.wins}W-${top.losses}L` : 'None'}</p>
    </div>
    <div class="card">
      <h3>Trade Activity</h3>
      <p>Executed: ${exec} | Pending: ${statusCounts.ORDER||0} | Rejected: ${statusCounts.REJECTED||0} | Settled: ${statusCounts.SETTLED||0}</p>
    </div>
    <div class="card">
      <h3>Scalability</h3>
      <p>Supports ${(data.scalability_test?.supported||[]).join(' → ')} users. Current: <strong>${data.scalability_test?.current}</strong>.</p>
      <p>${data.scalability_test?.architecture}</p>
    </div>
  `;
}

// Leaderboard
async function loadLeaderboard() {
  const data = await fetchJSON(`site_data/leaderboard_page_${currentPage}.json`);
  if (!data) {
    const all = await fetchJSON('site_data/leaderboard.json');
    if (!all) { document.getElementById('leaderboard-content').innerHTML = '<p>No users yet.</p>'; return; }
    renderLeaderboard(all.users, all.count, 1, 1);
    return;
  }
  renderLeaderboard(data.users, data.total, data.page, data.total_pages);
}

function renderLeaderboard(users, total, page, totalPages) {
  let filtered = users || [];
  if (currentSearch) {
    const s = currentSearch.toLowerCase();
    filtered = filtered.filter(u =>
      (u.username||'').toLowerCase().includes(s) ||
      (u.strategy_name||'').toLowerCase().includes(s));
  }

  const sortFns = {
    pnl: (a,b) => b.total_pnl - a.total_pnl,
    roi: (a,b) => b.roi_percent - a.roi_percent,
    win_rate: (a,b) => b.win_rate - a.win_rate,
    trades: (a,b) => b.total_trades - a.total_trades,
    bankroll: (a,b) => b.current_bankroll - a.current_bankroll,
    rank: (a,b) => (a.rank||9999) - (b.rank||9999),
  };
  if (sortFns[currentSort]) filtered = [...filtered].sort(sortFns[currentSort]);

  const slice = filtered.slice(0, currentPageSize);
  let html = `<div class="table-container"><table>
    <thead><tr>
      <th>#</th><th>Username</th><th>Strategy</th><th>Bankroll</th>
      <th>PnL</th><th>ROI</th><th>W-L</th><th>Win%</th>
      <th>Trades</th><th>Open</th><th>Last Trade</th>
    </tr></thead><tbody>`;

  for (const u of slice) {
    html += `<tr>
      <td>${u.rank || '-'}</td>
      <td><a href="#" onclick="loadProfile('${u.user_id}');return false;" title="${u.strategy_description||''}">${u.username}</a></td>
      <td title="${u.strategy_description||''}">${(u.strategy_name||'').slice(0,30)}</td>
      <td>$${Number(u.current_bankroll||0).toFixed(0)}</td>
      <td class="${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</td>
      <td class="${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</td>
      <td>${u.wins||0}-${u.losses||0}</td>
      <td>${u.win_rate||0}%</td>
      <td>${u.total_trades||0}</td>
      <td>${(u.open_trades||[]).length}</td>
      <td>${fmtShort(u.last_trade_at)}</td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('leaderboard-content').innerHTML = html;

  // Pagination
  const tp = Math.ceil(total / currentPageSize) || 1;
  let pag = `<span style="margin-right:0.5rem;font-size:0.8rem;color:#64748b">${total} users</span>`;
  for (let i = 1; i <= Math.min(tp, 15); i++) {
    pag += `<button class="${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
  }
  if (tp > 15) pag += `<span>...</span><button onclick="goPage(${tp})">${tp}</button>`;
  document.getElementById('pagination').innerHTML = pag;
}

function goPage(p) { currentPage = p; loadLeaderboard(); }

// User Profile — the profile summary is per-user, but trade bodies come from the
// single shared index, filtered client-side by user_id.
let tradeIndexCache = null;
async function getTradeIndex() {
  if (tradeIndexCache) return tradeIndexCache;
  const data = await fetchJSON('site_data/trades/index.json');
  tradeIndexCache = data ? (data.trades || []) : [];
  return tradeIndexCache;
}
// Expand the compact leg keys back to readable names for display.
function expandLeg(l) {
  if (l.market_ticker) return l;   // already a full record
  return {
    market_ticker: l.t, event_ticker: l.e, series_ticker: l.s,
    side: l.side, entry_price: l.px, exec_price: l.exec,
    quantity: l.qty, quantity_requested: l.qty_req,
    bid_at_entry: l.bid, ask_at_entry: l.ask, spread: l.spr,
    implied_prob: l.ip, liquidity_at_entry: l.liq,
    reason: l.req, model_prob: l.mp, source_file: l.src, source_sha256: l.sha,
    entry_timestamp: l.ts, source_url: l.u, verification_url: l.v,
  };
}
function expandTrade(t) {
  if (!t || !t.legs) return t;
  return { ...t, legs: t.legs.map(expandLeg) };
}

let strategyCache = null;
async function getStrategies() {
  if (strategyCache) return strategyCache;
  const data = await fetchJSON('site_data/strategies.json');
  strategyCache = {};
  for (const s of ((data && data.strategies) || [])) strategyCache[s.strategy_id] = s;
  return strategyCache;
}

async function loadProfile(userId) {
  const data = await fetchJSON(`site_data/users/${userId}.json`);
  if (!data) { document.getElementById('user-profile').innerHTML = '<p>User not found.</p>'; return; }
  const index = await getTradeIndex();
  const mine = index.filter(t => t.user_id === userId).map(expandTrade);
  data.trades = mine;
  // Strategy text is served once from the strategy library, not per user.
  const strategy = (await getStrategies())[data.strategy_ref] || {};
  const u = data.user;
  const s = data.stats;

  let html = `
    <div class="card">
      <h3>${u.username} — ${u.strategy_name}</h3>
      <p class="subtitle">${u.strategy_description || ''}</p>
      <div class="kv"><div>Category</div><div>${strategy.category || '-'}</div></div>
      <details><summary>Full Strategy Explanation</summary>
        <pre style="white-space:pre-wrap;margin-top:0.5rem">${strategy.long_explanation || 'not available'}</pre>
      </details>
      <details><summary>Strategy sources (${(strategy.sources||[]).length})</summary>
        ${(strategy.sources||[]).map(src => `<div><a href="${src}" target="_blank">${src}</a></div>`).join('')}
      </details>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Starting Bankroll</div><div class="value">$${Number(u.starting_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Current Bankroll</div><div class="value ${cls$(u.current_bankroll - u.starting_bankroll)}">$${Number(u.current_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">ROI</div><div class="value ${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</div></div>
      <div class="stat-card"><div class="label">Rank</div><div class="value">#${u.rank || '-'}</div></div>
      <div class="stat-card"><div class="label">Win Rate</div><div class="value">${u.win_rate || 0}%</div></div>
      <div class="stat-card"><div class="label">Trades</div><div class="value">${u.total_trades || 0}</div></div>
      <div class="stat-card"><div class="label">Open Exposure</div><div class="value">$${(s.open_exposure||0).toFixed(2)}</div></div>
    </div>
    <div class="card"><h3>Performance</h3>
      <div class="stat-grid">
        <div class="stat-card"><div class="label">Wins / Losses</div><div class="value">${s.wins} / ${s.losses}</div></div>
        <div class="stat-card"><div class="label">Max Drawdown</div><div class="value">${s.max_drawdown_pct ?? 0}%</div></div>
        <div class="stat-card"><div class="label">Gross Profit</div><div class="value positive">${fmt$(s.gross_profit)}</div></div>
        <div class="stat-card"><div class="label">Gross Loss</div><div class="value negative">${fmt$(s.gross_loss)}</div></div>
        <div class="stat-card"><div class="label">Total Fees Paid</div><div class="value">$${(s.total_fees||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Total Volume</div><div class="value">$${(s.total_volume||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Avg PnL / Trade</div><div class="value ${cls$(s.avg_trade_pnl)}">${fmt$(s.avg_trade_pnl)}</div></div>
        <div class="stat-card"><div class="label">Avg ROI / Trade</div><div class="value ${cls$(s.avg_roi_per_trade)}">${fmtPct(s.avg_roi_per_trade)}</div></div>
        <div class="stat-card"><div class="label">Open / Closed</div><div class="value">${s.open_positions} / ${s.closed_positions}</div></div>
      </div>
      <p class="subtitle">Settlement provenance:
        ${Object.entries(s.settlement_sources || {}).filter(([,v]) => v)
          .map(([k,v]) => `${k} ${v}`).join(' · ') || 'no settled trades yet'}
        — a SIMULATED outcome is a draw from the market-implied probability, not a verified result.</p>
    </div>`;

  // Equity curve: a simple inline sparkline over the stored history.
  const eq = data.equity_curve || [];
  if (eq.length > 0) {
    const values = eq.map(p => Number(p.bankroll));
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = (hi - lo) || 1;
    const pts = values.map((v, i) => {
      const x = values.length === 1 ? 100 : (i / (values.length - 1)) * 100;
      const y = 30 - ((v - lo) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    html += `<div class="card"><h3>Equity Curve (${eq.length} points)</h3>
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark">
        <polyline points="${pts}" fill="none" stroke="#1e40af" stroke-width="0.6"/>
      </svg>
      <div class="kv"><span>High</span><span>$${hi.toFixed(2)}</span></div>
      <div class="kv"><span>Low</span><span>$${lo.toFixed(2)}</span></div>
      <div class="kv"><span>Latest</span><span>$${values[values.length-1].toFixed(2)}</span></div>
      <details><summary>Full history</summary><div class="equity">`;
    for (const pt of eq.slice(-50)) {
      html += `${fmtDate(pt.t)}: $${Number(pt.bankroll).toFixed(2)} (PnL: ${fmt$(pt.pnl)})<br>`;
    }
    html += '</div></details></div>';
  }

  // Trade history with drill-down
  const trades = data.trades || [];
  html += `<div class="card"><h3>Trade History (${trades.length})</h3>
    <p class="subtitle">Click any row to inspect the full record: every leg, every price,
    the snapshot file, the fee model, and the official source link.</p>`;
  if (trades.length === 0) {
    html += '<p>No trades yet.</p>';
  } else {
    html += `<div class="table-container"><table>
      <thead><tr><th>ID</th><th>Legs</th><th>Entry</th><th>Exit</th><th>Cost</th>
      <th>Fees</th><th>PnL</th><th>ROI</th><th>Status</th><th>Settlement</th></tr></thead><tbody>`;
    for (const t of trades.slice(0, 50)) {
      const legs = (t.legs || []).map(l =>
        `${(l.market_ticker||'').slice(0,30)} ${l.side}@${l.entry_price}`
      ).join('<br>');
      const tid = t.trade_id || '';
      html += `<tr class="clickable" onclick="toggleDetail('${tid}')">
        <td title="${tid}">${tid.slice(0, 12)} ▸</td>
        <td style="font-size:0.75rem">${legs}</td>
        <td>${t.entry_price_combined || '-'}</td>
        <td>${t.exit_price_combined ?? t.settlement_price ?? '-'}</td>
        <td>$${(t.position_size_dollars || 0).toFixed(2)}</td>
        <td>$${(t.fees || 0).toFixed(2)}</td>
        <td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td>
        <td class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</td>
        <td>${badge(t.status)}</td>
        <td>${provCell(t)}</td>
      </tr>
      <tr class="detail-row" id="detail-${tid}"><td colspan="10">
        ${tradeDetail(t)}${reconcile(t)}
      </td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  html += '</div>';
  document.getElementById('user-profile').innerHTML = html;
  // Switch to users section
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('users').classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  document.querySelector('[data-section="users"]').classList.add('active');
  document.getElementById('user-profile').scrollIntoView({ behavior: 'smooth' });
}

// Trades (upcoming/recent)
async function loadTrades(sectionId, fileName) {
  const data = await fetchJSON(`site_data/trades/${fileName}`);
  if (!data) { document.getElementById(sectionId).innerHTML = '<p>No trades.</p>'; return; }
  const trades = data.trades || [];
  if (trades.length === 0) {
    document.getElementById(sectionId).innerHTML = `<p>No ${fileName.replace('.json','')} trades yet.</p>`;
    return;
  }
  let html = `<p class="subtitle">Showing ${Math.min(trades.length, 50)} of ${data.count} trades
    — click a row for the full verifiable record</p>`;
  html += `<div class="table-container"><table>
    <thead><tr><th>ID</th><th>User</th><th>Strategy</th><th>Legs</th><th>Entry</th>
    <th>Cost</th><th>Fees</th><th>PnL</th><th>Status</th><th>Created</th></tr></thead><tbody>`;
  for (const t of trades.slice(0, 50)) {
    const legs = (t.legs || []).map(l =>
      `${(l.market_ticker||'').slice(0,25)} ${l.side}@${l.entry_price}`
    ).join('<br>');
    const tid = t.trade_id || '';
    html += `<tr class="clickable" onclick="toggleDetail('${tid}')">
      <td title="${tid}">${tid.slice(0, 12)} ▸</td>
      <td><a href="#" onclick="loadProfile('${t.user_id}');return false;">${t.username}</a></td>
      <td>${(t.strategy_id||'').replace('STRAT_','').slice(0,20)}</td>
      <td style="font-size:0.75rem">${legs}</td>
      <td>${t.entry_price_combined || '-'}</td>
      <td>$${(t.position_size_dollars || 0).toFixed(2)}</td>
      <td>$${(t.fees || 0).toFixed(2)}</td>
      <td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td>
      <td>${badge(t.status)}${provBadge(t)}</td>
      <td>${fmtShort(t.created_at)}</td>
    </tr>
    <tr class="detail-row" id="detail-${tid}"><td colspan="10">
      ${tradeDetail(t)}${reconcile(t)}
    </td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById(sectionId).innerHTML = html;
}

// Markets
async function loadMarkets() {
  const data = await fetchJSON('site_data/markets.json');
  if (!data) { document.getElementById('markets-content').innerHTML = '<p>No market data.</p>'; return; }
  let html = `<p class="subtitle">Events: ${(data.events||[]).length} | Markets: ${(data.markets||[]).length}</p>`;
  if ((data.markets||[]).length === 0) {
    html += '<p>No market snapshots. Run collect.py to fetch real Kalshi data.</p>';
  } else {
    html += `<div class="table-container"><table>
      <thead><tr><th>Ticker</th><th>Event</th><th>Series</th><th>Status</th>
      <th>Bid/Ask</th><th>Last</th><th>Volume</th><th>Verify</th></tr></thead><tbody>`;
    for (const m of (data.markets||[]).slice(0, 80)) {
      html += `<tr>
        <td title="${m.ticker}">${(m.ticker||'').slice(0,35)}</td>
        <td>${(m.event_ticker||'').slice(0,30)}</td>
        <td>${m.series_ticker}</td>
        <td>${badge(m.status)}</td>
        <td>${m.yes_bid||'-'}/${m.yes_ask||'-'}</td>
        <td>${m.last_price||'-'}</td>
        <td>${m.volume ? Number(m.volume).toFixed(0) : '-'}</td>
        <td><a href="https://kalshi.com/markets/${m.ticker}" target="_blank">Kalshi</a>
            <a href="https://api.elections.kalshi.com/trade-api/v2/markets/${m.ticker}" target="_blank">API</a></td>
      </tr>`;
    }
    html += '</tbody></table></div>';
  }
  document.getElementById('markets-content').innerHTML = html;
}

// Strategies
async function loadStrategies() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategies-content').innerHTML = '<p>No strategies.</p>'; return; }
  let html = `<p class="subtitle">${data.count} distinct strategies across 5 categories</p>`;
  // Group by category
  const byCategory = {};
  for (const s of (data.strategies || [])) {
    const cat = s.category || 'Other';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(s);
  }
  for (const [cat, strats] of Object.entries(byCategory)) {
    html += `<h3 style="margin:1rem 0 0.5rem;font-size:0.95rem;color:#475569">${cat} (${strats.length})</h3>`;
    for (const s of strats) {
      html += `<div class="card">
        <strong>${s.name}</strong> <span style="color:#64748b;font-size:0.75rem">${s.strategy_id}</span><br>
        <em style="font-size:0.85rem">${s.description}</em>
        <details style="margin-top:0.5rem"><summary>Full explanation</summary>
          <pre style="white-space:pre-wrap;font-size:0.78rem">${s.long_explanation || ''}</pre>
        </details>
        <div style="margin-top:0.5rem;font-size:0.8rem;color:#475569">
          Users: ${s.performance.users} | PnL: ${fmt$(s.performance.total_pnl)} | Avg ROI: ${fmtPct(s.performance.avg_roi)} | Trades: ${s.performance.trades}
        </div>
        <div style="font-size:0.75rem;color:#94a3b8">Sources: ${(s.sources||[]).join(', ')}</div>
      </div>`;
    }
  }
  document.getElementById('strategies-content').innerHTML = html;
}

// Verification
async function loadVerification() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('verification-content').innerHTML = '<p>No verification data.</p>'; return; }
  let html = `<div class="stat-grid">
    <div class="stat-card"><div class="label">Chain Valid</div><div class="value">${data.chain?.valid ? '✅' : '❌'}</div></div>
    <div class="stat-card"><div class="label">Chain Count</div><div class="value">${data.chain?.count || 0}</div></div>
    <div class="stat-card"><div class="label">Manifest Rows</div><div class="value">${data.manifest?.rows || 0}</div></div>
    <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.trades?.total_trades || 0}</div></div>
    <div class="stat-card"><div class="label">Errors</div><div class="value">${(data.trades?.errors||[]).length}</div></div>
    <div class="stat-card"><div class="label">Flags</div><div class="value">${(data.trades?.flags||[]).length}</div></div>
  </div>`;

  const agg = data.trades?.flags_aggregated || [];
  const totalFlags = data.trades?.flags_total ?? (data.trades?.flags || []).length;
  if (agg.length > 0) {
    html += `<h3>Flags by type (${totalFlags} total)</h3>
      <p class="subtitle">Aggregated so the page stays readable at 1,000 users. The
      complete per-trade flag list lives in the ledger and in
      data/competition/verification_report.json.</p>
      <div class="table-container"><table>
      <thead><tr><th>Flag type</th><th>Severity</th><th>Occurrences</th>
      <th>Trades affected</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) {
      html += `<tr class="flag-${f.severity||'low'}">
        <td><strong>${f.flag_type}</strong></td>
        <td>${f.severity || '-'}</td>
        <td>${f.count}</td>
        <td>${f.trades_affected}</td>
        <td style="font-size:0.75rem">${(f.sample_messages||[])[0] || ''}</td>
      </tr>`;
    }
    html += '</tbody></table></div>';
  }

  const sample = data.trades?.flags || [];
  if (sample.length > 0) {
    html += `<details><summary>Sample of individual flags (${sample.length} shown${data.trades.flags_truncated ? ', truncated' : ''})</summary>`;
    for (const f of sample) {
      html += `<div class="card flag-${f.severity||'low'}" style="margin-top:0.5rem">
        <strong>${f.flag_type}</strong> [${f.severity}] ${f.message}
        ${f.trade_id ? `<br><small>Trade: ${f.trade_id}</small>` : ''}
      </div>`;
    }
    html += '</details>';
  }

  const errs = data.trades?.errors || [];
  if (errs.length > 0) {
    html += `<h3>Errors (${errs.length})</h3>`;
    for (const e of errs.slice(0, 20)) {
      html += `<div class="card flag-high"><strong>${e.trade_id || ''}</strong> ${e.error}</div>`;
    }
  }
  document.getElementById('verification-content').innerHTML = html;

  const sources = await fetchJSON('site_data/data_sources.json');
  if (sources) {
    let shtml = '<div class="card"><h3>Data Sources</h3><pre style="white-space:pre-wrap">';
    shtml += JSON.stringify(sources.sources, null, 2);
    shtml += '</pre></div>';
    document.getElementById('data-sources-content').innerHTML = shtml;
  }
}

// History
async function loadHistory() {
  const data = await fetchJSON('site_data/competition.json');
  const scale = data?.scalability_test || {};
  document.getElementById('history-content').innerHTML = `
    <div class="card">
      <h3>Architecture</h3>
      <p>Shared market data in <code>data/raw/kalshi/</code> (loaded once, not duplicated per user).</p>
      <p>Hash-chained ledger <code>data/competition/ledger.jsonl</code> — append-only, SHA-256 chain.</p>
      <p>Lightweight <code>users.json</code> with performance history.</p>
      <p>Pre-aggregated <code>site_data/</code> JSON for fast page loads.</p>
    </div>
    <div class="card">
      <h3>Scalability Test</h3>
      <p>Supports: ${(scale.supported||[]).join(' → ')} users</p>
      <p>Current: <strong>${scale.current || 0}</strong> users</p>
      <p>Method: <code>${scale.architecture}</code></p>
    </div>
    <div class="card">
      <h3>Data Model</h3>
      <p><strong>Real verified data:</strong> Kalshi Trade API v2 (read-only, no credentials), ESPN keyless, NWS. Every fetch logged to manifest with SHA-256.</p>
      <p><strong>Simulated trades:</strong> Paper trades executed against real market data. Clearly labeled as SIMULATED.</p>
      <p><strong>Parlay model:</strong> Synthetic parlay (portfolio of independent markets, flagged with correlation warning) vs Native COMBO (KXNFLCOMBO, RFQ-priced).</p>
      <p><strong>Verification path:</strong> Leaderboard → User → Trade → Official Source (API link + Kalshi page).</p>
    </div>
    <div class="card">
      <h3>Paper Trading Realism</h3>
      <p>Bid/ask spread, liquidity checks (10% depth rule), slippage (bps), fees (7% profit), market status checks, orderbook when available.</p>
    </div>
  `;
}

// Event listeners
document.getElementById('search').addEventListener('input', e => {
  currentSearch = e.target.value; currentPage = 1; loadLeaderboard();
});
document.getElementById('sort').addEventListener('change', e => {
  currentSort = e.target.value; loadLeaderboard();
});
document.getElementById('pageSize').addEventListener('change', e => {
  currentPageSize = parseInt(e.target.value); currentPage = 1; loadLeaderboard();
});

// Init
loadOverview();
loadLeaderboard();
loadTrades('upcoming-content', 'upcoming.json');
loadTrades('recent-content', 'recent.json');
loadMarkets();
loadStrategies();
loadVerification();
loadHistory();
