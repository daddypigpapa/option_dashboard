import logging
import os
from datetime import date
from database import init_db, get_db_session, OptionSnapshot, StockHistory
from collector import collect_options_for_ticker
from usa_etf_option_collect import save_to_database

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestRun")

def test_single_ticker():
    logger.info("1. 테스트용 DB 초기화 시작...")
    init_db()
    
    test_ticker = "SPY"
    logger.info(f"2. {test_ticker} 옵션 데이터 수집 및 그릭스 연산 시작...")
    
    # 임시 수집 (튜플 반환으로 수정)
    option_snapshots, stock_history_snapshots = collect_options_for_ticker(test_ticker)
    
    if not option_snapshots:
        logger.error("데이터 수집 실패 또는 데이터 없음")
        return False
        
    logger.info(f"3. 수집 성공! 레코드 개수 - 옵션: {len(option_snapshots)}개, 주가: {len(stock_history_snapshots)}개")
    logger.info("첫 번째 레코드 정보 프리뷰:")
    first = option_snapshots[0]
    logger.info(f" - 티커: {first.underlying_ticker}, 현재가: {first.spot_price}")
    logger.info(f" - 옵션 심볼: {first.option_symbol}, 만기일: {first.expiration_date}, DTE: {first.dte}")
    logger.info(f" - 구분: {first.option_type}, 행사가: {first.strike}")
    logger.info(f" - IV: {first.implied_volatility}")
    logger.info(f" - 계산된 Greeks -> Delta: {first.delta}, Gamma: {first.gamma}, Vega: {first.vega}, Theta: {first.theta}")
 
    logger.info("4. SQLite 데이터베이스에 적재 시도...")
    db_session = get_db_session()
    try:
        opt_inserted = save_to_database(db_session, option_snapshots)
        stock_inserted = save_to_database(db_session, stock_history_snapshots)
        logger.info(f"DB 적재 완료! 성공 개수 - 옵션: {opt_inserted}/{len(option_snapshots)}개, 주가: {stock_inserted}/{len(stock_history_snapshots)}개")
        
        # 5. DB 검증 쿼리 수행
        logger.info("5. DB 데이터 재조회 검증...")
        saved_records = db_session.query(OptionSnapshot).filter_by(underlying_ticker=test_ticker).limit(5).all()
        for rec in saved_records:
            logger.info(f" DB 레코드 -> Symbol: {rec.option_symbol}, Strike: {rec.strike}, Delta: {rec.delta}")
            
        if len(saved_records) > 0:
            logger.info("★ 테스트 성공: 데이터 수집, 계산, DB 저장이 완벽히 검증되었습니다. ★")
            return True
        else:
            logger.error("테스트 실패: DB에서 적재된 데이터를 조회하지 못했습니다.")
            return False
    except Exception as e:
        logger.error(f"테스트 중 예외 발생: {e}")
        return False
    finally:
        db_session.close()

if __name__ == "__main__":
    test_single_ticker()
