"""현재 예측 상태.

GET  /api/predict            가장 최근 브리핑 (캐시에서)
POST /api/predict/run        강제 새 브리핑 생성
"""
import traceback
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.config import load as load_config
from src.analyzers.briefing import generate_briefing, SLOTS
from src.analyzers.llm import QuotaExhaustedError
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
    except QuotaExhaustedError as e:
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "reason": "quota_exhausted",
                "error": "Gemini 무료 쿼터가 소진됐습니다.",
                "user_message": (
                    "⚠️ Gemini API 무료 쿼터 소진\n\n"
                    "• 1~2시간 후 다시 시도하거나\n"
                    "• Google AI Studio에서 결제 연결 시 바로 해제\n"
                    "  (https://aistudio.google.com → Billing)\n\n"
                    "정기 브리핑은 GitHub Actions에서 하루 5번 자동 실행됩니다."
                ),
                "detail": str(e),
            },
        )
    except Exception as e:
        tb = traceback.format_exc().splitlines()[-10:]
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "reason": "internal_error",
                "error": str(e)[:500],
                "type": type(e).__name__,
                "user_message": (
                    "브리핑 생성 중 서버 오류.\n"
                    f"({type(e).__name__}: {str(e)[:150]})"
                ),
                "traceback": tb,
                "hint": "Vercel 서버리스는 60초 제한이 있어 긴 Gemini 호출이 끊길 수 있음. "
                        "정기 브리핑은 GitHub Actions에서 자동 실행 중.",
            },
        )
