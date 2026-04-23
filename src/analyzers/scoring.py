"""예측 결과 파싱 + 채점.

크게 2가지:
1) parse_briefing_predictions(text, slot, watchlist) — 브리핑 텍스트에서
   종목별 신호/확률/목표/손절 추출해 Prediction 리스트로 반환.
2) score_unresolved() — 채점 안된 과거 예측들의 실제 결과(yfinance)를
   받아와 outcome 채우기.
"""
from __future__ import annotations

import re
from datetime import timedelta

from src import timez
from src.analyzers.probability import estimate as estimate_probability, anchor_probability
from src.collectors.price import get_snapshot, _to_yf_symbol
from src.storage import predictions_store
from src.storage.predictions_store import Prediction


# 브리핑 라인 매칭용 정규식
_LINE_PAT = re.compile(
    r"•\s*(?P<name>[^\s]+[^\n|]*?)\s*(?P<emoji>🟢|🟡|⚪|🟠|🔴)[^|]*\|\s*상승확률\s*(?P<prob>\d+)\s*%"
)
_PREV_CLOSE_PAT = re.compile(r"📊\s*전일\s*종가\s*₩?([\d,]+)")
_EXPECTED_OPEN_PAT = re.compile(r"📈\s*예상\s*시가\s*≈?\s*₩?([\d,]+)")
_TARGET_PAT = re.compile(r"🎯\s*목표:\s*시가\s*\+?([\d.]+)%\s*≈?\s*₩?([\d,]+)")
_STOP_PAT = re.compile(r"🛑\s*손절:\s*시가\s*-?([\d.]+)%\s*≈?\s*₩?([\d,]+)")


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def parse_briefing_predictions(
    text: str, slot: str, watchlist: list[dict]
) -> list[Prediction]:
    """브리핑 본문에서 종목별 예측을 추출.

    day_trade 슬롯은 시가 기준 목표/손절까지 파싱.
    medium 슬롯은 현재가 기준이라 구조 다름 — 일단 day_trade 만 자세히 파싱.
    """
    name_to_code: dict[str, dict] = {s["name"]: s for s in watchlist}
    today = timez.now().date().isoformat()
    now_ts = timez.now_iso()

    # 텍스트를 "•" 단위 블록으로 분할
    blocks = re.split(r"(?=\n• )", "\n" + text)
    preds: list[Prediction] = []

    for block in blocks:
        m = _LINE_PAT.search(block)
        if not m:
            continue
        name_raw = m.group("name").strip()
        # 매칭 종목 찾기 (prefix 매칭 — "삼성전자 🟢 매수 추천" 에서 "삼성전자" 추출)
        stock = None
        for wname, s in name_to_code.items():
            if block.lstrip().startswith(f"• {wname}") or wname in name_raw:
                stock = s
                break
        if not stock:
            continue

        emoji = m.group("emoji")
        prob = int(m.group("prob"))

        # 숫자 필드 추출 (없으면 None)
        prev_close = None
        expected_open = None
        target_price = target_pct = None
        stop_price = stop_pct = None

        pm = _PREV_CLOSE_PAT.search(block)
        if pm:
            prev_close = float(_to_int(pm.group(1)))
        om = _EXPECTED_OPEN_PAT.search(block)
        if om:
            expected_open = float(_to_int(om.group(1)))
        tm = _TARGET_PAT.search(block)
        if tm:
            target_pct = float(tm.group(1))
            target_price = float(_to_int(tm.group(2)))
        sm = _STOP_PAT.search(block)
        if sm:
            stop_pct = float(sm.group(1))
            stop_price = float(_to_int(sm.group(2)))

        # 앵커 확률 계산 (실측 OHLC 기반)
        anchor = None
        try:
            if target_pct and stop_pct:
                est = estimate_probability(
                    stock["code"], stock["market"],
                    target_pct=target_pct, stop_pct=stop_pct,
                    days=90,
                )
                if est:
                    anchor = anchor_probability(est)
        except Exception:
            pass

        preds.append(Prediction(
            date=today, slot=slot,
            code=stock["code"], name=stock["name"],
            signal=f"{emoji} (브리핑)",  # 전체 신호 텍스트 추출은 생략
            signal_emoji=emoji,
            probability=prob,
            prev_close=prev_close or 0.0,
            expected_open=expected_open,
            target_price=target_price,
            stop_price=stop_price,
            target_pct=target_pct,
            stop_pct=stop_pct,
            anchor_prob=anchor,
            ts=now_ts,
        ))
    return preds


def score_unresolved() -> dict:
    """어제 이전의 채점 안된 예측들을 yfinance 로 결과 채워넣음.

    각 예측에 대해:
      - 예측 일자의 다음 거래일 OHLC 가져옴
      - target_price 도달 여부 (High >= target)
      - stop_price 도달 여부 (Low <= stop)
      - 기록

    반환: {scored: N, skipped: M, errors: K}
    """
    import yfinance as yf
    from datetime import datetime as dt

    targets = predictions_store.unresolved_predictions(cutoff_days_ago=1)
    stats = {"scored": 0, "skipped": 0, "errors": 0}
    for p in targets:
        try:
            market = "KS" if int(p.code) >= 100000 or len(p.code) == 6 else ""
            # 간단히 code 로부터 KS/KQ 추측이 어려우니 둘 다 시도
            for mkt_try in ("KS", "KQ", ""):
                symbol = _to_yf_symbol(p.code, mkt_try)
                try:
                    hist = yf.Ticker(symbol).history(
                        start=p.date, period="7d", auto_adjust=True
                    )
                    if not hist.empty:
                        break
                except Exception:
                    continue
            else:
                stats["errors"] += 1
                continue

            # p.date 다음 거래일 찾기
            pred_date = dt.fromisoformat(p.date).date()
            post_rows = hist[hist.index.date > pred_date]
            if post_rows.empty:
                stats["skipped"] += 1
                continue
            next_row = post_rows.iloc[0]
            actual_open = float(next_row["Open"])
            actual_high = float(next_row["High"])
            actual_low = float(next_row["Low"])
            actual_close = float(next_row["Close"])

            target_hit = bool(p.target_price and actual_high >= p.target_price)
            stop_hit = bool(p.stop_price and actual_low <= p.stop_price)

            predictions_store.mark_outcome(p.key(), {
                "actual_open": actual_open,
                "actual_high": actual_high,
                "actual_low": actual_low,
                "actual_close": actual_close,
                "target_hit": target_hit,
                "stop_hit": stop_hit,
                "resolved_at": timez.now_iso(),
                "hit_by_11am": None,   # 분봉 데이터 붙이면 채움
            })
            stats["scored"] += 1
        except Exception as e:
            print(f"[scoring] {p.key()} 실패: {e}")
            stats["errors"] += 1
    return stats


def format_accuracy_for_prompt(days: int = 30) -> str:
    """다음 브리핑 프롬프트에 주입할 적중률 요약."""
    stats = predictions_store.rolling_accuracy(days)
    if stats["scored"] == 0:
        return (
            "📊 적중률 데이터: 아직 채점된 예측이 없음. "
            "이번 브리핑은 보수적으로 판단할 것."
        )
    by = stats["by_signal"]
    lines = [
        f"📊 최근 {days}일 실제 적중률 (채점 {stats['scored']}건 / 전체 {stats['total']}건)",
        f"   전체 목표가 도달률: {stats['overall_target_hit_rate']}%",
    ]
    for emoji in ("🟢", "🟡", "⚪", "🟠", "🔴"):
        b = by.get(emoji)
        if not b:
            continue
        lines.append(
            f"   {emoji} {b['count']}건 → 목표 {b['hit_rate']}% / 손절 {b['stop_rate']}%"
        )
    lines.append(
        "   ⚠️ 위 실적중률을 참고해 상승확률 보정. "
        "🟢 가 자주 틀렸으면 이번엔 더 보수적으로."
    )
    return "\n".join(lines)
