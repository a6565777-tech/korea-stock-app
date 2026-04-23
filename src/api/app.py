"""FastAPI 메인.

로컬: uvicorn src.api.app:app --reload --port 8000
Vercel: api/index.py에서 임포트
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from src.api.routes import positions as positions_routes
from src.api.routes import predict as predict_routes
from src.api.routes import briefing as briefing_routes
from src.api.routes import watchlist as watchlist_routes
from src.api.routes import accuracy as accuracy_routes

app = FastAPI(title="Korea Stock Alert API", version="0.1.0")

# PWA/APK가 다른 도메인에서 호출할 수 있게
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions_routes.router, prefix="/api/positions", tags=["positions"])
app.include_router(predict_routes.router, prefix="/api/predict", tags=["predict"])
app.include_router(briefing_routes.router, prefix="/api/briefing", tags=["briefing"])
app.include_router(watchlist_routes.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(accuracy_routes.router, prefix="/api/accuracy", tags=["accuracy"])


@app.get("/api/health")
def health():
    return {"ok": True}


# 정적 파일 (PWA 프론트엔드) 서빙
_WEB_DIR = Path(__file__).parent.parent.parent / "web"
if _WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
