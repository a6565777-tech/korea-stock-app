"""포지션 저장소 (로컬 YAML · Upstash Redis 자동 전환).

환경변수 UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN 둘 다 있으면 Redis 사용.
없으면 positions.yaml 파일 사용 (로컬 개발용).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).parent.parent.parent / "positions.yaml"
_REDIS_KEY = "positions:v1"


def _redis_enabled() -> bool:
    return bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))


def _redis_call(cmd: list[str]) -> Any:
    """Upstash Redis REST API 호출 (requests만 쓰면 됨)."""
    import requests

    url = os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")
    token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
    r = requests.post(url, json=cmd, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def _load_redis() -> list[dict]:
    raw = _redis_call(["GET", _REDIS_KEY])
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _save_redis(positions: list[dict]) -> None:
    _redis_call(["SET", _REDIS_KEY, json.dumps(positions, ensure_ascii=False)])


def _load_yaml() -> list[dict]:
    if not _YAML_PATH.exists():
        return []
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    if not data or not data.get("positions"):
        return []
    return data["positions"]


def _save_yaml(positions: list[dict]) -> None:
    _YAML_PATH.write_text(
        yaml.safe_dump({"positions": positions}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# ── 공개 API ──────────────────────────────────────
def list_positions() -> list[dict]:
    if _redis_enabled():
        return _load_redis()
    return _load_yaml()


def save_all(positions: list[dict]) -> None:
    if _redis_enabled():
        _save_redis(positions)
    else:
        _save_yaml(positions)


def add_position(p: dict) -> list[dict]:
    positions = list_positions()
    # 같은 code가 있으면 덮어쓰기
    positions = [x for x in positions if str(x.get("code")) != str(p.get("code"))]
    positions.append(p)
    save_all(positions)
    return positions


def delete_position(code: str) -> list[dict]:
    positions = [x for x in list_positions() if str(x.get("code")) != str(code)]
    save_all(positions)
    return positions


def update_position(code: str, updates: dict) -> list[dict]:
    positions = list_positions()
    for p in positions:
        if str(p.get("code")) == str(code):
            p.update(updates)
            break
    save_all(positions)
    return positions


if __name__ == "__main__":
    print(f"Redis enabled: {_redis_enabled()}")
    print(f"Positions: {list_positions()}")
