"""Part 2: per-ticker 6-factor scoring from price/volume + analyst data.

Six factors (all derived from FREE data so the score always computes):
  1. momentum      - 63-day (~3 month) total return
  2. trend         - price vs 50/200-day moving averages
  3. volume_surge  - recent 5-day avg volume vs 60-day avg (수급/거래량)
  4. rel_strength  - 63-day return relative to the S&P 500 (SPY)
  5. low_vol       - inverse of 20-day realized volatility (lower vol scores higher)
  6. analyst_upside- consensus target mean vs current price

Each factor is converted to a 0-100 percentile rank across the universe, then
averaged into ``composite_score``. Options-flow status (paid) is attached when
available but does not block scoring.
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

import config

log = logging.getLogger(__name__)

_FACTORS = ["momentum", "trend", "volume_surge", "rel_strength", "low_vol", "analyst_upside"]


def _per_ticker_metrics(prices: pd.DataFrame, spy_ret_63: float | None) -> pd.DataFrame:
    rows = []
    for tk, g in prices.groupby("ticker"):
        g = g.sort_values("date")
        close = g["close"].astype(float).reset_index(drop=True)
        vol = g["volume"].astype(float).reset_index(drop=True)
        if len(close) < 65:
            continue

        ret_63 = close.iloc[-1] / close.iloc[-64] - 1
        ma50 = close.tail(50).mean()
        ma200 = close.tail(200).mean() if len(close) >= 200 else close.mean()
        last = close.iloc[-1]
        # Trend: how far above both MAs (averaged), positive = uptrend.
        trend = ((last / ma50 - 1) + (last / ma200 - 1)) / 2

        vol5 = vol.tail(5).mean()
        vol60 = vol.tail(60).mean()
        volume_surge = (vol5 / vol60 - 1) if vol60 else 0.0

        daily_ret = close.pct_change().tail(20)
        realized_vol = daily_ret.std() * np.sqrt(252) if len(daily_ret) > 2 else np.nan
        rel_strength = (ret_63 - spy_ret_63) if spy_ret_63 is not None else ret_63

        rows.append(
            {
                "ticker": tk,
                "momentum": ret_63,
                "trend": trend,
                "volume_surge": volume_surge,
                "rel_strength": rel_strength,
                "realized_vol": realized_vol,
            }
        )
    return pd.DataFrame(rows)


def _percentile(s: pd.Series, invert: bool = False) -> pd.Series:
    r = s.rank(pct=True) * 100
    return (100 - r) if invert else r


def score_universe(
    prices: pd.DataFrame,
    targets: pd.DataFrame,
    options_flow: dict[str, dict] | None = None,
    benchmark: str = "SPY",
    out_prefix: str = "scores",
) -> pd.DataFrame:
    """Produce a scored, ranked table for the whole universe.

    ``benchmark`` is the ticker used for relative strength (SPY for US, ^KS11 for
    KR). ``out_prefix`` names the persisted artifacts (``scores`` / ``kr_scores``).
    """
    options_flow = options_flow or {}

    # Benchmark 63-day return for relative strength.
    bench = prices[prices["ticker"] == benchmark].sort_values("date")["close"].astype(float)
    bench_ret_63 = (bench.iloc[-1] / bench.iloc[-64] - 1) if len(bench) >= 64 else None

    metrics = _per_ticker_metrics(prices, bench_ret_63)
    # Don't score the benchmark itself among the picks.
    metrics = metrics[metrics["ticker"] != benchmark]
    if metrics.empty:
        log.error("No tickers had enough history to score.")
        return pd.DataFrame()

    # Merge analyst upside.
    if not targets.empty and "upside_pct" in targets.columns:
        metrics = metrics.merge(
            targets[["ticker", "upside_pct"]], on="ticker", how="left"
        )
    else:
        metrics["upside_pct"] = np.nan
    # KR targets are often sparse; fall back to median, then 0 if all missing.
    _med = metrics["upside_pct"].median()
    metrics["analyst_upside"] = metrics["upside_pct"].fillna(_med if pd.notna(_med) else 0.0)

    # Factor -> 0-100 percentile. low_vol inverts realized_vol.
    metrics["momentum_score"] = _percentile(metrics["momentum"])
    metrics["trend_score"] = _percentile(metrics["trend"])
    metrics["volume_surge_score"] = _percentile(metrics["volume_surge"])
    metrics["rel_strength_score"] = _percentile(metrics["rel_strength"])
    metrics["low_vol_score"] = _percentile(metrics["realized_vol"].fillna(metrics["realized_vol"].median()), invert=True)
    metrics["analyst_upside_score"] = _percentile(metrics["analyst_upside"])

    score_cols = [f"{f}_score" for f in _FACTORS]
    metrics["composite_score"] = metrics[score_cols].mean(axis=1).round(2)

    # Attach options-flow status (paid; may be empty).
    metrics["flow_status"] = metrics["ticker"].map(
        lambda t: options_flow.get(t, {}).get("status", "unavailable")
    )
    metrics["flow_color"] = metrics["ticker"].map(
        lambda t: options_flow.get(t, {}).get("color", "gray")
    )

    metrics = metrics.sort_values("composite_score", ascending=False).reset_index(drop=True)
    metrics["rank"] = metrics.index + 1

    out_cols = (
        ["rank", "ticker", "composite_score"]
        + score_cols
        + ["momentum", "trend", "volume_surge", "rel_strength", "realized_vol",
           "analyst_upside", "flow_status", "flow_color"]
    )
    scored = metrics[out_cols].round(4)

    csv_path = config.ANALYSIS_DIR / f"{out_prefix}.csv"
    scored.to_csv(csv_path, index=False)
    scored.to_json(config.ANALYSIS_DIR / f"{out_prefix}.json", orient="records", indent=2)
    log.info("Scored %d tickers (benchmark=%s) -> %s", len(scored), benchmark, csv_path)
    return scored
