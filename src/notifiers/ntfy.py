"""ntfy.sh 푸시 알림 모듈"""
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
    ntfy 푸시 발송.
    priority: 1(min) ~ 5(max). 🔴긴급=5, 🟡참고=4, 🟢뉴스=3
    tags: 알림 아이콘 (예: ["chart_with_upwards_trend"])
    """
    if not TOPIC:
        print("[ntfy] NTFY_TOPIC 환경변수가 없습니다")
        return False

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": str(priority),
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    if click_url:
        headers["Click"] = click_url

    try:
        r = requests.post(
            f"{NTFY_URL}/{TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ntfy] 발송 실패: {e}")
        return False


if __name__ == "__main__":
    ok = send(
        "주식 AI 알림 시스템이 연결되었습니다 ✅",
        title="연결 테스트",
        priority=3,
        tags=["white_check_mark"],
    )
    print("전송 성공!" if ok else "전송 실패")
