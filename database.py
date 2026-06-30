from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DATABASE_URL

Base = declarative_base()

class OptionSnapshot(Base):
    __tablename__ = "option_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collected_date = Column(Date, nullable=False, index=True)       # 수집일자 (Snapshot Date)
    underlying_ticker = Column(String(10), nullable=False, index=True) # 기초자산 티커 (예: SPY)
    spot_price = Column(Float, nullable=False)                        # 기초자산 가격
    
    option_symbol = Column(String(30), nullable=False, index=True)     # 옵션 고유 심볼 (OSI 코드)
    expiration_date = Column(Date, nullable=False, index=True)         # 옵션 만기일
    dte = Column(Integer, nullable=False)                              # 잔존일수 (Days to Expiry)
    strike = Column(Float, nullable=False)                             # 행사가격
    option_type = Column(String(10), nullable=False)                   # 'call' 또는 'put'
    
    last_price = Column(Float)                                         # 최근 거래가
    bid = Column(Float)                                                # 매수 호가
    ask = Column(Float)                                                # 매도 호가
    volume = Column(Integer)                                           # 거래량
    open_interest = Column(Integer)                                    # 미결제 약정 (OI)
    implied_volatility = Column(Float)                                 # 야후 제공 내재변동성 (IV)
    
    # 자체 연산된 블랙-숄즈 그릭스
    delta = Column(Float)
    gamma = Column(Float)
    vega = Column(Float)
    theta = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)             # 레코드 생성시간

    # 동일 수집일자에 동일 옵션 심볼이 중복 적재되지 않도록 복합 유니크 제약 추가
    __table_args__ = (
        UniqueConstraint('collected_date', 'option_symbol', name='_collected_option_uc'),
    )

    def __repr__(self):
        return f"<OptionSnapshot {self.underlying_ticker} {self.option_symbol} {self.option_type} K={self.strike} Date={self.collected_date}>"

class StockHistory(Base):
    __tablename__ = "stock_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collected_date = Column(Date, nullable=False, index=True)         # 수집일자 (Snapshot Date)
    underlying_ticker = Column(String(10), nullable=False, index=True)   # 기초자산 티커 (예: SPY)
    time = Column(String(30), nullable=False, index=True)             # 분봉 캔들 Timestamp
    
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # 동일 수집일자 내 동일한 시간의 주가 분봉 데이터 중복 적재 방지
    __table_args__ = (
        UniqueConstraint('collected_date', 'underlying_ticker', 'time', name='_collected_stock_time_uc'),
    )

    def __repr__(self):
        return f"<StockHistory {self.underlying_ticker} {self.time} Close={self.close}>"

# DB 엔진 및 세션 관리자 생성
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """
    데이터베이스 테이블 초기화 및 생성
    """
    Base.metadata.create_all(bind=engine)

def get_db_session():
    """
    데이터베이스 세션 컨텍스트 매니저
    """
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise
