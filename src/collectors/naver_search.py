"""네이버 금융 자동완성 기반 한국 종목 검색.

한글·영문·코드 모두 지원. Yahoo와 달리 KR 특화라 한글 검색이 자연스러움.

응답 예시:
    {"result": {"items": [
        {"code": "005930", "name": "삼성전자", "typeCode": "KOSPI", ...}
    ]}}
"""
from __future__ import annotations

import requests

_URL = "https://m.stock.naver.com/front-api/search/autoComplete"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Naver typeCode → yfinance suffix
_MARKET_MAP = {
    "KOSPI": "KS",
    "KOSDAQ": "KQ",
    # KONEX, ETF, etc는 제외 (yfinance 가격 조회 불가능 많음)
}


def search(query: str, limit: int = 10) -> list[dict]:
    """네이버 자동완성 → 한국 상장주식(KOSPI/KOSDAQ)만 반환."""
    q = (query or "").strip()
    if not q:
        return []
    params = {
        "query": q,
        "target": "stock,index,marketindicator,coin,ipo",
    }
    headers = {
        "User-Agent": _UA,
        "Referer": "https://m.stock.naver.com/",
        "Accept": "application/json",
    }
    r = requests.get(_URL, params=params, headers=headers, timeout=8)
    r.raise_for_status()
    data = r.json()
    items = (data.get("result") or {}).get("items") or []

    out: list[dict] = []
    for it in items:
        # 한국 주식만 (index·coin·환율 등 제외)
        if it.get("category") != "stock":
            continue
        if it.get("nationCode") != "KOR":
            continue
        type_code = it.get("typeCode", "")
        market = _MARKET_MAP.get(type_code)
        if not market:
            continue
        code = str(it.get("code", "")).strip()
        if not code.isdigit() or len(code) != 6:
            continue
        out.append({
            "code": code,
            "market": market,
            "symbol": f"{code}.{market}",
            "name": it.get("name", code),
            "long_name": "",            # 네이버는 영문명 따로 없음
            "exchange": type_code,       # "KOSPI" / "KOSDAQ"
        })
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    for hit in search(q):
        print(f"  {hit['name']} ({hit['code']}.{hit['market']}) [{hit['exchange']}]")
