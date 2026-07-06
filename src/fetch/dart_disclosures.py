"""Part 1: recent corporate disclosures from DART (전자공시, opendart.fss.or.kr).

DART is the Korean regulator's official filing system. We pull the most recent
filings for a watchlist of major Korean companies (Samsung Electronics, SK Hynix,
etc.) so the dashboard can show what those issuers have just disclosed.

Two-step OpenDART flow, both free with a DART API key entered on the dashboard:
  1. ``corpCode.xml`` — a one-time zip mapping 6-digit stock codes -> 8-digit
     DART corp codes. Cached locally so we download it at most once.
  2. ``list.json`` — recent disclosure list for a given corp code.

Without a DART key the whole step is skipped gracefully (returns []), exactly like
the other optional data sources.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import zipfile
import xml.etree.ElementTree as ET

import requests

import config

log = logging.getLogger(__name__)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
# DART's own filing viewer; rcept_no opens the actual document.
_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"

_DART_DIR = config.RAW_DIR / "dart"
_CORP_MAP_PATH = _DART_DIR / "corpcode_map.json"
_OUT_PATH = config.RAW_DIR / "dart_disclosures.json"

# Watchlist of major Korean issuers by 6-digit KRX stock code.
_TARGETS: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "000270": "기아",
    "035420": "NAVER",
    "035720": "카카오",
    "068270": "셀트리온",
    "005490": "POSCO홀딩스",
    "051910": "LG화학",
    "006400": "삼성SDI",
}


def _load_corp_map(api_key: str) -> dict[str, str]:
    """Return {stock_code -> corp_code}, downloading & caching corpCode.xml once."""
    if _CORP_MAP_PATH.exists():
        try:
            return json.loads(_CORP_MAP_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # fall through and re-download

    log.info("Downloading DART corpCode map (one-time)...")
    try:
        resp = requests.get(_CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=60)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("DART corpCode download failed: %s", exc)
        return {}

    # An invalid key returns a small JSON error instead of a zip.
    if not resp.content[:2] == b"PK":
        log.warning("DART corpCode response was not a zip (check API key): %s",
                    resp.text[:200])
        return {}

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")
        root = ET.fromstring(xml_bytes)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        log.warning("DART corpCode parse failed: %s", exc)
        return {}

    mapping: dict[str, str] = {}
    for item in root.iter("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code and corp_code:  # listed companies only have a stock_code
            mapping[stock_code] = corp_code

    _DART_DIR.mkdir(parents=True, exist_ok=True)
    _CORP_MAP_PATH.write_text(json.dumps(mapping), encoding="utf-8")
    log.info("DART corpCode map cached (%d listed companies).", len(mapping))
    return mapping


def _recent_filings(api_key: str, corp_code: str, bgn: str, end: str,
                    page_count: int) -> list[dict]:
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": 1,
        "page_count": page_count,
    }
    try:
        resp = requests.get(_LIST_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("DART list fetch failed for %s: %s", corp_code, exc)
        return []

    status = data.get("status")
    if status == "013":  # "조회된 데이터가 없습니다" — no filings in range
        return []
    if status != "000":
        log.warning("DART list status %s for %s: %s", status, corp_code,
                    data.get("message"))
        return []
    return data.get("list", [])


def fetch_dart_disclosures(days_back: int = 30, per_company: int = 5) -> list[dict]:
    """Recent DART filings for the major-issuer watchlist.

    Returns a list of ``{stock_code, corp_name, filings: [...]}`` and writes it to
    ``data/raw/dart_disclosures.json``. Empty list (and a saved empty file) when no
    DART key is configured.
    """
    if not config.DART_API_KEY:
        log.warning("DART_API_KEY missing; DART disclosures skipped.")
        _OUT_PATH.write_text("[]", encoding="utf-8")
        return []

    corp_map = _load_corp_map(config.DART_API_KEY)
    if not corp_map:
        log.warning("DART corp map empty; cannot fetch disclosures.")
        _OUT_PATH.write_text("[]", encoding="utf-8")
        return []

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=days_back)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    results: list[dict] = []
    for stock_code, name in _TARGETS.items():
        corp_code = corp_map.get(stock_code)
        if not corp_code:
            log.debug("No DART corp_code for %s (%s); skipping.", stock_code, name)
            continue

        filings = []
        for f in _recent_filings(config.DART_API_KEY, corp_code, bgn, end, per_company):
            rcept_no = f.get("rcept_no", "")
            filings.append({
                "report_nm": f.get("report_nm", ""),
                "rcept_dt": f.get("rcept_dt", ""),
                "flr_nm": f.get("flr_nm", ""),       # filer
                "rcept_no": rcept_no,
                "url": _VIEWER_URL.format(rcept_no) if rcept_no else "",
            })

        results.append({
            "stock_code": stock_code,
            "corp_name": name,
            "filings": filings,
        })

    total = sum(len(r["filings"]) for r in results)
    _OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    log.info("Saved DART disclosures for %d companies (%d filings) -> %s",
             len(results), total, _OUT_PATH)
    return results
