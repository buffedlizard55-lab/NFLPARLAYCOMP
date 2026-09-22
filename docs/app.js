
async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed ${path}: ${res.status}`);
  return res.json();
}

function fmtMoney(n) {
  if (n==null) return '-';
  return (n>=0?'+':'') + '$' + Number(n).toFixed(2);
}
function fmtPct(n) {
  if (n==null) return '-';
  return (n>=0?'+':'') + Number(n).toFixed(2) + '%';
}

let currentPage = 1;
let currentSearch = '';
let currentSort = 'rank';
let currentPageSize = 25;

async function loadOverview() {
  try {
    const data = await fetchJSON('site_data/competition.json');
    document.getElementById('overview-content').innerHTML = `
      <div class="card">
        <p><strong>Season:</strong> ${data.season} | <strong>Status:</strong> ${data.status} | <strong>Users:</strong> ${data.total_users} | <strong>Total Trades:</strong> ${data.total_trades} | <strong>Total PnL:</strong> ${fmtMoney(data.total_pnl)} | <strong>Avg ROI:</strong> ${fmtPct(data.avg_roi)}</p>
        <p><strong>Scalability:</strong> Supports ${data.scalability_test.supported.join(' → ')} users. Current: ${data.scalability_test.current}. Architecture: ${data.scalability_test.architecture}</p>
        <p><strong>Top:</strong> ${data.top_performer ? data.top_performer.username + ' (' + fmtMoney(data.top_performer.total_pnl) + ')' : 'None'}</p>
        <p><strong>By Status:</strong> ${JSON.stringify(data.by_status)}</p>
      </div>
    `;
  } catch(e) { document.getElementById('overview-content').innerText = 'Error: '+e; }
}

async function loadLeaderboard() {
  try {
    const data = await fetchJSON(`site_data/leaderboard_page_${currentPage}.json`).catch(async () => {
      return await fetchJSON('site_data/leaderboard.json');
    });
    let users = data.users || data;
    // Apply search filter client-side if needed
    if (currentSearch) {
      const s = currentSearch.toLowerCase();
      users = users.filter(u => u.username.toLowerCase().includes(s) || u.strategy_name.toLowerCase().includes(s));
    }
    // Sorting
    if (currentSort==='pnl') users = [...users].sort((a,b)=>b.total_pnl-a.total_pnl);
    if (currentSort==='roi') users = [...users].sort((a,b)=>b.roi_percent-a.roi_percent);
    if (currentSort==='win_rate') users = [...users].sort((a,b)=>b.win_rate-a.win_rate);
    if (currentSort==='trades') users = [...users].sort((a,b)=>b.total_trades-a.total_trades);

    const slice = users.slice(0, currentPageSize);
    let html = `<table><thead><tr><th>Rank</th><th>Username</th><th>Strategy</th><th>Start</th><th>Current</th><th>PnL</th><th>ROI</th><th>W-L</th><th>Win%</th><th>Trades</th><th>Open</th><th>Last</th></tr></thead><tbody>`;
    for (const u of slice) {
      html += `<tr>
        <td>${u.rank||'-'}</td>
        <td><a href="#" onclick="loadUserProfile('${u.user_id}'); return false;">${u.username}</a></td>
        <td title="${u.strategy_description}">${u.strategy_name}</td>
        <td>$${Number(u.starting_bankroll).toFixed(0)}</td>
        <td>$${Number(u.current_bankroll).toFixed(0)}</td>
        <td>${fmtMoney(u.total_pnl)}</td>
        <td>${fmtPct(u.roi_percent)}</td>
        <td>${u.wins}-${u.losses}</td>
        <td>${u.win_rate}%</td>
        <td>${u.total_trades}</td>
        <td>${u.open_trades.length}</td>
        <td>${u.last_trade_at ? new Date(u.last_trade_at).toLocaleDateString() : '-'}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    document.getElementById('leaderboard-content').innerHTML = html;

    // Pagination
    const totalPages = data.total_pages || Math.ceil((data.total||users.length)/currentPageSize);
    let pag = '';
    for (let i=1;i<=Math.min(totalPages,20);i++) {
      pag += `<button class="${i===currentPage?'active':''}" onclick="goPage(${i})">${i}</button>`;
    }
    document.getElementById('pagination').innerHTML = pag;
  } catch(e) { document.getElementById('leaderboard-content').innerText = 'Error: '+e; }
}

function goPage(p) { currentPage=p; loadLeaderboard(); }

async function loadTrades(section, file) {
  try {
    const data = await fetchJSON(`site_data/trades/${file}`);
    const trades = data.trades || [];
    let html = `<p>Total: ${data.count||trades.length}</p><table><thead><tr><th>ID</th><th>User</th><th>Strategy</th><th>Legs</th><th>Price</th><th>Size</th><th>PnL</th><th>ROI</th><th>Status</th><th>Created</th></tr></thead><tbody>`;
    for (const t of trades.slice(0,50)) {
      const legs = (t.legs||[]).map(l=>`${l.market_ticker} ${l.side}@${l.entry_price}`).join('<br>');
      html += `<tr>
        <td><a href="#" onclick="inspectTrade('${t.trade_id}'); return false;">${t.trade_id.slice(0,12)}</a></td>
        <td>${t.username}</td>
        <td>${t.strategy_id}</td>
        <td>${legs}</td>
        <td>${t.entry_price_combined||'-'}</td>
        <td>$${t.position_size_dollars||'-'}</td>
        <td>${t.pnl_dollars!=null?fmtMoney(t.pnl_dollars):'-'}</td>
        <td>${t.roi_percent!=null?fmtPct(t.roi_percent):'-'}</td>
        <td><span class="badge badge-${(t.result||'').toLowerCase()}">${t.status}</span></td>
        <td>${t.created_at ? new Date(t.created_at).toLocaleString() : '-'}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    document.getElementById(section).innerHTML = html;
  } catch(e) { document.getElementById(section).innerText = 'Error: '+e; }
}

async function loadMarkets() {
  try {
    const data = await fetchJSON('site_data/markets.json');
    let html = `<p>Events: ${(data.events||[]).length}, Sample markets: ${(data.markets||[]).length}</p><table><thead><tr><th>Ticker</th><th>Event</th><th>Series</th><th>Status</th><th>Bid/Ask</th><th>Last</th><th>Volume</th><th>Verify</th></tr></thead><tbody>`;
    for (const m of (data.markets||[]).slice(0,50)) {
      html += `<tr>
        <td>${m.ticker}</td>
        <td>${m.event_ticker}</td>
        <td>${m.series_ticker}</td>
        <td>${m.status}</td>
        <td>${m.yes_bid||'-'}/${m.yes_ask||'-'}</td>
        <td>${m.last_price||'-'}</td>
        <td>${m.volume||'-'}</td>
        <td><a href="https://api.elections.kalshi.com/trade-api/v2/markets/${m.ticker}" target="_blank">API</a> <a href="https://kalshi.com/markets/${m.ticker}" target="_blank">Kalshi</a></td>
      </tr>`;
    }
    html += `</tbody></table>`;
    document.getElementById('markets-content').innerHTML = html;
  } catch(e) { document.getElementById('markets-content').innerText = 'Error: '+e; }
}

async function loadStrategies() {
  try {
    const data = await fetchJSON('site_data/strategies.json');
    let html = `<p>Total strategies: ${data.count}</p>`;
    for (const s of (data.strategies||[]).slice(0,100)) {
      html += `<div class="card">
        <strong>${s.name}</strong> (${s.strategy_id}) — ${s.category}<br>
        <em>${s.description}</em><br>
        <small>${s.long_explanation.slice(0,300)}...</small><br>
        <small>Performance: Users ${s.performance.users}, PnL ${fmtMoney(s.performance.total_pnl)}, Avg ROI ${fmtPct(s.performance.avg_roi)}, Trades ${s.performance.trades}</small><br>
        <small>Sources: ${(s.sources||[]).join(', ')}</small>
      </div>`;
    }
    document.getElementById('strategies-content').innerHTML = html;
  } catch(e) { document.getElementById('strategies-content').innerText = 'Error: '+e; }
}

async function loadUserProfile(userId) {
  try {
    const data = await fetchJSON(`site_data/users/${userId}.json`);
    const u = data.user;
    let html = `<div class="card">
      <h3>${u.username} — ${u.strategy_name}</h3>
      <p><strong>Strategy:</strong> ${u.strategy_description}</p>
      <p>${u.strategy_long_explanation.slice(0,800)}</p>
      <p><strong>Bankroll:</strong> Start $${u.starting_bankroll} → Current $${u.current_bankroll} | PnL ${fmtMoney(u.total_pnl)} | ROI ${fmtPct(u.roi_percent)} | Rank #${u.rank}</p>
      <p><strong>Record:</strong> ${u.wins}W-${u.losses}L (${u.win_rate}%) | Trades ${u.total_trades} | Open ${u.open_trades.length}</p>
      <p><strong>Equity Curve:</strong> ${data.equity_curve.length} points, last ${data.equity_curve.slice(-1)[0]?.bankroll||'-'}</p>
      <p><strong>Open Exposure:</strong> $${data.stats.open_exposure}</p>
    </div>`;
    html += `<h4>Trade History (${data.trades.length})</h4><table><thead><tr><th>ID</th><th>Legs</th><th>Entry</th><th>Exit</th><th>PnL</th><th>ROI</th><th>Status</th><th>Why Entered</th><th>Verify</th></tr></thead><tbody>`;
    for (const t of data.trades.slice(0,100)) {
      const legs = (t.legs||[]).map(l=>`${l.market_ticker} ${l.side}@${l.entry_price} (src: ${l.source_file})`).join('<br>');
      const sources = (t.official_sources||[]).map(s=>`<a href="${s}" target="_blank">src</a>`).join(' ');
      html += `<tr>
        <td>${t.trade_id.slice(0,12)}</td>
        <td>${legs}</td>
        <td>${t.entry_price_combined||'-'}</td>
        <td>${t.exit_price_combined||t.settlement_price||'-'}</td>
        <td>${t.pnl_dollars!=null?fmtMoney(t.pnl_dollars):'-'}</td>
        <td>${t.roi_percent!=null?fmtPct(t.roi_percent):'-'}</td>
        <td>${t.status}</td>
        <td>${t.why_entered||''}</td>
        <td>${sources}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    document.getElementById('user-profile').innerHTML = html;
    document.getElementById('user-profile').scrollIntoView();
  } catch(e) { document.getElementById('user-profile').innerText = 'Error: '+e; }
}

async function inspectTrade(tradeId) {
  alert('Trade inspection: open site_data/trades files and search for '+tradeId+' to see full verification chain. Each trade includes source_file SHA and official API URL.');
}

async function loadVerification() {
  try {
    const data = await fetchJSON('site_data/verification.json');
    let html = `<div class="card">
      <p><strong>Valid:</strong> ${data.valid} | <strong>Chain count:</strong> ${data.chain.count} | <strong>Chain valid:</strong> ${data.chain.valid}</p>
      <p><strong>Manifest rows:</strong> ${data.manifest.rows||0} | <strong>Malformed:</strong> ${data.manifest.malformed||0}</p>
      <p><strong>Total trades:</strong> ${data.trades.total_trades} | <strong>Errors:</strong> ${data.trades.errors.length} | <strong>Flags:</strong> ${data.trades.flags.length}</p>
      <p><strong>Users:</strong> ${data.users.count||0}</p>
    </div>`;
    if (data.trades.flags.length) {
      html += `<h4>Flags (${data.trades.flags.length})</h4>`;
      for (const f of data.trades.flags.slice(0,50)) {
        html += `<div class="card flag-${f.severity}"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message} ${f.trade_id||''} ${f.market_ticker||''}</div>`;
      }
    }
    document.getElementById('verification-content').innerHTML = html;

    const sources = await fetchJSON('site_data/data_sources.json');
    let shtml = `<div class="card"><h4>Data Sources</h4><pre>${JSON.stringify(sources.sources, null, 2)}</pre></div>`;
    document.getElementById('data-sources-content').innerHTML = shtml;
  } catch(e) { document.getElementById('verification-content').innerText = 'Error: '+e; }
}

async function loadHistory() {
  document.getElementById('history-content').innerHTML = `
    <div class="card">
      <p>Competition designed for scalability: 5 → 10 → 15 → 25 → 30 → 50 → 70 → 100 → 250 → 500 → 750 → 1000 users</p>
      <p>Architecture: Shared market data in data/raw/kalshi (not duplicated), hash-chained ledger data/competition/ledger.jsonl, lightweight users.json, pre-aggregated site_data JSON for fast pages.</p>
      <p>Real vs Simulated: Real verified market data from Kalshi API (with manifest SHA) vs simulated paper trades. Clearly distinguished in trade records (market_type, is_native_kalshi_combo, source_file, source_sha256, official_sources).</p>
      <p>Parlay Model: Kalshi offers native COMBO markets (KXNFLCOMBO) via RFQ, same-game and cross-game, priced by market makers, not orderbook. Synthetic parlays are simulated portfolios of independent binary markets, flagged as SYNTHETIC_PARLAY with correlation warning. Both tracked.</p>
      <p>Paper Trading Realism: Bid/ask, liquidity, position size vs depth (10% rule), slippage (bps), fees (7% profit), market status checks, orderbook when available.</p>
      <p>Verification Path: Leaderboard → User Profile → Trade → Official Source (API + Kalshi page + source file SHA)</p>
    </div>
  `;
}

document.getElementById('search').addEventListener('input', (e)=>{ currentSearch=e.target.value; loadLeaderboard(); });
document.getElementById('sort').addEventListener('change', (e)=>{ currentSort=e.target.value; loadLeaderboard(); });
document.getElementById('pageSize').addEventListener('change', (e)=>{ currentPageSize=parseInt(e.target.value); loadLeaderboard(); });

loadOverview();
loadLeaderboard();
loadTrades('upcoming-content','upcoming.json');
loadTrades('recent-content','recent.json');
loadMarkets();
loadStrategies();
loadVerification();
loadHistory();
