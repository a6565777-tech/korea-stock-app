"""ntfy.sh 푸시 알림 모듈 (JSON publish API 사용 — UTF-8 안전).

[FIX 2026-04] 기존 헤더 기반 발송은 한국어/이모지가 포함된 Title이
HTTP 헤더에 UTF-8 바이트로 박혀서 ntfy 서버가 latin-1로 해석 → 제목 깨짐(mojibake).
또한 비ASCII 본문은 ntfy가 통째로 'attachment.txt'로 강등시켜 알림 자체가
"You received a file"만 표시되는 문제 발생.
수정 방식: ntfy의 JSON publish API POST https://ntfy.sh/)로 전환.
이건 UTF-8 본문/제목/태그를 정상 처리한다.
"""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

NTFY_URL = "https://ntfy.sh"
TOPIC = os.getenv("NTFY_TOPIC")


def send(
    message: str,
    title: str = "주식 알림",
    priority: int = 3,
    tags: list[str] | None = None,
    click_url: str | None = None,
) -> bool:
    """
    ntfy 푸시 발송 (JSON publish API).
    priority: 1(min) ~ 5(max). 🔴긴급=5, 🟡참고=4, 🟢뉴스=3
    tags: 알림 아이콘 (예: ["chart_with_upwards_trend"])
    """
    if not TOPIC:
        print("[ntfy] NTFY_TOPIC 환경변수가 없습니다")
        return False

    payload: dict = {
        "topic": TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if tags:
        payload["tags"] = list(tags)
    if click_url:
        payload["click"] = click_url

    try:
        # JSON 본문을 UTF-8 바이트로 명시 직렬화 (Windows 환경 안전)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        r = requests.post(
            NTFY_URL,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ntfy] 발송 실패: {e}")
        return False


if __name__ == "__main__":
    ok = send(
        "주식 AI 알림 시스템이 연결되었습니다 ✅\n한국어·이모지 정상 표시 확인.",
        title="🌅 연결 테스트",
        priority=3,
        tags=["white_check_mark"],
    )
    print("전송 성공!" if ok else "전송 실패")
