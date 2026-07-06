"""Builds the stock universe (~500 names, S&P 500 by default).

Live constituents are scraped from Wikipedia. If that fails (offline, layout
change), we fall back to a small static seed list so the pipeline still runs.
"""
from __future__ import annotations

import logging

import pandas as pd

import config

log = logging.getLogger(__name__)

_WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Minimal fallback so the pipeline never hard-fails on a network hiccup.
_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "XOM", "UNH", "MA", "JNJ", "PG", "HD", "COST", "ABBV",
]


def _normalize(ticker: str) -> str:
    # Yahoo uses '-' where the index uses '.', e.g. BRK.B -> BRK-B.
    return ticker.strip().upper().replace(".", "-")


def fetch_sp500_tickers() -> list[str]:
    """Return live S&P 500 tickers, or a fallback list on failure."""
    try:
        # Wikipedia 403-blocks pandas' default urllib User-Agent, so fetch the
        # page with requests + a browser UA and parse the HTML text instead.
        import io

        import requests

        resp = requests.get(
            _WIKI_SP500,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=30,
        )
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]
        tickers = [_normalize(t) for t in df["Symbol"].tolist()]
        log.info("Fetched %d S&P 500 tickers from Wikipedia", len(tickers))
        return tickers
    except Exception as exc:  # noqa: BLE001 - any failure -> fallback
        log.warning("S&P 500 fetch failed (%s); using fallback list", exc)
        return list(_FALLBACK)


def get_universe() -> list[str]:
    """Resolve the working universe, honoring config overrides/limits."""
    if config.UNIVERSE_OVERRIDE:
        tickers = [_normalize(t) for t in config.UNIVERSE_OVERRIDE]
        log.info("Using UNIVERSE_OVERRIDE (%d tickers)", len(tickers))
    else:
        tickers = fetch_sp500_tickers()

    # De-dupe, keep order.
    seen, ordered = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            ordered.append(t)

    if config.MAX_TICKERS:
        ordered = ordered[: config.MAX_TICKERS]
        log.info("Capped universe to MAX_TICKERS=%d", config.MAX_TICKERS)
    return ordered
