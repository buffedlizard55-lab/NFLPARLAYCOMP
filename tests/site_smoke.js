/*
 * Headless smoke test for the GitHub Pages front-end.
 *
 * Runs docs/app.js in Node with a minimal DOM/fetch stub, then invokes the real
 * render functions against the real bundles in docs/site_data. This catches the
 * failure mode a static site is most prone to: JavaScript that parses fine but
 * throws the moment a bundle is missing a field, leaving the page blank in a
 * browser where nobody is watching.
 *
 * Exits non-zero on any thrown error or unrendered placeholder.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const DOCS = path.join(__dirname, '..', 'docs');
const failures = [];
const notes = [];

// ---- minimal DOM + fetch ------------------------------------------------------
const elements = {};
function makeElement(id) {
  return {
    id,
    innerHTML: '',
    innerText: '',
    value: '',
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {},
    scrollIntoView() {},
  };
}
const documentStub = {
  getElementById(id) {
    if (!elements[id]) elements[id] = makeElement(id);
    return elements[id];
  },
  querySelectorAll() { return []; },
  querySelector() { return makeElement('stub'); },
  addEventListener() {},
};

function loadBundle(rel) {
  const full = path.join(DOCS, rel);
  if (!fs.existsSync(full)) return null;
  try {
    return JSON.parse(fs.readFileSync(full, 'utf8'));
  } catch (e) {
    failures.push(`bundle ${rel} is not valid JSON: ${e.message}`);
    return null;
  }
}

async function fetchStub(rel) {
  const data = loadBundle(rel);
  if (data === null) return { ok: false, status: 404, json: async () => null };
  return { ok: true, status: 200, json: async () => data };
}

// ---- run app.js --------------------------------------------------------------
const appPath = path.join(DOCS, 'app.js');
const source = fs.readFileSync(appPath, 'utf8');
const sandbox = {
  document: documentStub,
  fetch: fetchStub,
  console,
  Date,
  Number,
  Math,
  JSON,
  Object,
  Array,
  parseInt,
  parseFloat,
  String,
  Boolean,
  isNaN,
  setTimeout,
  alert() {},
  window: {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

try {
  vm.runInContext(source, sandbox, { filename: 'app.js' });
  notes.push('app.js executed without throwing');
} catch (e) {
  failures.push(`app.js threw on load: ${e.message}`);
}

// ---- drive the renderers -----------------------------------------------------
async function run() {
  const checks = [
    ['loadOverview', 'overview-content'],
    ['loadLeaderboard', 'leaderboard-content'],
    ['loadMarkets', 'markets-content'],
    ['loadStrategies', 'strategies-content'],
    ['loadVerification', 'verification-content'],
    ['loadHistory', 'history-content'],
  ];
  for (const [fn, target] of checks) {
    if (typeof sandbox[fn] !== 'function') {
      failures.push(`${fn} is not defined`);
      continue;
    }
    try {
      await sandbox[fn]();
      const html = (elements[target] || {}).innerHTML || '';
      if (!html) {
        failures.push(`${fn}() rendered nothing into #${target}`);
      } else if (html.includes('Error:')) {
        failures.push(`${fn}() rendered an error: ${html.slice(0, 200)}`);
      } else if (html.includes('undefined') || html.includes('NaN')) {
        failures.push(`${fn}() rendered undefined/NaN into #${target}`);
      } else {
        notes.push(`${fn}() rendered ${html.length} chars into #${target}`);
      }
    } catch (e) {
      failures.push(`${fn}() threw: ${e.message}`);
    }
  }

  // Trades views
  for (const [target, file] of [['upcoming-content', 'upcoming.json'],
                                ['recent-content', 'recent.json'],
                                ['closed-content', 'closed.json'],
                                ['rejected-content', 'rejected.json']]) {
    try {
      await sandbox.loadTrades(target, file);
      const html = (elements[target] || {}).innerHTML || '';
      if (!html) failures.push(`loadTrades(${file}) rendered nothing`);
      else if (html.includes('Error:')) failures.push(`loadTrades(${file}) errored`);
      else notes.push(`loadTrades(${file}) rendered ${html.length} chars`);
    } catch (e) {
      failures.push(`loadTrades(${file}) threw: ${e.message}`);
    }
  }

  // Every user profile must render, not just the first.
  const lb = loadBundle('site_data/leaderboard.json');
  if (!lb || !lb.users || !lb.users.length) {
    failures.push('leaderboard.json has no users to drive profile rendering');
  } else {
    const sampleSize = Math.min(lb.users.length, 25);
    for (let i = 0; i < sampleSize; i++) {
      const u = lb.users[i];
      try {
        await sandbox.loadProfile(u.user_id);
        const html = (elements['user-profile'] || {}).innerHTML || '';
        if (!html || html.includes('User not found')) {
          failures.push(`loadProfile(${u.user_id}) rendered nothing`);
        } else if (html.includes('undefined') || html.includes('NaN')) {
          failures.push(`loadProfile(${u.user_id}) rendered undefined/NaN`);
        }
      } catch (e) {
        failures.push(`loadProfile(${u.user_id}) threw: ${e.message}`);
      }
    }
    notes.push(`rendered ${sampleSize} user profiles without error`);
  }

  // Detail expansion for a settled trade must produce the full record.
  const closed = loadBundle('site_data/trades/closed.json');
  if (closed && closed.trades && closed.trades.length) {
    const t = closed.trades[0];
    try {
      const detail = sandbox.tradeDetail(t);
      const recon = sandbox.reconcile(t);
      if (!detail.includes(t.trade_id)) failures.push('tradeDetail missing trade id');
      if (!detail.includes('Official source')) failures.push('tradeDetail missing source section');
      if (!recon.includes('=')) failures.push('reconcile did not render arithmetic');
      notes.push('tradeDetail + reconcile rendered for a settled trade');
    } catch (e) {
      failures.push(`tradeDetail threw: ${e.message}`);
    }
  }

  // Provenance must be visibly labelled for settled trades.
  if (closed && closed.trades) {
    const settled = closed.trades.filter(x => x.settlement_result_source);
    const missing = closed.trades.filter(x => !x.settlement_result_source);
    if (missing.length) {
      failures.push(`${missing.length} settled trades lack settlement provenance`);
    }
    notes.push(`${settled.length} settled trades carry provenance`);
    if (settled.length) {
      const b = sandbox.provBadge(settled[0]);
      if (!b) failures.push('provBadge rendered nothing for a settled trade');
    }
  }

  return failures;
}

run().then(failuresOut => {
  console.log('--- site smoke test ---');
  for (const n of notes) console.log('  ok  : ' + n);
  if (failuresOut.length) {
    for (const f of failuresOut) console.log('  FAIL: ' + f);
    console.log(`\n${failuresOut.length} failure(s)`);
    process.exit(1);
  }
  console.log('\nAll site render checks passed');
}).catch(e => {
  console.log('smoke runner crashed: ' + e.stack);
  process.exit(1);
});
