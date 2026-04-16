"""Vercel serverless 진입점. FastAPI 앱을 그대로 노출."""
import sys
from pathlib import Path

# src/ 경로를 sys.path에 추가 (Vercel에선 api/index.py가 루트에서 실행됨)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.api.app import app  # noqa: E402,F401
