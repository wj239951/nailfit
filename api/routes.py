from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.data import load_styles, load_taxonomy
from core.features import FeatureError, HandFeatures
from core.pipeline import recommend
from core.validator import ContractError

from .schemas import RecommendRequest, RecommendResponse

router = APIRouter(prefix="/api", tags=["nailfit"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "nailfit"}


@router.get("/taxonomy")
def taxonomy() -> dict:
    return load_taxonomy()


@router.get("/styles")
def list_styles() -> dict:
    styles = load_styles()
    return {"count": len(styles), "styles": list(styles)}


@router.post("/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest) -> dict:
    try:
        features = HandFeatures.from_dict(req.features)
    except FeatureError as exc:
        raise HTTPException(status_code=422, detail=f"特征非法: {exc}") from exc

    try:
        return recommend(features, free_text=req.free_text, use_llm=req.use_llm)
    except ContractError as exc:
        # 输出契约失败：说明模型编了款式或理由不合规
        raise HTTPException(status_code=502, detail=f"推荐结果校验失败: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
