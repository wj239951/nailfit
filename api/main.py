"""NailFit API 入口。

    uvicorn api.main:app --reload --port 8000

前端（Streamlit / Vue）用到的款式图片位于 `static/`，通过 `/static/*` 直接提供。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(
    title="NailFit API",
    version="0.1.0",
    description="Hand-aware nail style recommendation：规则决定推荐什么，模型决定怎么说。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> dict:
    return {"name": "NailFit", "docs": "/docs", "health": "/api/health", "static": "/static/styles/"}
