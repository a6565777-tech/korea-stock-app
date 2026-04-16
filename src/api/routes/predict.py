"""현재 예측 상태.

GET /api/predict            현재 시점 기준 관심종목 전체 예측 (가장 최근 브리핑 텍스트)
GET /api/predict/run        강제로 새 브리핑 생성 (앱에서 "새로고침" 버튼용)
                             slot 쿼리 파라미터 선택 가능, 기본 midday
"""
from fastapi import APIRouter, Query

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
            "message": "아직 생성된 브리핑이 없습니다. 앱에서 '새로고침' 누르거나 자동 시각을 기다려주세요.",
        }
    slot, rec = max(all_.items(), key=lambda kv: kv[1].get("ts", ""))
    return {"has_briefing": True, **rec}


@router.post("/run")
def run_prediction(slot: str = Query("midday", description="슬롯명")):
    """앱의 '새로고침' 버튼용. 즉시 브리핑 생성.

    ⚠️ Gemini API 호출 1회 소비. 남발 금지.
    """
    if slot not in SLOTS:
        return {"ok": False, "error": f"알 수 없는 슬롯: {slot}"}
    cfg = load_config()
    text = generate_briefing(cfg, slot)
    briefing_cache.save(slot, text)
    return {"ok": True, "slot": slot, "text": text}
