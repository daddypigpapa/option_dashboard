# US Market Analysis Backend

Python backend that collects US equity + macro data, scores ~500 stocks on six
factors, classifies institutional flow, and produces AI (Claude + Gemini) insight
for a frontend dashboard.

> **Heads-up on data availability.** This project is honest about what free APIs
> can and cannot do. Yahoo Finance + FRED cover prices, volume, the macro
> indicators, analyst targets, and the economic calendar. **Institutional options
> flow** and **ETF fund flows** are *not* available for free — those modules are
> built as **adapters** with a clear integration point for a paid provider, and
> are **skipped gracefully** when no provider key is set.

## Pipeline

| Stage | Module | Output |
|-------|--------|--------|
| **Part 1 – Fetch** | `src/fetch/` | `data/raw/*.csv`, `*.json` |
| Universe (S&P 500) | `src/universe.py` | live Wikipedia scrape + fallback |
| Daily OHLCV (~500) | `fetch/prices.py` | `prices.csv`, `prices_latest.json` |
| 7+ market indicators | `fetch/market_indicators.py` | VIX, gold, oil, BTC, 10Y/3Y yields, DXY, USD/KRW, SKEW |
| ~30 macro series | `fetch/macro_fred.py` | `macro_indicators.csv` |
| Analyst targets + upside% | `fetch/analyst_targets.py` | `analyst_targets.csv/json` |
| Economic calendar | `fetch/economic_calendar.py` | `economic_calendar.json` (FRED release dates) |
| Korean disclosures (DART) | `fetch/dart_disclosures.py` | `dart_disclosures.json` (recent filings for major KR issuers) |
| **Part 2 – Analyze** | `src/analyze/`, `src/premium/` | `data/analysis/` |
| 6-factor scoring | `analyze/scoring.py` | `scores.csv/json` |
| Options flow (paid) | `premium/options_flow.py` | long/neutral/short → green/orange/red |
| ETF flows (paid) | `premium/etf_flows.py` | top inflow / top outflow |
| Top-10 smart-money picks | `analyze/smart_money.py` | `top_picks.json` |
| **Part 3 – AI** | `src/ai/` | `data/analysis/` |
| Per-pick company brief | `ai/stock_brief.py` | Claude |
| Macro analysis (×2) | `ai/macro_analysis.py` | Claude **and** Gemini, side by side |
| **Output** | `src/pipeline.py` | `data/output/dashboard.json` |

### The 6 scoring factors
All derived from **free** data so a score always computes:
`momentum` (3-mo return) · `trend` (vs 50/200-day MAs) · `volume_surge` (5d vs 60d
volume) · `rel_strength` (vs SPY) · `low_vol` (inverse realized vol) ·
`analyst_upside` (target mean vs price). Each is percentile-ranked 0–100 and
averaged into `composite_score`.

## Setup

> **Note:** Python **3.12 is installed** at
> `C:\Users\leejaegeon\AppData\Local\Programs\Python\Python312\python.exe`, but the
> Microsoft Store stub shadows it on PATH (plain `python` opens the Store). Use the
> full path once to create the venv, then the venv's `python` works normally.

```powershell
# from C:\Users\leejaegeon\claude\dashboard_project
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

copy .env.example .env       # then edit .env with your keys
```

### Entering keys — two options

**(A) Web dashboard (recommended).** Run the Flask app and enter keys in the
browser; they are saved to `keys.json` locally.
```powershell
python -m webapp.app        # then open http://127.0.0.1:5000
```
The dashboard lets you: enter/save all API keys, trigger the pipeline (full or
`--skip-ai`) with live log, and view results (market indicators, Top-10 picks,
Claude-vs-Gemini macro analysis, economic calendar).

> Keys are stored **plaintext** in `keys.json` (gitignored, local-only). The UI
> only ever shows a masked hint (`••••1234`), never the raw secret.

**Key resolution order:** `keys.json` (dashboard) → environment / `.env`.

**(B) `.env` file** — copy `.env.example` to `.env` and fill in:
- `FRED_API_KEY` — free: <https://fred.stlouisfed.org/docs/api/api_key.html>
- `DART_API_KEY` — free Korean disclosures: <https://opendart.fss.or.kr/> (leave blank to skip)
- `ANTHROPIC_API_KEY` — Claude
- `GEMINI_API_KEY` — Google AI Studio

### Optional (paid) keys — leave blank to skip those features
- `OPTIONS_FLOW_API_KEY` / `OPTIONS_FLOW_PROVIDER` — e.g. Unusual Whales, CBOE
- `ETF_FLOW_API_KEY` / `ETF_FLOW_PROVIDER` — e.g. ETF.com, FactSet

To turn the paid features on, implement the one marked
`PROVIDER INTEGRATION POINT` function in `premium/options_flow.py` and
`premium/etf_flows.py`.

## Run

```powershell
python main.py                # full pipeline
python main.py --skip-ai      # data + scoring only (no API spend)
python main.py -v             # verbose logging
```

Quick test on a handful of tickers without scraping all 500:
```powershell
$env:UNIVERSE_OVERRIDE="AAPL,MSFT,NVDA,AMZN,SPY"; python main.py --skip-ai
```

The frontend should read `data/output/dashboard.json`.
