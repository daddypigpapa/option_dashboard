"""FRED REST client + the ~30-indicator macro bundle for AI macro analysis.

Uses the public FRED API (free key required). Each series is cached to
data/raw/fred/<id>.csv so repeat runs don't re-hit the API.
"""
from __future__ import annotations

import logging

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_DIR = config.RAW_DIR / "fred"
_FRED_DIR.mkdir(parents=True, exist_ok=True)

# ~30 macro series spanning rates, inflation, growth, labor, credit, sentiment.
MACRO_SERIES: dict[str, str] = {
    "DGS10": "10Y Treasury yield",
    "DGS2": "2Y Treasury yield",
    "DGS3": "3Y Treasury yield",
    "DGS3MO": "3M Treasury yield",
    "T10Y2Y": "10Y-2Y spread",
    "T10Y3M": "10Y-3M spread",
    "DFF": "Fed funds effective rate",
    "FEDFUNDS": "Fed funds rate (monthly)",
    "CPIAUCSL": "CPI (all urban)",
    "CPILFESL": "Core CPI",
    "PCEPILFE": "Core PCE",
    "T5YIE": "5Y breakeven inflation",
    "T10YIE": "10Y breakeven inflation",
    "UNRATE": "Unemployment rate",
    "PAYEMS": "Nonfarm payrolls",
    "ICSA": "Initial jobless claims",
    "GDPC1": "Real GDP",
    "INDPRO": "Industrial production",
    "UMCSENT": "U. Michigan consumer sentiment",
    "RSAFS": "Retail sales",
    "HOUST": "Housing starts",
    "PERMIT": "Building permits",
    "M2SL": "M2 money supply",
    "BAMLH0A0HYM2": "High-yield credit spread (OAS)",
    "BAMLC0A0CM": "IG credit spread (OAS)",
    "VIXCLS": "VIX (FRED)",
    "DTWEXBGS": "Trade-weighted USD index",
    "DCOILWTICO": "WTI crude (FRED)",
    "DEXKOUS": "USD/KRW (FRED)",
    "WALCL": "Fed balance sheet",
}


def fetch_fred_series(series_id: str, use_cache: bool = True) -> pd.Series:
    """Fetch one FRED series as a date-indexed (YYYY-MM-DD string) Series."""
    cache = _FRED_DIR / f"{series_id}.csv"
    if use_cache and cache.exists():
        df = pd.read_csv(cache)
        return pd.Series(df["value"].values, index=df["date"].astype(str), name=series_id)

    if not config.FRED_API_KEY:
        log.warning("FRED_API_KEY missing; cannot fetch %s", series_id)
        return pd.Series(dtype=float, name=series_id)

    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }
    try:
        resp = requests.get(_BASE, params=params, timeout=30)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED fetch %s failed: %s", series_id, exc)
        return pd.Series(dtype=float, name=series_id)

    rows = [(o["date"], float(o["value"])) for o in obs if o["value"] not in (".", "")]
    if not rows:
        return pd.Series(dtype=float, name=series_id)
    dates, vals = zip(*rows)
    s = pd.Series(vals, index=dates, name=series_id)
    pd.DataFrame({"date": dates, "value": vals}).to_csv(cache, index=False)
    return s


def fetch_macro_bundle() -> pd.DataFrame:
    """Fetch all MACRO_SERIES, save a wide CSV, and return the latest values."""
    latest_rows = []
    for sid, desc in MACRO_SERIES.items():
        s = fetch_fred_series(sid).dropna()
        if s.empty:
            continue
        prev = s.iloc[-2] if len(s) >= 2 else s.iloc[-1]
        latest_rows.append(
            {
                "series_id": sid,
                "description": desc,
                "latest": round(float(s.iloc[-1]), 4),
                "previous": round(float(prev), 4),
                "as_of": s.index[-1],
            }
        )

    df = pd.DataFrame(latest_rows)
    out = config.RAW_DIR / "macro_indicators.csv"
    df.to_csv(out, index=False)
    log.info("Saved %d macro series -> %s", len(df), out)
    return df
