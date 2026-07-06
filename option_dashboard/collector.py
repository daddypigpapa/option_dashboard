import time
import random
import logging
from datetime import datetime, date
import requests
import pandas as pd
import yfinance as yf

from config import MAX_DTE, DELAY_MIN, DELAY_MAX
from greeks import calculate_greeks
from database import OptionSnapshot, StockHistory

import urllib3

# 로깅 설정
logger = logging.getLogger("OptionCollector")

# SSL 인증서 검증 경고 비활성화 (보안 프로그램/사설 인증서 환경용)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# yfinance 요청 시 차단을 피하기 위한 세션 생성 및 User-Agent 지정
session = requests.Session()
session.verify = False  # SSL 인증서 검증 비활성화
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
})

def get_spot_price(ticker_obj):
    """
    기초자산의 최신 종가(Spot Price)를 수집
    """
    try:
        # 최근 1일치 봉 데이터를 긁어서 종가 획득
        hist = ticker_obj.history(period="1d")
        if hist.empty:
            return None
        return float(hist['Close'].iloc[-1])
    except Exception as e:
        logger.error(f"기초자산 가격 조회 중 오류 발생: {e}")
        return None

def process_option_data(df, option_type, exp_str, spot_price, ticker_symbol, collected_date):
    """
    yfinance 옵션 체인 DataFrame을 정제하고 그릭스를 계산하여 ORM 모델 인스턴스 리스트로 반환
    """
    snapshots = []
    exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
    dte = (exp_date - collected_date).days
    T = dte / 365.0 # 연 단위 만기 기간
    
    # 임의로 무위험 이자율은 미국 3개월 국채 금리 수준(4.5%) 적용
    r = 0.045
    
    for _, row in df.iterrows():
        # 필수 가격 정보가 누락된 경우 스킵
        if pd.isna(row['strike']):
            continue
            
        strike = float(row['strike'])
        iv = float(row['impliedVolatility']) if not pd.isna(row['impliedVolatility']) else 0.0
        
        # 1. 자체 블랙-숄즈 그릭스 연산 수행
        greeks = calculate_greeks(
            flag=option_type,
            S=spot_price,
            K=strike,
            T=T,
            r=r,
            sigma=iv
        )
        
        # 2. ORM 객체 매핑
        snapshot = OptionSnapshot(
            collected_date=collected_date,
            underlying_ticker=ticker_symbol,
            spot_price=spot_price,
            option_symbol=row['contractSymbol'],
            expiration_date=exp_date,
            dte=dte,
            strike=strike,
            option_type=option_type,
            last_price=float(row['lastPrice']) if not pd.isna(row['lastPrice']) else None,
            bid=float(row['bid']) if not pd.isna(row['bid']) else None,
            ask=float(row['ask']) if not pd.isna(row['ask']) else None,
            volume=int(row['volume']) if not pd.isna(row['volume']) else 0,
            open_interest=int(row['openInterest']) if not pd.isna(row['openInterest']) else 0,
            implied_volatility=iv,
            delta=greeks['delta'],
            gamma=greeks['gamma'],
            vega=greeks['vega'],
            theta=greeks['theta']
        )
        snapshots.append(snapshot)
        
    return snapshots

def collect_options_for_ticker(ticker_symbol):
    """
    단일 티커에 대해 90일 이내의 옵션 체인 및 일봉 주가를 함께 수집하여 (옵션스냅샷, 주가스냅샷) 튜플 반환
    """
    collected_date = date.today()
    ticker = yf.Ticker(ticker_symbol, session=session)
    
    # 1. 기초자산 일봉 시세 (최근 3개월) 및 Spot 가격 수집
    try:
        hist = ticker.history(interval="1d", period="3mo")
        if hist.empty:
            logger.warning(f"[{ticker_symbol}] 일봉 주가 시세 데이터를 가져올 수 없어 수집을 건너뜁니다.")
            return [], []
            
        spot_price = float(hist['Close'].iloc[-1])
    except Exception as e:
        logger.error(f"[{ticker_symbol}] 주가 데이터 조회 중 오류: {e}")
        return [], []
        
    logger.info(f"[{ticker_symbol}] 현재가: {spot_price:.2f} USD 수집 완료. 옵션 및 일봉 데이터 가공 중...")
    
    # 주가 일봉 스냅샷 생성
    stock_history_snapshots = []
    for idx, row in hist.iterrows():
        time_str = idx.strftime('%Y-%m-%d')
        stock_rec = StockHistory(
            collected_date=collected_date,
            underlying_ticker=ticker_symbol,
            time=time_str,
            open=round(float(row['Open']), 2),
            high=round(float(row['High']), 2),
            low=round(float(row['Low']), 2),
            close=round(float(row['Close']), 2),
            volume=int(row['Volume'])
        )
        stock_history_snapshots.append(stock_rec)

    # 2. 모든 만기일 목록 조회
    try:
        expirations = ticker.options
    except Exception as e:
        logger.error(f"[{ticker_symbol}] 만기일 목록 로드 중 오류: {e}")
        return [], []
        
    if not expirations:
        logger.warning(f"[{ticker_symbol}] 활성화된 옵션 만기물이 없습니다.")
        return [], []
        
    all_snapshots = []
    
    # 3. 90일 이내의 만기일만 필터링하여 루프 구동
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            dte = (exp_date - collected_date).days
            
            # 90일 DTE 제한 조건
            if dte > MAX_DTE:
                continue
                
            # 만기가 오늘 이전인 과거 데이터는 필터링
            if dte <= 0:
                continue
                
            logger.info(f" -> [{ticker_symbol}] 만기일 수집: {exp_str} (DTE: {dte}일)")
            
            # 옵션 체인 데이터 수집
            opt_chain = ticker.option_chain(exp_str)
            
            # 콜옵션 데이터 처리
            calls_snapshots = process_option_data(
                opt_chain.calls, 'call', exp_str, spot_price, ticker_symbol, collected_date
            )
            all_snapshots.extend(calls_snapshots)
            
            # 풋옵션 데이터 처리
            puts_snapshots = process_option_data(
                opt_chain.puts, 'put', exp_str, spot_price, ticker_symbol, collected_date
            )
            all_snapshots.extend(puts_snapshots)
            
        except Exception as e:
            logger.error(f" -> [{ticker_symbol}] {exp_str} 만기물 처리 중 에러 발생: {e}")
            
        # API Rate Limit 준수 및 차단 방지를 위해 만기일별 랜덤 딜레이
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)
        
    logger.info(f"[{ticker_symbol}] 수집 완료. (옵션: {len(all_snapshots)}개, 분봉: {len(stock_history_snapshots)}개)")
    return all_snapshots, stock_history_snapshots
