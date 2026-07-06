"""
한국 시장(한국 ETF 20 + KOSPI 개별주 50) 수집 러너.

전제: kis_config.json 에 한국투자증권 OpenAPI 앱키/시크릿 입력
      (없으면 안내 메시지 출력 후 종료 — 대시보드의 한국 페이지는 빈 상태로 유지됨)

사용법
    python kr_collect.py            # 한국 ETF + KOSPI50 전체
    python kr_collect.py 005930     # 특정 종목코드만

수집 내용
- 일봉 3개월 → stock_history 테이블 (미국 파이프라인과 동일 스키마)
- 옵션 체인 → kis_collector.get_option_chain() 연동 지점 (현재 빈 목록)
- 완료 후 정적 대시보드 자동 재빌드
"""

import sys
import time
import logging
from datetime import date

from config import KR_ETFS, KOSPI50, LOG_FORMAT, LOG_LEVEL
from database import init_db, get_db_session, StockHistory
from usa_etf_option_collect import save_to_database
from build_static_dashboard import build_dashboard
from kis_collector import (KISConfigError, load_kis_config, get_access_token,
                           get_daily_candles, get_option_chain, get_stock_option_universe)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger("KRCollector")

# KIS 유량 제한(실전 초당 20건) 대비 보수적 호출 간격
REQUEST_DELAY = 0.3


def main():
    # 1. KIS 설정 확인 (키 없으면 안내 후 종료)
    try:
        cfg = load_kis_config()
    except KISConfigError as e:
        logger.error("한국투자증권 API 미설정: %s", e)
        logger.error("→ kis_config.template.json 을 kis_config.json 으로 복사하고 앱키를 입력하면 즉시 수집 가능합니다.")
        return False

    token = get_access_token(cfg)
    init_db()
    session = get_db_session()
    collected_date = date.today()

    # 2. 옵션 상장 기초자산 판별 (종목마스터 기준)
    universe = get_stock_option_universe()

    # 대상 구성:
    # - 한국 ETF 20: 주가 차트용 일봉만 수집 (KRX에 ETF 옵션 시장 없음)
    # - KOSPI 개별주: 옵션이 실제 상장된 종목만 수집 (일봉 + 옵션 체인)
    etf_targets = [(e["code"], e["name"], False) for e in KR_ETFS]
    kospi_targets = []
    skipped = []
    for s in KOSPI50:
        if s["code"] in universe:
            kospi_targets.append((s["code"], s["name"], True))
        else:
            skipped.append(s["name"])
    if skipped:
        logger.info("옵션 미상장으로 수집 제외된 KOSPI 종목 %d개: %s", len(skipped), ", ".join(skipped))

    targets = etf_targets + kospi_targets
    if len(sys.argv) > 1:
        want = set(sys.argv[1:])
        targets = [(c, n, o) for c, n, o in targets if c in want]

    logger.info("한국 시장 수집 시작: %d개 종목 (ETF %d + KOSPI 옵션상장 %d, 수집일 %s)",
                len(targets), len(etf_targets), len(kospi_targets), collected_date)

    success, failed = [], []
    total_opts = 0
    for idx, (code, name, has_options) in enumerate(targets, start=1):
        try:
            current_price, candles = get_daily_candles(cfg, token, code)
            if not candles:
                logger.warning("[%d/%d] %s(%s) 일봉 없음", idx, len(targets), name, code)
                failed.append(code)
                continue

            rows = [
                StockHistory(
                    collected_date=collected_date,
                    underlying_ticker=code,
                    time=c["time"],
                    open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                    volume=c["volume"],
                )
                for c in candles
            ]
            n = save_to_database(session, rows)

            # 옵션 상장 종목: 체인 시세 수집 (유효 데이터만 적재됨)
            opt_n = 0
            if has_options:
                option_rows = get_option_chain(cfg, token, code, spot_price=current_price)
                if option_rows:
                    opt_n = save_to_database(session, option_rows)
                    total_opts += opt_n

            logger.info("[%d/%d] %s(%s) 일봉 %d건, 옵션 %d건 적재 (현재가 %s)",
                        idx, len(targets), name, code, n, opt_n,
                        f"{current_price:,.0f}원" if current_price else "-")
            success.append(code)
        except Exception as e:
            logger.error("[%d/%d] %s(%s) 수집 실패: %s", idx, len(targets), name, code, e)
            failed.append(code)

        time.sleep(REQUEST_DELAY)

    logger.info("옵션 스냅샷 총 적재: %d건 (0건이면 현재 KRX 주식옵션 무거래 상태)", total_opts)

    session.close()
    logger.info("수집 완료 — 성공 %d / 실패 %d", len(success), len(failed))
    if failed:
        logger.warning("실패 코드: %s", ", ".join(failed))

    # 3. 대시보드 재빌드
    try:
        build_dashboard()
    except Exception as e:
        logger.error("대시보드 재빌드 실패: %s", e)
    return True


if __name__ == "__main__":
    main()
