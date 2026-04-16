"""주가·거래량·거시지표 수집 (yfinance 기반)"""
from dataclasses import dataclass
from datetime import datetime
import yfinance as yf


@dataclass
class PriceSnapshot:
    symbol: str
    name: str
    last: float          # 최근 종가
    prev_close: float    # 전일 종가
    change_pct: float    # 등락률 %
    volume: int          # 당일 거래량
    avg_volume: int      # 20일 평균 거래량
    volume_ratio: float  # 거래량 배수
    week_52_high: float
    week_52_low: float
    updated: datetime

    def summary(self) -> str:
        arrow = "▲" if self.change_pct > 0 else ("▼" if self.change_pct < 0 else "—")
        # 한국 주식(.KS/.KQ)은 ₩, 환율/원자재는 단위 생략, 나머지는 $
        if self.symbol.endswith(".KS") or self.symbol.endswith(".KQ"):
            price = f"₩{self.last:,.0f}"
        elif "=" in self.symbol or "^" in self.symbol:
            price = f"{self.last:,.2f}"
        else:
            price = f"${self.last:,.2f}"
        return (
            f"{self.name}: {price} {arrow}{abs(self.change_pct):.2f}% "
            f"(거래량 {self.volume_ratio:.1f}x)"
        )


def _to_yf_symbol(code: str, market: str) -> str:
    """종목코드 → yfinance 심볼. 이미 yf 심볼이면 그대로 반환."""
    if "." in code or "=" in code or "^" in code:
        return code
    if not market:   # 미국 주식처럼 접미사 없는 경우
        return code
    return f"{code}.{market}"


def get_snapshot(code: str, market: str = "KS", name: str | None = None) -> PriceSnapshot | None:
    """단일 종목의 현재 스냅샷. 장 중엔 실시간(15분 지연), 장 외엔 마지막 종가."""
    symbol = _to_yf_symbol(code, market)
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="3mo", auto_adjust=False)
        if hist.empty or len(hist) < 2:
            return None

        last_row = hist.iloc[-1]
        prev_row = hist.iloc[-2]
        last = float(last_row["Close"])
        prev_close = float(prev_row["Close"])
        change_pct = (last - prev_close) / prev_close * 100 if prev_close else 0.0

        volume = int(last_row["Volume"])
        avg_vol = int(hist["Volume"].tail(20).mean())
        vol_ratio = volume / avg_vol if avg_vol else 0.0

        return PriceSnapshot(
            symbol=symbol,
            name=name or symbol,
            last=last,
            prev_close=prev_close,
            change_pct=change_pct,
            volume=volume,
            avg_volume=avg_vol,
            volume_ratio=vol_ratio,
            week_52_high=float(hist["High"].max()),
            week_52_low=float(hist["Low"].min()),
            updated=datetime.now(),
        )
    except Exception as e:
        print(f"[price] {symbol} 조회 실패: {e}")
        return None


def get_many(items: list[dict]) -> list[PriceSnapshot]:
    """
    config의 watchlist 또는 macro 리스트를 받아 일괄 조회.
    items: [{"code": "005930", "market": "KS", "name": "삼성전자"}, ...]
           또는 [{"ticker": "NVDA", "name": "엔비디아"}, ...]
    """
    out = []
    for it in items:
        code = it.get("code") or it.get("ticker")
        market = it.get("market", "")
        name = it.get("name", code)
        snap = get_snapshot(code, market, name)
        if snap:
            out.append(snap)
    return out


if __name__ == "__main__":
    # 빠른 테스트
    s = get_snapshot("005930", "KS", "삼성전자")
    if s:
        print(s.summary())
    n = get_snapshot("NVDA", "", "엔비디아")
    if n:
        print(n.summary())
