"""Part 3: upcoming economic calendar.

Built from the FRED *releases* API, which publishes the official future release
dates for series like CPI, payrolls, GDP, FOMC-related data, etc. This is a free,
authoritative source for "what macro data drops next". Without a FRED key it
returns an empty calendar (skipped, not faked).
"""
from __future__ import annotations

import datetime as dt
import json
import logging

import requests

import config

log = logging.getLogger(__name__)

_RELEASE_DATES = "https://api.stlouisfed.org/fred/releases/dates"

# Releases most relevant to a market dashboard (FRED release ids -> friendly name).
_KEY_RELEASES = {
    10: "Consumer Price Index (CPI)",
    50: "Employment Situation (Nonfarm Payrolls)",
    53: "Gross Domestic Product (GDP)",
    21: "Personal Income & Outlays (PCE)",
    13: "Producer Price Index (PPI)",
    9: "Advance Retail Sales",
    18: "Industrial Production",
    101: "FOMC: H.4.1 / policy-related",
}


def fetch_economic_calendar(days_ahead: int = 60) -> list[dict]:
    if not config.FRED_API_KEY:
        log.warning("FRED_API_KEY missing; economic calendar skipped.")
        return []

    today = dt.date.today()
    horizon = today + dt.timedelta(days=days_ahead)
    events: list[dict] = []

    for rid, name in _KEY_RELEASES.items():
        params = {
            "release_id": rid,
            "api_key": config.FRED_API_KEY,
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "realtime_start": today.isoformat(),
            "realtime_end": horizon.isoformat(),
        }
        try:
            resp = requests.get(_RELEASE_DATES, params=params, timeout=30)
            resp.raise_for_status()
            for d in resp.json().get("release_dates", []):
                date = d.get("date")
                if date and today.isoformat() <= date <= horizon.isoformat():
                    events.append({"date": date, "event": name, "release_id": rid})
        except Exception as exc:  # noqa: BLE001
            log.warning("Calendar release %s failed: %s", rid, exc)

    events.sort(key=lambda e: e["date"])
    path = config.RAW_DIR / "economic_calendar.json"
    path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    log.info("Saved %d upcoming events -> %s", len(events), path)
    return events
