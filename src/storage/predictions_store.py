"""예측 결과 로깅 + 실현 추적 (Redis / 로컬 JSON 자동전환).

목적:
  매 브리핑의 종목별 예측을 저장 → 다음 날 실제 결과 채점 → 롤링 적중률 계산
  → 다음 브리핑 프롬프트에 "최근 30일 🟢 신호 실적중률 38%" 로 주입해서 자가교정.

스키마 (Redis Hash `predictions:v1`):
  key = "2026-04-22:morning:005930"
  value = JSON {
    date: "2026-04-22",
    slot: "morning",
    code: "005930",
    name: "삼성전자",
    signal: "🟢 매수 추천",
    signal_emoji: "🟢",
    probability: 57,
    prev_close: 217000,
    expected_open: 218500,
    target_price: 221800,
    stop_price: 216300,
    target_pct: 1.5,   # 시가 대비
    stop_pct: 1.0,
    anchor_prob: 55,   # 역사적 도달률 기반 앵커
    ts: "2026-04-22T08:00:00+09:00",
    # 채점 결과 (다음날 채워짐)
    outcome: null | {
      actual_open: 218100,
      actual_high: 220500,
      actual_low: 217000,
      actual_close: 219800,
      target_hit: bool,
      stop_hit: bool,
      resolved_at: "2026-04-23T09:00:00+09:00",
      hit_by_11am: bool | null,  # 지금은 일봉만 쓰니 null. 분봉 붙이면 채워짐
    }
  }
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from src import timez

_LOCAL_DIR = Path(__file__).parent.parent.parent / "data" / "predictions"
_REDIS_KEY = "predictions:v1"
_INDEX_KEY = "predictions:index:v1"   # 날짜 리스트 (정렬용)


def _redis_enabled() -> bool:
    return bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))


def _redis_call(cmd: list[Any]) -> Any:
    import requests
    url = os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")
    token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
    r = requests.post(url, json=cmd, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def _ensure_local() -> None:
    try:
        _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


@dataclass
class Prediction:
    date: str                # "YYYY-MM-DD"
    slot: str
    code: str
    name: str
    signal: str              # "🟢 매수 추천" 등 전체
    signal_emoji: str        # "🟢"만
    probability: int         # Gemini가 최종적으로 내놓은 확률 (클램프 후)
    prev_close: float
    expected_open: float | None
    target_price: float | None
    stop_price: float | None
    target_pct: float | None
    stop_pct: float | None
    anchor_prob: int | None
    ts: str
    outcome: dict | None = None

    def key(self) -> str:
        return f"{self.date}:{self.slot}:{self.code}"


def save(p: Prediction) -> None:
    """예측 1건 저장."""
    key = p.key()
    payload = json.dumps(asdict(p), ensure_ascii=False)
    if _redis_enabled():
        _redis_call(["HSET", _REDIS_KEY, key, payload])
        # 날짜 인덱스에 추가 (ZADD — score 는 timestamp ms)
        import time
        _redis_call(["ZADD", _INDEX_KEY, int(time.time() * 1000), key])
    else:
        _ensure_local()
        (_LOCAL_DIR / f"{key.replace(':', '_')}.json").write_text(
            payload, encoding="utf-8"
        )


def save_batch(preds: list[Prediction]) -> int:
    for p in preds:
        try:
            save(p)
        except Exception as e:
            print(f"[predictions] save 실패 {p.key()}: {e}")
    return len(preds)


def list_keys(days_back: int = 30) -> list[str]:
    """최근 N일간의 예측 키 목록."""
    if _redis_enabled():
        # 최근 것부터 역순으로
        res = _redis_call(["ZREVRANGE", _INDEX_KEY, 0, days_back * 20])  # 하루 20개까지
        return res or []
    _ensure_local()
    files = sorted(_LOCAL_DIR.glob("*.json"), reverse=True)
    return [f.stem.replace("_", ":") for f in files]


def get(key: str) -> Prediction | None:
    if _redis_enabled():
        raw = _redis_call(["HGET", _REDIS_KEY, key])
        if not raw:
            return None
    else:
        f = _LOCAL_DIR / f"{key.replace(':', '_')}.json"
        if not f.exists():
            return None
        raw = f.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        return Prediction(**data)
    except Exception:
        return None


def list_recent(days_back: int = 30) -> list[Prediction]:
    """최근 N일 예측 전부 로드."""
    keys = list_keys(days_back)
    out = []
    for k in keys:
        p = get(k)
        if p:
            out.append(p)
    return out


def mark_outcome(key: str, outcome: dict) -> bool:
    """채점 결과 기록."""
    p = get(key)
    if not p:
        return False
    p.outcome = outcome
    save(p)
    return True


def rolling_accuracy(days_back: int = 30) -> dict:
    """최근 N일 신호별 실제 적중률.

    반환:
      {
        "period_days": 30,
        "total": 42,
        "scored": 30,        # outcome 이 채워진 것
        "by_signal": {
          "🟢": {"count": 8, "target_hit": 3, "stop_hit": 2, "hit_rate": 37.5, "stop_rate": 25.0},
          "🟡": {...},
          ...
        },
        "overall_target_hit_rate": 32.1,
      }
    """
    preds = list_recent(days_back)
    scored = [p for p in preds if p.outcome]
    by_signal: dict[str, dict] = {}
    total_hit = 0
    for p in scored:
        bucket = by_signal.setdefault(p.signal_emoji, {"count": 0, "target_hit": 0, "stop_hit": 0})
        bucket["count"] += 1
        if p.outcome.get("target_hit"):
            bucket["target_hit"] += 1
            total_hit += 1
        if p.outcome.get("stop_hit"):
            bucket["stop_hit"] += 1
    for emoji, b in by_signal.items():
        b["hit_rate"] = round(b["target_hit"] / b["count"] * 100, 1) if b["count"] else 0.0
        b["stop_rate"] = round(b["stop_hit"] / b["count"] * 100, 1) if b["count"] else 0.0
    return {
        "period_days": days_back,
        "total": len(preds),
        "scored": len(scored),
        "by_signal": by_signal,
        "overall_target_hit_rate": round(total_hit / len(scored) * 100, 1) if scored else 0.0,
    }


def unresolved_predictions(cutoff_days_ago: int = 1) -> list[Prediction]:
    """outcome 이 아직 안 채워진 예측 중 cutoff_days_ago 이전 것.

    cutoff_days_ago=1 → 어제 이전 예측 중 채점 안 된 것들 (오늘 채점 대상).
    """
    from datetime import timedelta
    cutoff = (timez.now() - timedelta(days=cutoff_days_ago)).date().isoformat()
    out = []
    for p in list_recent(days_back=cutoff_days_ago + 7):
        if p.outcome:
            continue
        if p.date <= cutoff:
            out.append(p)
    return out


if __name__ == "__main__":
    from datetime import datetime
    p = Prediction(
        date="2026-04-22", slot="morning",
        code="005930", name="삼성전자",
        signal="🟢 매수 추천", signal_emoji="🟢",
        probability=57, prev_close=217000, expected_open=218500,
        target_price=221800, stop_price=216300,
        target_pct=1.5, stop_pct=1.0,
        anchor_prob=55,
        ts=timez.now_iso(),
    )
    save(p)
    print("saved:", p.key())
    print("list:", list_keys(7))
    print("accuracy:", rolling_accuracy(30))
