import os
import json

# 1. 수집 대상 미국 주요 ETF 30선 로드
# etf_list.json 파일에서 리스트를 동적으로 읽어옵니다.
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
ETF_LIST_PATH = os.path.join(CONFIG_DIR, "etf_list.json")

DEFAULT_ETFS = [
    "SPY", "QQQ", "IWM", "TQQQ", "SOXL", "SQQQ", "TLT", "VOO", "IVV", "HYG",
    "EEM", "XLK", "XLE", "XLF", "TSLL", "BOIL", "SLV", "GLD", "GDX", "LABU",
    "UPRO", "SPXS", "UVXY", "SVXY", "KWEB", "FXI", "JNUG", "ARKK", "LQD", "FNGU"
]

if os.path.exists(ETF_LIST_PATH):
    try:
        with open(ETF_LIST_PATH, "r", encoding="utf-8") as f:
            TARGET_ETFS = json.load(f)
    except Exception:
        TARGET_ETFS = DEFAULT_ETFS
else:
    TARGET_ETFS = DEFAULT_ETFS

# 2. 수집 범위 기준 설정
# 잔존 만기일(Days to Expiry, DTE) 기준
MAX_DTE = 90

# 3. 속도 제한 및 차단 우회 정책 설정
# API 호출 간 임의 대기 시간 범위 (초 단위)
DELAY_MIN = 1.5
DELAY_MAX = 3.0

# 4. 데이터베이스 및 저장소 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "options_data.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 5. 로깅 설정
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_LEVEL = "INFO"
