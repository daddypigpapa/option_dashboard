"""
한국투자증권(KIS) OpenAPI 기반 한국 시장 수집기.

동작 조건
- kis_config.json 에 app_key / app_secret 입력 시 즉시 동작 (kis_config.template.json 참고).
- 키가 없으면 KISConfigError 를 발생시켜 러너(kr_collect.py)가 친절한 안내를 출력한다.

구현 범위
- 접근 토큰 발급/캐시 (kis_token.json, 만료 자동 갱신. KIS는 토큰 발급 횟수 제한이 있어 캐시 필수)
- 국내주식/ETF 일봉 조회 (기간별시세, tr_id: FHKST03010100)
- KRX 주식선물옵션 종목마스터(fo_stk_code.mst) 다운로드/파싱 → 옵션 상장 기초자산 판별
- 개별주식옵션 체인 시세 수집 (선물옵션시세 tr_id: FHMIF10000000, 시장구분 'JO')
  ※ 2026-07 실측: KRX 개별주식옵션은 전 종목·전 행사가에서 가격/미결제약정이 0으로 수신됨
    (K200 지수옵션은 동일 계열 API에서 정상 수신 → 권한 문제 아님, 시장 무거래 상태).
    따라서 유효 데이터(가격>0 또는 OI>0)가 있는 행만 적재하며, 시장이 살아나면 자동 반영된다.
"""

import io
import os
import re
import json
import time
import zipfile
import logging
from datetime import date, datetime, timedelta

import requests

from config import KIS_CONFIG_PATH, BASE_DIR

logger = logging.getLogger("KISCollector")

# 주식선물옵션 종목마스터 (KIS 공식 배포)
STOCK_FO_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_stk_code.mst.zip"
OPTION_UNIVERSE_CACHE = os.path.join(BASE_DIR, "kr_option_universe.json")

TOKEN_CACHE_PATH = os.path.join(BASE_DIR, "kis_token.json")

BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"


class KISConfigError(Exception):
    """kis_config.json 미설정/키 누락 시 발생."""


def load_kis_config():
    """kis_config.json 로드. 키가 비어있으면 KISConfigError."""
    if not os.path.exists(KIS_CONFIG_PATH):
        raise KISConfigError(
            "kis_config.json 이 없습니다. kis_config.template.json 을 복사해 "
            "앱키/시크릿을 입력하세요. (발급: https://apiportal.koreainvestment.com)"
        )
    with open(KIS_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    app_key = (cfg.get("app_key") or "").strip()
    app_secret = (cfg.get("app_secret") or "").strip()
    if not app_key or not app_secret or "입력" in app_key:
        raise KISConfigError("kis_config.json 의 app_key / app_secret 이 비어 있습니다.")
    return {
        "app_key": app_key,
        "app_secret": app_secret,
        "base_url": BASE_URL_PAPER if cfg.get("is_paper") else BASE_URL_REAL,
    }


def _issue_token(cfg):
    """접근 토큰 신규 발급 (POST /oauth2/tokenP)."""
    url = f"{cfg['base_url']}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": cfg["app_key"],
        "appsecret": cfg["app_secret"],
    }
    resp = requests.post(url, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 86400))
    cache = {
        "access_token": token,
        "expires_at": time.time() + expires_in - 600,  # 10분 여유
        "base_url": cfg["base_url"],
    }
    with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    logger.info("KIS 접근 토큰 신규 발급 완료 (유효 %d초)", expires_in)
    return token


def get_access_token(cfg):
    """캐시된 토큰이 유효하면 재사용, 아니면 신규 발급."""
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("base_url") == cfg["base_url"] and time.time() < cache.get("expires_at", 0):
                return cache["access_token"]
        except Exception:
            pass
    return _issue_token(cfg)


def _api_headers(cfg, token, tr_id):
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": cfg["app_key"],
        "appsecret": cfg["app_secret"],
        "tr_id": tr_id,
        "custtype": "P",  # 개인
    }


def get_daily_candles(cfg, token, stock_code, months=3):
    """
    국내주식/ETF 일봉 조회 (기간별시세: 일/주/월/년).
    tr_id FHKST03010100, 최대 100건 반환.

    반환: (current_price: float|None, candles: list[dict])
      candles = [{"time": "YYYY-MM-DD", "open":.., "high":.., "low":.., "close":.., "volume":..}, ...] (오름차순)
    """
    end = date.today()
    start = end - timedelta(days=int(months * 31))
    url = f"{cfg['base_url']}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",          # 주식/ETF/ETN
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",             # 일봉
        "FID_ORG_ADJ_PRC": "0",                 # 수정주가 반영
    }
    headers = _api_headers(cfg, token, "FHKST03010100")
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("rt_cd") != "0":
        logger.error("[%s] KIS 일봉 조회 실패: %s %s", stock_code, data.get("msg_cd"), data.get("msg1"))
        return None, []

    # output1: 현재가 요약, output2: 일봉 배열 (최신순)
    out1 = data.get("output1") or {}
    current_price = None
    try:
        current_price = float(out1.get("stck_prpr"))
    except (TypeError, ValueError):
        pass

    candles = []
    for row in data.get("output2") or []:
        d = (row.get("stck_bsop_date") or "").strip()
        if len(d) != 8:
            continue
        try:
            candles.append({
                "time": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
                "open": float(row["stck_oprc"]),
                "high": float(row["stck_hgpr"]),
                "low": float(row["stck_lwpr"]),
                "close": float(row["stck_clpr"]),
                "volume": int(row.get("acml_vol") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue

    candles.sort(key=lambda c: c["time"])  # 오름차순 정렬
    if current_price is None and candles:
        current_price = candles[-1]["close"]
    return current_price, candles


def get_stock_option_universe(force_refresh=False):
    """
    주식선물옵션 종목마스터를 파싱하여 옵션(콜/풋) 상장 기초자산별 계약 목록을 반환.

    반환: {기초자산코드: {"name": 기초자산명,
                          "options": [{"sc": 단축코드, "t": "C"|"P",
                                       "exp": "YYYYMM", "k": 행사가}, ...]}}
    하루 1회 캐시(kr_option_universe.json) — 마스터는 영업일 단위로 갱신됨.
    """
    today = date.today().isoformat()
    if not force_refresh and os.path.exists(OPTION_UNIVERSE_CACHE):
        try:
            with open(OPTION_UNIVERSE_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today:
                return cache["universe"]
        except Exception:
            pass

    resp = requests.get(STOCK_FO_MASTER_URL, timeout=20, verify=False)
    resp.raise_for_status()
    raw = zipfile.ZipFile(io.BytesIO(resp.content)).read("fo_stk_code.mst")

    # 고정폭이지만 종목명 길이에 따라 오프셋이 밀리므로 정규식으로 파싱
    type_pat = re.compile(r"\s([FCP])\s+(\d{6})\s")
    universe = {}
    for ln in raw.split(b"\n"):
        if len(ln) < 50:
            continue
        s = ln.decode("euc-kr", errors="replace")
        m = type_pat.search(s[22:60])
        if not m or m.group(1) == "F":
            continue  # 선물 행 제외, 옵션(C/P)만
        # 기초자산 코드: 행 후반부의 마지막 '6자리 숫자+공백' 매치
        codes = list(re.finditer(r"(\d{6})\s", s[40:]))
        if not codes:
            continue
        ucode = codes[-1].group(1)
        uname = s[40:][codes[-1].end():].strip()
        strike_m = re.search(r"([\d,]+)\(", s)
        if not strike_m:
            continue
        try:
            strike = float(strike_m.group(1).replace(",", ""))
        except ValueError:
            continue
        d = universe.setdefault(ucode, {"name": uname, "options": []})
        d["options"].append({
            "sc": s[0:10].strip(),
            "t": m.group(1),
            "exp": m.group(2),
            "k": strike,
        })

    with open(OPTION_UNIVERSE_CACHE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "universe": universe}, f, ensure_ascii=False)
    logger.info("주식옵션 종목마스터 갱신: 옵션 상장 기초자산 %d개", len(universe))
    return universe


def expiry_from_ym(ym):
    """주식옵션 만기일 = 해당 월의 두 번째 목요일 (KOSPI200 옵션과 동일)."""
    year, month = int(ym[:4]), int(ym[4:6])
    d = date(year, month, 1)
    # 첫 목요일(weekday 3)까지 이동 후 +7일
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=7)


def get_option_chain(cfg, token, stock_code, spot_price=None, max_dte=90,
                     strike_band=0.30, request_delay=0.06):
    """
    개별주식옵션 체인 시세 수집 → database.OptionSnapshot 리스트 반환.

    - 종목마스터에서 해당 기초자산의 옵션 계약을 찾고 (미상장이면 빈 목록)
    - 잔존만기 max_dte 이내 + 행사가 spot ±strike_band 이내로 추려
    - 계약별 시세(FHMIF10000000/'JO')를 조회, 유효 데이터(가격>0 또는 OI>0)만 적재한다.

    ★ 종목코드 주의: 시세 API는 마스터 단축코드의 첫 글자(타입 프리픽스, 콜 '5'/풋 '6')를
      제거한 9자리 코드를 요구한다 (예: '5B11607101' → 'B11607101').
      원형 10자리로 조회하면 rt_cd=0 이지만 모든 값이 0인 빈 템플릿이 반환된다 (실측).
    ★ 그릭스 주의: KIS 주식옵션 응답의 delta/gama 필드는 신뢰 불가(델타 1.0/0.0 고정 등)라서
      미국 파이프라인과 동일하게 자체 블랙-숄즈 연산(greeks.calculate_greeks)을 사용한다.
      IV(hts_ints_vltl)는 주식옵션은 소수(0.96=96%), 지수옵션은 퍼센트(85.85) 단위로 오므로 정규화한다.
    """
    from database import OptionSnapshot  # 순환 임포트 방지용 지연 임포트
    from greeks import calculate_greeks

    universe = get_stock_option_universe()
    info = universe.get(stock_code)
    if not info:
        return []  # 옵션 미상장 기초자산

    collected = date.today()
    targets = []
    for o in info["options"]:
        exp_d = expiry_from_ym(o["exp"])
        dte = (exp_d - collected).days
        if dte <= 0 or dte > max_dte:
            continue
        if spot_price and strike_band:
            lo, hi = spot_price * (1 - strike_band), spot_price * (1 + strike_band)
            if not (lo <= o["k"] <= hi):
                continue
        targets.append((o, exp_d, dte))

    if not targets:
        return []

    url = f"{cfg['base_url']}/uapi/domestic-futureoption/v1/quotations/inquire-price"
    r_riskfree = 0.03  # 한국 무위험 이자율 근사
    snapshots = []
    for o, exp_d, dte in targets:
        quote_code = o["sc"][1:]  # 타입 프리픽스 제거 (★ 필수)
        try:
            resp = requests.get(
                url,
                headers=_api_headers(cfg, token, "FHMIF10000000"),
                params={"FID_COND_MRKT_DIV_CODE": "JO", "FID_INPUT_ISCD": quote_code},
                timeout=10,
            )
            body = resp.json()
            out = body.get("output1") or {}
            price = float(out.get("futs_prpr") or 0)
            oi = int(out.get("hts_otst_stpl_qty") or 0)
            # 가격/미결제 모두 0인 계약(호가·거래 없음)은 스킵
            if price <= 0 and oi <= 0:
                continue

            # IV 단위 정규화: 3 초과면 퍼센트 단위로 보고 소수로 환산
            iv = float(out.get("hts_ints_vltl") or 0)
            if iv > 3:
                iv /= 100.0

            opt_type = "call" if o["t"] == "C" else "put"
            g = calculate_greeks(
                flag=opt_type,
                S=spot_price or 0.0,
                K=o["k"],
                T=dte / 365.0,
                r=r_riskfree,
                sigma=iv if iv > 0 else 0.3,
            )

            snapshots.append(OptionSnapshot(
                collected_date=collected,
                underlying_ticker=stock_code,
                spot_price=spot_price or 0.0,
                option_symbol=quote_code,
                expiration_date=exp_d,
                dte=dte,
                strike=o["k"],
                option_type=opt_type,
                last_price=price if price > 0 else None,
                bid=None,
                ask=None,
                volume=int(out.get("acml_vol") or 0),
                open_interest=oi,
                implied_volatility=iv,
                delta=g["delta"],
                gamma=g["gamma"],
                vega=g["vega"],
                theta=g["theta"],
            ))
        except Exception as e:
            logger.debug("[%s] 옵션 %s 시세 조회 실패: %s", stock_code, quote_code, e)
        time.sleep(request_delay)

    return snapshots
