"""LLM 래퍼 - 새 google-genai SDK 사용. 추후 Claude로 교체 가능."""
import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_API_KEY) if _API_KEY else None

# [2026-04 업데이트] tier 별 폴백 체인.
#   pro      : '전문가 분석' — Pro 모델 전용 (Flash 폴백 없음, 실패 시 명확히 사용 불가)
#   standard : '일반 분석' — Flash 모델 (무료 또는 저비용)
#   flash    : standard 의 alias (하위 호환)
# Pro 는 2026-04-01 부터 유료 전용. 무료 키로는 항상 QuotaExhaustedError 가 떠서
# 프론트엔드가 "전문가 분석을 지금 사용할 수 없습니다" 라고 사용자에게 깔끔히 안내 가능.
_FALLBACK_PRO = [
    "gemini-3.1-pro",            # 최신 플래그쉛
    "gemini-2.5-pro",            # 차상위
]
_FALLBACK_STANDARD = [
    "gemini-flash-latest",       # 자동 최신 alias (무료)
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]
_FALLBACK_FLASH = _FALLBACK_STANDARD  # 하위 호환 (이전 버전 alias)
_FALLBACK_MODELS = _FALLBACK_STANDARD  # 하위 호환 (기존 호출자)


class QuotaExhaustedError(RuntimeError):
    """모든 모델에서 429 쿼터 소진. 사용자에게 별도 안내 가능."""
    pass


def ask(
    prompt: str,
    model: str | None = None,
    tier: str = "standard",
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str:
    """Gemini에게 질문하고 텍스트 응답 반환.

    tier="pro"      → '전문가 분석'. Pro 모델 전용. 실패 시 QuotaExhaustedError
                      (Flash 자동 폴백 안 함 — 프론트가 명시적으로 사용자에게 안내).
    tier="standard" → '일반 분석'. Flash 체인 (무료/저비용).
    tier="flash"    → standard 의 alias (하위 호환).
    model 인자가 명시되면 tier 무시하고 그 모델만 시도.

    폴백 체인을 순회하며 시도. 503/과부하는 지수 백오프 재시도, 그 외 에러는
    즉시 다음 모델. 모든 모델이 429이면 QuotaExhaustedError.
    """
    if not _client:
        raise RuntimeError("GEMINI_API_KEY 가 .env에 없습니다")

    if model:
        models = [model]
    elif tier == "pro":
        models = _FALLBACK_PRO
    else:  # standard / flash / 기타
        models = _FALLBACK_STANDARD

    per_model_errors: dict[str, str] = {}
    all_quota = True

    for m in models:
        for attempt in range(max_retries):
            try:
                resp = _client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature),
                )
                return (resp.text or "").strip()
            except Exception as e:
                msg = str(e)
                per_model_errors[m] = msg[:300]
                # 503/과부하는 같은 모델로 재시도
                if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                # 429(쿼터)가 아닌 에러가 하나라도 있으면 플래그 해제
                if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
                    all_quota = False
                break  # 다음 모델로

    # 에러 요약 (모델별 짧게)
    summary = " | ".join(f"{m}: {err[:120]}" for m, err in per_model_errors.items())
    # tier="pro" 는 결제 미연결(PERMISSION_DENIED)이든 쿼터 소진(429)이든
    # 사용자 입장엔 똑같이 "전문가 분석 사용 불가". 일관된 예외로 통일.
    if tier == "pro" and per_model_errors:
        raise QuotaExhaustedError(
            f"전문가 분석(Pro) 사용 불가. 결제 연결 또는 사용량 한도 확인 필요. 상세: {summary}"
        )
    if all_quota and per_model_errors:
        raise QuotaExhaustedError(
            "Gemini 쿼터 소진(모든 폴백 모델 429). "
            "Google AI Studio에서 결제 연결 또는 1~2시간 후 재시도. "
            f"상세: {summary}"
        )
    raise RuntimeError(f"모든 모델 실패: {summary}")


if __name__ == "__main__":
    answer = ask(
        "너는 한국 주식 전문 분석가야. '안녕'이라고 짧게 인사하고, "
        "오늘 날짜를 모르니 모른다고 말해줘."
    )
    print("Gemini 응답:")
    print(answer)
