"""Part 3: macro analysis from ~30 indicators, by Claude AND Gemini independently.

Both models receive the same structured macro snapshot and the same prompt, so the
two summaries can be displayed side by side on the dashboard.
"""
from __future__ import annotations

import json
import logging

import pandas as pd

import config
from src.ai.clients import ClaudeClient, GeminiClient

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a macro strategist. Summarize the current US macro regime from the "
    "indicators provided. Be specific and reference the numbers. Cover: growth, "
    "inflation, rates/curve, credit & risk sentiment, and the USD. End with 2-3 "
    "key watch-items. Do not give specific trade or price-target advice."
)


def _format_macro(macro_df: pd.DataFrame, extra: dict | None) -> str:
    lines = ["Current macro indicators (latest vs previous):"]
    for _, r in macro_df.iterrows():
        lines.append(
            f"- {r['description']} [{r['series_id']}]: {r['latest']} "
            f"(prev {r['previous']}, as of {r['as_of']})"
        )
    if extra:
        lines.append("\nAdditional market indicators:")
        for k, v in extra.items():
            val = v.get("value") if isinstance(v, dict) else v
            lines.append(f"- {k}: {val}")
    return "\n".join(lines)


def run_macro_analysis(macro_df: pd.DataFrame, extra_indicators: dict | None = None) -> dict:
    """Return {'claude': str|None, 'gemini': str|None, 'inputs': str}."""
    snapshot = _format_macro(macro_df, extra_indicators)
    prompt = (
        f"{snapshot}\n\nWrite a concise (250-350 word) macro analysis of the current "
        "US economic situation based strictly on the indicators above."
    )

    claude, gemini = ClaudeClient(), GeminiClient()
    result = {
        "claude": claude.complete(prompt, system=_SYSTEM) if claude.available else None,
        "gemini": gemini.complete(prompt, system=_SYSTEM) if gemini.available else None,
        "inputs": snapshot,
    }
    if not claude.available:
        log.warning("Claude unavailable for macro analysis.")
    if not gemini.available:
        log.warning("Gemini unavailable for macro analysis.")

    (config.ANALYSIS_DIR / "macro_analysis.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    log.info("Macro analysis complete (claude=%s, gemini=%s)",
             bool(result["claude"]), bool(result["gemini"]))
    return result
