"""Korean (KOSPI) stock universe for the KR smart-money scoring track.

A curated list of major KOSPI large/mid caps (Yahoo Finance ``.KS`` symbols) — wide
enough (~40 names) for meaningful 0-100 percentile ranking across the six factors.
The KOSPI index (``^KS11``) is used as the relative-strength benchmark, mirroring
how SPY anchors the US track.
"""
from __future__ import annotations

# 6-digit KRX code + ``.KS`` (KOSPI). Yahoo Finance serves these directly.
KR_TICKERS: list[str] = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "373220.KS",  # LG에너지솔루션
    "207940.KS",  # 삼성바이오로직스
    "005380.KS",  # 현대차
    "000270.KS",  # 기아
    "005490.KS",  # POSCO홀딩스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "051910.KS",  # LG화학
    "006400.KS",  # 삼성SDI
    "068270.KS",  # 셀트리온
    "105560.KS",  # KB금융
    "055550.KS",  # 신한지주
    "012330.KS",  # 현대모비스
    "028260.KS",  # 삼성물산
    "066570.KS",  # LG전자
    "003670.KS",  # 포스코퓨처엠
    "096770.KS",  # SK이노베이션
    "034730.KS",  # SK
    "015760.KS",  # 한국전력
    "017670.KS",  # SK텔레콤
    "030200.KS",  # KT
    "086790.KS",  # 하나금융지주
    "033780.KS",  # KT&G
    "009150.KS",  # 삼성전기
    "011200.KS",  # HMM
    "010130.KS",  # 고려아연
    "259960.KS",  # 크래프톤
    "036570.KS",  # 엔씨소프트
    "090430.KS",  # 아모레퍼시픽
    "018260.KS",  # 삼성에스디에스
    "032830.KS",  # 삼성생명
    "316140.KS",  # 우리금융지주
    "024110.KS",  # 기업은행
    "047810.KS",  # 한국항공우주
    "010950.KS",  # S-Oil
    "011170.KS",  # 롯데케미칼
    "097950.KS",  # CJ제일제당
    "000810.KS",  # 삼성화재
]

# KOSPI composite index — relative-strength benchmark for the KR track.
KR_BENCHMARK = "^KS11"

# Ticker -> Korean company name, used to enrich the AI brief prompt (Claude maps a
# numeric KRX code far better when given the name).
KR_NAMES: dict[str, str] = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스",
    "005380.KS": "현대차",
    "000270.KS": "기아",
    "005490.KS": "POSCO홀딩스",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
    "051910.KS": "LG화학",
    "006400.KS": "삼성SDI",
    "068270.KS": "셀트리온",
    "105560.KS": "KB금융",
    "055550.KS": "신한지주",
    "012330.KS": "현대모비스",
    "028260.KS": "삼성물산",
    "066570.KS": "LG전자",
    "003670.KS": "포스코퓨처엠",
    "096770.KS": "SK이노베이션",
    "034730.KS": "SK",
    "015760.KS": "한국전력",
    "017670.KS": "SK텔레콤",
    "030200.KS": "KT",
    "086790.KS": "하나금융지주",
    "033780.KS": "KT&G",
    "009150.KS": "삼성전기",
    "011200.KS": "HMM",
    "010130.KS": "고려아연",
    "259960.KS": "크래프톤",
    "036570.KS": "엔씨소프트",
    "090430.KS": "아모레퍼시픽",
    "018260.KS": "삼성에스디에스",
    "032830.KS": "삼성생명",
    "316140.KS": "우리금융지주",
    "024110.KS": "기업은행",
    "047810.KS": "한국항공우주",
    "010950.KS": "S-Oil",
    "011170.KS": "롯데케미칼",
    "097950.KS": "CJ제일제당",
    "000810.KS": "삼성화재",
}


def get_kr_universe() -> list[str]:
    """Return the KR working universe (de-duped, order preserved)."""
    seen, ordered = set(), []
    for t in KR_TICKERS:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered
