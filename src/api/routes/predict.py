"""현재 예측 상태.

GET  /api/predict                      가장 최근 브리핑 (캐시에서)
POST /api/predict/run?slot=&mode=      강제 새 브리핑 생성

mode:
  standard (기본) → '일반 분석' — Flash 체인, 항상 가능
  expert          → '전문가 분석' — Pro 전용, 쿼터 소진 시 429 반환
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
def run_prediction(
    slot: str = Query("midday", description="슬롯명"),
    mode: str = Query("standard", description="standard | expert"),
):
    """즉시 브리핑 생성. Vercel 60초 타임아웃 안에서 처리.

    mode='expert' 는 Pro 모델만 시도하고, 쿼터/결제 문제 시 429 + user_message 반환.
    """
    if slot not in SLOTS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"알 수 없는 슬롯: {slot}"},
        )
    if mode not in ("standard", "expert"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"알 수 없는 모드: {mode}"},
        )

    try:
        cfg = load_config()
        text = generate_briefing(cfg, slot, mode=mode)
        briefing_cache.save(slot, text)
        return {"ok": True, "slot": slot, "mode": mode, "text": text}

    except QuotaExhaustedError as e:
        # 사용자에게 노출되는 메시지에는 'Gemini' 등 내부 모델명 노출하지 않음
        if mode == "expert":
            user_msg = (
                "🎓 전문가 분석을 지금 사용할 수 없어요. 잠시 후 다시 시도하거나, 일반 분석을 사용해 주세요. (전문가 분석은 일별 사용량 한도가 있습니다.)"
            )
            reason = "expert_unavailable"
        else:
            user_msg = (
                "분석 사용량이 일시적으로 한도에 도달했어요. 1~2시간 후 다시 시도해 주세요."
            )
            reason = "quota_exhausted"
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "reason": reason,
                "mode": mode,
                "error": "분석 사용량 한도 도달",
                "user_message": user_msg,
                "detail": str(e)[:300],
            },
        )

    except Exception as e:
        tb = traceback.format_exc().splitlines()[-10:]
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "reason": "internal_error",
                "mode": mode,
                "error": str(e)[:500],
                "type": type(e).__name__,
                "user_message": (
                    "분석 생성 중 일시 오류가 발생했어요. 잠시 후 다시 시도해 주세요."
                ),
                "traceback": tb,
                "hint": "Vercel 서버리스 60초 제한이 있어 긴 호출이 끊길 수 있음. "
                        "정기 브리핑은 GitHub Actions에서 자동 실행 중.",
            },
        )
