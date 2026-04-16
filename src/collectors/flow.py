"""네이버 금융에서 종목별 외국인·기관 수급 동향 수집.

최근 거래일 N일치 외국인/기관 순매수량을 반환.
네이버 HTML 구조가 바뀌면 깨질 수 있음 — 실패 시 None 반환 (브리핑은 수급 없이 계속 진행).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

_URL = "https://finance.naver.com/item/frgn.naver"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class FlowRow:
    date: str              # "2026.04.17"
    close: int             # 종가
    volume: int            # 거래량
    foreign_net: int       # 외국인 순매수 주수 (양수=순매수, 음수=순매도)
    inst_net: int          # 기관 순매수 주수
    foreign_ratio: float   # 외국인 보유비율 %


_NUM_RE = re.compile(r"[-+]?[\d,]+")


def _parse_int(s: str) -> int:
    s = (s or "").replace(",", "").replace("&nbsp;", "").strip()
    m = re.match(r"[-+]?\d+", s)
    return int(m.group(0)) if m else 0


def _parse_float(s: str) -> float:
    s = (s or "").replace(",", "").replace("%", "").replace("&nbsp;", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def get_flow(code: str, days: int = 5) -> list[FlowRow] | None:
    """종목코드의 최근 N거래일 외국인·기관 매매 동향. 실패 시 None."""
    try:
        r = requests.get(
            _URL,
            params={"code": code},
            headers={"User-Agent": _UA, "Referer": "https://finance.naver.com/"},
            timeout=8,
        )
        r.encoding = "euc-kr"
        html = r.text
    except Exception as e:
        print(f"[flow] {code} HTTP 실패: {e}")
        return None

    tr_pattern = re.compile(r"<tr[^>]*onmouseover[^>]*>(.*?)</tr>", re.DOTALL)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    tag_pattern = re.compile(r"<[^>]+>")

    rows: list[FlowRow] = []
    for tr_match in tr_pattern.finditer(html):
        tr_html = tr_match.group(1)
        tds_raw = td_pattern.findall(tr_html)
        tds = [tag_pattern.sub("", t).replace("&nbsp;", "").strip() for t in tds_raw]
        if len(tds) < 9:
            continue
        date_str = tds[0]
        if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_str):
            continue
        try:
            rows.append(
                FlowRow(
                    date=date_str,
                    close=_parse_int(tds[1]),
                    volume=_parse_int(tds[4]),
                    foreign_net=_parse_int(tds[5]),
                    inst_net=_parse_int(tds[6]),
                    foreign_ratio=_parse_float(tds[8]),
                )
            )
        except Exception:
            continue
        if len(rows) >= days:
            break

    return rows if rows else None


def format_flow_summary(rows: list[FlowRow]) -> str:
    """Gemini 프롬프트용 짧은 요약 문자열."""
    if not rows:
        return "수급 데이터 없음"

    foreign_total = sum(r.foreign_net for r in rows)
    inst_total = sum(r.inst_net for r in rows)
    foreign_days_buy = sum(1 for r in rows if r.foreign_net > 0)
    inst_days_buy = sum(1 for r in rows if r.inst_net > 0)

    lines = [
        f"최근 {len(rows)}거래일: 외국인 누적 {foreign_total:+,}주 "
        f"({foreign_days_buy}일 순매수) / 기관 누적 {inst_total:+,}주 "
        f"({inst_days_buy}일 순매수)",
        f"외국인 지분율: {rows[0].foreign_ratio:.2f}%",
        "일자별:",
    ]
    for r in rows:
        lines.append(
            f"  {r.date}: 외인 {r.foreign_net:+,} / 기관 {r.inst_net:+,}"
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
