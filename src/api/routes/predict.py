"""현재 예측 상태.

GET  /api/predict            가장 최근 브리핑 (캐시에서)
POST /api/predict/run        강제 새 브리핑 생성
"""
import traceback
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.config import load as load_config
from src.analyzers.briefing import generate_briefing, SLOTS
from src.storage import briefing_cache

router = APIRouter()


@router.get("")
def current_prediction():
    """가장 최근 브리핑 반환 (캐시에서)."""
    all_ = briefing_cache.get_all()
    if not all_:
        return {
            "has_briefing": False,
            "message": "아직 생성된 브리핑이 없습니다. 예약된 자동 시각(자정/아침/점심/오후/마감)을 기다리거나 '새로고침' 누르세요.",
        }
    slot, rec = max(all_.items(), key=lambda kv: kv[1].get("ts", ""))
    return {"has_briefing": True, **rec}


@router.post("/run")
def run_prediction(slot: str = Query("midday", description="슬롯명")):
    """즉시 브리핑 생성 — Vercel 10초 타임아웃을 넘길 수 있어 실패 시 안내 반환."""
    if slot not in SLOTS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"알 수 없는 슬롯: {slot}"},
        )
    try:
        cfg = load_config()
        text = generate_briefing(cfg, slot)
        briefing_cache.save(slot, text)
        return {"ok": True, "slot": slot, "text": text}
    except Exception as e:
        tb = traceback.format_exc().splitlines()[-15:]
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(e),
                "type": type(e).__name__,
                "traceback": tb,
                "hint": "Vercel 서버리스는 10초 제한이 있어 긴 Gemini 호출이 끊길 수 있음. "
                        "정기 브리핑은 GitHub Actions에서 자동 실행 중.",
            },
        )
