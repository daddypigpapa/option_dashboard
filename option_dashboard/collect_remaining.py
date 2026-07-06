"""
미수집 ETF만 골라서 옵션/주가 데이터를 수집하는 보조 러너.

특징
- 이미 DB(option_snapshots)에 존재하는 티커는 건너뛴다 → SPY 등 기수집분 재호출 방지.
- 중간에 yfinance 호출 제한/차단으로 중단되어도, 다시 실행하면 남은 티커부터 이어서 수집(재개 가능).
- 티커 사이 대기 시간을 기본 수집기보다 보수적으로(기본 8~15초) 둬서 차단 위험을 낮춘다.
- 모두 끝나면 정적 대시보드를 재빌드한다.

사용법
    python collect_remaining.py            # 미수집 티커 전체
    python collect_remaining.py QQQ IWM    # 지정한 티커만 (그래도 기수집분은 스킵)
"""

import sys
import time
import random
import logging

from sqlalchemy import distinct

from config import TARGET_ETFS, LOG_FORMAT, LOG_LEVEL
from database import init_db, get_db_session, OptionSnapshot
from collector import collect_options_for_ticker
from usa_etf_option_collect import save_to_database
from build_static_dashboard import build_dashboard

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger("RemainingCollector")

# 티커 사이 보수적 대기(초). 호출 제한 회피용. 필요시 값만 조정.
TICKER_DELAY_MIN = 8.0
TICKER_DELAY_MAX = 15.0


def get_existing_tickers(session):
    """DB에 이미 옵션 데이터가 적재된 티커 집합 반환."""
    rows = session.query(distinct(OptionSnapshot.underlying_ticker)).all()
    return {r[0] for r in rows}


def main():
    init_db()
    session = get_db_session()

    existing = get_existing_tickers(session)

    # 인자로 티커를 지정하면 그 안에서만, 아니면 전체 대상에서 미수집분만.
    requested = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else list(TARGET_ETFS)
    remaining = [t for t in requested if t not in existing]

    logger.info("==================================================")
    logger.info(f"기수집 티커({len(existing)}개): {', '.join(sorted(existing)) or '없음'}")
    logger.info(f"이번 수집 대상({len(remaining)}개): {', '.join(remaining) or '없음'}")
    logger.info("==================================================")

    if not remaining:
        logger.info("새로 수집할 티커가 없습니다. 종료합니다.")
        session.close()
        return

    success, failed = [], []
    start = time.time()

    for idx, ticker in enumerate(remaining, start=1):
        logger.info(f"[{idx}/{len(remaining)}] {ticker} 수집 시작...")
        try:
            option_snapshots, stock_snapshots = collect_options_for_ticker(ticker)

            if option_snapshots or stock_snapshots:
                opt_n = save_to_database(session, option_snapshots)
                stk_n = save_to_database(session, stock_snapshots)
                logger.info(f" -> [{ticker}] 적재 완료 (옵션 {opt_n} / 주가 {stk_n})")
                success.append(ticker)
            else:
                logger.warning(f" -> [{ticker}] 수집 데이터 없음 (호출 제한 가능성 → 나중에 재실행).")
                failed.append(ticker)
        except Exception as e:
            logger.error(f" -> [{ticker}] 수집 중 에러: {e}")
            failed.append(ticker)

        # 마지막 티커가 아니면 보수적 대기
        if idx < len(remaining):
            delay = random.uniform(TICKER_DELAY_MIN, TICKER_DELAY_MAX)
            logger.info(f"다음 티커까지 대기 {delay:.1f}초...")
            time.sleep(delay)

    session.close()

    logger.info("==================================================")
    logger.info(f"총 소요: {(time.time()-start)/60.0:.1f}분")
    logger.info(f"성공({len(success)}): {', '.join(success) or '없음'}")
    if failed:
        logger.warning(f"실패/미적재({len(failed)}): {', '.join(failed)} — 인터넷/호출제한 확인 후 재실행하면 이어받습니다.")

    # 대시보드 재빌드
    try:
        build_dashboard()
        logger.info("대시보드 재빌드 완료.")
    except Exception as e:
        logger.error(f"대시보드 재빌드 실패: {e}")
    logger.info("==================================================")


if __name__ == "__main__":
    main()
