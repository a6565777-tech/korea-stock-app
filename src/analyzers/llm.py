"""LLM 래퍼 - 새 google-genai SDK 사용. 추후 Claude로 교체 가능."""
import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_API_KEY) if _API_KEY else None

# 폴백 체인: 하나가 503/과부하이면 다음 모델로 재시도
_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
]


def ask(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str:
    """Gemini에게 질문하고 텍스트 응답 반환. 503/과부하 시 폴백 모델 시도."""
    if not _client:
        raise RuntimeError("GEMINI_API_KEY 가 .env에 없습니다")

    models = [model] if model else _FALLBACK_MODELS
    last_error: Exception | None = None

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
                last_error = e
                msg = str(e)
                # 503/과부하는 재시도, 그 외 에러는 다음 모델로
                if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                break  # 다음 모델 시도

    raise RuntimeError(f"모든 Gemini 모델 실패: {last_error}")


if __name__ == "__main__":
    answer = ask(
        "너는 한국 주식 전문 분석가야. '안녕'이라고 짧게 인사하고, "
        "오늘 날짜를 모르니 모른다고 말해줘."
    )
    print("Gemini 응답:")
    print(answer)
