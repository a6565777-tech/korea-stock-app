"""Vercel serverless 진입점. FastAPI 앱을 그대로 노출.

import 실패 시 최소 FastAPI 앱으로 폴백해 디버그 정보 반환.
"""
import sys
import traceback
from pathlib import Path

# src/ 경로를 sys.path에 추가 (Vercel에선 api/index.py가 루트에서 실행됨)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from src.api.app import app  # noqa: E402,F401
except Exception as _e:
    _err_tb = traceback.format_exc()
    _err_msg = str(_e)
    from fastapi import FastAPI

    app = FastAPI(title="Import Failed (debug fallback)")

    @app.get("/api/health")
    def _health():
        return {"ok": False, "error": _err_msg, "traceback": _err_tb.splitlines()[-20:]}

    @app.get("/{path:path}")
    def _catch(path: str):
        return {
            "ok": False,
            "import_failed": True,
            "error": _err_msg,
            "traceback": _err_tb.splitlines()[-30:],
            "sys_path": sys.path[:5],
            "cwd_exists_src": (_ROOT / "src").exists(),
            "cwd_exists_config": (_ROOT / "config.yaml").exists(),
        }
