"""Part 1: daily price + volume download for the whole universe via Yahoo Finance.

Saves one tidy CSV (long format) plus a per-ticker latest-snapshot JSON for the
frontend. Downloads in batches to stay friendly with Yahoo's rate limits.
"""
from __future__ import annotations

import json
import logging
import time

import pandas as pd

import config

log = logging.getLogger(__name__)

_BATCH = 50           # tickers per yfinance download call
_PAUSE = 1.0          # seconds between batches


def _download_batch(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        tickers=" ".join(tickers),
        period=config.PRICE_HISTORY_PERIOD,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    frames = []
    # yfinance returns a MultiIndex (ticker, field) for multi-ticker requests,
    # or a flat frame for a single ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        for tk in tickers:
            if tk not in raw.columns.get_level_values(0):
                continue
            ticker_df = raw[tk]
            cols = ticker_df.columns
            close_col = "Close" if "Close" in cols else ("close" if "close" in cols else None)
            if close_col:
                sub = ticker_df.dropna(subset=[close_col]).reset_index()
            else:
                sub = ticker_df.dropna(how="all").reset_index()
            sub["ticker"] = tk
            frames.append(sub)
    else:
        cols = raw.columns
        close_col = "Close" if "Close" in cols else ("close" if "close" in cols else None)
        if close_col:
            sub = raw.dropna(subset=[close_col]).reset_index()
        else:
            sub = raw.dropna(how="all").reset_index()
        sub["ticker"] = tickers[0]
        frames.append(sub)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def download_prices(tickers: list[str], out_prefix: str = "prices") -> pd.DataFrame:
    """Download OHLCV for all tickers and persist to data/raw.

    ``out_prefix`` names the artifacts so the KR track (``kr_prices``) doesn't
    overwrite the US one.
    """
    all_frames = []
    for i in range(0, len(tickers), _BATCH):
        batch = tickers[i : i + _BATCH]
        log.info("Downloading prices %d-%d / %d", i + 1, i + len(batch), len(tickers))
        try:
            df = _download_batch(batch)
            if not df.empty:
                all_frames.append(df)
        except Exception as exc:  # noqa: BLE001
            log.warning("Batch %s failed: %s", batch[:3], exc)
        time.sleep(_PAUSE)

    if not all_frames:
        log.error("No price data downloaded.")
        return pd.DataFrame()

    prices = pd.concat(all_frames, ignore_index=True)
    prices = prices.rename(columns=str.lower)
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
    prices = prices[[c for c in cols if c in prices.columns]]

    csv_path = config.RAW_DIR / f"{out_prefix}.csv"
    prices.to_csv(csv_path, index=False)
    log.info("Saved %d price rows -> %s", len(prices), csv_path)

    _write_latest_snapshot(prices, out_prefix)
    return prices


def _write_latest_snapshot(prices: pd.DataFrame, out_prefix: str = "prices") -> None:
    """Compact JSON of each ticker's most recent bar + 1d change, for the UI."""
    snap = []
    for tk, g in prices.groupby("ticker"):
        g = g.sort_values("date")
        if len(g) < 2:
            continue
        last, prev = g.iloc[-1], g.iloc[-2]
        snap.append(
            {
                "ticker": tk,
                "date": last["date"],
                "close": round(float(last["close"]), 4),
                "volume": int(last["volume"]) if pd.notna(last["volume"]) else None,
                "change_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
            }
        )
    path = config.RAW_DIR / f"{out_prefix}_latest.json"
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    log.info("Saved latest snapshot for %d tickers -> %s", len(snap), path)
