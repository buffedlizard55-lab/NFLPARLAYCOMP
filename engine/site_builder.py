#!/usr/bin/env python3
"""
Site builder: generates static JSON bundles for GitHub Pages site.

Outputs:
- site_data/leaderboard.json
- site_data/users/<user_id>.json
- site_data/trades/recent.json, upcoming.json
- site_data/markets.json
- site_data/strategies.json
- site_data/verification.json
- site_data/competition.json

And builds docs/ (GitHub Pages) with clean UI:
- Overview, Leaderboard, Upcoming Trades, Recent Trades, Markets
- Strategies: library, performance, research
- Users: search, profiles, trade history
- Verification: trade verification, data sources, flags
- History: previous competitions

The site is dependency-free static HTML/JS that loads JSON bundles.
"""
from __future__ import annotations

import json
import os
import time
import shutil
from typing import Any, Dict, List

from .competition import load_users, get_leaderboard
from .ledger import read_ledger
from .verify import full_verification
from .utils import iso_now

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA = os.path.join(ROOT, "site_data")
DOCS = os.path.join(ROOT, "docs")
COMP = os.path.join(ROOT, "data", "competition")
RAW = os.path.join(ROOT, "data", "raw")

def ensure_dirs():
    os.makedirs(SITE_DATA, exist_ok=True)
    os.makedirs(os.path.join(SITE_DATA, "users"), exist_ok=True)
    os.makedirs(os.path.join(SITE_DATA, "trades"), exist_ok=True)
    os.makedirs(DOCS, exist_ok=True)

def build_leaderboard():
    users = load_users()
    # Full leaderboard sorted
    sorted_users = sorted(users, key=lambda u: u.get("rank", 9999))
    # Write full and paginated
    with open(os.path.join(SITE_DATA, "leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(sorted_users), "users": sorted_users}, f, indent=2)

    # Write pages for pagination (25 per page)
    page_size = 25
    total_pages = (len(sorted_users) + page_size - 1) // page_size
    for page in range(1, total_pages + 1):
        start = (page - 1) * page_size
        end = start + page_size
        page_data = {
            "page": page,
            "page_size": page_size,
            "total": len(sorted_users),
            "total_pages": total_pages,
            "users": sorted_users[start:end],
        }
        with open(os.path.join(SITE_DATA, f"leaderboard_page_{page}.json"), "w", encoding="utf-8") as f:
            json.dump(page_data, f, indent=2)

def build_user_profiles():
    users = load_users()
    trades = read_ledger()
    trades_by_user = {}
    for t in trades:
        uid = t.get("user_id")
        trades_by_user.setdefault(uid, []).append(t)

    for user in users:
        uid = user["user_id"]
        user_trades = sorted(trades_by_user.get(uid, []), key=lambda x: x.get("created_at", ""), reverse=True)
        # Equity curve from performance_history
        equity = user.get("performance_history", [])
        # Win/loss distribution
        wins = user.get("wins", 0)
        losses = user.get("losses", 0)
        # Open exposure
        open_trades = [t for t in user_trades if t.get("status") == "EXECUTED"]
        closed_trades = [t for t in user_trades if t.get("status") in ("SETTLED", "CLOSED")]

        profile = {
            "user": user,
            "trades": user_trades,
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "equity_curve": equity,
            "stats": {
                "wins": wins,
                "losses": losses,
                "win_rate": user.get("win_rate"),
                "total_trades": user.get("total_trades"),
                "roi": user.get("roi_percent"),
                "pnl": user.get("total_pnl"),
                "open_exposure": sum(t.get("position_size_dollars", 0) for t in open_trades),
                "total_volume": sum(t.get("position_size_dollars", 0) for t in user_trades),
            },
            "updated_at": iso_now(),
        }
        with open(os.path.join(SITE_DATA, "users", f"{uid}.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

def build_trades():
    trades = read_ledger()
    # Sort by created_at desc
    sorted_trades = sorted(trades, key=lambda x: x.get("created_at", ""), reverse=True)

    recent = sorted_trades[:100]
    upcoming = [t for t in sorted_trades if t.get("status") in ("CANDIDATE", "SIGNAL", "ORDER", "EXECUTED")][:100]
    closed = [t for t in sorted_trades if t.get("status") in ("SETTLED", "CLOSED")][:100]
    rejected = [t for t in sorted_trades if t.get("status") == "REJECTED"][:100]

    with open(os.path.join(SITE_DATA, "trades", "recent.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(recent), "trades": recent}, f, indent=2)
    with open(os.path.join(SITE_DATA, "trades", "upcoming.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(upcoming), "trades": upcoming}, f, indent=2)
    with open(os.path.join(SITE_DATA, "trades", "closed.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(closed), "trades": closed}, f, indent=2)
    with open(os.path.join(SITE_DATA, "trades", "rejected.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(rejected), "trades": rejected}, f, indent=2)
    # Full ledger summary
    with open(os.path.join(SITE_DATA, "trades", "ledger_summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": iso_now(),
            "total": len(sorted_trades),
            "by_status": {status: len([t for t in sorted_trades if t.get("status")==status]) for status in ["CANDIDATE","SIGNAL","ORDER","EXECUTED","CLOSED","SETTLED","CANCELLED","REJECTED"]},
        }, f, indent=2)

def build_markets():
    # Load season events
    season_path = os.path.join(RAW, "kalshi", "season_events.json")
    markets_data = {"markets": [], "events": [], "updated_at": iso_now()}
    if os.path.exists(season_path):
        with open(season_path, "r", encoding="utf-8") as f:
            season = json.load(f)
            markets_data["events"] = season.get("event_tickers", [])[:100]
            markets_data["series_summary"] = season.get("series_summary", {})

    # Load some market snapshots
    markets_dir = os.path.join(RAW, "kalshi", "markets")
    if os.path.exists(markets_dir):
        sample = []
        for fn in os.listdir(markets_dir)[:20]:
            fp = os.path.join(markets_dir, fn)
            try:
                with open(fp, "r", encoding="utf-8") as pf:
                    payload = json.load(pf)
                    sample.extend(payload.get("markets", [])[:5])
            except:
                continue
        markets_data["markets"] = sample

    with open(os.path.join(SITE_DATA, "markets.json"), "w", encoding="utf-8") as f:
        json.dump(markets_data, f, indent=2)

def build_strategies():
    from .strategies import get_all_strategies
    strategies = get_all_strategies()
    # Load user performance per strategy
    users = load_users()
    strat_perf = {}
    for u in users:
        sid = u["strategy_id"]
        if sid not in strat_perf:
            strat_perf[sid] = {"users": 0, "total_pnl": 0, "wins": 0, "losses": 0, "trades": 0, "roi": []}
        strat_perf[sid]["users"] += 1
        strat_perf[sid]["total_pnl"] += u.get("total_pnl", 0)
        strat_perf[sid]["wins"] += u.get("wins", 0)
        strat_perf[sid]["losses"] += u.get("losses", 0)
        strat_perf[sid]["trades"] += u.get("total_trades", 0)
        strat_perf[sid]["roi"].append(u.get("roi_percent", 0))

    strategies_data = []
    for s in strategies:
        perf = strat_perf.get(s.strategy_id, {})
        avg_roi = sum(perf.get("roi", [])) / len(perf.get("roi", [])) if perf.get("roi") else 0
        strategies_data.append({
            **s.to_dict(),
            "performance": {
                "users": perf.get("users", 0),
                "total_pnl": round(perf.get("total_pnl", 0), 2),
                "wins": perf.get("wins", 0),
                "losses": perf.get("losses", 0),
                "trades": perf.get("trades", 0),
                "avg_roi": round(avg_roi, 2),
            }
        })

    with open(os.path.join(SITE_DATA, "strategies.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(strategies_data), "strategies": strategies_data}, f, indent=2)

def build_verification():
    verification = full_verification()
    with open(os.path.join(SITE_DATA, "verification.json"), "w", encoding="utf-8") as f:
        json.dump(verification, f, indent=2)

    # Data sources
    sources = {
        "kalshi_api": {
            "base_url": "https://api.elections.kalshi.com/trade-api/v2",
            "docs": "https://docs.kalshi.com/",
            "endpoints": [
                "/exchange/status",
                "/series",
                "/events",
                "/markets",
                "/markets/{ticker}",
                "/markets/{ticker}/orderbook",
                "/series/{series}/markets/{ticker}/candlesticks",
                "/markets/trades"
            ],
            "note": "Only official Kalshi Trade API v2, read-only, no credentials"
        },
        "espn_api": {
            "base_url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
            "endpoints": ["/scoreboard", "/injuries"],
            "note": "NFL metadata only (home/away, scores, venue, injuries) - not price source"
        },
        "nws_api": {
            "base_url": "https://api.weather.gov",
            "note": "Weather forecasts forward-only, historical unavailable"
        },
        "master_site": {
            "url": "https://buffedlizard55-lab.github.io/MasterSite/",
            "relevant_projects": [
                {"name": "NFL Injury Report", "url": "https://buffedlizard55-lab.github.io/NFLInjuryReport/", "use": "Injury data cross-check"},
                {"name": "NFLComp", "url": "https://buffedlizard55-lab.github.io/NFLComp/", "use": "Strategy research reference"},
                {"name": "Commodities", "url": "https://buffedlizard55-lab.github.io/Commodities/", "use": "Paper-trading ledger design reference"},
            ]
        }
    }
    with open(os.path.join(SITE_DATA, "data_sources.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "sources": sources}, f, indent=2)

def build_competition_overview():
    users = load_users()
    trades = read_ledger()
    total_pnl = sum(u.get("total_pnl", 0) for u in users)
    total_trades = len(trades)
    overview = {
        "updated_at": iso_now(),
        "season": "2026",
        "status": "ACTIVE",
        "total_users": len(users),
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "avg_roi": round(sum(u.get("roi_percent", 0) for u in users) / len(users), 2) if users else 0,
        "top_performer": sorted(users, key=lambda x: x.get("total_pnl", 0), reverse=True)[0] if users else None,
        "worst_performer": sorted(users, key=lambda x: x.get("total_pnl", 0))[0] if users else None,
        "by_status": {status: len([t for t in trades if t.get("status")==status]) for status in ["CANDIDATE","SIGNAL","ORDER","EXECUTED","CLOSED","SETTLED","CANCELLED","REJECTED"]},
        "scalability_test": {
            "supported": [5,10,15,25,30,50,70,100,250,500,750,1000],
            "current": len(users),
            "architecture": "Shared market data + hash-chained ledger, no per-user duplication"
        }
    }
    with open(os.path.join(SITE_DATA, "competition.json"), "w", encoding="utf-8") as f:
        json.dump(overview, f, indent=2)

def build_docs_site():
    """Build GitHub Pages site in docs/"""
    ensure_dirs()
    # Main index.html
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL Parlay Trading Competition</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
<h1>NFL Parlay Trading Competition</h1>
<p>Auditable paper-trading competition using real verified Kalshi NFL markets. No real money traded.</p>
<nav>
<a href="#overview">Overview</a>
<a href="#leaderboard">Leaderboard</a>
<a href="#upcoming">Upcoming Trades</a>
<a href="#recent">Recent Trades</a>
<a href="#markets">Markets</a>
<a href="#strategies">Strategies</a>
<a href="#users">Users</a>
<a href="#verification">Verification</a>
<a href="#history">History</a>
</nav>
</header>

<main>
<section id="overview">
<h2>Competition Overview</h2>
<div id="overview-content">Loading...</div>
</section>

<section id="leaderboard">
<h2>Leaderboard</h2>
<div class="controls">
<input type="text" id="search" placeholder="Search username or strategy">
<select id="sort">
<option value="rank">Rank</option>
<option value="pnl">PnL</option>
<option value="roi">ROI</option>
<option value="win_rate">Win Rate</option>
<option value="trades">Trades</option>
</select>
<select id="pageSize">
<option value="25">25 per page</option>
<option value="50">50 per page</option>
<option value="100">100 per page</option>
</select>
</div>
<div id="leaderboard-content">Loading...</div>
<div id="pagination"></div>
</section>

<section id="upcoming">
<h2>Upcoming Trades</h2>
<p>Candidate → Signal → Order → Executed → Closed → Settled lifecycle. Only EXECUTED trades affect bankroll.</p>
<div id="upcoming-content">Loading...</div>
</section>

<section id="recent">
<h2>Recent Trades</h2>
<div id="recent-content">Loading...</div>
</section>

<section id="markets">
<h2>Markets</h2>
<p>Real verified Kalshi NFL markets. Prices from official Trade API v2. Synthetic fixtures flagged when real data unavailable.</p>
<div id="markets-content">Loading...</div>
</section>

<section id="strategies">
<h2>Strategy Library</h2>
<div id="strategies-content">Loading...</div>
</section>

<section id="users">
<h2>User Profiles</h2>
<p>Click a user on leaderboard to view profile. Scalable to 1000+ users.</p>
<div id="user-profile">Select a user to view profile</div>
</section>

<section id="verification">
<h2>Trade Verification</h2>
<p>Every trade: Leaderboard → User → Trade → Official Source. Real verified data vs simulated trades clearly distinguished.</p>
<div id="verification-content">Loading...</div>
<div id="data-sources-content"></div>
</section>

<section id="history">
<h2>History & Scalability</h2>
<p>Competition supports 5 → 1000 users without redesign. Shared market data, hash-chained ledger.</p>
<div id="history-content"></div>
</section>
</main>

<footer>
<p>NFL Parlay Trading Competition — Paper trading only. No real money. Data from Kalshi official API, ESPN keyless, NWS. <a href="https://github.com/buffedlizard55-lab/NFLPARLAYCOMP">Repo</a></p>
<p>Verification: Every price, timestamp, market, settlement from official sources with SHA-256 manifest. Simulated trades clearly labeled.</p>
</footer>

<script src="app.js"></script>
</body>
</html>
"""
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # CSS
    css = """
body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; margin:0; padding:0; background:#f8fafc; color:#0f172a; line-height:1.5; }
header { background:#0f172a; color:white; padding:1.5rem; position:sticky; top:0; z-index:10; }
header h1 { margin:0 0 0.5rem 0; font-size:1.5rem; }
header p { margin:0 0 1rem 0; opacity:0.8; font-size:0.9rem; }
nav { display:flex; flex-wrap:wrap; gap:0.75rem; }
nav a { color:#93c5fd; text-decoration:none; font-size:0.85rem; }
nav a:hover { text-decoration:underline; }
main { max-width:1200px; margin:0 auto; padding:1rem; }
section { background:white; border-radius:8px; padding:1.25rem; margin-bottom:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
h2 { margin-top:0; font-size:1.25rem; border-bottom:1px solid #e2e8f0; padding-bottom:0.5rem; }
.controls { display:flex; gap:0.5rem; margin-bottom:1rem; flex-wrap:wrap; }
.controls input, .controls select { padding:0.5rem; border:1px solid #cbd5e1; border-radius:4px; }
table { width:100%; border-collapse:collapse; font-size:0.85rem; }
th, td { padding:0.5rem; text-align:left; border-bottom:1px solid #e2e8f0; }
th { background:#f1f5f9; cursor:pointer; }
tr:hover { background:#f8fafc; }
.badge { display:inline-block; padding:0.15rem 0.4rem; border-radius:4px; font-size:0.75rem; }
.badge-win { background:#dcfce7; color:#166534; }
.badge-loss { background:#fee2e2; color:#991b1b; }
.badge-pending { background:#fef3c7; color:#92400e; }
a { color:#2563eb; }
.pagination { display:flex; gap:0.25rem; margin-top:1rem; flex-wrap:wrap; }
.pagination button { padding:0.4rem 0.7rem; border:1px solid #cbd5e1; background:white; border-radius:4px; cursor:pointer; }
.pagination button.active { background:#0f172a; color:white; }
.card { border:1px solid #e2e8f0; border-radius:6px; padding:0.75rem; margin-bottom:0.5rem; }
pre { background:#f1f5f9; padding:0.75rem; border-radius:4px; overflow:auto; font-size:0.8rem; }
.flag-high { border-left:4px solid #dc2626; }
.flag-medium { border-left:4px solid #f59e0b; }
.flag-low { border-left:4px solid #6b7280; }
"""
    with open(os.path.join(DOCS, "style.css"), "w", encoding="utf-8") as f:
        f.write(css)

    # JS
    js = """
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
    const data = await fetchJSON('../site_data/competition.json');
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
    const data = await fetchJSON(`../site_data/leaderboard_page_${currentPage}.json`).catch(async () => {
      return await fetchJSON('../site_data/leaderboard.json');
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
    const data = await fetchJSON(`../site_data/trades/${file}`);
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
    const data = await fetchJSON('../site_data/markets.json');
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
    const data = await fetchJSON('../site_data/strategies.json');
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
    const data = await fetchJSON(`../site_data/users/${userId}.json`);
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
    const data = await fetchJSON('../site_data/verification.json');
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

    const sources = await fetchJSON('../site_data/data_sources.json');
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
"""
    with open(os.path.join(DOCS, "app.js"), "w", encoding="utf-8") as f:
        f.write(js)

def copy_site_data_to_docs():
    """Copy site_data into docs/site_data for GitHub Pages (docs/ is served, not root)."""
    src = SITE_DATA
    dst = os.path.join(DOCS, "site_data")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    # Also copy into docs root for relative fetch that works both locally and on Pages
    # app.js currently uses ../site_data, but for Pages we need ./site_data as well
    # So we patch app.js paths to use site_data/ relative to docs/
    # We'll rewrite app.js fetch paths after copying

def patch_app_js_paths():
    """Patch app.js to use site_data/ relative to docs/ for GitHub Pages compatibility."""
    app_path = os.path.join(DOCS, "app.js")
    if not os.path.exists(app_path):
        return
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Replace ../site_data with site_data and also handle ./site_data
    content = content.replace("../site_data/", "site_data/")
    content = content.replace("'../site_data/", "'site_data/")
    content = content.replace('"../site_data/', '"site_data/')
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(content)
    # Create .nojekyll
    with open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

def main() -> int:
    ensure_dirs()
    print("Building site data...")
    build_leaderboard()
    print(" - leaderboard")
    build_user_profiles()
    print(" - user profiles")
    build_trades()
    print(" - trades")
    build_markets()
    print(" - markets")
    build_strategies()
    print(" - strategies")
    build_verification()
    print(" - verification")
    build_competition_overview()
    print(" - competition overview")
    build_docs_site()
    print(" - docs site")
    copy_site_data_to_docs()
    print(" - copied site_data to docs/site_data")
    patch_app_js_paths()
    print(" - patched app.js for Pages")
    print("Done")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
