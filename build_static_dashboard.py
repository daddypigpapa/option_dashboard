import math
import os
import json
import logging
from datetime import date
from sqlalchemy import desc

from database import SessionLocal, OptionSnapshot, StockHistory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StaticBuilder")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def calculate_bs_gamma(S, K, T, r, sigma):
    """
    가상의 기초자산 가격 S에 대해 블랙-숄즈 감마 계산
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        pdf_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return pdf_d1 / (S * sigma * math.sqrt(T))
    except Exception:
        return 0.0

def calculate_gamma_flip_price(spot_price, option_recs, r=0.045):
    """
    기초자산의 가격을 spot_price 기준 -20% ~ +20% 가상 순회하며 GEX 총합이 0이 되는 지점을 시뮬레이션
    """
    if not option_recs or spot_price <= 0:
        return None
    
    steps = 100
    s_min = spot_price * 0.8
    s_max = spot_price * 1.2
    
    s_vals = [s_min + (s_max - s_min) * i / (steps - 1) for i in range(steps)]
    gex_vals = []
    
    for s_hyp in s_vals:
        total_gex_hyp = 0.0
        for o in option_recs:
            T = max(o.dte, 0.5) / 365.0  # 극단적 0 나누기 방지를 위해 최소 0.5일 DTE 적용
            iv = o.implied_volatility if (o.implied_volatility and o.implied_volatility > 0) else 0.2
            
            gamma_hyp = calculate_bs_gamma(s_hyp, o.strike, T, r, iv)
            sign = 1.0 if o.option_type == 'call' else -1.0
            # Dollar GEX = Gamma * OI * 100 * S^2 * 0.01 = Gamma * OI * S^2
            gex_hyp = sign * gamma_hyp * (o.open_interest or 0) * (s_hyp ** 2)
            total_gex_hyp += gex_hyp
        gex_vals.append(total_gex_hyp)
        
    for i in range(len(s_vals) - 1):
        g1 = gex_vals[i]
        g2 = gex_vals[i+1]
        if g1 * g2 <= 0:
            s1, s2 = s_vals[i], s_vals[i+1]
            if g2 - g1 != 0:
                flip_price = s1 - g1 * (s2 - s1) / (g2 - g1)
                return round(flip_price, 2)
            return round((s1 + s2) / 2.0, 2)
            
    return None

def build_dashboard():
    """
    DB의 모든 최신 데이터를 수집하여 option_dashboard.html 정적 대시보드 파일을 생성합니다.
    """
    logger.info("정적 HTML 대시보드 빌드 프로세스 가동 시작...")
    db = SessionLocal()
    
    try:
        # 1. 고유 티커 목록 조회
        tickers_rec = db.query(OptionSnapshot.underlying_ticker).distinct().all()
        tickers = [t[0] for t in tickers_rec]
        
        if not tickers:
            logger.warning("DB에 저장된 티커 정보가 없어 빌드를 중단합니다. 수집기를 먼저 돌려주세요.")
            return False
            
        options_database = {}
        
        # 2. 각 티커별 최신 스냅샷 데이터 가공
        for ticker in tickers:
            # 해당 티커의 가장 최근 수집 일자 쿼리
            latest_date_rec = db.query(OptionSnapshot.collected_date)\
                .filter_by(underlying_ticker=ticker)\
                .order_by(desc(OptionSnapshot.collected_date))\
                .first()
                
            if not latest_date_rec:
                continue
                
            collected_date = latest_date_rec[0]
            
            # 해당 수집일자의 주가 일봉 로드
            stock_recs = db.query(StockHistory).filter_by(
                underlying_ticker=ticker,
                collected_date=collected_date
            ).order_by(StockHistory.time).all()
            
            # 일봉 차트용: DB에 일봉(YYYY-MM-DD)과 당일 분봉(YYYY-MM-DD HH:MM:SS)이
            # 섞여 들어올 수 있으므로 '날짜' 기준으로 그룹화하여 하루 1개 OHLC 봉으로 정규화한다.
            from collections import OrderedDict
            by_date = OrderedDict()
            for sh in stock_recs:
                date_part = sh.time.split(' ')[0]  # 'YYYY-MM-DD'
                has_time = ' ' in sh.time
                slot = by_date.setdefault(date_part, {"daily": None, "intra": []})
                if has_time:
                    slot["intra"].append(sh)
                else:
                    slot["daily"] = sh

            stock_history = []
            for date_part in sorted(by_date.keys()):
                slot = by_date[date_part]
                if slot["daily"] is not None:
                    # 정식 일봉 행이 있으면 그대로 사용
                    sh = slot["daily"]
                    o, h, l, cl, v = sh.open, sh.high, sh.low, sh.close, sh.volume
                else:
                    # 분봉만 있는 날짜는 일봉으로 집계 (시:첫봉 / 종:막봉 / 고:max / 저:min / 거래량:합)
                    bars = sorted(slot["intra"], key=lambda x: x.time)
                    o = bars[0].open
                    cl = bars[-1].close
                    h = max(b.high for b in bars)
                    l = min(b.low for b in bars)
                    v = sum((b.volume or 0) for b in bars)

                stock_history.append({
                    "time": date_part,  # 항상 YYYY-MM-DD
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(l, 2),
                    "close": round(cl, 2),
                    "volume": v
                })
                
            # 해당 수집일자의 옵션 데이터 로드
            option_recs = db.query(OptionSnapshot).filter_by(
                underlying_ticker=ticker,
                collected_date=collected_date
            ).order_by(OptionSnapshot.strike).all()
            
            if not option_recs:
                continue
                
            spot_price = round(option_recs[0].spot_price, 2)
            
            # 만기일 리스트 추출 및 만기별 데이터 그룹화
            expirations_set = sorted(list(set(str(o.expiration_date) for o in option_recs)))
            
            options_by_expiry = {}
            for exp in expirations_set:
                options_by_expiry[exp] = []
                
            # GEX / DEX 집계용 변수들
            total_gex = 0.0
            total_dex = 0.0
            call_gex_by_strike = {}
            put_gex_by_strike = {}
            
            for o in option_recs:
                exp_str = str(o.expiration_date)
                
                # 데이터 정밀도 절삭 및 Null 처리
                lp_val = round(o.last_price, 2) if o.last_price is not None else None
                b_val = round(o.bid, 2) if o.bid is not None else None
                a_val = round(o.ask, 2) if o.ask is not None else None
                iv_val = round(o.implied_volatility, 4) if o.implied_volatility is not None else None
                d_val = round(o.delta, 4) if o.delta is not None else None
                g_val = round(o.gamma, 6) if o.gamma is not None else None
                v_val = round(o.vega, 4) if o.vega is not None else None
                th_val = round(o.theta, 4) if o.theta is not None else None
                
                # 1. 개별 옵션 GEX, DEX 계산
                # GEX (Dollar Gamma Exposure) = sign * gamma * OI * 100 * S^2 * 0.01 = sign * gamma * OI * S^2
                # DEX (Dollar Delta Exposure) = delta * OI * 100 * S
                oi_val = o.open_interest or 0
                sign = 1.0 if o.option_type == "call" else -1.0
                
                opt_gex = sign * (g_val or 0.0) * oi_val * (spot_price ** 2)
                opt_dex = (d_val or 0.0) * oi_val * 100.0 * spot_price
                
                total_gex += opt_gex
                total_dex += opt_dex
                
                # 행사가별 감마 누적 (Walls 연산용)
                strike_rounded = round(o.strike, 2)
                if o.option_type == "call":
                    call_gex_by_strike[strike_rounded] = call_gex_by_strike.get(strike_rounded, 0.0) + opt_gex
                else:
                    put_gex_by_strike[strike_rounded] = put_gex_by_strike.get(strike_rounded, 0.0) + opt_gex
                
                # 가로막대 매물대 구축에 쓰이지 않는 dte 등은 데이터 주입에서 과감히 제외
                options_by_expiry[exp_str].append({
                    "s": o.option_symbol,   # s: option_symbol
                    "t": o.option_type,     # t: option_type
                    "k": round(o.strike, 2),# k: strike
                    "lp": lp_val,           # lp: last_price
                    "b": b_val,             # b: bid
                    "a": a_val,             # a: ask
                    "vo": o.volume or 0,    # vo: volume
                    "o": oi_val,            # o: open_interest
                    "iv": iv_val,           # iv: implied_volatility
                    "d": d_val,             # d: delta
                    "g": g_val,             # g: gamma
                    "v": v_val,             # v: vega
                    "th": th_val,           # th: theta
                    "gex": round(opt_gex, 2), # gex: gamma exposure
                    "dex": round(opt_dex, 2)  # dex: delta exposure
                })
                
            # 전체 메트릭 계산
            calls = [o for o in option_recs if o.option_type == 'call']
            puts = [o for o in option_recs if o.option_type == 'put']
            total_call_oi = sum(c.open_interest or 0 for c in calls)
            total_put_oi = sum(p.open_interest or 0 for p in puts)
            total_oi = total_call_oi + total_put_oi
            pcr_oi = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0.0
            
            # Call Wall, Put Wall 연산 (가장 노출이 큰 Strike)
            call_wall = max(call_gex_by_strike, key=call_gex_by_strike.get) if call_gex_by_strike else None
            put_wall = min(put_gex_by_strike, key=put_gex_by_strike.get) if put_gex_by_strike else None
            
            # Gamma Flip 가격 시뮬레이션 산출
            gamma_flip_price = calculate_gamma_flip_price(spot_price, option_recs)
            
            options_database[ticker] = {
                "spot_price": spot_price,
                "collected_date": str(collected_date),
                "total_oi": total_oi,
                "pcr_oi": pcr_oi,
                "net_gex": round(total_gex, 2),
                "net_dex": round(total_dex, 2),
                "call_wall": call_wall,
                "put_wall": put_wall,
                "gamma_flip_price": gamma_flip_price,
                "expirations": expirations_set,
                "stock_history": stock_history,
                "options": options_by_expiry
            }
            logger.info(f" -> [{ticker}] 데이터 직렬화 완료 (만기일수: {len(expirations_set)}개)")
            
        # 3. 티커별 옵션 데이터를 분리 JS 파일로 저장 (지연 로딩용)
        data_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(data_dir, exist_ok=True)

        meta_database = {}  # HTML 인라인용 요약 데이터 (options 제외)
        for ticker, info in options_database.items():
            # options 키를 별도 JS 파일로 분리 저장
            options_payload = json.dumps(info["options"], ensure_ascii=False, separators=(',', ':'))
            js_path = os.path.join(data_dir, f"{ticker}_options.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(f"window._etfOptions_{ticker}={options_payload};")
            logger.info(f" -> [{ticker}] 옵션 데이터 분리 저장: {js_path} ({os.path.getsize(js_path)//1024}KB)")

            # HTML 인라인 페이로드에는 options 제외
            meta_database[ticker] = {k: v for k, v in info.items() if k != "options"}

        # 4. 템플릿 읽기 및 요약 메타데이터 주입
        template_path = os.path.join(BASE_DIR, "index_template.html")
        if not os.path.exists(template_path):
            logger.error("index_template.html 파일을 찾을 수 없어 빌드를 취소합니다.")
            return False

        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # 요약 메타데이터만 인라인 주입 (options 미포함으로 크기 대폭 절감)
        json_payload = json.dumps(meta_database, ensure_ascii=False, indent=2)
        final_html = template_content.replace("/*DATA_PAYLOAD_PLACEHOLDER*/", json_payload)

        # 5. 정적 대시보드 내보내기
        output_path = os.path.join(BASE_DIR, "option_dashboard.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_html)

        html_size_kb = os.path.getsize(output_path) // 1024
        logger.info(f"★ 정적 HTML 대시보드 빌드 성공! 생성파일: {output_path} ({html_size_kb}KB)")
        return True
        
    except Exception as e:
        logger.error(f"대시보드 빌드 중 에러 발생: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    build_dashboard()
