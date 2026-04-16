"""LLM 래퍼 - 새 google-genai SDK 사용. 추후 Claude로 교체 가능."""
import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_API_KEY) if _API_KEY else None

# 폴백 체인: latest alias를 최우선으로 (무료 티어 쿼터 이슈 회피)
# 하나가 실패하면 다음 모델로 순차 재시도
_FALLBACK_MODELS = [
    "gemini-flash-latest",       # 구글이 자동으로 최신 무료 flash 모델 연결
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


class QuotaExhaustedError(RuntimeError):
    """모든 모델에서 429 쿼터 소진. 사용자에게 별도 안내 가능."""
    pass


def ask(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str:
    """Gemini에게 질문하고 텍스트 응답 반환.

    폴백 체인을 순회하며 시도. 503/과부하는 지수 백오프 재시도, 그 외 에러는
    즉시 다음 모델. 모든 모델이 429이면 QuotaExhaustedError.
    """
    if not _client:
        raise RuntimeError("GEMINI_API_KEY 가 .env에 없습니다")

    models = [model] if model else _FALLBACK_MODELS
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
    if all_quota and per_model_errors:
        raise QuotaExhaustedError(
            "Gemini 무료 티어 쿼터 소진(모든 폴백 모델 429). "
            "Google AI Studio에서 결제 연결 또는 1~2시간 후 재시도. "
            f"상세: {summary}"
        )
    raise RuntimeError(f"모든 Gemini 모델 실패: {summary}")


if __name__ == "__main__":
    answer = ask(
        "너는 한국 주식 전문 분석가야. '안녕'이라고 짧게 인사하고, "
        "오늘 날짜를 모르니 모른다고 말해줘."
    )
    print("Gemini 응답:")
    print(answer)
