"""Part 2: ETF fund flows -> Top Inflow / Top Outflow.

NOT available from Yahoo/FRED. Requires a paid provider (ETF.com, FactSet,
State Street/SSGA, etc.). Adapter pattern, same as options_flow: wire your
provider into ``_fetch_raw_flows``; with no key the feature is skipped.

Normalized output: list of {ticker, name, flow_usd, flow_pct_aum} sorted so the
pipeline can slice top inflow (largest positive) and top outflow (largest negative).
Examples in the spec: Russell index ETFs (IWM), Nasdaq inverse ETFs (PSQ/SQQQ).
"""
from __future__ import annotations

import json
import logging

import config

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(config.ETF_FLOW_API_KEY)


def _fetch_raw_flows() -> list[dict]:
    """PROVIDER INTEGRATION POINT.

    Implement the real call for ETF_FLOW_PROVIDER. Return a list of dicts with at
    least: ticker, name, flow_usd (signed; + = inflow), flow_pct_aum (optional).
    """
    raise NotImplementedError(
        f"ETF-flow provider '{config.ETF_FLOW_PROVIDER}' not wired up. "
        "Implement _fetch_raw_flows() with your paid API."
    )


def fetch_etf_flows(top_n: int = 10) -> dict:
    """Return {'top_inflow': [...], 'top_outflow': [...], 'all': [...]}.

    Empty lists if no provider configured.
    """
    empty = {"top_inflow": [], "top_outflow": [], "all": []}
    if not is_enabled():
        log.warning("ETF_FLOW_API_KEY missing; ETF flows skipped.")
        return empty

    try:
        flows = _fetch_raw_flows()
    except NotImplementedError as exc:
        log.warning("%s", exc)
        return empty
    except Exception as exc:  # noqa: BLE001
        log.error("ETF flow provider error: %s", exc)
        return empty

    flows.sort(key=lambda f: f.get("flow_usd", 0), reverse=True)
    result = {
        "top_inflow": flows[:top_n],
        "top_outflow": list(reversed(flows[-top_n:])),
        "all": flows,
    }
    (config.RAW_DIR / "etf_flows.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    log.info("ETF flows: %d funds (top %d in/out)", len(flows), top_n)
    return result
