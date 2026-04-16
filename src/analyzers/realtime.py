"""실시간 경보 (스마트 필터링):
   규칙 기반 트리거 → AI 판단 → 매수추천/매도고려 신호일 때만 알림.

장중(09:00~15:30) 5분마다 체크. 각 종목 쿨다운 2시간.
"""
import json
import sys
import time
import traceback
from datetime import datetime, time as dtime
from pathlib import Path

from src.config import load as load_config
from src.collectors.price import get_snapshot, PriceSnapshot
from src.collectors.news import search as search_news
from src.analyzers.llm import ask
from src.notifiers.ntfy import send
from src.positions import load as load_positions, enrich_with_market, Position


_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOG_DIR.mkdir(exist_ok=True)
_COOLDOWN_FILE = _DATA_DIR / "last_alerts.json"

# ── 규칙 기반 트리거 기준 ─────────────────────────
TRIGGER_PCT = 3.0          # ±3% 이상 변동 시 후보
TRIGGER_VOL_MULT = 3.0     # 거래량 평소 대비 3배 이상 시 후보
COOLDOWN_MINUTES = 120     # 같은 종목 2시간 중복 억제

# ── 장 시간 ──────────────────────────────────────
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
CHECK_INTERVAL_SEC = 300   # 5분


# ── LLM 프롬프트: 관심 종목용 (미보유) ─────────────
WATCH_PROMPT = """너는 한국 주식 분석가야. 주어진 종목이 지금 이상 움직임을 보이고 있어.
제공되는 최근 뉴스와 수치를 근거로 **정확히** 다음 5단계 중 하나를 골라:

🟢 매수 추천    : 강한 호재 근거 있고 진입 타이밍 양호
🟡 매수 조심    : 호재 있으나 리스크 공존
⚪ 관망         : 근거 부족 또는 혼조 (기본값)
🟠 매수 비추천  : 약한 악재, 추격 매수 위험
🔴 매도 고려    : 강한 악재, 하방 리스크 명확

[엄격한 규칙]
- 뉴스에 명확한 근거가 없으면 무조건 ⚪ 관망.
- 단순 "수급" "차익실현" "테마" 만으로는 🟢/🔴 금지.
- 근거는 제공된 뉴스만 인용. 지어내지 마.
- 한국어, 매우 간결.

[출력 - 이 형식 그대로, 다른 말 붙이지 마]
신호: [🟢매수 추천 | 🟡매수 조심 | ⚪관망 | 🟠매수 비추천 | 🔴매도 고려]
근거: (한 줄, 구체적 뉴스·수치 인용)
신뢰도: [상/중/하]
"""

# ── LLM 프롬프트: 보유 포지션용 ─────────────
POSITION_PROMPT = """너는 한국 주식 분석가야. 사용자가 실제 보유 중인 종목이 이상 움직임을 보이고 있어.
손익률·매수 이유·뉴스를 종합해 **정확히** 다음 중 하나를 골라:

🟢 홀드 유지    : 추세·호재 살아있음, 목표가까지 보유
🟡 부분 익절    : 수익 쌓임 + 리스크 증가, 50% 정도 정리
🟠 전량 익절    : 목표 도달 or 상승 동력 끝
🔴 손절 고려    : 시나리오 틀어짐, 악재 명확
🔵 추가 매수    : 일시 조정, 펀더멘털 견고, 평단 낮추기
⚪ 무판단       : 근거 부족

[판단 기준]
- 수익률이 +10% 이상이고 단기 급등 후라면 부분익절 고려
- 손실이 -5% 이상이고 악재 명확하면 손절 고려
- 매수 이유가 여전히 유효한지 뉴스로 검증
- 근거는 제공된 정보만. 지어내지 마.

[출력 - 이 형식 그대로]
신호: [🟢홀드 유지 | 🟡부분 익절 | 🟠전량 익절 | 🔴손절 고려 | 🔵추가 매수 | ⚪무판단]
근거: (한 줄, 구체적 수치·뉴스 인용)
신뢰도: [상/중/하]
"""


# ── 쿨다운 저장/조회 ─────────────────────────────
def _load_cooldown() -> dict[str, str]:
    if _COOLDOWN_FILE.exists():
        try:
            return json.loads(_COOLDOWN_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cooldown(d: dict[str, str]) -> None:
    _COOLDOWN_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_on_cooldown(code: str, cooldown: dict[str, str]) -> bool:
    last = cooldown.get(code)
    if not last:
        return False
    last_dt = datetime.fromisoformat(last)
    return (datetime.now() - last_dt).total_seconds() < COOLDOWN_MINUTES * 60


def _mark_alerted(code: str, cooldown: dict[str, str]) -> None:
    cooldown[code] = datetime.now().isoformat()
    _save_cooldown(cooldown)


# ── 로깅 ────────────────────────────────────────
def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    logfile = _LOG_DIR / f"realtime_{datetime.now().strftime('%Y-%m-%d')}.log"
    try:
        with logfile.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 트리거 판별 ─────────────────────────────────
def _should_analyze(snap: PriceSnapshot) -> tuple[bool, str]:
    reasons = []
    if abs(snap.change_pct) >= TRIGGER_PCT:
        reasons.append(f"변동 {snap.change_pct:+.2f}%")
    if snap.volume_ratio >= TRIGGER_VOL_MULT:
        reasons.append(f"거래량 {snap.volume_ratio:.1f}x")
    return (bool(reasons), " + ".join(reasons))


# ── LLM 판단 ────────────────────────────────────
def _parse_llm_response(response: str) -> dict:
    signal = reason = confidence = ""
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("신호:"):
            signal = line.split(":", 1)[1].strip()
        elif line.startswith("근거:"):
            reason = line.split(":", 1)[1].strip()
        elif line.startswith("신뢰도:"):
            confidence = line.split(":", 1)[1].strip()
    return {"signal": signal, "reason": reason, "confidence": confidence, "raw": response}


def _analyze_watch(stock: dict, snap: PriceSnapshot, trigger: str) -> dict:
    news = search_news(stock["news_keywords"], limit=5, recent_hours=6)
    news_block = "\n".join(f"  • {n.line()}" for n in news) or "  (최근 6시간 뉴스 없음)"
    context = f"""# 종목: {stock['name']} ({stock['code']}) - {stock['sector']}
# 트리거: {trigger}
# 현재가: {snap.summary()}
# 주요 영향 요인: {', '.join(stock['drivers'])}

# 최근 6시간 뉴스:
{news_block}
"""
    response = ask(WATCH_PROMPT + "\n\n" + context, temperature=0.2)
    return _parse_llm_response(response)


def _analyze_position(stock: dict, pos: Position, snap: PriceSnapshot, trigger: str) -> dict:
    news = search_news(stock.get("news_keywords", [pos.name]), limit=5, recent_hours=6)
    news_block = "\n".join(f"  • {n.line()}" for n in news) or "  (최근 6시간 뉴스 없음)"
    pnl = pos.pnl(snap.last)
    context = f"""# 보유 종목: {pos.name} ({pos.code})
# 트리거: {trigger}
# 매수 정보: {pos.quantity}주 @ ₩{pos.buy_price:,.0f} (매수일 {pos.buy_date or '-'})
# 매수 이유: {pos.note or '-'}
# 현재가: ₩{snap.last:,.0f}
# 수익률: {pnl['pct']:+.2f}% ({pnl['unrealized']:+,.0f}원)
# 목표가: {f"₩{pos.target_price:,.0f} ({'도달' if pnl['target_hit'] else '미도달'})" if pos.target_price else '미지정 (AI 판단)'}
# 손절가: {f"₩{pos.stop_loss:,.0f} ({'도달' if pnl['stop_hit'] else '미도달'})" if pos.stop_loss else '미지정 (AI 판단)'}
# 주요 영향 요인: {', '.join(stock.get('drivers', []))}

# 최근 6시간 뉴스:
{news_block}
"""
    response = ask(POSITION_PROMPT + "\n\n" + context, temperature=0.2)
    return _parse_llm_response(response)


# ── 알림 발송 ───────────────────────────────────
def _watch_actionable(signal: str) -> bool:
    """관심종목: 🟢매수추천 / 🔴매도고려만 알림."""
    return "🟢" in signal or "매도 고려" in signal or "🔴" in signal


def _position_actionable(signal: str) -> bool:
    """보유종목: 홀드/무판단 외엔 전부 알림 대상 (익절·손절·추가매수는 전부 중요 액션)."""
    return any(x in signal for x in ["🟡", "🟠", "🔴", "🔵"])


def _send_watch_alert(stock: dict, snap: PriceSnapshot, analysis: dict, trigger: str) -> bool:
    signal = analysis["signal"]
    is_buy = "🟢" in signal
    priority = 5 if is_buy or "🔴" in signal else 4
    tag = "chart_with_upwards_trend" if is_buy else "warning"
    toss_link = f"supertoss://stock/A{stock['code']}"
    msg = f"""{signal}
{snap.summary()}
트리거: {trigger}
━━━━━━━━━━
📰 {analysis['reason']}
신뢰도: {analysis['confidence']}
━━━━━━━━━━
⚠️ 데이터 15~20분 지연. 판단은 본인."""
    return send(
        message=msg, title=f"⚡ {stock['name']} 실시간",
        priority=priority, tags=[tag], click_url=toss_link,
    )


def _send_position_alert(pos: Position, snap: PriceSnapshot, analysis: dict,
                         trigger: str, target_hit: bool, stop_hit: bool) -> bool:
    signal = analysis["signal"]
    # 우선순위: 목표가/손절가 도달 → 최우선 긴급, 손절/전량익절 → 긴급, 부분익절/추가매수 → 중요
    if target_hit or stop_hit:
        priority = 5
        tag = "dart" if target_hit else "stop_sign"
        header_prefix = "🎯 목표가 도달" if target_hit else "🛑 손절가 도달"
    elif "🔴" in signal or "🟠" in signal:
        priority = 5
        tag = "warning"
        header_prefix = "💼 포지션 경보"
    else:
        priority = 4
        tag = "moneybag"
        header_prefix = "💼 포지션 업데이트"

    pnl = pos.pnl(snap.last)
    toss_link = f"supertoss://stock/A{pos.code}"
    msg = f"""{signal}
{pos.name} {pos.quantity}주 @₩{pos.buy_price:,.0f}
현재 ₩{snap.last:,.0f} | {pnl['pct']:+.2f}% ({pnl['unrealized']:+,.0f}원)
트리거: {trigger}
━━━━━━━━━━
📰 {analysis['reason']}
신뢰도: {analysis['confidence']}
━━━━━━━━━━
⚠️ 데이터 15~20분 지연. 판단은 본인."""
    return send(
        message=msg, title=f"{header_prefix} - {pos.name}",
        priority=priority, tags=[tag], click_url=toss_link,
    )


# ── 메인 루프 ───────────────────────────────────
def check_once(cfg: dict, cooldown: dict[str, str]) -> int:
    """1 사이클 체크. 반환: 발송된 알림 수.

    우선순위:
    1) 보유 포지션의 목표가/손절가 도달 → 무조건 긴급 알림 (쿨다운 무시)
    2) 보유 포지션의 가격/거래량 이상 → 포지션 전용 분석
    3) 관심종목(미보유) 가격/거래량 이상 → 관심종목 분석
    """
    sent = 0

    positions = load_positions()
    enrich_with_market(positions, cfg["watchlist"])
    position_codes = {p.code for p in positions}
    stock_by_code = {s["code"]: s for s in cfg["watchlist"]}

    # ─ 1) 포지션 우선 체크 ─
    for pos in positions:
        snap = get_snapshot(pos.code, pos.market, pos.name)
        if not snap:
            continue
        pnl = pos.pnl(snap.last)
        target_hit = pnl["target_hit"]
        stop_hit = pnl["stop_hit"]

        # 목표가/손절가 도달은 쿨다운도 무시하는 최우선 긴급
        if target_hit or stop_hit:
            reason = "🎯 목표가 도달" if target_hit else "🛑 손절가 도달"
            _log(f"긴급: {pos.name} ({reason})")
            try:
                stock = stock_by_code.get(pos.code, {"name": pos.name, "code": pos.code})
                analysis = _analyze_position(stock, pos, snap, reason)
                _log(f"  AI 판단: {analysis['signal']} / {analysis['confidence']}")
                if _send_position_alert(pos, snap, analysis, reason, target_hit, stop_hit):
                    _mark_alerted(pos.code, cooldown)
                    sent += 1
                    _log(f"  → 긴급 알림 발송")
            except Exception as e:
                _log(f"  포지션 분석 실패: {e}")
            continue

        # 쿨다운 체크
        if _is_on_cooldown(pos.code, cooldown):
            continue

        # 가격/거래량 트리거
        trigger_hit, trigger_reason = _should_analyze(snap)
        if not trigger_hit:
            continue

        _log(f"포지션 트리거: {pos.name} ({trigger_reason})")
        try:
            stock = stock_by_code.get(pos.code, {"name": pos.name, "code": pos.code})
            analysis = _analyze_position(stock, pos, snap, trigger_reason)
            _log(f"  AI 판단: {analysis['signal']} / {analysis['confidence']}")
            if _position_actionable(analysis["signal"]):
                if _send_position_alert(pos, snap, analysis, trigger_reason, False, False):
                    _mark_alerted(pos.code, cooldown)
                    sent += 1
                    _log(f"  → 포지션 알림 발송")
            else:
                _log(f"  → 홀드/무판단 - 알림 안 함")
        except Exception as e:
            _log(f"  포지션 분석 실패: {e}")

    # ─ 2) 미보유 관심종목 체크 ─
    for stock in cfg["watchlist"]:
        code = stock["code"]
        if code in position_codes:
            continue  # 포지션에서 이미 처리됨
        if _is_on_cooldown(code, cooldown):
            continue
        snap = get_snapshot(code, stock["market"], stock["name"])
        if not snap:
            continue
        trigger_hit, trigger_reason = _should_analyze(snap)
        if not trigger_hit:
            continue

        _log(f"관심 트리거: {stock['name']} ({trigger_reason})")
        try:
            analysis = _analyze_watch(stock, snap, trigger_reason)
            _log(f"  AI 판단: {analysis['signal']} / {analysis['confidence']}")
            if _watch_actionable(analysis["signal"]):
                if _send_watch_alert(stock, snap, analysis, trigger_reason):
                    _mark_alerted(code, cooldown)
                    sent += 1
                    _log(f"  → 알림 발송 ({stock['name']})")
            else:
                _log(f"  → 관망/비액션 - 알림 안 함")
        except Exception as e:
            _log(f"  분석 실패: {e}")

    return sent


def is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:   # 주말
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def monitor_loop() -> None:
    """장중 상시 체크. 마감시 종료."""
    cfg = load_config()
    cooldown = _load_cooldown()
    _log("실시간 모니터 시작")
    _log(f"트리거: ±{TRIGGER_PCT}% 또는 거래량 {TRIGGER_VOL_MULT}x 이상")
    _log(f"쿨다운: {COOLDOWN_MINUTES}분")

    try:
        while is_market_open():
            sent = check_once(cfg, cooldown)
            _log(f"사이클 완료 (알림 {sent}건)")
            time.sleep(CHECK_INTERVAL_SEC)
        _log("장 마감 - 모니터 종료")
    except KeyboardInterrupt:
        _log("수동 중단")
    except Exception as e:
        _log(f"모니터 오류: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    # --once : 1회만 체크 (테스트용)
    # --test : 장외라도 강제 실행
    if "--once" in sys.argv:
        cfg = load_config()
        cooldown = _load_cooldown()
        sent = check_once(cfg, cooldown)
        _log(f"1회 체크 완료 - 알림 {sent}건")
    elif "--test" in sys.argv:
        _log("테스트 모드: 장 시간 무시")
        cfg = load_config()
        cooldown = _load_cooldown()
        sent = check_once(cfg, cooldown)
        _log(f"테스트 완료 - 알림 {sent}건")
    else:
        monitor_loop()
