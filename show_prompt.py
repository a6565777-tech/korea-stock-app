"""실제로 Gemini에 보내는 전체 프롬프트를 파일로 덤프 (호출 없이)"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.analyzers.briefing import SYSTEM_PROMPT, build_context
from src.config import load

cfg = load()
ctx = build_context(cfg)
full = SYSTEM_PROMPT + "\n\n# 컨텍스트\n" + ctx

print(full)

# 파일로도 저장
with open("logs/last_prompt.txt", "w", encoding="utf-8") as f:
    f.write(full)
print("\n\n>> logs/last_prompt.txt 에 저장됨")
