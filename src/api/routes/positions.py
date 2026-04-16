"""포지션 CRUD API.

GET    /api/positions        모든 포지션 + 현재가·손익 정보
POST   /api/positions        새 포지션 추가 (기존 code 있으면 덮어씀)
DELETE /api/positions/{code} 포지션 삭제
PATCH  /api/positions/{code} 일부 필드 수정
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config import load as load_config
from src.collectors.price import get_snapshot
from src.positions import load as load_positions, Position
from src.storage import positions_store

router = APIRouter()


class PositionIn(BaseModel):
    code: str = Field(..., description="종목코드 (6자리)")
    name: Optional[str] = None
    buy_price: float
    quantity: int
    buy_date: Optional[str] = ""
    note: Optional[str] = ""
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None


class PositionUpdate(BaseModel):
    name: Optional[str] = None
    buy_price: Optional[float] = None
    quantity: Optional[int] = None
    buy_date: Optional[str] = None
    note: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None


def _resolve_market(code: str, watchlist: list[dict]) -> str:
    for s in watchlist:
        if str(s["code"]) == str(code):
            return s.get("market", "KS")
    return "KS"


def _resolve_name(code: str, watchlist: list[dict], fallback: str) -> str:
    for s in watchlist:
        if str(s["code"]) == str(code):
            return s["name"]
    return fallback or str(code)


def _enrich(p: Position, watchlist: list[dict]) -> dict:
    """포지션 + 현재가·손익을 API 응답용 dict로 변환"""
    p.market = _resolve_market(p.code, watchlist)
    base = p.to_dict()
    snap = get_snapshot(p.code, p.market, p.name)
    if snap:
        pnl = p.pnl(snap.last)
        base.update({
            "current_price": snap.last,
            "prev_close": snap.prev_close,
            "change_pct": snap.change_pct,
            "day_change": snap.last - snap.prev_close,
            "pnl_pct": pnl["pct"],
            "pnl_amount": pnl["unrealized"],
            "current_value": pnl["current_value"],
            "target_hit": pnl["target_hit"],
            "stop_hit": pnl["stop_hit"],
        })
    else:
        base.update({
            "current_price": None,
            "change_pct": None,
            "pnl_pct": None,
            "pnl_amount": None,
        })
    return base


@router.get("")
def list_positions():
    cfg = load_config()
    positions = load_positions()
    total_cost = 0.0
    total_value = 0.0
    items = []
    for p in positions:
        enriched = _enrich(p, cfg["watchlist"])
        items.append(enriched)
        total_cost += p.cost
        if enriched.get("current_value"):
            total_value += enriched["current_value"]
    total_pnl = total_value - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost else 0
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pct": total_pct,
        },
    }


@router.post("")
def add_position(payload: PositionIn):
    cfg = load_config()
    raw = payload.model_dump(exclude_none=True)
    raw["code"] = str(raw["code"]).zfill(6)
    raw["name"] = _resolve_name(raw["code"], cfg["watchlist"], raw.get("name", ""))
    positions_store.add_position(raw)
    return {"ok": True, "position": raw}


@router.delete("/{code}")
def delete_position(code: str):
    code = code.zfill(6)
    existing = [p for p in positions_store.list_positions() if str(p.get("code")) == code]
    if not existing:
        raise HTTPException(status_code=404, detail=f"포지션 없음: {code}")
    positions_store.delete_position(code)
    return {"ok": True, "deleted": code}


@router.patch("/{code}")
def update_position(code: str, payload: PositionUpdate):
    code = code.zfill(6)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="수정할 필드가 없음")
    existing = [p for p in positions_store.list_positions() if str(p.get("code")) == code]
    if not existing:
        raise HTTPException(status_code=404, detail=f"포지션 없음: {code}")
    positions_store.update_position(code, updates)
    return {"ok": True, "updated": code, "changes": updates}
