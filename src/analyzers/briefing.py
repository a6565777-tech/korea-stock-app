"""브리핑 파이프라인: 데이터 수집 → Gemini 분석 → ntfy 발송.

슬롯 4종: morning(08:00) / midday(12:00) / afternoon(14:00) / closing(15:40)
"""
import sys
import traceback
from datetime import datetime
from pathlib import Path

from src.config import load as load_config
from src.collectors.price import get_snapshot, PriceSnapshot
from src.collectors.news import search as search_news, search_macro, NewsItem
from src.analyzers.llm import ask
from src.notifiers.ntfy import send
from src.positions import load as load_positions, enrich_with_market, Position
from src.storage import briefing_cache


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


# ── 슬롯별 메타 ─────────────────────────────────────
SLOTS = {
    "overnight": {
        "title": "🌙 자정 선제 브리핑",
        "emoji": "🌙",
        "focus": (
            "지금은 한국 자정(미국 뉴욕 개장 1~2시간 경과 시점). "
            "현재 미국 증시 움직임(지수·반도체·자동차·원/달러)과 "
            "오늘 낮 한국 뉴스 흐름을 종합해 **내일 아침 8시 한국 장 시작 때 "
            "오를지 내릴지**를 선제적으로 유추해. "
            "특히 미국 개장 후 흐름이 아시아장에 미칠 영향, "
            "밤새 나올 이슈(실적·FOMC·지정학)에 주의. 잠들기 전 참고용."
        ),
        "news_hours": 14,   # 오늘 오후~저녁 뉴스 + 미국 개장 소식
    },
    "morning": {
        "title": "🌅 아침 브리핑",
        "emoji": "🌅",
        "focus": (
            "간밤 해외증시·지정학 이슈를 반영해 오늘 장 시작 시 주목할 종목과 "
            "진입 시그널에 집중해. 장 시작 전 사전 참고용."
        ),
        "news_hours": 18,   # 전날 저녁~오늘 아침 뉴스
    },
    "midday": {
        "title": "🍱 점심 업데이트",
        "emoji": "🍱",
        "focus": (
            "오전장 중 움직임과 그 배경, 오후장 전망에 집중해. "
            "점심시간 빠르게 상황 확인하는 용도."
        ),
        "news_hours": 8,
    },
    "afternoon": {
        "title": "⏰ 오후 체크",
        "emoji": "⏰",
        "focus": (
            "마감 1시간 30분 전 상황. 오늘 고점·저점 대비 현재 위치, "
            "막판 변동성·수급 변화 가능성에 집중해."
        ),
        "news_hours": 6,
    },
    "closing": {
        "title": "🔔 마감 정리",
        "emoji": "🔔",
        "focus": (
            "오늘 종가 결과 요약 + 내일 아침까지 나올 해외 이슈·이벤트 "
            "(미국장, 지정학, 실적 발표 등) 리스크에 집중해. 내일 대비용."
        ),
        "news_hours": 12,
    },
}


# ── 프롬프트 (공통 규칙 + 슬롯별 초점) ───────────────
BASE_SYSTEM_PROMPT = """너는 한국 주식 전문 분석가야. 개인 참고용 브리핑이니 솔직하게 판단해.

각 관심 종목에 대해 다음 5단계 중 **정확히 하나**를 선택해.

[신호 체계 - 반드시 이 중 하나]
🟢 매수 추천    : 강한 호재 + 근거 다수 일치. 신규 진입 고려 가능.
🟡 매수 조심    : 호재 있으나 리스크 공존. 소액/분할 진입 권장.
⚪ 관망         : 방향성 불명확. 신규 매수 X, 보유 중이면 홀드.
🟠 매수 비추천  : 약한 악재, 모멘텀 약화. 신규 진입 X.
🔴 매도 고려    : 강한 악재, 하방 리스크. 손절/익절 점검.

[신뢰도 기준 - 반드시 이 중 하나]
상 : 근거 3개 이상 + 주류 언론 복수 보도 + 대형주 유동성
중 : 근거 1~2개 + 일부 보도 + 중형주
하 : 단편 정보 + 테마·수급 영향 큼 + 뉴스 예측력 제한

[엄격한 규칙]
- 위 5개 신호 중 하나를 골라야 함. 새로운 단계 만들지 마.
- 근거는 실제 제공된 뉴스·수치만 인용. 없으면 "근거 부족"이라 써.
- 휴림로봇같은 테마주는 특별한 호재 없으면 기본 ⚪관망 또는 신뢰도 '하'.
- 한국어. 매우 간결하게. 각 종목 근거는 한 줄.
"""

OUTPUT_FORMAT = """
[출력 형식 - 이 구조 그대로]
━━━ {header} ━━━
🌍 거시 요약: (2줄 이내, 오늘의 핵심 맥락)

• 삼성전자 [신호] | 신뢰도 [상/중/하]
  └ 한 줄 근거
• SK하이닉스 [신호] | 신뢰도 [상/중/하]
  └ 한 줄 근거
• 현대차 [신호] | 신뢰도 [상/중/하]
  └ 한 줄 근거
• 에이피알 [신호] | 신뢰도 [상/중/하]
  └ 한 줄 근거
• 휴림로봇 [신호] | 신뢰도 [상/중/하]
  └ 한 줄 근거
{positions_section}
⚠️ 오늘 주의할 포인트: (1~2줄)
💡 최종 판단은 본인. 시그널은 참고용.
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


def build_context(cfg: dict, news_hours: int = 24) -> tuple[str, list[Position]]:
    """반환: (프롬프트 컨텍스트, 로드된 포지션 리스트)"""
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

    lines.append("\n\n## 관심 종목")
    for stock in cfg["watchlist"]:
        snap = get_snapshot(stock["code"], stock["market"], stock["name"])
        news = search_news(stock["news_keywords"], limit=4, recent_hours=news_hours)
        lines.append(f"\n### {stock['name']} ({stock['code']}) - {stock['sector']}")
        lines.append(f"주요 영향 요인: {', '.join(stock['drivers'])}")
        if snap:
            lines.append(f"현재가: {snap.summary()}")
        lines.append("최근 뉴스:")
        lines.append(_format_news(news, max_n=4))

    # 포지션
    positions = load_positions()
    enrich_with_market(positions, cfg["watchlist"])
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

    return "\n".join(lines), positions


def generate_briefing(cfg: dict, slot: str) -> str:
    meta = SLOTS[slot]
    context, positions = build_context(cfg, news_hours=meta["news_hours"])
    header = f"{meta['title']} ({datetime.now().strftime('%m/%d %H:%M')})"

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

    prompt = (
        BASE_SYSTEM_PROMPT
        + position_rules
        + f"\n[이번 브리핑 초점 - {meta['title']}]\n{meta['focus']}\n"
        + OUTPUT_FORMAT.format(header=header, positions_section=positions_output_block)
        + "\n# 컨텍스트\n"
        + context
    )
    raw = ask(prompt, temperature=0.3)

    # ── 포지션 섹션에 실제 계산된 수익률 주입 ──
    if positions:
        raw = _inject_position_numbers(raw, positions, cfg["watchlist"])
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
