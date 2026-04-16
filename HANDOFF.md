# 🔄 프로젝트 핸드오프 문서

**이 파일을 새 Claude 세션 시작 시 통째로 붙여넣으면 이어서 작업 가능합니다.**

---

## 📌 프로젝트 개요

- **이름**: 한국 주식 AI 알림 시스템
- **목적**: 실시간 뉴스/정세를 반영해서 관심종목 상승·하락 시그널을 푸시 알림으로 받기. 토스증권 매수 참고용.
- **용도**: 개인용. 배포·서비스 아님. 법적 리스크 없음.
- **개발 PC**: Windows 11, Python 3.14
- **프로젝트 경로**: `C:\Users\Phoary\Desktop\주식AI알림`

---

## ✅ 현재까지 완료

1. 프로젝트 구조 생성
2. Gemini API 연결 (무료 티어, 폴백 체인 포함)
3. ntfy.sh 푸시 연결 (토픽: `phoary-stock-alert-xY9kQ2`)
4. yfinance 주가 수집기 (관심종목 5개 + 거시지표 5개)
5. Google News RSS 뉴스 수집기 (키 불필요)
6. **아침 브리핑 파이프라인 E2E 작동 확인** — 핸드폰에 푸시까지 성공

---

## ⏭️ 다음 할 일

- [ ] 자동 스케줄러 (매일 아침 8시) — 2가지 방식 중 선택:
  - **A안**: Windows 작업 스케줄러 (PC가 켜져 있을 때만)
  - **B안**: Oracle Cloud Free Tier VM 배포 (24/7)
- [ ] 실시간 가격 경보 (±3% / ±5%) — 한국투자증권 API 신청 후
- [ ] AI 추천 종목 레이더 — 급등주 스크리닝

---

## 🧰 기술 스택 및 설계 결정

| 항목 | 선택 | 이유 |
|------|------|------|
| Python | 3.14 (이미 설치됨) | 사용자 환경 |
| LLM | Gemini 2.5 Flash (무료) | Claude 품질 85%, 월 0원 |
| 주가 데이터 | yfinance (`005930.KS` 등) | pykrx는 numpy 빌드 실패로 제외 |
| 뉴스 | Google News RSS | API 키 불필요 |
| 푸시 | ntfy.sh | 무료, iOS·안드 OK |
| DB | 아직 없음 (SQLite 예정) | 이후 히스토리용 |

### 중요 결정 사항
- **LLM 공급자 추상화**: `src/analyzers/llm.py::ask()` 한 함수로 래핑. 나중에 Claude 교체 시 model 인자만 바꾸면 됨.
- **모델 폴백 체인**: 503/UNAVAILABLE 시 `gemini-2.5-flash` → `gemini-2.5-flash-lite` → `gemini-flash-latest` 자동 시도.
- **인코딩**: 실행 시 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` 필수 (Windows cp949 이슈).

---

## 📁 파일 구조

```
주식AI알림/
├── .env                 # 🔑 API 키 (Gemini 키 들어있음, KIS/Naver 미발급)
├── .env.example
├── .gitignore
├── requirements.txt
├── config.yaml          # 관심종목·거시지표·알림시간·기준
├── test_connection.py   # Gemini+ntfy 연결 테스트
├── HANDOFF.md           # 이 파일
└── src/
    ├── __init__.py
    ├── config.py                  # config.yaml 로더
    ├── collectors/
    │   ├── price.py               # yfinance 래퍼
    │   └── news.py                # Google News RSS
    ├── analyzers/
    │   ├── llm.py                 # Gemini 래퍼 (폴백 체인)
    │   └── briefing.py            # 아침 브리핑 파이프라인
    └── notifiers/
        └── ntfy.py                # ntfy 푸시 발송
```

---

## 🔑 환경변수 (.env)

> ⚠️ 실제 값은 `.env` (gitignored) 및 GitHub Secrets에만 저장. 공개 문서에 절대 포함 금지.

```
GEMINI_API_KEY=<YOUR_KEY>                      # Google AI Studio에서 발급
KIS_APP_KEY=                                   # (선택) 한국투자증권 OpenAPI
KIS_APP_SECRET=
KIS_ACCOUNT_NO=
NAVER_CLIENT_ID=                               # (선택)
NAVER_CLIENT_SECRET=
NTFY_TOPIC=<YOUR_NTFY_TOPIC>                   # 추측 불가한 무작위 문자열 권장
UPSTASH_REDIS_REST_URL=<YOUR_UPSTASH_URL>
UPSTASH_REDIS_REST_TOKEN=<YOUR_UPSTASH_TOKEN>
TZ=Asia/Seoul
```

---

## 📊 관심 종목 (config.yaml)

| 종목 | 코드 | 시장 | 섹터 |
|------|------|------|------|
| 삼성전자 | 005930 | KS | 반도체 |
| SK하이닉스 | 000660 | KS | 반도체 |
| 현대차 | 005380 | KS | 자동차 |
| 에이피알 | 278470 | KS | 화장품/뷰티디바이스 |
| 휴림로봇 | 090710 | KQ | 로봇 |

각 종목에 `drivers`(민감 요인)와 `news_keywords`(뉴스 검색어)가 정의되어 있음.

---

## 🚀 실행 방법

```bash
cd "C:\Users\Phoary\Desktop\주식AI알림"

# 연결 테스트 (Gemini + ntfy)
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python test_connection.py

# 아침 브리핑 수동 실행 (전체 파이프라인)
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m src.analyzers.briefing

# 개별 모듈 테스트
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m src.collectors.price
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m src.collectors.news
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m src.config
```

---

## 🧠 Gemini에 보내는 프롬프트 (시스템 지시)

```
너는 한국 주식 전문 분석가야.
주어진 데이터(거시 지표, 뉴스, 종목 현재가)를 바탕으로 각 관심 종목에 대해:

1. 신호: 🟢긍정 / ⚪중립 / 🔴부정 (이모지 그대로 사용)
2. 한 줄 근거 (왜 그렇게 판단했는지, 뉴스나 수치 인용)
3. 신뢰도: 상/중/하 (뉴스 커버리지와 근거 강도 기반)

중요 규칙:
- 절대로 매수/매도를 명령하지 마. "참고 시그널"일 뿐.
- 뉴스에 없는 사실 지어내지 마. 근거 부족하면 "근거 부족"이라고 써.
- 단기 테마주(휴림로봇 등)는 "수급 영향 큼, 뉴스 예측력 제한적"임을 반영.
- 한국어로 답해. 매우 간결하게.

출력 형식 (엄격히):
━━━ 📊 오늘의 브리핑 ━━━
🌍 거시 요약: (2줄 이내)
• 종목명 🟢/⚪/🔴 | 신뢰도 상/중/하
  └ 한 줄 근거
⚠️ 오늘 주의할 포인트: (1~2줄)
```

프롬프트는 `src/analyzers/briefing.py::SYSTEM_PROMPT` 상수.
컨텍스트(거시지표 수치 + 거시뉴스 + 종목별 현재가·뉴스)는 `build_context()`에서 매번 새로 조립.

---

## 💬 사용자 선호 및 제약

- **한국어**로 응답
- 법적 리스크 걱정 없음 (개인용)
- 무료 위주. 나중에 Claude 업그레이드 가능하게 설계는 유지.
- 알림 시간 변경 가능하게 해야 함 (config.yaml에서 수정)
- 토스증권으로 수동 매수 (자동매매 X)

---

## 🏁 집에서 이어서 작업하려면

1. 이 프로젝트 폴더(`주식AI알림`)를 통째로 USB/클라우드 드라이브에 복사
2. 집 PC에 Python 3.11~3.14 설치
3. 의존성 설치: `pip install google-genai python-dotenv requests pyyaml yfinance feedparser apscheduler`
4. 새 Claude 세션에 이 `HANDOFF.md` 붙여넣고 "이어서 작업해줘" 라고 말하기

---

**마지막 작업 시점 요약**: 아침 브리핑 MVP 완성. 실제 Gemini 분석 결과 품질 우수(이란사태·엔비디아AI·HBM 등 실시간 반영 확인). 다음은 자동 스케줄러 결정 대기 중 (Windows 작업 스케줄러 vs Oracle Cloud).
