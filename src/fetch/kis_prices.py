"""KR daily prices via the 한국투자증권(KIS) OpenAPI.

Used to refresh the Korean market track with up-to-date data when KIS keys are
entered in the dashboard settings (KIS_APP_KEY / KIS_APP_SECRET). The endpoints
and token handling mirror the proven code in option_dashboard/kis_collector.py:

  - POST /oauth2/tokenP                               access token (cached ~24h)
  - FHKST03010100 inquire-daily-itemchartprice        stock/ETF daily OHLCV (<=100 bars)
  - FHKUP03500100 inquire-daily-indexchartprice       KOSPI/KOSDAQ index daily bars

Without keys every function degrades gracefully (None / empty), so callers can
fall back to yfinance.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

_BASE_URL = "https://openapi.koreainvestment.com:9443"
_TOKEN_CACHE = config.RAW_DIR / "kis_token.json"
_PAUSE = 0.12  # seconds between calls (KIS real-account limit ~20 req/s)

# Index codes for the daily index-chart endpoint (FID_COND_MRKT_DIV_CODE = "U").
INDEX_CODES = {"kospi": "0001", "kosdaq": "1001"}


def kis_available() -> bool:
    return bool(config.KIS_APP_KEY and config.KIS_APP_SECRET)


# ------------------------------------------------------------------ token
def _issue_token() -> str | None:
    try:
        resp = requests.post(
            f"{_BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": config.KIS_APP_KEY,
                "appsecret": config.KIS_APP_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
    except Exception as exc:  # noqa: BLE001
        log.error("KIS token issue failed: %s", exc)
        return None

    _TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        # 10-minute safety margin, mirroring kis_collector.py
        "expires_at": time.time() + int(data.get("expires_in", 86400)) - 600,
    }), encoding="utf-8")
    log.info("KIS access token issued.")
    return token


def _get_token() -> str | None:
    if not kis_available():
        return None
    if _TOKEN_CACHE.exists():
        try:
            cache = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
            if time.time() < cache.get("expires_at", 0):
                return cache["access_token"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return _issue_token()


def _headers(token: str, tr_id: str) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": config.KIS_APP_KEY,
        "appsecret": config.KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }


# ------------------------------------------------------------------ stocks
def _daily_candles(token: str, stock_code: str, days_back: int = 200) -> list[dict]:
    """Daily OHLCV bars for one 6-digit code, oldest first (max 100 bars)."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days_back)
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",  # adjusted prices
    }
    resp = requests.get(
        f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        headers=_headers(token, "FHKST03010100"), params=params, timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("rt_cd") != "0":
        log.warning("KIS daily %s failed: %s %s", stock_code,
                    data.get("msg_cd"), data.get("msg1"))
        return []

    bars = []
    for row in data.get("output2") or []:
        d = (row.get("stck_bsop_date") or "").strip()
        if len(d) != 8:
            continue
        try:
            bars.append({
                "date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
                "open": float(row["stck_oprc"]),
                "high": float(row["stck_hgpr"]),
                "low": float(row["stck_lwpr"]),
                "close": float(row["stck_clpr"]),
                "volume": int(row.get("acml_vol") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b["date"])
    return bars


def fetch_index_daily(index_key: str, days_back: int = 200) -> list[dict]:
    """Daily bars for a KOSPI/KOSDAQ index ('kospi' | 'kosdaq'), oldest first."""
    token = _get_token()
    code = INDEX_CODES.get(index_key)
    if not token or not code:
        return []
    end = dt.date.today()
    start = end - dt.timedelta(days=days_back)
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
    }
    try:
        resp = requests.get(
            f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            headers=_headers(token, "FHKUP03500100"), params=params, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("KIS index %s fetch failed: %s", index_key, exc)
        return []
    if data.get("rt_cd") != "0":
        log.warning("KIS index %s failed: %s %s", index_key,
                    data.get("msg_cd"), data.get("msg1"))
        return []

    bars = []
    for row in data.get("output2") or []:
        d = (row.get("stck_bsop_date") or "").strip()
        if len(d) != 8:
            continue
        try:
            bars.append({
                "date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
                "close": float(row["bstp_nmix_prpr"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b["date"])
    return bars


def fetch_kr_prices_kis(tickers: list[str], benchmark: str = "^KS11") -> pd.DataFrame:
    """OHLCV DataFrame for '.KS' tickers + the KOSPI benchmark, via KIS.

    Same long format as fetch.prices.download_prices (ticker/date/open/high/low/
    close/volume) so the scoring pipeline is unchanged. Empty DataFrame when keys
    are missing or every call fails — callers then fall back to yfinance.
    """
    token = _get_token()
    if not token:
        log.warning("KIS keys missing/invalid; KIS price fetch skipped.")
        return pd.DataFrame()

    rows: list[dict] = []
    for i, tk in enumerate(tickers, 1):
        code = tk.split(".")[0]
        if not (code.isdigit() and len(code) == 6):
            log.debug("KIS: skipping non-KRX ticker %s", tk)
            continue
        try:
            for bar in _daily_candles(token, code):
                rows.append({"ticker": tk, **bar})
        except Exception as exc:  # noqa: BLE001
            log.warning("KIS daily %s failed: %s", tk, exc)
        if i % 10 == 0:
            log.info("KIS prices %d / %d", i, len(tickers))
        time.sleep(_PAUSE)

    # Benchmark rows from the KOSPI index so relative strength keeps working.
    for bar in fetch_index_daily("kospi"):
        rows.append({"ticker": benchmark, "date": bar["date"], "open": bar["close"],
                     "high": bar["close"], "low": bar["close"],
                     "close": bar["close"], "volume": 0})

    if not rows:
        log.warning("KIS returned no KR price data.")
        return pd.DataFrame()

    prices = pd.DataFrame(rows)
    csv_path = config.RAW_DIR / "kr_prices.csv"
    prices.to_csv(csv_path, index=False)
    n_tickers = prices["ticker"].nunique()
    log.info("KIS: saved %d rows for %d tickers -> %s", len(prices), n_tickers, csv_path)
    return prices
