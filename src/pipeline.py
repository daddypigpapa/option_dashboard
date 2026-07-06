"""End-to-end pipeline. Wires Part 1 (fetch) -> Part 2 (analyze) -> Part 3 (AI)
and writes a single consolidated dashboard.json for the frontend.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

import pandas as pd

import config
from src.universe import get_universe
from src.kr_universe import get_kr_universe, KR_BENCHMARK, KR_NAMES
from src.fetch.prices import download_prices
from src.fetch.market_indicators import fetch_market_indicators
from src.fetch.macro_fred import fetch_macro_bundle
from src.fetch.analyst_targets import fetch_analyst_targets
from src.fetch.economic_calendar import fetch_economic_calendar
from src.fetch.dart_disclosures import fetch_dart_disclosures
from src.premium.options_flow import fetch_options_flow
from src.premium.etf_flows import fetch_etf_flows
from src.analyze.scoring import score_universe
from src.analyze.smart_money import select_top_picks
from src.ai.stock_brief import write_briefs
from src.ai.macro_analysis import run_macro_analysis

log = logging.getLogger(__name__)


def run(skip_ai: bool = False) -> dict:
    log.info("=== Stock dashboard pipeline started ===")

    # ---- Part 1: data fetching ----
    universe = get_universe()
    # Always include SPY as the relative-strength benchmark.
    tickers = universe if "SPY" in universe else universe + ["SPY"]

    prices = download_prices(tickers)
    indicators = fetch_market_indicators()
    macro_df = fetch_macro_bundle()
    targets = fetch_analyst_targets(universe)
    calendar = fetch_economic_calendar()
    dart_disclosures = fetch_dart_disclosures()

    # ---- Part 2: premium adapters + scoring ----
    options_flow = fetch_options_flow(universe)
    etf_flows = fetch_etf_flows(top_n=10)
    scored = score_universe(prices, targets, options_flow)
    picks = select_top_picks(scored, targets, prices)

    # ---- KR track: score the KOSPI universe for the day-time (08-20) view ----
    kr_picks = _run_kr_track()

    # ---- Part 3: AI ----
    macro_ai = {"claude": None, "gemini": None, "inputs": ""}
    if not skip_ai:
        picks = write_briefs(picks)
        if kr_picks:
            kr_picks = write_briefs(kr_picks, out_name="kr_top_picks.json")
        macro_ai = run_macro_analysis(macro_df, indicators.get("latest"))
    else:
        log.info("AI steps skipped (--skip-ai).")

    # ---- Consolidate ----
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    dashboard = {
        "generated_at": now_iso,
        # The full pipeline refreshes the KR track too, so stamp it as well
        # (otherwise only src/kr_refresh.py sets this and the header shows "-").
        "kr_updated_at": now_iso if kr_picks else None,
        "universe_size": len(universe),
        "market_indicators": indicators.get("latest", {}),
        "market_indicators_history": indicators.get("history", {}),
        "top_picks": picks,
        "kr_picks": kr_picks,
        "options_flow": list(options_flow.values()),
        "etf_flows": etf_flows,
        "macro_analysis": macro_ai,
        "economic_calendar": calendar,
        "dart_disclosures": dart_disclosures,
        "scores_csv": str((config.ANALYSIS_DIR / "scores.csv").relative_to(config.ROOT_DIR)),
    }
    out = config.OUTPUT_DIR / "dashboard.json"
    out.write_text(json.dumps(dashboard, indent=2, default=str), encoding="utf-8")
    log.info("=== Pipeline complete -> %s ===", out)
    return dashboard


def _run_kr_track() -> list[dict]:
    """Score the KOSPI universe and return its top picks (same shape as US).

    Uses the KOSPI index (^KS11) as the relative-strength benchmark and writes
    KR-prefixed artifacts so the US track is untouched. Returns [] on failure so
    the pipeline never hard-fails on the KR side.
    """
    try:
        kr_universe = get_kr_universe()
        kr_tickers = kr_universe + [KR_BENCHMARK]

        # Prefer the KIS OpenAPI (keys from dashboard settings) — always current.
        # Fall back to yfinance when keys are missing or KIS returns nothing.
        from src.fetch.kis_prices import kis_available, fetch_kr_prices_kis

        kr_prices = pd.DataFrame()
        if kis_available():
            log.info("KR track: using 한국투자증권(KIS) OpenAPI for prices.")
            kr_prices = fetch_kr_prices_kis(kr_universe, benchmark=KR_BENCHMARK)
        if kr_prices.empty:
            log.info("KR track: falling back to yfinance prices.")
            kr_prices = download_prices(kr_tickers, out_prefix="kr_prices")
        if kr_prices.empty:
            log.warning("KR prices empty; KR picks skipped.")
            return []
        kr_targets = fetch_analyst_targets(kr_universe, out_prefix="kr_analyst_targets")
        kr_scored = score_universe(
            kr_prices, kr_targets, options_flow=None,
            benchmark=KR_BENCHMARK, out_prefix="kr_scores",
        )
        kr_picks = select_top_picks(
            kr_scored, kr_targets, kr_prices, out_name="kr_top_picks.json",
            names=KR_NAMES,
        )
        log.info("KR track produced %d picks.", len(kr_picks))
        return kr_picks
    except Exception as exc:  # noqa: BLE001
        log.warning("KR track failed (%s); KR picks skipped.", exc)
        return []
