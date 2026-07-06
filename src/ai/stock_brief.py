"""Part 3: AI-written basic company brief for each Top-N pick (via Claude)."""
from __future__ import annotations

import json
import logging

import config
from src.ai.clients import ClaudeClient

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are an equity research assistant. Given a ticker and quantitative factor "
    "scores, write a concise, factual company brief. Do NOT give buy/sell advice or "
    "price predictions. 3-4 sentences."
)


def _prompt(pick: dict) -> str:
    f = pick["factors"]
    name = pick.get("name")
    company_line = f"Company: {name} (ticker {pick['ticker']})\n" if name else f"Ticker: {pick['ticker']}\n"
    return (
        company_line +
        f"Composite score: {pick['composite_score']}/100 (rank {pick['rank']}).\n"
        f"Factor percentiles: momentum {f['momentum']:.0f}, trend {f['trend']:.0f}, "
        f"volume {f['volume_surge']:.0f}, relative strength {f['rel_strength']:.0f}, "
        f"low-vol {f['low_vol']:.0f}, analyst-upside {f['analyst_upside']:.0f}.\n"
        f"Analyst upside: {pick.get('upside_pct')}%. Options flow: {pick['flow_status']}.\n\n"
        "Briefly describe: (1) what this company does and its sector, "
        "(2) why these factor readings might look the way they do, in neutral terms. "
        "No investment recommendation."
    )


def write_briefs(picks: list[dict], out_name: str = "top_picks.json") -> list[dict]:
    claude = ClaudeClient()
    if not claude.available:
        log.warning("Claude unavailable; stock briefs skipped.")
        for p in picks:
            p["ai_brief"] = None
        return picks

    for p in picks:
        brief = claude.complete(_prompt(p), system=_SYSTEM, max_tokens=400)
        p["ai_brief"] = brief
        log.info("Brief written for %s", p["ticker"])

    (config.ANALYSIS_DIR / out_name).write_text(
        json.dumps(picks, indent=2), encoding="utf-8"
    )
    return picks
