"""임시 디버그 라우트 — 해결 후 삭제 예정."""
import os
import traceback

from fastapi import APIRouter

from src.storage import positions_store, watchlist_store, briefing_cache

router = APIRouter()


@router.get("/state")
def state():
    out = {
        "upstash_url_set": bool(os.getenv("UPSTASH_REDIS_REST_URL")),
        "upstash_token_set": bool(os.getenv("UPSTASH_REDIS_REST_TOKEN")),
    }
    try:
        raw_positions = positions_store.list_positions()
        out["positions_count"] = len(raw_positions)
        out["positions_raw"] = raw_positions
    except Exception as e:
        out["positions_error"] = f"{type(e).__name__}: {e}"
        out["positions_tb"] = traceback.format_exc().splitlines()[-10:]

    try:
        raw_wl = watchlist_store.list_watchlist()
        out["watchlist_count"] = len(raw_wl)
        out["watchlist_sample"] = raw_wl[:3]
    except Exception as e:
        out["watchlist_error"] = f"{type(e).__name__}: {e}"

    try:
        briefings = briefing_cache.get_all()
        out["briefing_slots"] = list(briefings.keys())
    except Exception as e:
        out["briefing_error"] = str(e)

    return out


@router.get("/raw-redis")
def raw_redis(key: str = "positions:v1"):
    """Upstash에서 특정 키 값 그대로 반환."""
    try:
        from src.storage.positions_store import _redis_call
        result = _redis_call(["GET", key])
        return {"key": key, "result_type": type(result).__name__, "result": result}
    except Exception as e:
        return {"key": key, "error": f"{type(e).__name__}: {e}"}
