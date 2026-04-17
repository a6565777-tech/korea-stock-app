"""브리핑 결과 캐시 (로컬 JSON · Upstash Redis 자동 전환).

앱에서 "오늘 점심 브리핑 뭐였지?" 조회할 때 사용.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src import timez

_LOCAL_DIR = Path(__file__).parent.parent.parent / "data" / "briefings"
_REDIS_KEY = "briefing:v1"   # { slot: {ts, text} } 해시


def _ensure_local_dir() -> None:
    """로컬 모드에서만 필요. 읽기전용 FS면 조용히 실패."""
    try:
        _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _redis_enabled() -> bool:
    return bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))


def _redis_call(cmd: list[str]) -> Any:
    import requests

    url = os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")
    token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
    r = requests.post(url, json=cmd, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def save(slot: str, text: str) -> None:
    record = {
        "slot": slot,
        "text": text,
        "ts": timez.now_iso(),  # 항상 KST
    }
    if _redis_enabled():
        _redis_call(["HSET", _REDIS_KEY, slot, json.dumps(record, ensure_ascii=False)])
    else:
        _ensure_local_dir()
        (_LOCAL_DIR / f"{slot}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get(slot: str) -> dict | None:
    if _redis_enabled():
        raw = _redis_call(["HGET", _REDIS_KEY, slot])
        if not raw:
            return None
        return json.loads(raw)
    f = _LOCAL_DIR / f"{slot}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def get_all() -> dict[str, dict]:
    slots = ["overnight", "morning", "realtime", "midday", "afternoon", "closing"]
    out = {}
    for slot in slots:
        rec = get(slot)
        if rec:
            out[slot] = rec
    return out
