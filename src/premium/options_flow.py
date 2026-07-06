"""Part 2: institutional options flow -> long / neutral / short classification.

This data is NOT available from Yahoo/FRED. It requires a paid provider
(Unusual Whales, CBOE LiveVol, Polygon options, etc.). This module is an *adapter*:
plug your provider + key into ``_fetch_raw_flow`` and the rest of the pipeline
consumes a normalized result. With no key configured it returns an empty result
so the pipeline keeps running (the field is simply marked unavailable downstream).

Normalized output per ticker:
    {ticker, net_premium, call_put_ratio, status, color}
where status in {"long","neutral","short"} and color in {"green","orange","red"}.
"""
from __future__ import annotations

import json
import logging

import config

log = logging.getLogger(__name__)

_STATUS_COLOR = {"long": "green", "neutral": "orange", "short": "red"}


def is_enabled() -> bool:
    return bool(config.OPTIONS_FLOW_API_KEY)


def _classify(net_premium: float, call_put_ratio: float) -> str:
    """Map raw flow metrics to a directional status.

    Tune these thresholds to your provider's scale. Defaults assume net_premium
    in USD (positive = net call buying) and a standard call/put premium ratio.
    """
    if net_premium > 0 and call_put_ratio >= 1.2:
        return "long"
    if net_premium < 0 and call_put_ratio <= 0.8:
        return "short"
    return "neutral"


def _fetch_raw_flow(tickers: list[str]) -> list[dict]:
    """PROVIDER INTEGRATION POINT.

    Implement the real HTTP call here for OPTIONS_FLOW_PROVIDER. Must return a
    list of dicts with at least: ticker, net_premium, call_put_ratio.

    Example skeleton for Unusual Whales-style REST:

        import requests
        headers = {"Authorization": f"Bearer {config.OPTIONS_FLOW_API_KEY}"}
        out = []
        for tk in tickers:
            r = requests.get(
                f"https://api.unusualwhales.com/api/stock/{tk}/flow",
                headers=headers, timeout=30,
            )
            d = r.json()
            out.append({
                "ticker": tk,
                "net_premium": d["net_premium"],
                "call_put_ratio": d["call_put_ratio"],
            })
        return out
    """
    raise NotImplementedError(
        f"Options-flow provider '{config.OPTIONS_FLOW_PROVIDER}' not wired up. "
        "Implement _fetch_raw_flow() with your paid API."
    )


def fetch_options_flow(tickers: list[str]) -> dict[str, dict]:
    """Return {ticker: normalized_flow}. Empty dict if no provider configured."""
    if not is_enabled():
        log.warning("OPTIONS_FLOW_API_KEY missing; options flow skipped.")
        return {}

    try:
        raw = _fetch_raw_flow(tickers)
    except NotImplementedError as exc:
        log.warning("%s", exc)
        return {}
    except Exception as exc:  # noqa: BLE001
        log.error("Options flow provider error: %s", exc)
        return {}

    result = {}
    for row in raw:
        status = _classify(row.get("net_premium", 0), row.get("call_put_ratio", 1.0))
        result[row["ticker"]] = {
            "ticker": row["ticker"],
            "net_premium": row.get("net_premium"),
            "call_put_ratio": row.get("call_put_ratio"),
            "status": status,
            "color": _STATUS_COLOR[status],
        }

    (config.RAW_DIR / "options_flow.json").write_text(
        json.dumps(list(result.values()), indent=2), encoding="utf-8"
    )
    log.info("Options flow classified for %d tickers", len(result))
    return result
