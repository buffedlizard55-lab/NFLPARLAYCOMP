#!/usr/bin/env python3
"""Minimal, dependency-free client for Kalshi's public (unauthenticated) Trade API.

Design rules (see README "Verification contract"):
  * Only official endpoints under https://external-api.kalshi.com/trade-api/v2 are called
    (api.elections.kalshi.com is kept as a fallback host — both serve the same Trade API).
  * Every response body is recorded in a call log (URL, HTTP status, bytes, SHA-256,
    retrieval time) which the collector stores as the fetch manifest.  Prices become
    evidence only through this log.
  * No credentials are ever read or sent.  This client can only READ.
  * Rate limiting: a small fixed pause between calls plus exponential backoff on
    429/5xx/network errors, per Kalshi's documented guidance.

Official API reference: https://docs.kalshi.com/api-reference/overview
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

PRIMARY_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
FALLBACK_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = ("NFLPARLAYCOMP/1.0 (+https://github.com/buffedlizard55-lab/NFLPARLAYCOMP; "
              "paper-trading research, read-only, no credentials)")


def iso(ts: float) -> str:
    """UTC ISO-8601 timestamp for a unix epoch float/int."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class KalshiError(RuntimeError):
    pass


class KalshiClient:
    """Read-only HTTP client with a call log that the collector stores."""

    def __init__(self, base_url: str = PRIMARY_BASE_URL, pause: float = 0.12,
                 timeout: float = 30.0, max_retries: int = 5, opener=None):
        self.base_url = base_url.rstrip("/")
        self.pause = pause
        self.timeout = timeout
        self.max_retries = max_retries
        self.calls: list[dict] = []
        self._opener = opener or urllib.request.build_opener()
        self._last_call = 0.0

    # ------------------------------------------------------------- transport
    def _sleep_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.pause:
            time.sleep(self.pause - elapsed)

    def get(self, path: str, params: dict | None = None) -> tuple[dict, bytes, str]:
        """GET a JSON endpoint.  Returns (parsed_json, raw_bytes, full_url)."""
        query = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        attempt = 0
        while True:
            self._sleep_for_rate_limit()
            request = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            started = time.time()
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    raw = response.read()
                    status = response.status
            except urllib.error.HTTPError as error:
                raw = error.read() if error.fp else b""
                status = error.code
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                raw = str(error).encode()
                status = 0
            finally:
                self._last_call = time.monotonic()
            self.calls.append({
                "url": url, "status": status, "bytes": len(raw), "at": iso(started),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            if status == 200:
                try:
                    return json.loads(raw.decode("utf-8")), raw, url
                except json.JSONDecodeError as error:
                    raise KalshiError(f"non-JSON body from {url}: {error}") from error
            if status in (400, 404):
                # A definitive client error: retrying will not help.
                raise KalshiError(f"HTTP {status} from {url}: {raw[:200]!r}")
            attempt += 1
            if attempt > self.max_retries:
                raise KalshiError(f"HTTP {status} from {url} after {attempt} attempts: {raw[:200]!r}")
            # 429 / 5xx / network: exponential backoff (documented guidance for 429).
            time.sleep(min(30.0, 0.5 * (2 ** attempt)))

    # ------------------------------------------------------------ endpoints
    # All endpoint names/parameters verified against https://docs.kalshi.com
    # (see docs/SOURCES.md) and empirically against the live API on 2026-09-22.
    def exchange_status(self) -> dict:
        return self.get("exchange/status")[0]

    def historical_cutoff(self) -> dict:
        return self.get("historical/cutoff")[0]

    def series(self, ticker: str) -> dict:
        return self.get(f"series/{urllib.parse.quote(ticker)}")[0].get("series", {})

    def series_list(self, category: str | None = None) -> list[dict]:
        params = {"category": category} if category else None
        return (self.get("series", params)[0].get("series")) or []

    def events(self, series_ticker: str | None = None, status: str | None = None,
               limit: int = 200, max_pages: int = 25,
               min_date: str | None = None, max_date: str | None = None) -> list[dict]:
        """Cursor-paginated event list (documented cursor pagination)."""
        out: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params = {"series_ticker": series_ticker, "status": status, "limit": limit,
                      "cursor": cursor or None, "min_date": min_date, "max_date": max_date}
            payload = self.get("events", params)[0]
            rows = payload.get("events") or []
            out.extend(rows)
            cursor = str(payload.get("cursor") or "")
            if not cursor or not rows:
                break
        return out

    def markets(self, series_ticker: str | None = None, status: str | None = None,
                limit: int = 200, max_pages: int = 25, event_ticker: str | None = None,
                tickers: list[str] | None = None) -> list[dict]:
        """Cursor-paginated market list.  `tickers` filters to specific markets."""
        out: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params = {"series_ticker": series_ticker, "status": status, "limit": limit,
                      "cursor": cursor or None, "event_ticker": event_ticker}
            if tickers:
                params["ticker"] = ",".join(tickers)
            payload = self.get("markets", params)[0]
            rows = payload.get("markets") or []
            out.extend(rows)
            cursor = str(payload.get("cursor") or "")
            if not cursor or not rows:
                break
            if len(out) >= 1000:
                break
        return out

    def market(self, ticker: str) -> dict:
        payload = self.get(f"markets/{urllib.parse.quote(ticker, safe='')}")
        return payload[0].get("market", payload[0])

    def orderbook(self, ticker: str, depth: int = 100) -> dict:
        payload = self.get(
            f"markets/{urllib.parse.quote(ticker, safe='')}/orderbook", {"depth": depth})
        return payload[0]

    def candlesticks(self, series_ticker: str, ticker: str, start_ts: int, end_ts: int,
                     period_interval: int = 60) -> list[dict]:
        """Hourly (60), daily (1440) or 1-minute (1) candlesticks for one market.

        Verified live 2026-09-22 for series KXNFLGAME.  Returns [] when the API has no
        bars in the window.  The caller pages windows so each response stays bounded.
        """
        payload = self.get(
            f"series/{urllib.parse.quote(series_ticker, safe='')}"
            f"/markets/{urllib.parse.quote(ticker, safe='')}/candlesticks",
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval})
        return payload[0].get("candlesticks") or []

    def trades(self, ticker: str | None = None, limit: int = 100, min_ts: int | None = None,
               max_ts: int | None = None, max_pages: int = 5) -> list[dict]:
        """Public trade tape.  NOTE (verified 2026-09-22): the tape does NOT return
        trades older than a few hours for these markets even when min_ts/max_ts are
        given, so historical fills cannot be validated against the tape — candlesticks
        are the verified historical source.  The tape IS used for execution-realism
        checks of fills made near collection time."""
        out: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            payload = self.get("markets/trades", {
                "ticker": ticker, "limit": limit, "min_ts": min_ts, "max_ts": max_ts,
                "cursor": cursor or None})[0]
            rows = payload.get("trades") or []
            out.extend(rows)
            cursor = str(payload.get("cursor") or "")
            if not cursor or not rows:
                break
        return out


class FixtureClient(KalshiClient):
    """Offline client used by tests: serves pre-recorded JSON bodies keyed by path."""

    def __init__(self, fixtures: dict[str, object]):
        super().__init__(pause=0.0)
        self.fixtures = fixtures

    def get(self, path: str, params: dict | None = None):
        import hashlib
        import json
        query = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key = path.lstrip("/")
        if query:
            key += "?" + urllib.parse.urlencode(query, doseq=True)
        if key not in self.fixtures:
            if path.lstrip("/") in self.fixtures:
                key = path.lstrip("/")
            else:
                self.calls.append({"url": key, "status": 404, "bytes": 0,
                                   "at": iso(time.time()), "sha256": ""})
                raise KalshiError(f"HTTP 404 (fixture missing) for {key}")
        body = self.fixtures[key]
        raw = json.dumps(body).encode()
        self.calls.append({"url": key, "status": 200, "bytes": len(raw),
                           "at": iso(time.time()),
                           "sha256": hashlib.sha256(raw).hexdigest()})
        return body, raw, key
