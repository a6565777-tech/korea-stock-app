"""Vercel serverless 진입점 — 단계적 진단 모드.

현재 목표: 왜 FUNCTION_INVOCATION_FAILED 나는지 격리.
"""
import sys
import os
import traceback
from pathlib import Path

from fastapi import FastAPI

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

app = FastAPI(title="Korea Stock API (diag)")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "minimal"}


@app.get("/api/diag")
def diag():
    info = {
        "python": sys.version,
        "cwd": os.getcwd(),
        "root": str(_ROOT),
        "root_exists": _ROOT.exists(),
        "src_exists": (_ROOT / "src").exists(),
        "config_exists": (_ROOT / "config.yaml").exists(),
        "positions_exists": (_ROOT / "positions.yaml").exists(),
        "listdir_root": sorted(os.listdir(_ROOT))[:30] if _ROOT.exists() else [],
        "env_keys": sorted([k for k in os.environ if not k.startswith("_")])[:50],
    }
    # 하나씩 import 테스트
    tests = {}
    for name in ["yaml", "requests", "yfinance", "google.genai", "fastapi", "pydantic"]:
        try:
            __import__(name)
            tests[name] = "ok"
        except Exception as e:
            tests[name] = f"FAIL: {e}"
    info["imports"] = tests

    # src 모듈 하나씩 import 테스트
    src_tests = {}
    for modname in [
        "src.config",
        "src.storage.positions_store",
        "src.storage.briefing_cache",
        "src.collectors.price",
        "src.analyzers.llm",
        "src.api.app",
    ]:
        try:
            __import__(modname)
            src_tests[modname] = "ok"
        except Exception as e:
            src_tests[modname] = f"FAIL: {type(e).__name__}: {e}"
    info["src_imports"] = src_tests
    return info


@app.get("/api/load-app")
def load_app():
    """실제 앱 로딩 시도."""
    try:
        from src.api.app import app as real_app  # noqa: F401
        return {"ok": True, "routes": [r.path for r in real_app.routes][:30]}
    except Exception as e:
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc().splitlines()[-20:]}
