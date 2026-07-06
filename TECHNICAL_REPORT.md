# MARKET AI DASHBOARD — 기술 구현 리포트

작성일: 2026-07-02 · 위치: `C:\Users\leejaegeon\claude\dashboard_project`

---

## 1. 시스템 아키텍처

```
┌─ 데이터 소스 ─────────────────────────────────────────────────────┐
│  yfinance        FRED API        DART OpenAPI      KIS OpenAPI    │
│  (주가/지표/목표가) (거시 30종/캘린더) (한국 공시)     (한국 일봉/지수) │
└──────┬───────────────┬───────────────┬────────────────┬──────────┘
       ▼               ▼               ▼                ▼
  src/fetch/*  ──────────────────────────────────►  data/raw/*.csv|json
       │
       ▼  Part 2: 분석
  src/analyze/scoring.py      6팩터 스코어링 (US: SPY 벤치마크 / KR: ^KS11)
  src/analyze/smart_money.py  Top-N 스마트머니 픽 선정
  src/premium/*               옵션플로우·ETF플로우 (유료 어댑터, 키 없으면 skip)
       │
       ▼  Part 3: AI
  src/ai/stock_brief.py       픽별 기업 브리프 (Claude)
  src/ai/macro_analysis.py    거시 분석 (Claude + Gemini 병렬, 동일 프롬프트)
       │
       ▼
  data/output/dashboard.json  ◄── 단일 통합 산출물
       │
       ▼
  webapp/ (Flask :5000)  ──►  브라우저 대시보드
       └── /options/     ──►  option_dashboard/ (벤더링된 옵션 분석 레포, iframe 임베드)
```

| 모듈 | 역할 |
|---|---|
| `config.py` | 경로·키·튜닝 중앙 관리. 키 해석 순서: `keys.json`(대시보드 입력) → 환경변수/`.env` |
| `keystore.py` | 대시보드에서 입력한 API 키를 `keys.json`에 저장(평문·gitignore). UI에는 마스킹(`••••1234`)만 노출 |
| `main.py` | CLI 진입점: `--skip-ai`(AI 제외) / `--kr-only`(한국증시만 갱신) / `-v` |
| `src/pipeline.py` | Part 1→2→3 오케스트레이션 + `dashboard.json` 통합 출력 |
| `src/kr_refresh.py` | KR 전용 고속 갱신 (US 유니버스 무접촉, ~1분) |
| `webapp/app.py` | Flask 서버: 페이지·키 API·실행 API·옵션 대시보드 서빙 |

---

## 2. Part 1 — 데이터 수집 계층 (`src/fetch/`)

### 2.1 유니버스
- **US** (`src/universe.py`): S&P 500 구성종목을 Wikipedia에서 라이브 스크랩(~503종). 실패 시 대형주 20종 폴백. `UNIVERSE_OVERRIDE`/`MAX_TICKERS` 환경변수로 축소 테스트 가능.
- **KR** (`src/kr_universe.py`): KOSPI 대형주 40종 큐레이션(6자리 KRX 코드 + `.KS`) + 한글 종목명 맵(`KR_NAMES`, AI 프롬프트 보강용). 벤치마크 `^KS11`.

### 2.2 수집 모듈
| 모듈 | 소스 | 산출물 (`data/raw/`) | 비고 |
|---|---|---|---|
| `prices.py` | yfinance | `prices.csv`, `prices_latest.json` (KR은 `kr_` 접두사) | 50종 배치 + 1초 대기, 1년 일봉 |
| `market_indicators.py` | yfinance+FRED | `market_indicators*.{csv,json}` | 13개 야후 심볼(다우/S&P/나스닥/러셀/코스피/코스닥/VIX/SKEW/금/유가/BTC/DXY/원달러) + FRED 국채 10y/3y/2y |
| `macro_fred.py` | FRED | `macro_indicators.csv`, `fred/*.csv` | 거시 30종 (CPI·PCE·고용·금리곡선·신용스프레드·M2 등) |
| `analyst_targets.py` | yfinance | `analyst_targets.{csv,json}` | 컨센서스 목표가 → 업사이드% 계산. 티커당 0.3초 페이싱 |
| `economic_calendar.py` | FRED releases | `economic_calendar.json` | CPI/고용/GDP/PCE 등 향후 발표 일정 |
| `dart_disclosures.py` | DART OpenAPI | `dart_disclosures.json` | 한국 주요 12사 최근 30일 공시. corpCode.xml 1회 캐싱 |
| `kis_prices.py` | **KIS OpenAPI** | `kr_prices.csv`, `kis_token.json` | 한국투자증권 일봉(FHKST03010100, 수정주가, ≤100봉) + 코스피/코스닥 지수(FHKUP03500100). 토큰 24h 캐싱 |

### 2.3 KR 데이터 이원화 전략
KR 트랙(`pipeline._run_kr_track`)은 **KIS 키가 설정되면 KIS 우선, 아니면 yfinance 자동 폴백**.
KIS 응답을 yfinance와 동일한 long-format DataFrame(ticker/date/OHLCV)으로 정규화하므로 하위 스코어링 코드는 소스를 구분하지 않는다.

### 2.4 공통 설계 원칙
- **Graceful degradation**: 모든 선택적 소스(DART·KIS·유료 어댑터·AI)는 키 부재/실패 시 로그 경고 후 빈 결과 반환 — 파이프라인은 절대 하드페일하지 않음.
- **키 없이도 항상 계산 가능**: 6팩터가 전부 무료 데이터(가격·거래량·목표가)에서 파생.

---

## 3. Part 2 — 6팩터 스코어링 (`src/analyze/scoring.py`)

| 팩터 | 산식 |
|---|---|
| momentum | 63거래일(~3개월) 수익률 `close[-1]/close[-64] − 1` |
| trend | `((P/MA50 − 1) + (P/MA200 − 1)) / 2` (200봉 미만이면 전체평균 대체) |
| volume_surge | `vol5일평균 / vol60일평균 − 1` |
| rel_strength | `momentum − 벤치마크 momentum` (US=SPY, KR=^KS11) |
| low_vol | 20일 실현변동성(연율화)의 **역백분위** (낮을수록 고득점) |
| analyst_upside | `목표가평균/현재가 − 1` (결측 시 중앙값→0 폴백; KR은 목표가 희박) |

- 각 팩터를 유니버스 내 **0–100 백분위**로 변환 → 동일가중 평균 = `composite_score` → 내림차순 rank.
- 옵션플로우 상태(롱🟢/중립🟠/숏🔴)는 픽에 **부착만** 되고 점수에는 미반영 (유료 어댑터 미구현 시 'unavailable').
- `smart_money.select_top_picks`: 상위 N(현재 20) 선정, 가격·등락·거래량·시총·목표가·(KR)한글명 병합. 산출: `scores.csv/json`, `top_picks.json` (KR은 `kr_` 접두사).
- 벤치마크 자신은 픽 대상에서 제외.

유료 어댑터(`src/premium/`): `options_flow.py`·`etf_flows.py`에 `PROVIDER INTEGRATION POINT` 함수 1개씩 — 유료 데이터 계약 시 해당 함수만 구현하면 됨.

---

## 4. Part 3 — AI 통합 (`src/ai/`)

- `clients.py`: Claude(`claude-opus-4-8`)·Gemini(`gemini-2.5-pro`) 래퍼. 키/SDK 부재 시 `available=False`로 우아하게 skip. 모델명은 대시보드에서 변경 가능.
- `stock_brief.py`: 픽별 3–4문장 기업 브리프(Claude). KR 픽은 `Company: 삼성전자 (ticker 005930.KS)` 형식으로 한글명을 프롬프트에 주입 — 숫자코드만 줄 때보다 정확도↑. 매수/매도 조언 금지 시스템 프롬프트.
- `macro_analysis.py`: 거시 30종 + 시장지표 스냅샷을 **동일 프롬프트로 Claude와 Gemini에 각각** 전달 → 두 요약을 나란히 표시(성장/물가/금리곡선/신용/달러 + 관찰 포인트 2–3).

---

## 5. 산출물 — `data/output/dashboard.json` 스키마

```jsonc
{
  "generated_at": "…",            // 전체 파이프라인 실행 시각
  "kr_updated_at": "…",           // KR 전용 갱신 시각 (헤더에 별도 표시)
  "universe_size": 20,            // 스크랩 성공 시 ~503, 폴백 시 20 (아래 §9-7 참조)
  "market_indicators": { "kospi": {"value","change_pct","as_of"}, … },   // 16종
  "market_indicators_history": { "kospi": {"YYYY-MM-DD": close, …}, … }, // 스파크라인용
  "top_picks":  [ {rank, ticker, name, composite_score, factors{6}, flow_status,
                   current_price, daily_change_pct, volume, market_cap,
                   target_mean, upside_pct, ai_brief}, … ],   // US 20
  "kr_picks":   [ …동일 스키마… ],                              // KR 20
  "options_flow": [], "etf_flows": {},        // 유료 키 없으면 빈 값
  "macro_analysis": { "claude", "gemini", "inputs" },
  "economic_calendar": [ {date, event, release_id}, … ],
  "dart_disclosures": [ {stock_code, corp_name, filings[]}, … ]
}
```

---

## 6. 웹 대시보드 (`webapp/`)

### 6.1 Flask 엔드포인트
| 경로 | 기능 |
|---|---|
| `/` | 메인 대시보드 (Jinja, `TEMPLATES_AUTO_RELOAD` 활성) |
| `/api/keys` GET/POST | 키 상태(마스킹) 조회 / 저장 |
| `/api/run` POST | 파이프라인 실행 (`{skip_ai, kr_only}`) — `main.py` 서브프로세스, 단일 실행 락 |
| `/api/status` | 실행 상태 + 로그 (프론트가 2초 폴링) |
| `/api/dashboard` | `dashboard.json` 서빙 |
| `/api/stock/<ticker>` | 종목 1년 일봉 라이브 조회 (yfinance, 차트용) |
| `/options/`, `/options/<path>` | **벤더링된 옵션 대시보드 서빙** (아래 6.3) |

### 6.2 UI 기능
- **통합 메뉴**: 한국증시 · 미국증시 · 미국ETF · 한국ETF · 한국옵션 · 경제관련 일정 · 피드 · 내 포트폴리오 · 보고서
- **시간대 기본 화면**: 로컬 08:00–20:00 → 한국증시, 그 외 → 미국증시 (`getDefaultMarketView`). 픽 목록·히트맵·기본 선택종목이 함께 전환.
- **TOP 스마트머니 PICK**: 종목명 우선 표시(티커는 부제) · 정렬 바(현재가[기본]/등락률/거래대금/시총/점수, 재클릭 시 방향 토글, 결측값 항상 하단) · rank 컬럼은 스코어 순위 보존.
- **종목 상세**: 종목명 우선 헤더(⇄ 버튼으로 티커↔이름 스왑, 세션 내 유지) · TradingView **Lightweight Charts v5** 캔들+거래량(기간 1달~5년) · AI 브리프.
- **마켓맵 히트맵**: KR/US 섹터 트리맵, 색상 모드(KR 빨강▲/US 초록▲) 토글.
- **하단**: Claude vs Gemini 거시 분석 병렬 카드 · 옵션/ETF 플로우 · 경제 캘린더.
- **분석 실행기 콘솔**: 전체 파이프라인(Skip-AI 체크) / **🇰🇷 한국증시 최신화(KIS)** 버튼, 실시간 로그 스트림.
- **헤더 타임스탬프 2종**: `Pipeline Generated At`(전체) + `KR 갱신`(KR 전용, 없으면 `-`).

### 6.3 옵션 분석 대시보드 통합 (option_dashboard 레포)
- https://github.com/daddypigpapa/option_dashboard 를 프로젝트 루트에 **클론(벤더링, .git 유지 → `git pull`로 업데이트)**.
- 완전 정적 산출물(HTML+`data/*.js` 지연로딩+로컬 Plotly/Tailwind)이라 Flask가 폴더째 `/options/`로 서빙.
- 상단 메뉴 **미국ETF/한국ETF/한국옵션**이 iframe 내부의 `data-market`(us/kr_etf/kr_stock) 탭 버튼을 **프로그래밍 클릭**으로 구동 — 내부 중복 탭은 CSS 주입으로 숨김.
- 임베드 커스터마이징은 **부모에서 `<style id="embed-overrides">` 주입**으로만 수행(제목 크기·헤더 패딩·탭 숨김) → 레포 파일 무수정 유지, pull 충돌 없음.
- 분석 내용: ETF/개별주 옵션 체인의 GEX·DEX·Call/Put Wall·Gamma Flip·PCR (레포 자체 리포트 `option_dashboard/TECHNICAL_REPORT.md` 참조).

---

## 7. 키 관리 & 보안

| 키 | 용도 | 필수 여부 |
|---|---|---|
| FRED_API_KEY | 거시지표·캘린더 | 권장 (무료) |
| DART_API_KEY | 한국 공시 | 선택 (무료) |
| KIS_APP_KEY / KIS_APP_SECRET | 한국증시 최신화 | 선택 |
| ANTHROPIC_API_KEY / GEMINI_API_KEY | AI 분석 | 선택 |
| OPTIONS_FLOW / ETF_FLOW | 유료 데이터 | 선택 (어댑터만 존재) |

- 저장: `keys.json` **평문·로컬 전용·gitignore**. UI는 마스킹 힌트만 표시, 원문 재노출 없음.
- KIS 토큰은 `data/raw/kis_token.json`에 캐싱(만료 10분 여유) — KIS의 발급 횟수 제한 대응.

---

## 8. 실행 방법

```powershell
# venv (Python 3.12 — Store 스텁이 PATH를 가리므로 전체 경로로 생성)
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt

python -m webapp.app          # 대시보드 (http://127.0.0.1:5000)
python main.py                # 전체 파이프라인 (fetch+분석+AI)
python main.py --skip-ai      # AI 제외 (API 비용 0)
python main.py --kr-only      # 한국증시만 고속 갱신 (~1분)
```

데이터 신선도 모델: **US = 전체 파이프라인**(500종, 수십 분) / **KR = 전용 갱신**(40종+지수, ~1분, 버튼 원클릭).

---

## 9. 알려진 한계 / 확장 포인트

1. **옵션·ETF 플로우는 유료** — 무료 API로 불가. 어댑터의 `PROVIDER INTEGRATION POINT` 함수만 구현하면 활성화.
2. **KR 애널리스트 목표가·시총은 yfinance 의존** (KIS 미제공) — 커버리지 희박, 스코어에선 중앙값 폴백으로 흡수.
3. **KIS 실계좌 키 경로는 공식 스펙+검증된 레포 코드 기반이나 실키 첫 실행 시 로그 확인 권장.**
4. 옵션 대시보드의 데이터는 레포 빌드 시점 스냅샷 — 갱신은 `option_dashboard/` 안의 수집기 실행 또는 `git pull`.
5. 피드·내 포트폴리오·보고서 메뉴는 현재 스크롤 이동/자리표시자 수준.
6. 프론트 하드코딩 잔존: 히트맵 섹터 구성·등락률 데모값, `STOCK_NAMES` 맵 — 실데이터 연동 여지.
7. **현재 적재된 US 데이터는 폴백 유니버스 기준** — 마지막 전체 실행(6/20)의 `universe_size=20`, 즉 Wikipedia S&P500 스크랩이 실패해 대형주 20종 폴백으로 수집됨. 전체 파이프라인 재실행으로 ~503종 복원 필요 (스크랩 재실패 시 `lxml` 설치/네트워크 확인).
