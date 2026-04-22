"""주가·거래량·거시지표 수집 (yfinance 기반).

기준일(trade_date) 추적 + 스테일 감지:
  yfinance 는 종목별로 "오늘 bar" 생성 시점이 달라서 `iloc[-1]`이
  실제로 오늘 데이터인지 어제 데이터인지 보장 안 됨.
  → 히스토리 인덱스의 날짜를 그대로 snap에 담아, 브리핑 쪽에서
    "이 수치가 실제 언제 기준인지" 표시하고 장 마감/개장 전 혼동을 차단.
"""
from dataclasses import dataclass
from datetime import datetime, date
import yfinance as yf

from src import timez


@dataclass
class PriceSnapshot:
    symbol: str
    name: str
    last: float          # 최근 종가 (장중엔 현재가)
    prev_close: float    # 전일 종가
    change_pct: float    # 등락률 %
    open: float          # 당일 시가 (또는 마지막 거래일 시가)
    high: float          # 당일 고가
    low: float           # 당일 저가
    volume: int          # 당일 거래량
    avg_volume: int      # 20일 평균 거래량
    volume_ratio: float  # 거래량 배수
    week_52_high: float
    week_52_low: float
    # 최근 10거래일 평균 일간 변동폭(%). (고가-저가)/시가.
    # 종목별 현실적 목표/손절 범위 산정용. (삼성 ~1.5%, 테마주 ~6%)
    daily_range_pct: float
    trade_date: date     # last 값의 실제 거래일 (KST 기준)
    prev_trade_date: date  # prev_close 의 실제 거래일
    is_stale: bool       # trade_date 가 오늘(KST)이 아니고 장 시작 후면 True
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
        stale = " ⚠️스테일" if self.is_stale else ""
        return (
            f"{self.name}: {price} {arrow}{abs(self.change_pct):.2f}% "
            f"(거래량 {self.volume_ratio:.1f}x · 일변동폭 {self.daily_range_pct:.1f}% "
            f"· {self.trade_date.isoformat()}{stale})"
        )


def _to_yf_symbol(code: str, market: str) -> str:
    """종목코드 → yfinance 심볼. 이미 yf 심볼이면 그대로 반환."""
    if "." in code or "=" in code or "^" in code:
        return code
    if not market:   # 미국 주식처럼 접미사 없는 경우
        return code
    return f"{code}.{market}"


def _row_date(row_index) -> date:
    """pandas DatetimeIndex 의 한 row → date (tz 제거, 시장 현지 날짜 유지)."""
    try:
        # yfinance 는 종목 상장 시장 tz 로 인덱스를 만듦 (KS/KQ = Asia/Seoul)
        # .date() 는 tz-aware 든 naive 든 현지 날짜만 반환
        return row_index.date()
    except Exception:
        return timez.now().date()


def _is_korean(symbol: str) -> bool:
    return symbol.endswith(".KS") or symbol.endswith(".KQ")


def get_snapshot(code: str, market: str = "KS", name: str | None = None) -> PriceSnapshot | None:
    """단일 종목의 현재 스냅샷. 장 중엔 실시간(15분 지연), 장 외엔 마지막 종가."""
    symbol = _to_yf_symbol(code, market)
    try:
        t = yf.Ticker(symbol)
        # auto_adjust=True 로 배당/액면분할 조정된 가격 사용 → 토스·네이버 표기와 일치
        hist = t.history(period="3mo", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None

        last_row = hist.iloc[-1]
        prev_row = hist.iloc[-2]
        last = float(last_row["Close"])
        prev_close = float(prev_row["Close"])
        change_pct = (last - prev_close) / prev_close * 100 if prev_close else 0.0

        trade_date = _row_date(hist.index[-1])
        prev_trade_date = _row_date(hist.index[-2])

        open_ = float(last_row["Open"])
        high = float(last_row["High"])
        low = float(last_row["Low"])
        volume = int(last_row["Volume"])
        avg_vol = int(hist["Volume"].tail(20).mean())
        vol_ratio = volume / avg_vol if avg_vol else 0.0

        # 최근 10거래일 평균 일간 변동폭(%)
        tail = hist.tail(10)
        daily_range_pct = 0.0
        try:
            ranges = []
            for _, row in tail.iterrows():
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                if o > 0:
                    ranges.append((h - l) / o * 100)
            if ranges:
                daily_range_pct = sum(ranges) / len(ranges)
        except Exception:
            daily_range_pct = 0.0

        # 스테일 판정: 한국 종목 한정, 평일 장 시작(09:00 KST) 이후인데
        # trade_date 가 오늘이 아니면 "오늘 데이터 아직 없음" → 스테일.
        # 주말/휴일은 원래 오늘 데이터가 없는 게 정상이므로 스테일 아님.
        now_kst = timez.now()
        is_stale = False
        if _is_korean(symbol):
            today = now_kst.date()
            # 평일이고 장 시작(09:00) 이후인데 마지막 데이터가 오늘이 아님 → 스테일
            if now_kst.weekday() < 5 and now_kst.time() >= datetime.min.time().replace(hour=9):
                if trade_date < today:
                    is_stale = True

        return PriceSnapshot(
            symbol=symbol,
            name=name or symbol,
            last=last,
            prev_close=prev_close,
            change_pct=change_pct,
            open=open_,
            high=high,
            low=low,
            volume=volume,
            avg_volume=avg_vol,
            volume_ratio=vol_ratio,
            week_52_high=float(hist["High"].max()),
            week_52_low=float(hist["Low"].min()),
            daily_range_pct=daily_range_pct,
            trade_date=trade_date,
            prev_trade_date=prev_trade_date,
            is_stale=is_stale,
            updated=now_kst,
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
        print(f"  시가 ₩{s.open:,.0f} / 고 ₩{s.high:,.0f} / 저 ₩{s.low:,.0f}")
        print(f"  기준일 {s.trade_date} / 전일 {s.prev_trade_date} / 스테일: {s.is_stale}")
    n = get_snapshot("NVDA", "", "엔비디아")
    if n:
        print(n.summary())
