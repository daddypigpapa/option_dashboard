"""Local API-key store: read/write keys to a plaintext JSON file.

Keys entered in the frontend dashboard are persisted to ``keys.json`` (gitignored)
and read back by ``config.py`` with priority over environment variables. This is a
deliberate, simple local-only design per the project requirement — the file is
NOT encrypted, so it must never be committed or shared.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
KEYS_PATH = ROOT_DIR / "keys.json"

# Secret fields are masked when read back to the UI; provider fields are plain.
SECRET_FIELDS = [
    "FRED_API_KEY",
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPTIONS_FLOW_API_KEY",
    "ETF_FLOW_API_KEY",
]
PLAIN_FIELDS = [
    "OPTIONS_FLOW_PROVIDER",
    "ETF_FLOW_PROVIDER",
    "CLAUDE_MODEL",
    "GEMINI_MODEL",
]
ALL_FIELDS = SECRET_FIELDS + PLAIN_FIELDS


def load_keys() -> dict:
    """Return the saved key dict, or {} if no file / unreadable."""
    if not KEYS_PATH.exists():
        return {}
    try:
        data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_keys(updates: dict) -> dict:
    """Merge ``updates`` into the stored keys and persist. Returns the merged dict.

    Only recognized fields are stored. Blank/whitespace values clear that field.
    """
    data = load_keys()
    for field in ALL_FIELDS:
        if field in updates:
            val = (updates.get(field) or "").strip()
            if val:
                data[field] = val
            else:
                data.pop(field, None)
    KEYS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * 4 + value[-4:]


def status() -> dict:
    """Safe-to-display status: secrets masked, providers/models shown plain."""
    data = load_keys()
    out: dict[str, dict] = {}
    for field in SECRET_FIELDS:
        val = data.get(field, "")
        out[field] = {"set": bool(val), "hint": _mask(val)}
    for field in PLAIN_FIELDS:
        val = data.get(field, "")
        out[field] = {"set": bool(val), "value": val}
    return out
