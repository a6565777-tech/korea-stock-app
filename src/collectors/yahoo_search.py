"""Yahoo Finance 종목 검색 (한국 KOSPI/KOSDAQ 필터).

사용 예:
    results = search("삼성")
    # -> [{"code": "005930", "market": "KS", "name": "Samsung Electronics", ...}]
"""
from __future__ import annotations

from typing import Any

import requests

_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_UA = "Mozilla/5.0 (compatible; KoreaStockApp/0.1)"


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
        "lang": "ko-KR",
        "region": "KR",
    }
    try:
        r = requests.get(
            _SEARCH_URL,
            params=params,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Yahoo 검색 실패: {e}") from e

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
