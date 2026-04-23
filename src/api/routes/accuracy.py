"""예측 적중률 API.

GET /api/accuracy?days=30     최근 N일 신호별 적중률 요약
GET /api/accuracy/recent       최근 예측 상세 (outcome 포함)
POST /api/accuracy/score       채점 수동 실행 (크론용)
"""
from fastapi import APIRouter, Query

from src.storage import predictions_store
from src.analyzers import scoring

router = APIRouter()


@router.get("")
def get_accuracy(days: int = Query(30, ge=1, le=180)):
    return predictions_store.rolling_accuracy(days)


@router.get("/recent")
def recent_predictions(days: int = Query(14, ge=1, le=90)):
    preds = predictions_store.list_recent(days)
    return {
        "count": len(preds),
        "items": [
            {
                "key": p.key(),
                "date": p.date,
                "slot": p.slot,
                "code": p.code,
                "name": p.name,
                "signal": p.signal_emoji,
                "probability": p.probability,
                "anchor_prob": p.anchor_prob,
                "target_price": p.target_price,
                "stop_price": p.stop_price,
                "outcome": p.outcome,
            }
            for p in preds
        ],
    }


@router.post("/score")
def run_scoring():
    """채점 수동 실행 — 크론이나 관리자 버튼에서."""
    return scoring.score_unresolved()
