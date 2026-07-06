# ETF·주식 옵션 분석 대시보드 — 기술 구현 리포트

작성일: 2026-07-02 (2차 갱신: 한국 시장 통합 중간 리포트 포함) · 저장소: https://github.com/daddypigpapa/option_dashboard

---

## 1. 시스템 아키텍처

```
[yfinance API]
     │  (수집: 만기 90일 이내 옵션체인 + 3개월 일봉)
     ▼
collector.py ──► SQLite (options_data.db)
                   ├─ option_snapshots  (유니크: collected_date + option_symbol)
                   └─ stock_history
     │
     ▼  (파생지표 연산 + 직렬화)
build_static_dashboard.py
     ├─► option_dashboard.html      (경량 셸 + 요약 메타데이터 인라인, ~73KB)
     └─► data/{TICKER}_options.js   (종목별 옵션 상세, 선택 시 지연 로딩)
     │
     ▼
정적 대시보드 (100% Serverless, 오프라인 동작)
  - libs/plotly.min.js      : 차트 라이브러리 로컬 번들
  - libs/tailwind-local.css : Tailwind 사용-클래스 서브셋 (8KB, CDN 제거)
```

| 모듈 | 역할 |
|---|---|
| `config.py` | 대상 ETF 30종(`etf_list.json`), MAX_DTE=90, 딜레이 정책, DB 경로 |
| `collector.py` | yfinance 세션 관리, 옵션체인/일봉 수집, Black-Scholes 그릭스 산출 |
| `usa_etf_option_collect.py` | 전 종목 순회 수집 메인 러너 (티커 간 3~5초 랜덤 대기) |
| `collect_remaining.py` | **미수집분만** 수집하는 보조 러너 (재개 가능, 티커 간 8~15초) |
| `greeks.py` | Black-Scholes 델타/감마/베가/세타 (r=4.5% 고정) |
| `database.py` | SQLAlchemy ORM, 유니크 제약 기반 멱등 적재 |
| `build_static_dashboard.py` | GEX/DEX/Wall/Gamma-Flip 연산 + 정적 HTML/JS 빌드 |
| `index_template.html` | 대시보드 UI/차트 로직 템플릿 (빌더가 데이터 치환) |

---

## 2. 데이터 수집 계층

### 2.1 레이트리밋 대응
- `requests.Session` 재사용 + 브라우저 User-Agent 지정, SSL 검증 비활성(사내망/보안SW 환경 대응).
- 만기일별 1.5~3.0초, 티커 간 3~5초(메인) / 8~15초(보조) 랜덤 대기.
- `collect_remaining.py`는 DB에 이미 존재하는 티커를 자동 스킵 → 차단·중단 시 **재실행만으로 이어받기**.
- 멱등성: `(collected_date, option_symbol)` 유니크 제약 + IntegrityError 개별 롤백 → 같은 날 재실행해도 중복 적재 없음.

### 2.2 수집 결과 (2026-06-30 스냅샷)
- 30종 중 **29종 성공**, 옵션 스냅샷 총 ~29,000건.
- **FNGU 실패**: 호출 제한이 아니라 옵션 체인 자체가 미상장(ETN). 목록 제외 검토 대상.

---

## 3. 파생 지표 연산 (빌드 타임)

| 지표 | 산식 |
|---|---|
| GEX (Dollar Gamma) | `sign(call=+1/put=−1) × γ × OI × S²` |
| DEX (Dollar Delta) | `δ × OI × 100 × S` |
| Call/Put Wall | 행사가별 GEX 합산의 최대(콜)/최소(풋) 행사가 |
| Gamma Flip | S를 spot ±20% 구간 100스텝으로 가상 순회, 각 S에서 BS 감마 재계산 → 총 GEX 부호 전환점을 선형보간 |
| PCR(OI) | 풋 OI 합 / 콜 OI 합 |

연산은 전부 **빌드 타임(Python)** 에 수행되어 JSON으로 직렬화 → 브라우저는 표시만 담당(런타임 연산 0).

---

## 4. 로딩 성능 최적화 (핵심 작업)

### 4.1 문제
- 초기 구조: 전 종목 옵션 상세를 HTML에 인라인 → SPY 1종만으로 **1.88MB / 79,278줄**. 30종 완수 시 ~56MB 추정. 브라우저 파싱 시점에 전량 로드.

### 4.2 해결 — 티커별 지연 로딩
- 빌더가 무거운 `options` 딕셔너리를 `data/{TICKER}_options.js`로 분리 (`window._etfOptions_{TICKER} = {...}` 형태).
- HTML에는 요약 메타데이터(`window.optionsMeta`: spot/OI/PCR/GEX/DEX/Wall/만기목록/일봉)만 인라인.
- 티커 선택 시 `<script>` 태그 동적 주입으로 해당 파일만 로드. `fetch` 대신 script 주입이라 **`file://` 프로토콜에서도 동작**. `Set` 기반 로드 캐시로 재선택 시 0ms.
- 결과: **HTML 1.88MB → 73KB (96% 감소)**, 30종 확장 후에도 셸은 ~380KB(메타데이터 증가분), 상세는 종목당 60~840KB 온디맨드.

### 4.3 외부 의존성 제거 (오프라인 장애 해결)
- 증상: 오프라인 환경에서 페이지가 무한 로딩 → `<head>`의 Tailwind CDN `<script>`가 응답 대기하며 렌더 블로킹.
- 조치: 템플릿에서 실사용 클래스(~130개)를 grep 추출해 **8KB 로컬 CSS 서브셋**(`libs/tailwind-local.css`) 수제 작성, CDN `<script>` → `<link>` 교체. Plotly는 기존에 로컬화 완료.
- 결과: 외부 URL 참조 0건, 완전 오프라인 동작.

---

## 5. 차트 (Plotly) 구현 세부

### 5.1 구조
- 캔들스틱(x/y: 날짜·가격) + 가로 막대 2트레이스(x2/y: 노출액·행사가, `overlaying:'x'`, `barmode:'overlay'`).
- 지표 라디오(GEX/DEX/δ/γ/ν/θ)에 따라 막대 x값·색·호버템플릿 스위칭. 콜=적색 계열, 풋=녹색 계열(그릭스 모드는 Reds/Greens 컬러스케일).

### 5.2 가이드라인 & 동적 겹침 방지
- 4종 수평선: Spot(노랑 점선) / Gamma Flip(흰 점선) / Call Wall(시안 파선) / Put Wall(주황 파선).
- 레이블은 `xref:'paper', x:1.005`로 **우측 여백에 고정**.
- 겹침 방지 알고리즘: 렌더 후 `yaxis.l2p()`로 각 레이블의 실제 픽셀 y를 계산 → 상단부터 정렬 → 간격 15px 미만이면 아래로 밀고 `yshift`(px) 보정 → `plotly_relayout` 이벤트로 줌/팬 시 재계산. 자기 갱신 재진입은 플래그로 차단.

### 5.3 줌/스케일 UX
- 기본 Y축 범위: **spot × [0.9, 1.1]** (현재가 ±10%).
- 가격(Y) 줌: 항상 **spot을 중심점으로 고정**하여 0.85/1.15배 스팬 조절.
- 날짜(X) 줌: 우측 끝(최근일) 앵커 고정. date/category 겸용 숫자 변환 처리.
- X줌 버튼 옆 **가시 일봉 수 배지**: 현재 x range와 교차하는 거래일 수를 계산해 "63일봉" 형태로 실시간 표시.
- 축 스타일: Plotly에서 무효인 `font` 속성을 `tickfont`/`title.font`로 교정하며 전축 흰색 적용.

### 5.4 만기 필터
- 주물 필터를 금요일 단독 → **월(1)·수(3)·금(5)** 으로 보정 (SPY 주간옵션 실제 만기 체계). 월물은 3째주 금요일(15≤일≤21 & 금) 유지.

---

## 6. 데이터 정합성 버그 수정 (차트 붕괴 원인)

- **증상**: 차트 전체 미표시, 콘솔에 `unrecognized date 15:55` 다발.
- **원인**: `stock_history` 테이블에 일봉(`2026-06-29`)과 당일 5분 분봉(`2026-06-29 15:55:00`) 78행이 혼입. 구 빌더가 분봉을 `"15:55"`로 절단해 date축 x값으로 주입 → Plotly 파싱 실패.
- **수정**: 빌더에서 날짜 기준 그룹화 — 정식 일봉 행 우선, 분봉만 있는 날짜는 OHLC 집계(시가=첫봉, 종가=막봉, 고가=max, 저가=min, 거래량=합)로 일봉화. x값은 항상 `YYYY-MM-DD` 보장.
- 진단은 프리뷰 브라우저 콘솔/`gd.data` 실측으로 수행 (63봉 전량 유효 확인).

---

## 7. 알려진 이슈 / TODO

| 항목 | 내용 |
|---|---|
| **KR 옵션 수집 미완** | 41종 중 26종만 적재 후 일시 중단 — `python kr_collect.py` 재실행으로 재개 |
| **Wall 미표시** | 다수 종목에서 Call/Put Wall이 기본 Y범위(±10%) 밖 (예: ARKK spot 80.6 vs wall 35.0) → 선·레이블이 화면 밖. Y범위를 Wall 포함으로 확장하거나 경계 클램프 표시 필요. **미해결** |
| KR 옵션 bid/ask | `inquire-price`에 호가 미포함 — 필요 시 `inquire_asking_price` 추가 연동 |
| 휴장일 갭 | date축이라 주말·휴일 공백 존재. category 축 전환은 부작용으로 롤백 → `rangebreaks` 방식 재시도 예정 |
| FNGU | 옵션 미상장. `etf_list.json`에서 제외 검토 |
| Wall 산정식 | Put Wall을 GEX 최소값으로 선정 중 — put OI 최대 행사가 방식 등 대안 검토 여지 |
| 스크린샷 도구 | 대형 SVG(막대 수천 개) 렌더 시 프리뷰 캡처 30s 타임아웃 간헐 발생 (기능 무관) |

---

## 8. 배포 / 운영

- **GitHub**: `daddypigpapa/option_dashboard` (main). 수집 DB(7.9MB) 포함, `FinanceToolkit_daddypigpapa/`(94MB, 미사용 외부 클론)·로그·캐시는 `.gitignore` 제외.
- **다른 PC에서 재개**:
  ```bash
  git clone https://github.com/daddypigpapa/option_dashboard.git
  cd option_dashboard && pip install -r requirements.txt
  python -m http.server 8080   # → http://localhost:8080/option_dashboard.html
  ```
- **일일 수집**: `python usa_etf_option_collect.py` (전 종목, 완료 시 대시보드 자동 재빌드) / 중단 복구: `python collect_remaining.py`.
- 대시보드는 지연 로딩(`data/*.js` 동적 script 주입) 때문에 로컬 HTTP 서버 경유 접속 권장. `file://` 직접 열기는 브라우저 보안 설정에 따라 차단될 수 있음.

---

# 2차 개발 — 한국 시장 통합 (중간 리포트, 2026-07-02)

## 9. 페이지 스위칭 & 한국 시장 아키텍처

- 대시보드 상단에 시장 전환 탭 3개 추가: **미국 ETF(30) / 한국 ETF(20) / KOSPI 개별주(41)**.
- 빌더가 종목별 `market`(us/kr_etf/kr_stock)·`name`(한글명)·`currency`(USD/KRW)·`has_options` 를 태깅,
  프런트는 활성 탭으로 드롭다운을 필터. 통화별 포맷(₩ 정수 / $ 소수) 자동 전환.
- 옵션 없는 종목은 "옵션 데이터 없음" 안내와 함께 **주가 캔들 전용 차트** 렌더 (빌더가 주가 전용
  티커도 포함하도록 티커 소스를 `option_snapshots ∪ stock_history` 로 확장).
- 종목 목록: `kr_etf_list.json`(거래대금 상위 20), `kospi50_list.json`(시총 상위 50) — 수동 편집 가능.

## 10. 한국투자증권(KIS) OpenAPI 연동

| 구성 요소 | 내용 |
|---|---|
| 인증 | `kis_config.json`(앱키/시크릿, gitignore) → 토큰 발급 `/oauth2/tokenP`, `kis_token.json` 캐시(24h) |
| 주가 일봉 | `FHKST03010100` 기간별시세 (3개월, 정상 동작 확인) |
| 종목마스터 | `fo_stk_code.mst.zip` (KIS 공식 배포) 다운로드·파싱 → 옵션 상장 기초자산 판별, 일일 캐시 |
| 옵션 시세 | `FHMIF10000000` + 시장구분 `JO`, 계약별 조회 (만기 90일 이내 + 행사가 ±30% 필터) |
| 유량 제한 | 호출 간 0.06~0.3초, 마스터/토큰 캐시로 불필요 호출 제거 |

수집 정책(사용자 결정 반영):
- **KOSPI 개별주: 옵션이 실제 상장된 종목만** — 마스터 기준 50종 중 41종. 미상장 9종
  (삼성전자우·우리금융지주·기업은행·현대글로비스·아모레퍼시픽·LG·SK스퀘어·한진칼·S-Oil)은
  수집 제외 + 기존 주가 데이터 삭제.
- **한국 ETF: KRX에 ETF 옵션 시장이 없음** (마스터 실측 0종) → 주가 차트 전용으로 유지.

## 11. 트러블슈팅 — "옵션 시세 전량 0" 원인 규명 (핵심)

**증상**: 삼성전자 236계약 전수 포함 모든 주식옵션이 가격 0·OI 0·과거차트 0행.
MTS에는 계약(미결제)이 존재 → 데이터가 있어야 정상.

**교차 검증 과정**:
1. K200 지수옵션 전광판(`FHPIF05030100`)은 실데이터 정상 수신 → 권한 문제 배제
2. 전광판이 반환하는 실계약 코드(`B01607C42`)와 마스터 단축코드(`5B01607550`) 형식 불일치 발견
3. 삼성전자 옵션으로 재검증 → **마스터 단축코드의 첫 글자(타입 프리픽스: 콜 '5'/풋 '6')를 제거한
   9자리 코드**(`B11607101`)로 조회 시 실데이터 수신 (가격 10,600원 / OI 1,496계약, MTS와 일치)

**교훈**: 존재하지 않는 파생 코드로 조회해도 KIS는 오류가 아닌 **rt_cd=0 + 전부 0인 템플릿**을
반환한다. "값이 0" ≠ "무거래" — 반드시 유동성 있는 대조군(지수옵션)과 코드 형식을 교차 검증할 것.

**추가 수정 2건**:
- KIS 주식옵션 응답의 그릭스 필드 불량(델타 1.0/-0.0 고정, 감마·베가 0) → 미국 파이프라인과 동일하게
  **자체 블랙-숄즈 연산**(`greeks.py`, r=3%)으로 대체. IV 단위 정규화(주식옵션 소수 / 지수옵션 퍼센트).
- **거래승수 반영**: 한국 개별주식옵션 1계약=10주(미국 100주). 빌더 GEX/DEX 산식을
  `mult` 인자화 (`GEX = sign·γ·OI·mult·0.01·S²`, `DEX = δ·OI·mult·S`) — 미국 값은 기존과 동치.

## 12. 진행 상태 (중단 시점 스냅샷)

- 수정된 파이프라인으로 재수집 중 **사용자 요청으로 일시 중단** (46/61 종목 완료)
- DB 적재 현황: 한국 옵션 스냅샷 **26종목 2,898건** (삼성전자 98, SK하이닉스 156 등)
- **재개 방법**: `python kr_collect.py` 재실행 — 일봉은 유니크 제약으로 중복 스킵, 옵션은
  `(collected_date, option_symbol)` 멱등 적재라 그대로 이어받음. 완료 시 대시보드 자동 재빌드.
