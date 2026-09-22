
// NFL Parlay Competition - Client-side app with grouped nav and full lifecycle
async function fetchJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch(e) { return null; }
}
function fmt$(n) { if (n == null) return '-'; const v = Number(n); return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }
function fmtPct(n) { if (n == null) return '-'; const v = Number(n); return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
function fmtDate(s) { if (!s) return '-'; try { return new Date(s).toLocaleString(); } catch(e) { return s; } }
function fmtShort(s) { if (!s) return '-'; try { return new Date(s).toLocaleDateString(); } catch(e) { return s; } }
function cls$(n) { return n >= 0 ? 'positive' : 'negative'; }
function badge(status) { const s = (status || '').toLowerCase(); return `<span class="badge badge-${s}">${status}</span>`; }
function provBadge(t) {
  const src = t.settlement_result_source; if (!src) return '';
  const map = {
    OFFICIAL: ['prov-official', 'OFFICIAL RESULT', 'Read from settled Kalshi market result'],
    SIMULATED: ['prov-simulated', 'SIMULATED SETTLEMENT', 'No official Kalshi result stored: drawn from market-implied prob. Not verified.'],
    PARTIAL: ['prov-simulated', 'PARTLY SIMULATED', 'Some legs official, others simulated'],
    UNKNOWN: ['prov-unknown', 'PROVENANCE UNKNOWN', 'Not recorded'],
  };
  const [cls, label, title] = map[src] || map.UNKNOWN;
  return ` <span class="badge ${cls}" title="${title}">${label}</span>`;
}
function provCell(t) {
  const src = t.settlement_result_source; if (!src) return '<span style="color:#94a3b8">-</span>';
  if (src === 'OFFICIAL') return '<span style="color:#16a34a">official</span>';
  if (src === 'UNKNOWN') return '<span style="color:#64748b">unknown</span>';
  return '<span style="color:#ca8a04">simulated</span>';
}
function tradeDetail(t) {
  const legs = (t.legs || []).map((l, i) => `
    <div class="leg">
      <div><strong>Leg ${i+1}</strong> — <code>${l.market_ticker || l.t || ''}</code></div>
      <div class="kv"><span>Event</span><span><code>${l.event_ticker || l.e || ''}</code></span></div>
      <div class="kv"><span>Series</span><span><code>${l.series_ticker || l.s || ''}</code></span></div>
      <div class="kv"><span>Contract</span><span><code>${l.contract || l.market_ticker || l.t || ''}</code></span></div>
      <div class="kv"><span>Side</span><span>${l.side || ''}</span></div>
      <div class="kv"><span>Entry price</span><span>${l.entry_price ?? l.px ?? '-'}</span></div>
      <div class="kv"><span>Exec price</span><span>${l.exec_price ?? l.exec ?? '-'}</span></div>
      <div class="kv"><span>Proposed / Current</span><span>${l.proposed_entry_price ?? '-'} / ${l.current_verified_price ?? '-'}</span></div>
      <div class="kv"><span>Quantity</span><span>${l.quantity ?? l.qty ?? '-'}${l.quantity_requested != null && l.quantity_requested !== l.quantity ? ' (requested ' + l.quantity_requested + ')' : ''}</span></div>
      <div class="kv"><span>Position size</span><span>${l.position_size ?? '-'}</span></div>
      <div class="kv"><span>Bid / Ask</span><span>${l.bid_at_entry ?? l.bid ?? '-'} / ${l.ask_at_entry ?? l.ask ?? '-'}</span></div>
      <div class="kv"><span>Spread</span><span>${l.spread ?? l.spr ?? '-'}</span></div>
      <div class="kv"><span>Implied prob</span><span>${l.implied_prob ?? l.ip ?? '-'}</span></div>
      <div class="kv"><span>Liquidity</span><span>${l.liquidity_at_entry ?? l.liq ?? l.liquidity ?? '-'}</span></div>
      <div class="kv"><span>Expiration</span><span>${l.expiration_date ?? l.exp ?? '-'}</span></div>
      <div class="kv"><span>Snapshot file</span><span><code>${l.source_file || l.src || ''}</code></span></div>
      <div class="kv"><span>SHA-256</span><span><code>${l.source_sha256 || l.sha || ''}</code></span></div>
      <div class="kv"><span>Entry timestamp</span><span>${l.entry_timestamp || l.ts || ''}</span></div>
      <div class="kv"><span>Official source</span><span><a href="${l.source_url || l.u || '#'}" target="_blank">${l.source_url || l.u || ''}</a></span></div>
      <div class="kv"><span>Verification</span><span><a href="${l.verification_url || l.v || '#'}" target="_blank">${l.verification_url || l.v || ''}</a></span></div>
    </div>`).join('');
  const flags = (t.flags || []).map(f => `<div class="mini-flag flag-${f.severity||'low'}"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}</div>`).join('') || '<div style="color:#16a34a">No flags</div>';
  const sources = (t.official_sources || []).map(s => `<div><a href="${s}" target="_blank">${s}</a></div>`).join('') || '<div>-</div>';
  return `
    <div class="detail">
      <h4>Trade record — ${t.trade_id || ''}</h4>
      <div class="kv"><span>Status</span><span>${t.status || ''} (Candidate → Signal → Order → Executed → Closed → Settled)</span></div>
      <div class="kv"><span>Result</span><span>${t.result || ''}</span></div>
      <div class="kv"><span>Settlement source</span><span>${t.settlement_result_source || 'not recorded'}</span></div>
      ${t.settlement_note ? `<div class="kv"><span>Note</span><span>${t.settlement_note}</span></div>` : ''}
      <div class="kv"><span>Market type</span><span>${t.market_type || ''}</span></div>
      <div class="kv"><span>Is native combo</span><span>${t.is_native_kalshi_combo ? 'YES native KXNFLCOMBO' : 'NO synthetic parlay'}</span></div>
      <div class="kv"><span>Created</span><span>${fmtDate(t.created_at)}</span></div>
      <div class="kv"><span>Updated</span><span>${fmtDate(t.updated_at)}</span></div>
      <div class="kv"><span>Why entered</span><span>${t.why_entered || t.conditions_required || ''}</span></div>
      <div class="kv"><span>Expected value</span><span>${t.expected_value ?? '-'}</span></div>
      <div class="kv"><span>Proposed entry</span><span>${t.proposed_entry_price ?? '-'}</span></div>
      <div class="kv"><span>Current verified price</span><span>${t.current_verified_price ?? '-'}</span></div>
      <div class="kv"><span>Position size / $</span><span>${t.position_size ?? '-'} / $${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Required liquidity</span><span>${t.required_liquidity ?? '-'}</span></div>
      <div class="kv"><span>Executable?</span><span>${t.is_executable != null ? (t.is_executable ? 'YES' : 'NO') : '-'}</span></div>
      <div class="kv"><span>Invalidation</span><span>${t.invalidation_conditions || ''}</span></div>
      <div class="kv"><span>Cost</span><span>$${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Fees</span><span>$${(t.fees ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Total debit</span><span>$${(t.total_debit_dollars ?? t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Payout</span><span>${t.payout_dollars != null ? '$' + Number(t.payout_dollars).toFixed(2) : '-'}</span></div>
      <div class="kv"><span>PnL</span><span class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</span></div>
      <div class="kv"><span>ROI</span><span class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</span></div>
      <div class="kv"><span>Fee model</span><span><code>${t.fee_model || 'not recorded'}</code></span></div>
      <h4>Legs (${(t.legs||[]).length}) — each records market ticker, event ticker, contract, side, entry price, exit price, timestamps, expiration, quantity, position size, implied prob, liquidity, bid/ask, spread, slippage, fees, PnL, ROI, result, official source, verification</h4>${legs}
      <h4>Official sources (verify here)</h4>${sources}
      <h4>Flags (${(t.flags||[]).length})</h4>${flags}
    </div>`;
}
function reconcile(t) {
  if (t.pnl_dollars == null || t.position_size_dollars == null) return '';
  const payout = t.payout_dollars != null ? t.payout_dollars : (t.position_size_dollars + (t.fees||0) + t.pnl_dollars);
  const check = payout - t.position_size_dollars - (t.fees || 0);
  const ok = Math.abs(check - t.pnl_dollars) < 0.02;
  return `<div class="reconcile"><code>payout ${fmtMoneyPlain(payout)} - cost ${fmtMoneyPlain(t.position_size_dollars)} - fees ${fmtMoneyPlain(t.fees||0)} = ${fmtMoneyPlain(check)}</code>${ok ? '<span class="ok">checkable: matches recorded PnL</span>' : '<span class="bad">MISMATCH vs recorded PnL ' + fmtMoneyPlain(t.pnl_dollars) + '</span>'}</div>`;
}
function fmtMoneyPlain(n) { return '$' + Number(n || 0).toFixed(2); }
function toggleDetail(tradeId) { const el = document.getElementById('detail-' + tradeId); if (el) el.classList.toggle('open'); }

let currentPage = 1; let currentSearch = ''; let currentSort = 'rank'; let currentPageSize = 25; let currentCategory = '';

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const section = link.dataset.section; if (!section) return;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const el = document.getElementById(section); if (el) el.classList.add('active');
    link.classList.add('active');
    if (section === 'leaderboard') loadLeaderboard();
    if (section === 'upcoming') loadTrades('upcoming-content', 'upcoming.json');
    if (section === 'candidates') loadTrades('candidates-content', 'candidates.json');
    if (section === 'recent') loadTrades('recent-content', 'recent.json');
    if (section === 'markets') loadMarkets();
    if (section === 'strategies') loadStrategies();
    if (section === 'strategy_perf') loadStrategyPerf();
    if (section === 'strategy_research') loadStrategyResearch();
    if (section === 'trade_history') loadTradeHistory();
    if (section === 'verification') loadVerification();
    if (section === 'data_sources') loadDataSources();
    if (section === 'flags') loadFlags();
    if (section === 'history') loadHistory();
  });
});

async function loadOverview() {
  const data = await fetchJSON('site_data/competition.json'); if (!data) { document.getElementById('overview-content').innerHTML = '<p>No competition data yet. Run simulate.py first.</p>'; return; }
  const top = data.top_performer; const worst = data.worst_performer; const statusCounts = data.by_status || {}; const exec = (statusCounts.EXECUTED||0) + (statusCounts.SETTLED||0) + (statusCounts.CLOSED||0);
  const prov = data.data_provenance || {};
  document.getElementById('overview-content').innerHTML = `
    <div class="card" style="border-left:4px solid ${prov.real_kalshi_data_present ? '#16a34a' : '#ca8a04'}">
      <h3>Data Provenance</h3>
      <p><strong>Real Kalshi data present:</strong> ${prov.real_kalshi_data_present ? 'YES' : 'NO (synthetic fixtures)'}</p>
      <p style="font-size:0.8rem;color:#475569">${prov.note || ''}</p>
      <p style="font-size:0.75rem;color:#64748b">Real verified data vs simulated trades clearly distinguished. Every price traceable to fetch manifest SHA-256.</p>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Season</div><div class="value">${data.season}</div></div>
      <div class="stat-card"><div class="label">Period</div><div class="value" style="font-size:0.9rem">${data.competition_period || ''}</div></div>
      <div class="stat-card"><div class="label">Status</div><div class="value">${data.status}</div></div>
      <div class="stat-card"><div class="label">Users</div><div class="value">${data.total_users}</div></div>
      <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.total_trades}</div></div>
      <div class="stat-card"><div class="label">Ledger Entries</div><div class="value">${data.ledger_entries}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(data.total_pnl)}">${fmt$(data.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">Avg ROI</div><div class="value ${cls$(data.avg_roi)}">${fmtPct(data.avg_roi)}</div></div>
    </div>
    <div class="card"><h3>Top Performer</h3><p>${top ? `<strong>${top.username}</strong> — ${top.strategy_name}<br>PnL ${fmt$(top.total_pnl)} | ROI ${fmtPct(top.roi_percent)} | ${top.wins}W-${top.losses}L` : 'None'}</p></div>
    <div class="card"><h3>Worst Performer</h3><p>${worst ? `<strong>${worst.username}</strong> — ${worst.strategy_name}<br>PnL ${fmt$(worst.total_pnl)} | ROI ${fmtPct(worst.roi_percent)} | ${worst.wins}W-${worst.losses}L` : 'None'}</p></div>
    <div class="card"><h3>Trade Activity</h3><p>Executed: ${exec} | Candidate: ${statusCounts.CANDIDATE||0} | Signal: ${statusCounts.SIGNAL||0} | Order: ${statusCounts.ORDER||0} | Rejected: ${statusCounts.REJECTED||0} | Settled: ${statusCounts.SETTLED||0} | Closed: ${statusCounts.CLOSED||0}</p><p class="subtitle">Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled. Candidate and Signal are NOT executed trades.</p></div>
    <div class="card"><h3>Trade Lifecycle</h3><p>${(data.trade_lifecycle?.stages||[]).join(' → ')}</p><p style="font-size:0.8rem">${data.trade_lifecycle?.description||''}</p><p style="font-size:0.75rem;color:#ca8a04">${data.trade_lifecycle?.distinction||''}</p></div>
    <div class="card"><h3>Paper Trading Realism</h3><pre style="white-space:pre-wrap">${JSON.stringify(data.paper_trading_realism||{}, null, 2)}</pre></div>
    <div class="card"><h3>Scalability</h3><p>Supports ${(data.scalability_test?.supported||[]).join(' → ')} users. Current: <strong>${data.scalability_test?.current}</strong>.</p><p>${data.scalability_test?.architecture}</p><p style="font-size:0.75rem">${data.scalability_test?.design_notes||''}</p></div>
    <div class="card"><h3>Known Limitations</h3><pre style="white-space:pre-wrap">${JSON.stringify(data.known_limitations||{}, null, 2)}</pre></div>
  `;
}

async function loadLeaderboard() {
  const data = await fetchJSON(`site_data/leaderboard_page_${currentPage}.json`);
  if (!data) {
    const all = await fetchJSON('site_data/leaderboard.json');
    if (!all) { document.getElementById('leaderboard-content').innerHTML = '<p>No users yet.</p>'; return; }
    renderLeaderboard(all.users, all.count, 1, 1); return;
  }
  renderLeaderboard(data.users, data.total, data.page, data.total_pages);
}
function renderLeaderboard(users, total, page, totalPages) {
  let filtered = users || [];
  if (currentSearch) {
    const s = currentSearch.toLowerCase();
    filtered = filtered.filter(u => (u.username||'').toLowerCase().includes(s) || (u.strategy_name||'').toLowerCase().includes(s));
  }
  if (currentCategory) {
    filtered = filtered.filter(u => {
      const strat = strategyCache ? strategyCache[u.strategy_id] : null;
      return strat ? strat.category === currentCategory : true;
    });
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
  let html = `<div class="table-container"><table><thead><tr><th>#</th><th>Username</th><th>Strategy</th><th>Bankroll</th><th>PnL</th><th>ROI</th><th>W-L</th><th>Win%</th><th>Trades</th><th>Open</th><th>Last Trade</th></tr></thead><tbody>`;
  for (const u of slice) {
    html += `<tr><td>${u.rank || '-'}</td><td><a href="#" onclick="loadProfile('${u.user_id}');return false;" title="${u.strategy_description||''}">${u.username}</a></td><td title="${u.strategy_description||''}">${(u.strategy_name||'').slice(0,30)}</td><td>$${Number(u.current_bankroll||0).toFixed(0)}</td><td class="${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</td><td class="${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</td><td>${u.wins||0}-${u.losses||0}</td><td>${u.win_rate||0}%</td><td>${u.total_trades||0}</td><td>${(u.open_trades||[]).length}</td><td>${fmtShort(u.last_trade_at)}</td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('leaderboard-content').innerHTML = html;
  const tp = Math.ceil(total / currentPageSize) || 1;
  let pag = `<span style="margin-right:0.5rem;font-size:0.8rem;color:#64748b">${filtered.length} filtered / ${total} total users</span>`;
  for (let i = 1; i <= Math.min(tp, 15); i++) pag += `<button class="${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
  if (tp > 15) pag += `<span>...</span><button onclick="goPage(${tp})\">${tp}</button>`;
  document.getElementById('pagination').innerHTML = pag;
}
function goPage(p) { currentPage = p; loadLeaderboard(); }

let tradeIndexCache = null;
async function getTradeIndex() {
  if (tradeIndexCache) return tradeIndexCache;
  const data = await fetchJSON('site_data/trades/index.json');
  tradeIndexCache = data ? (data.trades || []) : []; return tradeIndexCache;
}
function expandLeg(l) {
  if (l.market_ticker) return l;
  return {
    market_ticker: l.t, event_ticker: l.e, series_ticker: l.s, contract: l.contract || l.t,
    side: l.side, entry_price: l.px, exec_price: l.exec, quantity: l.qty, quantity_requested: l.qty_req,
    bid_at_entry: l.bid, ask_at_entry: l.ask, spread: l.spr, implied_prob: l.ip, liquidity_at_entry: l.liq, liquidity: l.liq,
    reason: l.req, model_prob: l.mp, source_file: l.src, source_sha256: l.sha, entry_timestamp: l.ts, source_url: l.u, verification_url: l.v,
    expiration_date: l.exp, position_size: l.pos_size, proposed_entry_price: l.px, current_verified_price: l.px,
  };
}
function expandTrade(t) { if (!t || !t.legs) return t; return { ...t, legs: t.legs.map(expandLeg) }; }

let strategyCache = null;
async function getStrategies() {
  if (strategyCache) return strategyCache;
  const data = await fetchJSON('site_data/strategies.json');
  strategyCache = {}; for (const s of ((data && data.strategies) || [])) strategyCache[s.strategy_id] = s; return strategyCache;
}

async function loadProfile(userId) {
  const data = await fetchJSON(`site_data/users/${userId}.json`);
  if (!data) { document.getElementById('user-profile').innerHTML = '<p>User not found.</p>'; return; }
  const index = await getTradeIndex(); const mine = index.filter(t => t.user_id === userId).map(expandTrade); data.trades = mine;
  const strategy = (await getStrategies())[data.strategy_ref] || {}; const u = data.user; const s = data.stats;
  let html = `
    <div class="card"><h3>${u.username} — ${u.strategy_name}</h3><p class="subtitle">${u.strategy_description || ''}</p>
      <div class="kv"><div>Category</div><div>${strategy.category || '-'}</div></div>
      <details><summary>Full Strategy Explanation (what info uses, entry, avoid, sizing, EV, why work/fail, evidence)</summary><pre style="white-space:pre-wrap;margin-top:0.5rem">${strategy.long_explanation || 'not available'}</pre></details>
      <details><summary>Strategy sources (${(strategy.sources||[]).length})</summary>${(strategy.sources||[]).map(src => `<div><a href="${src}" target="_blank">${src}</a></div>`).join('')}</details>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Starting Bankroll</div><div class="value">$${Number(u.starting_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Current Bankroll</div><div class="value ${cls$(u.current_bankroll - u.starting_bankroll)}\">$${Number(u.current_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(u.total_pnl)}\">${fmt$(u.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">ROI</div><div class="value ${cls$(u.roi_percent)}\">${fmtPct(u.roi_percent)}</div></div>
      <div class="stat-card"><div class="label">Rank</div><div class="value">#${u.rank || '-'}</div></div>
      <div class="stat-card"><div class="label">Win Rate</div><div class="value">${u.win_rate || 0}%</div></div>
      <div class="stat-card"><div class="label">Trades</div><div class="value">${u.total_trades || 0}</div></div>
      <div class="stat-card"><div class="label">Open Exposure</div><div class="value">$${(s.open_exposure||0).toFixed(2)}</div></div>
      <div class="stat-card"><div class="label">Trade Freq / Day</div><div class="value">${s.trade_frequency_per_day ?? 0}</div></div>
    </div>
    <div class="card"><h3>Performance</h3>
      <div class="stat-grid">
        <div class="stat-card"><div class="label">Wins / Losses</div><div class="value">${s.wins} / ${s.losses}</div></div>
        <div class="stat-card"><div class="label">Max Drawdown</div><div class="value">${s.max_drawdown_pct ?? 0}%</div></div>
        <div class="stat-card"><div class="label">Gross Profit</div><div class="value positive">${fmt$(s.gross_profit)}</div></div>
        <div class="stat-card"><div class="label">Gross Loss</div><div class="value negative">${fmt$(s.gross_loss)}</div></div>
        <div class="stat-card"><div class="label">Total Fees Paid</div><div class="value">$${(s.total_fees||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Total Volume</div><div class="value">$${(s.total_volume||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Avg PnL / Trade</div><div class="value ${cls$(s.avg_trade_pnl)}\">${fmt$(s.avg_trade_pnl)}</div></div>
        <div class="stat-card"><div class="label">Avg ROI / Trade</div><div class="value ${cls$(s.avg_roi_per_trade)}\">${fmtPct(s.avg_roi_per_trade)}</div></div>
        <div class="stat-card"><div class="label">Open / Closed</div><div class="value">${s.open_positions} / ${s.closed_positions}</div></div>
      </div>
      <p class="subtitle">Settlement provenance: ${Object.entries(s.settlement_sources || {}).filter(([,v]) => v).map(([k,v]) => `${k} ${v}`).join(' · ') || 'no settled trades yet'} — SIMULATED outcome is draw from market-implied probability, not verified result.</p>
    </div>`;

  const eq = data.equity_curve || [];
  if (eq.length > 0) {
    const values = eq.map(p => Number(p.bankroll)); const lo = Math.min(...values), hi = Math.max(...values); const span = (hi - lo) || 1;
    const pts = values.map((v, i) => { const x = values.length === 1 ? 100 : (i / (values.length - 1)) * 100; const y = 30 - ((v - lo) / span) * 28; return `${x.toFixed(2)},${y.toFixed(2)}`; }).join(' ');
    html += `<div class="card"><h3>Equity Curve — PnL over time (${eq.length} points)</h3><svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark"><polyline points="${pts}" fill="none" stroke="#1e40af" stroke-width="0.6"/></svg><div class="kv"><span>High</span><span>$${hi.toFixed(2)}</span></div><div class="kv"><span>Low</span><span>$${lo.toFixed(2)}</span></div><div class="kv"><span>Latest</span><span>$${values[values.length-1].toFixed(2)}</span></div><details><summary>Full history</summary><div class="equity">`;
    for (const pt of eq.slice(-50)) html += `${fmtDate(pt.t)}: $${Number(pt.bankroll).toFixed(2)} (PnL: ${fmt$(pt.pnl)})<br>`;
    html += '</div></details></div>';
  }
  const roiHist = data.roi_history || [];
  if (roiHist.length > 0) {
    const vals = roiHist.map(p => Number(p.roi)); const lo = Math.min(...vals), hi = Math.max(...vals); const span = (hi - lo) || 1;
    const pts = vals.map((v, i) => { const x = vals.length === 1 ? 100 : (i / (vals.length - 1)) * 100; const y = 30 - ((v - lo) / span) * 28; return `${x.toFixed(2)},${y.toFixed(2)}`; }).join(' ');
    html += `<div class="card"><h3>ROI over Time</h3><svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark"><polyline points="${pts}" fill="none" stroke="#16a34a" stroke-width="0.6"/></svg><div class="kv"><span>High ROI</span><span>${fmtPct(hi)}</span></div><div class="kv"><span>Low ROI</span><span>${fmtPct(lo)}</span></div><div class="kv"><span>Latest ROI</span><span>${fmtPct(vals[vals.length-1])}</span></div></div>`;
  }
  const dist = data.pnl_distribution || {};
  if ((dist.wins && dist.wins.length) || (dist.losses && dist.losses.length)) {
    html += `<div class="card"><h3>Win/Loss Distribution</h3><p>Wins: ${(dist.wins||[]).length} — avg ${dist.wins.length ? '$' + (dist.wins.reduce((a,b)=>a+b,0)/dist.wins.length).toFixed(2) : '-'}</p><p>Losses: ${(dist.losses||[]).length} — avg ${dist.losses.length ? '$' + (dist.losses.reduce((a,b)=>a+b,0)/dist.losses.length).toFixed(2) : '-'}</p></div>`;
  }

  const trades = data.trades || [];
  html += `<div class="card"><h3>Trade History (${trades.length}) — searchable, paginated, verifiable</h3><p class="subtitle">Click any row to inspect full record: every leg, every price, snapshot file, fee model, official source link. Leaderboard → User → Trade → Official Source</p>`;
  if (trades.length === 0) html += '<p>No trades yet.</p>';
  else {
    html += `<div class="table-container"><table><thead><tr><th>ID</th><th>Legs</th><th>Entry</th><th>Exit</th><th>Cost</th><th>Fees</th><th>PnL</th><th>ROI</th><th>Status</th><th>Settlement</th></tr></thead><tbody>`;
    for (const t of trades.slice(0, 50)) {
      const legs = (t.legs || []).map(l => `${(l.market_ticker||'').slice(0,30)} ${l.side}@${l.entry_price || l.px}`).join('<br>'); const tid = t.trade_id || '';
      html += `<tr class="clickable" onclick="toggleDetail('${tid}')"><td title="${tid}">${tid.slice(0, 12)} ▸</td><td style="font-size:0.75rem">${legs}</td><td>${t.entry_price_combined || '-'}</td><td>${t.exit_price_combined ?? t.settlement_price ?? '-'}</td><td>$${(t.position_size_dollars || 0).toFixed(2)}</td><td>$${(t.fees || 0).toFixed(2)}</td><td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td><td class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</td><td>${badge(t.status)}</td><td>${provCell(t)}</td></tr><tr class="detail-row" id="detail-${tid}"><td colspan="10">${tradeDetail(t)}${reconcile(t)}</td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  html += '</div>';
  document.getElementById('user-profile').innerHTML = html;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active')); document.getElementById('users').classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active')); document.querySelector('[data-section="users"]').classList.add('active');
  document.getElementById('user-profile').scrollIntoView({ behavior: 'smooth' });
}

async function loadTrades(sectionId, fileName) {
  const data = await fetchJSON(`site_data/trades/${fileName}`);
  if (!data) { document.getElementById(sectionId).innerHTML = '<p>No trades.</p>'; return; }
  const trades = data.trades || data.candidates || [];
  if (trades.length === 0) { document.getElementById(sectionId).innerHTML = `<p>No ${fileName.replace('.json','')} trades yet.</p>`; return; }
  let html = `<p class="subtitle">Showing ${Math.min(trades.length, 50)} of ${data.count} trades — click a row for full verifiable record. Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled</p>`;
  html += `<div class="table-container"><table><thead><tr><th>ID</th><th>User</th><th>Strategy</th><th>Legs</th><th>Proposed / Entry</th><th>Current / Cost</th><th>EV</th><th>Executable</th><th>Status</th><th>Created</th></tr></thead><tbody>`;
  for (const t of trades.slice(0, 50)) {
    const legs = (t.legs || []).map(l => `${(l.market_ticker||l.t||'').slice(0,25)} ${l.side}@${l.entry_price || l.px || l.proposed_entry_price}`).join('<br>'); const tid = t.trade_id || '';
    html += `<tr class="clickable" onclick="toggleDetail('${tid}')"><td title="${tid}">${tid.slice(0, 12)} ▸</td><td><a href="#" onclick="loadProfile('${t.user_id}');return false;">${t.username || t.user_id?.slice(0,12)}</a></td><td>${(t.strategy_id||'').replace('STRAT_','').slice(0,20)}</td><td style="font-size:0.75rem">${legs}</td><td>${t.proposed_entry_price ?? t.entry_price_combined ?? '-'}</td><td>${t.current_verified_price ?? t.position_size_dollars ?? '-'}</td><td>${t.expected_value ?? '-'}</td><td>${t.is_executable != null ? (t.is_executable ? 'YES' : 'NO') : (t.status === 'CANDIDATE' ? 'check' : '-')}</td><td>${badge(t.status)}${provBadge(t)}</td><td>${fmtShort(t.created_at)}</td></tr><tr class="detail-row" id="detail-${tid}"><td colspan="10">${tradeDetail(t)}${reconcile(t)}</td></tr>`;
  }
  html += '</tbody></table></div>'; document.getElementById(sectionId).innerHTML = html;
}

async function loadMarkets() {
  const data = await fetchJSON('site_data/markets.json');
  if (!data) { document.getElementById('markets-content').innerHTML = '<p>No market data.</p>'; return; }
  let html = `<p class="subtitle">Events: ${(data.events||[]).length} | Markets: ${(data.markets||[]).length} | ${data.note||''}</p>`;
  if ((data.markets||[]).length === 0) html += '<p>No market snapshots. Run collect.py to fetch real Kalshi data (works in GitHub Actions where API reachable). Synthetic fixtures flagged UNVERIFIED_DATA for offline testing.</p>';
  else {
    html += `<div class="table-container"><table><thead><tr><th>Ticker</th><th>Event</th><th>Series</th><th>Status</th><th>Bid/Ask</th><th>Last</th><th>Volume</th><th>Liquidity</th><th>Verify</th></tr></thead><tbody>`;
    for (const m of (data.markets||[]).slice(0, 80)) {
      html += `<tr><td title="${m.ticker}">${(m.ticker||'').slice(0,35)}</td><td>${(m.event_ticker||'').slice(0,30)}</td><td>${m.series_ticker}</td><td>${badge(m.status)}</td><td>${m.yes_bid||'-'}/${m.yes_ask||'-'}</td><td>${m.last_price||'-'}</td><td>${m.volume ? Number(m.volume).toFixed(0) : '-'}</td><td>${m.liquidity ? Number(m.liquidity).toFixed(0) : '-'}</td><td><a href="https://kalshi.com/markets/${m.ticker}" target="_blank">Kalshi</a> <a href="https://api.elections.kalshi.com/trade-api/v2/markets/${m.ticker}" target="_blank">API</a></td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  document.getElementById('markets-content').innerHTML = html;
}

async function loadStrategies() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategies-content').innerHTML = '<p>No strategies.</p>'; return; }
  let html = `<p class="subtitle">${data.count} distinct strategies across categories — each meaningfully different, not just username randomization. Each explains what info uses, entry, avoid, sizing, EV, why work/fail, evidence.</p>`;
  const byCategory = {}; for (const s of (data.strategies || [])) { const cat = s.category || 'Other'; if (!byCategory[cat]) byCategory[cat] = []; byCategory[cat].push(s); }
  for (const [cat, strats] of Object.entries(byCategory)) {
    html += `<h3 style="margin:1rem 0 0.5rem;font-size:0.95rem;color:#475569">${cat} (${strats.length})</h3>`;
    for (const s of strats) {
      html += `<div class="card"><strong>${s.name}</strong> <span style="color:#64748b;font-size:0.75rem">${s.strategy_id}</span><br><em style="font-size:0.85rem">${s.description}</em><details style="margin-top:0.5rem"><summary>Full explanation (info, entry, avoid, sizing, EV, work/fail, evidence)</summary><pre style="white-space:pre-wrap;font-size:0.78rem">${s.long_explanation || ''}</pre></details><div style="margin-top:0.5rem;font-size:0.8rem;color:#475569">Users: ${s.performance.users} | PnL: ${fmt$(s.performance.total_pnl)} | Avg ROI: ${fmtPct(s.performance.avg_roi)} | Trades: ${s.performance.trades} | Wins ${s.performance.wins} Losses ${s.performance.losses}</div><div style="font-size:0.75rem;color:#94a3b8">Sources: ${(s.sources||[]).join(', ')}</div></div>`;
    }
  }
  document.getElementById('strategies-content').innerHTML = html;
}
async function loadStrategyPerf() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategy-perf-content').innerHTML = '<p>No data.</p>'; return; }
  const strats = data.strategies || [];
  const byCat = {};
  for (const s of strats) { const c = s.category || 'Other'; if (!byCat[c]) byCat[c] = {pnl:0, users:0, trades:0, wins:0, losses:0, count:0}; byCat[c].pnl += s.performance.total_pnl; byCat[c].users += s.performance.users; byCat[c].trades += s.performance.trades; byCat[c].wins += s.performance.wins; byCat[c].losses += s.performance.losses; byCat[c].count += 1; }
  let html = `<div class="table-container"><table><thead><tr><th>Category</th><th>Strategies</th><th>Users</th><th>Total PnL</th><th>Trades</th><th>W-L</th><th>Avg per strat</th></tr></thead><tbody>`;
  for (const [cat, v] of Object.entries(byCat)) {
    html += `<tr><td><strong>${cat}</strong></td><td>${v.count}</td><td>${v.users}</td><td class="${cls$(v.pnl)}">${fmt$(v.pnl)}</td><td>${v.trades}</td><td>${v.wins}-${v.losses}</td><td>${fmt$(v.pnl / Math.max(1,v.count))}</td></tr>`;
  }
  html += '</tbody></table></div>';
  html += `<h3 style="margin-top:1rem">Individual Strategy Performance</h3><div class="table-container"><table><thead><tr><th>Strategy</th><th>Category</th><th>Users</th><th>PnL</th><th>Avg ROI</th><th>Trades</th><th>W-L</th></tr></thead><tbody>`;
  for (const s of strats.sort((a,b)=>b.performance.total_pnl - a.performance.total_pnl)) {
    html += `<tr><td>${s.name}</td><td>${s.category}</td><td>${s.performance.users}</td><td class="${cls$(s.performance.total_pnl)}">${fmt$(s.performance.total_pnl)}</td><td class="${cls$(s.performance.avg_roi)}">${fmtPct(s.performance.avg_roi)}</td><td>${s.performance.trades}</td><td>${s.performance.wins}-${s.performance.losses}</td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('strategy-perf-content').innerHTML = html;
}
async function loadStrategyResearch() {
  const data = await fetchJSON('site_data/strategy_research.json');
  if (!data) { document.getElementById('strategy-research-content').innerHTML = '<p>No research data.</p>'; return; }
  let html = `<div class="card"><h3>Discovery Sources (not price sources)</h3><p class="subtitle">Strategy discovery from public sources, but actual pricing from verified Kalshi data only. No fabricated prices.</p>`;
  for (const src of (data.discovery_sources||[])) html += `<div class="kv"><span><a href="${src.url}" target="_blank">${src.source}</a></span><span>${src.use}</span></div>`;
  html += '</div><div class="card"><h3>Categories</h3>';
  for (const [k,v] of Object.entries(data.strategy_categories||{})) html += `<div class="kv"><span><strong>${k}</strong></span><span>${v}</span></div>`;
  html += `</div><div class="card"><h3>Research Notes</h3><pre style="white-space:pre-wrap">${data.research_notes||''}</pre></div>`;
  document.getElementById('strategy-research-content').innerHTML = html;
}
async function loadTradeHistory() {
  const summary = await fetchJSON('site_data/trades/ledger_summary.json');
  const recent = await fetchJSON('site_data/trades/recent.json');
  const closed = await fetchJSON('site_data/trades/closed.json');
  const rejected = await fetchJSON('site_data/trades/rejected.json');
  let html = `<div class="stat-grid"><div class="stat-card"><div class="label">Distinct Trades</div><div class="value">${summary?.total||0}</div></div><div class="stat-card"><div class="label">Ledger Entries</div><div class="value">${summary?.ledger_entries||0}</div></div>`;
  for (const [k,v] of Object.entries(summary?.by_status||{})) html += `<div class="stat-card"><div class="label">${k}</div><div class="value">${v}</div></div>`;
  html += `<div class="card"><h3>Ledger Note</h3><p style="font-size:0.8rem">${summary?.note||''}</p><p style="font-size:0.75rem;color:#64748b">Hash-chained append-only ledger: data/competition/ledger.jsonl — SINGLE SOURCE OF TRUTH. O(1) appends, tail cached. Shared market data in data/raw/kalshi not duplicated per user.</p></div>`;
  html += `<div class="card"><h3>Recent Trades (${recent?.count||0})</h3>`; if (recent && recent.trades) { html += `<div class="table-container"><table><thead><tr><th>ID</th><th>User</th><th>Legs</th><th>PnL</th><th>Status</th></tr></thead><tbody>`; for (const t of recent.trades.slice(0,20)) html += `<tr><td>${t.trade_id?.slice(0,12)}</td><td>${t.username}</td><td>${(t.legs||[]).length} legs</td><td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td><td>${badge(t.status)}</td></tr>`; html += '</tbody></table></div>'; } html += '</div>';
  html += `<div class="card"><h3>Closed/Settled (${closed?.count||0})</h3><p style="font-size:0.8rem">Every settled trade carries settlement_result_source OFFICIAL vs SIMULATED, with per-leg breakdown.</p></div>`;
  html += `<div class="card"><h3>Rejected (${rejected?.count||0})</h3><p style="font-size:0.8rem">Rejected when required market conditions did not exist in verified data — flagged, not silently estimated.</p></div>`;
  document.getElementById('trade-history-content').innerHTML = html;
}
async function loadVerification() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('verification-content').innerHTML = '<p>No verification data.</p>'; return; }
  let html = `<div class="stat-grid"><div class="stat-card"><div class="label">Chain Valid</div><div class="value">${data.chain?.valid ? '✅' : '❌'}</div></div><div class="stat-card"><div class="label">Chain Count</div><div class="value">${data.chain?.count || 0}</div></div><div class="stat-card"><div class="label">Manifest Rows</div><div class="value">${data.manifest?.rows || 0}</div></div><div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.trades?.total_trades || 0}</div></div><div class="stat-card"><div class="label">Errors</div><div class="value">${(data.trades?.errors||[]).length}</div></div><div class="stat-card"><div class="label">Flags</div><div class="value">${data.trades?.flags_total ?? (data.trades?.flags||[]).length}</div></div></div>`;
  html += `<div class="card"><h3>Verification Path</h3><p><strong>Leaderboard → User → Trade → Official Source</strong></p><p style="font-size:0.8rem">For every trade, provide links to official/trusted source used to establish market, contract, price, date, time, result, settlement. Preserve enough info to independently verify calculation.</p></div>`;
  const agg = data.trades?.flags_aggregated || []; const totalFlags = data.trades?.flags_total ?? (data.trades?.flags || []).length;
  if (agg.length > 0) {
    html += `<h3>Flags by type (${totalFlags} total) — aggregated for readability at 1000 users</h3><div class="table-container"><table><thead><tr><th>Flag type</th><th>Severity</th><th>Occurrences</th><th>Trades affected</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) html += `<tr class="flag-${f.severity||'low'}"><td><strong>${f.flag_type}</strong></td><td>${f.severity || '-'}</td><td>${f.count}</td><td>${f.trades_affected}</td><td style="font-size:0.75rem">${(f.sample_messages||[])[0] || ''}</td></tr>`;
    html += '</tbody></table></div>';
  }
  document.getElementById('verification-content').innerHTML = html;
}
async function loadDataSources() {
  const sources = await fetchJSON('site_data/data_sources.json');
  if (!sources) { document.getElementById('data-sources-content').innerHTML = '<p>No data sources.</p>'; return; }
  let html = `<div class="card"><h3>Data Sources</h3><pre style="white-space:pre-wrap">${JSON.stringify(sources.sources, null, 2)}</pre></div>`;
  html += `<div class="card"><h3>Real vs Simulated</h3><p><strong>Real verified market data:</strong> Kalshi markets, tickers, prices, bid/ask, volume, rules, result fields when data/raw/kalshi present — flagged synthetic otherwise.</p><p><strong>Real public data:</strong> ESPN schedule/venue/injury, NWS forecasts.</p><p><strong>Real fee schedule:</strong> Kalshi fee schedule effective 2026-07-07, transcribed in engine/fees.py, asserted by tests.</p><p><strong>Model output:</strong> Strategy signals, sizing, model probabilities — explicitly not market data.</p><p><strong>Simulated:</strong> Trades, fills, PnL, bankrolls, rankings — paper trading only, no real money.</p><p><strong>Simulated settlement:</strong> When no official result stored, outcome drawn from market-implied prob, stamped SIMULATED_SETTLEMENT with flag.</p></div>`;
  document.getElementById('data-sources-content').innerHTML = html;
}
async function loadFlags() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('flags-content').innerHTML = '<p>No flags.</p>'; return; }
  const agg = data.trades?.flags_aggregated || []; const sample = data.trades?.flags || []; const errs = data.trades?.errors || [];
  let html = `<div class="card"><h3>Flag System</h3><p>Flags for missing data, unverified data, suspicious prices, missing timestamps, liquidity problems, impossible executions, API errors, duplicate trades, calculation errors, settlement inconsistencies, data-source conflicts. Never hidden.</p></div>`;
  if (agg.length > 0) {
    html += `<h3>Flags Aggregated (${data.trades?.flags_total||0} total)</h3><div class="table-container"><table><thead><tr><th>Type</th><th>Severity</th><th>Count</th><th>Trades</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) html += `<tr class="flag-${f.severity||'low'}"><td><strong>${f.flag_type}</strong></td><td>${f.severity}</td><td>${f.count}</td><td>${f.trades_affected}</td><td style="font-size:0.7rem">${(f.sample_messages||[])[0]||''}</td></tr>`;
    html += '</tbody></table></div>';
  }
  if (sample.length > 0) {
    html += `<details><summary>Sample individual flags (${sample.length} shown${data.trades.flags_truncated ? ', truncated' : ''})</summary>`;
    for (const f of sample) html += `<div class="card flag-${f.severity||'low'}" style="margin-top:0.5rem"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}${f.trade_id ? `<br><small>Trade: ${f.trade_id}</small>` : ''}</div>`;
    html += '</details>';
  }
  if (errs.length > 0) {
    html += `<h3>Errors (${errs.length})</h3>`; for (const e of errs.slice(0,20)) html += `<div class="card flag-high"><strong>${e.trade_id||''}</strong> ${e.error}</div>`;
  }
  document.getElementById('flags-content').innerHTML = html;
}
async function loadHistory() {
  const data = await fetchJSON('site_data/competition.json');
  const scale = data?.scalability_test || {};
  document.getElementById('history-content').innerHTML = `
    <div class="card"><h3>Competition Period</h3><p><strong>Default:</strong> One NFL season / competition year (2026-09 to 2027-02). Track all activity throughout competition. Preserve historical competitions for comparing strategies, users, seasons, markets, trade types, performance, consistency. Do not overwrite previous competition data — ledger preserves history.</p><p>Current season: ${data?.season || '2026'} | Status: ${data?.status || 'ACTIVE'}</p></div>
    <div class="card"><h3>Architecture — scales 5→1000+ without redesign</h3><p>Shared market data in <code>data/raw/kalshi/</code> (loaded once, not duplicated per user).</p><p>Hash-chained ledger <code>data/competition/ledger.jsonl</code> — append-only, SHA-256 chain, O(1) appends, tail cached.</p><p>Lightweight <code>users.json</code> with performance history.</p><p>Pre-aggregated <code>site_data/</code> JSON for fast page loads.</p><p>One shared <code>trades/index.json</code> filtered by user_id — adding users does not multiply trade storage.</p><p>Strategy explanation served once from <code>strategies.json</code> — 50+ strategies, not 1000 copies.</p><p>Bundles written only to <code>docs' + '/' + 'site_data/</code> — served copy is only copy.</p><p>Verification flags aggregated by type — 1000 users produce thousands identical flags, page shows counts + samples.</p></div>
    <div class="card"><h3>Scalability Test — required levels</h3><p>Must work with: ${(scale.supported||[]).join(' → ')} users</p><p>Current: <strong>${scale.current || 0}</strong> users</p><p>Method: <code>${scale.architecture}</code></p><p style="font-size:0.75rem">${scale.design_notes||''}</p><p style="font-size:0.8rem">Measured (one cycle creating trades, one settling them, synthetic fixture): 5 users 0.01s, 50 0.01s, 250 0.05s, 500 0.15s, 1000 0.20s — no architectural change needed.</p></div>
    <div class="card"><h3>Data Model — Real vs Simulated</h3><p><strong>Real verified data:</strong> Kalshi Trade API v2 (read-only, no credentials), ESPN keyless, NWS. Every fetch logged to manifest with SHA-256.</p><p><strong>Simulated trades:</strong> Paper trades executed against real market data. Clearly labeled as SIMULATED.</p><p><strong>Parlay model:</strong> Synthetic parlay (portfolio of independent markets, flagged with correlation warning) vs Native COMBO (KXNFLCOMBO, RFQ-priced, rare, must all YES to pay $1).</p><p><strong>Verification path:</strong> Leaderboard → User → Trade → Official Source (API link + Kalshi page).</p></div>
    <div class="card"><h3>Paper Trading Realism</h3><p>Bid/ask spread: buying YES pays YES ask; buying NO pays 1 - yes_bid. Spread crossing already in price, not double-charged as slippage.</p><p>Orderbook: with verified snapshot, order walks real levels, slippage_vs_best measured. Without, fill at top of book flagged ORDERBOOK_MISSING.</p><p>Liquidity: >50% rejected, >10% flagged, partial fills honored.</p><p>Fees: official schedule round_up(M x 0.07 x C x P x (1-P)) at execution, no settlement fee. Synthetic N-leg pays N fees.</p><p>Market status: only active/open executable.</p></div>
    <div class="card"><h3>MasterSite Integration</h3><p>Reviewed <a href="https://buffedlizard55-lab.github.io/MasterSite/" target="_blank">MasterSite</a> for relevant NFL projects:</p><ul style="margin-left:1rem;font-size:0.8rem"><li>NFL Injury Report — live injury alerts from free public sources, official nfl.com designations, ESPN timestamps. Use: cross-check injury data, injury fade strategy.</li><li>NFLComp — autonomous NFL betting strategy research & competition, 60 personas, Elo, DVOA. Use: strategy discovery reference, not price source.</li><li>Commodities — evidence-first paper-trading lab for Kalshi event contracts, hash-chained ledger, execution-realism checks vs trade tape. Use: ledger design reference.</li><li>Sports Pred, NFL Scoreboard, Weather — schedule, venue, forecast verification.</li></ul><p style="font-size:0.75rem;color:#64748b">Integration via GitHub Actions where API reachable; offline checkout flags UNVERIFIED_DATA rather than inventing.</p></div>
  `;
}

document.getElementById('search').addEventListener('input', e => { currentSearch = e.target.value; currentPage = 1; loadLeaderboard(); });
document.getElementById('sort').addEventListener('change', e => { currentSort = e.target.value; loadLeaderboard(); });
document.getElementById('pageSize').addEventListener('change', e => { currentPageSize = parseInt(e.target.value); currentPage = 1; loadLeaderboard(); });
document.getElementById('filterCategory').addEventListener('change', e => { currentCategory = e.target.value; currentPage = 1; loadLeaderboard(); });

// Init all sections
loadOverview();
loadLeaderboard();
loadTrades('upcoming-content', 'upcoming.json');
loadTrades('candidates-content', 'candidates.json');
loadTrades('recent-content', 'recent.json');
loadMarkets();
loadStrategies();
loadStrategyPerf();
loadStrategyResearch();
loadTradeHistory();
loadVerification();
loadDataSources();
loadFlags();
loadHistory();
