"""NailFit API 入口。

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

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


@app.get("/")
def root() -> dict:
    return {"name": "NailFit", "docs": "/docs", "health": "/api/health"}
