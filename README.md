# 부동산 정보 조회 시스템

관심 단지의 실거래 추이, 매물 현황·상세, 일일 부동산 뉴스 요약을 보여 주는 개인용 대시보드. (계획서 v1.2 기준 MVP)

## 처음 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # 그다음 .env 에 공공데이터포털 키 입력
```

## 실행

- **`대시보드 실행.bat`** 더블클릭 → 브라우저에 대시보드가 열린다. 처음이면 프로그램 설치부터 한다. 검은 창을 닫으면 대시보드가 꺼진다.
- **`수집 실행.bat`** 더블클릭 → 관심 단지 전체를 지금 수집한다 (대시보드 없이).
- 대시보드 안에서:
  - 사이드바 **🔄 수동 수집** → 고른 항목(단지 정보·실거래·매물·뉴스)을 전체 관심 단지에 대해 지금 수집
  - 단지 블록의 **수집** → 그 단지만 수집 (단지 정보·그 시군구 실거래·매물)
  - **➕ 관심 단지 등록** → 등록 후 바로 실거래·매물 수집 (체크 해제 가능)
  - 수집은 백그라운드에서 돌고, 동시에 하나만 실행된다. 끝나면 화면이 자동으로 새로 고쳐진다.

명령줄로 실행:

```powershell
# 대시보드 → http://localhost:8501
.\.venv\Scripts\python -m streamlit run app.py

# 일일 배치 (단지 정보 → 실거래 → 매물 → 뉴스)
.\.venv\Scripts\python run_daily.py
.\.venv\Scripts\python run_daily.py --only listing,news   # 일부만
.\.venv\Scripts\python run_daily.py --complex 236         # 특정 단지만

# 매일 05:00 자동 실행 등록
powershell -ExecutionPolicy Bypass -File .\register_task.ps1
```

## 사용 순서

1. 대시보드의 **➕ 관심 단지 등록**에서 이름 검색이나 시/도 › 시군구 › 동 선택으로 단지를 등록한다.
2. '등록 후 바로 수집'이 켜져 있으면 실거래·매물을 바로 받는다. 꺼 두었으면 단지 블록의 **수집**을 누르거나 다음 일일 배치를 기다린다.
   - 새 시군구는 10년치 첫 적재가 함께 진행되어 몇 분 걸린다. 첫 적재는 시군구당 약 300~500회를 호출한다. 하루 한도(`molit.max_calls_per_run`)를 넘으면 다음 날 이어서 받는다.
3. **단지 매핑** 화면에서 국토부 단지명과 네이버 단지가 맞게 연결됐는지 확인하고, 틀리면 고친다.

## 구성

| 경로 | 역할 |
|---|---|
| `collectors/molit_trade.py` | 국토부 매매(상세)·전월세 실거래. 해제 거래 표시, 최근 3개월 매일 다시 받기, 빠진 달 이어 받기 |
| `collectors/naver_client.py` | 네이버페이 부동산 `fin.land.naver.com/front-api` 공통 클라이언트 (2~4초 대기, 429/403 이면 중단) |
| `collectors/naver_complex.py` | 단지 정보·평형, 단지 검색, 법정동 목록, 동별 단지 목록 |
| `collectors/naver_listing.py` | 매물 수집. 네이버 API 구조가 바뀌면 이 파일만 고친다 |
| `collectors/news_rss.py` | 뉴스 수집. Google 뉴스 RSS 키워드 검색 + 언론사 부동산 RSS |
| `processing/mapping.py` | 국토부 단지(aptSeq) ↔ 네이버 단지 자동 매핑 (동 + 지번 + 이름 유사도) |
| `processing/metrics.py` | 전세 환산가, 평형 구간, 금액 표시, 월별 집계 |
| `processing/news_summary.py` | 이슈 묶기(TF-IDF + 군집), 순위(보도한 언론사 수), TextRank 발췌, (선택) Ollama |
| `ui/` | Streamlit 화면 (조회 조건, 단지 블록, 뉴스, 단지 추가, 매핑·수집 현황) |
| `db/realestate.db` | SQLite (금액 단위: 만원) |

## 계획서와 달라진 점

- **뉴스**: 네이버 검색 API 대신 RSS를 쓴다(키 불필요). Google 뉴스는 제목만 주므로 핵심 문장은 언론사 RSS 요약에서 뽑고, 요약문이 없는 이슈는 다른 언론사 제목으로 대신한다.
- **네이버 매물 API**: 예전 `new.land.naver.com` API는 바로 429로 막혀서, 현재 네이버페이 부동산이 쓰는 `fin.land.naver.com/front-api`를 쓴다. 토큰이 필요 없어 Playwright는 쓰지 않는다.
- **단지 매핑**: 국토부 응답의 단지 고유번호(`aptSeq`)를 기준으로 매핑한다.
- **그래프**: 가격(선)과 거래 건수(막대)를 보조 축 하나에 겹치지 않고, 같은 x축을 쓰는 위·아래 두 패널로 나눴다.
- **같은 매물 묶기**: 네이버가 이미 묶어서 주는 정보(대표 매물 + 중개사 수)를 그대로 쓴다.

## 주의

- 네이버 매물은 비공식 API다. 개인용으로 관심 단지만, 하루 1회만 수집하고 수집한 데이터는 외부에 공유하지 않는다.
- 매물이 많은 대단지는 유형별로 최대 `naver.max_pages_per_type` × 30건까지 받는다.
- 국토부 전월세 자료의 신규/갱신 표시는 비어 있는 거래가 많다. '신규만'을 고르면 표시가 없는 거래는 빠진다.
