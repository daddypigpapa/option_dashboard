"""Central configuration. Reads from environment / .env file.

All other modules import from here so paths and keys live in one place.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional at runtime; env vars still work.
    pass

import keystore

# Keys saved from the frontend dashboard take priority over environment vars.
_FILE_KEYS = keystore.load_keys()


def _key(name: str, default: str = "") -> str:
    """Resolve a key: keys.json first, then env var, then default."""
    return (_FILE_KEYS.get(name) or os.getenv(name, "") or default).strip()


# ---------------------------------------------------------------- paths
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"           # downloaded source data (prices, indicators)
ANALYSIS_DIR = DATA_DIR / "analysis"  # scored / derived data
OUTPUT_DIR = DATA_DIR / "output"      # final frontend-facing JSON

for _d in (RAW_DIR, ANALYSIS_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- keys
FRED_API_KEY = _key("FRED_API_KEY")
DART_API_KEY = _key("DART_API_KEY")  # opendart.fss.or.kr — Korean disclosures
# 한국투자증권 OpenAPI (apiportal.koreainvestment.com) — KR market refresh
KIS_APP_KEY = _key("KIS_APP_KEY")
KIS_APP_SECRET = _key("KIS_APP_SECRET")
ANTHROPIC_API_KEY = _key("ANTHROPIC_API_KEY")
GEMINI_API_KEY = _key("GEMINI_API_KEY")

OPTIONS_FLOW_API_KEY = _key("OPTIONS_FLOW_API_KEY")
OPTIONS_FLOW_PROVIDER = _key("OPTIONS_FLOW_PROVIDER", "unusualwhales")
ETF_FLOW_API_KEY = _key("ETF_FLOW_API_KEY")
ETF_FLOW_PROVIDER = _key("ETF_FLOW_PROVIDER")


# ---------------------------------------------------------------- models
# Latest Claude model id (see claude-api reference). Override via dashboard/env.
CLAUDE_MODEL = _key("CLAUDE_MODEL", "claude-opus-4-8")
# Google AI Studio Gemini model.
GEMINI_MODEL = _key("GEMINI_MODEL", "gemini-2.5-pro")


# ---------------------------------------------------------------- tuning
def _int_or_none(name: str):
    val = os.getenv(name, "").strip()
    return int(val) if val.isdigit() else None


MAX_TICKERS = _int_or_none("MAX_TICKERS")
UNIVERSE_OVERRIDE = [
    t.strip().upper() for t in os.getenv("UNIVERSE_OVERRIDE", "").split(",") if t.strip()
]

# How much history to download for each stock.
PRICE_HISTORY_PERIOD = os.getenv("PRICE_HISTORY_PERIOD", "1y")

# Top-N smart money picks to surface for AI briefing.
TOP_N_PICKS = int(os.getenv("TOP_N_PICKS", "20"))
