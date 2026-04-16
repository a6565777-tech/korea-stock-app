"""Yahoo Finance 종목 검색 (한국 KOSPI/KOSDAQ 필터).

사용 예:
    results = search("삼성")
    # -> [{"code": "005930", "market": "KS", "name": "Samsung Electronics", ...}]
"""
from __future__ import annotations

from typing import Any

import requests

_SEARCH_URLS = [
    "https://query1.finance.yahoo.com/v1/finance/search",
    "https://query2.finance.yahoo.com/v1/finance/search",
]
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _parse_symbol(symbol: str) -> tuple[str, str] | None:
    """'005930.KS' -> ('005930', 'KS'). 한국 종목이 아니면 None."""
    if "." not in symbol:
        return None
    code, suffix = symbol.rsplit(".", 1)
    if suffix not in ("KS", "KQ"):
        return None
    if not code.isdigit() or len(code) != 6:
        return None
    return code, suffix


def search(query: str, limit: int = 10) -> list[dict]:
    """Yahoo 검색 → 한국 종목(KOSPI/KOSDAQ)만 필터링해 반환."""
    if not query or not query.strip():
        return []
    params = {
        "q": query.strip(),
        "quotesCount": 20,
        "newsCount": 0,
    }
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    last_err: Exception | None = None
    data = None
    for url in _SEARCH_URLS:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=8)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            last_err = e
            continue
    if data is None:
        raise RuntimeError(f"Yahoo 검색 실패: {last_err}")

    out: list[dict] = []
    for q in data.get("quotes", []):
        sym = q.get("symbol", "")
        parsed = _parse_symbol(sym)
        if not parsed:
            continue
        code, market = parsed
        name = q.get("shortname") or q.get("longname") or code
        out.append({
            "code": code,
            "market": market,
            "symbol": sym,
            "name": name,
            "long_name": q.get("longname", ""),
            "exchange": q.get("exchange", ""),
            "quote_type": q.get("quoteType", ""),
        })
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    for hit in search(q):
        print(f"  {hit['name']} ({hit['code']}.{hit['market']})")
