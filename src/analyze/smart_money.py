"""Part 3 (selection): Top-N 'smart money picks' from the scored table."""
from __future__ import annotations

import json
import logging

import pandas as pd

import config

log = logging.getLogger(__name__)


def select_top_picks(scored: pd.DataFrame, targets: pd.DataFrame, prices: pd.DataFrame = None, n: int | None = None, out_name: str = "top_picks.json", names: dict | None = None) -> list[dict]:
    n = n or config.TOP_N_PICKS
    if scored.empty:
        return []

    top = scored.head(n).copy()
    target_map = (
        targets.set_index("ticker").to_dict(orient="index") if not targets.empty else {}
    )

    picks = []
    for _, r in top.iterrows():
        tk = r["ticker"]
        tinfo = target_map.get(tk, {})

        current_price = tinfo.get("current_price") or r.get("current_price")
        previous_close = tinfo.get("previous_close") or r.get("previous_close")
        market_cap = tinfo.get("market_cap")

        vol = None
        if prices is not None and not prices.empty and tk in prices["ticker"].values:
            tk_prices = prices[prices["ticker"] == tk]
            if not tk_prices.empty:
                last_bar = tk_prices.sort_values("date").iloc[-1]
                vol = int(last_bar["volume"]) if pd.notna(last_bar["volume"]) else None
                if current_price is None:
                    current_price = float(last_bar["close"])
                if previous_close is None and len(tk_prices) > 1:
                    previous_close = float(tk_prices.sort_values("date").iloc[-2]["close"])

        daily_change_pct = 0.0
        if current_price and previous_close:
            daily_change_pct = round(((current_price / previous_close) - 1) * 100, 2)
        elif tinfo.get("change_pct") is not None:
            daily_change_pct = float(tinfo.get("change_pct"))
        elif r.get("change_pct") is not None:
            daily_change_pct = float(r.get("change_pct"))

        picks.append(
            {
                "rank": int(r["rank"]),
                "ticker": tk,
                # Curated map first (KR Korean names), else yfinance shortName.
                "name": (names or {}).get(tk) or tinfo.get("name"),
                "composite_score": float(r["composite_score"]),
                "factors": {
                    "momentum": float(r["momentum_score"]),
                    "trend": float(r["trend_score"]),
                    "volume_surge": float(r["volume_surge_score"]),
                    "rel_strength": float(r["rel_strength_score"]),
                    "low_vol": float(r["low_vol_score"]),
                    "analyst_upside": float(r["analyst_upside_score"]),
                },
                "flow_status": r["flow_status"],
                "flow_color": r["flow_color"],
                "current_price": round(float(current_price), 2) if current_price else None,
                "previous_close": round(float(previous_close), 2) if previous_close else None,
                "daily_change_pct": daily_change_pct,
                "volume": vol,
                "market_cap": market_cap,
                "target_mean": tinfo.get("target_mean"),
                "upside_pct": tinfo.get("upside_pct"),
                "ai_brief": None,  # filled by ai.stock_brief
            }
        )

    (config.ANALYSIS_DIR / out_name).write_text(
        json.dumps(picks, indent=2), encoding="utf-8"
    )
    log.info("Selected top %d smart-money picks -> %s", len(picks), out_name)
    return picks
