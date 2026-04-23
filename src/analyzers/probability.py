"""통계 기반 상승확률 엔진.

목적:
  Gemini 에게 "상승확률 %" 를 물으면 그럴듯한 숫자를 찍을 뿐 칼리브레이션 안 됨.
  이 모듈은 **과거 OHLCV 데이터로 실측 도달률을 계산**해서 앵커로 제공.
  Gemini 는 이 숫자 기준 ±3% 만 조정 가능 (프롬프트 F5 규칙).

계산하는 것:
  1) 무조건 도달률 (Baseline): 과거 60일 중 장중 High 가 시가 대비 +X% 이상 기록한 비율
  2) 갭 조건부 도달률: 비슷한 갭 크기(±0.5% 허용)에서의 도달률
  3) 드로우다운 확률: 장중 Low 가 시가 대비 -Y% 이하로 내려간 비율 (손절 트리거)

한계:
  - yfinance 일봉 데이터만 사용 (분봉은 30일치밖에 안 받아짐).
    "11시까지 도달" 아니라 "장 중 언젠가 도달" 확률. 상관관계 높음 but 동일 X.
  - 샘플 크기 작으면(<10) confidence=low. UI/프롬프트에 명시.
"""
from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf

from src.collectors.price import _to_yf_symbol


@dataclass
class ProbabilityEstimate:
    # 입력
    symbol: str
    target_pct: float        # 시가 대비 목표 상승률 %
    stop_pct: float          # 시가 대비 손절 하락률 %
    gap_pct: float | None    # 조건부 계산용 (없으면 무조건부만)

    # 계산 결과
    unconditional_hit: float     # 과거 전체에서 목표 도달률 (0~1)
    unconditional_stop: float    # 과거 전체에서 손절 도달률
    conditional_hit: float | None  # 비슷한 갭 조건에서의 도달률
    conditional_stop: float | None

    # 샘플 크기
    total_days: int
    conditional_days: int | None

    # 신뢰도 등급
    confidence: str   # "high" / "medium" / "low"

    def summary_line(self) -> str:
        """프롬프트에 주입할 요약 1~2줄."""
        uhit = round(self.unconditional_hit * 100, 1)
        ustop = round(self.unconditional_stop * 100, 1)
        parts = [
            f"📊 역사적 도달률 (과거 {self.total_days}일, {self.symbol}):",
            f"  ◦ 무조건부: 장중 +{self.target_pct:.1f}% 도달 {uhit}% / -{self.stop_pct:.1f}% 하락 {ustop}%",
        ]
        if self.conditional_hit is not None and self.conditional_days and self.conditional_days >= 5:
            chit = round(self.conditional_hit * 100, 1)
            cstop = round(self.conditional_stop * 100, 1)
            parts.append(
                f"  ◦ 갭 {self.gap_pct:+.1f}% 유사조건(샘플 {self.conditional_days}건): "
                f"도달 {chit}% / 손절 {cstop}%"
            )
        parts.append(f"  ◦ 신뢰도: {self.confidence}")
        parts.append(
            f"  ⚠️ 상승확률은 '도달률'을 앵커로 쓸 것. 이 값±3% 범위에서만 조정 가능."
        )
        return "\n".join(parts)


def _confidence(total: int, conditional: int | None) -> str:
    """샘플 크기 기반 신뢰도."""
    if total < 20:
        return "low"
    if conditional and conditional >= 15:
        return "high"
    if conditional and conditional >= 5:
        return "medium"
    # 무조건부만 있는 경우
    if total >= 50:
        return "medium"
    return "low"


def estimate(
    code: str,
    market: str,
    target_pct: float = 1.5,
    stop_pct: float = 1.5,
    gap_pct: float | None = None,
    days: int = 90,
    gap_tolerance: float = 0.5,
) -> ProbabilityEstimate | None:
    """과거 N일 OHLC로 목표/손절 도달률 계산.

    Args:
      target_pct: 시가 대비 목표 상승률 (%). 예: 1.5 → +1.5%
      stop_pct: 시가 대비 손절 하락률 (%, 양수 입력). 예: 1.5 → -1.5%
      gap_pct: 오늘 예상 갭 (%, 예: +0.5). None 이면 무조건부만.
      days: 과거 몇 일 보낼지 (보통 60~90일).
      gap_tolerance: 갭 조건부 허용 오차. ±0.5% 이내 비슷한 갭.
    """
    symbol = _to_yf_symbol(code, market)
    try:
        hist = yf.Ticker(symbol).history(period=f"{days + 10}d", auto_adjust=True)
    except Exception as e:
        print(f"[prob] {symbol} 조회 실패: {e}")
        return None
    if hist.empty or len(hist) < 20:
        return None

    # 최근 N일로 자름 (마지막 1일은 "오늘"이라 제외 — 아직 장 진행 중일 수 있음)
    hist = hist.tail(days + 1).iloc[:-1]
    if len(hist) < 10:
        return None

    # 각 일자별로 계산:
    #  gap_actual = (Open - prev_Close) / prev_Close * 100
    #  hit = (High - Open) / Open * 100 >= target_pct
    #  stop = (Low - Open) / Open * 100 <= -stop_pct
    prev_close = hist["Close"].shift(1)
    opens = hist["Open"]
    highs = hist["High"]
    lows = hist["Low"]

    gap_actual = (opens - prev_close) / prev_close * 100
    hit_mask = (highs - opens) / opens * 100 >= target_pct
    stop_mask = (lows - opens) / opens * 100 <= -stop_pct

    # prev_close NaN 제거 (첫 날)
    valid = ~prev_close.isna()
    gap_actual = gap_actual[valid]
    hit_mask = hit_mask[valid]
    stop_mask = stop_mask[valid]
    total = len(hit_mask)
    if total == 0:
        return None

    unconditional_hit = float(hit_mask.mean())
    unconditional_stop = float(stop_mask.mean())

    conditional_hit = None
    conditional_stop = None
    conditional_days = None
    if gap_pct is not None:
        lo = gap_pct - gap_tolerance
        hi = gap_pct + gap_tolerance
        cond = (gap_actual >= lo) & (gap_actual <= hi)
        conditional_days = int(cond.sum())
        if conditional_days >= 3:
            conditional_hit = float(hit_mask[cond].mean())
            conditional_stop = float(stop_mask[cond].mean())

    return ProbabilityEstimate(
        symbol=symbol,
        target_pct=target_pct,
        stop_pct=stop_pct,
        gap_pct=gap_pct,
        unconditional_hit=unconditional_hit,
        unconditional_stop=unconditional_stop,
        conditional_hit=conditional_hit,
        conditional_stop=conditional_stop,
        total_days=total,
        conditional_days=conditional_days,
        confidence=_confidence(total, conditional_days),
    )


def anchor_probability(est: ProbabilityEstimate) -> int:
    """도달률을 0~100 정수 '상승확률' 앵커로 변환.

    단순히 hit rate 를 % 로 쓰면 50% 언저리에 쏠림.
    대신 hit rate 와 stop rate 를 같이 고려한 기대값 기반 신호 강도:
        score = (hit - stop) / 2 + 50
    예: hit=35%, stop=25% → score = 5 + 50 = 55 (약한 긍정)
    예: hit=20%, stop=40% → score = -10 + 50 = 40 (약한 부정)
    조건부 데이터 있으면 우선, 없으면 무조건부.
    """
    if est.conditional_hit is not None and est.conditional_days and est.conditional_days >= 5:
        hit = est.conditional_hit
        stop = est.conditional_stop or 0.0
    else:
        hit = est.unconditional_hit
        stop = est.unconditional_stop
    raw = (hit - stop) * 50 + 50   # 스케일 조정 (0.3 차이 → ±15)
    # 현실적 범위로 클램프 (과신 방지)
    return max(30, min(60, round(raw)))


if __name__ == "__main__":
    # 빠른 테스트
    for code, name in [("005930", "삼성전자"), ("090710", "휴림로봇")]:
        est = estimate(code, "KS" if code == "005930" else "KQ",
                       target_pct=1.5, stop_pct=1.0, gap_pct=0.5)
        if est:
            print(f"\n=== {name} ({code}) ===")
            print(est.summary_line())
            print(f"앵커 확률: {anchor_probability(est)}%")
