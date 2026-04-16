"""
연결 테스트 스크립트.

1) Gemini API 응답 확인
2) ntfy 푸시 발송 확인

실행: python test_connection.py
"""
import sys
# Windows 콘솔에서 유니코드/이모지 출력 강제
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.analyzers.llm import ask
from src.notifiers.ntfy import send


def test_gemini():
    print("=" * 50)
    print("[1] Gemini API 테스트")
    print("=" * 50)
    try:
        answer = ask("안녕! 너는 한국 주식 분석 보조야. 한 문장으로 인사해줘.")
        print(f"[OK] Gemini 응답:\n{answer}\n")
        return True
    except Exception as e:
        print(f"[FAIL] Gemini 실패: {e}\n")
        return False


def test_ntfy():
    print("=" * 50)
    print("[2] ntfy 푸시 테스트")
    print("=" * 50)
    ok = send(
        "연결 테스트 성공! 이 메시지가 보이면 알림 시스템이 정상입니다.",
        title="주식 AI 알림 - 설치 테스트",
        priority=4,
        tags=["white_check_mark", "chart_with_upwards_trend"],
    )
    if ok:
        print("[OK] 푸시 발송 성공. 핸드폰 확인!\n")
    else:
        print("[FAIL] 푸시 발송 실패\n")
    return ok


if __name__ == "__main__":
    g = test_gemini()
    n = test_ntfy()
    print("=" * 50)
    if g and n:
        print("모든 연결 OK! 다음 단계로 갈 수 있습니다.")
    else:
        print("위 에러를 먼저 해결해주세요.")
