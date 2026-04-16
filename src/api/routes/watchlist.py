"""관심종목 CRUD + 검색.

GET    /api/watchlist              전체 관심종목 + 현재가
POST   /api/watchlist              관심종목 추가 (code, market, name, sector?)
DELETE /api/watchlist/{code}       관심종목 삭제
GET    /api/watchlist/search?q=..  Yahoo 검색 (한국 종목만)
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.collectors.price import get_snapshot
from src.collectors.naver_search import search as stock_search
from src.storage import watchlist_store

router = APIRouter()


class WatchlistItemIn(BaseModel):
    code: str = Field(..., description="종목코드 (6자리)")
    market: str = Field("KS", description="KS=KOSPI, KQ=KOSDAQ")
    name: str
    sector: Optional[str] = ""


@router.get("")
def list_watchlist():
    items = []
    for stock in watchlist_store.list_watchlist():
        snap = get_snapshot(stock["code"], stock.get("market", "KS"), stock["name"])
        items.append({
            "code": stock["code"],
            "market": stock.get("market", "KS"),
            "name": stock["name"],
            "sector": stock.get("sector", ""),
            "current_price": snap.last if snap else None,
            "prev_close": snap.prev_close if snap else None,
            "change_pct": snap.change_pct if snap else None,
            "day_change": (snap.last - snap.prev_close) if snap else None,
        })
    return {"items": items}


@router.get("/search")
def search_symbols(q: str = Query(..., min_length=1, description="검색어")):
    """네이버 금융에서 한국 KOSPI/KOSDAQ 종목 검색 (한글·영문·코드 OK)."""
    try:
        hits = stock_search(q)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"검색 실패: {e}")
    return {"query": q, "items": hits}


@router.post("")
def add_watchlist_item(payload: WatchlistItemIn):
    code = str(payload.code).zfill(6)
    market = payload.market.upper()
    if market not in ("KS", "KQ"):
        raise HTTPException(status_code=400, detail="market은 KS 또는 KQ")
    item = {
        "code": code,
        "market": market,
        "name": payload.name,
        "sector": payload.sector or "",
    }
    watchlist_store.add_item(item)
    return {"ok": True, "item": item}


@router.delete("/{code}")
def delete_watchlist_item(code: str):
    code = code.zfill(6)
    existing = [x for x in watchlist_store.list_watchlist() if str(x.get("code")) == code]
    if not existing:
        raise HTTPException(status_code=404, detail=f"관심종목 없음: {code}")
    watchlist_store.delete_item(code)
    return {"ok": True, "deleted": code}
