"""KR-only refresh: update the Korean market data in dashboard.json.

Runs just the KR track (KIS OpenAPI when keys are set, else yfinance) and merges
the results into the existing dashboard.json — much faster than the full
pipeline because the ~500-ticker US universe is untouched.

Updates:
  - kr_picks                      (re-scored KOSPI top picks)
  - market_indicators.kospi/kosdaq  {value, change_pct, as_of}   (KIS only)
  - market_indicators_history.kospi/kosdaq  {date: close}        (KIS only)
  - kr_updated_at                 refresh timestamp

Usage:  python main.py --kr-only   (or python -m src.kr_refresh)
"""
from __future__ import annotations

import datetime as dt
import json
import logging

import config
from src.pipeline import _run_kr_track
from src.fetch.kis_prices import kis_available, fetch_index_daily

log = logging.getLogger(__name__)


def run() -> dict:
    log.info("=== KR-only refresh started (KIS=%s) ===", kis_available())

    picks = _run_kr_track()

    dash_path = config.OUTPUT_DIR / "dashboard.json"
    if not dash_path.exists():
        log.warning("dashboard.json missing — run the full pipeline once first.")
        return {"kr_picks": len(picks), "dashboard_updated": False}

    dashboard = json.loads(dash_path.read_text(encoding="utf-8"))
    if picks:
        dashboard["kr_picks"] = picks

    # KOSPI/KOSDAQ indicator cards + sparkline history (KIS keys required).
    if kis_available():
        for key in ("kospi", "kosdaq"):
            bars = fetch_index_daily(key)
            if len(bars) >= 2:
                last, prev = bars[-1], bars[-2]
                dashboard.setdefault("market_indicators", {})[key] = {
                    "value": round(last["close"], 4),
                    "change_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
                    "as_of": last["date"],
                }
                hist = dashboard.setdefault("market_indicators_history", {}).setdefault(key, {})
                for b in bars:
                    hist[b["date"]] = b["close"]
                log.info("Indicator %s updated: %.2f (%s)", key, last["close"], last["date"])
            else:
                log.warning("Indicator %s: no KIS index data.", key)

    dashboard["kr_updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    dash_path.write_text(
        json.dumps(dashboard, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("=== KR refresh complete: %d picks -> %s ===", len(picks), dash_path)
    return {"kr_picks": len(picks), "dashboard_updated": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    run()
