"""브리핑 파이프라인: 데이터 수집 → Gemini 분석 → ntfy 발송.

슬롯:
  overnight 00:00 / morning 08:00 / midday 12:00 / afternoon 14:00 / closing 15:40
  realtime (사용자 수동 호출 - 호출 시각 기준)

각 슬롯은 '기준 시각(reference_time)'을 가짐. 수동 생성이 되더라도 자정 슬롯은
'자정 기준 브리핑'으로 헤더를 찍고, Gemini 프롬프트도 그 시각 기준으로 작성해서
생성 시각과 내용이 불일치하는 혼란을 방지한다. (realtime만 now() 그대로 사용)
"""
import re
import sys
import traceback
from datetime import datetime, time as dtime
from pathlib import Path

from src.config import load as load_config
from src.collectors.price import get_snapshot, PriceSnapshot
from src.collectors.news import search as search_news, search_macro, NewsItem
from src.collectors.flow import get_flow, format_flow_summary
from src.analyzers.llm import ask
from src.notifiers.ntfy import send
from src.positions import load as load_positions, enrich_with_market, Position
from src.storage import briefing_cache, watchlist_store


_LOG_DIR = Path(__file__).parent.parent.parent / "logs"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    # 읽기전용 FS(Vercel 등)에서는 파일 로그 스킵
    try:
        _LOG_DIR.mkdir(exist_ok=True)
        logfile = _LOG_DIR / f"briefing_{datetime.now().strftime('%Y-%m-%d')}.log"
        with logfile.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_market_day(dt: datetime | None = None) -> bool:
    dt = dt or datetime.now()
    return dt.weekday() < 5


# ── 슬롯별 "기준 시각" ─────────────────────────────────
# 사용자가 자정 탭 누르면 생성이 밤 10시에 되더라도 분석 기준은 00:00.
# realtime만 지금 시각 그대로 사용.
_SLOT_REF_HM: dict[str, tuple[int, int] | None] = {
    "overnight": (0, 0),
    "morning": (8, 0),
    "midday": (12, 0),
    "afternoon": (14, 0),
    "closing": (15, 40),
    "realtime": None,  # None = datetime.now()
}


def slot_reference_time(slot: str, now: datetime | None = None) -> datetime:
    """슬롯의 '기준 시각'을 반환.

    예약 스케줄 슬롯(자정/아침/점심/오후/마감)은 그 슬롯이 '원래 돌았어야 할 시각'.
    수동 생성이 늦더라도 헤더/프롬프트는 이 기준 시각을 사용.
    realtime은 지금 시각.
    """
    now = now or datetime.now()
    hm = _SLOT_REF_HM.get(slot)
    if hm is None:
        return now
    h, m = hm
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


# ── 장 상태 감지 (KST) ─────────────────────────────────
# 한국 정규장: 평일 09:00 ~ 15:30
# 동시호가: 08:30~09:00(시가), 15:20~15:30(종가) — 매매 불가 취급
# 시간외 단일가: 15:40~16:00, 16:00~18:00 — 개인 매매 가능하지만 얕음
_KR_OPEN = dtime(9, 0)
_KR_CLOSE = dtime(15, 30)


def market_status(dt: datetime | None = None) -> dict:
    """현재 장 상태.

    반환: {"state": "open"|"pre"|"after"|"holiday", "label": str, "tradable": bool}
    """
    dt = dt or datetime.now()
    if dt.weekday() >= 5:
        return {"state": "holiday", "label": "주말/휴일 (매매 불가)", "tradable": False}
    t = dt.time()
    if _KR_OPEN <= t <= _KR_CLOSE:
        return {"state": "open", "label": "장 중 (실시간 매매 가능)", "tradable": True}
    if t < _KR_OPEN:
        return {"state": "pre", "label": "장 시작 전 (다음 시초가 대기)", "tradable": False}
    return {"state": "after", "label": "장 마감 후 (다음 영업일 시초가 대기)", "tradable": False}


# ── 슬롯별 메타 ─────────────────────────────────────
# mode: "day_trade" (예약매수·시초가 매도 전략) / "medium" (중기 관점 진입/목표/손절)
SLOTS = {
    "overnight": {
        "title": "🌙 자정 선제 브리핑",
        "emoji": "🌙",
        "mode": "day_trade",
        "focus": (
            "지금은 한국 자정(미국 뉴욕 개장 1~2시간 경과 시점). "
            "미국 증시 움직임(지수·반도체·자동차·원/달러)과 오늘 낮 한국 뉴스를 종합해 "
            "**내일 아침 시초가 예약매수** 전략을 세워. "
            "간밤 미국장 결과로 한국장이 ±몇% 갭업/갭다운 열릴지 추정하고, "
            "예약매수 GO/NO-GO를 명확히 판단. 잠들기 전 다음날 주문 세팅용."
        ),
        "news_hours": 14,
    },
    "morning": {
        "title": "🌅 아침 브리핑",
        "emoji": "🌅",
        "mode": "day_trade",
        "focus": (
            "장 시작 30분 전. 간밤 미국장 마감·지정학 이슈·환율을 반영해 "
            "**시초가 예약매수 최종 GO/NO-GO**를 판단. "
            "자정 브리핑 이후 바뀐 게 있는지 체크, 갭업 크기 재추정."
        ),
        "news_hours": 18,
    },
    "realtime": {
        "title": "⚡ 실시간 체크",
        "emoji": "⚡",
        "mode": "day_trade",
        "focus": (
            "사용자가 아무 때나 수동 호출. 현재 시점 기준 당일 데이트레이딩 판단. "
            "장 중이면 현재 시가 대비 움직임과 남은 시간 승부 가능성, "
            "장 외면 다음 장 시초가 예약매수 관점."
        ),
        "news_hours": 6,
    },
    "midday": {
        "title": "🍱 점심 업데이트",
        "emoji": "🍱",
        "mode": "medium",
        "focus": (
            "오전장 중 움직임과 그 배경, 오후장 전망에 집중해. "
            "점심시간 빠르게 상황 확인하는 용도."
        ),
        "news_hours": 8,
    },
    "afternoon": {
        "title": "⏰ 오후 체크",
        "emoji": "⏰",
        "mode": "medium",
        "focus": (
            "마감 1시간 30분 전 상황. 오늘 고점·저점 대비 현재 위치, "
            "막판 변동성·수급 변화 가능성에 집중해."
        ),
        "news_hours": 6,
    },
    "closing": {
        "title": "🔔 마감 정리",
        "emoji": "🔔",
        "mode": "medium",
        "focus": (
            "오늘 종가 결과 요약 + 내일 아침까지 나올 해외 이슈·이벤트 "
            "(미국장, 지정학, 실적 발표 등) 리스크에 집중해. 내일 대비용."
        ),
        "news_hours": 12,
    },
}


# ── 데이트레이딩 프롬프트 (overnight/morning/realtime) ────────
DAY_TRADE_SYSTEM_PROMPT = """너는 한국 주식 데이트레이딩 전문가야.
사용자 전략: 아침 시초가 예약매수 → 9:00~11:00 중 익절/손절 → 2시간 승부.

[신호 체계 - 반드시 이 중 하나]
🟢 매수 추천    : 예약매수 GO. 갭업 +3% 이하 + 호재 + 수급 동반.
🟡 매수 조심    : 시그널 있으나 리스크. 소액 예약 or 장 초반 확인 후 진입.
⚪ 관망         : 방향성 불명확. 예약매수 보류.
🟠 매수 비추천  : 약세 우세 or 갭업 과열. 오늘 패스.
🔴 매도 고려    : 강한 악재 + 수급 이탈. 보유 시 정리.

[시초가 갭 예측 - 필수]
간밤 미국장(엔비디아·S&P·나스닥) + 환율 + 밤새 뉴스로 시초가가
전일 종가 대비 ±몇% 열릴지 반드시 추정.
  예: "엔비디아 +3% → 삼성전자 갭업 +1.5~+2% 예상"
  예: "원화 강세 + 자동차 관세 우려 → 현대차 갭다운 -1% 예상"

[갭 대응 규칙 - 엄격]
- 갭업 +3% 이상 예상 → 무조건 🟠 매수 비추천 (추격 금지, 고점 매수 위험)
- 갭다운 -2% 이상 예상 → 🟠 매수 비추천 (악재 있음, 하락 지속 가능)
- 갭 -1% ~ +2% → 정상 범위, 호재·수급 보고 신호 결정

[★ 종목별 목표/손절 범위 - 매우 중요, 이전 고정 규칙은 폐기]
하드코딩된 "+2.0% / -2.0%"는 쓰지 마. 각 종목의 **일간 평균 변동폭(%)** 을
컨텍스트에서 확인하고 그 수치로 현실적 범위를 직접 제시해.

기본 가이드 (일간 변동폭 기준):
  - 변동폭 ≤ 1.5% (대형 저변동: 삼성전자·LG전자 등)
      → 목표 시가 +0.7~+1.2% / 손절 시가 -0.8~-1.0%
  - 변동폭 1.5~2.5% (중변동 대형주: SK하이닉스·현대차 등)
      → 목표 시가 +1.0~+1.8% / 손절 시가 -1.0~-1.3%
  - 변동폭 2.5~4% (중형주·업종 민감주)
      → 목표 시가 +1.5~+2.5% / 손절 시가 -1.5~-2.0%
  - 변동폭 > 4% (테마주·소형주: 휴림로봇 등)
      → 목표 시가 +2.5~+5% / 손절 시가 -3~-5%

규칙:
- "시가 +2% 목표"같은 하드코딩 금지. **종목 고유 변동폭 수치를 근거로 제시**.
- 예: "(일변동 1.3%이라) 목표 시가 +1.0%, 손절 시가 -1.0%"
- 대형주에 +2% 목표 쓰지 마 (비현실적으로 한 번 장중 도달 어려움).
- 체결 조건은 슬롯별 지침에 맞춰(아래 [체결 조건] 참고).

[체결 조건 - 슬롯별]
- overnight/morning (장외 또는 개장 전): "예약매수: 시가 ±0.5% 이내일 때만 체결"
- realtime 장중: "현재가 기준 즉시 매수" 또는 "대기 매수 범위 ±0.3%"
- realtime 장외: "내일 시초가 예약매수 관점. 오늘 매매 불가"

[상승 확률 - 0~100% 정수]
"장 시작 후 11시까지 목표가 도달 확률"을 숫자로.
  75~90% : 강한 호재 + 외인·기관 동반 매수 + 갭업 +1% 이내
  55~74% : 호재 우세, 수급 양호
  40~54% : 방향성 애매 (동전던지기)
  25~39% : 약세 우세 or 갭 과열
  10~24% : 강한 악재 + 수급 이탈
극단값(95%+, 10%-) 지양.

[수급 해석]
- 외인·기관 둘 다 N일 연속 순매수 → 시초가 강세 확률 ↑ (+10~15%)
- 둘 다 순매도 → 하락 가능성 (-10~15%)
- 대형주(삼성전자·하이닉스·현대차)는 수급이 핵심
- 테마주(휴림로봇)는 수급 변동 커서 참고만

[출력 순서 - 중요]
종목 리스트는 아래 신호 우선순위로 정렬. 매수 추천을 가장 위에.
  1. 🟢 매수 추천 (최상단)
  2. 🟡 매수 조심
  3. ⚪ 관망
  4. 🟠 매수 비추천
  5. 🔴 매도 고려 (최하단)
같은 신호 내에서는 상승확률 높은 순.

[엄격한 규칙]
- 신호 5개 중 하나만.
- 근거는 실제 뉴스·수치·수급만. 지어내지 마.
- **전일 종가는 컨텍스트의 "확정 전일 종가 ₩N" 값을 그대로 써. 절대 다른 숫자 쓰지 마.**
- **목표/손절 % 는 반드시 종목별 일변동폭 수치를 인용**. "일변동 X%이라 목표 +Y%" 형식.
- 수급 언급 시 "외인 3일 순매수 12만주"처럼 구체 수치.
- 각 종목 블록 사이에 빈 줄 하나 넣어서 가독성 확보.
- 한국어, 간결하게.
"""

DAY_TRADE_OUTPUT_FORMAT = """
[출력 형식 - 이 구조 그대로. 종목 순서는 신호 우선순위(🟢→🟡→⚪→🟠→🔴)로 재배열.]
━━━ {header} ━━━
🕐 기준: {reference_line}
🏛️ 시장 상태: {market_line}
🌍 간밤/현재 맥락: (미국장 결과 + 환율 + 주요 이슈, 2줄)

{stocks_section}
{positions_section}
⚠️ 오늘 이벤트/주의: (FOMC·실적·지정학 등 1~2줄)
💡 목표·손절은 종목 일변동폭 기반. 범위 벗어난 추격 금지. 손절은 즉시 지킬 것.
"""


# ── 중기 프롬프트 (midday/afternoon/closing) ───────────────
BASE_SYSTEM_PROMPT = """너는 한국 주식 전문 분석가야. 개인 참고용 브리핑이니 솔직하게 판단해.

각 관심 종목에 대해 아래 5단계 신호 중 **정확히 하나**를 선택하고,
상승 확률(0~100%)과 진입/목표/손절가까지 제시해.

[신호 체계 - 반드시 이 중 하나]
🟢 매수 추천    : 강한 호재 + 근거 다수 일치 + 수급 동반. 신규 진입 고려.
🟡 매수 조심    : 호재 있으나 리스크 공존. 소액/분할 진입 권장.
⚪ 관망         : 방향성 불명확. 신규 매수 X, 보유 중이면 홀드.
🟠 매수 비추천  : 약한 악재, 모멘텀 약화. 신규 진입 X.
🔴 매도 고려    : 강한 악재, 하방 리스크. 손절/익절 점검.

[상승 확률 - 0~100% 정수]
주어진 뉴스·거시·수급을 종합해 "목표 기간 내 상승 확률"을 숫자로 제시.
  80~95% : 강한 호재 다수 일치 + 외인·기관 동반 순매수
  60~79% : 호재 우세하나 리스크 공존
  45~59% : 방향성 불명확
  30~44% : 약세 기운 우세
  10~29% : 강한 악재 + 수급 이탈
극단값(100%, 0%)은 쓰지 마. 근거 부족하면 50% 근처로.

[진입/목표/손절가 - 현재가 기준 산출]
  - 진입가: 현재가 ±2% 내 분할 진입 범위 (예: 73,000~74,500)
  - 목표가: 호재 강도에 따라 현재가 +3~+10% (매수 추천은 +5~+10%, 매수 조심은 +3~+5%)
  - 손절가: 현재가 -2~-5% (대형주 -2~-3%, 테마주 -4~-7%)
  - 기간: 단기(1~2주) / 중기(2~4주) / 스윙(1~3개월) 중 하나
  ⚪관망·🟠비추천·🔴매도 신호는 진입/목표 대신 "—"로 표시, 손절만 유지.

[수급 해석 규칙 - 매우 중요]
외국인·기관 순매수 데이터를 다음처럼 반영:
  - 둘 다 N일 연속 순매수 → 강한 호재 시그널 (상승확률 +10~15%, 신호 한 단계 상향 고려)
  - 한쪽만 지속 순매수 → 약한 호재 (상승확률 +5%)
  - 둘 다 순매도 → 약세 시그널 (상승확률 -10~15%, 신호 한 단계 하향 고려)
  - 개인만 매수 + 외인·기관 매도 → 대부분 하락 (경계)
대형주(삼성전자·SK하이닉스·현대차)는 수급이 뉴스보다 더 강한 단기 신호.
테마주(휴림로봇 등)는 수급 변동 크므로 참고만.

[출력 순서 - 중요]
종목 리스트는 아래 신호 우선순위로 정렬. 매수 추천을 가장 위에.
  1. 🟢 매수 추천 (최상단)
  2. 🟡 매수 조심
  3. ⚪ 관망
  4. 🟠 매수 비추천
  5. 🔴 매도 고려 (최하단)
같은 신호 내에서는 상승확률 높은 순.

[엄격한 규칙]
- 위 5개 신호 중 하나만. 새로운 단계 만들지 마.
- 근거는 실제 제공된 뉴스·수치·수급만 인용. 지어내지 마.
- **현재가·전일 종가는 컨텍스트의 실제 값을 그대로 써. 절대 다른 숫자 쓰지 마.**
- 수급 언급 시 "외인 3일 순매수 12만주"처럼 구체 숫자 포함.
- 가격은 현재가 기준 반올림(천원 단위), 원 기호 ₩ 붙이기.
- 테마주(소형주)는 강한 호재 + 수급 확인 없으면 기본 ⚪관망.
- 각 종목 블록 사이에 빈 줄 하나 넣어서 가독성 확보.
- 한국어. 매우 간결하게. 각 종목 근거는 한 줄.
"""

OUTPUT_FORMAT = """
[출력 형식 - 이 구조 그대로. 종목 순서는 신호 우선순위(🟢→🟡→⚪→🟠→🔴)로 재배열.]
━━━ {header} ━━━
🕐 기준: {reference_line}
🏛️ 시장 상태: {market_line}
🌍 거시 요약: (2줄 이내, 오늘의 핵심 맥락)

{stocks_section}
{positions_section}
⚠️ 오늘 주의할 포인트: (1~2줄)
💡 시그널은 참고용. 손절가는 반드시 지킬 것. 최종 판단은 본인.
"""

POSITION_SIGNALS = """
[포지션 전용 신호 - 반드시 이 중 하나]
🟢 홀드 유지    : 추세·호재 살아있음, 목표가까지 보유
🟡 부분 익절    : 수익 쌓임 + 리스크 증가, 50% 정도 정리
🟠 전량 익절    : 목표 도달 or 상승 동력 끝, 전량 매도
🔴 손절 고려    : 시나리오 틀어짐, 악재 명확, 리스크 관리
🔵 추가 매수    : 일시 조정, 펀더멘털 견고, 평단 낮추기
⚪ 무판단       : 근거 부족 (기본값)

포지션 판단은 다음을 반영:
- 현재 손익률과 절대 수익액 (단기 급등 후엔 익절 고려)
- 매수 이유(note)와 지금 상황의 정합성
- 뉴스·거시 상황이 여전히 호재/악재 유지되는지
"""

POSITION_FORMAT = """
━━━ 💼 내 포지션 ━━━
• {name} {qty}주 @₩{buy_price} | 현재 ₩{cur_price}
  {pct}% ({pnl}원)
  [신호] 근거 한 줄
...
"""


def _format_prices(snaps: list[PriceSnapshot]) -> str:
    return "\n".join(f"- {s.summary()}" for s in snaps)


def _format_news(items: list[NewsItem], max_n: int = 5) -> str:
    if not items:
        return "  (최근 뉴스 없음)"
    return "\n".join(f"  • {n.line()}" for n in items[:max_n])


def _resolve_watchlist(cfg: dict) -> list[dict]:
    """Redis(앱에서 추가한 종목 포함) 우선. 실패 시 config.yaml 로 폴백.
    앱 추가 종목은 drivers/news_keywords 없으므로 기본값 채워넣음."""
    try:
        items = watchlist_store.list_watchlist() or []
    except Exception as e:
        print(f"[briefing] watchlist_store 실패, config.yaml 폴백: {e}")
        items = []
    if not items:
        items = list(cfg.get("watchlist", []))

    out = []
    for s in items:
        name = s.get("name", str(s.get("code", "")))
        out.append({
            "code": str(s.get("code", "")),
            "market": s.get("market", "KS"),
            "name": name,
            "sector": s.get("sector", ""),
            # 앱 추가 종목엔 없음 → 종목명으로 기본 검색
            "drivers": s.get("drivers") or [name],
            "news_keywords": s.get("news_keywords") or [name],
        })
    return out


def build_context(cfg: dict, news_hours: int = 24) -> tuple[str, list[Position], list[dict]]:
    """반환: (프롬프트 컨텍스트, 로드된 포지션 리스트, 실제 사용된 watchlist)"""
    lines = [f"# 오늘 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} (KST)\n"]

    lines.append("## 거시 지표")
    macro_snaps = []
    for m in cfg["macro"]:
        s = get_snapshot(m["ticker"], "", m["name"])
        if s:
            macro_snaps.append(s)
    lines.append(_format_prices(macro_snaps) or "- (데이터 없음)")

    lines.append(f"\n## 거시 뉴스 (최근 {news_hours}시간)")
    macro_news = search_macro(limit_per_topic=2)
    for topic, items in macro_news.items():
        lines.append(f"\n[{topic}]")
        lines.append(_format_news(items, max_n=2))

    watchlist = _resolve_watchlist(cfg)
    lines.append("\n\n## 관심 종목")
    for stock in watchlist:
        snap = get_snapshot(stock["code"], stock["market"], stock["name"])
        news = search_news(stock["news_keywords"], limit=4, recent_hours=news_hours)
        lines.append(f"\n### {stock['name']} ({stock['code']}) - {stock['sector']}")
        lines.append(f"주요 영향 요인: {', '.join(stock['drivers'])}")
        if snap:
            lines.append(f"현재가: {snap.summary()}")
            # Gemini가 숫자를 지어내는 문제 방지 — 확정값을 명시적으로 박아둠
            lines.append(
                f"★ 확정 현재가: ₩{snap.last:,.0f}  "
                f"★ 확정 전일 종가: ₩{snap.prev_close:,.0f}  "
                f"★ 일간 평균 변동폭: {snap.daily_range_pct:.1f}%  "
                f"(이 값들을 그대로 쓸 것. 목표/손절 %는 일변동폭 기반으로 산출)"
            )
        lines.append("최근 뉴스:")
        lines.append(_format_news(news, max_n=4))
        # 외국인·기관 수급 (실패 시 조용히 스킵)
        flow = get_flow(stock["code"], days=5)
        if flow:
            lines.append("수급:")
            lines.append("  " + format_flow_summary(flow).replace("\n", "\n  "))

    # 포지션
    positions = load_positions()
    enrich_with_market(positions, watchlist)
    if positions:
        lines.append("\n\n## 내 보유 포지션 (개인화 판단용)")
        for p in positions:
            snap = get_snapshot(p.code, p.market, p.name)
            if not snap:
                continue
            pnl = p.pnl(snap.last)
            lines.append(f"\n### {p.name} ({p.code}) - {p.quantity}주")
            lines.append(f"매수가: ₩{p.buy_price:,.0f} / 현재가: ₩{snap.last:,.0f}")
            lines.append(f"수익률: {pnl['pct']:+.2f}% ({pnl['unrealized']:+,.0f}원)")
            if p.note:
                lines.append(f"매수 이유: {p.note}")
            if p.target_price:
                lines.append(f"목표가: ₩{p.target_price:,.0f} ({'도달' if pnl['target_hit'] else '미도달'})")
            if p.stop_loss:
                lines.append(f"손절가: ₩{p.stop_loss:,.0f} ({'도달' if pnl['stop_hit'] else '미도달'})")

    return "\n".join(lines), positions, watchlist


def _build_stocks_template(stocks: list[dict], mode: str) -> str:
    """출력 형식의 종목 블록 뼈대 — 관심종목 실제 구성으로 동적 생성.
    Gemini는 이걸 보고 같은 수만큼, 같은 형식으로 답변."""
    blocks = []
    for s in stocks:
        name = s["name"]
        if mode == "day_trade":
            blocks.append(
                f"• {name} [신호] | 상승확률 [N]%\n"
                f"  └ 한 줄 근거 (미국장 반응 + 수급 + 뉴스)\n"
                f"  📊 전일 종가 ₩[확정 전일 종가 그대로] / 갭 예상 [±N%] / 일변동 [X.X]%\n"
                f"  💰 [체결조건] / 🎯 시가 +[Y]% (변동폭 근거) / 🛑 시가 -[Z]% (변동폭 근거)\n"
                f"  ⏱️ 데이 (9:00~11:00)"
            )
        else:
            blocks.append(
                f"• {name} [신호] | 상승확률 [N]%\n"
                f"  └ 한 줄 근거 (뉴스 + 수급 구체 수치)\n"
                f"  💰 진입 ₩[하]~₩[상] / 🎯 ₩[목표] / 🛑 ₩[손절]\n"
                f"  ⏱️ [단기/중기/스윙]"
            )
    return "\n\n".join(blocks)  # 블럭 사이 빈 줄


def _inject_prev_close_numbers(text: str, stocks: list[dict]) -> str:
    """Gemini 가 전일 종가를 지어내면 실제 yfinance 값으로 덮어씀 (day_trade 전용)."""
    for s in stocks:
        snap = get_snapshot(s["code"], s["market"], s["name"])
        if not snap:
            continue
        name = re.escape(s["name"])
        # "• 종목명 ..." 줄 이후 500자 이내 첫 "📊 전일 종가 ₩XXX"를 실제값으로 교체
        pattern = re.compile(
            rf"(•\s*{name}[\s\S]{{0,500}}?📊\s*전일\s*종가\s*)₩?[\d,]+",
        )
        text = pattern.sub(
            lambda m: f"{m.group(1)}₩{snap.prev_close:,.0f}", text, count=1
        )
    return text


def generate_briefing(cfg: dict, slot: str) -> str:
    meta = SLOTS[slot]
    now = datetime.now()
    ref = slot_reference_time(slot, now)
    mstat = market_status(now)

    context, positions, watchlist = build_context(cfg, news_hours=meta["news_hours"])

    # 헤더: "기준 시각"을 제목에, "업데이트 시각"은 별도 라인
    if slot == "realtime":
        header = f"{meta['title']} (기준 {ref.strftime('%m/%d %H:%M')})"
        reference_line = f"지금 시각 {ref.strftime('%Y-%m-%d %H:%M')} — 실시간 판단"
    else:
        header = f"{meta['title']} (기준 {ref.strftime('%m/%d %H:%M')})"
        update_note = f"업데이트 {now.strftime('%m/%d %H:%M')}"
        reference_line = (
            f"{ref.strftime('%Y-%m-%d %H:%M')} 기준 분석 · {update_note}"
        )
    market_line = mstat["label"]
    mode = meta.get("mode", "medium")

    # realtime이 장외일 때는 '지금 매매 불가 — 다음 시초가 예약' 모드로 힌트
    market_hint = ""
    if slot == "realtime" and not mstat["tradable"]:
        market_hint = (
            f"\n[★ 현재 {mstat['label']}]\n"
            "현재 시각엔 시장가 매매가 불가능해. 그러므로:\n"
            "- 체결 조건은 '다음 시초가 예약매수 ±0.5%'로 제시\n"
            "- 목표·손절도 '시가 기준'으로 산출 (현재가 기준 X)\n"
            "- 갭 예상·간밤 미국장 영향을 최우선 고려\n"
        )
    elif slot == "realtime" and mstat["tradable"]:
        market_hint = (
            f"\n[★ 현재 {mstat['label']}]\n"
            "현재 장 중이므로 실시간 현재가 기준 판단:\n"
            "- 체결 조건은 '현재가 ±0.3% 즉시 매수 또는 대기'\n"
            "- 목표·손절은 '현재가 기준 종목별 일변동폭'으로 산출\n"
            "- 남은 장 시간과 현재까지의 움직임 맥락을 반영\n"
        )

    # 포지션 출력은 2단계로 처리:
    # 1) 출력 형식에선 "숫자는 이미 확정됨, [신호]+[근거]만 채워라"로 안내
    # 2) 응답 후 Python이 [신호]·[근거] 위에 실제 숫자를 덮어씀 (오차 0%)
    if positions:
        # 프롬프트용 템플릿 (AI는 이 뼈대를 그대로 따라함)
        positions_output_block = "\n━━━ 💼 내 포지션 ━━━\n"
        positions_output_block += (
            "(아래 각 포지션에 대해 [신호]와 [근거]만 채워. "
            "수익률/금액은 Python이 계산하므로 절대 지어내지 마.)\n"
        )
        for p in positions:
            positions_output_block += (
                f"• {p.name} {p.quantity}주 @₩{p.buy_price:,.0f}\n"
                f"  [신호] [근거]\n"
            )
        positions_output_block += "\n"
        position_rules = POSITION_SIGNALS
    else:
        positions_output_block = ""
        position_rules = ""

    # 모드별 프롬프트 선택
    if mode == "day_trade":
        system_prompt = DAY_TRADE_SYSTEM_PROMPT
        output_format = DAY_TRADE_OUTPUT_FORMAT
    else:
        system_prompt = BASE_SYSTEM_PROMPT
        output_format = OUTPUT_FORMAT

    stocks_section = _build_stocks_template(watchlist, mode)

    # 출력 포맷에 reference_line/market_line 주입.
    # medium 프롬프트는 기존 포맷이 해당 플레이스홀더를 아직 안 가지므로 safe하게 처리.
    try:
        formatted_output = output_format.format(
            header=header,
            stocks_section=stocks_section,
            positions_section=positions_output_block,
            reference_line=reference_line,
            market_line=market_line,
        )
    except KeyError:
        formatted_output = output_format.format(
            header=header,
            stocks_section=stocks_section,
            positions_section=positions_output_block,
        )

    prompt = (
        system_prompt
        + position_rules
        + f"\n[이번 브리핑 초점 - {meta['title']}]\n{meta['focus']}\n"
        + f"[기준 시각] {reference_line}\n"
        + f"[시장 상태] {market_line}\n"
        + market_hint
        + formatted_output
        + "\n# 컨텍스트\n"
        + context
    )
    raw = ask(prompt, temperature=0.3)

    # ── 전일 종가 지어낸 것을 실제값으로 덮어씀 (day_trade 슬롯) ──
    if mode == "day_trade":
        raw = _inject_prev_close_numbers(raw, watchlist)
    # ── 포지션 섹션에 실제 계산된 수익률 주입 ──
    if positions:
        raw = _inject_position_numbers(raw, positions, watchlist)
    return raw


def _inject_position_numbers(text: str, positions: list[Position], watchlist: list[dict]) -> str:
    """브리핑 텍스트의 포지션 라인 아래에 실제 수익률·금액을 삽입."""
    enrich_with_market(positions, watchlist)
    for p in positions:
        snap = get_snapshot(p.code, p.market, p.name)
        if not snap:
            continue
        pnl = p.pnl(snap.last)
        stat_line = (
            f"  현재 ₩{snap.last:,.0f} | "
            f"{pnl['pct']:+.2f}% ({pnl['unrealized']:+,.0f}원)"
        )
        # "• {name} {qty}주 @₩{price}" 줄 바로 아래에 stat_line 삽입
        header_line = f"• {p.name} {p.quantity}주 @₩{p.buy_price:,.0f}"
        if header_line in text:
            text = text.replace(header_line, header_line + "\n" + stat_line, 1)
    return text


def run(slot: str = "morning", send_push: bool = True, force: bool = False) -> str:
    if slot not in SLOTS:
        raise ValueError(f"알 수 없는 슬롯: {slot}. 가능: {list(SLOTS.keys())}")
    if not force and not is_market_day():
        _log(f"[{slot}] 주말이라 스킵")
        return ""

    meta = SLOTS[slot]
    _log("=" * 50)
    _log(f"{meta['title']} 시작")
    try:
        cfg = load_config()
        briefing = generate_briefing(cfg, slot)
        _log("Gemini 분석 완료")
        print(briefing)

        # 앱에서 조회할 수 있게 캐시 저장
        try:
            briefing_cache.save(slot, briefing)
        except Exception as e:
            _log(f"브리핑 캐시 저장 실패 (무시): {e}")

        logfile = _LOG_DIR / f"briefing_{datetime.now().strftime('%Y-%m-%d')}.log"
        with logfile.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {meta['title']} 본문 ---\n{briefing}\n")

        if send_push:
            ok = send(
                message=briefing,
                title=f"{meta['title']} {datetime.now().strftime('%m/%d %H:%M')}",
                priority=4,
                tags=["chart_with_upwards_trend"],
            )
            _log("ntfy 발송 " + ("성공" if ok else "실패"))
        return briefing
    except Exception as e:
        err = f"{meta['title']} 실패: {e}\n{traceback.format_exc()}"
        _log(err)
        try:
            send(
                message=f"{meta['title']} 생성 실패.\n{e}",
                title="⚠️ 브리핑 오류",
                priority=4,
                tags=["warning"],
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    # 사용법: python -m src.analyzers.briefing [morning|midday|afternoon|closing] [--force]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    slot = args[0] if args else "morning"
    run(slot=slot, send_push=True, force=force)
