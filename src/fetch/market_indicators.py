"""Part 1: the 7+ headline market indicators.

Mix of Yahoo Finance tickers (VIX, gold, oil, BTC, DXY, USD/KRW, SKEW) and FRED
series (Treasury yields). FRED is used for yields because it is the cleanest free
source for constant-maturity rates.
"""
from __future__ import annotations

import json
import logging

import pandas as pd

import config
from src.fetch.macro_fred import fetch_fred_series

log = logging.getLogger(__name__)

# Yahoo-sourced indicators: label -> Yahoo symbol.
_YAHOO_INDICATORS = {
    "vix": "^VIX",            # CBOE Volatility Index
    "gold": "GC=F",           # Gold futures
    "wti_oil": "CL=F",        # WTI crude futures
    "bitcoin": "BTC-USD",     # Bitcoin
    "dxy": "DX-Y.NYB",        # US Dollar Index
    "usdkrw": "KRW=X",        # USD/KRW
    "skew": "^SKEW",          # CBOE SKEW (tail-risk) index
    # --- Major US equity indices ---
    "dow_jones": "^DJI",      # Dow Jones Industrial Average
    "sp500": "^GSPC",         # S&P 500 index
    "nasdaq": "^IXIC",        # Nasdaq Composite
    "russell2000": "^RUT",    # Russell 2000 (small-cap)
    "kospi": "^KS11",         # KOSPI Composite Index
    "kosdaq": "^KQ11",        # KOSDAQ Index
    # 10Y Treasury yield via Yahoo (^TNX, in %; same scale as FRED DGS10).
    # Used as a no-FRED-key fallback; overwritten by FRED DGS10 below if available.
    "ust_10y": "^TNX",
}

# FRED-sourced indicators: label -> FRED series id.
# These run AFTER the Yahoo set and only override when data is returned (i.e. a
# FRED key is configured), so ust_10y gracefully falls back to Yahoo ^TNX.
_FRED_INDICATORS = {
    "ust_10y": "DGS10",       # 10-Year Treasury constant maturity (overrides ^TNX)
    "ust_3y": "DGS3",         # 3-Year Treasury constant maturity
    "ust_2y": "DGS2",         # 2-Year (used later for 10y/2y spread)
}


def _fetch_yahoo(symbol: str) -> pd.Series:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period=config.PRICE_HISTORY_PERIOD)
    if hist.empty:
        return pd.Series(dtype=float)
    s = hist["Close"].dropna().copy()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:  # yfinance is usually tz-aware; only strip if so.
        idx = idx.tz_localize(None)
    s.index = idx.strftime("%Y-%m-%d")
    return s


def fetch_market_indicators() -> dict:
    """Return {label: {date: value}} and persist CSV + JSON."""
    series_map: dict[str, pd.Series] = {}

    for label, sym in _YAHOO_INDICATORS.items():
        try:
            s = _fetch_yahoo(sym)
            if not s.empty:
                series_map[label] = s
                log.info("Indicator %s (%s): %d points", label, sym, len(s))
        except Exception as exc:  # noqa: BLE001
            log.warning("Indicator %s (%s) failed: %s", label, sym, exc)

    for label, sid in _FRED_INDICATORS.items():
        s = fetch_fred_series(sid)
        if not s.empty:
            series_map[label] = s
            log.info("Indicator %s (FRED %s): %d points", label, sid, len(s))

    # Wide CSV: one column per indicator.
    wide = pd.DataFrame(series_map).sort_index()
    csv_path = config.RAW_DIR / "market_indicators.csv"
    wide.to_csv(csv_path, index_label="date")
    log.info("Saved indicators -> %s", csv_path)

    # Latest value + change for the UI header strip.
    latest = {}
    for label, s in series_map.items():
        s = s.dropna()
        if len(s) < 2:
            continue
        latest[label] = {
            "value": round(float(s.iloc[-1]), 4),
            "change_pct": round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2),
            "as_of": s.index[-1],
        }
    json_path = config.RAW_DIR / "market_indicators_latest.json"
    json_path.write_text(json.dumps(latest, indent=2), encoding="utf-8")
    log.info("Saved indicator snapshot -> %s", json_path)
    return {"history": {k: v.dropna().to_dict() for k, v in series_map.items()}, "latest": latest}
