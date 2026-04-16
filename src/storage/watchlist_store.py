"""관심종목 저장소 (Upstash Redis 우선 · 없으면 config.yaml).

환경변수 UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN 있으면 Redis 사용.
처음 접근 시 Redis가 비어 있으면 config.yaml 의 watchlist 를 시드로 복사.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
_REDIS_KEY = "watchlist:v1"


def _redis_enabled() -> bool:
    return bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))


def _redis_call(cmd: list[Any]) -> Any:
    import requests

    url = os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")
    token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
    r = requests.post(url, json=cmd, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def _seed_from_config() -> list[dict]:
    """config.yaml 의 watchlist 를 그대로 반환 (seed용)."""
    if not _CONFIG_PATH.exists():
        return []
    cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return list(cfg.get("watchlist", []))


def _load_redis() -> list[dict]:
    raw = _redis_call(["GET", _REDIS_KEY])
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return []
    # 비어 있으면 config.yaml 로 시드 (한 번만)
    seed = _seed_from_config()
    if seed:
        _redis_call(["SET", _REDIS_KEY, json.dumps(seed, ensure_ascii=False)])
    return seed


def _save_redis(items: list[dict]) -> None:
    _redis_call(["SET", _REDIS_KEY, json.dumps(items, ensure_ascii=False)])


def list_watchlist() -> list[dict]:
    if _redis_enabled():
        return _load_redis()
    return _seed_from_config()


def save_all(items: list[dict]) -> None:
    if _redis_enabled():
        _save_redis(items)
    # 로컬(config.yaml) 모드에서는 저장 불가 — 읽기전용 취급


def add_item(item: dict) -> list[dict]:
    items = list_watchlist()
    # code 중복 방지
    items = [x for x in items if str(x.get("code")) != str(item.get("code"))]
    items.append(item)
    save_all(items)
    return items


def delete_item(code: str) -> list[dict]:
    items = [x for x in list_watchlist() if str(x.get("code")) != str(code)]
    save_all(items)
    return items


if __name__ == "__main__":
    print(f"Redis enabled: {_redis_enabled()}")
    for s in list_watchlist():
        print(f"  - {s.get('name')} ({s.get('code')}.{s.get('market')})")
