"""브리핑 조회 API.

GET /api/briefing           저장된 모든 슬롯의 최신 브리핑
GET /api/briefing/{slot}    특정 슬롯 (overnight/morning/midday/afternoon/closing)
GET /api/briefing/latest    가장 최근에 저장된 브리핑
"""
from fastapi import APIRouter, HTTPException

from src.storage import briefing_cache

router = APIRouter()

_VALID_SLOTS = {"overnight", "morning", "midday", "afternoon", "closing"}


@router.get("")
def all_briefings():
    return briefing_cache.get_all()


@router.get("/latest")
def latest_briefing():
    all_ = briefing_cache.get_all()
    if not all_:
        return {"slot": None, "text": "", "ts": None}
    # ts 최신순
    slot, rec = max(all_.items(), key=lambda kv: kv[1].get("ts", ""))
    return rec


@router.get("/{slot}")
def get_briefing(slot: str):
    if slot not in _VALID_SLOTS:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 슬롯: {slot}")
    rec = briefing_cache.get(slot)
    if not rec:
        return {"slot": slot, "text": "", "ts": None}
    return rec
