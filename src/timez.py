"""공용 시각 유틸 — 서버 시각대(Vercel UTC 등)와 무관하게 항상 KST 반환.

Vercel 서버리스는 UTC로 동작. Python `datetime.now()`를 그대로 쓰면
"🌙 자정 체크" 같은 한국 시각 기반 슬롯이 UTC로 찍혀서 9시간 어긋남.
이 모듈의 `now()`를 써서 어디서 실행되든 KST로 통일.

한국은 DST 없으므로 UTC+9 고정 오프셋으로 안전하게 처리 (tzdata 의존 없음).
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    """현재 KST 시각을 naive datetime으로 반환.

    기존 코드가 naive datetime 전제로 작성돼 있어서 tzinfo는 제거.
    strftime/비교 연산 모두 기존 로직 그대로 유지 가능.
    """
    return datetime.now(KST).replace(tzinfo=None)


def now_iso() -> str:
    """KST ISO 8601 문자열 (초 단위)."""
    return now().isoformat(timespec="seconds")
