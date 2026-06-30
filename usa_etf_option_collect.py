import time
import random
import logging
from datetime import date
from sqlalchemy.exc import IntegrityError

from config import TARGET_ETFS, LOG_FORMAT, LOG_LEVEL
from database import init_db, get_db_session, OptionSnapshot, StockHistory
from collector import collect_options_for_ticker
from build_static_dashboard import build_dashboard

# 1. 로깅 초기화
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger("MainCollector")

def save_to_database(session, snapshots):
    """
    수집된 옵션 데이터를 DB에 일괄 Bulk Save 처리.
    UniqueConstraint(collected_date, option_symbol) 충돌 시 예외 처리 적용.
    """
    if not snapshots:
        return 0

    inserted_count = 0
    # SQLite 성능 향상 및 충돌 대응을 위한 개별/배치 인서트 처리
    # 대량 적재 시 전체 롤백을 피하기 위해 청크 단위 혹은 개별 저장 처리 지원
    for snapshot in snapshots:
        try:
            session.add(snapshot)
            session.commit()
            inserted_count += 1
        except IntegrityError:
            # 중복 데이터 유니크 제약 충돌 시 세션 롤백 후 건너뜀 (멱등성 보장)
            session.rollback()
        except Exception as e:
            logger.error(f"데이터 적재 중 일반 오류 발생: {e}")
            session.rollback()
            
    return inserted_count

def main():
    logger.info("==================================================")
    logger.info("미국 ETF 30종 만기 90일 이내 옵션 수집 시스템 구동 시작")
    logger.info(f"대상 종목 수: {len(TARGET_ETFS)}개")
    logger.info("==================================================")
    
    start_time = time.time()
    
    # 2. 데이터베이스 초기화 (테이블 없으면 자동 생성)
    init_db()
    db_session = get_db_session()
    
    total_inserted = 0
    successful_tickers = []
    failed_tickers = []
    
    # 3. 30개 ETF 순회 수집
    for index, ticker in enumerate(TARGET_ETFS, start=1):
        logger.info(f"[{index}/{len(TARGET_ETFS)}] {ticker} 옵션 수집 프로세스 구동...")
        
        try:
            # Ticker별 옵션 데이터 및 주가 일봉 수집 (튜플 반환)
            option_snapshots, stock_history_snapshots = collect_options_for_ticker(ticker)
            
            if option_snapshots or stock_history_snapshots:
                logger.info(f" -> [{ticker}] DB 적재 프로세스 가동 (옵션: {len(option_snapshots)}개, 주가: {len(stock_history_snapshots)}개)")
                
                # 각각 DB 적재 실행
                opt_inserted = save_to_database(db_session, option_snapshots)
                stock_inserted = save_to_database(db_session, stock_history_snapshots)
                
                logger.info(f" -> [{ticker}] DB 적재 완료 (옵션 성공: {opt_inserted}개, 주가 성공: {stock_inserted}개)")
                
                total_inserted += (opt_inserted + stock_inserted)
                successful_tickers.append(ticker)
            else:
                logger.warning(f" -> [{ticker}] 수집된 데이터가 없습니다.")
                failed_tickers.append(ticker)
                
        except Exception as e:
            logger.error(f" -> [{ticker}] 수집 중 심각한 에러 발생: {e}")
            failed_tickers.append(ticker)
            
        # 종목 간 호출 딜레이 설정 (차단 위험 최소화)
        if index < len(TARGET_ETFS):
            delay = random.uniform(3.0, 5.0)
            logger.info(f"다음 종목 수집 전 대기 시간: {delay:.2f}초...")
            time.sleep(delay)
            
    # 세션 닫기
    db_session.close()
    
    elapsed_time = time.time() - start_time
    logger.info("==================================================")
    logger.info("데이터 수집 완료 보고")
    logger.info(f"총 소요 시간: {elapsed_time/60.0:.2f}분")
    logger.info(f"총 신규 적재 데이터 수: {total_inserted} 건")
    logger.info(f"성공 종목 ({len(successful_tickers)}개): {', '.join(successful_tickers)}")
    if failed_tickers:
        logger.warning(f"실패/미적재 종목 ({len(failed_tickers)}개): {', '.join(failed_tickers)}")
    # 수집 성공 완료 후 자동으로 정적 HTML 대시보드 파일 갱신 빌드
    try:
        build_dashboard()
    except Exception as e:
        logger.error(f"수집 프로세스 완료 후 대시보드 자동 빌드 실패: {e}")

    logger.info("==================================================")

if __name__ == "__main__":
    main()
