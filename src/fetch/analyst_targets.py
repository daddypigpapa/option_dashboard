"""Part 2: analyst target prices + upside %, via yfinance.

yfinance exposes consensus targets through ``Ticker.analyst_price_targets`` (and
falls back to the ``info`` dict on older versions). We compute upside vs the last
close. This is the one "premium-ish" datapoint available for free, though it is
rate-limited, so we go one ticker at a time with light pacing.
"""
from __future__ import annotations

import json
import logging
import time

import pandas as pd

import config

log = logging.getLogger(__name__)

_PAUSE = 0.3  # seconds between tickers


def _targets_for(ticker: str) -> dict | None:
    import yfinance as yf

    t = yf.Ticker(ticker)
    current = mean = high = low = mcap = pclose = name = None

    try:
        info = t.info
        if isinstance(info, dict) and info:
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            mean = info.get("targetMeanPrice")
            high = info.get("targetHighPrice")
            low = info.get("targetLowPrice")
            mcap = info.get("marketCap")
            pclose = info.get("previousClose")
            name = info.get("shortName") or info.get("longName")
    except Exception:
        pass

    if not mean or not current:
        try:
            apt = t.analyst_price_targets
            if isinstance(apt, dict) and apt:
                current = current or apt.get("current")
                mean = mean or apt.get("mean")
                high = high or apt.get("high")
                low = low or apt.get("low")
        except Exception:
            pass

    if not current:
        return None

    upside = round((float(mean) / float(current) - 1) * 100, 2) if (mean and current) else 0.0

    return {
        "ticker": ticker,
        "name": name,
        "current_price": round(float(current), 2) if current else None,
        "target_mean": round(float(mean), 2) if mean else None,
        "target_high": round(float(high), 2) if high else None,
        "target_low": round(float(low), 2) if low else None,
        "upside_pct": upside,
        "market_cap": mcap,
        "previous_close": pclose,
    }


def fetch_analyst_targets(tickers: list[str], out_prefix: str = "analyst_targets") -> pd.DataFrame:
    rows = []
    for i, tk in enumerate(tickers, 1):
        try:
            row = _targets_for(tk)
            if row:
                rows.append(row)
        except Exception as exc:  # noqa: BLE001
            log.debug("targets %s failed: %s", tk, exc)
        if i % 50 == 0:
            log.info("Analyst targets %d / %d", i, len(tickers))
        time.sleep(_PAUSE)

    df = pd.DataFrame(rows)
    csv_path = config.RAW_DIR / f"{out_prefix}.csv"
    df.to_csv(csv_path, index=False)
    (config.RAW_DIR / f"{out_prefix}.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    log.info("Saved analyst targets for %d tickers -> %s", len(df), csv_path)
    return df
