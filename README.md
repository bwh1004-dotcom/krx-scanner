# 📈 UNO SCANNER | KRX 신고가 & 거래량 분석기

> 코스피 + 코스닥 전 종목 52주 신고가 · 연속 신고가 · 거래량 급증 추적기  
> **매일 장 마감(16:35 KST) 자동 업데이트**

---

## 🔧 GitHub 세팅 (최초 1회)

### 1. 저장소 생성 및 파일 업로드
```bash
# 이 폴더 전체를 GitHub에 push
git init
git add .
git commit -m "🚀 초기 세팅"
git remote add origin https://github.com/YOUR_NAME/krx-scanner.git
git push -u origin main
```

### 2. GitHub Pages 활성화
- GitHub 저장소 → **Settings** → **Pages**
- Source: `Deploy from a branch` → `main` branch → `/ (root)`
- 저장 → URL: `https://YOUR_NAME.github.io/krx-scanner`

### 3. GitHub Actions 권한 설정
- **Settings** → **Actions** → **General**
- Workflow permissions → **Read and write permissions** ✅
- Allow GitHub Actions to create and approve pull requests ✅

### 4. 완료 확인
- **Actions** 탭에서 `workflow_dispatch` 로 수동 실행 (첫 실행 확인)
- 첫 실행은 약 **5~10분** 소요 (260일치 데이터 수집)
- 이후 매일 실행은 **1~2분** 이내

---

## 📊 기능

| 탭 | 설명 |
|---|---|
| **52주 신고가** | 오늘 52주 신고가 갱신 종목 전체 |
| **연속 2회+** | 2거래일 이상 연속 신고가 종목 |
| **연속 3회+** | 3거래일 이상 연속 신고가 (강력 모멘텀) |
| **거래량 급증** | 20일 평균 대비 2배 이상 거래량 종목 |
| **신고가 + 거래량** | 두 조건 동시 충족 (핵심 관심 종목) |

### 표시 정보
- 돌파율: 직전 52주 고가 대비 오늘 신고가 상승률
- 연속 일수: 🔥 3회+ | 🔥🔥 5회+
- 첫 신고가 날짜 + 경과일
- 거래량 비율 바 차트

---

## 🗂 파일 구조

```
krx-scanner/
├── index.html                    ← 대시보드 UI
├── scripts/
│   └── fetch_data.py             ← 데이터 수집·분석 (pykrx)
├── data/
│   ├── market_data.json          ← 분석 결과 (HTML이 읽음)
│   └── history.json              ← 260일 히스토리 (Python이 사용)
├── .github/
│   └── workflows/
│       └── update.yml            ← 자동 실행 스케줄
└── README.md
```

---

## ⚙ 로컬 테스트

```bash
pip install pykrx pandas
python scripts/fetch_data.py
```

`data/market_data.json` 생성 확인 후 `index.html`을 브라우저로 열면 됨

---

## 📝 파라미터 조정

`scripts/fetch_data.py` 상단:
```python
LOOKBACK = 260          # 52주 기준 (거래일 수)
VOLUME_AVG_DAYS = 20    # 거래량 비교 기준 (20일 평균)
VOLUME_SPIKE_RATIO = 2.0 # 거래량 급증 기준 (평균 대비 배수)
```

---

*pykrx 사용 | KRX 공식 데이터 | API 키 불필요*
