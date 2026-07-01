# 미국 ETF 옵션 분석 대시보드 — 기술 구현 리포트

작성일: 2026-07-02 · 저장소: https://github.com/daddypigpapa/option_dashboard

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
| **Wall 미표시** | 다수 종목에서 Call/Put Wall이 기본 Y범위(±10%) 밖 (예: ARKK spot 80.6 vs wall 35.0) → 선·레이블이 화면 밖. Y범위를 Wall 포함으로 확장하거나 경계 클램프 표시 필요. **미해결** |
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
