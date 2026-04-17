"""네이버 모바일 JSON API로 종목별 수급(외인·기관·개인) 수집.

엔드포인트: https://m.stock.naver.com/api/stock/{code}/trend?pageSize=N
응답 스키마(배열, 최신일 우선):
  [{
    "itemCode": "005930",
    "bizdate": "20260416",
    "foreignerPureBuyQuant": "+1,689,165",
    "foreignerHoldRatio": "49.26%",
    "organPureBuyQuant": "+1,432,694",
    "individualPureBuyQuant": "-4,968,280",
    "closePrice": "217,500",
    "compareToPreviousClosePrice": "6,500",
    "compareToPreviousPrice": {...},
    "accumulatedTradingVolume": "21,499,788"
  }, ...]

기존 HTML 파싱(finance.naver.com/item/frgn.naver) 방식은 네이버가 JS 동적 로딩으로
전환하면서 깨져서 교체. JSON API는 숫자가 부호·콤마 포함 문자열이므로 _parse_signed로 처리.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

_URL = "https://m.stock.naver.com/api/stock/{code}/trend"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class FlowRow:
    date: str              # "2026-04-16"
    close: int             # 종가
    volume: int            # 거래량
    foreign_net: int       # 외국인 순매수 주수 (양수=순매수, 음수=순매도)
    inst_net: int          # 기관 순매수 주수
    individual_net: int    # 개인 순매수 주수 (✨새로 추가)
    foreign_ratio: float   # 외국인 보유비율 %


def _parse_signed(s: str) -> int:
    """'+1,234,567' / '-5,000' / '123' → int."""
    s = (s or "").replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except Exception:
        return 0


def _parse_percent(s: str) -> float:
    s = (s or "").replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def _fmt_date(yyyymmdd: str) -> str:
    if len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return yyyymmdd


def get_flow(code: str, days: int = 5) -> list[FlowRow] | None:
    """종목코드의 최근 N거래일 외인·기관·개인 매매 동향. 실패 시 None."""
    try:
        r = requests.get(
            _URL.format(code=code),
            params={"pageSize": max(days, 5)},
            headers={"User-Agent": _UA, "Referer": "https://m.stock.naver.com/"},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[flow] {code} 조회 실패: {e}")
        return None

    if not isinstance(data, list) or not data:
        return None

    rows: list[FlowRow] = []
    for item in data[:days]:
        try:
            rows.append(
                FlowRow(
                    date=_fmt_date(item.get("bizdate", "")),
                    close=_parse_signed(item.get("closePrice", "0")),
                    volume=_parse_signed(item.get("accumulatedTradingVolume", "0")),
                    foreign_net=_parse_signed(item.get("foreignerPureBuyQuant", "0")),
                    inst_net=_parse_signed(item.get("organPureBuyQuant", "0")),
                    individual_net=_parse_signed(item.get("individualPureBuyQuant", "0")),
                    foreign_ratio=_parse_percent(item.get("foreignerHoldRatio", "0%")),
                )
            )
        except Exception as e:
            print(f"[flow] {code} 행 파싱 실패 (무시): {e}")
            continue

    return rows if rows else None


def _k(n: int) -> str:
    """주수를 보기 좋은 축약 표기: 1,234,567 → '123만주'."""
    sign = "+" if n > 0 else ("-" if n < 0 else "")
    n = abs(n)
    if n >= 10_000_000:   # 천만 이상 → '억'
        return f"{sign}{n/100_000_000:.2f}억주"
    if n >= 10_000:       # 만 이상 → '만'
        return f"{sign}{n/10_000:.1f}만주"
    return f"{sign}{n:,}주"


def format_flow_summary(rows: list[FlowRow]) -> str:
    """Gemini 프롬프트용 수급 요약. 매수/매도 패턴·연속성·개인 vs 외기관 대비까지 포함."""
    if not rows:
        return "수급 데이터 없음"

    f_total = sum(r.foreign_net for r in rows)
    i_total = sum(r.inst_net for r in rows)
    p_total = sum(r.individual_net for r in rows)

    f_buy_days = sum(1 for r in rows if r.foreign_net > 0)
    i_buy_days = sum(1 for r in rows if r.inst_net > 0)
    p_buy_days = sum(1 for r in rows if r.individual_net > 0)
    n = len(rows)

    # 패턴 레이블 (Gemini가 빠르게 해석할 수 있도록)
    pattern = ""
    if f_total > 0 and i_total > 0:
        pattern = "🔥 외인+기관 동반 순매수 (강세 시그널)"
    elif f_total < 0 and i_total < 0:
        if p_total > 0:
            pattern = "⚠️ 외인·기관 매도 + 개인만 매수 (개미 물림 위험)"
        else:
            pattern = "❄️ 외인+기관 동반 순매도 (약세 시그널)"
    elif f_total > 0 and i_total < 0:
        pattern = "🟡 외인 매수 / 기관 매도 (엇갈림)"
    elif f_total < 0 and i_total > 0:
        pattern = "🟡 외인 매도 / 기관 매수 (엇갈림)"

    lines = [
        f"최근 {n}거래일 수급:",
        f"  {pattern}" if pattern else "  (방향성 불분명)",
        f"  외인 누적 {_k(f_total)} ({f_buy_days}/{n}일 순매수)",
        f"  기관 누적 {_k(i_total)} ({i_buy_days}/{n}일 순매수)",
        f"  개인 누적 {_k(p_total)} ({p_buy_days}/{n}일 순매수)",
        f"  외인 지분율: {rows[0].foreign_ratio:.2f}%",
        "  일자별 (최근→과거):",
    ]
    for r in rows:
        lines.append(
            f"    {r.date}: 외인 {_k(r.foreign_net)} / 기관 {_k(r.inst_net)} / 개인 {_k(r.individual_net)}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    rows = get_flow(code, days=5)
    if rows:
        print(format_flow_summary(rows))
    else:
        print("조회 실패")
