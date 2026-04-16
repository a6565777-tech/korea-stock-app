"""관심종목 조회 (PWA의 드롭다운용 + 실시간 현재가)."""
from fastapi import APIRouter

from src.config import load as load_config
from src.collectors.price import get_snapshot

router = APIRouter()


@router.get("")
def list_watchlist():
    cfg = load_config()
    items = []
    for stock in cfg["watchlist"]:
        snap = get_snapshot(stock["code"], stock["market"], stock["name"])
        items.append({
            "code": stock["code"],
            "market": stock["market"],
            "name": stock["name"],
            "sector": stock.get("sector", ""),
            "current_price": snap.last if snap else None,
            "prev_close": snap.prev_close if snap else None,
            "change_pct": snap.change_pct if snap else None,
            "day_change": (snap.last - snap.prev_close) if snap else None,
        })
    return {"items": items}
